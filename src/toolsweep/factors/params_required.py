"""Factor ``params.required`` - how much of the argument list the schema demands.

Levels
------
``as_authored``       leave the required list alone (control)
``all_required``      mark every parameter required
``minimal_required``  keep only the parameters the author marked ``essential``

``minimal_required`` reads the ``essential`` flag, which defaults to ``required``. On a
catalogue that never set it the level is **inert**, and the runner says so. This is
deliberate: deriving "which required parameters are not really required" from names or
types would be guessing, and a guessed level produces a confident number about a decision
nobody made.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import ClassVar

from ..catalogue import Catalogue, Param, Tool
from .base import Factor, map_tools

LEVELS = ("as_authored", "all_required", "minimal_required")

RequiredPredicate = Callable[[Param], bool]


class ParamsRequiredFactor(Factor):
    id: ClassVar[str] = "params.required"
    control_level: ClassVar[str] = "as_authored"
    summary: ClassVar[str] = "every parameter required vs only the essential ones"

    @property
    def levels(self) -> tuple[str, ...]:
        return LEVELS

    def apply(self, level: str, cat: Catalogue) -> Catalogue:
        self.check_level(level)
        if level == self.control_level:
            return cat
        if level == "all_required":
            return map_tools(cat, lambda t: _set_required(t, _all))
        return map_tools(cat, lambda t: _set_required(t, _essential_only))

    def describe(self, level: str) -> str:
        return {
            "as_authored": "Required parameter lists left exactly as authored.",
            "all_required": "Every parameter of every tool marked required.",
            "minimal_required": (
                "Only parameters explicitly marked essential kept required; every other "
                "parameter made optional."
            ),
        }[level]


def _all(_: Param) -> bool:
    return True


def _essential_only(param: Param) -> bool:
    return param.is_essential


def _set_required(tool: Tool, predicate: RequiredPredicate) -> Tool:
    return replace(tool, params=_walk(tool.params, predicate))


def _walk(params: Sequence[Param], predicate: RequiredPredicate) -> tuple[Param, ...]:
    return tuple(
        replace(
            p,
            required=predicate(p),
            properties=_walk(p.properties, predicate) if p.properties else (),
        )
        for p in params
    )
