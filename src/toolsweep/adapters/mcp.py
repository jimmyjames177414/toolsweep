"""MCP ``tools/list`` adapter.

Accepts either a full ``tools/list`` response (``{"tools": [...]}``), a JSON-RPC envelope
(``{"result": {"tools": [...]}}``) or a bare list of tool objects, because all three are
what people actually have on disk.
"""

from __future__ import annotations

from typing import Any

from ..catalogue import Catalogue, Tool, stamp_origin_paths
from ._schema import params_from_json_schema, params_to_json_schema, require_object

FORMAT = "mcp"


def load(payload: Any) -> Catalogue:
    tools_payload = _locate_tools(payload)
    tools: list[Tool] = []
    for index, raw in enumerate(tools_payload):
        obj = require_object(raw, f"tools[{index}]")
        schema = require_object(obj.get("inputSchema", {}), f"tools[{index}].inputSchema")
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


def dump(cat: Catalogue, *, extensions: bool = False) -> dict[str, Any]:
    return {
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": params_to_json_schema(t, extensions=extensions),
            }
            for t in cat.tools
        ]
    }


def _locate_tools(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return list(payload)
    obj = require_object(payload, "catalogue")
    if "tools" in obj:
        inner = obj["tools"]
        if isinstance(inner, list):
            return list(inner)
    result = obj.get("result")
    if isinstance(result, dict) and isinstance(result.get("tools"), list):
        return list(result["tools"])
    raise ValueError("MCP catalogue must contain a 'tools' list")
