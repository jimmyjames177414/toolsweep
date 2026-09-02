"""Factor ``catalogue.size`` - how many tools the model is shown at once.

Levels are derived from the catalogue: ``n=6``, ``n=10``, ``n=14`` and so on, with the
full catalogue as the control.

**Pinned tools are never dropped.** Every tool the task suite names as an ``expected_tool``
is present in every subset, because a subset that removed the answer would score zero for
reasons that have nothing to do with catalogue size. The runner supplies the pinned set
from the suite; ``apply`` stays a pure function of the catalogue given that configuration.

Subsets are chosen deterministically: pinned tools first, then the remaining tools in a
seeded shuffle order, and the result is re-ordered back into the catalogue's original
order so this factor varies *size* and not *position*.
"""

from __future__ import annotations

import random
from typing import ClassVar

from ..catalogue import Catalogue
from .base import Factor, FactorContext, select_tools


class CatalogueSizeFactor(Factor):
    id: ClassVar[str] = "catalogue.size"
    control_level: ClassVar[str] = "full"
    cxs_kind: ClassVar[str] = "remove"
    summary: ClassVar[str] = "number of tools exposed at once (target tool always present)"

    def __init__(self, ctx: FactorContext) -> None:
        super().__init__(ctx)
        total = len(ctx.catalogue)
        # Sizes are spaced over the *removable* range, not over the whole catalogue.
        # Fixed fractions of the total collapse to a single level the moment the suite
        # pins most of the catalogue, and they miss the most informative point: the
        # minimal catalogue containing exactly what the suite needs.
        floor = max(len(ctx.pinned_tools), 1)
        removable = total - floor
        sizes: set[int] = set()
        if removable >= 1:
            sizes.add(floor)
        if removable >= 3:
            sizes.add(floor + round(removable / 2))
        self._sizes: tuple[int, ...] = tuple(sorted(n for n in sizes if n < total))
        self._total = total
        self._pinned_count = floor

    @property
    def levels(self) -> tuple[str, ...]:
        return (self.control_level, *(f"n={n}" for n in self._sizes))

    @property
    def unavailable_reason(self) -> str | None:
        if self._sizes:
            return None
        return (
            f"the suite expects all {self._pinned_count} of the {self._total} tools in "
            f"this catalogue, so no smaller subset can be shown without dropping an answer"
        )

    def apply(self, level: str, cat: Catalogue) -> Catalogue:
        self.check_level(level)
        if level == self.control_level:
            return cat
        return select_tools(cat, self._subset(int(level[2:]), cat))

    def describe(self, level: str) -> str:
        if level == self.control_level:
            return f"All {len(self.ctx.catalogue)} tools presented."
        n = int(level[2:])
        return (
            f"Only {n} of {len(self.ctx.catalogue)} tools presented, chosen by seeded "
            f"sample with every tool the suite expects pinned in."
        )

    def _subset(self, n: int, cat: Catalogue) -> tuple[str, ...]:
        # Pinned tools are matched on `origin`: the suite names tools as authored, and
        # this factor has to work the same whether or not a rename ran first.
        pinned = [t.name for t in cat.tools if t.origin in self.ctx.pinned_tools]
        if len(pinned) > n:
            raise ValueError(
                f"catalogue.size level n={n} is smaller than the {len(pinned)} tools the "
                f"suite expects; nothing the suite asks for may be dropped"
            )
        rest = [t.name for t in cat.tools if t.origin not in self.ctx.pinned_tools]
        rng = random.Random(f"{self.ctx.seed}:catalogue.size:{n}")
        rng.shuffle(rest)
        return tuple(pinned) + tuple(rest[: n - len(pinned)])
