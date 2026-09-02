"""Paired statistics for factorial sweeps.

The rules here are the portfolio's, not this project's, and they are binding:

1. **Always report a control arm.** An effect is ``score(arm) - score(control)``, never
   ``score(arm)`` alone.
2. **Always report an interval.** Bootstrap percentile CI over *items*, because items are
   the independent unit; repeats of the same item are not.
3. **Paired by item.** Arm and control run on the same items and the paired difference is
   what gets resampled. Unpaired comparison wastes power and is not permitted.
4. **State N.** ``n_items`` and ``repeats`` travel with every number.
5. **Report the MDE**, so "no effect" and "underpowered" are distinguishable.
6. **Multiplicity.** Holm-adjusted p-values alongside the raw ones, labelled.
7. **Never round a CI away.**

An :class:`Effect` cannot be constructed without its interval - the fields have no
defaults, so a caller that skipped the bootstrap gets a ``TypeError`` rather than a
plausible-looking number. That is deliberate; see ``tests/test_stats.py``.

Methodology reference, cited rather than claimed: Miller, *Adding Error Bars to Evals: A
Statistical Approach to Language Model Evaluations*, arXiv:2411.00640.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

#: 95% two-sided normal quantile.
Z_ALPHA = 1.959963984540054
#: 80% power one-sided normal quantile.
Z_POWER = 0.8416212335729143

DEFAULT_RESAMPLES = 10_000


class StatsError(ValueError):
    """Raised when an effect cannot be computed from the data given."""


@dataclass(frozen=True)
class Effect:
    """A paired effect with its interval. Every field is required, on purpose."""

    label: str
    #: Mean accuracy of the treatment arm, 0..1.
    arm_mean: float
    #: Mean accuracy of the control arm on the same items, 0..1.
    control_mean: float
    #: Mean paired difference, 0..1 scale (multiply by 100 for percentage points).
    delta: float
    ci_low: float
    ci_high: float
    p_value: float
    p_holm: float
    n_items: int
    repeats: int
    confidence: float

    @property
    def delta_pp(self) -> float:
        return self.delta * 100.0

    @property
    def ci_pp(self) -> tuple[float, float]:
        return self.ci_low * 100.0, self.ci_high * 100.0

    @property
    def significant(self) -> bool:
        """Whether the Holm-adjusted p-value clears 0.05 *and* the CI excludes zero."""
        return self.p_holm < 0.05 and (self.ci_low > 0.0 or self.ci_high < 0.0)


def paired_differences(
    arm: Mapping[str, float], control: Mapping[str, float]
) -> tuple[tuple[str, ...], tuple[float, ...]]:
    """Per-item ``arm - control``, over the items both arms scored.

    Items missing from either side are dropped rather than imputed, and the returned item
    list says which ones survived, so a partial run cannot silently become an unpaired
    comparison.
    """
    shared = tuple(sorted(set(arm) & set(control)))
    if not shared:
        raise StatsError("no items scored under both the arm and the control")
    return shared, tuple(arm[i] - control[i] for i in shared)


def bootstrap_ci(
    diffs: Sequence[float],
    *,
    resamples: int = DEFAULT_RESAMPLES,
    confidence: float = 0.95,
    seed: int = 0,
) -> tuple[float, float]:
    """Percentile bootstrap CI of the mean paired difference, resampling items."""
    n = len(diffs)
    if n == 0:
        raise StatsError("cannot bootstrap an empty set of differences")
    if n == 1:
        # One item carries no information about between-item variance. Saying so beats
        # emitting a zero-width interval that looks like certainty.
        return (float("-inf"), float("inf"))

    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(resamples):
        total = 0.0
        for _ in range(n):
            total += diffs[rng.randrange(n)]
        means.append(total / n)
    means.sort()

    tail = (1.0 - confidence) / 2.0
    lo = means[_percentile_index(len(means), tail)]
    hi = means[_percentile_index(len(means), 1.0 - tail)]
    return lo, hi


def permutation_p(
    diffs: Sequence[float], *, resamples: int = DEFAULT_RESAMPLES, seed: int = 0
) -> float:
    """Two-sided paired permutation (sign-flip) test on the mean difference.

    Preferred over a bootstrap p-value: under the null "this factor changed nothing", the
    sign of each item's paired difference is exchangeable, which is exactly what a sign
    flip simulates.
    """
    n = len(diffs)
    if n == 0:
        raise StatsError("cannot test an empty set of differences")
    observed = abs(_mean(diffs))
    if observed == 0.0:
        return 1.0

    rng = random.Random(seed)
    at_least_as_extreme = 0
    for _ in range(resamples):
        total = 0.0
        for d in diffs:
            total += d if rng.random() < 0.5 else -d
        if abs(total / n) >= observed - 1e-12:
            at_least_as_extreme += 1
    return (1.0 + at_least_as_extreme) / (resamples + 1.0)


def holm(p_values: Sequence[float]) -> tuple[float, ...]:
    """Holm-Bonferroni step-down adjustment, preserving input order."""
    m = len(p_values)
    if m == 0:
        return ()
    order = sorted(range(m), key=lambda i: p_values[i])
    adjusted = [0.0] * m
    running = 0.0
    for rank, idx in enumerate(order):
        candidate = min(1.0, (m - rank) * p_values[idx])
        running = max(running, candidate)
        adjusted[idx] = running
    return tuple(adjusted)


def mde(diffs: Sequence[float], *, confidence: float = 0.95) -> float:
    """Minimum detectable effect at 80% power for this run's N, on the 0..1 scale.

    Reported so a null result is interpretable: an effect smaller than this would not have
    been detected, whatever the truth. Uses the observed standard deviation of the paired
    differences, so it describes the run that actually happened rather than an assumed one.
    """
    n = len(diffs)
    if n < 2:
        return float("inf")
    sd = _stdev(diffs)
    if sd == 0.0:
        return 0.0
    z = Z_ALPHA if confidence == 0.95 else _z_two_sided(confidence)
    return (z + Z_POWER) * sd / math.sqrt(n)


def compute_effect(
    label: str,
    arm: Mapping[str, float],
    control: Mapping[str, float],
    *,
    repeats: int,
    resamples: int = DEFAULT_RESAMPLES,
    confidence: float = 0.95,
    seed: int = 0,
) -> Effect:
    """Everything reportable about one arm, computed together.

    ``p_holm`` is initialised to the raw p-value; :func:`apply_holm` corrects a whole
    family of effects at once, once the sweep knows how many arms it ran.
    """
    items, diffs = paired_differences(arm, control)
    lo, hi = bootstrap_ci(diffs, resamples=resamples, confidence=confidence, seed=seed)
    p = permutation_p(diffs, resamples=resamples, seed=seed + 1)
    return Effect(
        label=label,
        arm_mean=_mean([arm[i] for i in items]),
        control_mean=_mean([control[i] for i in items]),
        delta=_mean(diffs),
        ci_low=lo,
        ci_high=hi,
        p_value=p,
        p_holm=p,
        n_items=len(items),
        repeats=repeats,
        confidence=confidence,
    )


def apply_holm(effects: Sequence[Effect]) -> tuple[Effect, ...]:
    """Return the same effects with ``p_holm`` corrected across the family."""
    from dataclasses import replace

    adjusted = holm([e.p_value for e in effects])
    return tuple(replace(e, p_holm=a) for e, a in zip(effects, adjusted, strict=True))


# --------------------------------------------------------------------------------------
# Small numeric helpers (stdlib only, so the package has no runtime dependencies)
# --------------------------------------------------------------------------------------


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _stdev(values: Sequence[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mu = _mean(values)
    return math.sqrt(sum((v - mu) ** 2 for v in values) / (n - 1))


def _percentile_index(n: int, q: float) -> int:
    idx = round(q * (n - 1))
    return max(0, min(n - 1, idx))


def _z_two_sided(confidence: float) -> float:
    """Inverse normal CDF at ``1 - (1-confidence)/2``, via bisection on ``math.erf``."""
    target = 1.0 - (1.0 - confidence) / 2.0
    lo, hi = 0.0, 10.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if 0.5 * (1.0 + math.erf(mid / math.sqrt(2.0))) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0
