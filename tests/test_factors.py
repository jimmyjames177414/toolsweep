"""The factor contracts, enforced against every registered factor automatically.

Adding a factor to the registry adds it to every test in this file. That is deliberate:
"add a factor" is the project's flagship good-first-issue, and a contributor should get
purity, idempotency and schema-validity checks for free rather than having to remember
them.
"""

from __future__ import annotations

import json

import pytest

from toolsweep import adapters
from toolsweep.catalogue import TOOL_NAME_RE, Catalogue, walk_params
from toolsweep.factors import FACTOR_IDS, FactorContext, build, parse_specs
from toolsweep.factors.catalogue_size import CatalogueSizeFactor
from toolsweep.factors.description_length import DescriptionLengthFactor
from toolsweep.factors.description_negative import DescriptionNegativeFactor
from toolsweep.factors.enum_wording import EnumWordingFactor
from toolsweep.factors.naming_scheme import NamingSchemeFactor
from toolsweep.factors.naming_synonyms import NamingSynonymsFactor
from toolsweep.factors.params_required import ParamsRequiredFactor
from toolsweep.factors.schema_nesting import SchemaNestingFactor


def _cases(catalogue: Catalogue, pinned: frozenset[str] = frozenset()):
    ctx = FactorContext(catalogue=catalogue, pinned_tools=pinned, seed=7)
    for factor_id in FACTOR_IDS:
        factor = build(factor_id, ctx)
        for level in factor.levels:
            yield factor, level


# --------------------------------------------------------------------------------------
# Contract 1: purity
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "catalogue_name", ["crm_catalogue", "small_catalogue", "awkward_catalogue"]
)
def test_every_factor_is_pure(catalogue_name, request):
    catalogue = request.getfixturevalue(catalogue_name)
    for factor, level in _cases(catalogue):
        first = factor.apply(level, catalogue)
        second = factor.apply(level, catalogue)
        assert first == second, f"{factor.id}={level} is not a pure function"
        assert catalogue == request.getfixturevalue(catalogue_name), (
            f"{factor.id}={level} mutated its input"
        )


# --------------------------------------------------------------------------------------
# Contract 2: idempotency
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "catalogue_name", ["crm_catalogue", "small_catalogue", "awkward_catalogue"]
)
def test_every_factor_level_is_idempotent(catalogue_name, request):
    """apply(level, apply(level, c)) == apply(level, c).

    A level names a destination, not a step. This is the test that catches a naming
    transform which oscillates - ``get_index`` -> ``crm_retrieve_index`` ->
    ``crm_index_crm_retrieve`` - which is exactly what ``awkward_catalogue`` is for.
    """
    catalogue = request.getfixturevalue(catalogue_name)
    for factor, level in _cases(catalogue):
        once = factor.apply(level, catalogue)
        twice = factor.apply(level, once)
        assert once == twice, f"{factor.id}={level} is not idempotent"


# --------------------------------------------------------------------------------------
# Contract 3: never emits an invalid schema
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "catalogue_name", ["crm_catalogue", "small_catalogue", "awkward_catalogue"]
)
@pytest.mark.parametrize("fmt", adapters.FORMATS)
def test_every_factor_result_round_trips_through_every_adapter(catalogue_name, fmt, request):
    catalogue = request.getfixturevalue(catalogue_name)
    for factor, level in _cases(catalogue):
        result = factor.apply(level, catalogue)
        payload = adapters.dump(result, fmt, extensions=True)
        # Must be JSON-serialisable: this is what actually goes over the wire.
        reloaded = adapters.load(json.loads(json.dumps(payload)), fmt)
        assert reloaded.names == result.names, f"{factor.id}={level} lost tools via {fmt}"
        for original, seen in zip(result.tools, reloaded.tools, strict=True):
            assert original.description == seen.description
            assert [p.name for _, p in walk_params(original.params)] == [
                p.name for _, p in walk_params(seen.params)
            ]


@pytest.mark.parametrize(
    "catalogue_name", ["crm_catalogue", "small_catalogue", "awkward_catalogue"]
)
def test_every_factor_result_is_a_valid_catalogue(catalogue_name, request):
    catalogue = request.getfixturevalue(catalogue_name)
    for factor, level in _cases(catalogue):
        result = factor.apply(level, catalogue)
        assert len(set(result.names)) == len(result.names), f"{factor.id}={level} made duplicates"
        for name in result.names:
            assert TOOL_NAME_RE.match(name), f"{factor.id}={level} produced illegal name {name!r}"
        for tool in result.tools:
            for path, param in walk_params(tool.params):
                assert param.name, f"{factor.id}={level} produced an unnamed parameter at {path}"


