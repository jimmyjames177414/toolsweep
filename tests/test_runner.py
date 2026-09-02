"""Arm construction, the grid, the budget, resume, and the guards around all of them."""

from __future__ import annotations

import pytest

from toolsweep import cxs
from toolsweep.cache import ResponseCache
from toolsweep.providers import MockConfig, MockProvider
from toolsweep.runner import (
    CONTROL_ARM_ID,
    SweepConfig,
    build_arms,
    plan,
    run,
    unavailable_factors,
)
from toolsweep.suite import parse


def make_config(catalogue, suite, **kwargs) -> SweepConfig:
    defaults = {
        "catalogue": catalogue,
        "suite": suite,
        "factor_specs": ("naming.synonyms",),
        "repeats": 2,
        "seed": 7,
        "resamples": 200,
    }
    defaults.update(kwargs)
    return SweepConfig(**defaults)  # type: ignore[arg-type]


def make_provider(suite) -> MockProvider:
    return MockProvider(
        config=MockConfig(seed=7),
        expected_args={i.prompt: i.expected_args for i in suite.items if i.expected_args},
    )


# --------------------------------------------------------------------------------------
# Arms
# --------------------------------------------------------------------------------------


def test_arm_zero_is_always_the_unmodified_catalogue(crm_catalogue, crm_suite):
    arms = build_arms(make_config(crm_catalogue, crm_suite, factor_specs=("all",)))
    assert arms[0].id == CONTROL_ARM_ID
    assert arms[0].kind == "noop"
    assert arms[0].catalogue == crm_catalogue


def test_the_control_arm_cannot_be_switched_off(crm_catalogue, crm_suite):
    """There is no configuration that produces a sweep without a control."""
    for specs in (("naming.synonyms",), ("all",), ("enum.wording=alternate_wording",)):
        arms = build_arms(make_config(crm_catalogue, crm_suite, factor_specs=specs))
        assert sum(1 for a in arms if a.is_control) == 1


def test_a_level_identical_to_the_control_is_marked_inert(crm_catalogue, crm_suite):
    arms = build_arms(make_config(crm_catalogue, crm_suite, factor_specs=("naming.scheme",)))
    inert = [a for a in arms if a.inert]
    assert any(a.level == "verb_noun" for a in inert), (
        "this catalogue is already verb-first, so verb_noun changes nothing"
    )


def test_inert_arms_spend_no_calls(crm_catalogue, crm_suite):
    config = make_config(crm_catalogue, crm_suite, factor_specs=("naming.scheme",))
    estimate = plan(config, make_provider(crm_suite), ResponseCache(enabled=False))
    assert estimate.inert_arms >= 1
    assert estimate.grid_size == estimate.live_arms * len(crm_suite) * config.repeats


def test_every_arm_still_contains_every_expected_tool(crm_catalogue, crm_suite):
    for arm in build_arms(make_config(crm_catalogue, crm_suite, factor_specs=("all",))):
        for origin in crm_suite.expected_tools:
            assert arm.catalogue.resolve_tool(origin) is not None


def test_an_arm_that_dropped_an_expected_tool_is_refused(crm_catalogue, crm_suite):
    """Belt and braces over catalogue.size's pinning: the runner verifies, not trusts."""
    from toolsweep.runner import Arm, _check_expected_tools_present

    broken = Arm(
        id="broken",
        factor_id="x",
        level="y",
        catalogue=crm_catalogue.with_tools(crm_catalogue.tools[:2]),
        kind="remove",
        description="",
        implementation="",
    )
    with pytest.raises(ValueError, match="dropped tools the suite expects"):
        _check_expected_tools_present([broken], crm_suite)


def test_a_factor_with_no_levels_is_reported_not_dropped(crm_catalogue):
    """Silence would read as 'measured, no effect'. It has to say why instead."""
    every_tool = "\n".join(
        f'{{"id": "i{n}", "prompt": "do {name}", "expected_tool": "{name}"}}'
        for n, name in enumerate(crm_catalogue.names)
    )
    suite = parse(every_tool)
    config = make_config(crm_catalogue, suite, factor_specs=("catalogue.size",))
    assert build_arms(config) == build_arms(config)[:1], "no treatment arms are possible"

    reported = unavailable_factors(config)
    assert [f for f, _ in reported] == ["catalogue.size"]
    assert "without dropping an answer" in reported[0][1]


# --------------------------------------------------------------------------------------
# Dry run
# --------------------------------------------------------------------------------------


def test_dry_run_counts_the_grid_and_spends_nothing(crm_catalogue, crm_suite):
    config = make_config(crm_catalogue, crm_suite, factor_specs=("naming.synonyms",))
    estimate = plan(config, make_provider(crm_suite), ResponseCache(enabled=False))
    assert estimate.live_arms == 2
    assert estimate.grid_size == 2 * len(crm_suite) * config.repeats
    assert estimate.calls_needed == estimate.grid_size
    assert estimate.estimated_prompt_tokens > 0


def test_dry_run_subtracts_what_the_cache_already_holds(crm_catalogue, crm_suite, tmp_path):
    config = make_config(crm_catalogue, crm_suite, factor_specs=("naming.synonyms",))
    cache = ResponseCache(tmp_path / "cache")
    provider = make_provider(crm_suite)

    before = plan(config, provider, cache).calls_needed
    run(config, provider, cache, out_dir=tmp_path / "out")
    after = plan(config, provider, ResponseCache(tmp_path / "cache")).calls_needed

    assert before > 0
    assert after == 0, "a completed run should leave nothing to pay for"


