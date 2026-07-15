# PR #23 CI Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make both PR #23 CI jobs pass without weakening the deterministic audit toolchain contract or changing production path behavior.

**Architecture:** Keep Coverage exactly pinned at `7.15.0` and make every CI job that runs audit tests consume the same constraints file. Treat the Windows failures as portability defects in test expectations: production code intentionally canonicalizes paths, so tests must canonicalize their expected roots too.

**Tech Stack:** GitHub Actions YAML, Python 3.12, pytest, pathlib, PowerShell audit wrappers.

## Global Constraints

- Keep `coverage==7.15.0`; do not replace exact analyzer pins with ranges.
- Do not use `pip install --no-deps`.
- Every CI job that installs `.[dev]` and runs audit tests must apply `scripts/audit/constraints.txt`.
- Preserve production calls to `Path.resolve()` and canonical containment behavior.
- Change production semantics only through the six Windows-sensitive expectations reported by Actions run `29391461679`; formatting and a cohesive test-file split are authorized solely to satisfy the existing ratchets.
- Generator-owned JSON/SARIF outputs and enrolled JSON inputs must check out with LF bytes on every operating system.
- Do not refresh the quality baseline to accept new or enlarged debt.
- Preserve unrelated user-owned files, including the ignored `scripts/scan_real_library.py` in the main checkout.

---

### Task 1: Constrain the Linux Fast-Test Toolchain

**Files:**
- Modify: `.github/workflows/ci.yml`
- Test: `tests/audit/test_workflows.py`

**Interfaces:**
- Consumes: `scripts/audit/constraints.txt` with exact analyzer pins.
- Produces: a `fast-tests` installation command that installs `.[dev]` through the committed constraints file.

- [ ] **Step 1: Add a failing workflow contract test**

Add a test that extracts the `fast-tests` job and its dependency-install step, then requires both `pip install -e ".[dev]"` and `-c scripts/audit/constraints.txt` in that same step.

- [ ] **Step 2: Verify the new test fails for the missing constraint**

Run: `.\.venv\Scripts\python.exe -m pytest tests/audit/test_workflows.py -q`

Expected: FAIL because the Linux `fast-tests` install currently omits `-c scripts/audit/constraints.txt`.

- [ ] **Step 3: Apply the minimal workflow fix**

Change the Linux command to:

```yaml
pip install -e ".[dev]" -c scripts/audit/constraints.txt
```

- [ ] **Step 4: Verify the workflow contracts pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/audit/test_workflows.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

Commit message: `fix(ci): constrain fast-test audit toolchain`

### Task 2: Canonicalize Windows Path Expectations

**Files:**
- Test: `tests/test_media_controller.py`
- Test: `tests/test_refresh_policy_service.py`

**Interfaces:**
- Consumes: production helpers that intentionally return paths rooted at `Path.resolve()` results.
- Produces: portable assertions that compare canonical expected paths on Windows and remain equivalent on POSIX.

- [ ] **Step 1: Confirm the existing red evidence**

Use Actions run `29391461679`: the six assertions fail because `TemporaryDirectory()` supplies `C:/Users/RUNNER~1/...` while production `Path.resolve()` returns `C:/Users/runneradmin/...` for the same directory.

- [ ] **Step 2: Canonicalize only the six expected values**

In the three refresh-policy assertions, compare to `(lib / "Show").resolve()` or `lib.resolve()`. In the three media-controller tests, derive `resolved_output = output.resolve()` and compare output-root and target-directory values beneath that canonical root.

