# Vendored CXS v0.1 schemas

These are **vendored copies**, not a dependency. The Context Experiment Interchange Spec
is a *file format*: toolsweep does not import any sibling project to speak it, and no
sibling imports toolsweep. A duplicated schema file is cheaper than a version knot across
repositories that would otherwise have to rise and fall together.

| File | Written by toolsweep to |
|---|---|
| `run_manifest.schema.json` | `results/<id>/manifest.json` |
| `intervention.schema.json` | `results/<id>/interventions.json`, and inline in the manifest |
| `trial.schema.json` | `results/<id>/trials.jsonl` (one per line) |
| `outcome.schema.json` | `results/<id>/outcomes.jsonl` (one per line) |
| `model_descriptor.schema.json` | referenced by both of the above |

`tests/test_cxs_conformance.py` validates the output of a real demo run against these
files. Conformance is a claim about files, and toolsweep does not make it without that
test.

## Deliberately not vendored

CXS v0.1 also defines `ContextUnit` and `FailurePredicate`. toolsweep emits neither, so
they are not copied here. Vendoring schemas the tool never writes would pad the repository
and imply an interop surface that does not exist.

## Extensions

`trial.schema.json` and `outcome.schema.json` set `additionalProperties: true`, which the
spec permits. toolsweep uses that to add one field to each `Trial`: `tool_call`, holding
the structured `{name, arguments}` the model produced. Readers that only know CXS v0.1
ignore it; readers that want the parsed call do not have to re-parse `response_text`.
