"""Name analysis shared by the naming factors.

Everything here is a deterministic table lookup or a regex. There is no model in the
loop, which is the point: a factor has to be reproducible from its source alone, or the
sweep is measuring the factor's own randomness.

The tables are deliberately small and English-centric. That is a real limitation and it
is in the README's honest-limitations list, not hidden here.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence

_SPLIT_RE = re.compile(r"[_\-\s]+|(?<=[a-z0-9])(?=[A-Z])")

# Verb classes. Two verbs in the same class mean roughly the same thing to a reader.
VERB_CLASSES: dict[str, frozenset[str]] = {
    "read": frozenset({"get", "fetch", "retrieve", "read", "show", "view", "describe"}),
    "search": frozenset({"find", "search", "lookup", "query", "locate", "match"}),
    "list": frozenset({"list", "enumerate", "index", "browse"}),
    "create": frozenset({"create", "add", "new", "insert", "make", "register"}),
    "update": frozenset({"update", "edit", "modify", "patch", "set", "change", "rename"}),
    "delete": frozenset({"delete", "remove", "destroy", "erase", "drop", "purge"}),
    "close": frozenset({"close", "cancel", "void", "archive", "disable", "deactivate"}),
    "send": frozenset({"send", "email", "notify", "dispatch", "deliver", "post"}),
    "run": frozenset({"run", "execute", "invoke", "trigger", "start", "launch"}),
}

# Classes a model is plausibly asked to choose between. `get_x` / `find_x` / `search_x` /
# `list_x` are the canonical case; `create_x` and `update_x` are not confusable in the
# same way, because the user's intent distinguishes them.
CONFUSABLE_GROUPS: dict[str, frozenset[str]] = {
    "retrieval": frozenset({"read", "search", "list"}),
    "create": frozenset({"create"}),
    "update": frozenset({"update"}),
    "removal": frozenset({"delete", "close"}),
    "send": frozenset({"send"}),
    "run": frozenset({"run"}),
}

VERBS: frozenset[str] = frozenset().union(*VERB_CLASSES.values())

# Used by naming.scheme=terse.
NOUN_ABBREVIATIONS: dict[str, str] = {
    "account": "acct",
    "address": "addr",
    "attachment": "att",
    "balance": "bal",
    "configuration": "cfg",
    "customer": "cust",
    "document": "doc",
    "invoice": "inv",
    "message": "msg",
    "notification": "notif",
    "number": "num",
    "organisation": "org",
    "organization": "org",
    "payment": "pmt",
    "reference": "ref",
    "reminder": "rmdr",
    "subscription": "sub",
    "transaction": "txn",
}

VERB_ABBREVIATIONS: dict[str, str] = {
    "create": "mk",
    "delete": "del",
    "find": "fnd",
    "list": "ls",
    "lookup": "lk",
    "retrieve": "get",
    "search": "srch",
    "update": "upd",
}

# Used by naming.scheme=verbose. Identity for verbs that are already unambiguous words.
VERB_EXPANSIONS: dict[str, str] = {
    "add": "create",
    "del": "delete",
    "get": "retrieve",
    "ls": "list",
    "mk": "create",
    "new": "create",
    "rm": "delete",
    "set": "update",
}

# Parameter names that identify exactly one record.
KEY_PARAM_TOKENS: frozenset[str] = frozenset(
    {"id", "uuid", "key", "code", "email", "slug", "number", "reference", "handle"}
)

# Parameter names that hold user-typed free text.
FREE_TEXT_PARAM_TOKENS: frozenset[str] = frozenset(
    {"query", "q", "text", "term", "keyword", "keywords", "name", "search", "phrase"}
)

# Parameter names that mean "this tool returns many rows".
PAGINATION_PARAM_TOKENS: frozenset[str] = frozenset(
    {"limit", "page", "offset", "cursor", "per_page", "max_results", "count"}
)


def tokenize(name: str) -> tuple[str, ...]:
    """Split a tool or parameter name into lowercase word tokens."""
    parts = _SPLIT_RE.split(name)
    return tuple(p.lower() for p in parts if p)


def singularise(token: str) -> str:
    """Crude English de-pluralisation, so ``invoice`` and ``invoices`` cluster together."""
    if len(token) > 3 and token.endswith("ies"):
        return f"{token[:-3]}y"
    if len(token) > 3 and token.endswith("ses"):
        return token[:-2]
    if len(token) > 2 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def verb_class(verb: str) -> str | None:
    for name, members in VERB_CLASSES.items():
        if verb in members:
            return name
    return None


def confusable_group(verb: str) -> str | None:
    """The group of verb classes this verb competes with, or ``None`` if it is not a verb."""
    cls = verb_class(verb)
    if cls is None:
        return None
    for group, classes in CONFUSABLE_GROUPS.items():
        if cls in classes:
            return group
    return None


def split_verb_noun(name: str) -> tuple[str, tuple[str, ...]]:
    """Split a tool name into ``(verb, noun_tokens)``.

    Recognises the verb wherever it sits, which matters more than it looks. All four of
    these are the same tool under a different naming scheme, and all four must yield the
    verb ``get`` and the noun ``customer``-ish:

    ``get_customer``, ``customer_get``, ``crm_retrieve_customer``, ``getcust``.

    Miss the last two and every confusability judgement silently becomes "these names are
    not comparable", which makes an abbreviated or namespaced catalogue look like it fixed
    a confusion problem it merely obscured from the parser.

    Returns an empty verb when nothing is recognisable, which callers must treat as
    "leave this name alone".
    """
    tokens = tokenize(name)
    if not tokens:
        return "", ()
    # A trailing verb wins over a leading one, so `customer_get` reads as noun_verb
    # rather than as a noun called "customer" belonging to a verb called "get".
    if len(tokens) > 1 and tokens[-1] in VERBS and tokens[0] not in VERBS:
        return tokens[-1], tokens[:-1]
    for index, token in enumerate(tokens):
        if token in VERBS:
            return token, tokens[:index] + tokens[index + 1 :]
    if len(tokens) == 1:
        return _split_glued(tokens[0])
    return "", tokens


def _split_glued(token: str) -> tuple[str, tuple[str, ...]]:
    """Pull a verb off the front of a separator-free name: ``getcust`` -> ``get``, ``cust``.

    Longest prefix wins, so ``search`` beats ``sea``. The remainder must be at least two
    characters, which stops ``ping`` from being read as the verb ``pin`` plus a noun.
    """
    candidates = sorted(VERBS | set(VERB_ABBREVIATIONS.values()), key=len, reverse=True)
    for prefix in candidates:
        if token.startswith(prefix) and len(token) - len(prefix) >= 2:
            return _canonical_verb(prefix), (token[len(prefix) :],)
    return "", (token,)


def _canonical_verb(verb: str) -> str:
    """Map a verb abbreviation back to the verb it abbreviates."""
    if verb in VERBS:
        return verb
    for full, short in VERB_ABBREVIATIONS.items():
        if short == verb:
            return full
    return verb


def subject_key(name: str) -> tuple[str, tuple[str, ...]] | None:
    """The confusability key of a tool name: ``(confusable_group, singular noun tokens)``.

    Two tools share a key exactly when their names differ only by a synonym of the same
    verb - which is the thing ``naming.synonyms`` exists to eliminate and the thing the
    mock provider is built to be confused by.
    """
    verb, nouns = split_verb_noun(name)
    if not verb or not nouns:
        return None
    group = confusable_group(verb)
    if group is None:
        return None
    return group, tuple(singularise(t) for t in nouns)


def abbreviate_noun(token: str) -> str:
    if token in NOUN_ABBREVIATIONS:
        return NOUN_ABBREVIATIONS[token]
    return token[:4]


def abbreviate_verb(verb: str) -> str:
    return VERB_ABBREVIATIONS.get(verb, verb[:4])


def expand_verb(verb: str) -> str:
    return VERB_EXPANSIONS.get(verb, verb)


def strip_prefix_tokens(name: str, prefix_tokens: Iterable[str]) -> str:
    """Drop leading noun tokens from a parameter name: ``customer_id`` -> ``id``."""
    tokens = list(tokenize(name))
    prefixes = {singularise(t) for t in prefix_tokens}
    while len(tokens) > 1 and singularise(tokens[0]) in prefixes:
        tokens.pop(0)
    return "_".join(tokens)


def fit_name(name: str, limit: int = 64) -> str:
    """Truncate a generated name to the protocol limit, deterministically and uniquely."""
    if len(name) <= limit:
        return name
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:6]
    return f"{name[: limit - 7]}_{digest}"


def uniquify(proposed: Sequence[str]) -> tuple[str, ...]:
    """Make generated names unique by appending ``_2``, ``_3``, ... in catalogue order.

    Order-stable and deterministic: whichever tool claims a name first keeps it.
    """
    seen: dict[str, int] = {}
    out: list[str] = []
    for name in proposed:
        if name not in seen:
            seen[name] = 1
            out.append(name)
            continue
        while True:
            seen[name] += 1
            candidate = fit_name(f"{name}_{seen[name]}")
            if candidate not in seen:
                seen[candidate] = 1
                out.append(candidate)
                break
    return tuple(out)
