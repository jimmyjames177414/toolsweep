"""Any OpenAI-compatible ``/v1/chat/completions`` endpoint.

One adapter covers Ollama, vLLM, LM Studio, llama.cpp's server, OpenRouter, Together,
Groq, DeepSeek and OpenAI itself. Provider selection is a URL and an environment variable,
never a code change - a contributor with Ollama and no credit card can run everything.

Built on ``urllib`` rather than ``httpx`` so the package has **zero runtime dependencies**.
The request is one POST with a JSON body; a dependency would buy retry sugar and cost
every user a transitive tree.

Nothing in this module is exercised by the default test suite. Tests that touch it are
marked ``live`` and deselected, and CI runs with no secrets configured at all.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any, cast

from ..adapters import openai as openai_adapter
from ..score import ToolCall
from .base import ModelDescriptor, Provider, Request, Response

DEFAULT_SYSTEM = (
    "You are a tool-selection engine. Choose exactly one tool that answers the user's "
    "request and call it with the correct arguments. Do not explain."
)


class ProviderError(RuntimeError):
    """Raised when the endpoint cannot be reached or returns something unusable."""


class OpenAICompatibleProvider(Provider):
    name = "openai-compatible"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str = "",
        temperature: float = 0.0,
        max_tokens: int = 512,
        seed: int | None = None,
        timeout: float = 60.0,
        max_retries: int = 2,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.seed = seed
        self.timeout = timeout
        self.max_retries = max_retries

    @property
    def descriptor(self) -> ModelDescriptor:
        return ModelDescriptor(
            provider=self.name,
            base_url=self.base_url,
            model=self.model,
            params={
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                # Recorded even when None: a run has to state whether a seed was requested
                # rather than implying determinism it never had.
                "seed": self.seed,
            },
        )

    def complete(self, request: Request) -> Response:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.system or DEFAULT_SYSTEM},
                {"role": "user", "content": request.prompt},
            ],
            "tools": openai_adapter.dump(request.catalogue),
            "tool_choice": "required",
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if self.seed is not None:
            body["seed"] = self.seed

        started = time.monotonic()
        payload = self._post(body)
        latency_ms = int((time.monotonic() - started) * 1000)
        return _parse(payload, latency_ms)

    def _post(self, body: Mapping[str, Any]) -> Mapping[str, Any]:
        data = json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            req = urllib.request.Request(
                f"{self.base_url}/chat/completions", data=data, headers=headers
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = json.loads(resp.read().decode("utf-8"))
                if not isinstance(raw, dict):
                    raise ProviderError("endpoint returned a non-object response")
                return cast("dict[str, Any]", raw)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last = exc
                if attempt < self.max_retries:
                    time.sleep(1.5 * (attempt + 1))
        raise ProviderError(f"{self.base_url}: request failed after retries: {last}")


def _parse(payload: Mapping[str, Any], latency_ms: int) -> Response:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return Response(text="", tool_call=None, latency_ms=latency_ms, error="no choices")
    first = choices[0]
    if not isinstance(first, dict):
        return Response(text="", tool_call=None, latency_ms=latency_ms, error="bad choice")

    message = cast("dict[str, Any]", first).get("message", {})
    if not isinstance(message, dict):
        return Response(text="", tool_call=None, latency_ms=latency_ms, error="bad message")
    msg = cast("dict[str, Any]", message)
    text = str(msg.get("content") or "")

    usage_raw = payload.get("usage", {})
    usage: dict[str, int] = {}
    if isinstance(usage_raw, dict):
        for key in ("prompt_tokens", "completion_tokens"):
            value = cast("dict[str, Any]", usage_raw).get(key)
            if isinstance(value, int):
                usage[key] = value

    calls = msg.get("tool_calls")
    if not isinstance(calls, list) or not calls:
        return Response(text=text, tool_call=None, latency_ms=latency_ms, usage=usage)

    call_raw = calls[0]
    if not isinstance(call_raw, dict):
        return Response(text=text, tool_call=None, latency_ms=latency_ms, usage=usage)
    function = cast("dict[str, Any]", call_raw).get("function", {})
    if not isinstance(function, dict):
        return Response(text=text, tool_call=None, latency_ms=latency_ms, usage=usage)
    fn = cast("dict[str, Any]", function)

    arguments: dict[str, Any] = {}
    raw_args = fn.get("arguments", "{}")
    if isinstance(raw_args, str):
        try:
            decoded = json.loads(raw_args or "{}")
        except json.JSONDecodeError:
            # A malformed argument string is a real result: the tool was selected, the
            # arguments are invalid. Scoring records it as such rather than discarding it.
            return Response(
                text=text,
                tool_call=ToolCall(
                    name=str(fn.get("name", "")), arguments={"__malformed__": raw_args}
                ),
                latency_ms=latency_ms,
                usage=usage,
            )
        if isinstance(decoded, dict):
            arguments = cast("dict[str, Any]", decoded)
    elif isinstance(raw_args, dict):
        arguments = cast("dict[str, Any]", raw_args)

    return Response(
        text=text,
        tool_call=ToolCall(name=str(fn.get("name", "")), arguments=arguments),
        latency_ms=latency_ms,
        usage=usage,
    )
