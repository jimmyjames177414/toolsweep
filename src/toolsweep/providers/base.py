"""The provider contract.

A provider turns a :class:`Request` into a :class:`Response`. That is the only place in
toolsweep where a model could be involved, which is why the entire factor and scoring
layer is testable with no network and no keys.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ..adapters import openai as openai_adapter
from ..catalogue import Catalogue
from ..score import ToolCall


@dataclass(frozen=True)
class ModelDescriptor:
    """CXS ``ModelDescriptor``: what was asked, precisely enough to re-run."""

    provider: str
    model: str
    base_url: str = ""
    params: Mapping[str, Any] = field(default_factory=dict)

    def to_cxs(self, observed_at: str) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "base_url": self.base_url,
            "model": self.model,
            "params": dict(self.params),
            "observed_at": observed_at,
        }


@dataclass(frozen=True)
class Request:
    """One model call: a prompt and the catalogue the model is allowed to choose from."""

    prompt: str
    catalogue: Catalogue
    #: Included in the cache and cassette key. A stochastic provider must return
    #: different answers for different repeats, so repeats cannot share a cache entry.
    repeat_index: int = 0
    system: str = ""

    def key(self, model: ModelDescriptor) -> str:
        """Content-addressed key for caching and cassette replay."""
        payload = {
            "provider": model.provider,
            "base_url": model.base_url,
            "model": model.model,
            "params": _canonical(model.params),
            "system": self.system,
            "prompt": self.prompt,
            "tools": openai_adapter.dump(self.catalogue),
            "repeat_index": self.repeat_index,
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def prompt_sha256(self, model: ModelDescriptor) -> str:
        """CXS ``Trial.prompt_sha256``.

        Hashes the prompt *and* the presented catalogue, because in this experiment the
        catalogue is the part of the prompt under test. Hashing the text alone would
        collide across every arm and make the field useless for reproduction.
        """
        return self.key(model)


@dataclass(frozen=True)
class Response:
    """What came back."""

    text: str
    tool_call: ToolCall | None
    latency_ms: int = 0
    usage: Mapping[str, int] = field(default_factory=dict)
    cached: bool = False
    error: str | None = None


class Provider(ABC):
    """Anything that can answer a :class:`Request`."""

    #: CXS ``ModelDescriptor.provider``.
    name: str

    @abstractmethod
    def complete(self, request: Request) -> Response:
        """Answer one request."""

    @property
    @abstractmethod
    def descriptor(self) -> ModelDescriptor:
        """How this provider identifies itself in the run manifest."""


def _canonical(params: Mapping[str, Any]) -> dict[str, Any]:
    return {k: params[k] for k in sorted(params)}
