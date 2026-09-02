# Security policy

## Supported versions

toolsweep is pre-1.0. Only the latest released version receives fixes.

## Reporting a vulnerability

Please report privately via GitHub's [Report a
vulnerability](https://github.com/jimmyjames177414/toolsweep/security/advisories/new)
form rather than opening a public issue. A first response should take a few days; this is
a spare-time project, so please allow a little longer than you would for a funded one.

## What toolsweep touches

Worth knowing when you assess the risk of running it:

- **It sends your tool catalogue to whatever endpoint you configure.** That is the entire
  point of the tool, but it means your tool names, descriptions and argument schemas leave
  your machine. Point `--base-url` at a local endpoint if that matters.
- **API keys are read from an environment variable only** (`--api-key-env`, default
  `TOOLSWEEP_API_KEY`). No key is ever accepted on the command line, where it would land in
  shell history and in `ps` output, and no key is written to any run artefact.
- **Run directories contain prompts and model responses in the clear.** `trials.jsonl`
  records exactly what was sent and returned. Treat `results/` as sensitive if your suite
  is.
- **The on-disk cache** (`~/.cache/toolsweep/` by default) holds the same content. Disable
  it with `--no-cache`, or relocate it with `--cache-dir`.
- **toolsweep never executes a tool.** It measures which tool a model *selects* and with
  what arguments. Nothing in your catalogue is invoked, so a catalogue describing
  destructive operations is safe to sweep.
- **Zero runtime dependencies**, so the supply-chain surface of an install is this package
  alone. The `dev` extra pulls in pytest, ruff, mypy and jsonschema.

## Scope

Findings in toolsweep's own code are in scope. Vulnerabilities in a model provider, in an
MCP server you point it at, or in a catalogue you feed it are not.
