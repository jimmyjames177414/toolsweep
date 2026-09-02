"""Scoring one model response against one suite item.

The single most important line in this module is in :func:`score_call`::

    expected_name = catalogue.resolve_tool(item.expected_tool)

*not* ``called == item.expected_tool``. The suite names tools as authored; the model was
shown a transformed catalogue. Comparing the two literally makes every naming experiment
score zero while every test still passes and every report still renders. See
``tests/test_rename_map.py``.

Metrics
-------
``correct``      the model called the tool the suite expects, resolved through renames
``hallucinated`` it called a name that is not in the catalogue it was shown
``no_call``      it produced no tool call at all
``args_valid``   the arguments validate against the presented tool's schema
``args_match``   the arguments equal the expected arguments, resolved into presented space
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .catalogue import Catalogue, Param, Tool, resolve_args
from .suite import Item


@dataclass(frozen=True)
class ToolCall:
    """What the model asked for."""

    name: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True)
class ItemScore:
    """The scored result of one trial."""

    item_id: str
    correct: bool
    no_call: bool
    hallucinated: bool
    args_valid: bool
    args_match: bool
    #: The tool the model called, in as-authored space where that is knowable.
    called_origin: str | None
    #: The raw name the model called, whatever it was.
    called_raw: str | None
    #: The as-authored name the suite expected. Always present.
    expected_origin: str
    detail: dict[str, Any]

    @property
    def score(self) -> float:
        """The primary metric: tool-selection accuracy, as 0.0 or 1.0."""
        return 1.0 if self.correct else 0.0


def score_call(item: Item, cat: Catalogue, call: ToolCall | None) -> ItemScore:
    """Score one response. ``call is None`` means the model produced no tool call."""
    expected_name = cat.resolve_tool(item.expected_tool)
    if expected_name is None:
        # Only reachable if a factor dropped a tool the suite expects. catalogue.size
        # pins those, and the runner asserts it, so this is a bug rather than a result.
        raise ValueError(
            f"tool {item.expected_tool!r} expected by item {item.id!r} is absent from the "
            f"presented catalogue; a factor dropped it and the sweep cannot be scored"
        )

    if call is None:
        return ItemScore(
            item_id=item.id,
            correct=False,
            no_call=True,
            hallucinated=False,
            args_valid=False,
            args_match=False,
            called_origin=None,
            called_raw=None,
            expected_origin=item.expected_tool,
            detail={"expected": expected_name, "got": None},
        )

    called_tool = cat.by_name(call.name)
    if called_tool is None:
        return ItemScore(
            item_id=item.id,
            correct=False,
            no_call=False,
            hallucinated=True,
            args_valid=False,
            args_match=False,
            called_origin=None,
            called_raw=call.name,
            expected_origin=item.expected_tool,
            detail={"expected": expected_name, "got": call.name, "in_catalogue": False},
        )

    correct = call.name == expected_name
    problems = validate_arguments(called_tool, call.arguments)
    expected_args = resolve_args(called_tool, item.expected_args) if item.expected_args else None
    args_match = bool(correct and expected_args is not None and call.arguments == expected_args)

    detail: dict[str, Any] = {"expected": expected_name, "got": call.name}
    if problems:
        detail["argument_problems"] = problems
    if expected_args is not None and not args_match and correct:
        detail["expected_arguments"] = expected_args
        detail["got_arguments"] = dict(call.arguments)

    return ItemScore(
        item_id=item.id,
        correct=correct,
        no_call=False,
        hallucinated=False,
        args_valid=not problems,
        args_match=args_match,
        called_origin=called_tool.origin,
        called_raw=call.name,
        expected_origin=item.expected_tool,
        detail=detail,
    )


def validate_arguments(tool: Tool, arguments: Mapping[str, Any]) -> list[str]:
    """Check arguments against the presented tool's schema. Returns human-readable problems."""
    return _validate(tool.params, arguments, prefix="")


def _validate(params: Sequence[Param], arguments: Mapping[str, Any], prefix: str) -> list[str]:
    problems: list[str] = []
    declared = {p.name: p for p in params}

    for name, declared_param in declared.items():
        if declared_param.required and name not in arguments:
            problems.append(f"missing required argument {prefix}{name}")

    for name, value in arguments.items():
        path = f"{prefix}{name}"
        param = declared.get(name)
        if param is None:
            problems.append(f"unknown argument {path}")
            continue
        if not _type_ok(param, value):
            problems.append(f"{path} should be {param.type}, got {type(value).__name__}")
            continue
        if param.enum and isinstance(value, str):
            codes = [e.code for e in param.enum]
            if value not in codes:
                problems.append(f"{path} must be one of {codes}, got {value!r}")
        if param.properties and isinstance(value, dict):
            nested: Mapping[str, Any] = value
            problems.extend(_validate(param.properties, nested, f"{path}."))
    return problems


def _type_ok(param: Param, value: Any) -> bool:
    if param.type == "string":
        return isinstance(value, str)
    if param.type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if param.type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if param.type == "boolean":
        return isinstance(value, bool)
    if param.type == "array":
        return isinstance(value, list)
    return isinstance(value, dict)


# --------------------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ArmMetrics:
    """Everything measured for one arm, aggregated over items and repeats."""

    accuracy: float
    argument_validity: float
    argument_match: float
    hallucination_rate: float
    no_call_rate: float
    n_items: int
    n_trials: int


def aggregate(scores: Sequence[ItemScore]) -> ArmMetrics:
    n = len(scores)
    if n == 0:
        return ArmMetrics(0.0, 0.0, 0.0, 0.0, 0.0, 0, 0)
    called = [s for s in scores if not s.no_call and not s.hallucinated]
    return ArmMetrics(
        accuracy=sum(s.correct for s in scores) / n,
        argument_validity=(sum(s.args_valid for s in called) / len(called)) if called else 0.0,
        argument_match=(sum(s.args_match for s in called) / len(called)) if called else 0.0,
        hallucination_rate=sum(s.hallucinated for s in scores) / n,
        no_call_rate=sum(s.no_call for s in scores) / n,
        n_items=len({s.item_id for s in scores}),
        n_trials=n,
    )


def per_item_accuracy(scores: Sequence[ItemScore]) -> dict[str, float]:
    """Mean accuracy per item, over repeats. The unit the bootstrap resamples."""
    totals: dict[str, list[float]] = {}
    for s in scores:
        totals.setdefault(s.item_id, []).append(s.score)
    return {item: sum(vals) / len(vals) for item, vals in totals.items()}


def confusion_counts(scores: Sequence[ItemScore]) -> dict[tuple[str, str], int]:
    """``(expected_origin, got) -> count`` for every wrong answer.

    Keyed in as-authored space so a confusion matrix stays comparable across arms even
    when an arm renamed everything. Hallucinated names have no as-authored counterpart
    and are recorded raw with a marker; no-calls are recorded as ``<no call>``.
    """
    counts: dict[tuple[str, str], int] = {}
    for s in scores:
        if s.correct:
            continue
        if s.no_call:
            got = "<no call>"
        elif s.called_origin is not None:
            got = s.called_origin
        else:
            got = f"<not in catalogue: {s.called_raw}>"
        key = (s.expected_origin, got)
        counts[key] = counts.get(key, 0) + 1
    return counts
