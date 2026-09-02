"""Providers: the mock's determinism, the cassette's honesty, and request keying.

Nothing here touches a network. The OpenAI-compatible provider is exercised only through
its response parser, which is pure; anything that would open a socket is marked ``live``
and deselected by default.
"""

from __future__ import annotations

import json

import pytest

from toolsweep.providers import (
    CassetteError,
    CassetteProvider,
    MockConfig,
    MockProvider,
    Request,
    write_cassette,
)
from toolsweep.providers.openai_compatible import OpenAICompatibleProvider, _parse

# --------------------------------------------------------------------------------------
# Mock
# --------------------------------------------------------------------------------------


def test_the_mock_is_deterministic(small_catalogue):
    a = MockProvider(config=MockConfig(seed=3))
    b = MockProvider(config=MockConfig(seed=3))
    request = Request(prompt="Find the customer with id CUS-1", catalogue=small_catalogue)
    assert a.complete(request).tool_call == b.complete(request).tool_call


def test_the_mock_varies_across_repeats(crm_catalogue):
    """A stochastic provider must answer repeat 3 independently of repeat 1.

    Sharing an answer across repeats would collapse within-item variance to zero and make
    every interval narrower than the data supports.
    """
    provider = MockProvider(config=MockConfig(seed=3, confusion_rate=0.9))
    answers = {
        provider.complete(
            Request(
                prompt="Pull the record for customer id CUS-1041.",
                catalogue=crm_catalogue,
                repeat_index=r,
            )
        ).tool_call.name
        for r in range(12)
    }
    assert len(answers) > 1


def test_the_mock_confuses_only_within_a_synonym_cluster(crm_catalogue):
    provider = MockProvider(config=MockConfig(seed=3, confusion_rate=1.0))
    cluster = {"get_customer", "lookup_customer", "find_customer", "search_customer"}
    picks = {
        provider.complete(
            Request(
                prompt="Pull the record for customer id CUS-1041.",
                catalogue=crm_catalogue,
                repeat_index=r,
            )
        ).tool_call.name
        for r in range(30)
    }
    assert picks <= cluster, f"confusion escaped the cluster: {picks - cluster}"
    assert len(picks) > 1


def test_the_mock_never_hallucinates_or_declines_by_default(crm_catalogue):
    """Both rates default to zero, which is why the demo's columns for them read 0.0%."""
    provider = MockProvider()
    for repeat in range(25):
        response = provider.complete(
            Request(
                prompt="Void invoice INV-1 as a duplicate.",
                catalogue=crm_catalogue,
                repeat_index=repeat,
            )
        )
        assert response.tool_call is not None
        assert crm_catalogue.by_name(response.tool_call.name) is not None


def test_the_mock_reports_its_own_knobs_in_its_descriptor():
    descriptor = MockProvider(config=MockConfig(seed=5, confusion_rate=0.3)).descriptor
    assert descriptor.provider == "mock"
    assert descriptor.params["confusion_rate"] == 0.3
    assert "mock" in descriptor.model


# --------------------------------------------------------------------------------------
# Request keying
# --------------------------------------------------------------------------------------


def test_the_request_key_changes_with_the_catalogue(small_catalogue, crm_catalogue):
    """The catalogue is the part of the prompt under test; the key has to include it."""
    descriptor = MockProvider().descriptor
    a = Request(prompt="p", catalogue=small_catalogue).key(descriptor)
    b = Request(prompt="p", catalogue=crm_catalogue).key(descriptor)
    assert a != b


def test_the_request_key_changes_with_the_repeat_index(small_catalogue):
    descriptor = MockProvider().descriptor
    keys = {
        Request(prompt="p", catalogue=small_catalogue, repeat_index=r).key(descriptor)
        for r in range(3)
    }
    assert len(keys) == 3


def test_the_request_key_is_stable(small_catalogue):
    descriptor = MockProvider().descriptor
    request = Request(prompt="p", catalogue=small_catalogue)
    assert request.key(descriptor) == request.key(descriptor)
    assert len(request.key(descriptor)) == 64


# --------------------------------------------------------------------------------------
# Cassette
# --------------------------------------------------------------------------------------


def test_a_cassette_without_provenance_is_refused(tmp_path):
    """A fixture that looks like a model response must say if it was recorded or generated."""
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"model": {"model": "x"}, "entries": {}}))
    with pytest.raises(CassetteError, match="_provenance"):
        CassetteProvider(path)


