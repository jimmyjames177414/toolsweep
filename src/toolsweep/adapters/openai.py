"""OpenAI ``tools`` array adapter (``{"type": "function", "function": {...}}``)."""

from __future__ import annotations

from typing import Any

from ..catalogue import Catalogue, CatalogueError, Tool, stamp_origin_paths
from ._schema import params_from_json_schema, params_to_json_schema, require_object

FORMAT = "openai"


def load(payload: Any) -> Catalogue:
    entries = _locate_tools(payload)
    tools: list[Tool] = []
    for index, raw in enumerate(entries):
        obj = require_object(raw, f"tools[{index}]")
        fn = require_object(obj.get("function", obj), f"tools[{index}].function")
        schema = require_object(fn.get("parameters", {}), f"tools[{index}].function.parameters")
        params, not_for = params_from_json_schema(schema)
        tools.append(
            Tool(
                name=str(fn["name"]),
                description=str(fn.get("description", "")),
                params=stamp_origin_paths(params),
                not_for=not_for,
            )
        )
    return Catalogue(tools=tuple(tools))


def dump(cat: Catalogue, *, extensions: bool = False) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": params_to_json_schema(t, extensions=extensions),
            },
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
    raise CatalogueError("OpenAI catalogue must be a list of tools or have a 'tools' list")
