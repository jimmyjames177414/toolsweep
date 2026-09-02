"""Providers: mock, cassette, and any OpenAI-compatible endpoint."""

from __future__ import annotations

from .base import ModelDescriptor, Provider, Request, Response
from .cassette import CassetteError, CassetteProvider, write_cassette
from .mock import MockConfig, MockProvider
from .openai_compatible import OpenAICompatibleProvider, ProviderError

PROVIDER_NAMES: tuple[str, ...] = ("mock", "cassette", "openai-compatible")

__all__ = [
    "PROVIDER_NAMES",
    "CassetteError",
    "CassetteProvider",
    "MockConfig",
    "MockProvider",
    "ModelDescriptor",
    "OpenAICompatibleProvider",
    "Provider",
    "ProviderError",
    "Request",
    "Response",
    "write_cassette",
]
