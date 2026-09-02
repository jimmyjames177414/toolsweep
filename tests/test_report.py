"""Rendering, and the one rule it enforces: no effect is printed without its interval."""

from __future__ import annotations

import re

import pytest

from toolsweep.cache import ResponseCache
from toolsweep.providers import MockConfig, MockProvider
from toolsweep.report import (
    format_factor_list,
    render_confusion,
    render_markdown,
    render_table,
    report_json,
    top_confusions,
)
from toolsweep.runner import CONTROL_ARM_ID, SweepConfig, run

CI_PATTERN = re.compile(r"\[\s*[-+]\d+\.\d+,\s*[-+]\d+\.\d+\]")


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    from pathlib import Path

    from toolsweep.adapters import load_file as load_catalogue
    from toolsweep.suite import load_file as load_suite

    examples = Path(__file__).resolve().parents[1] / "examples" / "crm"
    catalogue, _ = load_catalogue(examples / "catalogue.json")
    suite = load_suite(examples / "suite.jsonl")
    config = SweepConfig(
        catalogue=catalogue, suite=suite, factor_specs=("all",), repeats=2, seed=7, resamples=300
    )
    provider = MockProvider(
        config=MockConfig(seed=7),
        expected_args={i.prompt: i.expected_args for i in suite.items if i.expected_args},
    )
    return run(
        config, provider, ResponseCache(enabled=False), out_dir=tmp_path_factory.mktemp("report")
    )


# --------------------------------------------------------------------------------------
# The rule
# --------------------------------------------------------------------------------------


def test_every_effect_row_carries_a_confidence_interval(result):
    """The headline assertion of this file.

    Walks the rendered table and requires a bracketed interval on every row that reports
    a delta. A row with a number and no interval is the failure mode the whole statistics
    module exists to prevent.
    """
    rows = [
        line for line in render_table(result).splitlines() if "pp" in line and "MDE" not in line
    ]
    assert rows, "the table reported no effects at all"
    for row in rows:
        assert CI_PATTERN.search(row), f"effect row has no interval: {row!r}"


def test_the_control_row_is_first_and_reports_no_delta(result):
    lines = render_table(result).splitlines()
    control = next(line for line in lines if line.startswith("control"))
    assert lines.index(control) == 2, "arm zero must be the first data row"
    assert "pp" not in control, "the control arm has nothing to be a delta against"


def test_markdown_reports_both_raw_and_holm_p_values(result):
    text = render_markdown(result)
    assert "p (raw)" in text and "p (Holm)" in text
    assert "Use Holm" in text


def test_markdown_distinguishes_a_null_result_from_an_underpowered_one(result):
    text = render_markdown(result)
    assert "MDE" in text
    assert "not** evidence of no effect" in text or "not evidence of no effect" in text


def test_markdown_states_that_results_do_not_transfer(result):
    assert "do not transfer" in render_markdown(result)


# --------------------------------------------------------------------------------------
# Inert and unavailable arms are never silently collapsed into "no effect"
# --------------------------------------------------------------------------------------


def test_inert_arms_are_listed_separately_from_measured_nulls(result):
    text = render_table(result)
    assert result.inert_arms, "fixture problem: expected at least one inert arm"
    assert "INERT ON THIS CATALOGUE" in text
    for arm in result.inert_arms:
        assert f"{arm.factor_id}={arm.level}" in text


def test_an_inert_arm_has_no_effect_row(result):
    """It was never run, so quoting a delta for it would be inventing a measurement."""
    labels = {e.label for e in result.effects}
    for arm in result.inert_arms:
        assert arm.id not in labels


def test_inert_arms_report_no_metrics_in_json(result):
    payload = report_json(result)
    for arm in payload["arms"]:
        if arm["inert"]:
            assert arm["metrics"] is None and arm["effect"] is None


# --------------------------------------------------------------------------------------
# JSON report
# --------------------------------------------------------------------------------------


def test_json_report_carries_an_interval_on_every_effect(result):
    payload = report_json(result)
    effects = [a["effect"] for a in payload["arms"] if a["effect"] is not None]
    assert effects
    for effect in effects:
        assert effect["ci_low"] <= effect["delta"] <= effect["ci_high"]
        assert effect["confidence"] == 0.95
        assert "p_holm" in effect and "p_value" in effect


def test_json_report_states_n_beside_the_numbers(result):
    payload = report_json(result)
    assert payload["n_items"] == 40
    assert payload["repeats"] == 2
    for arm in payload["arms"]:
        if arm["effect"]:
            assert arm["effect"]["n_items"] == 40


def test_json_report_separates_replays_from_live_model_calls(result):
    trials = report_json(result)["trials"]
    assert trials["replayed_from_cassette"] == 0
    assert trials["live_model_calls"] > 0


# --------------------------------------------------------------------------------------
# Confusion matrix
# --------------------------------------------------------------------------------------


def test_confusion_view_uses_as_authored_names(result):
    text = render_confusion(result, arm_id=CONTROL_ARM_ID)
    assert "as-authored space" in text
    assert "get_customer" in text


def test_confusion_view_handles_an_arm_with_no_trials(result):
    assert "no scored trials" in render_confusion(result, arm_id="nonexistent.arm=x")


def test_top_confusions_is_ordered_and_capped():
    counts = {("a", "b"): 5, ("c", "d"): 9, ("e", "f"): 1}
    assert top_confusions(counts, limit=2) == [(("c", "d"), 9), (("a", "b"), 5)]


# --------------------------------------------------------------------------------------
# factors listing
# --------------------------------------------------------------------------------------


def test_factor_listing_shows_every_factor_with_its_levels():
    from toolsweep.factors import FACTOR_IDS, SUMMARIES

    levels = dict.fromkeys(FACTOR_IDS, ("a", "b"))
    text = format_factor_list(SUMMARIES, levels)
    for factor_id in FACTOR_IDS:
        assert factor_id in text
    assert "--factors all" in text
