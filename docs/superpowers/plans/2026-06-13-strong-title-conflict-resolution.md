# Strong-Title Conflict Auto-Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When one auto-assigned file claims an episode slot by exact title and another claims the same slot by bare release number, auto-resolve in favour of the exact-title file (the number-only loser becomes unassigned) instead of surfacing a hard conflict.

**Architecture:** A small helper in `_episode_resolution.py` scans `table.conflicts()` and, for any slot with exactly one exact-title (`title-agree`/`title-strong`) auto claimant and no other exact-title claimant, awards the slot via the existing `table.resolve_conflict(...)`. It is invoked at the start of `apply_confidence_adjustments`, so both scan pipelines benefit and the surviving winner still receives normal confidence floors. No data-model changes.

**Tech Stack:** Python 3, pytest. Windows + PowerShell. **Spec:** `docs/superpowers/specs/2026-06-13-strong-title-conflict-resolution-design.md`.

**Run tests with:** `python -m pytest <path> -v` from the repo root. Qt smoke uses `scripts/test-smoke.cmd`. Commits go through `scripts/git-publish.cmd` per `CLAUDE.md`.

---

## File Structure

- `plex_renamer/engine/_episode_resolution.py` — new module constant `_EXACT_TITLE_EVIDENCE`; new helper `_auto_resolve_strong_title_conflicts`; one call added at the top of `apply_confidence_adjustments` (Task 1).
- `tests/test_episode_resolution.py` — new `TestConflictResolution` class; reframe the comment on the existing `test_title_matching_own_number_is_not_overridden` fixture (Task 1).

---

## Task 1: Auto-resolve strong-title vs number-only conflicts

A number-only fallback claim must not collide with a confident exact-title claim for the same slot.
Add a helper that awards such conflicts to the exact-title claimant and unassigns the number-only loser.

**Files:**
- Modify: `plex_renamer/engine/_episode_resolution.py`
- Modify: `tests/test_episode_resolution.py` (`TestConflictResolution`, plus a comment fix)

- [ ] **Step 1: Write the failing tests**

In `tests/test_episode_resolution.py`, add `ORIGIN_MANUAL` and `REASON_LOST_CONFLICT` to the
`from plex_renamer.engine.episode_assignments import (...)` block (the one that already imports
`ORIGIN_AUTO`, `EpisodeAssignmentTable`, `EpisodeSlot`). Then append a new test class at the end of the
file:

```python
class TestConflictResolution:
    def _two_claimants(self, *, title_ev, num_ev, num_origin=ORIGIN_AUTO):
        table = EpisodeAssignmentTable()
        table.add_slot(EpisodeSlot(season=2, episode=10, title="Sibling Revile-ry"))
        title_file = table.add_file(
            Path("ATBG - S02E06 - Sibling Revile-ry.mkv"),
            raw_title="Sibling Revile-ry",
        )
        num_file = table.add_file(
            Path("ATBG - S02E10 - April's Fools.mkv"), is_season_relative=True,
        )
        table.assign(
            title_file.file_id, 2, [10], origin=ORIGIN_AUTO,
            confidence=CONF_TITLE_WINS, evidence=frozenset(title_ev),
        )
        table.assign(
            num_file.file_id, 2, [10], origin=num_origin,
            confidence=CONF_NUMBER_RELATIVE, evidence=frozenset(num_ev),
        )
        return table, title_file, num_file

    def test_exact_title_beats_number_only(self):
        table, title_file, num_file = self._two_claimants(
            title_ev={"title-strong", "number-disagree"},
            num_ev={"number", "season-relative"},
        )
        apply_confidence_adjustments(table, show_info=SHOW)
        assert table.assignment_for(title_file.file_id) is not None
        assert table.assignment_for(title_file.file_id).episodes == (10,)
        assert table.assignment_for(num_file.file_id) is None
        assert table.unassigned_reasons[num_file.file_id] == REASON_LOST_CONFLICT
        assert (2, 10) not in table.conflicts()

    def test_title_agree_also_wins(self):
        table, title_file, num_file = self._two_claimants(
            title_ev={"number", "title-agree"},
            num_ev={"number", "season-relative"},
        )
        apply_confidence_adjustments(table, show_info=SHOW)
        assert table.assignment_for(num_file.file_id) is None
        assert (2, 10) not in table.conflicts()

    def test_two_number_only_stays_conflict(self):
        table, title_file, num_file = self._two_claimants(
            title_ev={"number", "season-relative"},
            num_ev={"number", "season-relative"},
        )
        apply_confidence_adjustments(table, show_info=SHOW)
        assert (2, 10) in table.conflicts()

    def test_inexact_title_does_not_evict(self):
        table, title_file, num_file = self._two_claimants(
            title_ev={"title-strong-inexact", "number-disagree"},
            num_ev={"number", "season-relative"},
        )
        apply_confidence_adjustments(table, show_info=SHOW)
        assert (2, 10) in table.conflicts()

    def test_manual_claim_not_evicted(self):
        table, title_file, num_file = self._two_claimants(
            title_ev={"title-strong", "number-disagree"},
            num_ev={"number"}, num_origin=ORIGIN_MANUAL,
        )
        apply_confidence_adjustments(table, show_info=SHOW)
        assert (2, 10) in table.conflicts()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_episode_resolution.py::TestConflictResolution -v`
