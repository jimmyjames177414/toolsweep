"""Factor ``description.length`` - how much prose each tool carries.

Levels
------
``as_authored``  leave descriptions alone (control)
``terse``        first sentence only
``verbose``      the authored description plus a generated parameter narrative

``verbose`` does not invent semantics. It restates what the schema already declares -
parameter names, types, required-ness and enum members - in prose, which is exactly the
duplication people argue about when they write tool descriptions.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import ClassVar

from ..catalogue import Catalogue, Param, Tool
from .base import Factor, map_tools

LEVELS = ("as_authored", "terse", "verbose")

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_PARAM_NARRATIVE = re.compile(r"\n\nParameters: ")


class DescriptionLengthFactor(Factor):
    id: ClassVar[str] = "description.length"
    control_level: ClassVar[str] = "as_authored"
    summary: ClassVar[str] = "terse / standard / verbose tool descriptions"

    @property
    def levels(self) -> tuple[str, ...]:
        return LEVELS

    def apply(self, level: str, cat: Catalogue) -> Catalogue:
        self.check_level(level)
        if level == self.control_level:
            return cat
        if level == "terse":
            return map_tools(cat, _terse)
        return map_tools(cat, _verbose)

    def describe(self, level: str) -> str:
        return {
            "as_authored": "Tool descriptions left exactly as authored.",
            "terse": "Tool descriptions cut to their first sentence.",
            "verbose": (
                "Tool descriptions extended with a generated narrative of each "
                "parameter's name, type, required-ness and enum members."
            ),
        }[level]


def _terse(tool: Tool) -> Tool:
    body = _strip_narrative(tool.description).strip()
    if not body:
        return tool
    first = _SENTENCE_END.split(body, maxsplit=1)[0].strip()
    return replace(tool, description=first)


def _verbose(tool: Tool) -> Tool:
    body = _strip_narrative(tool.description).rstrip()
    if not tool.params:
        return replace(tool, description=body)
    clauses = "; ".join(_describe_param(p) for p in tool.params)
    return replace(tool, description=f"{body}\n\nParameters: {clauses}.")


def _strip_narrative(description: str) -> str:
    """Remove a previously generated parameter narrative.

    Without this, ``verbose`` would append a second narrative on every application and
    break the idempotency contract; ``terse`` would still be correct but would be reading
    generated text as if it were authored.
    """
    return _PARAM_NARRATIVE.split(description, maxsplit=1)[0]


def _describe_param(param: Param) -> str:
    bits = [f"{param.name} ({param.type}"]
    bits.append(", required)" if param.required else ", optional)")
    text = "".join(bits)
    if param.enum:
        members = ", ".join(e.code for e in param.enum)
        text = f"{text} one of {members}"
    if param.properties:
        nested = ", ".join(p.name for p in param.properties)
        text = f"{text} containing {nested}"
    return text
