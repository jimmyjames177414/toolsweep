"""The correctness trap: expected labels must follow renames.

A task suite says ``expected_tool: get_customer``. The ``naming.synonyms`` arm shows the
model a catalogue where that tool is called ``get_customer_by_id``. If scoring compares
the model's answer to the *suite's* string, the model is right and toolsweep records it
as wrong - for every item, in every naming arm, silently. Every test still passes. The
report still renders. The conclusion "renaming costs you 40 points" is manufactured
entirely by the bug.

This file exists to make that regression impossible to ship. If you are reading it because
one of these tests failed after a refactor, the fix is almost certainly that something
started comparing to ``item.expected_tool`` instead of calling
``Catalogue.resolve_tool``.

Verified by breaking it: replacing the ``resolve_tool`` call in ``score.score_call``
with ``expected_name = item.expected_tool`` turns **5** of the tests below red -
``test_expected_label_is_resolved_through_the_rename_map``,
``test_scoring_refuses_rather_than_guesses_when_a_tool_was_dropped``, and the
``noun_verb`` / ``terse`` / ``verbose`` cases of
``test_every_naming_scheme_level_keeps_expected_labels_resolvable``. The ``verb_noun``
case survives, because this catalogue is already authored verb-first and that level
renames nothing - which is exactly why a single-catalogue naming test would not have
caught the bug.
"""

from __future__ import annotations

import json

import pytest

from toolsweep import adapters
from toolsweep.catalogue import find_param_by_origin, flatten_args, resolve_args
from toolsweep.factors import FactorContext, build
from toolsweep.factors.enum_wording import EnumWordingFactor
from toolsweep.factors.naming_scheme import NamingSchemeFactor
from toolsweep.factors.naming_synonyms import NamingSynonymsFactor
from toolsweep.factors.schema_nesting import SchemaNestingFactor
from toolsweep.score import ToolCall, score_call
from toolsweep.suite import Item

# --------------------------------------------------------------------------------------
# Tool names
# --------------------------------------------------------------------------------------


def test_expected_label_is_resolved_through_the_rename_map(crm_catalogue):
    """The core assertion. Everything else in this file supports it."""
    renamed = NamingSynonymsFactor(FactorContext(catalogue=crm_catalogue)).apply(
        "distinct_verbs", crm_catalogue
    )
    item = Item(id="t1", prompt="...", expected_tool="get_customer")

    presented = renamed.resolve_tool("get_customer")
    assert presented == "get_customer_by_id"
    # Precondition for this test meaning anything: the name really did change.
    assert presented != item.expected_tool

    score = score_call(item, renamed, ToolCall(name=presented, arguments={}))
    assert score.correct, "a correct answer under a renamed catalogue was scored wrong"
    assert score.called_origin == "get_customer"


def test_answering_with_the_old_name_is_wrong(crm_catalogue):
    """The mirror image: the pre-rename name is not in the catalogue any more.

    Without this, a scorer could 'pass' the test above by accepting both names, which
    would quietly count a hallucinated name as correct.
    """
    renamed = NamingSynonymsFactor(FactorContext(catalogue=crm_catalogue)).apply(
        "distinct_verbs", crm_catalogue
    )
    item = Item(id="t1", prompt="...", expected_tool="get_customer")
    score = score_call(item, renamed, ToolCall(name="get_customer", arguments={}))
    assert not score.correct
    assert score.hallucinated, "a name absent from the presented catalogue is a hallucination"


@pytest.mark.parametrize("level", ["verb_noun", "noun_verb", "terse", "verbose"])
def test_every_naming_scheme_level_keeps_expected_labels_resolvable(level, crm_catalogue):
    renamed = NamingSchemeFactor(FactorContext(catalogue=crm_catalogue)).apply(level, crm_catalogue)
    for origin in crm_catalogue.origins:
        presented = renamed.resolve_tool(origin)
        assert presented is not None, f"{level} made {origin!r} unresolvable"
        item = Item(id=origin, prompt="...", expected_tool=origin)
        assert score_call(item, renamed, ToolCall(name=presented, arguments={})).correct


def test_scoring_refuses_rather_than_guesses_when_a_tool_was_dropped(crm_catalogue):
    """A dropped expected tool is a bug, not a zero. It must raise, loudly."""
    subset = crm_catalogue.with_tools([t for t in crm_catalogue.tools if t.name != "get_customer"])
    item = Item(id="t1", prompt="...", expected_tool="get_customer")
    with pytest.raises(ValueError, match="absent from the presented catalogue"):
        score_call(item, subset, ToolCall(name="find_customer", arguments={}))


