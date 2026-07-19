# Task 7 quality-ratchet repair report

## Status

Complete. The supported quality gate reports no new or enlarged debt after a
stale-only baseline refresh. Generated audit artifacts and the cycle baseline
remain intentionally unstaged.

## Root causes and repairs

- Formatted only the Task 7 Python scope. The 5,698-line Qt workspace test
  could not be edited safely while retaining formatter debt, so four cohesive
  review-action tests were extracted into a strict, formatted 298-line module.
  The remaining formatted legacy module is 5,662 lines, below its old ceiling.
  Collection stayed identical at 104 tests before and after the split.
- Replaced the dynamic `type(...)` scanner fixture with a named metadata
  capability fake. `ScanState` now composes narrow TV metadata/TV operation and
  movie rematch protocols; consumers cast only to the capability they use.
- Extracted episode-metadata lookup and audit cycle-edge rendering into focused
  modules. This reduced the reported audit CC/LOC debt without changing output.
- Added a real retained-movie-source invariant so the movie scanner protocol's
  `explicit_files` capability is exercised by production behavior.
- Made coverage mode run the complete test suite, including Qt, while ordinary
  fast runs retain their existing Qt exclusions. Scope validation records the
  actual complete coverage suite instead of relying on an import workaround or
  coverage suppression.

## Evidence

- Pre-repair quality gate: 65 new/enlarged entries (52 new, 13 enlarged) and 25
  stale entries.
- Final pre-refresh gate: 0 new/enlarged entries and 68 stale entries.
- Supported refresh: `scripts\audit.cmd --update-quality-baseline` -> 1,838
  findings, 37 ceilings, 354 legacy Python files.
- Final gate: `scripts\audit.cmd --quality-check` -> `quality: baseline current;
  no new or enlarged debt`.
- Coverage: 187/206 changed statements, 90.8%; controller package 1,337/1,517,
  88.1% versus the 87.4% floor. The fresh coverage-mode run passed 2,301 tests
  (2,288 passed, 13 skipped).
- Full pytest: 2,245 passed, 4 skipped, 9 xfailed, 43 subtests passed.
- Focused architecture/controller suite: 269 passed. Coverage provenance and
  runner policy suite: 64 passed. Extracted Qt review-action suite: 4 passed.
- Audit generation and `scripts\audit.cmd --verify`: 178 modules, zero cycles,
  1,844 normalized findings, and `audit generated output is current`.

## Architectural correction

Three broader scanner-typing attempts were rejected because they either made
TV operation capabilities mandatory for metadata-only consumers, widened
construction to `Any`/`object`, or still could not make Pyright infer members
from a runtime `type()` namespace. The final design keeps explicit capability
protocols and fixes the legacy fixture at its test boundary. No ignore, pragma,
allowlist, manual baseline edit, or coverage exclusion was added.

## Commit scope and concerns

The commit includes the production, audit-policy, tests, supported
`quality-baseline.json`, and this report. It excludes `.audit`, coverage data,
`scripts/audit/cycle-baseline.json`, `audit.sarif`, and generated `docs/audit`
files. Those generated files were refreshed and verified only as working-tree
evidence and remain unstaged as required.

## Important-review follow-up

The four Important findings were repaired in a single TDD follow-up:

- Replaced the open-ended episode projection tuple with exact nested aliases
  for previews, companions, completeness, scanner metadata, season names, and
  the top-level cache signature. A narrow projection-media protocol removes
  the last strict-Pyright unknown at the legacy `ScanState.media_info` boundary.
- Replaced cycle-edge `Mapping[str, object]`/`dict[str, object]` casts with a
  `CycleGraph` schema, recursive TOML value types, and explicit non-empty string
  narrowing. Malformed record errors and exact graph-coverage validation remain
  unchanged. `_render_human.CYCLE_EDGE_FIELDS` is again a compatibility export.
- Coverage evidence now identifies itself as `full-coverage`, records the
  `complete-test-discovery-v1` method, and prints `Full coverage test suite` for
  coverage runs. The validator expects that identity and describes the
  complete coverage suite. Ordinary non-coverage runs retain the `Fast test
  suite` label. Unexpected test exclusions now force partial evidence.

### Follow-up evidence

- RED: focused pytest stopped during collection because the new structured
  projection aliases did not exist. Strict Pyright then reported eight unknown
  media-info diagnostics, followed by one boundary diagnostic after the first
  narrowing attempt.
- GREEN: strict Pyright on the projection-cache and cycle-edge modules reported
  0 errors, 0 warnings; the expanded focused suite passed 157 tests, and the
  final post-ratchet slice passed 38 tests.
- Ruff formatting and lint passed for all 13 follow-up source/test files.
- Fresh complete-suite coverage passed 2,305 tests: 2,292 passed and 13 skipped.
  Its sidecar records `full_suite=true`, `partial=false`, `failed=false`, no
  pytest filters, and only `tests/conftest_qt.py` (a fixture module) excluded.
- The pre-refresh gate reported 0 new/enlarged debt and 3 stale improvements.
  The supported refresh recorded 1,837 findings, 37 ceilings, and 354 legacy
  Python files. The final gate reported `baseline current; no new or enlarged
  debt`.
- Audit generation reported 178 modules, 0 cycles, and 1,843 normalized
  findings. `scripts\\audit.ps1 --verify` reported generated output current.
