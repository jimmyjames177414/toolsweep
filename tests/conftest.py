"""Shared fixtures. Everything here is synthetic and offline."""

from __future__ import annotations

from pathlib import Path

import pytest

from toolsweep.adapters import load_file as load_catalogue
from toolsweep.catalogue import Catalogue, EnumValue, Param, Tool, stamp_origin_paths
from toolsweep.suite import Suite
from toolsweep.suite import load_file as load_suite

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "crm"


@pytest.fixture(scope="session")
def examples_dir() -> Path:
    """The shipped example directory, as a fixture rather than an import.

    A test that wants this path must take the fixture. Importing ``EXAMPLES`` from this
    module as ``tests.conftest`` only works when the repository root happens to be on
    ``sys.path`` - true under ``python -m pytest``, false under the ``pytest`` console
    script that CI runs, because there is no ``tests/__init__.py``. A fixture has no such
    dependency on how pytest was invoked.
    """
    return EXAMPLES


@pytest.fixture(scope="session")
def crm_catalogue() -> Catalogue:
    catalogue, _ = load_catalogue(EXAMPLES / "catalogue.json")
    return catalogue


@pytest.fixture(scope="session")
def crm_suite() -> Suite:
    return load_suite(EXAMPLES / "suite.jsonl")


@pytest.fixture(scope="session")
def cassette_path() -> Path:
    return EXAMPLES / "cassette.json"


def tool(
    name: str,
    description: str = "A tool.",
    params: tuple[Param, ...] = (),
    not_for: str = "",
) -> Tool:
    return Tool(
        name=name,
        description=description,
        params=stamp_origin_paths(params),
        not_for=not_for,
    )


@pytest.fixture()
def small_catalogue() -> Catalogue:
    """A four-tool catalogue with one near-synonym cluster and one nested object."""
    return Catalogue(
        tools=(
            tool(
                "get_customer",
                "Retrieve one customer by id. Returns the whole record.",
                (Param("customer_id", "string", "The customer id.", required=True),),
                not_for="when you only have an email address.",
            ),
            tool(
                "find_customer",
                "Find customers by company name. Fuzzy.",
                (Param("name", "string", "Company name.", required=True),),
            ),
            tool(
                "search_customer",
                "Search customers by structured filters.",
                (
                    Param(
                        "filter",
                        "object",
                        "Filters.",
                        required=True,
                        properties=(
                            Param(
                                "status",
                                "string",
                                "Status.",
                                required=True,
                                enum=(
                                    EnumValue("ACT", "active"),
                                    EnumValue("INACT", "inactive"),
                                ),
                            ),
                            Param("region", "string", "Region."),
                        ),
                    ),
                    Param("limit", "integer", "Max rows."),
                ),
            ),
            tool(
                "create_invoice",
                "Create a draft invoice for a customer.",
                (
                    Param("customer_id", "string", "Customer.", required=True),
                    Param("amount_cents", "integer", "Amount.", required=True, essential=False),
                ),
            ),
        )
    )


@pytest.fixture()
def awkward_catalogue() -> Catalogue:
    """Names built to break naive naming transforms.

    ``get_index`` ends in a token that is itself a verb, which is what makes a naive
    ``verbose`` or ``noun_verb`` rename oscillate instead of settling. ``ping`` has no
    verb at all. Two tools collide under ``terse``.
    """
    return Catalogue(
        tools=(
            tool("get_index", "Retrieve the index."),
            tool("get_list", "Retrieve the list."),
            tool("ping", "Check liveness."),
            tool(
                "get_customer",
                "Retrieve one customer.",
                (Param("id", "string", "Id.", required=True),),
            ),
            tool(
                "getCustomer",
                "Retrieve one customer, camel case.",
                (Param("id", "string", "Id.", required=True),),
            ),
        ),
        namespace="crm",
    )