- [ ] **Step 3: Run the focused tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_media_controller.py tests/test_refresh_policy_service.py -q`

Expected: all focused tests pass.

- [ ] **Step 4: Commit**

Commit message: `fix(tests): canonicalize Windows path expectations`

### Task 2A: Pay Down Touched-Test Formatting and Size Debt

**Files:**
- Modify: `tests/test_media_controller.py`
- Modify: `tests/test_refresh_policy_service.py`
- Create: one narrowly named `tests/test_media_controller_*.py` file only if needed to keep `tests/test_media_controller.py` at or below its committed `1961` LOC ceiling after formatting.

**Interfaces:**
- Consumes: the six canonical-path expectations from Task 2 and the existing quality baseline.
- Produces: fully Ruff-formatted touched test files, no enlarged LOC debt, and no loss or duplication of collected tests.

- [ ] **Step 1: Format both touched test files**

Run Ruff formatting on `tests/test_media_controller.py` and `tests/test_refresh_policy_service.py`. Do not add formatter exclusions or refresh the formatting baseline.

- [ ] **Step 2: Extract one cohesive controller-test unit if required**

If formatting leaves `tests/test_media_controller.py` above `1961` LOC, move the smallest cohesive class or group of related classes needed to a narrowly named formatted test module. Reuse existing helpers through the repository's established adjacent-test import pattern; do not copy controller setup logic. Preserve every test and avoid new typing or lint findings in the new file.

- [ ] **Step 3: Verify test preservation and behavior**

Run the focused controller and refresh-policy tests, including the new module if created. Compare collection before and after the split so no test is lost or duplicated.

- [ ] **Step 4: Collect fresh coverage and enforce ratchets**

Run `.\scripts\test-fast.cmd -Coverage`, then `.\scripts\audit.cmd --quality-check`.

Expected: the test suite passes and the quality gate reports no new or enlarged debt. Stale formatter-baseline entries are an expected improvement and must not be re-enrolled.

- [ ] **Step 5: Commit**

Commit message: `refactor(tests): pay down touched-file debt`

### Task 3: Regenerate and Verify Audit Evidence

**Files:**
- Modify: generated audit artifacts selected by the audit harness.

**Interfaces:**
- Consumes: the completed Task 1 and Task 2 commits plus exact-digest coverage evidence.
- Produces: current committed audit artifacts and a PR head ready for GitHub Actions.

- [ ] **Step 1: Collect fresh coverage evidence**

Run: `.\scripts\test-fast.cmd -Coverage`

Expected: zero test failures.

- [ ] **Step 2: Enforce the quality ratchets**

Run: `.\scripts\audit.cmd --quality-check`

Expected: no new or enlarged debt.

- [ ] **Step 3: Regenerate committed audit artifacts**

Run: `.\scripts\audit.cmd`

Inspect the generated diff and confirm it contains only deterministic consequences of the approved CI/test changes.

- [ ] **Step 4: Verify generated output**

Run: `.\scripts\audit.cmd --verify`

Expected: generated output is current.

- [ ] **Step 5: Commit and verify again**

Commit message: `chore(audit): refresh CI remediation artifacts`

After committing, rerun `.\scripts\audit.cmd --verify` because documentation status depends on committed Git history.

- [ ] **Step 6: Push and monitor**

Fast-forward `dev/audit-debt3` to the verified head, push it, and monitor PR #23 until both `fast-tests` and `audit-verify` complete.

### Task 4: Pin Structured Audit Files to LF

**Files:**
- Modify: `.gitattributes`
- Test: `tests/audit/test_repository_contracts.py`
- Modify: generated audit artifacts selected by the audit harness.

**Interfaces:**
- Consumes: `_artifacts.write_text_lf()` and exact-byte generated-output verification.
- Produces: OS-independent checkout bytes for enrolled JSON inputs and generated JSON/SARIF outputs.

- [ ] **Step 1: Add a failing repository contract test**

Add:

```python
def test_structured_audit_files_are_pinned_to_lf() -> None:
    attributes = {
        line.strip()
        for line in (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    }
    assert "*.json text eol=lf" in attributes
    assert "*.sarif text eol=lf" in attributes
```

- [ ] **Step 2: Verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/audit/test_repository_contracts.py::test_structured_audit_files_are_pinned_to_lf -q`

Expected: FAIL because both LF rules are absent.

- [ ] **Step 3: Apply the minimal checkout contract**

Add to `.gitattributes` beside the existing structured-text rules:

```gitattributes
*.json text eol=lf
*.sarif text eol=lf
```

- [ ] **Step 4: Verify GREEN and the pristine digest hypothesis**

Run the focused repository-contract test and confirm it passes. Confirm `git check-attr eol -- pyrightconfig.json audit.sarif docs/audit/baseline.json` reports `lf` for all three paths.

- [ ] **Step 5: Commit the checkout fix**

Commit message: `fix(audit): pin structured artifacts to LF`

- [ ] **Step 6: Regenerate and verify exact-digest evidence**

Run, in order:

```powershell
.\scripts\test-fast.cmd -Coverage
.\scripts\audit.cmd --quality-check
.\scripts\audit.cmd
.\scripts\audit.cmd --verify
```

Expected: zero test failures, zero new/enlarged debt, and generated output current. Inspect the generated diff and confirm it contains only deterministic consequences of Task 4.

- [ ] **Step 7: Commit artifacts and verify again**

Commit message: `chore(audit): refresh LF contract artifacts`

After committing, rerun `.\scripts\audit.cmd --verify` because document status depends on committed history.

- [ ] **Step 8: Push and monitor**

Fast-forward `dev/audit-debt3` to the reviewed head, push it, and monitor PR #23 until both `fast-tests` and `audit-verify` complete.

### Task 5: Stabilize Coverage Across Supported Python Runtimes

**Files:**
- Create: `tests/test_matching_helpers.py`
- Modify: generated audit artifacts selected by the audit harness.

**Interfaces:**
- Consumes: `plex_renamer.engine._tv_scanner_consolidated._contiguous_run`, `plex_renamer.engine.matching.pick_alternate_matches`, and full-suite coverage evidence.
- Produces: explicit coverage of both helpers' natural loop-completion paths so Python 3.12 and Python 3.14 generate the same baseline percentages.

- [ ] **Step 1: Preserve the cross-runtime RED evidence**

Record that the same passing suite reports `_tv_scanner_consolidated.py:47` and `matching.py:169` covered on Python 3.12 but missing on Python 3.14. Confirm those are the only fields that differ in `docs/audit/baseline.json`.

- [ ] **Step 2: Add the smallest behavior tests for natural loop completion**

Add one test that exhausts `_contiguous_run` without taking its `break`, and one test that exhausts `pick_alternate_matches` before reaching its limit. Assert the returned values, not coverage internals. Do not change production code or coverage normalization.

- [ ] **Step 3: Verify focused behavior and GREEN line evidence**

Run the new test module. Collect full coverage under the repository Python 3.14 environment and confirm lines 47 and 169 are no longer missing. Run the disposable constrained Python 3.12 reproduction and confirm its generated `docs/audit/baseline.json` is byte-identical to the Python 3.14 result.

- [ ] **Step 4: Enforce ratchets and regenerate artifacts**

Run, in order:

```powershell
.\scripts\test-fast.cmd -Coverage
.\scripts\audit.cmd --quality-check
.\scripts\audit.cmd
.\scripts\audit.cmd --verify
```

Expected: zero test failures, zero new/enlarged debt, and generated output current. Inspect the generated diff and confirm it contains only deterministic consequences of the two added tests.

- [ ] **Step 5: Commit, review, and verify again**

Commit the tests and resulting artifacts with intentional messages. After committing, rerun `.\scripts\audit.cmd --verify` because document status depends on committed Git history. Obtain task-level and final remediation reviews.

- [ ] **Step 6: Push and monitor**

Fast-forward `dev/audit-debt3` to the reviewed head, push it, and monitor PR #23 until both `fast-tests` and `audit-verify` complete successfully.
