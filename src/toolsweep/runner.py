"""The sweep: build arms, run the grid, score, and compute effects.

Arm zero is always the unmodified catalogue. Every factor level is compared against it,
paired by item, on the same items - so one control run serves the whole sweep and no
factor is ever compared against a different baseline than its neighbour.

Three things this module refuses to do:

* **Report an effect without a control.** Arm zero is constructed before any factor is
  read and cannot be switched off.
* **Score an arm that dropped the answer.** Before any call is made, every arm is checked
  to still contain every tool the suite expects. ``catalogue.size`` pins them; this
  verifies it rather than trusting it.
* **Spend calls on an arm that changed nothing.** A level whose catalogue is identical to
  the control is marked *inert* and skipped. Its result is "this factor does not apply to
  this catalogue", which is a different statement from "we measured no effect", and the
  report says which.
"""

from __future__ import annotations

import json
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import cxs
from .adapters import openai as openai_adapter
from .cache import ResponseCache
from .catalogue import Catalogue
from .factors import FactorContext, parse_specs
from .factors.base import Factor
from .providers.base import Provider, Request, Response
from .score import (
    ArmMetrics,
    ItemScore,
    ToolCall,
    aggregate,
    confusion_counts,
    per_item_accuracy,
    score_call,
)
from .stats import Effect, apply_holm, compute_effect, mde, paired_differences
from .suite import Suite, validate_against

CONTROL_ARM_ID = "control"
SCORER = "tool_selection_exact:v1"


@dataclass(frozen=True)
class Arm:
    """One experimental condition: a catalogue, and how it came to be."""

    id: str
    factor_id: str
    level: str
    catalogue: Catalogue
    kind: str
    description: str
    implementation: str
    inert: bool = False

    @property
    def is_control(self) -> bool:
        return self.id == CONTROL_ARM_ID


@dataclass(frozen=True)
class SweepConfig:
    catalogue: Catalogue
    suite: Suite
    factor_specs: tuple[str, ...]
    repeats: int = 5
    seed: int = 7
    resamples: int = 10_000
    confidence: float = 0.95
    max_calls: int | None = None
    system: str = ""
    notes: str = ""
    dataset_name: str = ""
    dataset_sha256: str = ""
    catalogue_format: str = ""


@dataclass
class SweepResult:
    experiment_id: str
    arms: tuple[Arm, ...]
    metrics: dict[str, ArmMetrics]
    effects: tuple[Effect, ...]
    mde: float
    confusion: dict[tuple[str, str], int]
    unavailable: tuple[tuple[str, str], ...] = ()
    scores: dict[str, list[ItemScore]] = field(default_factory=dict)
    calls_made: int = 0
    replayed_trials: int = 0
    cache_hits: int = 0
    resumed_trials: int = 0
    truncated: bool = False
    determinism: str = "stochastic"
    totals: dict[str, int] = field(default_factory=dict)
    paths: cxs.RunPaths | None = None

    @property
    def control_metrics(self) -> ArmMetrics:
        return self.metrics[CONTROL_ARM_ID]

    @property
    def inert_arms(self) -> tuple[Arm, ...]:
        return tuple(a for a in self.arms if a.inert)


# --------------------------------------------------------------------------------------
# Arm construction
# --------------------------------------------------------------------------------------


def build_arms(config: SweepConfig) -> tuple[Arm, ...]:
    """Arm zero first, then every requested factor level."""
    validate_against(config.suite, config.catalogue)

    ctx = FactorContext(
        catalogue=config.catalogue,
        pinned_tools=config.suite.expected_tools,
        seed=config.seed,
    )
    control = Arm(
        id=CONTROL_ARM_ID,
        factor_id=CONTROL_ARM_ID,
        level="as_authored",
        catalogue=config.catalogue,
        kind="noop",
        description="The catalogue exactly as authored. Arm zero.",
        implementation="toolsweep.runner:control:v1",
    )

    arms: list[Arm] = [control]
    for factor, levels in parse_specs(config.factor_specs, ctx):
        for level in levels:
            arms.append(_build_arm(factor, level, config))
    _check_expected_tools_present(arms, config.suite)
    return tuple(arms)


