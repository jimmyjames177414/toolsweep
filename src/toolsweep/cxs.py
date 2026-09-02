"""Context Experiment Interchange Spec (CXS) v0.1 output.

CXS is a **file format**, not a library. toolsweep imports nothing from any sibling
project; interop is the ability to read and write these files, and it is only a claim
because ``tests/test_cxs_conformance.py`` validates a real run of the demo against the
vendored schemas in ``schemas/``.

On-disk layout, identical across the family::

    results/<experiment_id>/
      manifest.json          RunManifest
      interventions.json     [Intervention]
      trials.jsonl           one Trial per line, append-only, raw
      outcomes.jsonl         one Outcome per line
      report.json            aggregated + statistics
      report.md              human-readable

``trials.jsonl`` is append-only and never rewritten, so a crashed run resumes and the raw
data survives for re-analysis with a different scorer. That is the single most important
reproducibility property in the spec, and the reason ``Outcome`` is a separate record from
``Trial``: re-scoring costs nothing and calls no model.
"""

from __future__ import annotations

import json
import os
import platform
import random
import sys
import time
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CXS_VERSION = "0.1"

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_experiment_id(rng: random.Random | None = None) -> str:
    """A ULID-shaped identifier: 48-bit timestamp then 80 bits of randomness.

    Sortable by creation time, stdlib only. The spec's examples are ULIDs; the schema only
    requires a string.
    """
    source = rng or random.Random()
    millis = int(time.time() * 1000)
    return _encode(millis, 10) + _encode(source.getrandbits(80), 16)


def _encode(value: int, length: int) -> str:
    out = []
    for _ in range(length):
        out.append(_CROCKFORD[value & 0x1F])
        value >>= 5
    return "".join(reversed(out))


@dataclass(frozen=True)
class RunPaths:
    """Where one run's files live."""

    root: Path

    @property
    def manifest(self) -> Path:
        return self.root / "manifest.json"

    @property
    def interventions(self) -> Path:
        return self.root / "interventions.json"

    @property
    def trials(self) -> Path:
        return self.root / "trials.jsonl"

    @property
    def outcomes(self) -> Path:
        return self.root / "outcomes.jsonl"

    @property
    def report_json(self) -> Path:
        return self.root / "report.json"

    @property
    def report_md(self) -> Path:
        return self.root / "report.md"

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)


def environment() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "platform": sys.platform,
        "machine": platform.machine(),
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class JsonlWriter:
    """Append-only JSONL. Flushed per record so a crash keeps everything already written."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = path.open("a", encoding="utf-8")

    def write(self, record: Mapping[str, Any]) -> None:
        self._handle.write(json.dumps(record, sort_keys=True) + "\n")
        self._handle.flush()
        os.fsync(self._handle.fileno())

    def close(self) -> None:
        self._handle.close()

    def __enter__(self) -> JsonlWriter:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    if not path.is_file():
        return
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                record = json.loads(stripped)
                if isinstance(record, dict):
                    yield record


def intervention_record(
    *,
    intervention_id: str,
    kind: str,
    factor_id: str,
    level: str,
    description: str,
    implementation: str,
) -> dict[str, Any]:
    """One CXS ``Intervention``.

    The control arm is ``kind: "noop"`` and is mandatory in any experiment reporting an
    effect. It is written first, so a reader of ``interventions.json`` sees arm zero
    before anything it is compared against.
    """
    return {
        "id": intervention_id,
        "kind": kind,
        "selector": {"type": "tool_schema", "value": factor_id},
        "description": description,
        "deterministic": True,
        "implementation": implementation,
        "level": level,
    }


def determinism_of(
    *, temperature: float | None, identical_across_repeats: bool, repeats: int
) -> str:
    """CXS ``RunManifest.determinism``.

    Only returns ``deterministic`` when temperature is zero **and** identical outputs were
    actually observed across repeats. The spec forbids claiming determinism without having
    observed it, and a single repeat observes nothing.

    ``identical_across_repeats`` must be computed over the *tool call* as well as the
    response text. A provider that returns an empty string alongside a structured call -
    a cassette that stored only the call, for instance - would otherwise look identical on
    every repeat and earn a `deterministic` label it never demonstrated.
    """
    if repeats < 2:
        return "stochastic"
    if temperature == 0.0 and identical_across_repeats:
        return "deterministic"
    return "stochastic"


def manifest_record(
    *,
    experiment_id: str,
    tool_version: str,
    created_at: str,
    models: Sequence[Mapping[str, Any]],
    interventions: Sequence[Mapping[str, Any]],
    dataset: Mapping[str, Any],
    scorer: str,
    repeats: int,
    seed: int,
    determinism: str,
    cache: Mapping[str, int],
    totals: Mapping[str, int],
    notes: str = "",
) -> dict[str, Any]:
    return {
        "cxs_version": CXS_VERSION,
        "experiment_id": experiment_id,
        "tool": {"name": "toolsweep", "version": tool_version},
        "created_at": created_at,
        "models": [dict(m) for m in models],
        "interventions": [dict(i) for i in interventions],
        "dataset": dict(dataset),
        "scorer": scorer,
        "repeats": repeats,
        "seed": seed,
        "determinism": determinism,
        "cache": dict(cache),
        "totals": dict(totals),
        "environment": environment(),
        "notes": notes,
    }
