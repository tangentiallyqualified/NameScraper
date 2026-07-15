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
- Change only the six Windows-sensitive expectations reported by Actions run `29391461679`.
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
