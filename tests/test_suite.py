"""Task-suite loading and its validation against the catalogue.

The suite is the measurement instrument. A suite that silently references a tool you
deleted produces a confident wrong answer, so loading fails loudly rather than skipping.
"""

from __future__ import annotations

import pytest

from toolsweep.suite import SuiteError, parse, validate_against


def test_parses_a_well_formed_suite():
    suite = parse(
        '{"id": "a", "prompt": "p", "expected_tool": "get_customer"}\n'
        '{"id": "b", "prompt": "q", "expected_tool": "find_customer", '
        '"expected_args": {"name": "x"}}\n'
    )
    assert len(suite) == 2
    assert suite.items[1].expected_args == {"name": "x"}


def test_blank_lines_and_comments_are_skipped():
    suite = parse('# a comment\n\n{"id": "a", "prompt": "p", "expected_tool": "t"}\n   \n')
    assert len(suite) == 1


def test_expected_tools_is_the_set_catalogue_size_pins(crm_suite):
    assert "get_customer" in crm_suite.expected_tools
    # The suite covers 14 of the catalogue's 20 tools. The six it does not cover are
    # what makes catalogue.size measurable at all.
    assert len(crm_suite.expected_tools) == 14


def test_duplicate_ids_are_rejected():
    with pytest.raises(SuiteError, match="duplicate item id"):
        parse('{"id": "a", "prompt": "p", "expected_tool": "t"}\n' * 2)


def test_missing_fields_are_rejected():
    with pytest.raises(SuiteError, match="expected_tool"):
        parse('{"id": "a", "prompt": "p"}')
    with pytest.raises(SuiteError, match="prompt"):
        parse('{"id": "a", "expected_tool": "t"}')


def test_malformed_json_names_the_line():
    with pytest.raises(SuiteError, match=":2:"):
        parse('{"id": "a", "prompt": "p", "expected_tool": "t"}\nnot json\n', source="s")


def test_an_empty_suite_is_rejected():
    with pytest.raises(SuiteError, match="no items found"):
        parse("# nothing here\n")


def test_expected_args_must_be_an_object():
    with pytest.raises(SuiteError, match="expected_args must be an object"):
        parse('{"id": "a", "prompt": "p", "expected_tool": "t", "expected_args": []}')


# --------------------------------------------------------------------------------------
# Validation against a catalogue
# --------------------------------------------------------------------------------------


def test_the_example_suite_matches_the_example_catalogue(crm_suite, crm_catalogue):
    validate_against(crm_suite, crm_catalogue)


def test_an_unknown_tool_is_rejected(small_catalogue):
    suite = parse('{"id": "a", "prompt": "p", "expected_tool": "delete_everything"}')
    with pytest.raises(SuiteError, match="not in the catalogue"):
        validate_against(suite, small_catalogue)


def test_an_unknown_argument_path_is_rejected(small_catalogue):
    suite = parse(
        '{"id": "a", "prompt": "p", "expected_tool": "get_customer", '
        '"expected_args": {"customer_uuid": "x"}}'
    )
    with pytest.raises(SuiteError, match="does not declare"):
        validate_against(suite, small_catalogue)


def test_a_nested_argument_path_is_accepted(small_catalogue):
    suite = parse(
        '{"id": "a", "prompt": "p", "expected_tool": "search_customer", '
        '"expected_args": {"filter": {"status": "ACT"}}}'
    )
    validate_against(suite, small_catalogue)


def test_every_problem_is_reported_not_just_the_first(small_catalogue):
    suite = parse(
        '{"id": "a", "prompt": "p", "expected_tool": "nope"}\n'
        '{"id": "b", "prompt": "p", "expected_tool": "also_nope"}\n'
    )
    with pytest.raises(SuiteError) as exc:
        validate_against(suite, small_catalogue)
    assert "nope" in str(exc.value) and "also_nope" in str(exc.value)