def unavailable_factors(config: SweepConfig) -> tuple[tuple[str, str], ...]:
    """Requested factors that have nothing to vary here, with the reason why.

    Reported rather than dropped. A factor that silently disappears from a table reads as
    "measured, no effect", which is a claim toolsweep has not earned.
    """
    ctx = FactorContext(
        catalogue=config.catalogue,
        pinned_tools=config.suite.expected_tools,
        seed=config.seed,
    )
    out: list[tuple[str, str]] = []
    for factor, levels in parse_specs(config.factor_specs, ctx):
        if levels:
            continue
        reason = factor.unavailable_reason or "no levels available"
        out.append((factor.id, reason))
    return tuple(out)


def _build_arm(factor: Factor, level: str, config: SweepConfig) -> Arm:
    transformed = factor.apply(level, config.catalogue)
    return Arm(
        id=f"{factor.id}={level}",
        factor_id=factor.id,
        level=level,
        catalogue=transformed,
        kind=factor.cxs_kind,
        description=factor.describe(level),
        implementation=factor.implementation,
        inert=transformed == config.catalogue,
    )


def _check_expected_tools_present(arms: Sequence[Arm], suite: Suite) -> None:
    for arm in arms:
        missing = sorted(t for t in suite.expected_tools if arm.catalogue.resolve_tool(t) is None)
        if missing:
            raise ValueError(
                f"arm {arm.id!r} dropped tools the suite expects: {missing}. "
                f"No factor may remove a tool the suite asks for; results would be zero "
                f"for a reason unrelated to the factor."
            )


# --------------------------------------------------------------------------------------
# Dry run
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class DryRun:
    arms: tuple[Arm, ...]
    live_arms: int
    inert_arms: int
    n_items: int
    repeats: int
    grid_size: int
    cached: int
    calls_needed: int
    estimated_prompt_tokens: int
    unavailable: tuple[tuple[str, str], ...] = ()


def plan(config: SweepConfig, provider: Provider, cache: ResponseCache) -> DryRun:
    """Count what a sweep would cost before spending anything."""
    arms = build_arms(config)
    live = [a for a in arms if not a.inert]
    descriptor = provider.descriptor

    cached = 0
    tokens = 0
    for arm in live:
        for item in config.suite.items:
            for repeat in range(config.repeats):
                request = Request(
                    prompt=item.prompt,
                    catalogue=arm.catalogue,
                    repeat_index=repeat,
                    system=config.system,
                )
                if cache.get(request.key(descriptor)) is not None:
                    cached += 1
                else:
                    tokens += _estimate_prompt_tokens(request)

    grid = len(live) * len(config.suite) * config.repeats
    return DryRun(
        arms=arms,
        live_arms=len(live),
        inert_arms=len(arms) - len(live),
        n_items=len(config.suite),
        repeats=config.repeats,
        grid_size=grid,
        cached=cached,
        calls_needed=grid - cached,
        estimated_prompt_tokens=tokens,
        unavailable=unavailable_factors(config),
    )


def _estimate_prompt_tokens(request: Request) -> int:
    blob = json.dumps(openai_adapter.dump(request.catalogue), separators=(",", ":"))
    return (len(blob) + len(request.prompt) + len(request.system)) // 4


# --------------------------------------------------------------------------------------
# Execution
# --------------------------------------------------------------------------------------


