"""The project's own proof that it works.

The mock provider has exactly one deliberate flaw: it confuses tools whose names differ
only by a synonym of the same verb. If toolsweep is doing its job it should

1. **detect that effect** - a positive delta with a CI excluding zero and a Holm-corrected
   p-value that clears 0.05; and
2. **not detect the ones that are not there** - factors the mock is provably blind to must
   come back null, with an interval, rather than significant.

Both halves matter. A tool that reports an effect everywhere is exactly as useless as one
that reports it nowhere, and only the second half distinguishes them.
"""

from __future__ import annotations

import pytest

from toolsweep.cache import ResponseCache
from toolsweep.providers import MockConfig, MockProvider
from toolsweep.runner import CONTROL_ARM_ID, SweepConfig, run

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def swept(tmp_path_factory):
    """One full sweep against the mock, reused by every assertion in this file."""
    from pathlib import Path

    from toolsweep.adapters import load_file as load_catalogue
    from toolsweep.suite import load_file as load_suite

    examples = Path(__file__).resolve().parents[1] / "examples" / "crm"
    catalogue, _ = load_catalogue(examples / "catalogue.json")
    suite = load_suite(examples / "suite.jsonl")

    config = SweepConfig(
        catalogue=catalogue,
        suite=suite,
        factor_specs=("all",),
        repeats=5,
        seed=7,
        resamples=2000,
    )
    provider = MockProvider(
        config=MockConfig(seed=7),
        expected_args={i.prompt: i.expected_args for i in suite.items if i.expected_args},
    )
    return run(
        config,
        provider,
        ResponseCache(enabled=False),
        out_dir=tmp_path_factory.mktemp("planted"),
    )


def effect(result, label):
    for candidate in result.effects:
        if candidate.label == label:
            return candidate
    raise AssertionError(
        f"no effect reported for {label!r}; got {[e.label for e in result.effects]}"
    )


# --------------------------------------------------------------------------------------
# 1. The effect that IS there
# --------------------------------------------------------------------------------------


def test_toolsweep_detects_the_planted_synonym_confusion(swept):
    found = effect(swept, "naming.synonyms=distinct_verbs")
    assert found.delta > 0, "renaming the near-synonyms should have helped"
    assert found.ci_low > 0, f"CI {found.ci_pp} does not exclude zero"
    assert found.p_holm < 0.05, f"Holm-adjusted p was {found.p_holm}"
    assert found.significant


def test_the_planted_effect_is_large_enough_to_beat_the_run_s_own_mde(swept):
    """A detection smaller than the MDE would be luck, not evidence."""
    found = effect(swept, "naming.synonyms=distinct_verbs")
    assert found.delta > swept.mde


def test_the_control_arm_is_confused_and_the_treated_arm_is_not(swept):
    """The mechanism, not just the number: confusion is concentrated in the clusters."""
    treated = effect(swept, "naming.synonyms=distinct_verbs")
    assert swept.metrics[CONTROL_ARM_ID].accuracy < treated.arm_mean

    cluster_tools = {"get_customer", "lookup_customer", "find_customer", "search_customer"}
    cluster_confusions = sum(
        count
        for (expected, got), count in swept.confusion.items()
        if expected in cluster_tools and got in cluster_tools
    )
    assert cluster_confusions > 0, "the planted confusion did not appear in the control arm"


# --------------------------------------------------------------------------------------
# 2. The effects that are NOT there
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label",
    [
        "enum.wording=alternate_wording",
        "schema.nesting=nested",
        "params.required=all_required",
        "params.required=minimal_required",
    ],
)
def test_factors_the_mock_is_blind_to_come_back_null(swept, label):
    """The mock selects on names and descriptions only; argument schemas cannot move it.

    These arms are the control group for toolsweep itself. If any of them read as
    significant, the statistics are manufacturing effects.
    """
    found = effect(swept, label)
    assert not found.significant, f"{label} was reported significant against a blind mock"
    assert found.ci_low <= 0 <= found.ci_high, f"{label} CI {found.ci_pp} excludes zero"


