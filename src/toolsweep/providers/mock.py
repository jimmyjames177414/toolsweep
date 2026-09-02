"""A deterministic mock provider with one planted effect.

This is toolsweep's own proof that it works. The mock is a lexical tool picker with a
single deliberate flaw: **it confuses tools whose names differ only by a synonym of the
same verb.** Show it ``get_customer``, ``find_customer``, ``search_customer`` and
``lookup_customer`` and it picks among them by a seeded coin flip. Rename them so they
differ by more than the verb and the confusion disappears.

``tests/test_planted_effect.py`` runs a full sweep against this mock and asserts that
toolsweep detects that effect with a CI excluding zero - and, just as importantly, that
factors the mock is blind to come back **null with an interval**, not significant. A tool
that finds an effect everywhere is as useless as one that finds it nowhere.

What the mock is NOT
--------------------
It is not a model, and no number produced with it says anything about any real model. It
never hallucinates and never declines to call a tool (both rates default to zero), and it
emits arguments derived from the item's expected arguments, so argument validity and
argument match are ~1.0 by construction and carry no information in a mock run. All of
this is stated in the README next to the demo output rather than left for a reader to
discover.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..adapters import openai as openai_adapter
from ..catalogue import Catalogue, Param, Tool, resolve_args
from ..factors._text import singularise, subject_key, tokenize
from ..score import ToolCall
from .base import ModelDescriptor, Provider, Request, Response

#: Weight applied to a prompt token matching a tool *name* token, relative to a
#: description token. Names dominate, which is what makes naming factors bite.
NAME_WEIGHT = 3.0
DESCRIPTION_WEIGHT = 1.0

_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "get",
        "has",
        "have",
        "how",
        "i",
        "in",
        "is",
        "it",
        "its",
        "me",
        "my",
        "of",
        "on",
        "or",
        "please",
        "that",
        "the",
        "then",
        "there",
        "this",
        "to",
        "up",
        "was",
        "we",
        "what",
        "when",
        "which",
        "who",
        "will",
        "with",
        "you",
        "your",
    }
)


@dataclass(frozen=True)
class MockConfig:
    """Every knob the mock has. All defaults produce the demo's behaviour."""

    seed: int = 7
    #: Probability of re-picking at random within a confusable cluster. The planted effect.
    confusion_rate: float = 0.55
    #: Probability of returning no tool call at all.
    no_call_rate: float = 0.0
    #: Probability of inventing a tool name that is not in the catalogue.
    hallucination_rate: float = 0.0


class MockProvider(Provider):
    """Deterministic, offline, seeded. Same inputs, same answer, on every machine."""

    name = "mock"

    def __init__(
        self,
        *,
        config: MockConfig | None = None,
        expected_args: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        self.config = config or MockConfig()
        # Keyed by prompt so the mock can fill plausible arguments without the runner
        # having to hand it the suite. Absent entries simply produce empty arguments.
        self._expected_args = dict(expected_args or {})

    @property
    def descriptor(self) -> ModelDescriptor:
        return ModelDescriptor(
            provider=self.name,
            model=f"mock-lexical-picker-seed{self.config.seed}",
            params={
                "temperature": 0.0,
                "confusion_rate": self.config.confusion_rate,
                "no_call_rate": self.config.no_call_rate,
                "hallucination_rate": self.config.hallucination_rate,
            },
        )

    def complete(self, request: Request) -> Response:
        rng = self._rng(request)
        cat = request.catalogue
        if not cat.tools:
            return Response(text="", tool_call=None, error="empty catalogue")

        if rng.random() < self.config.no_call_rate:
            return Response(text="I do not think a tool is needed here.", tool_call=None)

        chosen = self._pick(request.prompt, cat)
        chosen = self._maybe_confuse(chosen, cat, rng)

        if rng.random() < self.config.hallucination_rate:
            invented = f"{chosen.name}_v2"
            return Response(
                text=json.dumps({"tool": invented, "arguments": {}}),
                tool_call=ToolCall(name=invented, arguments={}),
            )

        arguments = self._arguments(request.prompt, chosen)
        return Response(
            text=json.dumps({"tool": chosen.name, "arguments": arguments}, sort_keys=True),
            tool_call=ToolCall(name=chosen.name, arguments=arguments),
            usage={"prompt_tokens": _estimate_tokens(request, cat), "completion_tokens": 24},
        )

    # -- picking ------------------------------------------------------------------

    def _pick(self, prompt: str, cat: Catalogue) -> Tool:
        wanted = _content_tokens(prompt)
        best = cat.tools[0]
        best_score = float("-inf")
        for tool in cat.tools:
            score = _similarity(wanted, tool)
            if score > best_score:
                best, best_score = tool, score
        return best

    def _maybe_confuse(self, chosen: Tool, cat: Catalogue, rng: random.Random) -> Tool:
        """The planted effect: pick blind within a cluster of same-verb-synonym names."""
        key = subject_key(chosen.name)
        if key is None:
            return chosen
        cluster = [t for t in cat.tools if subject_key(t.name) == key]
        if len(cluster) < 2:
            return chosen
        if rng.random() >= self.config.confusion_rate:
            return chosen
        return cluster[rng.randrange(len(cluster))]

    # -- arguments ----------------------------------------------------------------

    def _arguments(self, prompt: str, tool: Tool) -> dict[str, Any]:
        expected = self._expected_args.get(prompt)
        if expected:
            resolved = resolve_args(tool, expected)
            if resolved:
                return resolved
        return _placeholder_arguments(tool.params)

    # -- determinism --------------------------------------------------------------

    def _rng(self, request: Request) -> random.Random:
        blob = "|".join(
            (
                str(self.config.seed),
                request.prompt,
                ",".join(request.catalogue.names),
                str(request.repeat_index),
            )
        )
        return random.Random(hashlib.sha256(blob.encode("utf-8")).hexdigest())


def _content_tokens(prompt: str) -> set[str]:
    return {
        singularise(t)
        for t in tokenize(prompt.replace(".", " ").replace(",", " "))
        if t not in _STOPWORDS and len(t) > 1
    }


def _similarity(wanted: set[str], tool: Tool) -> float:
    name_tokens = {singularise(t) for t in tokenize(tool.name)}
    desc_tokens = {singularise(t) for t in tokenize(tool.description) if t not in _STOPWORDS}
    param_tokens = {singularise(t) for p in tool.params for t in tokenize(p.name)}
    score = NAME_WEIGHT * len(wanted & name_tokens)
    score += DESCRIPTION_WEIGHT * len(wanted & desc_tokens)
    score += DESCRIPTION_WEIGHT * len(wanted & param_tokens)
    # Break ties towards shorter names, deterministically.
    return score - 1e-6 * len(tool.name)


def _placeholder_arguments(params: Sequence[Param]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for param in params:
        if not param.required:
            continue
        out[param.name] = _placeholder(param)
    return out


def _placeholder(param: Param) -> Any:
    if param.enum:
        return param.enum[0].code
    if param.type == "integer":
        return 1
    if param.type == "number":
        return 1.0
    if param.type == "boolean":
        return True
    if param.type == "array":
        return []
    if param.type == "object":
        return _placeholder_arguments(param.properties)
    return f"<{param.name}>"


def _estimate_tokens(request: Request, cat: Catalogue) -> int:
    """A rough character-based estimate, labelled as such wherever it surfaces."""
    blob = json.dumps(openai_adapter.dump(cat), separators=(",", ":"))
    return (len(blob) + len(request.prompt) + len(request.system)) // 4
