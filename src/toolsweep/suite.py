"""Task suite loading and validation.

A suite is JSONL, one item per line::

    {"id": "crm.001", "prompt": "...", "expected_tool": "get_customer",
     "expected_args": {"customer_id": "CUS-1041"}}

``expected_tool`` and ``expected_args`` are written against the **as-authored** catalogue
and are validated against it at load time. Loading fails loudly on an unknown tool or an
unknown argument path, because a suite that silently references a tool you deleted is a
benchmark that reports a confident wrong answer.

The suite is the measurement instrument. Nothing downstream can rescue a bad one, which
is why it gets its own honest-limitations bullet in the README.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from .catalogue import Catalogue, find_param_by_origin, flatten_args


class SuiteError(ValueError):
    """Raised when a task suite is malformed or inconsistent with its catalogue."""


@dataclass(frozen=True)
class Item:
    """One task: a prompt, and the tool call it should produce."""

    id: str
    prompt: str
    expected_tool: str
    expected_args: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class Suite:
    items: tuple[Item, ...]
    source: str = ""

    def __len__(self) -> int:
        return len(self.items)

    @property
    def expected_tools(self) -> frozenset[str]:
        """Every tool the suite expects, in as-authored name space.

        This is what ``catalogue.size`` pins so a subset never drops the answer.
        """
        return frozenset(item.expected_tool for item in self.items)


def parse(text: str, *, source: str = "") -> Suite:
    items: list[Item] = []
    seen: set[str] = set()
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            raw = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise SuiteError(f"{source}:{lineno}: not valid JSON: {exc}") from exc
        if not isinstance(raw, dict):
            raise SuiteError(f"{source}:{lineno}: each line must be a JSON object")
        obj = cast("dict[str, Any]", raw)

        for field in ("id", "prompt", "expected_tool"):
            if not isinstance(obj.get(field), str) or not obj[field]:
                raise SuiteError(f"{source}:{lineno}: missing or non-string {field!r}")

        item_id = str(obj["id"])
        if item_id in seen:
            raise SuiteError(f"{source}:{lineno}: duplicate item id {item_id!r}")
        seen.add(item_id)

        expected_args = obj.get("expected_args")
        if expected_args is not None and not isinstance(expected_args, dict):
            raise SuiteError(f"{source}:{lineno}: expected_args must be an object")

        items.append(
            Item(
                id=item_id,
                prompt=str(obj["prompt"]),
                expected_tool=str(obj["expected_tool"]),
                expected_args=cast("dict[str, Any] | None", expected_args),
            )
        )

    if not items:
        raise SuiteError(f"{source or 'suite'}: no items found")
    return Suite(items=tuple(items), source=source)


def load_file(path: Path) -> Suite:
    return parse(path.read_text(encoding="utf-8"), source=str(path))


def validate_against(suite: Suite, cat: Catalogue) -> None:
    """Check every item names a tool and argument paths the catalogue actually has."""
    known = set(cat.origins)
    problems: list[str] = []
    for item in suite.items:
        if item.expected_tool not in known:
            problems.append(
                f"item {item.id!r} expects tool {item.expected_tool!r}, which is not in "
                f"the catalogue"
            )
            continue
        if not item.expected_args:
            continue
        tool = cat.by_origin(item.expected_tool)
        assert tool is not None  # guarded by the membership check above
        for path in flatten_args(item.expected_args):
            if find_param_by_origin(tool, path) is None:
                problems.append(
                    f"item {item.id!r} expects argument {path!r}, which tool "
                    f"{item.expected_tool!r} does not declare"
                )
    if problems:
        joined = "\n  - ".join(problems)
        raise SuiteError(f"suite does not match catalogue:\n  - {joined}")


def item_ids(items: Sequence[Item]) -> tuple[str, ...]:
    return tuple(i.id for i in items)