def test_a_null_result_still_reports_an_interval(swept):
    """ "No effect" without an interval is indistinguishable from "underpowered"."""
    found = effect(swept, "params.required=all_required")
    assert found.ci_low is not None and found.ci_high is not None
    assert found.n_items == 40 and found.repeats == 5


# --------------------------------------------------------------------------------------
# 3. Reproducibility
# --------------------------------------------------------------------------------------


def test_the_whole_sweep_is_reproducible_from_the_seed(tmp_path):
    from pathlib import Path

    from toolsweep.adapters import load_file as load_catalogue
    from toolsweep.suite import load_file as load_suite

    examples = Path(__file__).resolve().parents[1] / "examples" / "crm"
    catalogue, _ = load_catalogue(examples / "catalogue.json")
    suite = load_suite(examples / "suite.jsonl")
    config = SweepConfig(
        catalogue=catalogue,
        suite=suite,
        factor_specs=("naming.synonyms",),
        repeats=3,
        seed=11,
        resamples=300,
    )

    def once(name: str):
        provider = MockProvider(
            config=MockConfig(seed=11),
            expected_args={i.prompt: i.expected_args for i in suite.items if i.expected_args},
        )
        return run(config, provider, ResponseCache(enabled=False), out_dir=tmp_path / name)

    first, second = once("a"), once("b")
    assert [(e.label, e.delta, e.ci_low, e.ci_high, e.p_value) for e in first.effects] == [
        (e.label, e.delta, e.ci_low, e.ci_high, e.p_value) for e in second.effects
    ]


def test_a_different_confusion_rate_moves_the_measured_effect(tmp_path):
    """The measurement tracks the planted cause, rather than being a fixed artefact.

    Dose-response measured across the mock's confusion rate (40 items, 5 repeats, seed 7)::

        rate 0.00  control 87.5%   +5.0pp  [ -5.0, +15.0]   not significant
        rate 0.40  control 78.0%  +14.5pp  [ +4.0, +24.5]
        rate 0.90  control 64.0%  +28.5pp  [+15.5, +40.5]

    The residual **+5.0pp at rate zero is not noise, and it is not the planted effect**.
    Renaming ``lookup_customer`` to ``get_customer_by_email`` adds a discriminating token
    the lexical mock can match on, so part of any naming result is the new name carrying
    more information, not confusion being removed. toolsweep cannot separate the two, and
    says so in the README's limitations rather than quietly attributing all of it to
    confusion. What it does do correctly here is decline to call that residual an effect:
    its interval spans zero.
    """
    from pathlib import Path

    from toolsweep.adapters import load_file as load_catalogue
    from toolsweep.suite import load_file as load_suite

    examples = Path(__file__).resolve().parents[1] / "examples" / "crm"
    catalogue, _ = load_catalogue(examples / "catalogue.json")
    suite = load_suite(examples / "suite.jsonl")
    config = SweepConfig(
        catalogue=catalogue,
        suite=suite,
        factor_specs=("naming.synonyms",),
        repeats=5,
        seed=7,
        resamples=500,
    )

    def sweep_at(rate: float, name: str):
        provider = MockProvider(
            config=MockConfig(seed=7, confusion_rate=rate),
            expected_args={i.prompt: i.expected_args for i in suite.items if i.expected_args},
        )
        result = run(config, provider, ResponseCache(enabled=False), out_dir=tmp_path / name)
        return effect(result, "naming.synonyms=distinct_verbs")

    none, some, lots = sweep_at(0.0, "n"), sweep_at(0.4, "s"), sweep_at(0.9, "l")
    deltas = (none.delta, some.delta, lots.delta)
    assert deltas == tuple(sorted(deltas)), f"effect did not track the planted rate: {deltas}"
    assert lots.delta - none.delta > 0.10, "the planted component should dominate"

    # With nothing planted, the leftover naming confound must not be called an effect.
    assert not none.significant
    assert none.ci_low <= 0 <= none.ci_high, f"CI {none.ci_pp} wrongly excludes zero"
    assert lots.significant