# --------------------------------------------------------------------------------------
# Execution, budget and resume
# --------------------------------------------------------------------------------------


def test_a_full_run_scores_every_arm(crm_catalogue, crm_suite, tmp_path):
    config = make_config(crm_catalogue, crm_suite, factor_specs=("naming.synonyms",))
    result = run(config, make_provider(crm_suite), ResponseCache(enabled=False), out_dir=tmp_path)
    assert set(result.metrics) == {a.id for a in result.arms}
    assert result.metrics[CONTROL_ARM_ID].n_trials == len(crm_suite) * config.repeats
    assert result.effects, "a sweep with a live arm must produce an effect"


def test_max_calls_is_a_hard_stop(crm_catalogue, crm_suite, tmp_path):
    config = make_config(crm_catalogue, crm_suite, factor_specs=("naming.synonyms",), max_calls=10)
    result = run(config, make_provider(crm_suite), ResponseCache(enabled=False), out_dir=tmp_path)
    assert result.calls_made == 10
    assert result.truncated


def test_a_truncated_run_still_renders_and_says_so(crm_catalogue, crm_suite, tmp_path):
    from toolsweep.report import render_table

    config = make_config(crm_catalogue, crm_suite, factor_specs=("naming.synonyms",), max_calls=5)
    result = run(config, make_provider(crm_suite), ResponseCache(enabled=False), out_dir=tmp_path)
    assert "RUN TRUNCATED" in render_table(result)


def test_a_resumed_run_makes_no_new_calls(crm_catalogue, crm_suite, tmp_path):
    """trials.jsonl is append-only, so a rerun re-scores rather than re-calling."""
    config = make_config(crm_catalogue, crm_suite, factor_specs=("naming.synonyms",))
    provider = make_provider(crm_suite)

    first = run(config, provider, ResponseCache(enabled=False), out_dir=tmp_path)
    assert first.calls_made > 0

    second = run(
        config,
        provider,
        ResponseCache(enabled=False),
        out_dir=tmp_path,
        experiment_id=first.experiment_id,
    )
    assert second.calls_made == 0
    assert second.resumed_trials == first.calls_made
    assert second.metrics[CONTROL_ARM_ID].accuracy == first.metrics[CONTROL_ARM_ID].accuracy


def test_resume_reproduces_the_same_effects(crm_catalogue, crm_suite, tmp_path):
    config = make_config(crm_catalogue, crm_suite, factor_specs=("naming.synonyms",))
    provider = make_provider(crm_suite)
    first = run(config, provider, ResponseCache(enabled=False), out_dir=tmp_path)
    second = run(
        config,
        provider,
        ResponseCache(enabled=False),
        out_dir=tmp_path,
        experiment_id=first.experiment_id,
    )
    assert [e.delta for e in second.effects] == [e.delta for e in first.effects]


def test_the_cache_removes_calls_on_a_second_run(crm_catalogue, crm_suite, tmp_path):
    config = make_config(crm_catalogue, crm_suite, factor_specs=("naming.synonyms",))
    provider = make_provider(crm_suite)
    cache_dir = tmp_path / "cache"

    first = run(config, provider, ResponseCache(cache_dir), out_dir=tmp_path / "a")
    second = run(config, provider, ResponseCache(cache_dir), out_dir=tmp_path / "b")
    assert first.calls_made > 0
    assert second.calls_made == 0
    assert second.cache_hits == first.calls_made


def test_a_run_writes_the_whole_cxs_layout(crm_catalogue, crm_suite, tmp_path):
    config = make_config(crm_catalogue, crm_suite, factor_specs=("naming.synonyms",))
    result = run(config, make_provider(crm_suite), ResponseCache(enabled=False), out_dir=tmp_path)
    assert result.paths is not None
    for path in (
        result.paths.manifest,
        result.paths.interventions,
        result.paths.trials,
        result.paths.outcomes,
    ):
        assert path.is_file()


def test_effects_are_holm_corrected_across_the_family(crm_catalogue, crm_suite, tmp_path):
    config = make_config(crm_catalogue, crm_suite, factor_specs=("all",))
    result = run(config, make_provider(crm_suite), ResponseCache(enabled=False), out_dir=tmp_path)
    assert len(result.effects) > 1
    assert all(e.p_holm >= e.p_value for e in result.effects)


def test_every_effect_carries_an_interval(crm_catalogue, crm_suite, tmp_path):
    config = make_config(crm_catalogue, crm_suite, factor_specs=("all",))
    result = run(config, make_provider(crm_suite), ResponseCache(enabled=False), out_dir=tmp_path)
    for effect in result.effects:
        assert effect.ci_low <= effect.delta <= effect.ci_high
        assert effect.n_items == len(crm_suite)


def test_the_experiment_id_is_sortable_by_creation_time():
    """ULID shape: 10 chars of timestamp then 16 of randomness.

    Only the timestamp prefix is ordered. Ids minted inside the same millisecond tie on
    it and are separated by randomness alone, so asserting the whole string sorts would be
    asserting something ULIDs do not promise.
    """
    ids = [cxs.new_experiment_id() for _ in range(5)]
    assert all(len(i) == 26 for i in ids)
    prefixes = [i[:10] for i in ids]
    assert prefixes == sorted(prefixes)
    assert len(set(ids)) == 5, "the random suffix must separate ids within a millisecond"