def test_a_cassette_with_a_bogus_provenance_is_refused(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(
        json.dumps({"_provenance": "probably fine", "model": {"model": "x"}, "entries": {}})
    )
    with pytest.raises(CassetteError, match="_provenance"):
        CassetteProvider(path)


def test_write_cassette_refuses_an_unlabelled_provenance(tmp_path):
    with pytest.raises(CassetteError):
        write_cassette(
            tmp_path / "c.json",
            descriptor=MockProvider().descriptor,
            entries={},
            provenance="",
            note="",
        )


def test_a_cassette_miss_raises_rather_than_calling_a_model(tmp_path, small_catalogue):
    """Silently filling gaps would mix replayed and live numbers in one run."""
    path = tmp_path / "c.json"
    write_cassette(
        path,
        descriptor=MockProvider().descriptor,
        entries={},
        provenance="synthetic",
        note="test",
    )
    provider = CassetteProvider(path)
    with pytest.raises(CassetteError, match="no recorded response"):
        provider.complete(Request(prompt="p", catalogue=small_catalogue))


def test_the_shipped_cassette_is_labelled_synthetic(cassette_path):
    provider = CassetteProvider(cassette_path)
    assert provider.provenance == "synthetic"
    assert "MockProvider" in provider.note
    assert "not recorded from any language model" in provider.note
    assert len(provider) == 360


def test_the_shipped_cassette_replays_the_readme_command(cassette_path, crm_catalogue, crm_suite):
    """The exact grid the README documents, keyed and present."""
    from toolsweep.runner import SweepConfig, build_arms

    provider = CassetteProvider(cassette_path)
    config = SweepConfig(
        catalogue=crm_catalogue,
        suite=crm_suite,
        factor_specs=("naming.synonyms,description.negative",),
        repeats=3,
        seed=7,
    )
    for arm in build_arms(config):
        if arm.inert:
            continue
        for item in crm_suite.items:
            for repeat in range(3):
                response = provider.complete(
                    Request(prompt=item.prompt, catalogue=arm.catalogue, repeat_index=repeat)
                )
                assert response.cached, "a replay must be marked cached, never a live call"


# --------------------------------------------------------------------------------------
# OpenAI-compatible response parsing (pure; no socket)
# --------------------------------------------------------------------------------------


def test_parses_a_normal_tool_call():
    payload = {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "function": {
                                "name": "get_customer",
                                "arguments": '{"customer_id": "CUS-1"}',
                            }
                        }
                    ],
                }
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 8},
    }
    response = _parse(payload, 12)
    assert response.tool_call is not None
    assert response.tool_call.name == "get_customer"
    assert response.tool_call.arguments == {"customer_id": "CUS-1"}
    assert response.usage == {"prompt_tokens": 100, "completion_tokens": 8}


def test_a_reply_with_no_tool_call_is_a_no_call():
    payload = {"choices": [{"message": {"content": "I'd rather not."}}]}
    response = _parse(payload, 5)
    assert response.tool_call is None
    assert response.text == "I'd rather not."


def test_malformed_arguments_keep_the_selection_and_fail_validation():
    """The tool was chosen and the arguments are bad. Both facts are results."""
    payload = {
        "choices": [
            {
                "message": {
                    "tool_calls": [{"function": {"name": "get_customer", "arguments": "{not json"}}]
                }
            }
        ]
    }
    response = _parse(payload, 5)
    assert response.tool_call is not None
    assert response.tool_call.name == "get_customer"
    assert "__malformed__" in response.tool_call.arguments


def test_an_empty_response_is_an_error_not_a_crash():
    assert _parse({}, 0).error == "no choices"
    assert _parse({"choices": []}, 0).error == "no choices"


def test_the_openai_descriptor_records_a_null_seed_rather_than_omitting_it():
    """A run must state whether a seed was requested, not imply determinism it lacked."""
    descriptor = OpenAICompatibleProvider(base_url="http://x/v1", model="m").descriptor
    assert "seed" in descriptor.params
    assert descriptor.params["seed"] is None


def test_the_openai_base_url_is_normalised():
    provider = OpenAICompatibleProvider(base_url="http://x/v1/", model="m")
    assert provider.base_url == "http://x/v1"