def test_origin_survives_stacked_transformations(crm_catalogue):
    """Provenance has to survive a rename applied on top of another transform."""
    ctx = FactorContext(catalogue=crm_catalogue)
    once = NamingSynonymsFactor(ctx).apply("distinct_verbs", crm_catalogue)
    twice = NamingSchemeFactor(ctx).apply("noun_verb", once)
    assert set(twice.origins) == set(crm_catalogue.origins)
    assert twice.resolve_tool("get_customer") is not None
    assert twice.resolve_tool("get_customer") != "get_customer"


# --------------------------------------------------------------------------------------
# The wire: provenance must never leak to the model
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("fmt", adapters.FORMATS)
def test_pre_rename_names_never_reach_the_wire(fmt, crm_catalogue):
    """If the model can see the old names, the naming experiment measures nothing.

    ``origin`` is run state. Serialising it - even into an ``x-`` extension - would show
    the model both names at once and quietly invalidate every naming arm.
    """
    renamed = NamingSynonymsFactor(FactorContext(catalogue=crm_catalogue)).apply(
        "distinct_verbs", crm_catalogue
    )
    changed = {t.origin for t in renamed.tools if t.origin != t.name}
    assert changed, "fixture problem: nothing was actually renamed"

    for extensions in (False, True):
        blob = json.dumps(adapters.dump(renamed, fmt, extensions=extensions))
        for old_name in changed:
            assert f'"{old_name}"' not in blob, f"{fmt} leaked the pre-rename name {old_name!r}"


# --------------------------------------------------------------------------------------
# Argument paths and enum values: the same trap, one level down
# --------------------------------------------------------------------------------------


def test_expected_arguments_resolve_through_a_nesting_change(crm_catalogue):
    nested = SchemaNestingFactor(FactorContext(catalogue=crm_catalogue)).apply(
        "nested", crm_catalogue
    )
    tool = nested.by_origin("search_customer")
    assert tool is not None

    resolved = resolve_args(tool, {"filter_status": "ACT", "limit": 5})
    assert resolved == {"filter": {"status": "ACT"}, "limit": 5}

    item = Item(
        id="t1",
        prompt="...",
        expected_tool="search_customer",
        expected_args={"filter_status": "ACT", "limit": 5},
    )
    score = score_call(item, nested, ToolCall(name=tool.name, arguments=resolved))
    assert score.correct and score.args_valid and score.args_match


def test_expected_arguments_resolve_through_a_flattening_change(small_catalogue):
    flat = SchemaNestingFactor(FactorContext(catalogue=small_catalogue)).apply(
        "flat", small_catalogue
    )
    tool = flat.by_origin("search_customer")
    assert tool is not None
    assert find_param_by_origin(tool, "filter.status") is not None
    assert resolve_args(tool, {"filter": {"status": "ACT"}}) == {"filter_status": "ACT"}


def test_expected_enum_values_resolve_through_a_wording_change(crm_catalogue):
    reworded = EnumWordingFactor(FactorContext(catalogue=crm_catalogue)).apply(
        "alternate_wording", crm_catalogue
    )
    tool = reworded.by_origin("search_customer")
    assert tool is not None
    # The suite says ACT; the model was shown "active".
    assert resolve_args(tool, {"filter_status": "ACT"}) == {"filter_status": "active"}

    item = Item(
        id="t1",
        prompt="...",
        expected_tool="search_customer",
        expected_args={"filter_status": "ACT"},
    )
    score = score_call(
        item, reworded, ToolCall(name=tool.name, arguments={"filter_status": "active"})
    )
    assert score.correct and score.args_valid and score.args_match
    # And the literal authored code is now *invalid* against the presented schema.
    assert (
        score_call(
            item, reworded, ToolCall(name=tool.name, arguments={"filter_status": "ACT"})
        ).args_valid
        is False
    )


def test_every_factor_keeps_every_expected_argument_resolvable(crm_catalogue, crm_suite):
    """Sweep-wide: no registered factor may orphan an argument the suite names."""
    from toolsweep.factors import FACTOR_IDS

    ctx = FactorContext(catalogue=crm_catalogue, pinned_tools=crm_suite.expected_tools, seed=7)
    for factor_id in FACTOR_IDS:
        factor = build(factor_id, ctx)
        for level in factor.levels:
            transformed = factor.apply(level, crm_catalogue)
            for item in crm_suite.items:
                tool = transformed.by_origin(item.expected_tool)
                assert tool is not None, f"{factor_id}={level} dropped {item.expected_tool}"
                if not item.expected_args:
                    continue
                resolved = resolve_args(tool, item.expected_args)
                # Compare *leaves*, not top-level keys: nesting legitimately turns three
                # top-level arguments into two, and counting keys would call that a loss.
                assert len(flatten_args(resolved)) == len(flatten_args(item.expected_args)), (
                    f"{factor_id}={level} orphaned an argument of {item.expected_tool!r} "
                    f"for item {item.id!r}: {resolved}"
                )
