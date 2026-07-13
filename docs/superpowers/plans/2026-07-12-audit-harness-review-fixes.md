# Audit Harness Review Fixes Implementation Plan

**Goal:** Fix the audit harness trust, confidence, coverage, provenance, staleness, diff-history, parse-integrity, and self-test gaps identified in the post-merge review of `dev/audit-debt2`.

**Architecture:** Preserve the existing staged pipeline, stage signatures, artifact filenames, existing artifact keys, `_diff.compare` return keys, advisory `--check` exit behavior, and product-only graph scope. Add evidence and provenance fields without renaming/removing old fields. Analyzer or coverage uncertainty must be visible and must never render as clean evidence.

**Branch:** `dev/audit-debt3` from merged `origin/main` (`942d726`).

**Validation baseline:** `tests/audit` = 113 passed; harness statement coverage = 94%; fast suite = 1447 passed / 9 skipped before automatic Qt-test discovery.

## Global constraints

- Run Python and pytest only through `.venv\Scripts\python.exe`.
- Tests use synthetic `tmp_path` repositories only.
- Generated files remain UTF-8; CLI stdout remains ASCII-safe.
- Analyzer/coverage failures degrade; inventory/graph failures abort.
- Existing JSON/baseline keys remain available with compatible meanings; additions are allowed.
- Keep `scripts/audit/` independent of `plex_renamer` imports.
- Keep graph/metrics scope product-only; self-awareness is added to `--check` and tests rather than merging harness modules into product maps.
- `--check` remains advisory and always exits 0.
- `--fast` becomes render-only and must not mutate `baseline.json` or `CHANGES.md`.
- Commit each task separately; do not push until requested.

---

## Task 1: Evidence-based dead-code confidence

**Files:**
- Modify `scripts/audit/_inventory.py`
- Modify `scripts/audit/_analyze.py`
- Modify `tests/audit/test_inventory.py`
- Modify `tests/audit/test_analyze.py`

### Implementation

1. Add `imports_symbols` to each test inventory record while keeping `imports_modules` unchanged.
2. Detect direct and aliased `from plex_renamer... import symbol` references. Also resolve simple module-alias attribute references such as `from plex_renamer.gui_qt import _scale; _scale.row_height()`.
3. Add dead-finding evidence fields: `production_references`, `test_references`, and `allowlist_reason`.
4. Preserve `assessment`; expand it to:
   - `entrypoint`
   - `test-referenced`
   - `dynamic-or-unresolved`
   - `referenced`
   - `high-confidence` (zero production/test references and Vulture confidence >= 80)
   - `medium-confidence` (zero references and confidence >= 60)
   - `low-confidence`
5. Keep inventory optional in `_assess_dead_code` for compatibility with direct callers.
6. Preserve allowlist matching and also retain the matched reason.

### Regression tests

- Direct and aliased test-symbol references are inventoried.
- A 60% zero-reference Vulture function is medium, not high.
- High confidence requires the numeric threshold plus zero references.
- Test-referenced, production-referenced, unresolved, and entrypoint tiers are distinct.
- Evidence fields are sorted and allowlist reasons survive.

### Commit

`fix(audit): make dead-code confidence evidence based`

---

## Task 2: Coverage evidence integrity and fresh-run coverage

**Files:**
- Modify `scripts/audit/_coverage.py`
- Modify `tests/audit/test_coverage.py`

### Implementation

1. Normalize sidecar `failed` as strictly as `partial`; malformed values downgrade evidence.
2. Treat failed, partial, unknown-commit, or over-age evidence as stale.
3. Improve `_run_fresh` diagnostics for launch errors, timeout, and nonzero exit with bounded ASCII-safe stderr context.
4. Ensure a failed fresh run cannot silently reuse an older `.coverage` file as fresh evidence.
5. Preserve all existing coverage keys and add `failed` where useful.

### Regression tests

- `_run_fresh` command/cwd/timeout success path.
- Launch, timeout, and nonzero failures.
- `collect_coverage(fresh=True)` success and failure behavior.
- Malformed/failed sidecars are partial-or-stale and never trusted.

### Commit

`fix(audit): harden fresh coverage evidence and failure provenance`

---

## Task 3: Drift-proof fast-test runner

**Files:**
- Modify `scripts/test_fast_runner.py`
- Add `tests/audit/test_fast_runner.py`

### Implementation

1. Replace the hardcoded Qt ignore list with deterministic AST discovery of `test_*.py` files importing `PySide6` or `conftest_qt`.
2. Always ignore `tests/conftest_qt.py` itself.
3. Extract pure command construction and make `main(argv=None, repo_root=None)` injectable.
4. Preserve logging, JUnit summaries, passthrough arguments, coverage data, and sidecar behavior.

### Regression tests

- Discovery catches direct/nested imports and ignores non-Qt tests.
- Deleted filenames cannot remain in a static manifest.
- Coverage, verbose, passthrough, success/failure, logging, and sidecar invocation paths.

### Commit

`refactor(tests): discover Qt exclusions for the fast runner`

---

## Task 4: Staleness self-awareness, fast provenance, and graph integrity

