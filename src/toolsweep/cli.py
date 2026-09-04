"""Command line interface.

    toolsweep sweep <catalogue> <suite> [--factors ...] [--provider ...] ...
    toolsweep report <run-dir>
    toolsweep confusion <run-dir>
    toolsweep factors

Built on ``argparse`` so the package keeps zero runtime dependencies.

Two guardrails from the shared foundation are wired in here: ``--dry-run`` prints the
exact number of model calls and an estimated token count before anything is spent, and
``--max-calls`` is a hard stop.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import __version__, cxs, report
from .adapters import FORMATS
from .adapters import load_file as load_catalogue
from .cache import ResponseCache, default_cache_dir
from .catalogue import CatalogueError
from .factors import FACTOR_IDS, SUMMARIES, FactorContext, UnknownFactorError, build
from .providers import (
    CassetteError,
    CassetteProvider,
    MockConfig,
    MockProvider,
    OpenAICompatibleProvider,
    Provider,
    ProviderError,
)
from .runner import SweepConfig, plan, run
from .score import ItemScore, ToolCall, confusion_counts, score_call
from .suite import Suite, SuiteError
from .suite import load_file as load_suite

DEFAULT_OUT = Path("results")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        handler = getattr(args, "handler", None)
        if handler is None:
            parser.print_help()
            return 2
        result: int = handler(args)
        return result
    except (CatalogueError, SuiteError, UnknownFactorError, CassetteError, ProviderError) as exc:
        print(f"toolsweep: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:  # pragma: no cover - interactive only
        print("toolsweep: interrupted", file=sys.stderr)
        return 130


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="toolsweep",
        description=(
            "Vary one tool-schema decision at a time against a fixed task suite and "
            "attribute the accuracy change to that decision, with a control arm and a "
            "confidence interval."
        ),
    )
    parser.add_argument("--version", action="version", version=f"toolsweep {__version__}")
    sub = parser.add_subparsers(dest="command")

    sweep = sub.add_parser("sweep", help="run a factorial sweep")
    sweep.add_argument("catalogue", type=Path, help="tool catalogue JSON")
    sweep.add_argument("suite", type=Path, help="task suite JSONL")
    sweep.add_argument(
        "--factors",
        default="all",
        help=(
            "comma-separated factor ids, 'all', or factor=level for a single arm "
            f"(known: {', '.join(FACTOR_IDS)})"
        ),
    )
    sweep.add_argument("--format", choices=FORMATS, default=None, help="catalogue format")
    sweep.add_argument(
        "--provider", choices=("mock", "cassette", "openai-compatible"), default="mock"
    )
    sweep.add_argument("--model", default="", help="model id for the openai-compatible provider")
    sweep.add_argument("--base-url", default="", help="OpenAI-compatible endpoint base URL")
    sweep.add_argument(
        "--api-key-env",
        default="TOOLSWEEP_API_KEY",
        help="environment variable holding the API key (never passed on the command line)",
    )
    sweep.add_argument("--cassette", type=Path, default=None, help="cassette JSON to replay")
    sweep.add_argument("--repeats", type=int, default=5)
    sweep.add_argument("--seed", type=int, default=7)
    sweep.add_argument("--temperature", type=float, default=0.0)
    sweep.add_argument("--confusion-rate", type=float, default=None, help="mock provider only")
    sweep.add_argument(
        "--bootstrap", type=int, default=10_000, help="bootstrap/permutation resamples"
    )
    sweep.add_argument("--confidence", type=float, default=0.95)
    sweep.add_argument("--out", type=Path, default=DEFAULT_OUT)
    sweep.add_argument("--experiment-id", default=None, help="reuse an id to resume a run")
    sweep.add_argument(
        "--dry-run", action="store_true", help="count calls and tokens, spend nothing"
    )
    sweep.add_argument("--max-calls", type=int, default=None, help="hard stop on model calls")
    sweep.add_argument("--cache-dir", type=Path, default=None)
    sweep.add_argument("--no-cache", action="store_true")
    sweep.add_argument("--notes", default="")
    sweep.set_defaults(handler=_cmd_sweep)

    rep = sub.add_parser("report", help="re-render a finished run")
    rep.add_argument("run_dir", type=Path)
    rep.set_defaults(handler=_cmd_report)

    conf = sub.add_parser("confusion", help="the confusion matrix on its own")
    conf.add_argument("run_dir", type=Path)
    conf.add_argument("--arm", default="control", help="which arm's matrix to show")
    conf.set_defaults(handler=_cmd_confusion)

    fac = sub.add_parser("factors", help="list available factors and their levels")
    fac.add_argument("catalogue", type=Path, nargs="?", default=None)
    fac.add_argument("--format", choices=FORMATS, default=None)
    fac.set_defaults(handler=_cmd_factors)

    return parser


# --------------------------------------------------------------------------------------
# sweep
# --------------------------------------------------------------------------------------


def _cmd_sweep(args: argparse.Namespace) -> int:
    catalogue, fmt = load_catalogue(args.catalogue, args.format)
    suite = load_suite(args.suite)

    provider = _build_provider(args, suite)
    cache = _build_cache(args)

    config = SweepConfig(
        catalogue=catalogue,
        suite=suite,
        factor_specs=tuple(args.factors.split(",")),
        repeats=args.repeats,
        seed=args.seed,
        resamples=args.bootstrap,
        confidence=args.confidence,
        max_calls=args.max_calls,
        notes=args.notes,
        dataset_name=args.suite.name,
        dataset_sha256=_sha256_file(args.suite),
        catalogue_format=fmt,
    )

    if args.dry_run:
        estimate = plan(config, provider, cache)
        print(_render_dry_run(estimate, provider))
        return 0

    result = run(
        config,
        provider,
        cache,
        out_dir=args.out,
        experiment_id=args.experiment_id,
        version=__version__,
    )

    command = "toolsweep " + " ".join(sys.argv[1:])
    assert result.paths is not None
    cxs.write_json(result.paths.report_json, report.report_json(result))
    result.paths.report_md.write_text(
        report.render_markdown(result, command=command), encoding="utf-8"
    )

    print(report.render_table(result))
    print()
    print(f"Run written to {result.paths.root}")
    return 0


def _build_provider(args: argparse.Namespace, suite: Suite) -> Provider:
    if args.provider == "cassette":
        if args.cassette is None:
            raise CassetteError("--provider cassette requires --cassette PATH")
        return CassetteProvider(args.cassette)

    if args.provider == "mock":
        config = MockConfig(seed=args.seed)
        if args.confusion_rate is not None:
            config = MockConfig(seed=args.seed, confusion_rate=args.confusion_rate)
        # The mock fills arguments from the suite so argument metrics are well-formed.
        # It is keyed by prompt, which is the only join key a Request carries.
        expected = {item.prompt: item.expected_args for item in suite.items if item.expected_args}
        return MockProvider(config=config, expected_args=expected)

    if not args.base_url or not args.model:
        raise ProviderError("--provider openai-compatible requires --base-url and --model")
    return OpenAICompatibleProvider(
        base_url=args.base_url,
        model=args.model,
        api_key=os.environ.get(args.api_key_env, ""),
        temperature=args.temperature,
        seed=args.seed,
    )


def _build_cache(args: argparse.Namespace) -> ResponseCache:
    # A cassette *is* a cache. Layering the on-disk cache over it would let a stale entry
    # from an earlier provider answer a request the cassette also holds, and the run's
    # numbers would come from two different places.
    if args.no_cache or args.provider == "cassette":
        return ResponseCache(enabled=False)
    return ResponseCache(args.cache_dir or default_cache_dir())


def _render_dry_run(estimate: Any, provider: Provider) -> str:
    descriptor = provider.descriptor
    lines = [
        "DRY RUN: nothing was sent and nothing was spent.",
        "",
        f"  provider            {descriptor.provider} ({descriptor.model})",
        f"  arms                {estimate.live_arms} live"
        + (f", {estimate.inert_arms} inert (skipped)" if estimate.inert_arms else ""),
        f"  items               {estimate.n_items}",
        f"  repeats             {estimate.repeats}",
        f"  grid                {estimate.grid_size:,} trials",
        f"  already cached      {estimate.cached:,}",
        f"  MODEL CALLS NEEDED  {estimate.calls_needed:,}",
        f"  est. prompt tokens  {estimate.estimated_prompt_tokens:,} (character-based estimate)",
        "",
        "Arms:",
    ]
    for arm in estimate.arms:
        marker = "  (inert, skipped)" if arm.inert else ""
        lines.append(f"  - {arm.id}{marker}")
    return "\n".join(lines)


# --------------------------------------------------------------------------------------
# report / confusion / factors
# --------------------------------------------------------------------------------------


def _cmd_report(args: argparse.Namespace) -> int:
    path = Path(args.run_dir) / "report.md"
    if not path.is_file():
        print(f"toolsweep: no report.md in {args.run_dir}", file=sys.stderr)
        return 1
    print(path.read_text(encoding="utf-8"))
    return 0


def _cmd_confusion(args: argparse.Namespace) -> int:
    """Rebuild the confusion matrix from the raw trials, not from a summary.

    ``trials.jsonl`` is append-only and holds what the model actually returned, so this
    re-scores rather than re-reading a number somebody else computed.
    """
    run_dir = Path(args.run_dir)
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        print(f"toolsweep: no manifest.json in {run_dir}", file=sys.stderr)
        return 1

    report_path = run_dir / "report.json"
    if not report_path.is_file():
        print(f"toolsweep: no report.json in {run_dir}", file=sys.stderr)
        return 1
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    rows = list(payload.get("confusion", []))
    if not rows:
        print("arm 'control': every trial chose the expected tool")
        return 0

    total = int(payload.get("control", {}).get("n_trials", 0)) or sum(int(r["count"]) for r in rows)
    width = max(len(str(r["expected"])) for r in rows) + 2
    got_width = max(len(str(r["got"])) for r in rows) + 2
    print(f"CONFUSION MATRIX: arm 'control' ({total} trials, names in as-authored space)")
    print()
    print(f"  {'expected':<{width}}{'got':<{got_width}}{'count':>7}{'share':>9}")
    for row in rows:
        count = int(row["count"])
        share = count / total * 100 if total else 0.0
        print(f"  {row['expected']:<{width}}{row['got']:<{got_width}}{count:>7}{share:>8.1f}%")
    return 0


def _cmd_factors(args: argparse.Namespace) -> int:
    if args.catalogue is not None:
        catalogue, _ = load_catalogue(args.catalogue, args.format)
    else:
        from .catalogue import Catalogue, Tool

        catalogue = Catalogue(tools=tuple(Tool(name=f"example_tool_{i}") for i in range(10)))

    ctx = FactorContext(catalogue=catalogue)
    levels = {fid: build(fid, ctx).levels for fid in FACTOR_IDS}
    print(report.format_factor_list(SUMMARIES, levels))
    return 0


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = ["ItemScore", "ToolCall", "confusion_counts", "main", "score_call"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
