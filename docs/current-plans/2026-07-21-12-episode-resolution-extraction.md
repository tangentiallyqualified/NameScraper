# Episode Resolution Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce `apply_confidence_adjustments` complexity while preserving every decision locked by the confidence corpus.

**Architecture:** Move confidence-only policy into `_episode_confidence_policy.py` as pure calculations over typed `FileEntry`, `Assignment`, and slot/coverage summaries. Keep conflict resolution and table mutation orchestration in `_episode_resolution.py`. Apply floors first and terminal caps last, exactly matching current order.

**Tech Stack:** Python 3.14, dataclasses/typed collections, Pyright, pytest.

## Global Constraints

- Execute only after the outcome corpus plan is accepted and green.
- Behavior-preserving: no confidence constant or threshold changes.
- Preserve conflict resolution -> assignment floors -> coverage floors -> contradiction caps -> review locks.
- New policy module and tests must be Pyright strict-clean.
- `apply_confidence_adjustments` remains the public entry point.

---

### Task 1: Extract per-assignment floor calculation

**Files:**
- Create: `plex_renamer/engine/_episode_confidence_policy.py`
- Modify: `plex_renamer/engine/_episode_resolution.py:1382-1471`
- Test: `tests/test_episode_confidence_policy.py`

**Interfaces:**
- Produces: `AssignmentConfidenceResult(confidence: float, contradicted: bool)`
- Produces: `assignment_confidence(entry, assignment, first_slot, *, show_name, show_year, show_norms) -> AssignmentConfidenceResult`

- [ ] **Step 1: Write direct RED tests for floor and contradiction ordering**

```python
def _entry(
    filename: str, *, relative: bool, season_hint: int | None
) -> FileEntry:
    return FileEntry(
        file_id=0,
        path=Path(filename),
        parsed_episodes=(1,),
        is_season_relative=relative,
        season_hint=season_hint,
    )


def _assignment(*, confidence: float) -> Assignment:
    return Assignment(
        file_id=0,
        season=1,
        episodes=(1,),
        origin=ORIGIN_AUTO,
        confidence=confidence,
        evidence=frozenset({"number", "season-relative"}),
    )


def test_assignment_floor_reports_contradiction_without_applying_terminal_cap() -> None:
    result = assignment_confidence(
        entry=_entry("Other.Show.S01E01.mkv", relative=True, season_hint=1),
        assignment=_assignment(confidence=0.40),
        first_slot=EpisodeSlot(season=1, episode=1, title="Pilot"),
        show_name="Show",
        show_year="",
        show_norms={"show"},
    )
    assert result.confidence >= EXPLICIT_EPISODE_FLOOR
    assert result.contradicted is True
```

- [ ] **Step 2: Run and confirm RED**

Run: `.venv\Scripts\python.exe -m pytest tests\test_episode_confidence_policy.py -q`
Expected: collection FAIL because the policy module does not exist.

- [ ] **Step 3: Move compatible-prefix, explicit-episode, title, and Plex-ready calculations**

```python
@dataclass(frozen=True, slots=True)
class AssignmentConfidenceResult:
    confidence: float
    contradicted: bool
```

The helper returns calculation only; `_episode_resolution.apply_confidence_adjustments` remains responsible for `table.set_confidence` and recording contradicted file IDs.

- [ ] **Step 4: Run policy, corpus, and resolution tests**

Run: `.venv\Scripts\python.exe -m pytest tests\test_episode_confidence_policy.py tests\test_episode_confidence_outcomes.py tests\test_episode_resolution.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add plex_renamer/engine/_episode_confidence_policy.py plex_renamer/engine/_episode_resolution.py tests/test_episode_confidence_policy.py
git commit -m "refactor: extract assignment confidence policy"
```

### Task 2: Extract season coverage calculations

**Files:**
- Modify: `plex_renamer/engine/_episode_confidence_policy.py`
- Modify: `plex_renamer/engine/_episode_resolution.py:1410-1518`
- Test: `tests/test_episode_confidence_policy.py`

**Interfaces:**
- Produces: `coverage_floor(expected, matched, *, single_regular_season, perfect_show) -> float | None`

- [ ] **Step 1: Add a complete decision table**