# --------------------------------------------------------------------------------------
# Contract 4: the control level changes nothing
# --------------------------------------------------------------------------------------


def test_control_level_is_the_identity(crm_catalogue):
    ctx = FactorContext(catalogue=crm_catalogue, seed=7)
    for factor_id in FACTOR_IDS:
        factor = build(factor_id, ctx)
        assert factor.control_level in factor.levels
        assert factor.apply(factor.control_level, crm_catalogue) == crm_catalogue


def test_every_factor_describes_every_level(crm_catalogue):
    ctx = FactorContext(catalogue=crm_catalogue, seed=7)
    for factor_id in FACTOR_IDS:
        factor = build(factor_id, ctx)
        for level in factor.levels:
            assert factor.describe(level).strip(), f"{factor_id}={level} has no description"


def test_unknown_level_is_rejected(crm_catalogue):
    factor = build("naming.scheme", FactorContext(catalogue=crm_catalogue))
    with pytest.raises(ValueError, match="has no level"):
        factor.apply("shouty_caps", crm_catalogue)


# --------------------------------------------------------------------------------------
# Per-factor behaviour
# --------------------------------------------------------------------------------------


def test_naming_scheme_moves_the_verb(small_catalogue):
    factor = NamingSchemeFactor(FactorContext(catalogue=small_catalogue))
    assert "customer_get" in factor.apply("noun_verb", small_catalogue).names
    assert "get_customer" in factor.apply("verb_noun", small_catalogue).names
    terse = factor.apply("terse", small_catalogue).names
    assert "getcust" in terse
    verbose = factor.apply("verbose", small_catalogue).names
    assert "api_retrieve_customer" in verbose


def test_naming_scheme_leaves_verbless_names_alone(awkward_catalogue):
    factor = NamingSchemeFactor(FactorContext(catalogue=awkward_catalogue))
    for level in ("verb_noun", "noun_verb", "terse", "verbose"):
        assert "ping" in factor.apply(level, awkward_catalogue).names


def test_naming_scheme_never_collides(awkward_catalogue):
    """`get_customer` and `getCustomer` both want the same name under three levels."""
    factor = NamingSchemeFactor(FactorContext(catalogue=awkward_catalogue))
    for level in factor.levels:
        names = factor.apply(level, awkward_catalogue).names
        assert len(set(names)) == len(names), f"{level} produced a duplicate name"


def test_naming_synonyms_splits_the_cluster(crm_catalogue):
    factor = NamingSynonymsFactor(FactorContext(catalogue=crm_catalogue))
    result = factor.apply("distinct_verbs", crm_catalogue)
    mapping = result.rename_map()

    assert mapping["get_customer"] == "get_customer_by_id"
    assert mapping["lookup_customer"] == "get_customer_by_email"
    assert mapping["find_customer"] == "search_customer_by_name"
    assert mapping["list_invoices"].startswith("list_invoice_by_")
    # Unrelated tools keep their names: the factor only touches confusable clusters.
    assert mapping["create_invoice"] == "create_invoice"
    assert mapping["close_task"] == "close_task"


def test_naming_synonyms_leaves_no_pair_differing_only_by_verb(crm_catalogue):
    """The property the factor exists to establish, checked directly."""
    from toolsweep.factors._text import subject_key

    factor = NamingSynonymsFactor(FactorContext(catalogue=crm_catalogue))
    result = factor.apply("distinct_verbs", crm_catalogue)
    keys = [subject_key(name) for name in result.names]
    real = [k for k in keys if k is not None]
    assert len(set(real)) == len(real), "two tools still differ only by a synonym of the verb"


def test_description_length_terse_keeps_one_sentence(crm_catalogue):
    factor = DescriptionLengthFactor(FactorContext(catalogue=crm_catalogue))
    result = factor.apply("terse", crm_catalogue)
    tool = result.by_name("get_customer")
    assert tool is not None
    assert tool.description.endswith(".")
    assert tool.description.count(".") == 1