**Files:**
- Modify `scripts/audit/_artifacts.py`
- Modify `scripts/audit/__main__.py`
- Modify `scripts/audit/_graph.py`
- Modify `tests/audit/test_artifacts.py`
- Modify `tests/audit/test_cli.py`
- Modify `tests/audit/test_graph.py`

### Implementation

1. Add a git helper returning committed plus staged/unstaged/untracked relevant files.
2. Make `--check` inspect `plex_renamer`, `scripts/audit`, audit wrappers/config, and audit tests.
3. Count added and removed product modules; do not filter changed paths through the old baseline module set.
4. Report dirty relevant files even when baseline commit equals HEAD, within the existing three-line advisory shape.
5. Set `FAST_STAGES = {"render"}` so `--fast` never runs diff.
6. Raise a path/line-specific hard graph error for `SyntaxError` rather than publishing an empty module.

### Regression tests

- Dirty product and harness files are reported at current HEAD.
- Newly added product modules are counted.
- Irrelevant doc changes do not count as mapped source changes.
- `--fast` leaves baseline and CHANGES byte-for-byte unchanged.
- Syntax errors abort graph/CLI with the source path and line.

### Commit

`fix(audit): close staleness blind spots and reject invalid graphs`

---

## Task 5: Trust-aware metrics and separated human/LLM reports

**Depends on:** Tasks 1-4.

**Files:**
- Modify `scripts/audit/_metrics.py`
- Modify `scripts/audit/_render_human.py`
- Modify `scripts/audit/_render_llm.py`
- Modify `tests/audit/test_metrics.py`
- Modify `tests/audit/test_render_human.py`
- Modify `tests/audit/test_render_llm.py`
- Modify `tests/audit/test_render_extensions.py`

### Implementation

1. Coverage is usable only when available, fresh, non-partial, and non-failed; retain unusable evidence as additive `metrics["coverage"]` provenance.
2. Add statement-weighted `statement_coverage` and `module_avg_coverage`; keep `avg_coverage` as a compatibility alias to the corrected statement-weighted value.
3. Add compatible dead-tier counts per module and headline while retaining `dead_candidates`, `dead_high_confidence`, and legacy aggregate `dead_low_confidence`.
4. Copy analysis tool status into metrics additively.
5. Render an analyzer-status section and tool-scoped unavailable messages. Failed/missing analyzers must never produce clean claims or trustworthy zero values.
6. Split the human dead-code checklist into high, medium, protected/ambiguous, test-referenced, and allowlisted sections with Vulture percentage and reference evidence.
7. Render coverage provenance and a ten-row least-covered table. Stale/partial/failed data displays as ignored, not as percentages.
8. Stamp human and LLM outputs from the metrics artifact commit, with current HEAD only as a legacy fallback.
9. Repeat concise analyzer/coverage incompleteness warnings in every independently consumable LLM output.

### Regression tests

- Weighted versus module-average coverage with unequal modules.
- Stale/partial/failed evidence yields no percentages or low-coverage flags but keeps provenance.
- Least-covered ordering and cap.
- Analyzer failures suppress clean claims and misleading complexity/dead metrics.
- Confidence sections are ordered independently of source path and include evidence.
- LLM outputs use artifact commit and warn on degraded evidence.

### Commit

`feat(audit): render confidence tiers and evidence provenance`

---

## Task 6: Complete audit change history

**Depends on:** Task 5.

**Files:**
- Modify `scripts/audit/_diff.py`
- Modify `tests/audit/test_diff.py`
- Modify `tests/audit/test_docs_ledger.py` only if needed for snapshot fixtures

### Implementation

1. Preserve `_diff.compare` return keys.
2. Add dead-symbol snapshots and confidence counts to baseline module records without removing old fields.
3. Report new, resolved, and confidence-changed dead symbols when both sides have detailed snapshots; remain quiet for legacy baselines without snapshots.
4. Skip coverage movements when either side reports unusable coverage evidence.
5. Snapshot enrolled doc stale/current state additively and report transitions in `_diff.run`.
6. Stamp CHANGES sections from `metrics["commit"]`, not current HEAD.

### Regression tests

- New/resolved/confidence-changed dead findings.
- Legacy baseline compatibility.
- Stale coverage movements suppressed.
- Doc stale/current transitions.
- Metrics artifact commit controls the section header.

### Commit

`feat(audit): track resolved findings and documentation transitions`

---

## Task 7: Final verification and artifact refresh

1. Run targeted tests after every task.
2. Run `.venv\Scripts\python.exe -m pytest tests\audit -q`.
3. Measure harness coverage with a temporary coverage data file; target no regression below 94% and ensure new trust paths are covered.
4. Run `scripts\test-fast.cmd` and `scripts\test-fast.cmd -Coverage`.
5. Run `scripts\audit.cmd`; require exit 0, fresh usable coverage, all enrolled docs current, and no false-clean/degraded sections.
6. Run `scripts\audit.cmd --check` twice in one session.
7. Refresh and commit `docs/audit/**` plus any required doc-ledger stamp updates.

### Commit

`chore(audit): refresh maps after trust and coverage fixes`

