# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-09-02

First release. A controlled, factorial sweep over tool-schema variables, with a mandatory
control arm and confidence intervals on every reported effect.

### Added

- **Eight schema factors**, each a pure, idempotent `Catalogue -> Catalogue` transform:
  `naming.scheme`, `naming.synonyms`, `description.length`, `description.negative`,
  `enum.wording`, `schema.nesting`, `params.required`, `catalogue.size`.
- **Four protocol adapters**, in and out: MCP `tools/list`, OpenAI tools, Anthropic tools,
  raw JSON Schema. Format is detected, or refused rather than guessed.
- **Rename-map resolution** for expected labels, argument paths and enum values, so a
  naming or nesting experiment scores what the model actually saw. Guarded by
  `tests/test_rename_map.py`.
- **Statistics**: paired-by-item bootstrap CI, paired permutation p-values, Holm correction
  across the family, and a reported MDE. An `Effect` cannot be constructed without its
  interval.
- **Three reported states**, kept distinct: a measured effect, an *inert* level that
  produced a catalogue identical to the control, and a factor that is *not measurable* on
  this catalogue at all.
- **Providers**: a deterministic seeded mock with one planted confusion effect, a cassette
  replayer that refuses to load a fixture without a `_provenance` label, and any
  OpenAI-compatible `/v1/chat/completions` endpoint.
- **Cost controls**: `--dry-run` prints the exact call count and an estimated token count
  before spending anything, `--max-calls` is a hard stop, and a content-addressed on-disk
  cache keyed including `repeat_index`.
- **CXS v0.1 output** — `manifest.json`, `interventions.json`, append-only `trials.jsonl`,
  `outcomes.jsonl`, `report.json`, `report.md` — with conformance asserted against the
  vendored schemas on a real run of the demo.
- **Resume and re-score**: a rerun into the same experiment id re-scores existing trials
  without calling anything.
- `examples/crm/`: a fictional 20-tool CRM catalogue with two deliberate near-synonym
  clusters, a 40-item suite, and a synthetic cassette.

### Not included, deliberately

- **Automatic rewrite suggestions.** See the README on DSPy PRs #8928 and #9223.
- Interaction effects between factors, `tool.order` / `param.order`, tool retrieval
  systems, and multi-turn tool use. All tracked as issues rather than shipped as stubs.

[Unreleased]: https://github.com/jimmyjames177414/toolsweep/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/jimmyjames177414/toolsweep/releases/tag/v0.1.0
