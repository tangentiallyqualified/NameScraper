# Deterministic Quality Harness Design

## Goal

Make the repository audit and its documentation useful without any LLM by
turning source code, explicit policy, and test evidence into deterministic
machine-readable artifacts and generated views. Use that foundation to stop
new structural debt before undertaking targeted legacy remediation.

## Decisions

- The audit is a compiler, not an assistant: source and policy are inputs;
  JSON, SARIF, Markdown, and CI annotations are outputs.
- Generated output must be byte-identical for identical audit inputs.
- Provenance uses a SHA-256 digest of audit inputs, not `HEAD`, wall-clock
  timestamps, or an LLM-generated summary.
- Human judgment belongs in small machine-readable policy files. Rendered
  review tables are generated and disposable.
- Existing debt is handled with ratchets. Legacy violations may remain, but
  new or enlarged violations fail CI.
- Current repository patterns are migration evidence, not the desired style.
  The target style is declared explicitly by formatter, lint, typing, and
  architecture configuration.
- Implementation is split into three independently useful plans.

## Plan Boundaries

### Plan 1: Deterministic audit generation and CI verification

Replace self-referential commit/timestamp provenance with an input digest,
make repeated generation idempotent, expose a non-mutating verification mode,
rename the LLM-oriented index as a neutral code index, and add PR/manual CI
entry points. This plan does not introduce new quality failures.

### Plan 2: Quality ratchets

Add formatting, curated lint rules, boundary-focused typing, changed-code
coverage, complexity/file-size ratchets, SARIF, and machine-readable finding
decisions. Existing violations become an explicit baseline and cannot grow.

### Plan 3: Architectural debt ratchets and remediation

First make cycle membership and dependency directions enforceable. Then remove
the three-module settings cycle and investigate the nineteen-module
engine/application strongly connected component using characterization tests
and dependency inversion. Complexity hotspots are split only when their
responsibilities and behavioral seams are understood.

## Deterministic Audit Architecture

The committed source of truth is configuration plus a compact baseline:

```text
Python/source files + audit policy + test metadata
                         |
                         v
              normalized .audit/*.json
                         |
              +----------+----------+
              |                     |
              v                     v
        docs/audit/*            audit.sarif
        generated views         CI annotations
```

`input_digest` hashes sorted repository-relative paths and file bytes for every
audit input. Generated outputs are excluded so committing them does not change
their own provenance. Coverage records carry the digest of the source they
measured; commit-age-based coverage freshness is removed from committed output.
Legacy commit-only coverage metadata remains readable during migration but is
considered unverifiable.

`audit --verify` snapshots generated files, performs a full generation, compares
the resulting bytes, restores the original files even on failure, and exits
nonzero with a sorted changed-file list when regeneration is required. The
ignored `.audit/` stage cache may be refreshed because it is not a committed
document artifact.

## Generated Documentation

`docs/audit/code-index/` replaces `docs/audit/llm/`. Its descriptions come only
from module and public-symbol docstrings. Missing descriptions render as
`(no docstring)`; the generator never invents prose.

All generated views use fixed templates, stable ordering, repository-relative
paths, and the input digest. No generated file contains the current time.
The baseline retains exactly one `previous_baseline` snapshot. When the input
digest changes, the former current snapshot rotates into that field; when the
digest is unchanged, it does not rotate. `CHANGES.md` always compares current
metrics with that stable previous snapshot, so a second generation is
byte-identical rather than changing the comparison to “current versus current.”

Curated historical review documents may remain as records, but they are not a
required stage of audit generation. In Plan 2, active exceptions move to a
machine-readable decisions file and the live review view is rendered from it.

## CI Behavior

Pull requests run audit verification after installing the development
dependencies. A `workflow_dispatch` entry runs the update path and uploads the
generated patch/artifacts for any developer to apply. It does not push to fork
branches or require write credentials.

The existing fast-test job remains unchanged in Plan 1. Later plans add quality
gates only after ratchet baselines exist, preventing a repository-wide flag day.

## Error Handling

- Snapshot restoration runs in `finally`, including analyzer and renderer
  failures.
- Analyzer failures keep their existing degraded-evidence behavior, but
  verification itself returns nonzero when the full pipeline returns nonzero.
- Missing generated files count as drift.
- Newly generated extra files count as drift and are removed during restore.
- Text is UTF-8 with LF line endings and JSON keys are sorted.

## Testing

Synthetic repositories under `tmp_path` prove digest stability, input-change
sensitivity, output restoration, idempotent change history, and neutral code
index paths. Workflow tests parse the YAML as text and assert the supported
events and exact audit commands without contacting GitHub.

Each implementation task follows red-green-refactor. The completed branch runs
the audit tests, the full test suite, a fresh audit update, and a subsequent
non-mutating verification pass.
