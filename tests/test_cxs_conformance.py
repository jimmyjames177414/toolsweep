"""CXS v0.1 conformance, asserted against a real run of the demo.

The spec says a project is conformant if it writes a manifest with ``cxs_version: "0.1"``
and all required fields, its ``trials.jsonl`` and ``outcomes.jsonl`` validate against the
vendored schemas, and it ships a test asserting both **on a real run of its own demo**.
This is that test. Conformance is a claim about files, and toolsweep does not make it
anywhere it is not backed by this file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from toolsweep import __version__, cxs
from toolsweep.cache import ResponseCache
from toolsweep.providers import MockConfig, MockProvider
from toolsweep.runner import SweepConfig, run

SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"


@pytest.fixture(scope="module")
def registry() -> Registry:
    """A resolver so ``$ref: model_descriptor.schema.json`` works from a local file."""
    resources = []
    for path in SCHEMAS.glob("*.schema.json"):
        contents = json.loads(path.read_text(encoding="utf-8"))
        resources.append((path.name, Resource.from_contents(contents)))
    return Registry().with_resources(resources)


def validator(name: str, registry: Registry) -> Draft202012Validator:
    schema = json.loads((SCHEMAS / name).read_text(encoding="utf-8"))
    return Draft202012Validator(schema, registry=registry)


@pytest.fixture(scope="module")
def demo_run(tmp_path_factory, request) -> Path:
    """A real, complete run of the shipped example. Not a hand-written fixture."""
    from toolsweep.adapters import load_file as load_catalogue
    from toolsweep.suite import load_file as load_suite

    examples = Path(__file__).resolve().parents[1] / "examples" / "crm"
    catalogue, _ = load_catalogue(examples / "catalogue.json")
    suite = load_suite(examples / "suite.jsonl")

    config = SweepConfig(
        catalogue=catalogue,
        suite=suite,
        factor_specs=("naming.synonyms", "enum.wording", "catalogue.size"),
        repeats=2,
        seed=7,
        resamples=200,
        dataset_name="crm",
    )
    provider = MockProvider(
        config=MockConfig(seed=7),
        expected_args={i.prompt: i.expected_args for i in suite.items if i.expected_args},
    )
    out = tmp_path_factory.mktemp("cxs")
    result = run(
        config,
        provider,
        ResponseCache(enabled=False),
        out_dir=out,
        version=__version__,
    )
    assert result.paths is not None
    return result.paths.root


# --------------------------------------------------------------------------------------
# 1. The manifest
# --------------------------------------------------------------------------------------


def test_manifest_validates(demo_run, registry):
    payload = json.loads((demo_run / "manifest.json").read_text(encoding="utf-8"))
    validator("run_manifest.schema.json", registry).validate(payload)
    assert payload["cxs_version"] == cxs.CXS_VERSION
    assert payload["tool"]["name"] == "toolsweep"


def test_manifest_contains_the_control_arm_as_a_noop_intervention(demo_run):
    """The rule the whole portfolio turns on: no effect without a control."""
    payload = json.loads((demo_run / "manifest.json").read_text(encoding="utf-8"))
    noops = [i for i in payload["interventions"] if i["kind"] == "noop"]
    assert len(noops) == 1
    assert noops[0]["id"] == "control"
    assert payload["interventions"][0]["kind"] == "noop", "arm zero must be listed first"


def test_manifest_does_not_claim_determinism_it_did_not_observe(demo_run):
    payload = json.loads((demo_run / "manifest.json").read_text(encoding="utf-8"))
    assert payload["determinism"] in ("deterministic", "stochastic")
    if payload["determinism"] == "deterministic":
        assert payload["repeats"] >= 2, "determinism cannot be observed from a single repeat"


# --------------------------------------------------------------------------------------
# 2. Interventions, trials, outcomes
# --------------------------------------------------------------------------------------


def test_interventions_validate(demo_run, registry):
    payload = json.loads((demo_run / "interventions.json").read_text(encoding="utf-8"))
    check = validator("intervention.schema.json", registry)
    assert payload
    for record in payload:
        check.validate(record)


def test_every_trial_validates(demo_run, registry):
    check = validator("trial.schema.json", registry)
    records = list(cxs.read_jsonl(demo_run / "trials.jsonl"))
    assert records, "the demo produced no trials"
    for record in records:
        check.validate(record)


def test_every_outcome_validates(demo_run, registry):
    check = validator("outcome.schema.json", registry)
    records = list(cxs.read_jsonl(demo_run / "outcomes.jsonl"))
    assert records, "the demo produced no outcomes"
    for record in records:
        check.validate(record)


def test_outcomes_join_to_trials_one_to_one(demo_run):
    """Outcome is a separate record so a run can be re-scored without re-calling."""
    trials = {r["trial_id"] for r in cxs.read_jsonl(demo_run / "trials.jsonl")}
    outcomes = [r["trial_id"] for r in cxs.read_jsonl(demo_run / "outcomes.jsonl")]
    assert len(outcomes) == len(set(outcomes))
    assert set(outcomes) == trials


def test_every_trial_names_an_intervention_the_manifest_declares(demo_run):
    payload = json.loads((demo_run / "manifest.json").read_text(encoding="utf-8"))
    declared = {i["id"] for i in payload["interventions"]}
    for record in cxs.read_jsonl(demo_run / "trials.jsonl"):
        assert record["intervention_id"] in declared


def test_the_full_on_disk_layout_is_present(demo_run):
    for name in ("manifest.json", "interventions.json", "trials.jsonl", "outcomes.jsonl"):
        assert (demo_run / name).is_file(), f"missing {name}"


# --------------------------------------------------------------------------------------
# 3. Append-only rawness
# --------------------------------------------------------------------------------------


def test_trials_jsonl_is_one_json_object_per_line(demo_run):
    """Append-only means line-oriented: a rewritten array would break resume."""
    text = (demo_run / "trials.jsonl").read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line.strip()]
    assert lines
    for line in lines:
        assert isinstance(json.loads(line), dict)


def test_a_trial_records_the_raw_response_not_a_summary(demo_run):
    records = list(cxs.read_jsonl(demo_run / "trials.jsonl"))
    called = [r for r in records if r.get("tool_call")]
    assert called, "the demo produced no tool calls at all"
    for record in called[:20]:
        assert record["response_text"], "raw response text was dropped"
        assert "name" in record["tool_call"]
