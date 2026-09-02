"""The factor registry.

Adding a factor is deliberately a one-file change plus one line here - it is the
project's flagship ``good-first-issue``. A new factor must satisfy the three contracts in
``base.py`` (purity, idempotency, validity); ``tests/test_factors.py`` enforces all three
against every registered factor automatically, so a new entry is tested the moment it is
listed.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from .base import Factor, FactorContext
from .catalogue_size import CatalogueSizeFactor
from .description_length import DescriptionLengthFactor
from .description_negative import DescriptionNegativeFactor
from .enum_wording import EnumWordingFactor
from .naming_scheme import NamingSchemeFactor
from .naming_synonyms import NamingSynonymsFactor
from .params_required import ParamsRequiredFactor
from .schema_nesting import SchemaNestingFactor

FactorBuilder = Callable[[FactorContext], Factor]

#: The one list to append to when adding a factor. Everything else is derived from it,
#: including the contract tests, so a new entry cannot be half-registered.
FACTOR_CLASSES: tuple[type[Factor], ...] = (
    NamingSchemeFactor,
    NamingSynonymsFactor,
    DescriptionLengthFactor,
    DescriptionNegativeFactor,
    EnumWordingFactor,
    SchemaNestingFactor,
    ParamsRequiredFactor,
    CatalogueSizeFactor,
)

REGISTRY: dict[str, FactorBuilder] = {cls.id: cls for cls in FACTOR_CLASSES}

FACTOR_IDS: tuple[str, ...] = tuple(REGISTRY)

SUMMARIES: dict[str, str] = {cls.id: cls.summary for cls in FACTOR_CLASSES}


class UnknownFactorError(ValueError):
    """Raised for a ``--factors`` entry that names no registered factor."""


def build(factor_id: str, ctx: FactorContext) -> Factor:
    if factor_id not in REGISTRY:
        raise UnknownFactorError(
            f"unknown factor {factor_id!r}; known factors: {', '.join(FACTOR_IDS)}"
        )
    return REGISTRY[factor_id](ctx)


def parse_specs(specs: Sequence[str], ctx: FactorContext) -> list[tuple[Factor, tuple[str, ...]]]:
    """Turn ``--factors`` entries into ``(factor, levels_to_run)`` pairs.

    Accepted forms:

    * ``all``                          every registered factor, every non-control level
    * ``naming.synonyms``              one factor, every non-control level
    * ``naming.synonyms=distinct_verbs`` one factor, one level

    The control level is never returned: the unmodified catalogue is arm zero and is run
    exactly once for the whole sweep, so every factor is compared against the same
    control on the same items.
    """
    requested: list[str] = []
    for spec in specs:
        for part in spec.split(","):
            part = part.strip()
            if part:
                requested.append(part)
    if not requested or requested == ["all"]:
        requested = list(FACTOR_IDS)

    out: list[tuple[Factor, tuple[str, ...]]] = []
    for spec in requested:
        if spec == "all":
            raise UnknownFactorError("'all' cannot be combined with named factors")
        factor_id, _, level = spec.partition("=")
        factor = build(factor_id, ctx)
        if level:
            factor.check_level(level)
            if level == factor.control_level:
                raise UnknownFactorError(
                    f"{factor_id}={level} is the control level; the control arm is always "
                    f"run and cannot be requested as a treatment"
                )
            levels: tuple[str, ...] = (level,)
        else:
            levels = tuple(lvl for lvl in factor.levels if lvl != factor.control_level)
        out.append((factor, levels))
    return out


__all__ = [
    "FACTOR_IDS",
    "REGISTRY",
    "SUMMARIES",
    "Factor",
    "FactorContext",
    "UnknownFactorError",
    "build",
    "parse_specs",
]
