"""Factor ``enum.wording`` - the words a parameter's enumeration puts on the wire.

Levels
------
``as_authored``        present each enum member's authored wire value (control)
``alternate_wording``  present each member's alternative phrasing instead, and append a
                       legend mapping the phrasing back to the authored value

An ``EnumValue`` carries a ``code`` (what goes on the wire) and a ``label`` (the
alternative phrasing). The usual authoring is ``code: "ACT"``, ``label: "active"``, so the
contrast measured is raw codes versus human phrasing. A catalogue authored the other way
round measures the same contrast in the other direction; the level is named after the
*field* it presents, not after a judgement about which wording is more human.

There is deliberately no ``raw_codes`` level. The authored wire value **is** the raw code,
so such a level would be identical to the control on every catalogue - a permanently inert
arm that would look like a measured null result.

Where a catalogue never distinguished code from label, this factor is inert. The runner
reports that rather than spending calls to measure a guaranteed zero.

``EnumValue.origin_code`` survives both levels, so an ``expected_args`` value written
against the authored catalogue still resolves after the wording changes. Same trap as tool
renaming, one level down.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import ClassVar

from ..catalogue import Catalogue, EnumValue, Param, Tool
from .base import Factor, map_tools

LEVELS = ("as_authored", "alternate_wording")

_LEGEND = " Values: "


class EnumWordingFactor(Factor):
    id: ClassVar[str] = "enum.wording"
    control_level: ClassVar[str] = "as_authored"
    summary: ClassVar[str] = "enum members as authored codes vs their alternative phrasing"

    @property
    def levels(self) -> tuple[str, ...]:
        return LEVELS

    def apply(self, level: str, cat: Catalogue) -> Catalogue:
        self.check_level(level)
        if level == self.control_level:
            return cat
        return map_tools(cat, _apply_tool)

    def describe(self, level: str) -> str:
        if level == self.control_level:
            return "Enum members presented with their authored wire values."
        return (
            "Every enum member presented with its alternative phrasing instead of its "
            "authored wire value, with a legend mapping each phrase back to that value "
            "appended to the parameter description."
        )


def _apply_tool(tool: Tool) -> Tool:
    return replace(tool, params=_apply_params(tool.params))


def _apply_params(params: Sequence[Param]) -> tuple[Param, ...]:
    out: list[Param] = []
    for param in params:
        nested = _apply_params(param.properties) if param.properties else ()
        if not param.enum:
            out.append(replace(param, properties=nested))
            continue

        members = tuple(
            EnumValue(code=e.label, label=e.label, origin_code=e.origin_code) for e in param.enum
        )
        description = _strip_legend(param.description)
        if any(e.label != e.origin_code for e in param.enum):
            legend = ", ".join(f"{e.label} = {e.origin_code}" for e in param.enum)
            description = f"{description.rstrip()}{_LEGEND}{legend}."
        out.append(replace(param, enum=members, description=description, properties=nested))
    return tuple(out)


def _strip_legend(description: str) -> str:
    return description.split(_LEGEND, 1)[0]