def run(
    config: SweepConfig,
    provider: Provider,
    cache: ResponseCache,
    *,
    out_dir: Path,
    experiment_id: str | None = None,
    version: str = "0.0.0",
) -> SweepResult:
    """Execute the grid and write a complete CXS run directory."""
    arms = build_arms(config)
    rng = random.Random(config.seed)
    exp_id = experiment_id or cxs.new_experiment_id(rng)
    paths = cxs.RunPaths(out_dir / exp_id)
    paths.ensure()

    descriptor = provider.descriptor
    created_at = cxs.now_iso()

    interventions = [
        cxs.intervention_record(
            intervention_id=arm.id,
            kind=arm.kind,
            factor_id=arm.factor_id,
            level=arm.level,
            description=arm.description,
            implementation=arm.implementation,
        )
        for arm in arms
    ]
    cxs.write_json(paths.interventions, interventions)

    # Resume: trials already on disk are re-scored rather than re-called. Because
    # Outcome is a separate record from Trial, re-scoring an existing run is free and
    # touches no model at all.
    done = _existing_trials(paths)
    scores: dict[str, list[ItemScore]] = {arm.id: [] for arm in arms}
    responses_by_arm_item: dict[tuple[str, str], list[str]] = {}
    calls_made = 0
    replayed = 0
    resumed = 0
    truncated = False
    totals = {"model_calls": 0, "prompt_tokens": 0, "completion_tokens": 0}

    with cxs.JsonlWriter(paths.trials) as trials, cxs.JsonlWriter(paths.outcomes) as outcomes:
        for arm in arms:
            if arm.inert:
                continue
            for item in config.suite.items:
                for repeat in range(config.repeats):
                    request = Request(
                        prompt=item.prompt,
                        catalogue=arm.catalogue,
                        repeat_index=repeat,
                        system=config.system,
                    )
                    key = request.key(descriptor)
                    trial_id = f"{exp_id}-{arm.id}-{item.id}-{repeat}"

                    previous = done.get((arm.id, item.id, repeat))
                    if previous is not None:
                        resumed += 1
                        score = score_call(item, arm.catalogue, previous.tool_call)
                        scores[arm.id].append(score)
                        responses_by_arm_item.setdefault((arm.id, item.id), []).append(
                            _response_fingerprint(previous)
                        )
                        continue

                    cached = cache.get(key)
                    if cached is None:
                        if config.max_calls is not None and calls_made >= config.max_calls:
                            truncated = True
                            break
                        response = provider.complete(request)
                        cache.put(key, response)
                        calls_made += 1
                        # A cassette answers without touching a model. Counting a replay
                        # as a model call would report a run as costing something it did
                        # not, and would make the manifest's totals a fiction.
                        if response.cached:
                            replayed += 1
                        else:
                            totals["model_calls"] += 1
                    else:
                        response = cached

                    totals["prompt_tokens"] += int(response.usage.get("prompt_tokens", 0))
                    totals["completion_tokens"] += int(response.usage.get("completion_tokens", 0))

                    score = score_call(item, arm.catalogue, response.tool_call)
                    scores[arm.id].append(score)
                    responses_by_arm_item.setdefault((arm.id, item.id), []).append(
                        _response_fingerprint(response)
                    )

                    trials.write(
                        {
                            "trial_id": trial_id,
                            "experiment_id": exp_id,
                            "intervention_id": arm.id,
                            "item_id": item.id,
                            "repeat_index": repeat,
                            "model": descriptor.to_cxs(created_at),
                            "prompt_sha256": key,
                            "response_text": response.text,
                            "tool_call": (
                                None
                                if response.tool_call is None
                                else {
                                    "name": response.tool_call.name,
                                    "arguments": dict(response.tool_call.arguments),
                                }
                            ),
                            "cached": cached is not None,
                            "latency_ms": response.latency_ms,
                            "usage": dict(response.usage),
                            "error": response.error,
                            "observed_at": cxs.now_iso(),
                        }
                    )
                    outcomes.write(
                        {
                            "trial_id": trial_id,
                            "scorer": SCORER,
                            "score": score.score,
                            "passed": score.correct,
                            "detail": score.detail,
                        }
                    )
                if truncated:
                    break
            if truncated:
                break

    metrics = {arm.id: aggregate(scores[arm.id]) for arm in arms}
    effects, minimum_detectable = _effects(config, arms, scores)
    determinism = cxs.determinism_of(
        temperature=_temperature(descriptor.params),
        identical_across_repeats=all(
            len(set(texts)) == 1 for texts in responses_by_arm_item.values()
        ),
        repeats=config.repeats,
    )

    result = SweepResult(
        experiment_id=exp_id,
        arms=arms,
        metrics=metrics,
        effects=effects,
        mde=minimum_detectable,
        confusion=confusion_counts(scores[CONTROL_ARM_ID]),
        unavailable=unavailable_factors(config),
        scores=scores,
        calls_made=calls_made,
        replayed_trials=replayed,
        cache_hits=cache.hits,
        resumed_trials=resumed,
        truncated=truncated,
        determinism=determinism,
        totals=totals,
        paths=paths,
    )

    cxs.write_json(
        paths.manifest,
        cxs.manifest_record(
            experiment_id=exp_id,
            tool_version=version,
            created_at=created_at,
            models=[descriptor.to_cxs(created_at)],
            interventions=interventions,
            dataset={
                "name": config.dataset_name or config.suite.source or "suite",
                "sha256": config.dataset_sha256,
                "n_items": len(config.suite),
                "source": config.suite.source,
            },
            scorer=SCORER,
            repeats=config.repeats,
            seed=config.seed,
            determinism=determinism,
            cache={"hits": cache.hits, "misses": cache.misses},
            totals=totals,
            notes=config.notes + (" Run truncated by --max-calls." if truncated else ""),
        ),
    )
    return result


