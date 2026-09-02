"""Shared JSON Schema <-> canonical parameter conversion.

All four supported protocols describe arguments with JSON Schema and differ only in the
envelope around it, so the interesting half of every adapter lives here.

Three pieces of canonical state have no representation in any wire format: the authored
"when NOT to use this" text, the ``essential`` flag, and enum labels. They are carried in
an ``x-toolsweep`` block, which JSON Schema permits (unknown keywords are ignored by
validators) and which is written only when ``extensions=True``. Requests sent to a model
always use ``extensions=False`` - the extension block is for catalogue files, not for the
wire.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from ..catalogue import (
    PARAM_TYPES,
    CatalogueError,
    EnumValue,
    Param,
    ParamType,
    Tool,
    walk_params,
)

EXTENSION_KEY = "x-toolsweep"


def params_to_json_schema(tool: Tool, *, extensions: bool = False) -> dict[str, Any]:
    """Render a tool's parameters as a JSON Schema object."""
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {p.name: _param_to_schema(p) for p in tool.params},
        "required": [p.name for p in tool.params if p.required],
    }
    if extensions:
        block = _extension_block(tool)
        if block:
            schema[EXTENSION_KEY] = block
    return schema


def params_from_json_schema(schema: Mapping[str, Any]) -> tuple[tuple[Param, ...], str]:
    """Parse a JSON Schema object into canonical parameters plus any ``not_for`` text."""
    raw_props = schema.get("properties", {})
    if not isinstance(raw_props, dict):
        raise CatalogueError("inputSchema.properties must be an object")
    props = cast("dict[str, Any]", raw_props)
    required = _string_list(schema.get("required", []), "required")

    extension = schema.get(EXTENSION_KEY, {})
    if not isinstance(extension, dict):
        raise CatalogueError(f"{EXTENSION_KEY} must be an object")
    ext = cast("dict[str, Any]", extension)
    essential = _essential_map(ext.get("essential", {}))
    labels = _label_map(ext.get("enum_labels", {}))
    not_for = str(ext.get("not_for", ""))

    params = _params_from_properties(props, set(required), essential, labels, prefix="")
    return params, not_for


def _params_from_properties(
    props: Mapping[str, Any],
    required: set[str],
    essential: Mapping[str, bool],
    labels: Mapping[str, Mapping[str, str]],
    prefix: str,
) -> tuple[Param, ...]:
    out: list[Param] = []
    for name, raw in props.items():
        if not isinstance(raw, dict):
            raise CatalogueError(f"property {name!r} must be an object")
        body = cast("dict[str, Any]", raw)
        path = f"{prefix}{name}"
        ptype = _param_type(body.get("type", "string"), path)

        nested: tuple[Param, ...] = ()
        if ptype == "object":
            raw_nested = body.get("properties", {})
            if not isinstance(raw_nested, dict):
                raise CatalogueError(f"property {path!r} has a non-object 'properties'")
            nested = _params_from_properties(
                cast("dict[str, Any]", raw_nested),
                set(_string_list(body.get("required", []), f"{path}.required")),
                essential,
                labels,
                prefix=f"{path}.",
            )

        item_type: ParamType | None = None
        items = body.get("items")
        if ptype == "array" and isinstance(items, dict):
            item_type = _param_type(cast("dict[str, Any]", items).get("type", "string"), path)

        enum_labels = labels.get(path, {})
        enum = tuple(
            EnumValue(code=code, label=enum_labels.get(code, code))
            for code in _string_list(body.get("enum", []), f"{path}.enum")
        )

        out.append(
            Param(
                name=name,
                type=ptype,
                description=str(body.get("description", "")),
                required=name in required,
                essential=essential.get(path),
                enum=enum,
                properties=nested,
                item_type=item_type,
            )
        )
    return tuple(out)


def _param_to_schema(param: Param) -> dict[str, Any]:
    body: dict[str, Any] = {"type": param.type}
    if param.description:
        body["description"] = param.description
    if param.enum:
        body["enum"] = [e.code for e in param.enum]
    if param.type == "object":
        body["properties"] = {p.name: _param_to_schema(p) for p in param.properties}
        body["required"] = [p.name for p in param.properties if p.required]
    if param.type == "array" and param.item_type is not None:
        body["items"] = {"type": param.item_type}
    return body


def _extension_block(tool: Tool) -> dict[str, Any]:
    block: dict[str, Any] = {}
    if tool.not_for:
        block["not_for"] = tool.not_for

    # Recorded as a path -> bool map, not a list of paths. ``essential: false`` on a
    # parameter the author also marked ``required`` is the entire point of the
    # ``params.required=minimal_required`` level, so a set-membership encoding would
    # quietly delete the only interesting case.
    essential = {
        path: p.essential for path, p in walk_params(tool.params) if p.essential is not None
    }
    if essential:
        block["essential"] = essential

    labels = {
        path: {e.code: e.label for e in p.enum}
        for path, p in walk_params(tool.params)
        if any(e.label != e.code for e in p.enum)
    }
    if labels:
        block["enum_labels"] = labels
    return block


def _param_type(value: Any, where: str) -> ParamType:
    if not isinstance(value, str) or value not in PARAM_TYPES:
        raise CatalogueError(f"unsupported JSON Schema type {value!r} at {where!r}")
    return cast(ParamType, value)


def _string_list(value: Any, where: str) -> list[str]:
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return cast("list[str]", value)
    raise CatalogueError(f"{where} must be a list of strings")


def _essential_map(value: Any) -> dict[str, bool]:
    if not isinstance(value, dict):
        raise CatalogueError("essential must be an object mapping paths to booleans")
    out: dict[str, bool] = {}
    for path, flag in cast("dict[str, Any]", value).items():
        if not isinstance(flag, bool):
            raise CatalogueError(f"essential[{path!r}] must be a boolean")
        out[str(path)] = flag
    return out


def _label_map(value: Any) -> dict[str, dict[str, str]]:
    if not isinstance(value, dict):
        raise CatalogueError("enum_labels must be an object")
    out: dict[str, dict[str, str]] = {}
    for path, mapping in cast("dict[str, Any]", value).items():
        if not isinstance(mapping, dict):
            raise CatalogueError(f"enum_labels[{path!r}] must be an object")
        out[path] = {str(k): str(v) for k, v in cast("dict[str, Any]", mapping).items()}
    return out


def require_list(payload: Any, where: str) -> Sequence[Any]:
    if not isinstance(payload, list):
        raise CatalogueError(f"{where} must be a list")
    return payload


def require_object(payload: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(payload, dict):
        raise CatalogueError(f"{where} must be an object")
    return cast("dict[str, Any]", payload)
