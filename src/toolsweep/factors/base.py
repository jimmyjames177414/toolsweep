"""The factor contract.

A factor is a named schema decision with two or more *levels*. Applying a level is a pure
function ``Catalogue -> Catalogue``: no network, no clock, no global state. That is what
makes the whole sweep testable offline, and it is why the largest test file in the repo is
``tests/test_factors.py``.

Three properties are contractual and tested for every factor at every level:

1. **Purity** - same input, same output, every time.
2. **Idempotency** - ``apply(l, apply(l, c)) == apply(l, c)``. A level describes a
   destination, not a step. This is why there is no ``reverse`` ordering level: reversal
   is an operation, and applying it twice undoes it.
3. **Validity** - the result is always a loadable catalogue in every adapter format.

A factor may be *inert* on a given catalogue: ``enum.wording`` changes nothing if no
parameter has an enum. The runner detects that by comparing the transformed catalogue to
the control and reports it, rather than spending calls to measure a guaranteed zero.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import ClassVar

from ..catalogue import Catalogue, Tool


@dataclass(frozen=True)
class FactorContext:
    """Everything a factor may depend on besides the catalogue itself.

    Passing these at construction time - rather than into ``apply`` - is what keeps
    ``apply`` a pure function of the catalogue. ``catalogue.size`` needs to know which
    tools the suite expects so it never drops one; that is configuration, not input.
    """

    catalogue: Catalogue
    #: Tools the suite names as ``expected_tool``. Never removed by any factor.
    pinned_tools: frozenset[str] = frozenset()
    seed: int = 0


class Factor(ABC):
    """One schema decision, varied across levels."""

    #: Stable identifier used on the CLI and in the CXS intervention id.
    id: ClassVar[str]
    #: The level that leaves the catalogue as authored. Always present in ``levels``.
    control_level: ClassVar[str]
    #: What kind of CXS intervention non-control levels are.
    cxs_kind: ClassVar[str] = "replace"
    #: One line, shown by ``toolsweep factors``.
    summary: ClassVar[str]

    def __init__(self, ctx: FactorContext) -> None:
        self.ctx = ctx

    @property
    @abstractmethod
    def levels(self) -> tuple[str, ...]:
        """All levels, control first. Derived from the catalogue for some factors."""

    @abstractmethod
    def apply(self, level: str, cat: Catalogue) -> Catalogue:
        """Return the catalogue as it would be under ``level``. Pure."""

    @abstractmethod
    def describe(self, level: str) -> str:
        """A sentence describing what this level did, for the CXS intervention record."""

    @property
    def implementation(self) -> str:
        """CXS ``Intervention.implementation`` value."""
        return f"{type(self).__module__}:{type(self).__name__}:v1"

    @property
    def unavailable_reason(self) -> str | None:
        """Why this factor has nothing to vary on this catalogue, if so.

        A factor with no non-control level must never just vanish from a report. "This
        could not be measured here, and here is why" is a result; silence looks like the
        factor was measured and found to do nothing.
        """
        if len(self.levels) > 1:
            return None
        return "this factor has no level that differs from the control on this catalogue"

    def check_level(self, level: str) -> None:
        if level not in self.levels:
            raise ValueError(f"factor {self.id!r} has no level {level!r}; expected {self.levels}")


# --------------------------------------------------------------------------------------
# Helpers shared by factor implementations
# --------------------------------------------------------------------------------------


def rename_tools(cat: Catalogue, new_names: Mapping[str, str]) -> Catalogue:
    """Rename tools by *current* name, preserving ``origin`` on every tool.

    Preserving ``origin`` is not an optimisation. It is the mechanism that lets an
    expected label survive a rename; a factor that rebuilt tools from scratch would
    silently reset provenance and score every naming experiment at zero.
    """
    tools: list[Tool] = []
    for tool in cat.tools:
        target = new_names.get(tool.name, tool.name)
        tools.append(tool if target == tool.name else replace(tool, name=target))
    return cat.with_tools(tools)


def map_tools(cat: Catalogue, fn: Callable[[Tool], Tool]) -> Catalogue:
    """Apply a per-tool transform, preserving catalogue order."""
    return cat.with_tools([fn(t) for t in cat.tools])


def select_tools(cat: Catalogue, keep: Sequence[str]) -> Catalogue:
    """Keep only the named tools, in the catalogue's original order."""
    wanted = set(keep)
    return cat.with_tools([t for t in cat.tools if t.name in wanted])
