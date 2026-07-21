# Quality-Gate Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Require an exact operator-reviewed debt set before `--accept-enlarged` can update the quality baseline.

**Architecture:** Add a repeatable `--expect-enlarged` CLI value whose canonical identities are parsed before collection. `gate_refresh_debt` compares the expected multiset with the actual new/enlarged multiset and refuses missing, extra, duplicate, or malformed expectations before the baseline write. Keep `build_baseline(..., accept_enlarged=True)` as a low-level bypass with an explicit caller precondition.

**Tech Stack:** Python 3.14, argparse, pytest, existing audit ratchet helpers.

## Global Constraints

- Implement `AUDIT-001`, `AUDIT-002`, and `AUDIT-003`; do not touch accepted SIM103/SIM117 decisions.
- Use TDD and retain ASCII-only CLI output.
- Do not update `scripts/audit/quality-baseline.json` in task commits.
- Run file-scoped Ruff and Pyright plus focused pytest after each task.
- Completed plans are removed and archived outside the repository after integration.

---

### Task 1: Parse exact expected-debt identities

**Files:**
- Modify: `scripts/audit/__main__.py:142-190`
- Test: `tests/audit/test_quality_baseline_accept.py`

**Interfaces:**
- Produces: `options.expect_enlarged: list[str]`
- Produces: `_validate_accept_enlarged(parser, options) -> None` rejecting expectations without both update and acceptance flags.

- [ ] **Step 1: Write failing argparse tests**

```python
def test_expect_enlarged_requires_accept_and_update(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        _main(["--expect-enlarged", "inventory|LOC|plex_renamer/a.py"])
    assert exc_info.value.code == 2
    assert (
        "--expect-enlarged requires --update-quality-baseline and --accept-enlarged"
        in capsys.readouterr().err
    )


def test_accept_enlarged_requires_update_quality_baseline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        _main(["--accept-enlarged", "--repo-root", str(tmp_path)])
    assert exc_info.value.code == 2
    assert (
        "--accept-enlarged requires --update-quality-baseline"
        in capsys.readouterr().err
    )
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `.venv\Scripts\python.exe -m pytest tests\audit\test_quality_baseline_accept.py -q`
Expected: FAIL because `--expect-enlarged` is unknown and the existing guard test does not assert stderr.

- [ ] **Step 3: Add the repeatable option and guard**

```python
parser.add_argument(
    "--expect-enlarged",
    action="append",
    default=[],
    metavar="ANALYZER|RULE|PATH",
    help="Expected new/enlarged debt identity; repeat once per reviewed entry.",
)

if options.expect_enlarged and not (
    options.update_quality_baseline and options.accept_enlarged
):
    parser.error(
        "--expect-enlarged requires --update-quality-baseline and --accept-enlarged"
    )
```

- [ ] **Step 4: Run focused pytest, Ruff, and Pyright**

Run: `.venv\Scripts\python.exe -m pytest tests\audit\test_quality_baseline_accept.py -q`
Expected: PASS.

Run: `.venv\Scripts\ruff.exe format scripts\audit\__main__.py tests\audit\test_quality_baseline_accept.py && .venv\Scripts\ruff.exe check scripts\audit\__main__.py tests\audit\test_quality_baseline_accept.py && .venv\Scripts\pyright.exe scripts\audit\__main__.py tests\audit\test_quality_baseline_accept.py`
Expected: all commands exit 0.

- [ ] **Step 5: Commit**

```powershell
git add scripts/audit/__main__.py tests/audit/test_quality_baseline_accept.py
git commit -m "audit: parse expected enlarged debt"
```

### Task 2: Compare the expected and actual debt multisets

**Files:**
- Modify: `scripts/audit/_quality_refresh.py:31-49`
- Modify: `scripts/audit/_ratchets.py:448-454`
- Test: `tests/audit/test_quality_baseline_accept.py`

**Interfaces:**
- Produces: `debt_identity(finding: Mapping[str, object]) -> str`
- Changes: `gate_refresh_debt(violations, accept_enlarged, expected_entries=()) -> None`

- [ ] **Step 1: Add failing exact/missing/additional/duplicate/malformed tests**

```python
EXPECTED_LOC = "inventory|LOC|plex_renamer/legacy.py"
EXPECTED_COVERAGE = "coverage|package-floor|plex_renamer"


@pytest.mark.parametrize(
    "expected, message",
    [
        ([EXPECTED_LOC], "unexpected debt: coverage|package-floor|plex_renamer"),
        (
            [EXPECTED_LOC, EXPECTED_COVERAGE, "ruff|F401|plex_renamer/extra.py"],
            "expected debt not produced: ruff|F401|plex_renamer/extra.py",
        ),
        ([EXPECTED_LOC, EXPECTED_LOC, EXPECTED_COVERAGE], "duplicate expectation"),
        (["inventory|LOC"], "malformed expectation"),
    ],
)
def test_accept_enlarged_requires_exact_expectations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    expected: list[str],
    message: str,
) -> None:
    path, before = _write_enlarged_debt_fixture(tmp_path, monkeypatch)
    args = ["--update-quality-baseline", "--accept-enlarged", "--repo-root", str(tmp_path)]
    for entry in expected:
        args.extend(["--expect-enlarged", entry])
    assert _main(args) == 1
    assert path.read_bytes() == before
    assert message in capsys.readouterr().out
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `.venv\Scripts\python.exe -m pytest tests\audit\test_quality_baseline_accept.py -q`
Expected: FAIL because the expected entries are not passed to the gate.

