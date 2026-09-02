"""The command line: exit codes, the dry-run guardrail, and error messages."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from toolsweep.cli import main

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "crm"
CATALOGUE = str(EXAMPLES / "catalogue.json")
SUITE = str(EXAMPLES / "suite.jsonl")
CASSETTE = str(EXAMPLES / "cassette.json")


def test_no_arguments_prints_help(capsys):
    assert main([]) == 2
    assert "usage" in capsys.readouterr().out.lower()


def test_factors_lists_every_registered_factor(capsys):
    from toolsweep.factors import FACTOR_IDS

    assert main(["factors"]) == 0
    out = capsys.readouterr().out
    for factor_id in FACTOR_IDS:
        assert factor_id in out


def test_factors_against_a_real_catalogue_shows_derived_levels(capsys):
    assert main(["factors", CATALOGUE]) == 0
    out = capsys.readouterr().out
    assert "catalogue.size" in out and "full" in out


# --------------------------------------------------------------------------------------
# Dry run: the guardrail that must work before anything is spent
# --------------------------------------------------------------------------------------


def test_dry_run_reports_the_call_count_and_spends_nothing(capsys):
    assert main(["sweep", CATALOGUE, SUITE, "--factors", "all", "--dry-run", "--no-cache"]) == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert "nothing was sent and nothing was spent" in out
    assert "MODEL CALLS NEEDED" in out
    assert "est. prompt tokens" in out


def test_dry_run_lists_the_arms_including_the_inert_ones(capsys):
    assert (
        main(["sweep", CATALOGUE, SUITE, "--factors", "naming.scheme", "--dry-run", "--no-cache"])
        == 0
    )
    out = capsys.readouterr().out
    assert "control" in out
    assert "(inert, skipped)" in out


def test_dry_run_writes_no_results(tmp_path, capsys):
    out_dir = tmp_path / "results"
    assert main(["sweep", CATALOGUE, SUITE, "--dry-run", "--no-cache", "--out", str(out_dir)]) == 0
    capsys.readouterr()
    assert not out_dir.exists()


# --------------------------------------------------------------------------------------
# A real sweep
# --------------------------------------------------------------------------------------


def test_a_mock_sweep_writes_the_full_run_directory(tmp_path, capsys):
    code = main(
        [
            "sweep",
            CATALOGUE,
            SUITE,
            "--factors",
            "naming.synonyms",
            "--repeats",
            "2",
            "--bootstrap",
            "200",
            "--no-cache",
            "--out",
            str(tmp_path),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "naming.synonyms" in out and "control" in out

    runs = list(tmp_path.iterdir())
    assert len(runs) == 1
    for name in (
        "manifest.json",
        "interventions.json",
        "trials.jsonl",
        "outcomes.jsonl",
        "report.json",
        "report.md",
    ):
        assert (runs[0] / name).is_file(), f"missing {name}"


def test_max_calls_truncates_and_says_so(tmp_path, capsys):
    code = main(
        [
            "sweep",
            CATALOGUE,
            SUITE,
            "--factors",
            "naming.synonyms",
            "--repeats",
            "2",
            "--bootstrap",
            "100",
            "--no-cache",
            "--max-calls",
            "8",
            "--out",
            str(tmp_path),
        ]
    )
    assert code == 0
    assert "RUN TRUNCATED" in capsys.readouterr().out


def test_the_cassette_demo_runs_offline(tmp_path, capsys):
    """No key, no network, and the numbers come from the recorded file."""
    code = main(
        [
            "sweep",
            CATALOGUE,
            SUITE,
            "--factors",
            "naming.synonyms,description.negative",
            "--provider",
            "cassette",
            "--cassette",
            CASSETTE,
            "--repeats",
            "3",
            "--seed",
            "7",
            "--bootstrap",
            "500",
            "--out",
            str(tmp_path),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "replayed from cassette" in out
    assert "live model calls" not in out


def test_report_and_confusion_read_a_finished_run(tmp_path, capsys):
    main(
        [
            "sweep",
            CATALOGUE,
            SUITE,
            "--factors",
            "naming.synonyms",
            "--repeats",
            "2",
            "--bootstrap",
            "100",
            "--no-cache",
            "--out",
            str(tmp_path),
        ]
    )
    capsys.readouterr()
    run_dir = str(next(tmp_path.iterdir()))

    assert main(["report", run_dir]) == 0
    assert "# toolsweep run" in capsys.readouterr().out

    assert main(["confusion", run_dir]) == 0
    assert "CONFUSION MATRIX" in capsys.readouterr().out


def test_report_json_is_valid_json_with_intervals(tmp_path, capsys):
    main(
        [
            "sweep",
            CATALOGUE,
            SUITE,
            "--factors",
            "naming.synonyms",
            "--repeats",
            "2",
            "--bootstrap",
            "100",
            "--no-cache",
            "--out",
            str(tmp_path),
        ]
    )
    capsys.readouterr()
    payload = json.loads((next(tmp_path.iterdir()) / "report.json").read_text())
    effects = [a["effect"] for a in payload["arms"] if a["effect"]]
    assert effects and all("ci_low" in e for e in effects)


# --------------------------------------------------------------------------------------
# Errors are messages and exit codes, not tracebacks
# --------------------------------------------------------------------------------------


def test_an_unknown_factor_exits_one_with_a_message(capsys):
    assert main(["sweep", CATALOGUE, SUITE, "--factors", "naming.vibes", "--dry-run"]) == 1
    assert "unknown factor" in capsys.readouterr().err


def test_the_control_level_cannot_be_requested_as_a_treatment(capsys):
    code = main(
        ["sweep", CATALOGUE, SUITE, "--factors", "naming.synonyms=as_authored", "--dry-run"]
    )
    assert code == 1
    assert "control level" in capsys.readouterr().err


def test_a_cassette_provider_without_a_cassette_exits_one(capsys):
    assert main(["sweep", CATALOGUE, SUITE, "--provider", "cassette", "--dry-run"]) == 1
    assert "requires --cassette" in capsys.readouterr().err


def test_openai_provider_without_a_base_url_exits_one(capsys):
    assert main(["sweep", CATALOGUE, SUITE, "--provider", "openai-compatible", "--dry-run"]) == 1
    assert "requires --base-url" in capsys.readouterr().err


def test_a_suite_that_does_not_match_the_catalogue_exits_one(tmp_path, capsys):
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"id": "a", "prompt": "p", "expected_tool": "delete_the_database"}\n')
    assert main(["sweep", CATALOGUE, str(bad), "--dry-run"]) == 1
    assert "not in the catalogue" in capsys.readouterr().err


def test_report_on_a_missing_run_exits_one(tmp_path, capsys):
    assert main(["report", str(tmp_path / "nope")]) == 1
    assert "no report.md" in capsys.readouterr().err


def test_version_is_printed(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "toolsweep" in capsys.readouterr().out


def test_the_api_key_is_read_from_the_environment_not_the_command_line(monkeypatch):
    """A key on argv lands in shell history and in `ps`. It is an env var only."""
    import argparse

    from toolsweep.cli import _build_provider
    from toolsweep.suite import parse

    monkeypatch.setenv("MY_TEST_KEY", "sk-not-a-real-key")
    args = argparse.Namespace(
        provider="openai-compatible",
        base_url="http://localhost:11434/v1",
        model="qwen3:8b",
        api_key_env="MY_TEST_KEY",
        temperature=0.0,
        seed=7,
        cassette=None,
        confusion_rate=None,
    )
    provider = _build_provider(args, parse('{"id":"a","prompt":"p","expected_tool":"t"}'))
    assert provider.api_key == "sk-not-a-real-key"  # type: ignore[attr-defined]
