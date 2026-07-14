# Quality Ratchets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent new formatting, lint, typing, coverage, complexity, size, and finding-decision debt without requiring an immediate whole-repository cleanup.

**Architecture:** Explicit policy lives in `pyproject.toml` and `scripts/audit/policy.toml`; a committed JSON baseline records legacy exceptions. CI evaluates changed/new code strictly and repository-wide metrics as non-increasing ratchets, emitting SARIF and generated Markdown from the same normalized findings.

**Tech Stack:** Ruff, Pyright, Coverage.py, Radon, pytest, SARIF 2.1.0, GitHub Actions.

## Global Constraints

- Current repository patterns are not inferred as style policy.
- New Python files must pass all configured rules; existing files may not add violations.
- Existing complexity, file-size, typing, and coverage debt may not worsen.
- Exceptions require a qualified target, rule ID, reason code, prose reason, and optional expiry.
- Stale exceptions fail verification.
- JSON/SARIF are sources of truth; Markdown is generated.

---

### Task 1: Declare formatting and curated lint policy

**Files:** Modify `pyproject.toml`; create `scripts/audit/policy.toml`; create
`tests/audit/test_quality_policy.py`.

**Interfaces:** Ruff format line length 100; lint families `E4,E7,E9,F,I,UP,B,C4,SIM,PIE,RUF` with documented PySide/test per-file ignores.

- [ ] Write failing tests that load TOML and assert exact formatter/lint policy.
- [ ] Run `.venv\Scripts\python.exe -m pytest tests\audit\test_quality_policy.py -q`; expect missing-policy failures.
- [ ] Add the explicit configuration and a policy schema version of `1`.
- [ ] Run Ruff only against newly touched plan files and confirm exit 0.
- [ ] Commit with `chore(quality): declare Python style policy`.

### Task 2: Add violation-baseline ratchets

**Files:** create `scripts/audit/_ratchets.py`; create
`scripts/audit/quality-baseline.json`; create `tests/audit/test_ratchets.py`;
modify `scripts/audit/__main__.py`.

**Interfaces:** `evaluate_ratchets(current, baseline) -> list[Finding]` compares
rule/path/symbol tuples and CC/LOC numeric ceilings; `audit --quality-check`
returns nonzero only for new/enlarged debt.

- [ ] Write RED tests for unchanged legacy debt, new lint findings, increased CC, new oversized files, resolved debt, and stale baseline entries.
- [ ] Implement normalized keys and deterministic sorted findings.
- [ ] Generate the initial baseline from `dev/audit-debt3` evidence.
- [ ] Run audit tests and commit with `feat(quality): enforce no-new-debt ratchets`.

### Task 3: Add boundary-focused typing

**Files:** modify `pyproject.toml`; create `pyrightconfig.json`; create
`tests/audit/test_type_policy.py`; modify CI.

**Interfaces:** Pyright basic mode repository-wide; strict mode for
`plex_renamer/app/models`, `plex_renamer/engine/_discovery_ports.py`, and newly
created modules; exclusions are explicit and ratcheted.

- [ ] Write RED configuration-contract tests.
- [ ] Add `pyright` to dev dependencies and exact include/exclude execution.
- [ ] Capture existing diagnostics as a ratchet rather than inline ignores.
- [ ] Run focused typing and tests; commit with `ci(quality): add boundary type ratchets`.

### Task 4: Add changed-code coverage and full-suite provenance

**Files:** modify `scripts/test_fast_runner.py`, `scripts/audit/_coverage.py`,
CI, and coverage tests.

**Interfaces:** coverage metadata stores audit `input_digest`; changed executable
lines require at least 80% coverage; unchanged package floors cannot decrease.

- [ ] Write RED tests for digest-matched coverage, mismatched evidence, and changed-line calculation.
- [ ] Extend metadata and deterministic diff coverage calculation.
- [ ] Add CI reporting without lowering the current full-suite behavior.
- [ ] Run tests and commit with `feat(quality): ratchet changed-code coverage`.

### Task 5: Move finding decisions to machine-readable policy and emit SARIF

**Files:** create `scripts/audit/decisions.toml`; create
`scripts/audit/_decisions.py`; create `scripts/audit/_render_sarif.py`; modify
human renderers and CLI; add focused tests.

**Interfaces:** decisions key on analyzer/rule/path/qualified symbol and use
reason codes `framework-callback`, `serialized-field`, `public-api`,
`test-seam`, `intentional-reservation`, or `accepted-debt`; SARIF version 2.1.0.

- [ ] Write RED tests for matching, stale decisions, duplicate decisions, Markdown generation, and SARIF locations.
- [ ] Migrate active allowlist entries; retain historical prose as archive only.
- [ ] Generate live review tables and `audit.sarif` from normalized findings.
- [ ] Upload SARIF in CI, run audit/full tests, and commit with `feat(audit): generate decisions and SARIF`.

### Task 6: Final quality-gate verification

- [ ] Run `scripts\audit.cmd --quality-check` and expect exit 0.
- [ ] Run `.venv\Scripts\python.exe -m pyright` and expect only baselined legacy diagnostics.
- [ ] Run `.venv\Scripts\python.exe -m pytest -q` and expect no failures.
- [ ] Run `scripts\audit.cmd --verify` and expect current deterministic output.
- [ ] Commit generated baselines/artifacts with `chore(quality): establish ratchet baselines`.
