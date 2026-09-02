"""The canonical model: validation, provenance, and argument-space helpers."""

from __future__ import annotations

import pytest

from toolsweep.catalogue import (
    Catalogue,
    CatalogueError,
    EnumValue,
    Param,
    Tool,
    find_param_by_origin,
    flatten_args,
    nest_args,
    param_path_map,
    reset_origins,
    resolve_args,
    stamp_origin_paths,
    walk_params,
)

# --------------------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------------------


def test_a_tool_name_must_be_acceptable_to_every_protocol():
    for bad in ("get customer", "get.customer", "", "a" * 65, "get/customer"):
        with pytest.raises(CatalogueError):
            Tool(name=bad)


def test_duplicate_tool_names_are_rejected():
    with pytest.raises(CatalogueError, match="duplicate tool names"):
        Catalogue(tools=(Tool(name="a"), Tool(name="a")))


def test_duplicate_origins_are_rejected():
    """Two tools claiming the same as-authored identity would break rename resolution."""
    with pytest.raises(CatalogueError, match="duplicate tool origins"):
        Catalogue(tools=(Tool(name="a", origin="z"), Tool(name="b", origin="z")))


def test_duplicate_parameter_names_are_rejected():
    with pytest.raises(CatalogueError, match="duplicate parameter names"):
        Tool(name="t", params=(Param("x"), Param("x")))


def test_an_unknown_parameter_type_is_rejected():
    with pytest.raises(CatalogueError, match="unknown parameter type"):
        Param("x", "datetime")  # type: ignore[arg-type]


def test_properties_require_an_object_type():
    with pytest.raises(CatalogueError, match="has properties but type"):
        Param("x", "string", properties=(Param("y"),))


def test_an_empty_enum_code_is_rejected():
    with pytest.raises(CatalogueError, match="must not be empty"):
        EnumValue("")


# --------------------------------------------------------------------------------------
# Provenance defaults
# --------------------------------------------------------------------------------------


def test_origin_defaults_to_the_current_name():
    assert Tool(name="get_customer").origin == "get_customer"
    assert Param("customer_id").origin_path == "customer_id"
    assert EnumValue("ACT").origin_code == "ACT"


def test_an_enum_label_defaults_to_its_code():
    assert EnumValue("ACT").label == "ACT"
    assert EnumValue("ACT", "active").label == "active"


def test_stamping_writes_full_dotted_paths():
    params = stamp_origin_paths(
        (Param("filter", "object", properties=(Param("status"), Param("region"))),)
    )
    paths = {p.origin_path for _, p in walk_params(params)}
    assert paths == {"filter", "filter.status", "filter.region"}


def test_reset_origins_re_stamps_from_current_names(small_catalogue):
    """Provenance is run state, so a round trip can only be compared after resetting it."""
    from dataclasses import replace

    renamed = small_catalogue.with_tools(
        [replace(small_catalogue.tools[0], name="renamed_tool"), *small_catalogue.tools[1:]]
    )
    assert renamed.tools[0].origin == "get_customer"
    assert reset_origins(renamed).tools[0].origin == "renamed_tool"


def test_is_essential_falls_back_to_required():
    assert Param("x", required=True).is_essential is True
    assert Param("x", required=False).is_essential is False
    assert Param("x", required=True, essential=False).is_essential is False
    assert Param("x", required=False, essential=True).is_essential is True


# --------------------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------------------


def test_rename_maps_are_inverses(small_catalogue):
    forward = small_catalogue.rename_map()
    backward = small_catalogue.inverse_rename_map()
    for origin, current in forward.items():
        assert backward[current] == origin


def test_resolve_tool_returns_none_for_a_dropped_tool(small_catalogue):
    subset = small_catalogue.with_tools(small_catalogue.tools[:1])
    assert subset.resolve_tool("get_customer") == "get_customer"
    assert subset.resolve_tool("find_customer") is None


def test_param_path_map_tracks_moves(small_catalogue):
    tool = small_catalogue.by_name("search_customer")
    assert tool is not None
    assert param_path_map(tool)["filter.status"] == "filter.status"
    assert find_param_by_origin(tool, "filter.region") is not None
    assert find_param_by_origin(tool, "filter.nope") is None


# --------------------------------------------------------------------------------------
# Argument helpers
# --------------------------------------------------------------------------------------


def test_flatten_and_nest_round_trip():
    nested = {"a": 1, "b": {"c": 2, "d": {"e": 3}}}
    flat = flatten_args(nested)
    assert flat == {"a": 1, "b.c": 2, "b.d.e": 3}
    assert nest_args(flat) == nested


def test_flatten_keeps_an_empty_object_as_a_leaf():
    """An empty object is a value, not a path prefix; dropping it would lose an argument."""
    assert flatten_args({"a": {}}) == {"a": {}}


def test_nest_refuses_a_path_that_collides_with_a_scalar():
    with pytest.raises(CatalogueError, match="collides with a scalar"):
        nest_args({"a": 1, "a.b": 2})


def test_resolve_args_drops_paths_the_presented_tool_does_not_have(small_catalogue):
    tool = small_catalogue.by_name("get_customer")
    assert tool is not None
    assert resolve_args(tool, {"customer_id": "x", "gone": "y"}) == {"customer_id": "x"}


def test_resolve_args_leaves_non_enum_values_untouched(small_catalogue):
    tool = small_catalogue.by_name("get_customer")
    assert tool is not None
    assert resolve_args(tool, {"customer_id": 7}) == {"customer_id": 7}


def test_catalogue_len_and_names(small_catalogue):
    assert len(small_catalogue) == 4
    assert small_catalogue.names[0] == "get_customer"
    assert small_catalogue.origins == small_catalogue.names
