"""Factor ``naming.synonyms`` - collapse near-synonym tool names onto distinct verbs.

This is the factor the whole project was pitched on: you expose ``get_customer``,
``find_customer``, ``search_customer`` and ``lookup_customer``, all four are valid, and
the model picks the wrong one.

Levels
------
``as_authored``     leave names alone (control)
``distinct_verbs``  rewrite every confusable cluster so its members differ by more than a
                    synonym

A *cluster* is a set of tools sharing a confusability key - the same confusable verb group
and the same singularised noun tokens (see ``_text.subject_key``). Within a cluster each
tool is renamed ``<shape_verb>_<noun>_by_<discriminator>``:

* ``shape_verb`` comes from the tool's most distinctive parameter: a unique key
  (``customer_id``, ``email``) means ``get``; free text (``query``, ``name``) means
  ``search``; anything else means ``list``.
* ``discriminator`` is that parameter's name with the noun prefix stripped.

Every member of a cluster gets the ``_by_`` suffix, not just the colliding ones. Suffixing
only the collisions would leave two members differing by their verb alone - which is the
exact condition the factor exists to remove.
"""

from __future__ import annotations

from typing import ClassVar

from ..catalogue import Catalogue, Param, Tool
from ._text import (
    FREE_TEXT_PARAM_TOKENS,
    KEY_PARAM_TOKENS,
    PAGINATION_PARAM_TOKENS,
    fit_name,
    singularise,
    split_verb_noun,
    strip_prefix_tokens,
    subject_key,
    tokenize,
    uniquify,
)
from .base import Factor, rename_tools

LEVELS = ("as_authored", "distinct_verbs")


class NamingSynonymsFactor(Factor):
    id: ClassVar[str] = "naming.synonyms"
    control_level: ClassVar[str] = "as_authored"
    summary: ClassVar[str] = (
        "collapse near-synonym names (get/find/search/lookup) onto distinct verbs"
    )

    @property
    def levels(self) -> tuple[str, ...]:
        return LEVELS

    def apply(self, level: str, cat: Catalogue) -> Catalogue:
        self.check_level(level)
        if level == self.control_level:
            return cat

        clusters: dict[tuple[str, tuple[str, ...]], list[Tool]] = {}
        for tool in cat.tools:
            key = subject_key(tool.name)
            if key is not None:
                clusters.setdefault(key, []).append(tool)

        renames: dict[str, str] = {}
        for (_group, nouns), members in clusters.items():
            if len(members) < 2:
                continue
            for tool in members:
                renames[tool.name] = _cluster_name(tool, nouns)

        if not renames:
            return cat

        proposed = [renames.get(t.name, t.name) for t in cat.tools]
        return rename_tools(cat, dict(zip(cat.names, uniquify(proposed), strict=True)))

    def describe(self, level: str) -> str:
        if level == self.control_level:
            return "Tool names left exactly as authored, near-synonyms included."
        return (
            "Every cluster of tools whose names differ only by a synonym of the same verb "
            "renamed to <verb>_<noun>_by_<discriminator>, so no two members of a cluster "
            "differ by their verb alone."
        )


def _cluster_name(tool: Tool, nouns: tuple[str, ...]) -> str:
    discriminator_param = _discriminator(tool)
    noun = "_".join(nouns)

    if discriminator_param is None:
        return fit_name(f"list_{noun}_all")

    discriminator = strip_prefix_tokens(discriminator_param.name, nouns)
    verb = _shape_verb(tool, discriminator_param, discriminator)
    return fit_name(f"{verb}_{noun}_by_{discriminator}")


def _discriminator(tool: Tool) -> Param | None:
    """The parameter that most distinguishes this tool from its cluster siblings.

    Required parameters first, in declaration order - an author's required list is the
    closest thing to a statement of what the tool is *for*. Falls back to the first
    optional parameter, then to nothing at all for zero-argument tools.
    """
    for param in tool.params:
        if param.required:
            return param
    return tool.params[0] if tool.params else None


def _shape_verb(tool: Tool, param: Param, discriminator: str) -> str:
    # Pagination arguments are the clearest signal a tool returns many rows, and they
    # outrank the discriminator: `list_invoices(customer_id, limit)` is a list even though
    # its most distinctive parameter is a key.
    if any(t.name in PAGINATION_PARAM_TOKENS for t in tool.params):
        return "list"

    tokens = {singularise(t) for t in tokenize(discriminator)}
    if tokens & KEY_PARAM_TOKENS:
        return "get"
    if tokens & FREE_TEXT_PARAM_TOKENS:
        return "search"
    if param.type in ("object", "array"):
        return "list"
    # Keep the authored verb when the shape says nothing, rather than inventing one.
    verb, _ = split_verb_noun(param.name)
    return verb or "list"
