# Episode Confidence Corpus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a documented, deterministic outcome corpus that distinguishes episode assignments which should auto-approve from those which must remain in review.

**Architecture:** Define strict typed scenario records outside the production module and execute them through `EpisodeAssignmentTable` plus `apply_confidence_adjustments`. The corpus records expected decision bands, not internal branch calls. Threshold changes are allowed only in a separate commit after corpus results demonstrate a false approval or needless review.

**Tech Stack:** Python 3.14, dataclasses/Literal, pytest parametrization, episode assignment engine.

## Global Constraints

- Implement `MATCH-001` characterization before `ARCH-001` extraction.
- Corpus scenarios are offline and deterministic; no live provider/library dependency.
- Each scenario names its real-world risk and expected approve/review outcome.
- Do not change confidence constants in the same commit that introduces the corpus.
- Preserve explicit conflicts and review-lock evidence regardless of floors.

---

### Task 1: Define the typed outcome corpus

**Files:**
- Create: `tests/episode_confidence_outcomes.py`
- Test: `tests/test_episode_confidence_outcomes.py`

**Interfaces:**
- Produces: `ConfidenceOutcome` and `OUTCOMES`

- [ ] **Step 1: Create a strict scenario record**

```python
from dataclasses import dataclass
from typing import Literal

Decision = Literal["approve", "review"]


@dataclass(frozen=True, slots=True)
class ConfidenceOutcome:
    name: str
    filename: str
    initial_confidence: float
    evidence: frozenset[str]
    is_season_relative: bool
    season_hint: int | None
    raw_title: str | None
    show_name: str
    slot_title: str
    show_match_confidence: float | None
    expected: Decision
    risk: str
```

- [ ] **Step 2: Add the minimum discriminating cases**

Create records for:

```python
OUTCOMES = (
    ConfidenceOutcome(
        name="explicit number and episode title agree",
        filename="Show.S01E01.Pilot.mkv",
        initial_confidence=0.60,
        evidence=frozenset({"number", "title-agree"}),
        is_season_relative=True,
        season_hint=1,
        raw_title="Pilot",
        show_name="Show",
        slot_title="Pilot",
        show_match_confidence=1.0,
        expected="approve",
        risk="needless review of explicit corroborated episode",
    ),
    ConfidenceOutcome(
        name="contradictory source title stays review",
        filename="Other.Show.S01E01.Pilot.mkv",
        initial_confidence=0.96,
        evidence=frozenset({"number", "title-agree"}),
        is_season_relative=True,
        season_hint=1,
        raw_title="Pilot",
        show_name="Show",
        slot_title="Pilot",
        show_match_confidence=1.0,
        expected="review",
        risk="false approval for a file carrying another show title",
    ),
    ConfidenceOutcome(
        name="provider alias prefix corroborates explicit episode",
        filename="Show.Alias.S01E01.mkv",
        initial_confidence=0.60,
        evidence=frozenset({"number", "season-relative"}),
        is_season_relative=True,
        season_hint=1,
        raw_title=None,
        show_name="Primary Show",
        slot_title="Pilot",
        show_match_confidence=None,
        expected="approve",
        risk="needless review when a configured provider alias matches the source",
    ),
    ConfidenceOutcome(
        name="strong inexact title remains review locked",
        filename="Show.S01E01.Pilot-ish.mkv",
        initial_confidence=0.90,
        evidence=frozenset({"number", "title-strong-inexact"}),
        is_season_relative=True,
        season_hint=1,
        raw_title="Pilot-ish",
        show_name="Show",
        slot_title="Pilot",
        show_match_confidence=1.0,
        expected="review",
        risk="false approval after a fuzzy title override",
    ),
    ConfidenceOutcome(
        name="multi segment title remains review locked",
        filename="Show.S01E01-E02.Pilot-and-Second.mkv",
        initial_confidence=0.96,
        evidence=frozenset({"number", "title-multi-segment"}),
        is_season_relative=True,
        season_hint=1,
        raw_title="Pilot and Second",
        show_name="Show",
        slot_title="Pilot",
        show_match_confidence=1.0,
        expected="review",
        risk="false approval when combined title evidence is not independently verified",
    ),
    ConfidenceOutcome(
        name="perfect single season exact coverage reaches threshold",
        filename="episode-one.mkv",
        initial_confidence=0.50,
        evidence=frozenset({"number"}),
        is_season_relative=False,
        season_hint=None,
        raw_title=None,
        show_name="Show",
        slot_title="Pilot",
        show_match_confidence=1.0,
        expected="approve",
        risk="needless review of the accepted exact-coverage product policy",
    ),
)
```

The table builder must pass `("Show Alias",)` for the alias case and an empty alias tuple for the other cases. The multi-segment and exact-coverage cases use dedicated builders because they require two slots or a full expected-season set.

- [ ] **Step 3: Add corpus integrity tests**

```python
def test_outcome_names_are_unique() -> None:
    assert len({case.name for case in OUTCOMES}) == len(OUTCOMES)


def test_outcomes_cover_both_decisions_and_every_record_has_risk() -> None:
    assert {case.expected for case in OUTCOMES} == {"approve", "review"}
    assert all(case.risk.strip() for case in OUTCOMES)
```

- [ ] **Step 4: Run strict type and corpus tests**

Run: `.venv\Scripts\python.exe -m pytest tests\test_episode_confidence_outcomes.py -q`
Expected: PASS for integrity tests.