Expected: FAIL — `test_exact_title_beats_number_only`, `test_title_agree_also_wins` fail because the
conflict is NOT auto-resolved yet (`(2, 10)` stays in conflicts, the number file keeps its assignment).
The three "stays conflict" tests may pass vacuously now; they must still pass after the change.

- [ ] **Step 3: Add the evidence constant**

In `plex_renamer/engine/_episode_resolution.py`, in the post-resolution constants block (right after
`CONTRADICTORY_PREFIX_CAP = 0.45`), add:

```python
# Evidence tags that mark a claimant as an EXACT title match (rule 1 agree or
# rule 2 exact override). Used to auto-resolve a conflict in favour of the
# exact-title file over a weaker number-only claim. Excludes the substring
# rule-2b tag "title-strong-inexact" on purpose.
_EXACT_TITLE_EVIDENCE = frozenset({"title-agree", "title-strong"})
```

- [ ] **Step 4: Add the helper**

In `plex_renamer/engine/_episode_resolution.py`, add this function directly **before**
`def apply_confidence_adjustments(` (e.g. after `_expected_for_season`):

```python
def _auto_resolve_strong_title_conflicts(table: EpisodeAssignmentTable) -> None:
    """Award a conflicted slot to its sole exact-title claimant.

    When a slot is claimed by exactly one auto file with exact-title evidence
    (``title-agree``/``title-strong``) and the other claimants are weaker
    (number-only / no exact-title evidence), the exact-title file keeps the
    slot and the rest are marked ``REASON_LOST_CONFLICT``. Slots with no exact
    -title claimant, with two or more exact-title claimants, or with any manual
    claimant are left untouched for manual resolution.
    """
    for (season, episode), claims in list(table.conflicts().items()):
        if any(claim.origin == ORIGIN_MANUAL for claim in claims):
            continue
        winners = [claim for claim in claims if claim.evidence & _EXACT_TITLE_EVIDENCE]
        if len(winners) != 1:
            continue
        table.resolve_conflict(season, episode, winner_file_id=winners[0].file_id)
```

- [ ] **Step 5: Call it at the top of `apply_confidence_adjustments`**

In `plex_renamer/engine/_episode_resolution.py`, the function currently begins:

```python
def apply_confidence_adjustments(
    table: EpisodeAssignmentTable,
    *,
    show_info: dict,
    show_match_confidence: float | None = None,
) -> None:
    """Raise/cap auto-assignment confidence from corroborating evidence."""
    show_name = show_info.get("name", "")
```

