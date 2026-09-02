"""The statistical contract: control arm, paired interval, Holm, MDE.

These are the rules that separate a factorial sweep from a table of vibes, so they get
tested as rules rather than as implementation details.
"""

from __future__ import annotations

import math

import pytest

from toolsweep.stats import (
    Effect,
    StatsError,
    apply_holm,
    bootstrap_ci,
    compute_effect,
    holm,
    mde,
    paired_differences,
    permutation_p,
)


def _accuracy(values: dict[str, float]) -> dict[str, float]:
    return values


# --------------------------------------------------------------------------------------
# Rule: an effect cannot exist without its interval
# --------------------------------------------------------------------------------------


def test_effect_cannot_be_constructed_without_a_confidence_interval():
    """Structural, not by convention: the CI fields have no defaults.

    This is what makes "no effect is reported without a CI" a property of the type rather
    than a promise in a docstring.
    """
    with pytest.raises(TypeError):
        Effect(  # type: ignore[call-arg]
            label="x",
            arm_mean=0.9,
            control_mean=0.8,
            delta=0.1,
            p_value=0.01,
            p_holm=0.01,
            n_items=40,
            repeats=5,
            confidence=0.95,
        )


def test_compute_effect_always_returns_an_interval():
    arm = {f"i{i}": 1.0 for i in range(20)}
    control = {f"i{i}": 0.5 for i in range(20)}
    effect = compute_effect("arm", arm, control, repeats=3, resamples=500, seed=1)
    assert effect.ci_low <= effect.delta <= effect.ci_high
    assert math.isfinite(effect.ci_low) and math.isfinite(effect.ci_high)


# --------------------------------------------------------------------------------------
# Rule: paired by item
# --------------------------------------------------------------------------------------


def test_pairing_uses_only_items_present_in_both_arms():
    items, diffs = paired_differences({"a": 1.0, "b": 0.0, "c": 1.0}, {"a": 0.0, "b": 0.0})
    assert items == ("a", "b")
    assert diffs == (1.0, 0.0)


def test_pairing_refuses_when_no_items_overlap():
    with pytest.raises(StatsError, match="no items scored under both"):
        paired_differences({"a": 1.0}, {"b": 1.0})


def test_effect_is_a_difference_from_control_not_a_raw_score():
    arm = {"a": 0.9, "b": 0.9}
    control = {"a": 0.8, "b": 0.8}
    effect = compute_effect("arm", arm, control, repeats=1, resamples=200, seed=0)
    assert effect.delta == pytest.approx(0.1)
    assert effect.arm_mean == pytest.approx(0.9)
    assert effect.control_mean == pytest.approx(0.8)


# --------------------------------------------------------------------------------------
# Bootstrap
# --------------------------------------------------------------------------------------


def test_bootstrap_is_deterministic_for_a_given_seed():
    diffs = [0.2, -0.1, 0.3, 0.0, 0.5, -0.2, 0.1, 0.4]
    assert bootstrap_ci(diffs, resamples=500, seed=4) == bootstrap_ci(diffs, resamples=500, seed=4)
    assert bootstrap_ci(diffs, resamples=500, seed=4) != bootstrap_ci(diffs, resamples=500, seed=5)


def test_bootstrap_brackets_the_observed_mean():
    diffs = [0.2, 0.25, 0.15, 0.3, 0.2, 0.22, 0.18, 0.24]
    lo, hi = bootstrap_ci(diffs, resamples=2000, seed=1)
    mean = sum(diffs) / len(diffs)
    assert lo < mean < hi


def test_bootstrap_widens_as_the_interval_gets_more_confident():
    diffs = [0.1, -0.2, 0.4, 0.0, 0.3, -0.1, 0.2, 0.05]
    narrow = bootstrap_ci(diffs, resamples=4000, confidence=0.80, seed=2)
    wide = bootstrap_ci(diffs, resamples=4000, confidence=0.99, seed=2)
    assert wide[0] <= narrow[0] and wide[1] >= narrow[1]


def test_a_single_item_yields_an_unbounded_interval_rather_than_false_precision():
    """One item carries no information about between-item variance, and says so."""
    lo, hi = bootstrap_ci([0.5])
    assert lo == float("-inf") and hi == float("inf")


def test_bootstrap_rejects_an_empty_sample():
    with pytest.raises(StatsError):
        bootstrap_ci([])


# --------------------------------------------------------------------------------------
# Permutation test
# --------------------------------------------------------------------------------------


def test_permutation_p_is_one_when_nothing_changed():
    assert permutation_p([0.0] * 10) == 1.0


def test_permutation_p_is_small_for_a_consistent_shift():
    diffs = [0.3] * 25
    assert permutation_p(diffs, resamples=2000, seed=3) < 0.01


def test_permutation_p_is_large_for_noise():
    diffs = [0.2, -0.2, 0.1, -0.1, 0.15, -0.15, 0.05, -0.05]
    assert permutation_p(diffs, resamples=2000, seed=3) > 0.5


# --------------------------------------------------------------------------------------
# Holm
# --------------------------------------------------------------------------------------


def test_holm_is_monotone_and_never_shrinks_a_p_value():
    raw = [0.001, 0.02, 0.04, 0.5]
    adjusted = holm(raw)
    assert all(a >= r for a, r in zip(adjusted, raw, strict=True))
    assert adjusted == tuple(sorted(adjusted))


def test_holm_matches_the_worked_example():
    # m=4: 0.001*4=0.004, 0.02*3=0.06, 0.04*2=0.08, 0.5*1=0.5, then step-down max.
    assert holm([0.001, 0.02, 0.04, 0.5]) == pytest.approx((0.004, 0.06, 0.08, 0.5))


def test_holm_preserves_input_order():
    assert holm([0.5, 0.001]) == pytest.approx((0.5, 0.002))


def test_holm_caps_at_one():
    assert all(p <= 1.0 for p in holm([0.4, 0.5, 0.6]))


def test_apply_holm_corrects_a_family_of_effects():
    effects = [
        compute_effect(
            f"arm{i}",
            {f"item{j}": 1.0 if j < i else 0.0 for j in range(10)},
            {f"item{j}": 0.0 for j in range(10)},
            repeats=1,
            resamples=300,
            seed=i,
        )
        for i in range(1, 4)
    ]
    corrected = apply_holm(effects)
    assert [e.label for e in corrected] == [e.label for e in effects]
    assert all(c.p_holm >= c.p_value for c in corrected)


# --------------------------------------------------------------------------------------
# MDE
# --------------------------------------------------------------------------------------


def test_mde_shrinks_as_n_grows():
    small = mde([0.2, -0.1, 0.3, 0.0] * 3)
    large = mde([0.2, -0.1, 0.3, 0.0] * 30)
    assert large < small


def test_mde_is_zero_when_every_item_moved_identically():
    """Zero variance means any nonzero effect is detectable; that is not infinity."""
    assert mde([0.25] * 10) == 0.0


def test_mde_is_infinite_below_two_items():
    assert mde([0.5]) == float("inf")


def test_significance_requires_both_holm_and_an_interval_excluding_zero():
    borderline = Effect(
        label="x",
        arm_mean=0.5,
        control_mean=0.5,
        delta=0.01,
        ci_low=-0.01,
        ci_high=0.03,
        p_value=0.01,
        p_holm=0.01,
        n_items=40,
        repeats=5,
        confidence=0.95,
    )
    assert not borderline.significant, "a CI spanning zero must never read as significant"
