"""Rendering a sweep into a table, a markdown report and a JSON report.

The one rule this module exists to enforce: **no effect is printed without its interval.**
That is guaranteed structurally rather than by discipline - the row formatter takes an
:class:`~toolsweep.stats.Effect`, whose CI fields have no defaults, so there is no way to
construct a row for an effect nobody bootstrapped. ``tests/test_report.py`` asserts every
non-control row of the rendered table carries a bracketed interval.

The control arm is always the first row. Inert arms are listed separately, under their own
heading, because "this factor does not apply to your catalogue" and "we measured no
effect" are different statements and collapsing them would be the dishonest choice.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .runner import CONTROL_ARM_ID, Arm, SweepResult
from .score import ArmMetrics
from .stats import Effect

HEADER = (
    f"{'FACTOR':<26}{'level':<20}{'accuracy':>10}{'Δ vs control':>16}{'95% CI':>20}{'p(Holm)':>10}"
)


def render_table(result: SweepResult) -> str:
    """The headline table. Every number computed at runtime; nothing is hardcoded."""
    lines = [HEADER, "-" * len(HEADER)]
    control = result.metrics[CONTROL_ARM_ID]
    lines.append(
        f"{'control':<26}{'as-authored':<20}{_pct(control.accuracy):>10}{'-':>16}{'-':>20}{'-':>10}"
    )

    by_id = {e.label: e for e in result.effects}
    for arm in result.arms:
        if arm.is_control or arm.inert:
            continue
        effect = by_id.get(arm.id)
        if effect is None:
            continue
        lines.append(_effect_row(arm, result.metrics[arm.id], effect))

    lines.extend(_confusion_block(result))
    lines.extend(_inert_block(result))
    lines.extend(_unavailable_block(result))
    lines.append("")
    lines.append(_footer(result))
    if result.truncated:
        lines.append("RUN TRUNCATED by --max-calls: the numbers above cover part of the grid.")
    return "\n".join(lines)


def _effect_row(arm: Arm, metrics: ArmMetrics, effect: Effect) -> str:
    lo, hi = effect.ci_pp
    ci = f"[{lo:+.1f}, {hi:+.1f}]"
    p = "<0.001" if effect.p_holm < 0.001 else f"{effect.p_holm:.3f}"
    return (
        f"{arm.factor_id:<26}{arm.level:<20}{_pct(metrics.accuracy):>10}"
        f"{effect.delta_pp:>+14.1f}pp{ci:>20}{p:>10}"
    )


def _confusion_block(result: SweepResult) -> list[str]:
    top = top_confusions(result.confusion, limit=5)
    if not top:
        return ["", "TOP CONFUSIONS (control arm)", "  none: every control trial chose correctly"]
    total = sum(result.confusion.values()) or 1
    lines = ["", "TOP CONFUSIONS (control arm)"]
    denominator = result.metrics[CONTROL_ARM_ID].n_trials or total
    for (expected, got), count in top:
        share = count / denominator
        lines.append(f"  {expected:<24}→ {got:<24}{share * 100:>5.1f}%")
    return lines


def _inert_block(result: SweepResult) -> list[str]:
    inert = result.inert_arms
    if not inert:
        return []
    lines = ["", "INERT ON THIS CATALOGUE (not run, no calls spent)"]
    for arm in inert:
        lines.append(
            f"  {arm.factor_id}={arm.level}: produced a catalogue identical to the control"
        )
    return lines


def _unavailable_block(result: SweepResult) -> list[str]:
    if not result.unavailable:
        return []
    lines = ["", "NOT MEASURABLE HERE (no level differs from the control)"]
    for factor_id, reason in result.unavailable:
        lines.append(f"  {factor_id}: {reason}")
    return lines


def _footer(result: SweepResult) -> str:
    control = result.metrics[CONTROL_ARM_ID]
    trials = result.calls_made + result.cache_hits + result.resumed_trials
    # The worst arm's MDE, not the best: a single figure quoted next to a table of arms
    # has to be the one that does not overstate what the run could have detected.
    mde_text = "n/a" if result.mde == float("inf") else f"{result.mde * 100:.1f}pp"

    # Only non-zero components, and replays are never called model calls.
    parts = [(result.calls_made - result.replayed_trials, "live model calls")]
    parts += [
        (result.replayed_trials, "replayed from cassette"),
        (result.cache_hits, "from cache"),
        (result.resumed_trials, "resumed"),
    ]
    breakdown = ", ".join(f"{count:,} {label}" for count, label in parts if count)
    return (
        f"{control.n_items} items · {result.effects[0].repeats if result.effects else 0} repeats"
        f" · {trials:,} trials ({breakdown or 'nothing run'})"
        f" · MDE ≤{mde_text} (worst arm) · {result.determinism}"
    )


def top_confusions(
    counts: Mapping[tuple[str, str], int], *, limit: int = 5
) -> list[tuple[tuple[str, str], int]]:
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]


def render_confusion(result: SweepResult, *, arm_id: str = CONTROL_ARM_ID) -> str:
    """The confusion matrix on its own, for ``toolsweep confusion``."""
    scores = result.scores.get(arm_id, [])
    if not scores:
        return f"no scored trials for arm {arm_id!r}"
    from .score import confusion_counts

    counts = confusion_counts(scores)
    if not counts:
        return f"arm {arm_id!r}: every trial chose the expected tool"

    total = len(scores)
    width = max(len(e) for e, _ in counts) + 2
    lines = [
        f"CONFUSION MATRIX: arm {arm_id!r} ({total} trials, names in as-authored space)",
        "",
        f"  {'expected':<{width}}{'got':<{width}}{'count':>7}{'share':>9}",
    ]
    for (expected, got), count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"  {expected:<{width}}{got:<{width}}{count:>7}{count / total * 100:>8.1f}%")
    return "\n".join(lines)


# --------------------------------------------------------------------------------------
# Serialised reports
# --------------------------------------------------------------------------------------


def report_json(result: SweepResult) -> dict[str, Any]:
    control = result.metrics[CONTROL_ARM_ID]
    return {
        "experiment_id": result.experiment_id,
        "scorer": "tool_selection_exact:v1",
        "determinism": result.determinism,
        "truncated": result.truncated,
        "n_items": control.n_items,
        "repeats": result.effects[0].repeats if result.effects else 0,
        "mde": None if result.mde == float("inf") else result.mde,
        "control": _metrics_json(control),
        "arms": [
            {
                "id": arm.id,
                "factor": arm.factor_id,
                "level": arm.level,
                "inert": arm.inert,
                "description": arm.description,
                "metrics": None if arm.inert else _metrics_json(result.metrics[arm.id]),
                "effect": _effect_json(result, arm.id),
            }
            for arm in result.arms
            if not arm.is_control
        ],
        "confusion": [
            {"expected": expected, "got": got, "count": count}
            for (expected, got), count in sorted(
                result.confusion.items(), key=lambda kv: (-kv[1], kv[0])
            )
        ],
        "unavailable": [
            {"factor": factor_id, "reason": reason} for factor_id, reason in result.unavailable
        ],
        "totals": dict(result.totals),
        "cache": {"hits": result.cache_hits, "new_calls": result.calls_made},
        "trials": {
            "live_model_calls": result.calls_made - result.replayed_trials,
            "replayed_from_cassette": result.replayed_trials,
            "from_cache": result.cache_hits,
            "resumed": result.resumed_trials,
        },
    }


def _metrics_json(metrics: ArmMetrics) -> dict[str, Any]:
    return {
        "accuracy": metrics.accuracy,
        "argument_validity": metrics.argument_validity,
        "argument_match": metrics.argument_match,
        "hallucination_rate": metrics.hallucination_rate,
        "no_call_rate": metrics.no_call_rate,
        "n_items": metrics.n_items,
        "n_trials": metrics.n_trials,
    }


def _effect_json(result: SweepResult, arm_id: str) -> dict[str, Any] | None:
    for effect in result.effects:
        if effect.label == arm_id:
            return {
                "delta": effect.delta,
                "delta_pp": effect.delta_pp,
                "ci_low": effect.ci_low,
                "ci_high": effect.ci_high,
                "ci_pp": list(effect.ci_pp),
                "confidence": effect.confidence,
                "p_value": effect.p_value,
                "p_holm": effect.p_holm,
                "significant": effect.significant,
                "n_items": effect.n_items,
                "repeats": effect.repeats,
            }
    return None


def render_markdown(result: SweepResult, *, command: str = "") -> str:
    """``report.md``: the same numbers, plus the caveats that belong beside them."""
    control = result.metrics[CONTROL_ARM_ID]
    lines = [
        f"# toolsweep run `{result.experiment_id}`",
        "",
        f"- **{control.n_items} items**, "
        f"**{result.effects[0].repeats if result.effects else 0} repeats**",
        f"- determinism: `{result.determinism}`",
        f"- MDE: {'n/a' if result.mde == float('inf') else f'{result.mde * 100:.1f}pp'}",
    ]
    if command:
        lines.append(f"- command: `{command}`")
    lines += [
        "",
        "## Effects",
        "",
        "| factor | level | accuracy | Δ vs control | 95% CI | p (raw) | p (Holm) |",
        "| --- | --- | ---: | ---: | :---: | ---: | ---: |",
        f"| control | as-authored | {_pct(control.accuracy)} | - | - | - | - |",
    ]

    by_id = {e.label: e for e in result.effects}
    for arm in result.arms:
        if arm.is_control or arm.inert:
            continue
        effect = by_id.get(arm.id)
        if effect is None:
            continue
        lo, hi = effect.ci_pp
        lines.append(
            f"| `{arm.factor_id}` | {arm.level} | {_pct(result.metrics[arm.id].accuracy)} "
            f"| {effect.delta_pp:+.1f}pp | [{lo:+.1f}, {hi:+.1f}] "
            f"| {effect.p_value:.3f} | {effect.p_holm:.3f} |"
        )

    if result.inert_arms:
        lines += ["", "## Inert on this catalogue", ""]
        lines += [
            f"- `{arm.factor_id}={arm.level}` produced a catalogue identical to the control, "
            f"so no calls were spent. This is not a measured null."
            for arm in result.inert_arms
        ]

    if result.unavailable:
        lines += ["", "## Not measurable on this catalogue", ""]
        lines += [f"- `{factor_id}`: {reason}" for factor_id, reason in result.unavailable]

    top = top_confusions(result.confusion, limit=10)
    if top:
        lines += [
            "",
            "## Top confusions (control arm)",
            "",
            "| expected | got | count |",
            "| --- | --- | ---: |",
        ]
        lines += [f"| `{e}` | `{g}` | {c} |" for (e, g), c in top]

    lines += [
        "",
        "## How to read this",
        "",
        "- Effects are **paired by item** against the control arm and bootstrapped over "
        "items, not over trials.",
        "- `p (Holm)` is corrected across every arm in this run; `p (raw)` is not. Use Holm.",
        "- An effect whose CI spans zero is **not** evidence of no effect. Compare it to "
        "the MDE above: below that, this run could not have detected it either way.",
        "- Results are specific to this model, this catalogue and this suite. They do not "
        "transfer, and toolsweep does not claim they do.",
    ]
    return "\n".join(lines) + "\n"


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def format_factor_list(summaries: Mapping[str, str], levels: Mapping[str, Sequence[str]]) -> str:
    """``toolsweep factors`` output."""
    lines = ["Available factors (use with --factors):", ""]
    for factor_id, summary in summaries.items():
        lines.append(f"  {factor_id}")
        lines.append(f"      {summary}")
        lines.append(f"      levels: {', '.join(levels.get(factor_id, ()))}")
        lines.append("")
    lines.append("Pass --factors all to run every factor, or factor=level for a single arm.")
    return "\n".join(lines)


def iter_rows(result: SweepResult) -> Iterable[str]:
    """Rendered rows, for tests that assert on structure rather than exact text."""
    return render_table(result).splitlines()