def test_description_length_verbose_names_every_parameter(crm_catalogue):
    factor = DescriptionLengthFactor(FactorContext(catalogue=crm_catalogue))
    result = factor.apply("verbose", crm_catalogue)
    tool = result.by_name("create_invoice")
    assert tool is not None
    for param in tool.params:
        assert param.name in tool.description
    assert "required" in tool.description


def test_description_negative_uses_authored_text_when_present(crm_catalogue):
    factor = DescriptionNegativeFactor(FactorContext(catalogue=crm_catalogue))
    authored = crm_catalogue.by_name("get_customer")
    assert authored is not None and authored.not_for

    with_negative = factor.apply("with", crm_catalogue).by_name("get_customer")
    assert with_negative is not None
    assert authored.not_for in with_negative.description

    without = factor.apply("without", crm_catalogue).by_name("get_customer")
    assert without is not None
    assert authored.not_for not in without.description


def test_description_negative_synthesises_only_when_nothing_was_authored(small_catalogue):
    factor = DescriptionNegativeFactor(FactorContext(catalogue=small_catalogue))
    result = factor.apply("with", small_catalogue)

    authored = result.by_name("get_customer")
    assert authored is not None
    assert "when you only have an email address." in authored.description

    synthesised = result.by_name("find_customer")
    assert synthesised is not None
    assert "get_customer" in synthesised.description


def test_enum_wording_swaps_the_wire_value_and_adds_a_legend(crm_catalogue):
    factor = EnumWordingFactor(FactorContext(catalogue=crm_catalogue))
    result = factor.apply("alternate_wording", crm_catalogue)
    tool = result.by_name("search_customer")
    assert tool is not None
    status = next(p for p in tool.params if p.name == "filter_status")
    assert [e.code for e in status.enum] == ["active", "inactive", "pending activation", "churned"]
    assert [e.origin_code for e in status.enum] == ["ACT", "INACT", "PEND", "CHURN"]
    assert "active = ACT" in status.description


def test_enum_wording_is_inert_without_labels(small_catalogue):
    """A catalogue whose codes and labels agree gets a catalogue back unchanged."""
    stripped = Catalogue(
        tools=tuple(
            t for t in small_catalogue.tools if not any(p.enum or p.properties for p in t.params)
        )
    )
    factor = EnumWordingFactor(FactorContext(catalogue=stripped))
    assert factor.apply("alternate_wording", stripped) == stripped


def test_schema_nesting_flattens_and_preserves_origin_paths(small_catalogue):
    factor = SchemaNestingFactor(FactorContext(catalogue=small_catalogue))
    flat = factor.apply("flat", small_catalogue).by_name("search_customer")
    assert flat is not None
    names = [p.name for p in flat.params]
    assert "filter_status" in names and "filter_region" in names
    origins = {p.origin_path for p in flat.params}
    assert "filter.status" in origins, "flattening lost the authored path"


def test_schema_nesting_groups_shared_prefixes(crm_catalogue):
    factor = SchemaNestingFactor(FactorContext(catalogue=crm_catalogue))
    nested = factor.apply("nested", crm_catalogue).by_name("search_customer")
    assert nested is not None
    grouped = next(p for p in nested.params if p.name == "filter")
    assert grouped.type == "object"
    assert {p.name for p in grouped.properties} == {"status", "region"}
    assert {p.origin_path for p in grouped.properties} == {"filter_status", "filter_region"}


def test_schema_nesting_keeps_a_required_child_of_an_optional_parent_optional(small_catalogue):
    optional_parent = Catalogue(
        tools=(
            small_catalogue.tools[2].__class__(
                name="search_customer",
                description="x",
                params=tuple(
                    p
                    if p.name != "filter"
                    else p.__class__(
                        name="filter",
                        type="object",
                        description=p.description,
                        required=False,
                        properties=p.properties,
                        origin_path="filter",
                    )
                    for p in small_catalogue.tools[2].params
                ),
            ),
        )
    )
    factor = SchemaNestingFactor(FactorContext(catalogue=optional_parent))
    flat = factor.apply("flat", optional_parent).tools[0]
    status = next(p for p in flat.params if p.name == "filter_status")
    assert not status.required