def _effects(
    config: SweepConfig, arms: Sequence[Arm], scores: Mapping[str, Sequence[ItemScore]]
) -> tuple[tuple[Effect, ...], float]:
    control = per_item_accuracy(scores[CONTROL_ARM_ID])
    if not control:
        return (), float("inf")

    computed: list[Effect] = []
    worst_mde = 0.0
    for arm in arms:
        if arm.is_control or arm.inert or not scores[arm.id]:
            continue
        arm_accuracy = per_item_accuracy(scores[arm.id])
        effect = compute_effect(
            arm.id,
            arm_accuracy,
            control,
            repeats=config.repeats,
            resamples=config.resamples,
            confidence=config.confidence,
            seed=config.seed,
        )
        computed.append(effect)
        _, diffs = paired_differences(arm_accuracy, control)
        worst_mde = max(worst_mde, mde(diffs, confidence=config.confidence))

    return apply_holm(computed), worst_mde


def _existing_trials(paths: cxs.RunPaths) -> dict[tuple[str, str, int], Response]:
    """Trials already on disk, so a resumed run does not repeat completed work.

    ``trials.jsonl`` is append-only, so this reads the raw record of what the model
    actually returned - not a summary of it - and the resumed run re-scores it from
    scratch.
    """
    out: dict[tuple[str, str, int], Response] = {}
    for record in cxs.read_jsonl(paths.trials):
        key = (
            str(record.get("intervention_id")),
            str(record.get("item_id")),
            int(record.get("repeat_index", 0)),
        )
        raw_call = record.get("tool_call")
        call: ToolCall | None = None
        if isinstance(raw_call, dict):
            arguments = raw_call.get("arguments", {})
            call = ToolCall(
                name=str(raw_call.get("name", "")),
                arguments=arguments if isinstance(arguments, dict) else {},
            )
        usage = record.get("usage", {})
        out[key] = Response(
            text=str(record.get("response_text", "")),
            tool_call=call,
            latency_ms=int(record.get("latency_ms", 0)),
            usage=usage if isinstance(usage, dict) else {},
            cached=True,
            error=record.get("error"),
        )
    return out


def _response_fingerprint(response: Response) -> str:
    """What "the same answer twice" means, for the determinism check.

    Covers the structured tool call as well as the text. A provider that returns an
    empty string beside a varying call would otherwise look perfectly repeatable and
    earn a `deterministic` label the run never demonstrated.
    """
    call = response.tool_call
    payload = {
        "text": response.text,
        "call": None if call is None else [call.name, dict(call.arguments)],
    }
    return json.dumps(payload, sort_keys=True, default=str)


def _temperature(params: Mapping[str, Any]) -> float | None:
    value = params.get("temperature")
    return float(value) if isinstance(value, (int, float)) else None
