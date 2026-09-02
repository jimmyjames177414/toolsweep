"""Factor ``description.negative`` - whether each tool says when *not* to use it.

Levels
------
``without``  strip any "do not use this ..." text (control)
``with``     append it

Where the text comes from matters, and toolsweep will not pretend otherwise:

* If the catalogue authored a ``not_for`` string, that string is used verbatim.
* If it did not, a negative is *synthesised* by pointing at the tool's nearest sibling -
  the other tool with the same confusability key. That is a name-similarity heuristic, not
  knowledge of what the tools do, and it can be wrong.

Synthesised text is marked in the intervention description so a report never implies the
author wrote it. A tool with no authored negative and no sibling gets nothing.
"""

from __future__ import annotations

from dataclasses import replace
from typing import ClassVar

from ..catalogue import Catalogue, Tool
from ._text import subject_key
from .base import Factor

LEVELS = ("without", "with")

_MARKER = "\n\nDo not use this "


class DescriptionNegativeFactor(Factor):
    id: ClassVar[str] = "description.negative"
    control_level: ClassVar[str] = "without"
    summary: ClassVar[str] = "with vs without a 'when NOT to use this' clause"

    @property
    def levels(self) -> tuple[str, ...]:
        return LEVELS

    def apply(self, level: str, cat: Catalogue) -> Catalogue:
        self.check_level(level)
        stripped = cat.with_tools([_strip(t) for t in cat.tools])
        if level == "without":
            return stripped

        siblings = _sibling_map(stripped)
        tools: list[Tool] = []
        for tool in stripped.tools:
            negative = tool.not_for or _synthesise(tool, siblings.get(tool.name, ()))
            if not negative:
                tools.append(tool)
                continue
            body = tool.description.rstrip()
            tools.append(replace(tool, description=f"{body}{_MARKER}{negative}"))
        return stripped.with_tools(tools)

    def describe(self, level: str) -> str:
        if level == "without":
            return "Any 'when NOT to use this' clause removed from every tool description."
        return (
            "A 'when NOT to use this' clause appended to every tool description, taken "
            "from the authored not_for text where one exists and otherwise synthesised "
            "from the tool's nearest same-subject sibling."
        )


def _strip(tool: Tool) -> Tool:
    if _MARKER not in tool.description:
        return tool
    head = tool.description.split(_MARKER, 1)[0].rstrip()
    return replace(tool, description=head)


def _sibling_map(cat: Catalogue) -> dict[str, tuple[str, ...]]:
    groups: dict[tuple[str, tuple[str, ...]], list[str]] = {}
    for tool in cat.tools:
        key = subject_key(tool.name)
        if key is not None:
            groups.setdefault(key, []).append(tool.name)
    return {
        name: tuple(n for n in members if n != name)
        for members in groups.values()
        for name in members
    }


def _synthesise(tool: Tool, siblings: tuple[str, ...]) -> str:
    if not siblings:
        return ""
    listed = ", ".join(f"`{s}`" for s in siblings)
    return (
        f"when another tool fits the request better; {listed} "
        f"{'cover' if len(siblings) > 1 else 'covers'} closely related requests."
    )
