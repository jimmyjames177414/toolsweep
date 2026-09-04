# NOVELTY.md: toolsweep

*(Proposed as "ToolFit". Renamed and reshaped by this novelty gate, completed 2026-09-02, before any
code was written. Every claim is sourced.)*

---

## 1. Problem

You expose `get_customer`, `find_customer`, `search_customer` and `lookup_customer`. All four are
valid JSON Schema. Your linter passes. Your MCP inspector passes. And the model still picks the wrong
one 19% of the time.

Schema validity is not schema usability. Nothing tells you which of your schema decisions is the
one costing you accuracy: the name, the enum wording, the nesting depth, the fact that you exposed
40 tools instead of 12.

## 2. Closest existing projects

| Project | URL | Verified | What it does |
|---|---|---|---|
| **mcpgrade** | [TengByte/mcpgrade](https://github.com/TengByte/mcpgrade) | 20★, pushed 2026-08-01, MIT, npm 0.4.0, 2,459 downloads last month | `--eval` synthesises tasks, shows a model your real catalogue blind, measures tool selection, argument validity, refusal accuracy and confusion pairs. 3-round calibration, `envFingerprint`, CI action, 36-server leaderboard |
| **GEPA MCP adapter** | [gepa-ai/gepa](https://github.com/gepa-ai/gepa/tree/main/src/gepa/adapters/mcp_adapter) | parent 6,361★, pushed 2026-09-01 | Evolves `tool_description` against your metric with real rollouts |
| **BFCL / Gorilla** | Berkeley | - | Benchmarks *models* on a fixed corpus; V4 varies serialisation format only |
| **τ-bench, ToolBench, API-Bank, MCP-Universe** | - | - | Benchmark *models*, not your schema |
| **MCP inspectors / linters / `mcp-scan`** | - | - | Validity, protocol conformance, security. Not usability |

Being blunt about mcpgrade: its README's opening line is the original ToolFit thesis sentence, and
`toolfit evaluate` is essentially already built.

## 3. Closest academic work

- Published findings on tool-selection degradation as tool count grows, tool overlap, and retrieval.
  All of them constrain what we may claim as new.
- The most decision-relevant artifact is not a paper but a pair of merged pull requests.
  DSPy PR [#8928](https://github.com/stanfordnlp/dspy/pull/8928) (merged 2025-12-05) added
  `enable_tool_optimization` to GEPA. DSPy PR [#9223](https://github.com/stanfordnlp/dspy/pull/9223)
  (merged 2026-02-02) removed it. The contributor's own controlled experiment:
  baseline 23-28%, vanilla GEPA 35-39%, tool optimization 21-32%. Tool optimisation *lost*.
  Root cause: `ReAct.__init__` bakes tool descriptions into `signature.instructions`, so generic
  optimisers already rewrite them incidentally; tool *names* are unreachable because
  `next_tool_name` is typed `Literal[tuple(tools.keys())]`.

That last finding is a gift. It is public evidence that naive description-rewriting is not the
answer, which is the case for building a diagnostic rather than another optimiser.

## 4. Exact overlap

- Scoring your own catalogue as-authored: already shipped (mcpgrade), with confusion pairs.
- Evolving tool descriptions against a metric: already shipped (GEPA MCP adapter).
- Benchmarking models on tool use: thoroughly occupied (BFCL, τ-bench, ToolBench, MCP-Universe).
- Even the motivating example is public. mcpgrade's calibration found selection misses landing on
  `extract`↔`scrape` and `agent_status`↔`check_crawl_status`.
- The original name and pitch were staked six days before we started.
  `sreshtalluri/toolfit`, created 2026-08-27: *"finds the specific places your MCP server confuses
  models, rewrites the tool descriptions and schemas to fix them, and proves the fix with a before
  and after eval."* README + LICENSE only, 0 stars. `toolfit.pro` is also a live commercial brand.

## 5. Exact differentiation

One thing, stated narrowly because that is all that survives:

**The controlled multi-factor sweep.** Treat schema decisions as *independent experimental factors*:
naming scheme, description wording, enum phrasing, nesting depth, required-vs-optional, tool ordering,
parameter ordering, tool count, functional overlap. Vary them systematically against a fixed task
suite, and attribute the accuracy loss to specific variables, with confidence intervals.

- BFCL V4 does this for serialisation format only, over its own corpus, to rank models.
- mcpgrade measures one catalogue, as-authored. It tells you that you have a problem, not which
  decision caused it.
- GEPA-MCP evolves prose only, never names, enums, nesting, ordering or count.

Nobody answers "which schema variable is costing *me* accuracy." That is the entire project.

It is also the right shape for this portfolio: the same intellectual spine as Stopless and
StopBench, controlled ablation with honest statistics, applied to tool schemas instead of prose.

## 6. Why a developer would choose ours

- mcpgrade told you your catalogue scores 81%. toolsweep tells you it is the four near-synonym names,
  worth 11 points, and that your nesting depth costs nothing.
- You are deciding whether to split one MCP server into two, and want the accuracy cost measured.
- You want the result to be a *finding you can act on*, not a rewritten prompt you must trust.

## 7. What is actually novel

Factorial attribution of tool-selection accuracy to individual schema variables, cross-protocol
(MCP / OpenAI / Anthropic / raw JSON Schema), with intervals and a control arm.

## 8. What is NOT novel

Measuring tool-selection accuracy. Finding tool confusion. Testing your own schema. Optimising tool
descriptions. Tool-use leaderboards. The `get_customer`/`search_customer` example.

## 9. Claims we must not make

| Forbidden | Why false | Source |
|---|---|---|
| "First tool to test your own tool schema" | mcpgrade `--eval` | github.com/TengByte/mcpgrade |
| "First to measure tool confusion" | mcpgrade reports confusion pairs | ibid |
| "First to optimise tool descriptions" | GEPA MCP adapter | gepa-ai/gepa |
| "Rewriting tool descriptions reliably improves accuracy" | DSPy's own experiment showed it *lost* to vanilla GEPA | dspy PR #9223 |
| "MCP tooling only does validation/security" | mcpgrade is an empirical usability tester | ibid |
| Any predicted improvement not measured by a real trial | The brief forbids it and so do we | - |

Banned: "first ever", "revolutionary", "solves tool selection".

## 10. Recommendation

**RENAME AND RESHAPE, then GO small.** Both done before implementation.

- Renamed `toolfit` → `toolsweep`. Verified free on PyPI (404), npm (404), and zero GitHub
  collisions, whereas `toolfit` is staked on GitHub with our exact pitch and is a live commercial
  brand elsewhere.
- Dropped `evaluate` and `optimize` as headline verbs. Both are shipped by better-resourced
  projects. The README must say so by name and point users to them.
- Kept only the factorial sweep, which is unoccupied.

Positioning line for the README: *"To score your catalogue as-authored, use mcpgrade. To evolve your
descriptions, use GEPA. Use toolsweep to find out which schema decision is costing you accuracy."*

Honest sizing: this is a focused measurement tool, not a platform. And the timing is tight.
Independent projects staked this territory within the last five weeks.
