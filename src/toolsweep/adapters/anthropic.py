"""Anthropic ``tools`` array adapter (``{"name", "description", "input_schema"}``)."""

from __future__ import annotations

from typing import Any

from ..catalogue import Catalogue, CatalogueError, Tool, stamp_origin_paths
from ._schema import params_from_json_schema, params_to_json_schema, require_object

FORMAT = "anthropic"


def load(payload: Any) -> Catalogue:
    entries = _locate_tools(payload)
    tools: list[Tool] = []
    for index, raw in enumerate(entries):
        obj = require_object(raw, f"tools[{index}]")
        schema = require_object(obj.get("input_schema", {}), f"tools[{index}].input_schema")
        params, not_for = params_from_json_schema(schema)
        tools.append(
            Tool(
                name=str(obj["name"]),
                description=str(obj.get("description", "")),
                params=stamp_origin_paths(params),
                not_for=not_for,
            )
        )
    return Catalogue(tools=tuple(tools))


def dump(cat: Catalogue, *, extensions: bool = False) -> list[dict[str, Any]]:
    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": params_to_json_schema(t, extensions=extensions),
        }
        for t in cat.tools
    ]


def _locate_tools(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return list(payload)
    obj = require_object(payload, "catalogue")
    inner = obj.get("tools")
    if isinstance(inner, list):
        return list(inner)
    raise CatalogueError("Anthropic catalogue must be a list of tools or have a 'tools' list")
