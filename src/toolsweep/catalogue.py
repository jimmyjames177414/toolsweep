"""Canonical, protocol-neutral model of a tool catalogue.

Every factor is a pure function ``Catalogue -> Catalogue``. Three provenance fields are
what make that safe to score:

* ``Tool.origin``          - the tool's name in the as-authored catalogue.
* ``Param.origin_path``    - the parameter's dotted path in the as-authored catalogue.
* ``EnumValue.origin_code`` - the enum member's value in the as-authored catalogue.

They exist because of the single easiest way to ship a silently broken benchmark:
renaming a tool changes the expected label. A suite says ``expected_tool: get_customer``;
after ``naming.synonyms`` that tool is called ``get_customer_by_id``, and a literal
string comparison scores every naming experiment at zero while looking perfectly healthy.
So expected labels and expected arguments are always written in *origin* space and
resolved into the presented catalogue through the maps below. See
``tests/test_rename_map.py``, which fails if that regresses.

Provenance is run state, not catalogue content: it is never serialised onto the wire, or
the model would see the pre-rename names and the experiment would be meaningless.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal, cast, get_args

ParamType = Literal["string", "integer", "number", "boolean", "array", "object"]

PARAM_TYPES: frozenset[str] = frozenset(get_args(ParamType))

# The intersection of what OpenAI, Anthropic and MCP accept as a tool name.
TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class CatalogueError(ValueError):
    """Raised when a catalogue is structurally invalid."""


@dataclass(frozen=True)
class EnumValue:
    """One member of a parameter's enumeration.

    ``code`` is what goes on the wire; ``label`` is the human phrasing. For most
    catalogues they are identical, which makes the ``enum.wording`` factor inert - a
    state toolsweep reports rather than silently scoring as "no effect".
    """

    code: str
    label: str = ""
    origin_code: str = ""

    def __post_init__(self) -> None:
        if not self.code:
            raise CatalogueError("enum value code must not be empty")
        if not self.label:
            object.__setattr__(self, "label", self.code)
        if not self.origin_code:
            object.__setattr__(self, "origin_code", self.code)


@dataclass(frozen=True)
class Param:
    """One parameter of one tool, in canonical form."""

    name: str
    type: ParamType = "string"
    description: str = ""
    required: bool = False
    #: The author's "this one genuinely cannot be omitted" flag. ``None`` means "same as
    #: ``required``", which is what makes ``params.required=minimal_required`` inert on a
    #: catalogue that never distinguished the two.
    essential: bool | None = None
    enum: tuple[EnumValue, ...] = ()
    properties: tuple[Param, ...] = ()
    item_type: ParamType | None = None
    origin_path: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise CatalogueError("parameter name must not be empty")
        if self.type not in PARAM_TYPES:
            raise CatalogueError(f"unknown parameter type {self.type!r} on {self.name!r}")
        if self.properties and self.type != "object":
            raise CatalogueError(f"parameter {self.name!r} has properties but type {self.type!r}")
        if not self.origin_path:
            object.__setattr__(self, "origin_path", self.name)

    @property
    def is_essential(self) -> bool:
        """Whether the author marked this parameter as genuinely indispensable."""
        return self.required if self.essential is None else self.essential


@dataclass(frozen=True)
class Tool:
    """One tool, in canonical form."""

    name: str
    description: str = ""
    params: tuple[Param, ...] = ()
    #: Authored "when NOT to use this". Carried separately from ``description`` so the
    #: ``description.negative`` factor can add and remove it without guessing.
    not_for: str = ""
    origin: str = ""

    def __post_init__(self) -> None:
        if not TOOL_NAME_RE.match(self.name):
            raise CatalogueError(
                f"tool name {self.name!r} is not accepted by every target protocol "
                f"(must match {TOOL_NAME_RE.pattern})"
            )
        names = [p.name for p in self.params]
        if len(set(names)) != len(names):
            raise CatalogueError(f"tool {self.name!r} has duplicate parameter names")
        if not self.origin:
            object.__setattr__(self, "origin", self.name)


@dataclass(frozen=True)
class Catalogue:
    """An ordered set of tools presented to a model as one unit."""

    tools: tuple[Tool, ...]
    #: Used by ``naming.scheme=verbose`` as a namespace prefix.
    namespace: str = "api"

    def __post_init__(self) -> None:
        names = [t.name for t in self.tools]
        if len(set(names)) != len(names):
            dupes = sorted({n for n in names if names.count(n) > 1})
            raise CatalogueError(f"duplicate tool names: {dupes}")
        origins = [t.origin for t in self.tools]
        if len(set(origins)) != len(origins):
            dupes = sorted({o for o in origins if origins.count(o) > 1})
            raise CatalogueError(f"duplicate tool origins: {dupes}")

    def __len__(self) -> int:
        return len(self.tools)

    @property
    def names(self) -> tuple[str, ...]:
        """Presented names, in catalogue order."""
        return tuple(t.name for t in self.tools)

    @property
    def origins(self) -> tuple[str, ...]:
        """As-authored names, in catalogue order."""
        return tuple(t.origin for t in self.tools)

    def by_name(self, name: str) -> Tool | None:
        for t in self.tools:
            if t.name == name:
                return t
        return None

    def by_origin(self, origin: str) -> Tool | None:
        for t in self.tools:
            if t.origin == origin:
                return t
        return None

    def rename_map(self) -> dict[str, str]:
        """as-authored name -> presented name, for tools still in the catalogue."""
        return {t.origin: t.name for t in self.tools}

    def inverse_rename_map(self) -> dict[str, str]:
        """presented name -> as-authored name."""
        return {t.name: t.origin for t in self.tools}

    def resolve_tool(self, origin: str) -> str | None:
        """The presented name of an as-authored tool, or ``None`` if it was dropped.

        This is the function that stands between toolsweep and a silently broken
        naming experiment. Scoring code must call it; it must never compare an
        ``expected_tool`` to a response literally.
        """
        tool = self.by_origin(origin)
        return None if tool is None else tool.name

    def with_tools(self, tools: Sequence[Tool]) -> Catalogue:
        return replace(self, tools=tuple(tools))


# --------------------------------------------------------------------------------------
# Parameter tree helpers
# --------------------------------------------------------------------------------------


def walk_params(params: Sequence[Param], prefix: str = "") -> Iterator[tuple[str, Param]]:
    """Yield ``(dotted_path, param)`` for every parameter, depth first."""
    for p in params:
        path = f"{prefix}{p.name}"
        yield path, p
        if p.properties:
            yield from walk_params(p.properties, f"{path}.")


def stamp_origin_paths(params: Sequence[Param], prefix: str = "") -> tuple[Param, ...]:
    """Rewrite ``origin_path`` on a parameter tree to full dotted paths.

    Called by loaders once, on the as-authored catalogue. Factors preserve whatever this
    stamped; they never recompute it.
    """
    out: list[Param] = []
    for p in params:
        path = f"{prefix}{p.name}"
        out.append(
            replace(
                p,
                origin_path=path,
                properties=stamp_origin_paths(p.properties, f"{path}."),
            )
        )
    return tuple(out)


def reset_origins(cat: Catalogue) -> Catalogue:
    """Re-stamp all provenance from the *current* names.

    Only used by adapter round-trip tests: provenance is run state and never crosses a
    serialisation boundary, so ``load(dump(cat))`` can only ever be compared to
    ``reset_origins(cat)``.
    """
    tools: list[Tool] = []
    for t in cat.tools:
        tools.append(
            replace(
                t,
                origin=t.name,
                params=stamp_origin_paths(_reset_enum_origins(t.params)),
            )
        )
    return cat.with_tools(tools)


def _reset_enum_origins(params: Sequence[Param]) -> tuple[Param, ...]:
    out: list[Param] = []
    for p in params:
        out.append(
            replace(
                p,
                enum=tuple(EnumValue(code=e.code, label=e.label) for e in p.enum),
                properties=_reset_enum_origins(p.properties),
                origin_path="",
            )
        )
    return tuple(out)


def param_path_map(tool: Tool) -> dict[str, str]:
    """as-authored dotted path -> presented dotted path, for one tool."""
    return {p.origin_path: path for path, p in walk_params(tool.params)}


def find_param_by_origin(tool: Tool, origin_path: str) -> tuple[str, Param] | None:
    """Locate a parameter by its as-authored dotted path."""
    for path, p in walk_params(tool.params):
        if p.origin_path == origin_path:
            return path, p
    return None


# --------------------------------------------------------------------------------------
# Argument-space resolution (the same trap as tool names, one level down)
# --------------------------------------------------------------------------------------


def flatten_args(args: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    """Turn a nested argument object into ``{dotted_path: leaf_value}``."""
    out: dict[str, Any] = {}
    for key, value in args.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            nested = cast("dict[str, Any]", value)
            if nested:
                out.update(flatten_args(nested, f"{path}."))
                continue
        out[path] = value
    return out


def nest_args(flat: Mapping[str, Any]) -> dict[str, Any]:
    """Inverse of :func:`flatten_args`."""
    out: dict[str, Any] = {}
    for path, value in flat.items():
        parts = path.split(".")
        cursor = out
        for part in parts[:-1]:
            nxt = cursor.setdefault(part, {})
            if not isinstance(nxt, dict):
                raise CatalogueError(f"argument path {path!r} collides with a scalar")
            cursor = cast("dict[str, Any]", nxt)
        cursor[parts[-1]] = value
    return out


def resolve_args(tool: Tool, expected_args: Mapping[str, Any]) -> dict[str, Any]:
    """Map arguments written in as-authored space into the presented tool's space.

    Handles both halves of the transformation: parameter paths move under
    ``schema.nesting``, and enum members change value under ``enum.wording``. An
    as-authored path with no counterpart in the presented tool is dropped, which is what
    a factor that removes a parameter should produce.
    """
    flat = flatten_args(expected_args)
    resolved: dict[str, Any] = {}
    for origin_path, value in flat.items():
        located = find_param_by_origin(tool, origin_path)
        if located is None:
            continue
        current_path, param = located
        resolved[current_path] = _resolve_enum_value(param, value)
    return nest_args(resolved)


def _resolve_enum_value(param: Param, value: Any) -> Any:
    if not param.enum or not isinstance(value, str):
        return value
    for member in param.enum:
        if member.origin_code == value:
            return member.code
    return value