- [ ] **Step 3: Implement canonical identity and multiset equality**

```python
from collections import Counter
from collections.abc import Iterable, Mapping


def debt_identity(finding: Mapping[str, object]) -> str:
    return f"{finding['analyzer']}|{finding['rule']}|{finding['path']}"


def gate_refresh_debt(
    violations: list[dict[str, object]],
    accept_enlarged: bool,
    expected_entries: Iterable[str] = (),
) -> None:
    debt = [finding for finding in violations if finding["kind"] != "stale-baseline"]
    if not accept_enlarged:
        reject_new_debt(violations)
        return
    expected = list(expected_entries)
    malformed = [entry for entry in expected if len(entry.split("|")) != 3]
    if malformed:
        raise QualityBaselineRefused(f"malformed expectation: {malformed[0]}")
    counts = Counter(expected)
    duplicate = next((entry for entry, count in counts.items() if count > 1), None)
    if duplicate is not None:
        raise QualityBaselineRefused(f"duplicate expectation: {duplicate}")
    actual = {debt_identity(finding) for finding in debt}
    expected_set = set(expected)
    if extra := sorted(actual - expected_set):
        raise QualityBaselineRefused(f"unexpected debt: {extra[0]}")
    if missing := sorted(expected_set - actual):
        raise QualityBaselineRefused(f"expected debt not produced: {missing[0]}")
```

Pass `options.expect_enlarged` from the CLI into `run_quality_baseline_update`, then into `gate_refresh_debt`; keep the comparison before `build_baseline` and `write_text`.

- [ ] **Step 4: Prove exact acceptance writes and every mismatch preserves bytes**

Run: `.venv\Scripts\python.exe -m pytest tests\audit\test_quality_baseline_accept.py tests\audit\test_ratchet_collection.py -q`
Expected: PASS, including an updated happy-path test that supplies both expected identities.

- [ ] **Step 5: Commit**

```powershell
git add scripts/audit/_quality_refresh.py scripts/audit/_ratchets.py tests/audit/test_quality_baseline_accept.py
git commit -m "audit: require exact debt acceptance"
```

### Task 3: Document the low-level caller contract and close the backlog entries

**Files:**
- Modify: `scripts/audit/_ratchets.py:108-128`
- Modify: `docs/deferred-work.md`
- Test: `tests/audit/test_quality_baseline_accept.py`

**Interfaces:**
- Preserves: `build_baseline(current, previous_baseline, accept_enlarged=False) -> dict`

- [ ] **Step 1: Replace the one-line docstring with the exact precondition**

```python
def build_baseline(
    current: dict, previous_baseline: dict, accept_enlarged: bool = False
) -> dict:
    """Refresh evidence while preserving the frozen legacy inventory.

    When ``accept_enlarged`` is true, the caller must first pass the same
    evidence through ``gate_refresh_debt`` with an exact operator-reviewed
    expected-entry set. This low-level function does not authorize debt.
    """
```

- [ ] **Step 2: Run focused audit tests**

Run: `.venv\Scripts\python.exe -m pytest tests\audit\test_quality_baseline_accept.py tests\audit\test_ratchets.py tests\audit\test_ratchet_collection.py -q`
Expected: PASS.

- [ ] **Step 3: Remove `AUDIT-001`, `AUDIT-002`, and `AUDIT-003` from active backlog sections**

Delete those three complete entries from `docs/deferred-work.md` and update the priority summary so it contains no dangling IDs. Do not add a completed-history section.

- [ ] **Step 4: Run final scoped verification**

Run: `.venv\Scripts\ruff.exe format scripts\audit\_quality_refresh.py scripts\audit\_ratchets.py scripts\audit\__main__.py tests\audit\test_quality_baseline_accept.py && .venv\Scripts\ruff.exe check scripts\audit\_quality_refresh.py scripts\audit\_ratchets.py scripts\audit\__main__.py tests\audit\test_quality_baseline_accept.py && .venv\Scripts\pyright.exe scripts\audit\_quality_refresh.py scripts\audit\_ratchets.py scripts\audit\__main__.py tests\audit\test_quality_baseline_accept.py`
Expected: all commands exit 0.

- [ ] **Step 5: Commit**

```powershell
git add scripts/audit/_ratchets.py docs/deferred-work.md
git commit -m "docs: close quality gate debt items"
```
