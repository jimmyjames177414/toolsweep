"""Content-addressed on-disk response cache.

Keyed by ``sha256(provider | base_url | model | params | system | prompt | tools |
repeat_index)``. ``repeat_index`` is in the key deliberately: a stochastic provider must
be free to answer differently on repeat 3 than on repeat 1, so repeats cannot share an
entry. Caching them together would collapse within-item variance to zero and make every
interval too narrow.

Default location ``~/.cache/toolsweep/``, overridable with ``--cache-dir``, disabled with
``--no-cache``.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from .providers.base import Response
from .score import ToolCall


def default_cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME")
    root = Path(base) if base else Path.home() / ".cache"
    return root / "toolsweep"


class ResponseCache:
    """A tiny sharded file cache. Never raises on a corrupt entry; it treats it as a miss."""

    def __init__(self, directory: Path | None = None, *, enabled: bool = True) -> None:
        self.directory = directory or default_cache_dir()
        self.enabled = enabled
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Response | None:
        if not self.enabled:
            return None
        path = self._path(key)
        if not path.is_file():
            self.misses += 1
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.misses += 1
            return None
        if not isinstance(payload, dict):
            self.misses += 1
            return None
        self.hits += 1
        return _decode(cast("dict[str, Any]", payload))

    def put(self, key: str, response: Response) -> None:
        if not self.enabled:
            return
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(_encode(response), sort_keys=True), encoding="utf-8")
        tmp.replace(path)

    def _path(self, key: str) -> Path:
        return self.directory / key[:2] / f"{key}.json"


def _encode(response: Response) -> dict[str, Any]:
    call = response.tool_call
    return {
        "text": response.text,
        "tool_call": (
            None if call is None else {"name": call.name, "arguments": dict(call.arguments)}
        ),
        "latency_ms": response.latency_ms,
        "usage": dict(response.usage),
        "error": response.error,
    }


def _decode(payload: Mapping[str, Any]) -> Response:
    raw_call = payload.get("tool_call")
    call: ToolCall | None = None
    if isinstance(raw_call, dict):
        obj = cast("dict[str, Any]", raw_call)
        arguments = obj.get("arguments", {})
        call = ToolCall(
            name=str(obj.get("name", "")),
            arguments=cast("dict[str, Any]", arguments) if isinstance(arguments, dict) else {},
        )
    usage = payload.get("usage", {})
    return Response(
        text=str(payload.get("text", "")),
        tool_call=call,
        latency_ms=int(payload.get("latency_ms", 0)),
        usage=cast("dict[str, int]", usage) if isinstance(usage, dict) else {},
        cached=True,
        error=cast("str | None", payload.get("error")),
    )