Insert the resolution call as the first statement of the body (between the docstring and `show_name = ...`):

```python
    """Raise/cap auto-assignment confidence from corroborating evidence."""
    _auto_resolve_strong_title_conflicts(table)
    show_name = show_info.get("name", "")
```

- [ ] **Step 6: Run the resolution suite**

Run: `python -m pytest tests/test_episode_resolution.py -v`
Expected: ALL pass — the five new `TestConflictResolution` tests plus every pre-existing test.

- [ ] **Step 7: Fix the misleading As Told By Ginger comment**

In `tests/test_episode_resolution.py`, the existing `test_title_matching_own_number_is_not_overridden`
has a comment claiming the As Told By Ginger S02E06 episode is "Sibling Revile-ry". That is factually
wrong (real TMDB puts that title at S02E10). Replace that test's leading comment with a generic,
accurate one and keep the assertions unchanged:

```python
    def test_title_matching_own_number_is_not_overridden(self):
        # When a title matches its OWN parsed number it is rule-1 agreement,
        # NOT a rule-2b inexact override. (Generic principle guard; the real
        # As Told By Ginger S02E06 release is title-offset and handled by the
        # conflict-resolution path, not this rule.)
```

(Leave the body — `resolve_file(parsed_episodes=(6,), raw_title="Sibling Revile-ry", ...)` and its
assertions — exactly as-is.)

- [ ] **Step 8: Run the full resolution suite again**

Run: `python -m pytest tests/test_episode_resolution.py tests/test_tv_scanner_normal.py -q`
Expected: ALL pass.

- [ ] **Step 9: Commit**

```bash
git add plex_renamer/engine/_episode_resolution.py tests/test_episode_resolution.py
git commit -m "fix: auto-resolve exact-title vs number-only episode conflicts"
```

---

## Task 2: Full verification + real-folder sweep re-run

**Files:** none (verification only)

- [ ] **Step 1: Full Python suite**

Run: `python -m pytest -q`
Expected: all pass.

- [ ] **Step 2: Qt smoke**

Run: `scripts/test-smoke.cmd`
Expected: exit code 0; no failures.

- [ ] **Step 3: Real-folder sweep re-run**

Re-run the reproduction sweep (live TMDB + `P:\data\downloads\in progress files`) for the four shows and
confirm:
- **As Told By Ginger** Season 2: **no S02E10 conflict** — "Sibling Revile-ry" is OK on S02E10;
  "April's Fools" is unassigned/needs-manual.
- **Adventure Time** S0, **Animaniacs** Featurettes, **Tigtone** S01: results **unchanged** from the
  round-2 sweep (Adventure Time all OK; Animaniacs "The Writers Flipped" OK; Tigtone pilot → S00E01
  review, E02–E11 correct, no S01E10 conflict).

---

## Self-Review

**Spec coverage:** Auto-resolve helper (design "Mechanism") → Task 1 Steps 3-5. Safety guards (exactly
one exact-title claimant; exclude `title-strong-inexact`; never evict manual) → Task 1 Step 4 logic +
Steps 1 tests (`test_two_number_only_stays_conflict`, `test_inexact_title_does_not_evict`,
`test_manual_claim_not_evicted`). Locus/ordering at top of `apply_confidence_adjustments` → Step 5.
Comment fix → Step 7. Acceptance bullets + sweep → Task 1 tests + Task 2.

**Placeholder scan:** none — every code/run step shows complete content.

**Type/name consistency:** `_EXACT_TITLE_EVIDENCE` (Step 3) is used by `_auto_resolve_strong_title_conflicts`
(Step 4), which is called in `apply_confidence_adjustments` (Step 5). `ORIGIN_MANUAL` is already imported
in `_episode_resolution.py`; `ORIGIN_MANUAL`/`REASON_LOST_CONFLICT` are added to the test imports
(Step 1). `resolve_conflict(season, episode, winner_file_id=...)` matches the table's signature.
