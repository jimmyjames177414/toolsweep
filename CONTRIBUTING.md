# Contributing to toolsweep

Thanks for looking. This is a small, focused measurement tool, and it intends to stay one.

## Setup

```bash
git clone https://github.com/jimmyjames177414/toolsweep && cd toolsweep
uv venv && uv pip install -e ".[dev]"
```

Everything runs offline. **You never need an API key to contribute**, and CI runs with no
secrets configured at all. Tests that would hit a real endpoint are marked `live` and
deselected by default.

```bash
uv run pytest -m "not live"
uv run ruff check . && uv run ruff format --check .
uv run mypy --strict src/
```

All three must pass. There is nothing else to remember.

## Adding a factor: the best first issue

A factor is one schema decision with two or more *levels*. It lives in one file and is
registered in one place.

1. Write `src/toolsweep/factors/<your_factor>.py`, subclassing `Factor` from `base.py`.
2. Add the class to `FACTOR_CLASSES` in `src/toolsweep/factors/__init__.py`.

That is the whole change. `tests/test_factors.py` enumerates the registry, so your factor
is immediately checked for all three contracts without you writing a line of test setup:

- Purity: `apply` is a pure function of the catalogue. No network, no clock, no global
  state. Anything else the factor depends on is passed to `__init__` via `FactorContext`.
- Idempotency: `apply(level, apply(level, c)) == apply(level, c)`. A level names a
  *destination*, not a step. This is stricter than it sounds. It rules out `reverse` as an
  ordering level, and it is why the naming factors carry "already in this scheme" guards.
- Validity: the result loads and dumps through every adapter, has unique tool names, and
  never produces a name a target protocol would reject.

Please also add a behaviour test for what your factor actually does. The contract tests
prove it is well-behaved, not that it is correct.

### Three things a factor must not do

- Do not lose provenance. Rebuild tools with `dataclasses.replace`, never from scratch.
  `Tool.origin`, `Param.origin_path` and `EnumValue.origin_code` are what let a suite's
  expected label survive your transformation. Drop them and every naming experiment silently
  scores zero while every test still passes. `tests/test_rename_map.py` is the guard.
- Do not drop a tool the suite expects. If your factor removes tools, pin
  `ctx.pinned_tools`, as `catalogue.size` does.
- Do not invent semantics. If the catalogue does not say something, the honest move is for
  the level to be *inert*; toolsweep reports that as "nothing to measure here" rather than
  as a null result. `params.required=minimal_required` works exactly this way.

## Adding an adapter

`src/toolsweep/adapters/<format>.py` needs `FORMAT`, `load(payload)` and
`dump(cat, *, extensions=False)`, plus an entry in `ADAPTERS`. The JSON Schema half is
already shared in `_schema.py`, so you are usually only writing the envelope.

`tests/test_adapters.py` tests every *ordered pair* of formats, so your adapter is checked
against all the existing ones automatically. Two rules:

- `extensions=False` is what the model sees. It must contain no toolsweep bookkeeping.
- Provenance never crosses the wire, in either mode.

## Adding an example

A catalogue plus a suite in `examples/<name>/`. It must be entirely fictional: invented
companies, invented ids, invented emails on `.example` domains. Do not contribute a
catalogue from a real product, yours or anyone else's.

## Evidence and honesty

This is a measurement tool, so the bar for claims is higher than the bar for code.

- No invented numbers. Every number in a README or a docstring must be reproducible by a
  command, or explicitly labelled synthetic.
- Any fixture that looks like a model response must say whether it was recorded or
  generated. The cassette format enforces this: loading fails without `_provenance`.
- Never report an effect without a control arm and an interval. This is enforced by the
  types, and if you find a way around it, that is a bug worth reporting.
- Banned phrasing: "first ever", "the first tool to", "revolutionary", "state of the art"
  without a cited measurement, "solves tool selection".

## Scope

Deliberately out of scope, and likely to be declined:

- Automatic rewrite suggestions. See the README's section on the DSPy result. This is a
  diagnostic on purpose.
- A shared runtime package with sibling projects. Interop is the CXS *file format* only.
- Runtime dependencies. There are currently zero, and that is a feature.

If a planned feature cannot be finished to "tested and honest" quality, it does not ship as
a stub. It goes in the README's "Not built yet" list and becomes an issue. A stub that looks
implemented is worse than an admitted gap.