```python
@pytest.mark.parametrize(
    "expected, matched, single, perfect, floor",
    [
        ({1, 2}, {1, 2}, False, False, EXACT_COVERAGE_FLOOR),
        (
            {1, 2},
            {1, 2},
            True,
            True,
            SINGLE_SEASON_PERFECT_SHOW_EXACT_COVERAGE_FLOOR,
        ),
        ({1, 2, 3}, {1, 2}, False, False, NEAR_COMPLETE_COVERAGE_FLOOR),
        ({1, 2, 3, 4}, {1}, False, False, None),
        (set(), set(), False, False, None),
    ],
)
def test_coverage_floor_decision_table(
    expected: set[int],
    matched: set[int],
    single: bool,
    perfect: bool,
    floor: float | None,
) -> None:
    assert coverage_floor(
        expected,
        matched,
        single_regular_season=single,
        perfect_show=perfect,
    ) == floor
```

- [ ] **Step 2: Move only the pure floor selection**

The caller still builds `season_has_issue`, `matched_by_season`, and iterates assignments to mutate the table. The helper receives sets and booleans and returns a floor or `None`.

- [ ] **Step 3: Run all confidence policy tests and commit**

Run: `.venv\Scripts\python.exe -m pytest tests\test_episode_confidence_policy.py tests\test_episode_confidence_outcomes.py tests\test_scan_improvements.py -q`
Expected: PASS.

```powershell
git add plex_renamer/engine/_episode_confidence_policy.py plex_renamer/engine/_episode_resolution.py tests/test_episode_confidence_policy.py
git commit -m "refactor: extract coverage confidence policy"
```

### Task 3: Extract terminal cap calculation and simplify orchestration

**Files:**
- Modify: `plex_renamer/engine/_episode_confidence_policy.py`
- Modify: `plex_renamer/engine/_episode_resolution.py:1519-1555`
- Test: `tests/test_episode_confidence_policy.py`

**Interfaces:**
- Produces: `terminal_confidence_cap(evidence: AbstractSet[str], *, contradicted: bool) -> float | None`

- [ ] **Step 1: Add precedence tests**

```python
def test_review_lock_is_never_raised_by_contradiction_cap() -> None:
    assert terminal_confidence_cap(
        {"title-strong-inexact"}, contradicted=True
    ) == min(CONTRADICTORY_PREFIX_CAP, CONF_TITLE_WINS_INEXACT)


def test_uncapped_evidence_returns_none() -> None:
    assert terminal_confidence_cap({"number", "title-agree"}, contradicted=False) is None
```

- [ ] **Step 2: Centralize the immutable review-lock evidence set and cap selection**

Move the evidence frozenset to the policy module. The main function calls the helper only after every floor has been applied.

- [ ] **Step 3: Run full resolution/scan regressions**

Run: `.venv\Scripts\python.exe -m pytest tests\test_episode_confidence_policy.py tests\test_episode_confidence_outcomes.py tests\test_episode_resolution.py tests\test_confidence_adjustment_guards.py tests\test_scan_improvements.py -q`
Expected: PASS.

- [ ] **Step 4: Run strict type/format checks**

Run: `.venv\Scripts\ruff.exe format plex_renamer\engine\_episode_confidence_policy.py plex_renamer\engine\_episode_resolution.py tests\test_episode_confidence_policy.py && .venv\Scripts\ruff.exe check plex_renamer\engine\_episode_confidence_policy.py plex_renamer\engine\_episode_resolution.py tests\test_episode_confidence_policy.py && .venv\Scripts\pyright.exe plex_renamer\engine\_episode_confidence_policy.py plex_renamer\engine\_episode_resolution.py tests\test_episode_confidence_policy.py`
Expected: all commands exit 0 and `apply_confidence_adjustments` complexity is materially below 49.

- [ ] **Step 5: Commit**

```powershell
git add plex_renamer/engine/_episode_confidence_policy.py plex_renamer/engine/_episode_resolution.py tests/test_episode_confidence_policy.py
git commit -m "refactor: isolate terminal confidence caps"
```

### Task 4: Prune baselines and close `ARCH-001`

**Files:**
- Modify: `docs/deferred-work.md`
- Modify prune-only: `scripts/audit/quality-baseline.json`

- [ ] **Step 1: Remove `ARCH-001` and update the P2 summary**

- [ ] **Step 2: Prune quality entries without accepting debt**

Run: `scripts\audit.cmd --update-quality-baseline`
Expected: exit 0; the old complexity/LOC entries shrink or disappear and no new/enlarged entry is enrolled.

- [ ] **Step 3: Commit**

```powershell
git add docs/deferred-work.md scripts/audit/quality-baseline.json
git commit -m "chore: close episode resolution architecture debt"
```
