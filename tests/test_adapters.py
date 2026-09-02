"""MCP / OpenAI / Anthropic / raw JSON Schema, in and out.

Fidelity is asserted for every ordered pair of formats, not just for a format against
itself, because a catalogue authored as MCP and sent to an OpenAI-compatible endpoint
crosses two adapters and any loss between them changes what the sweep measures.
"""

from __future__ import annotations

import itertools
import json

import pytest

from toolsweep import adapters
from toolsweep.catalogue import Catalogue, CatalogueError, reset_origins, walk_params

PAIRS = list(itertools.product(adapters.FORMATS, adapters.FORMATS))


@pytest.mark.parametrize("fmt", adapters.FORMATS)
def test_round_trip_is_lossless_with_extensions(fmt, crm_catalogue):
    """With the extension block, everything survives except run-state provenance."""
    payload = adapters.dump(crm_catalogue, fmt, extensions=True)
    reloaded = adapters.load(json.loads(json.dumps(payload)), fmt)
    assert reloaded == reset_origins(crm_catalogue)


@pytest.mark.parametrize("source,target", PAIRS)
def test_cross_format_conversion_preserves_the_wire_contract(source, target, crm_catalogue):
    """Names, descriptions, parameter trees, required-ness and enums survive any hop."""
    first = adapters.load(adapters.dump(crm_catalogue, source, extensions=True), source)
    second = adapters.load(adapters.dump(first, target, extensions=True), target)
    assert second == first


@pytest.mark.parametrize("fmt", adapters.FORMATS)
def test_wire_dump_drops_toolsweep_extensions(fmt, crm_catalogue):
    """The default dump is what a model sees; it must carry no toolsweep bookkeeping."""
    blob = json.dumps(adapters.dump(crm_catalogue, fmt))
    assert "x-toolsweep" not in blob
    assert "not_for" not in blob
    assert "essential" not in blob


@pytest.mark.parametrize("fmt", adapters.FORMATS)
def test_wire_dump_still_carries_every_tool_and_parameter(fmt, crm_catalogue):
    reloaded = adapters.load(adapters.dump(crm_catalogue, fmt), fmt)
    assert reloaded.names == crm_catalogue.names
    for original, seen in zip(crm_catalogue.tools, reloaded.tools, strict=True):
        assert original.description == seen.description
        assert [p for p, _ in walk_params(original.params)] == [
            p for p, _ in walk_params(seen.params)
        ]
        for (_, a), (_, b) in zip(
            walk_params(original.params), walk_params(seen.params), strict=True
        ):
            assert a.type == b.type
            assert a.required == b.required
            assert [e.code for e in a.enum] == [e.code for e in b.enum]


@pytest.mark.parametrize("fmt", adapters.FORMATS)
def test_format_detection_recognises_its_own_output(fmt, crm_catalogue):
    payload = adapters.dump(crm_catalogue, fmt)
    assert adapters.detect_format(payload) == fmt


def test_format_detection_refuses_rather_than_guesses():
    """A wrong guess would silently drop parameters, so detection abstains instead."""
    with pytest.raises(CatalogueError, match="cannot detect catalogue format"):
        adapters.detect_format([{"name": "x", "description": "y"}])
    with pytest.raises(CatalogueError, match="cannot detect catalogue format"):
        adapters.detect_format({"not_tools": []})
    with pytest.raises(CatalogueError, match="empty"):
        adapters.detect_format([])


def test_mcp_accepts_a_jsonrpc_envelope(crm_catalogue):
    inner = adapters.dump(crm_catalogue, "mcp")
    wrapped = {"jsonrpc": "2.0", "id": 1, "result": inner}
    assert adapters.load(wrapped, "mcp").names == crm_catalogue.names


def test_nested_objects_survive_every_format(small_catalogue):
    for fmt in adapters.FORMATS:
        reloaded = adapters.load(adapters.dump(small_catalogue, fmt, extensions=True), fmt)
        tool = reloaded.by_name("search_customer")
        assert tool is not None
        grouped = next(p for p in tool.params if p.name == "filter")
        assert grouped.type == "object"
        assert {p.name for p in grouped.properties} == {"status", "region"}
        status = next(p for p in grouped.properties if p.name == "status")
        assert status.required
        assert [e.label for e in status.enum] == ["active", "inactive"]


def test_essential_false_survives_the_round_trip(small_catalogue):
    """`required: true, essential: false` is the only case params.required can measure.

    A set-of-paths encoding cannot express it, so this is the test that keeps the
    extension block a map.
    """
    for fmt in adapters.FORMATS:
        reloaded = adapters.load(adapters.dump(small_catalogue, fmt, extensions=True), fmt)
        tool = reloaded.by_name("create_invoice")
        assert tool is not None
        amount = next(p for p in tool.params if p.name == "amount_cents")
        assert amount.required is True
        assert amount.essential is False
        assert amount.is_essential is False


def test_unknown_format_is_rejected(crm_catalogue):
    with pytest.raises(CatalogueError, match="unknown catalogue format"):
        adapters.dump(crm_catalogue, "protobuf")


def test_malformed_schemas_raise_rather_than_load_empty():
    with pytest.raises(CatalogueError, match="unsupported JSON Schema type"):
        adapters.load(
            [{"name": "t", "schema": {"type": "object", "properties": {"a": {"type": "date"}}}}],
            "jsonschema",
        )
    with pytest.raises(CatalogueError, match="must be a list of strings"):
        adapters.load(
            [{"name": "t", "schema": {"type": "object", "properties": {}, "required": "a"}}],
            "jsonschema",
        )


def test_duplicate_tool_names_are_rejected():
    with pytest.raises(CatalogueError, match="duplicate tool names"):
        adapters.load([{"name": "t", "schema": {}}, {"name": "t", "schema": {}}], "jsonschema")


def test_illegal_tool_names_are_rejected():
    with pytest.raises(CatalogueError, match="not accepted by every target protocol"):
        adapters.load([{"name": "get customer!", "schema": {}}], "jsonschema")


def test_load_file_detects_the_example_catalogue(examples_dir):
    catalogue, fmt = adapters.load_file(examples_dir / "catalogue.json")
    assert fmt == "mcp"
    assert isinstance(catalogue, Catalogue)
    assert len(catalogue) == 20
