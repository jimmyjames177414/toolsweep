"""Factor ``schema.nesting`` - flat argument lists versus grouped objects.

Levels
------
``as_authored``  leave the parameter tree alone (control)
``flat``         hoist every nested property to the top level as ``parent_child``
``nested``       group top-level parameters sharing an underscore prefix into an object

Required-ness is preserved in both directions. Flattening a required child of an optional
parent produces an *optional* top-level parameter, because the child was only required
when its parent was present; nesting marks the created object required when any of its
children were.

``Param.origin_path`` is preserved through both directions, which is what lets
``expected_args`` written against the authored shape still resolve after the tree moves.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import ClassVar

from ..catalogue import Catalogue, Param, Tool, walk_params
from ._text import tokenize
from .base import Factor, map_tools

LEVELS = ("as_authored", "flat", "nested")

#: A prefix must be shared by at least this many parameters before nesting groups them.
MIN_GROUP = 2


class SchemaNestingFactor(Factor):
    id: ClassVar[str] = "schema.nesting"
    control_level: ClassVar[str] = "as_authored"
    summary: ClassVar[str] = "flat vs nested argument objects"

    @property
    def levels(self) -> tuple[str, ...]:
        return LEVELS

    def apply(self, level: str, cat: Catalogue) -> Catalogue:
        self.check_level(level)
        if level == self.control_level:
            return cat
        if level == "flat":
            return map_tools(cat, _flatten_tool)
        return map_tools(cat, _nest_tool)

    def describe(self, level: str) -> str:
        return {
            "as_authored": "Argument schemas left exactly as authored.",
            "flat": "Every nested argument object hoisted to a flat parent_child parameter.",
            "nested": (
                "Top-level parameters sharing an underscore prefix grouped into a nested "
                "object named after that prefix."
            ),
        }[level]


# --------------------------------------------------------------------------------------
# flat
# --------------------------------------------------------------------------------------


def _flatten_tool(tool: Tool) -> Tool:
    if not any(p.properties for p in tool.params):
        return tool
    return replace(tool, params=_flatten(tool.params, prefix="", parent_required=True))


def _flatten(params: Sequence[Param], prefix: str, parent_required: bool) -> tuple[Param, ...]:
    out: list[Param] = []
    for param in params:
        name = f"{prefix}{param.name}"
        required = param.required and parent_required
        if param.properties:
            out.extend(_flatten(param.properties, f"{name}_", required))
            continue
        out.append(replace(param, name=name, required=required, properties=()))
    return tuple(out)


# --------------------------------------------------------------------------------------
# nested
# --------------------------------------------------------------------------------------


def _nest_tool(tool: Tool) -> Tool:
    groups = _group_prefixes(tool.params)
    if not groups:
        return tool

    used: set[str] = set()
    out: list[Param] = []
    for param in tool.params:
        prefix = _prefix_of(param.name)
        if prefix is None or prefix not in groups:
            out.append(param)
            continue
        if prefix in used:
            continue
        used.add(prefix)
        members = groups[prefix]
        children = tuple(
            replace(p, name=p.name[len(prefix) + 1 :], required=p.required) for p in members
        )
        out.append(
            Param(
                name=prefix,
                type="object",
                description=f"Grouped {prefix} arguments.",
                required=any(p.required for p in members),
                properties=children,
                # A created container has no counterpart in the authored catalogue. Giving
                # it a synthetic origin_path keeps every *leaf* path resolvable, which is
                # all argument resolution walks.
                origin_path=f"__nested__.{prefix}",
            )
        )
    return replace(tool, params=tuple(out))


def _group_prefixes(params: Sequence[Param]) -> dict[str, tuple[Param, ...]]:
    """Top-level parameters that share an underscore prefix, keyed by that prefix."""
    buckets: dict[str, list[Param]] = {}
    existing = {p.name for p in params}
    for param in params:
        if param.properties:
            # Already nested; leave it be.
            continue
        prefix = _prefix_of(param.name)
        if prefix is None or prefix in existing:
            continue
        buckets.setdefault(prefix, []).append(param)
    return {k: tuple(v) for k, v in buckets.items() if len(v) >= MIN_GROUP}


def _prefix_of(name: str) -> str | None:
    tokens = tokenize(name)
    if len(tokens) < 2 or "_" not in name:
        return None
    return name.split("_", 1)[0]


def nested_leaf_paths(tool: Tool) -> tuple[str, ...]:
    """Every leaf parameter path, used by the validity tests."""
    return tuple(path for path, p in walk_params(tool.params) if not p.properties)
