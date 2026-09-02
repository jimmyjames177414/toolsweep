"""Accuracy, argument validity, hallucination, no-call, and the confusion matrix."""

from __future__ import annotations

import pytest

from toolsweep.score import (
    ToolCall,
    aggregate,
    confusion_counts,
    per_item_accuracy,
    score_call,
    validate_arguments,
)
from toolsweep.suite import Item


def item(expected: str = "get_customer", args: dict | None = None) -> Item:
    return Item(id="i1", prompt="...", expected_tool=expected, expected_args=args)


def test_correct_call_scores_one(small_catalogue):
    score = score_call(
        item(args={"customer_id": "CUS-1"}),
        small_catalogue,
        ToolCall("get_customer", {"customer_id": "CUS-1"}),
    )
    assert score.correct and score.score == 1.0
    assert score.args_valid and score.args_match
    assert not score.hallucinated and not score.no_call


def test_wrong_tool_scores_zero_but_is_not_a_hallucination(small_catalogue):
    score = score_call(item(), small_catalogue, ToolCall("find_customer", {"name": "x"}))
    assert not score.correct and score.score == 0.0
    assert not score.hallucinated
    assert score.called_origin == "find_customer"


def test_a_name_absent_from_the_catalogue_is_a_hallucination(small_catalogue):
    score = score_call(item(), small_catalogue, ToolCall("delete_customer", {}))
    assert score.hallucinated and not score.correct
    assert score.called_origin is None
    assert score.called_raw == "delete_customer"
    assert score.detail["in_catalogue"] is False


def test_no_tool_call_is_recorded_as_a_no_call(small_catalogue):
    score = score_call(item(), small_catalogue, None)
    assert score.no_call and not score.correct and not score.hallucinated
    assert score.detail["got"] is None


def test_a_correct_tool_with_wrong_arguments_still_scores_the_selection(small_catalogue):
    """Selection accuracy and argument correctness are separate metrics, on purpose."""
    score = score_call(
        item(args={"customer_id": "CUS-1"}),
        small_catalogue,
        ToolCall("get_customer", {"customer_id": "WRONG"}),
    )
    assert score.correct
    assert score.args_valid
    assert not score.args_match
    assert score.detail["expected_arguments"] == {"customer_id": "CUS-1"}


# --------------------------------------------------------------------------------------
# Argument validation
# --------------------------------------------------------------------------------------


def test_missing_required_argument_is_invalid(small_catalogue):
    tool = small_catalogue.by_name("get_customer")
    assert tool is not None
    assert validate_arguments(tool, {}) == ["missing required argument customer_id"]


def test_unknown_argument_is_invalid(small_catalogue):
    tool = small_catalogue.by_name("get_customer")
    assert tool is not None
    problems = validate_arguments(tool, {"customer_id": "x", "colour": "blue"})
    assert problems == ["unknown argument colour"]


def test_wrong_type_is_invalid(small_catalogue):
    tool = small_catalogue.by_name("get_customer")
    assert tool is not None
    assert validate_arguments(tool, {"customer_id": 7}) == ["customer_id should be string, got int"]


def test_a_bool_is_not_an_integer(small_catalogue):
    """`isinstance(True, int)` is True in Python; a schema check must not accept it."""
    tool = small_catalogue.by_name("create_invoice")
    assert tool is not None
    problems = validate_arguments(tool, {"customer_id": "c", "amount_cents": True})
    assert problems == ["amount_cents should be integer, got bool"]


def test_enum_membership_is_checked(small_catalogue):
    tool = small_catalogue.by_name("search_customer")
    assert tool is not None
    problems = validate_arguments(tool, {"filter": {"status": "ARCHIVED"}})
    assert problems == ["filter.status must be one of ['ACT', 'INACT'], got 'ARCHIVED'"]


def test_nested_objects_are_validated_recursively(small_catalogue):
    tool = small_catalogue.by_name("search_customer")
    assert tool is not None
    assert validate_arguments(tool, {"filter": {"status": "ACT"}}) == []
    assert validate_arguments(tool, {"filter": {}}) == ["missing required argument filter.status"]


# --------------------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------------------


def test_aggregate_reports_every_rate(small_catalogue):
    scores = [
        score_call(item(), small_catalogue, ToolCall("get_customer", {"customer_id": "c"})),
        score_call(item(), small_catalogue, ToolCall("find_customer", {"name": "n"})),
        score_call(item(), small_catalogue, ToolCall("nope", {})),
        score_call(item(), small_catalogue, None),
    ]
    metrics = aggregate(scores)
    assert metrics.accuracy == pytest.approx(0.25)
    assert metrics.hallucination_rate == pytest.approx(0.25)
    assert metrics.no_call_rate == pytest.approx(0.25)
    assert metrics.n_trials == 4


def test_aggregate_of_nothing_is_zero_not_a_crash():
    metrics = aggregate([])
    assert metrics.accuracy == 0.0 and metrics.n_trials == 0


def test_per_item_accuracy_averages_over_repeats(small_catalogue):
    hit = score_call(item(), small_catalogue, ToolCall("get_customer", {"customer_id": "c"}))
    miss = score_call(item(), small_catalogue, ToolCall("find_customer", {"name": "n"}))
    assert per_item_accuracy([hit, miss, hit, hit]) == {"i1": 0.75}


# --------------------------------------------------------------------------------------
# Confusion matrix
# --------------------------------------------------------------------------------------


def test_confusion_is_keyed_in_as_authored_space(crm_catalogue):
    """So a matrix stays comparable across an arm that renamed everything."""
    from toolsweep.factors import FactorContext
    from toolsweep.factors.naming_synonyms import NamingSynonymsFactor

    renamed = NamingSynonymsFactor(FactorContext(catalogue=crm_catalogue)).apply(
        "distinct_verbs", crm_catalogue
    )
    wrong = renamed.resolve_tool("lookup_customer")
    assert wrong is not None and wrong != "lookup_customer"

    score = score_call(item(), renamed, ToolCall(wrong, {"email": "a@b.example"}))
    counts = confusion_counts([score])
    assert counts == {("get_customer", "lookup_customer"): 1}


def test_confusion_records_no_calls_and_hallucinations_distinctly(small_catalogue):
    scores = [
        score_call(item(), small_catalogue, None),
        score_call(item(), small_catalogue, ToolCall("invented_tool", {})),
    ]
    counts = confusion_counts(scores)
    assert counts[("get_customer", "<no call>")] == 1
    assert counts[("get_customer", "<not in catalogue: invented_tool>")] == 1


def test_correct_calls_are_absent_from_the_confusion_matrix(small_catalogue):
    score = score_call(item(), small_catalogue, ToolCall("get_customer", {"customer_id": "c"}))
    assert confusion_counts([score]) == {}
