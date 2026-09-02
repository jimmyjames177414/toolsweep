"""Replay recorded responses from disk. No network, no keys.

A cassette is a JSON file::

    {
      "_provenance": "synthetic | recorded",
      "_note": "...",
      "model": { "provider": "...", "model": "...", "base_url": "...", "params": {...} },
      "entries": { "<request sha256>": { "text": "...", "tool_call": {...} } }
    }

``_provenance`` is mandatory and must be either ``recorded`` (captured from a real model)
or ``synthetic`` (generated). A cassette without it fails to load. Shared foundation rule
D3: a fixture that looks like a model response must say which it is, in the file, so
nobody can mistake generated output for a measurement.

A cache miss is an **error**, never a silent fallback to a live call. Replaying a partial
cassette and quietly filling the gaps would produce a run whose numbers came from two
different places.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from ..score import ToolCall
from .base import ModelDescriptor, Provider, Request, Response

PROVENANCE_VALUES = ("recorded", "synthetic")


class CassetteError(RuntimeError):
    """Raised for a malformed cassette or a request it does not contain."""


class CassetteProvider(Provider):
    name = "cassette"

    def __init__(self, path: Path) -> None:
        self.path = path
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise CassetteError(f"{path}: cassette must be a JSON object")
        obj = cast("dict[str, Any]", payload)

        provenance = obj.get("_provenance")
        if provenance not in PROVENANCE_VALUES:
            raise CassetteError(
                f"{path}: '_provenance' must be one of {PROVENANCE_VALUES}; a fixture that "
                f"looks like a model response has to say whether it was recorded or generated"
            )
        self.provenance: str = str(provenance)
        self.note: str = str(obj.get("_note", ""))

        model = obj.get("model")
        if not isinstance(model, dict):
            raise CassetteError(f"{path}: cassette must record the model it replays")
        model_obj = cast("dict[str, Any]", model)
        self._descriptor = ModelDescriptor(
            provider=str(model_obj.get("provider", "cassette")),
            model=str(model_obj.get("model", "unknown")),
            base_url=str(model_obj.get("base_url", "")),
            params=cast("dict[str, Any]", model_obj.get("params", {})),
        )

        entries = obj.get("entries")
        if not isinstance(entries, dict):
            raise CassetteError(f"{path}: cassette must have an 'entries' object")
        self._entries = cast("dict[str, Any]", entries)

    @property
    def descriptor(self) -> ModelDescriptor:
        return self._descriptor

    def complete(self, request: Request) -> Response:
        key = request.key(self._descriptor)
        entry = self._entries.get(key)
        if entry is None:
            raise CassetteError(
                f"{self.path}: no recorded response for this request (key {key[:12]}...).\n"
                f"The cassette was recorded for one exact grid. Changing --repeats, --seed, "
                f"--factors or the catalogue changes the keys. Re-record, or run with "
                f"--provider mock."
            )
        if not isinstance(entry, dict):
            raise CassetteError(f"{self.path}: entry {key[:12]}... is not an object")
        body = cast("dict[str, Any]", entry)

        raw_call = body.get("tool_call")
        call: ToolCall | None = None
        if isinstance(raw_call, dict):
            call_obj = cast("dict[str, Any]", raw_call)
            arguments = call_obj.get("arguments", {})
            call = ToolCall(
                name=str(call_obj.get("name", "")),
                arguments=cast(
                    "Mapping[str, Any]", arguments if isinstance(arguments, dict) else {}
                ),
            )
        usage = body.get("usage", {})
        return Response(
            text=str(body.get("text", "")),
            tool_call=call,
            latency_ms=int(body.get("latency_ms", 0)),
            usage=cast("Mapping[str, int]", usage if isinstance(usage, dict) else {}),
            cached=True,
            error=cast("str | None", body.get("error")),
        )

    def __len__(self) -> int:
        return len(self._entries)


def write_cassette(
    path: Path,
    *,
    descriptor: ModelDescriptor,
    entries: Mapping[str, Mapping[str, Any]],
    provenance: str,
    note: str,
) -> None:
    """Write a cassette, refusing to omit its provenance."""
    if provenance not in PROVENANCE_VALUES:
        raise CassetteError(f"provenance must be one of {PROVENANCE_VALUES}")
    payload = {
        "_provenance": provenance,
        "_note": note,
        "model": {
            "provider": descriptor.provider,
            "model": descriptor.model,
            "base_url": descriptor.base_url,
            "params": dict(descriptor.params),
        },
        "entries": {k: dict(v) for k, v in entries.items()},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