Run: `.venv\Scripts\pyright.exe tests\episode_confidence_outcomes.py tests\test_episode_confidence_outcomes.py`
Expected: 0 errors.

- [ ] **Step 5: Commit**

```powershell
git add tests/episode_confidence_outcomes.py tests/test_episode_confidence_outcomes.py
git commit -m "test: define episode confidence outcomes"
```

### Task 2: Execute every scenario through the public policy entry

**Files:**
- Modify: `tests/test_episode_confidence_outcomes.py`

**Interfaces:**
- Consumes: `apply_confidence_adjustments(table, show_info=..., show_match_confidence=..., alt_show_names=...)`

- [ ] **Step 1: Add a table builder that uses real assignment types**

```python
def _table_for(case: ConfidenceOutcome) -> tuple[EpisodeAssignmentTable, int]:
    table = EpisodeAssignmentTable()
    table.add_slot(EpisodeSlot(season=1, episode=1, title=case.slot_title))
    entry = table.add_file(
        Path(case.filename),
        parsed_episodes=(1,),
        raw_title=case.raw_title,
        is_season_relative=case.is_season_relative,
        season_hint=case.season_hint,
    )
    table.assign(
        entry.file_id,
        1,
        [1],
        origin=ORIGIN_AUTO,
        confidence=case.initial_confidence,
        evidence=case.evidence,
    )
    return table, entry.file_id
```

- [ ] **Step 2: Add the parametrized approve/review assertion**

```python
@pytest.mark.parametrize("case", OUTCOMES, ids=lambda case: case.name)
def test_confidence_outcome(case: ConfidenceOutcome) -> None:
    table, file_id = _table_for(case)
    alt_show_names = (
        ("Show Alias",)
        if case.name == "provider alias prefix corroborates explicit episode"
        else ()
    )
    apply_confidence_adjustments(
        table,
        show_info={"name": case.show_name, "year": ""},
        show_match_confidence=case.show_match_confidence,
        alt_show_names=alt_show_names,
    )
    assignment = table.assignment_for(file_id)
    assert assignment is not None
    actual = (
        "approve"
        if assignment.confidence >= DEFAULT_EPISODE_AUTO_ACCEPT_THRESHOLD
        else "review"
    )
    assert actual == case.expected, case.risk
```

The one-slot exact-coverage record deliberately uses one expected slot and one matched file; that is a complete season set and exercises the real set-equality floor without assigning the final confidence in test code.

- [ ] **Step 3: Run and record actual policy disagreements**

Run: `.venv\Scripts\python.exe -m pytest tests\test_episode_confidence_outcomes.py -q`
Expected: every approved expectation passes. If a case disagrees, stop and classify it as a product decision; do not alter the expected result merely to make the suite green.

- [ ] **Step 4: Run related policy tests and commit**

Run: `.venv\Scripts\python.exe -m pytest tests\test_episode_confidence_outcomes.py tests\test_confidence_adjustment_guards.py tests\test_episode_resolution.py tests\test_batch_autoaccept_guards.py -q`
Expected: PASS.

```powershell
git add tests/test_episode_confidence_outcomes.py tests/episode_confidence_outcomes.py
git commit -m "test: lock episode confidence decisions"
```

### Task 3: Make separately justified tier corrections, if corpus evidence requires them

**Files:**
- Modify only when a corpus case is RED: `plex_renamer/engine/_episode_resolution.py`
- Modify: `tests/test_episode_confidence_outcomes.py`

- [ ] **Step 1: For each demonstrated disagreement, add a single-case RED regression**

The regression must assert both the intended decision and the exact evidence/floor or cap responsible. Do not batch unrelated constant changes.

- [ ] **Step 2: Change the narrowest named tier or terminal cap**

Example form:

```python
# Only after an approved false-approval corpus case proves this cap is too high.
CONTRADICTORY_PREFIX_CAP = 0.44
```

Prefer ordering/cap fixes over changing global thresholds. If the corpus already passes, make no production commit for this task.

- [ ] **Step 3: Run full resolution and scan policy suites**

Run: `.venv\Scripts\python.exe -m pytest tests\test_episode_confidence_outcomes.py tests\test_episode_resolution.py tests\test_confidence_adjustment_guards.py tests\test_scan_improvements.py tests\test_batch_autoaccept_guards.py -q`
Expected: PASS.

- [ ] **Step 4: Commit each approved correction separately**

```powershell
git add plex_renamer/engine/_episode_resolution.py tests/test_episode_confidence_outcomes.py
git commit -m "fix: calibrate episode confidence decision"
```

Skip the commit when no correction is required.

### Task 4: Close `MATCH-001`

**Files:**
- Modify: `docs/deferred-work.md`

- [ ] **Step 1: Remove `MATCH-001` and update the P1 summary**

Record rejected threshold proposals under the existing retired/rejected section only when the decision prevents rediscovery.

- [ ] **Step 2: Format/type check and commit**

Run: `.venv\Scripts\ruff.exe format tests\episode_confidence_outcomes.py tests\test_episode_confidence_outcomes.py plex_renamer\engine\_episode_resolution.py && .venv\Scripts\ruff.exe check tests\episode_confidence_outcomes.py tests\test_episode_confidence_outcomes.py plex_renamer\engine\_episode_resolution.py && .venv\Scripts\pyright.exe tests\episode_confidence_outcomes.py tests\test_episode_confidence_outcomes.py plex_renamer\engine\_episode_resolution.py`
Expected: no new/enlarged findings.

```powershell
git add docs/deferred-work.md
git commit -m "docs: close confidence calibration debt"
```
