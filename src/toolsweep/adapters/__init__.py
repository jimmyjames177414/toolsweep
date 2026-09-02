"""Protocol adapters: every supported format converts *in* and *out*.

One canonical representation, four envelopes. Loading a catalogue in any format and
dumping it in any other is a supported operation, and the round trip is tested for every
pair (``tests/test_adapters.py``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ..catalogue import Catalogue, CatalogueError
from . import anthropic, jsonschema_fmt, mcp, openai


class LoadFn(Protocol):
    def __call__(self, payload: Any) -> Catalogue: ...


class DumpFn(Protocol):
    def __call__(self, cat: Catalogue, *, extensions: bool = False) -> Any: ...


@dataclass(frozen=True)
class Adapter:
    """One format's pair of conversions, bound explicitly.

    The implementations are modules, and mypy will not check a module against a Protocol
    in a container. Naming the two functions here keeps the registry fully typed instead
    of falling back to ``dict[str, Any]``, which would silently swallow a signature change
    in any adapter.
    """

    name: str
    load: LoadFn
    dump: DumpFn


ADAPTERS: dict[str, Adapter] = {
    mcp.FORMAT: Adapter(mcp.FORMAT, mcp.load, mcp.dump),
    openai.FORMAT: Adapter(openai.FORMAT, openai.load, openai.dump),
    anthropic.FORMAT: Adapter(anthropic.FORMAT, anthropic.load, anthropic.dump),
    jsonschema_fmt.FORMAT: Adapter(jsonschema_fmt.FORMAT, jsonschema_fmt.load, jsonschema_fmt.dump),
}

FORMATS: tuple[str, ...] = tuple(ADAPTERS)


def get(fmt: str) -> Adapter:
    if fmt not in ADAPTERS:
        raise CatalogueError(f"unknown catalogue format {fmt!r}; expected one of {FORMATS}")
    return ADAPTERS[fmt]


def load(payload: Any, fmt: str) -> Catalogue:
    return get(fmt).load(payload)


def dump(cat: Catalogue, fmt: str, *, extensions: bool = False) -> Any:
    return get(fmt).dump(cat, extensions=extensions)


def detect_format(payload: Any) -> str:
    """Guess a catalogue's format from its shape.

    Deliberately conservative: it refuses rather than guesses when a payload matches
    nothing, because silently loading a catalogue as the wrong protocol would drop
    parameters and quietly change what the sweep measures.
    """
    entries: list[Any]
    if isinstance(payload, list):
        entries = list(payload)
    elif isinstance(payload, dict):
        inner = payload.get("tools")
        if isinstance(inner, list):
            entries = list(inner)
        else:
            result = payload.get("result")
            if isinstance(result, dict) and isinstance(result.get("tools"), list):
                entries = list(result["tools"])
            else:
                raise CatalogueError("cannot detect catalogue format: no 'tools' list found")
    else:
        raise CatalogueError("cannot detect catalogue format: expected an object or a list")

    if not entries:
        raise CatalogueError("cannot detect catalogue format: catalogue is empty")

    first = entries[0]
    if not isinstance(first, dict):
        raise CatalogueError("cannot detect catalogue format: tools must be objects")
    if "inputSchema" in first:
        return mcp.FORMAT
    if first.get("type") == "function" or "function" in first:
        return openai.FORMAT
    if "input_schema" in first:
        return anthropic.FORMAT
    if "schema" in first:
        return jsonschema_fmt.FORMAT
    raise CatalogueError(
        f"cannot detect catalogue format; pass --format explicitly (one of {', '.join(FORMATS)})"
    )


def load_file(path: Path, fmt: str | None = None) -> tuple[Catalogue, str]:
    """Load a catalogue from disk, detecting the format unless one is given."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    resolved = fmt or detect_format(payload)
    return load(payload, resolved), resolved


__all__ = [
    "ADAPTERS",
    "FORMATS",
    "Adapter",
    "anthropic",
    "detect_format",
    "dump",
    "get",
    "jsonschema_fmt",
    "load",
    "load_file",
    "mcp",
    "openai",
]