def test_params_required_all_and_minimal(small_catalogue):
    factor = ParamsRequiredFactor(FactorContext(catalogue=small_catalogue))

    everything = factor.apply("all_required", small_catalogue).by_name("search_customer")
    assert everything is not None
    assert all(p.required for p in everything.params)

    minimal = factor.apply("minimal_required", small_catalogue).by_name("create_invoice")
    assert minimal is not None
    by_name = {p.name: p for p in minimal.params}
    # amount_cents is authored required but explicitly not essential.
    assert by_name["customer_id"].required
    assert not by_name["amount_cents"].required


def test_catalogue_size_always_keeps_pinned_tools(crm_catalogue):
    pinned = frozenset({"get_customer", "close_task", "void_invoice"})
    factor = CatalogueSizeFactor(
        FactorContext(catalogue=crm_catalogue, pinned_tools=pinned, seed=3)
    )
    assert factor.levels[0] == "full"
    for level in factor.levels[1:]:
        result = factor.apply(level, crm_catalogue)
        assert pinned <= set(result.names), f"{level} dropped a pinned tool"
        assert len(result) == int(level[2:])


def test_catalogue_size_refuses_a_subset_smaller_than_the_pinned_set(crm_catalogue):
    pinned = frozenset(crm_catalogue.names)
    factor = CatalogueSizeFactor(FactorContext(catalogue=crm_catalogue, pinned_tools=pinned))
    # Every tool is pinned, so no subset smaller than the whole catalogue is possible.
    assert factor.levels == ("full",)


def test_catalogue_size_subsets_are_seed_stable(crm_catalogue):
    pinned = frozenset({"get_customer"})
    a = CatalogueSizeFactor(FactorContext(catalogue=crm_catalogue, pinned_tools=pinned, seed=1))
    b = CatalogueSizeFactor(FactorContext(catalogue=crm_catalogue, pinned_tools=pinned, seed=1))
    c = CatalogueSizeFactor(FactorContext(catalogue=crm_catalogue, pinned_tools=pinned, seed=2))
    # The largest subset level, where the seeded sample actually has something to choose.
    level = a.levels[-1]
    assert a.apply(level, crm_catalogue).names == b.apply(level, crm_catalogue).names
    assert a.apply(level, crm_catalogue).names != c.apply(level, crm_catalogue).names


def test_catalogue_size_smallest_level_is_exactly_what_the_suite_needs(crm_catalogue):
    """The most informative point on the curve, and the only seed-independent one."""
    pinned = frozenset({"get_customer", "create_invoice", "close_task"})
    factor = CatalogueSizeFactor(
        FactorContext(catalogue=crm_catalogue, pinned_tools=pinned, seed=1)
    )
    assert factor.levels[1] == f"n={len(pinned)}"
    assert set(factor.apply(factor.levels[1], crm_catalogue).names) == pinned


def test_catalogue_size_says_why_it_cannot_be_measured(crm_catalogue):
    """Every tool pinned means no subset is possible - which must be stated, not hidden."""
    everything = frozenset(crm_catalogue.names)
    factor = CatalogueSizeFactor(FactorContext(catalogue=crm_catalogue, pinned_tools=everything))
    assert factor.levels == ("full",)
    reason = factor.unavailable_reason
    assert reason is not None and "without dropping an answer" in reason


# --------------------------------------------------------------------------------------
# Spec parsing
# --------------------------------------------------------------------------------------


def test_parse_specs_never_returns_the_control_level(crm_catalogue):
    ctx = FactorContext(catalogue=crm_catalogue, pinned_tools=frozenset({"get_customer"}))
    for factor, levels in parse_specs(["all"], ctx):
        assert factor.control_level not in levels


def test_parse_specs_accepts_a_single_level(crm_catalogue):
    ctx = FactorContext(catalogue=crm_catalogue)
    pairs = parse_specs(["naming.synonyms=distinct_verbs"], ctx)
    assert len(pairs) == 1
    assert pairs[0][1] == ("distinct_verbs",)


def test_parse_specs_rejects_the_control_level_as_a_treatment(crm_catalogue):
    ctx = FactorContext(catalogue=crm_catalogue)
    with pytest.raises(ValueError, match="control level"):
        parse_specs(["naming.synonyms=as_authored"], ctx)


def test_parse_specs_rejects_an_unknown_factor(crm_catalogue):
    ctx = FactorContext(catalogue=crm_catalogue)
    with pytest.raises(ValueError, match="unknown factor"):
        parse_specs(["naming.vibes"], ctx)
