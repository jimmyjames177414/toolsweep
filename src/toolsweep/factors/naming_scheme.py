"""Factor ``naming.scheme`` - the shape of every tool name.

Levels
------
``as_authored``   leave names alone (control)
``verb_noun``     ``get_customer``
``noun_verb``     ``customer_get``
``terse``         ``getcust`` - abbreviated, no separators
``verbose``       ``crm_retrieve_customer`` - namespace-qualified, verbs expanded

Names whose first or last token is not a recognised verb are left untouched at every
level, because there is nothing to reorder and guessing would be worse than abstaining.
"""

from __future__ import annotations

from typing import ClassVar

from ..catalogue import Catalogue
from ._text import (
    VERBS,
    abbreviate_noun,
    abbreviate_verb,
    expand_verb,
    fit_name,
    split_verb_noun,
    tokenize,
    uniquify,
)
from .base import Factor, rename_tools

LEVELS = ("as_authored", "verb_noun", "noun_verb", "terse", "verbose")


class NamingSchemeFactor(Factor):
    id: ClassVar[str] = "naming.scheme"
    control_level: ClassVar[str] = "as_authored"
    summary: ClassVar[str] = "verb_noun / noun_verb / terse / verbose naming conventions"

    @property
    def levels(self) -> tuple[str, ...]:
        return LEVELS

    def apply(self, level: str, cat: Catalogue) -> Catalogue:
        self.check_level(level)
        if level == self.control_level:
            return cat

        proposed = [self._rename(level, cat.namespace, t.name) for t in cat.tools]
        unique = uniquify(proposed)
        return rename_tools(cat, dict(zip(cat.names, unique, strict=True)))

    def describe(self, level: str) -> str:
        return {
            "as_authored": "Tool names left exactly as authored.",
            "verb_noun": "Every tool name rewritten as verb_noun (get_customer).",
            "noun_verb": "Every tool name rewritten as noun_verb (customer_get).",
            "terse": "Every tool name abbreviated and stripped of separators (getcust).",
            "verbose": (
                "Every tool name namespace-qualified with verbs expanded (crm_retrieve_customer)."
            ),
        }[level]

    @staticmethod
    def _rename(level: str, namespace: str, name: str) -> str:
        # "Already in this scheme" guards, checked before parsing. Without them a name
        # whose *last* token is also a verb oscillates instead of settling:
        # get_index -> api_retrieve_index -> api_index_api_retrieve. Idempotency is a
        # contract (factors/base.py), so each level detects its own output and stops.
        if level == "verbose" and name.startswith(f"{namespace}_"):
            return name
        tokens = tokenize(name)
        if level == "terse" and len(tokens) == 1:
            # Terse output is a single glued token. Re-abbreviating it would truncate a
            # second time: sendinvrmdr -> sendinvr -> sendinv.
            return name
        if level == "noun_verb" and _ends_with_verb(tokens):
            return name

        verb, nouns = split_verb_noun(name)
        if not verb or not nouns:
            # No verb to move or expand. Abstaining beats mangling.
            return name

        if level == "verb_noun":
            return fit_name("_".join((verb, *nouns)))
        if level == "noun_verb":
            return fit_name("_".join((*nouns, verb)))
        if level == "terse":
            parts = [abbreviate_verb(verb), *(abbreviate_noun(n) for n in nouns)]
            return fit_name("".join(parts))
        if level == "verbose":
            return fit_name("_".join((namespace, expand_verb(verb), *nouns)))
        raise AssertionError(f"unhandled level {level!r}")


def _ends_with_verb(tokens: tuple[str, ...]) -> bool:
    """Whether a name is already verb-last, ignoring a numeric collision suffix.

    ``uniquify`` appends ``_2`` when two tools want the same generated name, which pushes
    the verb out of last place: ``customer_get_2``. Without trimming the digits the guard
    misses, and the next application produces ``customer_2_get``.
    """
    trimmed = list(tokens)
    while len(trimmed) > 1 and trimmed[-1].isdigit():
        trimmed.pop()
    return len(trimmed) > 1 and trimmed[-1] in VERBS
