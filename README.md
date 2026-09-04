<div align="center">

<img src="https://raw.githubusercontent.com/jimmyjames177414/toolsweep/main/docs/banner.jpg" alt="toolsweep" width="100%">

# toolsweep

**Varies one decision in your tool schema at a time: the naming, the enum wording, the nesting depth, how many tools you expose. Tells you which decision moved your tool-selection accuracy, with a confidence interval and a control arm.**

[![CI](https://github.com/jimmyjames177414/toolsweep/actions/workflows/ci.yml/badge.svg)](https://github.com/jimmyjames177414/toolsweep/actions/workflows/ci.yml)
[![licence](https://img.shields.io/badge/licence-Apache--2.0-green)](LICENSE)
[![python](https://img.shields.io/badge/python-3.10%20%E2%80%93%203.13-blue)](#install)
[![runtime deps](https://img.shields.io/badge/runtime%20deps-0-brightgreen)](#install)

</div>

---

You expose `get_customer`, `find_customer`, `search_customer` and `lookup_customer`. All four
are valid JSON Schema. Your linter passes, your MCP inspector passes, and the model still picks
the wrong one. Something in that catalogue is costing you accuracy, and nothing tells you which
decision it was.

The obvious fix, having a model rewrite the descriptions, has already been tried and
withdrawn. DSPy added `enable_tool_optimization` to GEPA in
[PR #8928](https://github.com/stanfordnlp/dspy/pull/8928) (merged 2025-12-05) and removed it
again in [PR #9223](https://github.com/stanfordnlp/dspy/pull/9223) (merged 2026-02-02). The
contributor's own controlled experiment: baseline 23-28%, vanilla GEPA 35-39%, tool
optimisation 21-32%. Automatic rewriting *lost* to leaving the schema alone.

So toolsweep rewrites nothing. It changes one decision, re-runs a fixed task suite, and reports
what that decision was worth. Including, loudly, when the answer is nothing.

```console
$ git clone -q https://github.com/jimmyjames177414/toolsweep && cd toolsweep
$ uvx --from git+https://github.com/jimmyjames177414/toolsweep toolsweep sweep \
      examples/crm/catalogue.json examples/crm/suite.jsonl \
      --factors all --provider mock --repeats 5 --seed 7

FACTOR                    level                 accuracy    Δ vs control              95% CI   p(Holm)
------------------------------------------------------------------------------------------------------
control                   as-authored              72.5%               -                   -         -
naming.scheme             noun_verb                72.0%          -0.5pp        [-7.5, +6.5]     1.000
naming.scheme             terse                    49.0%         -23.5pp      [-35.0, -12.5]     0.004
naming.scheme             verbose                  71.5%          -1.0pp        [-8.5, +6.5]     1.000
naming.synonyms           distinct_verbs           92.5%         +20.0pp       [+8.5, +31.0]     0.013
description.length        terse                    74.5%          +2.0pp        [+0.0, +5.0]     1.000
description.length        verbose                  72.5%          +0.0pp        [+0.0, +0.0]     1.000
description.negative      with                     70.0%          -2.5pp        [-7.5, +0.0]     1.000
enum.wording              alternate_wording        72.5%          +0.0pp        [+0.0, +0.0]     1.000
schema.nesting            nested                   72.5%          +0.0pp        [+0.0, +0.0]     1.000
params.required           all_required             72.5%          +0.0pp        [+0.0, +0.0]     1.000
params.required           minimal_required         72.5%          +0.0pp        [+0.0, +0.0]     1.000
catalogue.size            n=14                     73.0%          +0.5pp        [-5.0, +6.5]     1.000
catalogue.size            n=17                     76.0%          +3.5pp        [-1.5, +9.0]     1.000

TOP CONFUSIONS (control arm)
  lookup_customer         → get_customer              4.0%
  find_invoice            → update_invoice            2.5%
  get_customer            → find_customer             2.5%
  list_invoices           → find_invoice              2.5%
  update_invoice          → create_invoice            2.5%

INERT ON THIS CATALOGUE (not run, no calls spent)
  naming.scheme=verb_noun: produced a catalogue identical to the control
  schema.nesting=flat: produced a catalogue identical to the control

40 items · 5 repeats · 2,800 trials (2,800 live model calls) · MDE ≤16.2pp (worst arm) · stochastic
```

> ### Read this before you read that table
>
> **Those numbers come from a mock, not a model.** `--provider mock` is a deterministic
> lexical tool-picker that ships with toolsweep. It has exactly one deliberate flaw: it
> confuses tools whose names differ only by a synonym of the same verb. Nothing in that
> table says anything about how any real language model behaves.
>
> What it does demonstrate is that toolsweep works. The one effect we planted is the one it
> found (`naming.synonyms`, +20.0pp, interval excluding zero). Four factors the mock is
> provably blind to (enum wording, nesting, and both `params.required` levels) come back
> exactly null with intervals, rather than being quietly reported as findings. A tool that
> finds an effect everywhere is as useless as one that finds it nowhere; the null rows are
> the point.
>
> `naming.scheme=terse` moves too. That is real behaviour of *this mock*: abbreviating
> `get_customer` to `getcust` removes the lexical overlap it matches on. It is not a claim
> about anything else.
>
> To measure your own catalogue, point `--provider openai-compatible` at a real endpoint.

<div align="center">
<img src="https://raw.githubusercontent.com/jimmyjames177414/toolsweep/main/docs/demo.png" alt="toolsweep running the example CRM sweep" width="100%">
</div>

Reproduce it with no API key and no network, from the recorded cassette:

```console
$ uvx --from git+https://github.com/jimmyjames177414/toolsweep toolsweep sweep \
      examples/crm/catalogue.json examples/crm/suite.jsonl \
      --factors naming.synonyms,description.negative \
      --provider cassette --cassette examples/crm/cassette.json --repeats 3 --seed 7

FACTOR                    level                 accuracy    Δ vs control              95% CI   p(Holm)
------------------------------------------------------------------------------------------------------
control                   as-authored              70.8%               -                   -         -
naming.synonyms           distinct_verbs           92.5%         +21.7pp       [+9.2, +34.2]     0.004
description.negative      with                     68.3%          -2.5pp        [-7.5, +0.0]     1.000

TOP CONFUSIONS (control arm)
  find_customer           → get_customer              3.3%
  get_customer            → search_customer           3.3%
  find_invoice            → update_invoice            2.5%
  lookup_customer         → get_customer              2.5%
  search_customer         → lookup_customer           2.5%

40 items · 3 repeats · 360 trials (360 replayed from cassette) · MDE ≤18.2pp (worst arm) · stochastic
```

That cassette is labelled `_provenance: synthetic` in the file itself, because it was
generated by the mock rather than recorded from a model. toolsweep refuses to load a
cassette that does not say which it is.

## Install

Nothing is published to PyPI. Run it straight from the repository:

```bash
uvx --from git+https://github.com/jimmyjames177414/toolsweep toolsweep --help
```

Or put it on your `PATH`, which is what the rest of this README assumes when it writes a bare
`toolsweep`:

```bash
uv tool install git+https://github.com/jimmyjames177414/toolsweep
```

The example catalogue and suite live in the repository rather than the wheel, so clone it if
you want to run the demo above.

Python 3.10+, zero runtime dependencies. The OpenAI-compatible provider is one POST built
on `urllib`, and the statistics are pure Python.

## Pointing it at a real model

Any OpenAI-compatible `/v1/chat/completions` endpoint works: Ollama, vLLM, LM Studio,
llama.cpp, OpenRouter, Together, Groq, DeepSeek, OpenAI. Provider choice is a URL, never a
code change, and a contributor with Ollama and no credit card can run everything.

```bash
export TOOLSWEEP_API_KEY=...      # omit entirely for a local endpoint

# Always cost it first. Nothing is sent by a dry run.
toolsweep sweep tools.json suite.jsonl --factors all --dry-run \
    --provider openai-compatible --base-url http://localhost:11434/v1 --model qwen3:8b

toolsweep sweep tools.json suite.jsonl \
    --factors naming.synonyms,description.negative,catalogue.size \
    --provider openai-compatible --base-url http://localhost:11434/v1 --model qwen3:8b \
    --repeats 5 --max-calls 5000 --out results/
```

`--dry-run` prints the exact number of model calls before you spend anything, `--max-calls`
is a hard stop, and responses are cached on disk so a re-run costs nothing.

Your catalogue can be MCP `tools/list`, OpenAI tools, Anthropic tools, or raw JSON Schema.
The format is detected, and refused rather than guessed if it is ambiguous. Your suite is
JSONL:

```json
{"id": "crm.001", "prompt": "Pull the full record for customer id CUS-1041.",
 "expected_tool": "get_customer", "expected_args": {"customer_id": "CUS-1041"}}
```

## Which decisions it varies

Eight factors, each a pure, deterministic function `Catalogue -> Catalogue`. Run
`toolsweep factors` to see the levels for your own catalogue.

| Factor | What it varies |
|---|---|
| `naming.scheme` | `verb_noun` / `noun_verb` / `terse` / `verbose` |
| `naming.synonyms` | collapses near-synonym names (`get`/`find`/`search`/`lookup`) onto distinct verbs |
| `description.length` | first sentence only / as-authored / plus a generated parameter narrative |
| `description.negative` | with vs without a "when NOT to use this" clause |
| `enum.wording` | authored wire codes vs their human phrasing |
| `schema.nesting` | flat vs nested argument objects |
| `params.required` | every parameter required vs only the genuinely essential ones |
| `catalogue.size` | how many tools are exposed at once (never drops a tool your suite expects) |

## Three answers, and only one of them is a result

These are reported separately, because collapsing them would be dishonest:

- **an effect**: measured, with an interval;
- **inert**: this level produced a catalogue byte-identical to the control, so no calls
  were spent and nothing was measured;
- **not measurable here**: the factor has no level that differs on your catalogue at all
  (`catalogue.size` when your suite expects every tool you expose).

Only the first is a result. "We measured no effect" and "there was nothing to measure" are
different sentences.

## Rules every number here obeys

They are not optional:

1. A control arm, always. Effect is `score(arm) − score(control)`, never `score(arm)`.
   Arm zero is built before any factor is read and cannot be switched off.
2. An interval, always. Percentile bootstrap over *items*, 10 000 resamples. An `Effect`
   cannot even be constructed without its CI: the fields have no defaults, so skipping the
   bootstrap is a `TypeError`, not a plausible-looking number.
3. Paired by item. Arm and control run the same items; the paired difference is what gets
   resampled.
4. N beside every number. `n_items` and `repeats`, on every row.
5. An MDE, so a null result is interpretable. Below it, this run could not have detected an
   effect either way, which is not the same as there being none.
6. Holm-corrected p-values alongside the raw ones, labelled.
7. Never a rounded-away CI. `+20.0pp [+8.5, +31.0]`, not `+20.0pp`.

Statistical approach follows (and does not claim) Miller, *Adding Error Bars to Evals*,
[arXiv:2411.00640](https://arxiv.org/abs/2411.00640).

Runs are written as [CXS v0.1](schemas/): `manifest.json`, `interventions.json`, an
append-only `trials.jsonl`, `outcomes.jsonl`, and both reports. Because outcomes are stored
separately from trials, a finished run can be re-scored without calling anything, and a
crashed run resumes.

## Two of the three things you probably want are done better elsewhere

Read this before you decide whether you want toolsweep.

| Project | What it does |
|---|---|
| **[mcpgrade](https://github.com/TengByte/mcpgrade)** | Scores your catalogue *as authored*: synthesises tasks, shows a model your real tools blind, measures tool selection, argument validity, refusal accuracy and confusion pairs. 3-round calibration, `envFingerprint`, a CI action, a 36-server leaderboard, ~2,500 npm downloads a month. |
| **[GEPA MCP adapter](https://github.com/gepa-ai/gepa/tree/main/src/gepa/adapters/mcp_adapter)** | Evolves your `tool_description` against your metric with real rollouts. |
| **BFCL / Gorilla, τ-bench, ToolBench, API-Bank, MCP-Universe** | Benchmark *models* on a fixed corpus. BFCL V4 varies serialisation format only, over its own corpus, to rank models. |
| **MCP inspectors, linters, `mcp-scan`** | Validity, protocol conformance, security. Not usability. |

> To score your catalogue as-authored, use mcpgrade. To evolve your descriptions, use GEPA.
> Use toolsweep to find out which schema decision is costing you accuracy.

What is left, and all toolsweep claims, is the **controlled multi-factor sweep**: schema
decisions treated as independent experimental factors, varied against a fixed suite, with
the accuracy change attributed to a specific variable, cross-protocol, with a control arm
and intervals. mcpgrade tells you that you have a problem; toolsweep tells you which
decision caused it.

Measuring tool-selection accuracy is not new. Finding tool confusion is not new. Testing
your own schema is not new. Optimising tool descriptions is not new. The
`get_customer`/`search_customer` example is not new. See [NOVELTY.md](NOVELTY.md) for the
full audit, including the claims this project may not make.

### Why there are no rewrite suggestions

toolsweep will never hand you a rewritten description. That is the DSPy result at the top of
this file: automatic tool-description rewriting *lost* to not doing it at all, in the
contributor's own controlled experiment, and the feature was removed.

So a tool that confidently rewrites your schema is selling something it cannot back. A
diagnostic that tells you *which variable matters* and leaves the rewrite to you is the
honest shape for this problem. If you do want an optimiser, use GEPA. It is better at it
than anything we would build.

## What it cannot tell you

- Results do not transfer. They are specific to one model, one catalogue and one suite.
  Change any of the three and you must re-run. toolsweep does not imply otherwise anywhere.
- The suite is the measurement instrument. A bad suite produces confident wrong answers, and
  nothing downstream can rescue it. Ours is 40 items over 14 of 20 tools; that is small.
- Single-factor effects only. Interactions between factors are not measured. Two changes that
  each look harmless alone may not be.
- Renaming changes more than the name. It changes token count, position, and how much
  information the name carries. Measured on the shipped example: with the mock's confusion
  planted at *zero*, `naming.synonyms` still shows **+5.0pp [−5.0, +15.0]**, purely because
  `get_customer_by_email` carries a discriminating token that `lookup_customer` does not.
  toolsweep cannot separate that from the confusion it removed. It does correctly decline to
  call it an effect (the interval spans zero), but the confound is real and unremovable.
- 40 items is underpowered for small effects. The demo run's MDE is 16.2pp. Anything smaller
  than that was not detectable at that N, whatever the table says.
- The mock's metrics are degenerate by construction. It never hallucinates and never declines
  (both rates default to 0.0), and it derives arguments from the suite, so hallucination rate,
  no-call rate, argument validity and argument match carry no information in a mock run. They
  are measured properly against a real provider.
- Name analysis is English-centric. The verb classes, abbreviations and pluralisation rules in
  `factors/_text.py` are small hand-written tables. A catalogue named in another language, or
  with unusual conventions, will parse poorly and the naming factors will quietly abstain
  rather than mangle names. But they will also measure less.
- No multi-turn. One prompt, one tool call. Real agents loop.

## Not built yet

Genuinely absent rather than stubbed, and tracked as issues:

- Interaction effects between factors. The current sweep is one-factor-at-a-time.
- `tool.order` and `param.order` as factors. Cheap and planned; the only wrinkle is that
  every level has to be idempotent, so `reverse` is not allowed (applying it twice undoes it).
- Tool *retrieval* systems: catalogues assembled per query rather than fixed.
- Multi-turn tool use.
- A shared public suite so results are comparable between catalogues.

## Contributing

The flagship first issue is **adding a factor**: one file in `src/toolsweep/factors/`, one
line in the registry, and the contract tests in `tests/test_factors.py` pick it up
automatically and check purity, idempotency, adapter round-tripping and schema validity for
free. Adding an adapter, or a catalogue + suite to `examples/`, are the other two good
starting points. See [CONTRIBUTING.md](CONTRIBUTING.md).

```bash
git clone https://github.com/jimmyjames177414/toolsweep && cd toolsweep
uv venv && uv pip install -e ".[dev]"
uv run pytest -m "not live"     # 272 tests, no network, no API keys
uv run ruff check . && uv run ruff format --check .
uv run mypy --strict src/
```

The whole suite runs offline with no secrets configured at all. If a test needs a key it is
marked `live` and deselected by default.

---

<div align="center">
<img src="https://raw.githubusercontent.com/jimmyjames177414/toolsweep/main/docs/avatar.png" width="80" alt="jimmyjames177414">

**[@jimmyjames177414](https://github.com/jimmyjames177414)** · Apache-2.0

<sub>One of nine open-source tools for measuring what context and tools
actually do to AI systems:<br>
<a href="https://github.com/jimmyjames177414/stopless">stopless</a> · <a href="https://github.com/jimmyjames177414/stopbench">stopbench</a> · <a href="https://github.com/jimmyjames177414/mincontext">mincontext</a> · <a href="https://github.com/jimmyjames177414/validwhile">validwhile</a> · <a href="https://github.com/jimmyjames177414/errorbars">errorbars</a><br>
<a href="https://github.com/jimmyjames177414/assumptionledger">assumptionledger</a> · <a href="https://github.com/jimmyjames177414/toolsweep"><b>toolsweep</b></a> · <a href="https://github.com/jimmyjames177414/knowwhen">knowwhen</a> · <a href="https://github.com/jimmyjames177414/inconclusive">inconclusive</a></sub>
</div>
