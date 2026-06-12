# Episode Assignment Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace status-string-driven TV episode mapping with a first-class per-show `EpisodeAssignmentTable` (file↔episode claims with confidence and evidence), a single shared resolution policy for regular episodes and specials, and a bidirectional episode-fixing UI with a multi-select picker.

**Architecture:** The table is the source of truth inside the scan/preview layer; `PreviewItem`s become a projection of it, so the queue boundary (`build_rename_job_from_state` → `RenameOp`), job store, executor, and history are untouched. Scan paths resolve assignments through one policy module; the GUI mutates the table via `EpisodeMappingService` and reprojects.

**Tech Stack:** Python 3.12+, PySide6, pytest. Windows host — run commands in PowerShell. All new GUI sizing MUST go through `plex_renamer/gui_qt/_scale.py` (`px`, `row_height`, `icon`, `margins`); bare pixel literals are a review-blocking defect (HiDPI requirement from the spec).

**Spec:** `docs/superpowers/specs/2026-06-11-episode-assignment-redesign-design.md`

**Commits:** Use plain `git add <files>` + `git commit -m "..."` per task. Do NOT push; the user publishes via `scripts/git-publish.cmd` after review.

**Verification baseline:** Before Task 1, run `python -m pytest tests -x -q --ignore=tests/test_qt_main_window.py` and record the pass count. Every task must end with at least that many passing.

---

## File structure

New files:

| File | Responsibility |
| --- | --- |
| `plex_renamer/engine/episode_assignments.py` | `FileEntry`, `EpisodeSlot`, `Assignment` records; `EpisodeAssignmentTable` (operations, queries, validation, displacement, conflicts) |
| `plex_renamer/engine/_episode_resolution.py` | Title-strength matcher, the 6-rule resolution policy, ALL episode confidence calibration constants, table-based confidence floors/caps |
| `plex_renamer/engine/_episode_projection.py` | `project_preview_items(table, …)` — the only place episode status strings are minted |
| `plex_renamer/gui_qt/widgets/episode_assign_dialog.py` | `EpisodeAssignDialog.pick_episodes` (multi-select, contiguity-gated) and `EpisodeAssignDialog.pick_file` |
| `tests/test_episode_assignments.py` | Table unit tests |
| `tests/test_episode_resolution.py` | Policy + title matcher unit tests |
| `tests/test_episode_projection.py` | Projection unit tests + queue-parity integration test |

Modified files (each task lists exact ranges):

- `plex_renamer/_parsing_episodes.py` — multi-episode runs
- `plex_renamer/engine/models.py` — `PreviewItem.file_id`, `ScanState.assignments`, season-0 evidence
- `plex_renamer/engine/_tv_scanner_normal.py`, `_tv_scanner_specials.py`, `_tv_scanner.py`, `_tv_scanner_consolidated.py` — table-producing scan paths
- `plex_renamer/engine/_tv_scanner_postprocess.py` — shrinks to completeness reporting
- `plex_renamer/engine/_batch_tv_episode_claims.py` — sibling reconciliation merges tables
- `plex_renamer/engine/matching.py` — season-0 evidence in show scoring
- `plex_renamer/engine/__init__.py` — new exports
- `plex_renamer/app/controllers/_tv_state_helpers.py` — store table on state
- `plex_renamer/app/services/episode_mapping_service.py` — table-backed service ops
- `plex_renamer/app/models/state_models.py` — guide row actions metadata
- `plex_renamer/gui_qt/widgets/_workspace_widgets.py` — actions menu on guide rows
- `plex_renamer/gui_qt/widgets/_media_workspace_preview.py` — unassigned section, row wiring
- `plex_renamer/gui_qt/widgets/_media_workspace_actions.py` — action dispatch, dialog wiring

---

### Task 1: Parser — arbitrary multi-episode runs

**Files:**
- Modify: `plex_renamer/_parsing_episodes.py:27-49`
- Test: `tests/test_episode_resolution.py` (new file, parser section)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_episode_resolution.py`:

```python
"""Tests for episode parsing extensions and the resolution policy."""

from plex_renamer.parsing import extract_episode


class TestMultiEpisodeRuns:
    def test_three_episode_e_run(self):
        eps, title, rel = extract_episode("Show S01E01E02E03.mkv")
        assert eps == [1, 2, 3]
        assert rel is True

    def test_five_episode_e_run(self):
        eps, _, rel = extract_episode("Show S01E01E02E03E04E05.mkv")
        assert eps == [1, 2, 3, 4, 5]
        assert rel is True

    def test_sxx_exx_dash_range(self):
        eps, _, rel = extract_episode("Show S01E01-E04.mkv")
        assert eps == [1, 2, 3, 4]
        assert rel is True

    def test_sxx_exx_dash_range_bare_end(self):
        eps, _, rel = extract_episode("Show S01E01-04.mkv")
        assert eps == [1, 2, 3, 4]
        assert rel is True

    def test_xx_format_range(self):
        eps, _, rel = extract_episode("Show 1x01-1x04.mkv")
        assert eps == [1, 2, 3, 4]
        assert rel is True

    def test_range_span_cap_rejected(self):
        # Span > 12 is a parse artifact, not a real run: keep endpoints only.
        eps, _, _ = extract_episode("Show S01E01-E80.mkv")
        assert eps == [1, 80]

    def test_two_episode_format_unchanged(self):
        eps, title, rel = extract_episode("Show S01E01E02 - Pilot.mkv")
        assert eps == [1, 2]
        assert rel is True

    def test_single_episode_with_title_unchanged(self):
        eps, title, rel = extract_episode("Show S02E05 - The One.mkv")
        assert eps == [5]
        assert title == "The One"
        assert rel is True

    def test_resolution_number_not_an_episode(self):
        eps, _, _ = extract_episode("Show S01E01 1080p.mkv")
        assert eps == [1]
```

- [ ] **Step 2: Run to verify the new cases fail**

Run: `python -m pytest tests/test_episode_resolution.py -v`
Expected: `test_three_episode_e_run`, `test_five_episode_e_run`, range tests FAIL (lists truncated to 2 entries); the "unchanged" tests PASS.

- [ ] **Step 3: Implement**

In `plex_renamer/_parsing_episodes.py`, add a span cap constant at module level and replace the first two `match` blocks of `extract_episode` (the `S##E##` block at lines 27-37 and the `NxNN` block at lines 39-49):

```python
_MAX_RANGE_SPAN = 12


def _expand_range(start: int, end: int) -> list[int]:
    """Expand an inclusive episode range, capping absurd spans."""
    if end >= start and (end - start) <= _MAX_RANGE_SPAN:
        return list(range(start, end + 1))
    return [start, end]
```

```python
    match = re.search(
        r"S(\d+)((?:E\d+)+)(?:\s*-\s*E?(\d+))?\s*[-.]?\s*(.*)",
        name,
        re.IGNORECASE,
    )
    if match:
        episodes = [int(num) for num in re.findall(r"E(\d+)", match.group(2), re.IGNORECASE)]
        if match.group(3):
            episodes = _expand_range(episodes[0], int(match.group(3)))
        title = match.group(4).strip() if match.group(4) else None
        return episodes, title, True

    match = re.search(
        r"\b(\d{1,2})x(\d{2,3})(?:\s*-\s*(?:\1x)?(\d{2,3}))?(?!\d)\s*[-.]?\s*(.*)",
        name,
        re.IGNORECASE,
    )
    if match:
        start_num = int(match.group(2))
        if match.group(3):
            episodes = _expand_range(start_num, int(match.group(3)))
        else:
            episodes = [start_num]
        title = match.group(4).strip() if match.group(4) else None
        return episodes, title, True
```

Note the `S##E##` regex: `((?:E\d+)+)` consumes every chained `E##` token (covers `S01E01E02E03E04E05`), and the optional `-E##` / `-##` suffix triggers range expansion. The old `[E-]?E?(\d+)` two-episode form is subsumed: `S01E01E02` parses via the chained group; `S01E01-E04` parses via the range suffix.

`extract_season_number` (line 109) must accept the new shapes — update its first regex to `r"S(\d+)(?:E\d+)+"` and the `NxNN` one to `r"\b(\d{1,2})x\d{2,3}(?:\s*-\s*(?:\d{1,2}x)?\d{2,3})?(?!\d)"`.

- [ ] **Step 4: Run the parser tests and the full suite**

Run: `python -m pytest tests/test_episode_resolution.py tests/test_scan_improvements.py tests/test_haikyuu_matching.py tests/test_jojo_matching.py -v`
Expected: all PASS. If an existing test pinned the 2-episode truncation, update it to expect the full run (that truncation is the bug being fixed).

- [ ] **Step 5: Commit**

```powershell
git add plex_renamer/_parsing_episodes.py tests/test_episode_resolution.py
git commit -m "feat: parse arbitrary multi-episode runs and ranges"
```

---

### Task 2: EpisodeAssignmentTable — records and operations

**Files:**
- Create: `plex_renamer/engine/episode_assignments.py`
- Test: `tests/test_episode_assignments.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_episode_assignments.py`:

```python
"""Unit tests for the episode assignment table."""

from pathlib import Path

import pytest

from plex_renamer.engine.episode_assignments import (
    ORIGIN_AUTO,
    ORIGIN_MANUAL,
    REASON_DISPLACED,
    REASON_LOST_CONFLICT,
    ROLE_PRIMARY,
    EpisodeAssignmentTable,
    EpisodeSlot,
)


def make_table() -> EpisodeAssignmentTable:
    table = EpisodeAssignmentTable()
    for episode in range(1, 6):
        table.add_slot(EpisodeSlot(season=1, episode=episode, title=f"Ep {episode}"))
    table.add_slot(EpisodeSlot(season=0, episode=1, title="Special A"))
    table.add_slot(EpisodeSlot(season=0, episode=2, title="Special B"))
    return table


class TestFileAndSlotRegistration:
    def test_add_file_assigns_sequential_ids(self):
        table = make_table()
        a = table.add_file(Path("a.mkv"))
        b = table.add_file(Path("b.mkv"))
        assert (a.file_id, b.file_id) == (0, 1)

    def test_new_file_is_unassigned_without_reason(self):
        table = make_table()
        entry = table.add_file(Path("a.mkv"))
        assert table.assignment_for(entry.file_id) is None


class TestAssignValidation:
    def test_assign_single_episode(self):
        table = make_table()
        entry = table.add_file(Path("a.mkv"))
        assignment = table.assign(
            entry.file_id, 1, [3], origin=ORIGIN_AUTO, confidence=0.9,
        )
        assert assignment.episodes == (3,)
        assert assignment.role == ROLE_PRIMARY

    def test_assign_contiguous_run(self):
        table = make_table()
        entry = table.add_file(Path("a.mkv"))
        assignment = table.assign(
            entry.file_id, 1, [1, 2, 3], origin=ORIGIN_MANUAL,
        )
        assert assignment.episodes == (1, 2, 3)
        assert assignment.confidence == 1.0

    def test_non_contiguous_rejected(self):
        table = make_table()
        entry = table.add_file(Path("a.mkv"))
        with pytest.raises(ValueError):
            table.assign(entry.file_id, 1, [1, 3], origin=ORIGIN_MANUAL)

    def test_unknown_slot_rejected(self):
        table = make_table()
        entry = table.add_file(Path("a.mkv"))
        with pytest.raises(ValueError):
            table.assign(entry.file_id, 1, [99], origin=ORIGIN_MANUAL)

    def test_unknown_file_rejected(self):
        table = make_table()
        with pytest.raises(ValueError):
            table.assign(42, 1, [1], origin=ORIGIN_MANUAL)

    def test_empty_episodes_rejected(self):
        table = make_table()
        entry = table.add_file(Path("a.mkv"))
        with pytest.raises(ValueError):
            table.assign(entry.file_id, 1, [], origin=ORIGIN_MANUAL)

    def test_failed_assign_leaves_table_unchanged(self):
        table = make_table()
        entry = table.add_file(Path("a.mkv"))
        table.assign(entry.file_id, 1, [2], origin=ORIGIN_AUTO, confidence=0.9)
        with pytest.raises(ValueError):
            table.assign(entry.file_id, 1, [4, 6], origin=ORIGIN_MANUAL)
        existing = table.assignment_for(entry.file_id)
        assert existing is not None and existing.episodes == (2,)


class TestConflictsAndDisplacement:
    def test_auto_claims_accumulate_as_conflict(self):
        table = make_table()
        a = table.add_file(Path("a.mkv"))
        b = table.add_file(Path("b.mkv"))
        table.assign(a.file_id, 1, [2], origin=ORIGIN_AUTO, confidence=0.9)
        table.assign(b.file_id, 1, [2], origin=ORIGIN_AUTO, confidence=0.8)
        assert (1, 2) in table.conflicts()
        assert {item.file_id for item in table.claims(1, 2)} == {a.file_id, b.file_id}
        assert table.claimant(1, 2) is None  # ambiguous while conflicted

    def test_manual_assign_displaces(self):
        table = make_table()
        a = table.add_file(Path("a.mkv"))
        b = table.add_file(Path("b.mkv"))
        table.assign(a.file_id, 1, [2], origin=ORIGIN_AUTO, confidence=0.9)
        table.assign(b.file_id, 1, [2], origin=ORIGIN_MANUAL, displace=True)
        assert table.assignment_for(a.file_id) is None
        assert table.unassigned_reasons[a.file_id] == REASON_DISPLACED
        assert table.claimant(1, 2).file_id == b.file_id

    def test_resolve_conflict_keeps_winner(self):
        table = make_table()
        a = table.add_file(Path("a.mkv"))
        b = table.add_file(Path("b.mkv"))
        table.assign(a.file_id, 1, [2], origin=ORIGIN_AUTO, confidence=0.9)
        table.assign(b.file_id, 1, [2], origin=ORIGIN_AUTO, confidence=0.8)
        table.resolve_conflict(1, 2, winner_file_id=a.file_id)
        assert table.conflicts() == {}
        assert table.claimant(1, 2).file_id == a.file_id
        assert table.unassigned_reasons[b.file_id] == REASON_LOST_CONFLICT


class TestQueries:
    def test_unclaimed_slots(self):
        table = make_table()
        entry = table.add_file(Path("a.mkv"))
        table.assign(entry.file_id, 1, [1, 2], origin=ORIGIN_AUTO, confidence=0.9)
        unclaimed = {slot.key for slot in table.unclaimed_slots()}
        assert unclaimed == {(1, 3), (1, 4), (1, 5), (0, 1), (0, 2)}

    def test_unassigned_files_with_reason(self):
        table = make_table()
        entry = table.add_file(Path("a.mkv"))
        table.mark_unassigned(entry.file_id, "could not parse episode number")
        files = table.unassigned_files()
        assert files == [(entry, "could not parse episode number")]

    def test_unassign_clears_claims(self):
        table = make_table()
        entry = table.add_file(Path("a.mkv"))
        table.assign(entry.file_id, 1, [1], origin=ORIGIN_MANUAL)
        table.unassign(entry.file_id, reason="manually unassigned")
        assert table.claimant(1, 1) is None
        assert table.assignment_for(entry.file_id) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_episode_assignments.py -v`
Expected: FAIL with `ModuleNotFoundError: plex_renamer.engine.episode_assignments`

- [ ] **Step 3: Implement the module**

Create `plex_renamer/engine/episode_assignments.py`:

```python
"""First-class file<->episode assignment table for TV scans.

The table is the source of truth for the scan/preview layer. ``PreviewItem``
rows are projected from it (see ``_episode_projection``); nothing outside the
projection mints episode status strings.

Claims are stored per file but queried per slot as a *list*: policy, not
schema, decides what multiple claims on one slot mean. Today 2+ claims is a
conflict; a future duplicates policy may treat extra claims as Plex
"versions" via ``Assignment.role`` without a data migration.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

ORIGIN_AUTO = "auto"
ORIGIN_MANUAL = "manual"
ROLE_PRIMARY = "primary"
ROLE_VERSION = "version"  # reserved for future duplicate support

REASON_NO_PARSE = "could not parse episode number"
REASON_NO_TITLE_MATCH = "no TMDB title match"
REASON_NOT_IN_SEASON = "episode not in TMDB season"
REASON_LOST_CONFLICT = "lost conflict"
REASON_DISPLACED = "reassigned to another file"
REASON_MANUAL_UNASSIGN = "manually unassigned"


@dataclass(frozen=True, slots=True)
class EpisodeSlot:
    """One TMDB episode (including Season 0 specials)."""

    season: int
    episode: int
    title: str = ""
    air_date: str = ""
    overview: str = ""

    @property
    def key(self) -> tuple[int, int]:
        return (self.season, self.episode)


@dataclass(slots=True)
class FileEntry:
    """One discovered video file with its scan-time parse evidence.

    Evidence fields are written once at scan time and never mutated by
    fixes; manual operations only change the file's ``Assignment``.
    """

    file_id: int
    path: Path
    parsed_episodes: tuple[int, ...] = ()
    raw_title: str | None = None
    is_season_relative: bool = False
    season_hint: int | None = None
    folder_season: int | None = None
    from_extras_folder: bool = False
    source_relative_folder: str = ""


@dataclass(slots=True)
class Assignment:
    """Links one file to 1..N contiguous episodes in a single season."""

    file_id: int
    season: int
    episodes: tuple[int, ...]
    origin: str
    confidence: float
    role: str = ROLE_PRIMARY
    evidence: frozenset[str] = field(default_factory=frozenset)
    approved: bool = False


class EpisodeAssignmentTable:
    """Per-show registry of files, episode slots, and claims."""

    def __init__(self) -> None:
        self.files: dict[int, FileEntry] = {}
        self.slots: dict[tuple[int, int], EpisodeSlot] = {}
        self.unassigned_reasons: dict[int, str] = {}
        self._assignments: dict[int, Assignment] = {}
        self._next_file_id = 0

    # ── registration ────────────────────────────────────────────────

    def add_slot(self, slot: EpisodeSlot) -> None:
        self.slots[slot.key] = slot

    def add_file(self, path: Path, **evidence) -> FileEntry:
        entry = FileEntry(file_id=self._next_file_id, path=path, **evidence)
        self.files[entry.file_id] = entry
        self._next_file_id += 1
        return entry

    # ── mutations ───────────────────────────────────────────────────

    def assign(
        self,
        file_id: int,
        season: int,
        episodes: list[int] | tuple[int, ...],
        *,
        origin: str,
        confidence: float = 1.0,
        evidence: frozenset[str] = frozenset(),
        displace: bool = False,
    ) -> Assignment:
        """Validate and record an assignment. Raises ValueError untouched on bad input."""
        entry = self.files.get(file_id)
        if entry is None:
            raise ValueError(f"Unknown file id {file_id}")
        episode_run = tuple(sorted(int(episode) for episode in episodes))
        if not episode_run:
            raise ValueError("An assignment needs at least one episode")
        if any(b - a != 1 for a, b in zip(episode_run, episode_run[1:])):
            raise ValueError(
                f"Episodes {list(episode_run)} are not a contiguous run"
            )
        missing = [e for e in episode_run if (season, e) not in self.slots]
        if missing:
            raise ValueError(
                f"Season {season} has no episode(s) {missing} in TMDB"
            )

        if displace:
            for other_id in [
                claim.file_id
                for episode in episode_run
                for claim in self.claims(season, episode)
                if claim.file_id != file_id
            ]:
                self._assignments.pop(other_id, None)
                self.unassigned_reasons[other_id] = REASON_DISPLACED

        if origin == ORIGIN_MANUAL:
            confidence = 1.0
        assignment = Assignment(
            file_id=file_id,
            season=season,
            episodes=episode_run,
            origin=origin,
            confidence=confidence,
            evidence=evidence,
        )
        self._assignments[file_id] = assignment
        self.unassigned_reasons.pop(file_id, None)
        return assignment

    def mark_unassigned(self, file_id: int, reason: str) -> None:
        if file_id not in self.files:
            raise ValueError(f"Unknown file id {file_id}")
        self._assignments.pop(file_id, None)
        self.unassigned_reasons[file_id] = reason

    def unassign(self, file_id: int, *, reason: str = REASON_MANUAL_UNASSIGN) -> None:
        self.mark_unassigned(file_id, reason)

    def resolve_conflict(self, season: int, episode: int, *, winner_file_id: int) -> None:
        claimants = self.claims(season, episode)
        if all(claim.file_id != winner_file_id for claim in claimants):
            raise ValueError(
                f"File {winner_file_id} does not claim S{season:02d}E{episode:02d}"
            )
        for claim in claimants:
            if claim.file_id != winner_file_id:
                self.mark_unassigned(claim.file_id, REASON_LOST_CONFLICT)

    def set_approved(self, file_id: int, approved: bool = True) -> None:
        assignment = self._assignments.get(file_id)
        if assignment is None:
            raise ValueError(f"File {file_id} has no assignment to approve")
        self._assignments[file_id] = replace(assignment, approved=approved)

    def set_confidence(self, file_id: int, confidence: float) -> None:
        assignment = self._assignments.get(file_id)
        if assignment is None:
            raise ValueError(f"File {file_id} has no assignment")
        clamped = max(0.0, min(1.0, confidence))
        self._assignments[file_id] = replace(assignment, confidence=clamped)

    # ── queries ─────────────────────────────────────────────────────

    def assignment_for(self, file_id: int) -> Assignment | None:
        return self._assignments.get(file_id)

    def assignments(self) -> list[Assignment]:
        return list(self._assignments.values())

    def claims(self, season: int, episode: int) -> list[Assignment]:
        return [
            assignment
            for assignment in self._assignments.values()
            if assignment.season == season and episode in assignment.episodes
        ]

    def conflicts(self) -> dict[tuple[int, int], list[Assignment]]:
        by_slot: dict[tuple[int, int], list[Assignment]] = {}
        for assignment in self._assignments.values():
            for episode in assignment.episodes:
                by_slot.setdefault((assignment.season, episode), []).append(assignment)
        return {key: claims for key, claims in by_slot.items() if len(claims) > 1}

    def conflicted_file_ids(self) -> set[int]:
        return {
            claim.file_id
            for claims in self.conflicts().values()
            for claim in claims
        }

    def claimant(self, season: int, episode: int) -> FileEntry | None:
        claims = self.claims(season, episode)
        if len(claims) != 1:
            return None
        return self.files[claims[0].file_id]

    def unassigned_files(self) -> list[tuple[FileEntry, str]]:
        return [
            (entry, self.unassigned_reasons.get(file_id, ""))
            for file_id, entry in sorted(self.files.items())
            if file_id not in self._assignments
        ]

    def unclaimed_slots(self) -> list[EpisodeSlot]:
        claimed: set[tuple[int, int]] = set()
        for assignment in self._assignments.values():
            for episode in assignment.episodes:
                claimed.add((assignment.season, episode))
        return [
            slot for key, slot in sorted(self.slots.items()) if key not in claimed
        ]
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_episode_assignments.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```powershell
git add plex_renamer/engine/episode_assignments.py tests/test_episode_assignments.py
git commit -m "feat: add EpisodeAssignmentTable with claims, conflicts, displacement"
```

---

### Task 3: Resolution policy and title-strength matcher

**Files:**
- Create: `plex_renamer/engine/_episode_resolution.py`
- Test: `tests/test_episode_resolution.py` (extend)

- [ ] **Step 1: Write the failing tests** (append to `tests/test_episode_resolution.py`)

```python
from plex_renamer.engine._episode_resolution import (
    CONF_AGREE,
    CONF_NUMBER_INFERRED,
    CONF_NUMBER_RELATIVE,
    CONF_TITLE_ONLY,
    CONF_TITLE_WINS,
    CONF_WEAK_TITLE_NUMBER_CAP,
    STRONG_TITLE_STRENGTH,
    match_title_in_titles,
    resolve_file,
)

S0_TITLES = {1: "Inauguration Part 1", 2: "Special A", 3: "Special C"}
S1_TITLES = {1: "Pilot", 2: "The Heist", 3: "Endgame", 4: "Coda"}


class TestTitleStrength:
    def test_exact_normalized_match_is_full_strength(self):
        match = match_title_in_titles("Special A", S0_TITLES)
        assert match is not None
        assert match.episode == 2
        assert match.strength == 1.0

    def test_unique_substring_is_strong(self):
        match = match_title_in_titles("The Heist 720p extended", S1_TITLES)
        assert match is not None
        assert match.episode == 2
        assert match.strength >= STRONG_TITLE_STRENGTH

    def test_ambiguous_returns_none(self):
        titles = {1: "Part 1", 2: "Part 2"}
        assert match_title_in_titles("Part", titles) is None

    def test_no_match_returns_none(self):
        assert match_title_in_titles("Completely Unrelated", S1_TITLES) is None


class TestResolutionRules:
    def test_rule1_number_and_title_agree(self):
        res = resolve_file(
            parsed_episodes=(2,), raw_title="The Heist",
            is_season_relative=True, season_titles=S1_TITLES,
        )
        assert res.episodes == (2,)
        assert res.confidence >= CONF_AGREE
        assert res.reason is None

    def test_rule2_strong_title_beats_number(self):
        # The user-reported case: s00e03 named "Special A" must map to e02.
        res = resolve_file(
            parsed_episodes=(3,), raw_title="Special A",
            is_season_relative=True, season_titles=S0_TITLES,
        )
        assert res.episodes == (2,)
        assert res.confidence == CONF_TITLE_WINS

    def test_rule3_weak_title_keeps_number_capped(self):
        # Title fuzzy-misses; the valid number wins but lands in review range.
        res = resolve_file(
            parsed_episodes=(3,), raw_title="Endgame Part",
            is_season_relative=True,
            season_titles={1: "Pilot", 2: "Endgame Part One", 3: "Endgame Part Two"},
        )
        assert res.episodes == (3,)
        assert res.confidence <= CONF_WEAK_TITLE_NUMBER_CAP

    def test_rule4_number_only_relative(self):
        res = resolve_file(
            parsed_episodes=(4,), raw_title=None,
            is_season_relative=True, season_titles=S1_TITLES,
        )
        assert res.episodes == (4,)
        assert res.confidence == CONF_NUMBER_RELATIVE

    def test_rule4_number_only_inferred(self):
        res = resolve_file(
            parsed_episodes=(4,), raw_title=None,
            is_season_relative=False, season_titles=S1_TITLES,
        )
        assert res.episodes == (4,)
        assert res.confidence == CONF_NUMBER_INFERRED

    def test_rule5_title_only_strong(self):
        res = resolve_file(
            parsed_episodes=(), raw_title="Endgame",
            is_season_relative=False, season_titles=S1_TITLES,
        )
        assert res.episodes == (3,)
        assert res.confidence == CONF_TITLE_ONLY

    def test_rule5_title_only_weak_is_unassigned(self):
        res = resolve_file(
            parsed_episodes=(), raw_title="Bloopers Reel",
            is_season_relative=False, season_titles=S1_TITLES,
        )
        assert res.episodes == ()
        assert res.reason == "no TMDB title match"

    def test_rule6_nothing_is_unassigned(self):
        res = resolve_file(
            parsed_episodes=(), raw_title=None,
            is_season_relative=False, season_titles=S1_TITLES,
        )
        assert res.episodes == ()
        assert res.reason == "could not parse episode number"

    def test_number_not_in_season_is_unassigned(self):
        res = resolve_file(
            parsed_episodes=(99,), raw_title=None,
            is_season_relative=True, season_titles=S1_TITLES,
        )
        assert res.episodes == ()
        assert res.reason == "episode not in TMDB season"

    def test_multi_episode_run_validated(self):
        res = resolve_file(
            parsed_episodes=(1, 2, 3), raw_title=None,
            is_season_relative=True, season_titles=S1_TITLES,
        )
        assert res.episodes == (1, 2, 3)
        assert res.confidence == CONF_NUMBER_RELATIVE
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_episode_resolution.py -v`
Expected: FAIL with `ModuleNotFoundError` / `ImportError` on `_episode_resolution`.

- [ ] **Step 3: Implement**

Create `plex_renamer/engine/_episode_resolution.py`:

```python
"""Shared episode resolution policy and confidence calibration.

ALL episode-level confidence constants live here. Tweak values in one
place; see docs/superpowers/specs/2026-06-11-episode-assignment-redesign-design.md.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..parsing import normalize_for_specials
from .episode_assignments import (
    REASON_NO_PARSE,
    REASON_NO_TITLE_MATCH,
    REASON_NOT_IN_SEASON,
)

# ── calibration constants ───────────────────────────────────────────
STRONG_TITLE_STRENGTH = 0.85
CONF_AGREE = 0.96            # rule 1: number and title agree
CONF_TITLE_WINS = 0.90       # rule 2: strong title overrides number
CONF_WEAK_TITLE_NUMBER_CAP = 0.60   # rule 3: weak title disagreement caps number
CONF_NUMBER_RELATIVE = 0.86  # rule 4: S##E## number only
CONF_NUMBER_INFERRED = 0.50  # rule 4: bare/absolute number only
CONF_TITLE_ONLY = 0.88       # rule 5: strong title, no usable number

_TITLE_EXACT = 1.0
_TITLE_SUBSTRING = 0.90
_TITLE_PART_NUMBER = 0.80
_MIN_SUBSTRING_LEN = 6


@dataclass(frozen=True, slots=True)
class TitleMatch:
    episode: int
    title: str
    strength: float


@dataclass(frozen=True, slots=True)
class Resolution:
    """Outcome of resolving one file against one season's titles.

    ``episodes`` empty means unassigned; ``reason`` says why.
    """

    episodes: tuple[int, ...]
    confidence: float = 0.0
    evidence: frozenset[str] = frozenset()
    reason: str | None = None


def _strip_part_number(normalized: str) -> tuple[str, str]:
    import re

    match = re.search(r"\d{1,2}", normalized)
    if match:
        return normalized[: match.start()] + normalized[match.end():], match.group()
    return normalized, ""


def match_title_in_titles(
    raw_text: str | None,
    titles: dict[int, str],
) -> TitleMatch | None:
    """Fuzzy-match *raw_text* against episode titles, with a strength score.

    Strength: 1.0 exact normalized, 0.90 unique substring, 0.80 unique
    part-number base match. Ambiguous (2+ candidates) returns None.
    """
    if not raw_text or not titles:
        return None
    normalized = normalize_for_specials(raw_text)
    if not normalized:
        return None

    lookup = {
        normalize_for_specials(title): (episode, title)
        for episode, title in titles.items()
        if normalize_for_specials(title)
    }

    hit = lookup.get(normalized)
    if hit is not None:
        return TitleMatch(episode=hit[0], title=hit[1], strength=_TITLE_EXACT)

    if len(normalized) >= _MIN_SUBSTRING_LEN:
        substring_hits = [
            (episode, title)
            for key, (episode, title) in lookup.items()
            if len(key) >= _MIN_SUBSTRING_LEN
            and (normalized in key or key in normalized)
        ]
        if len(substring_hits) == 1:
            episode, title = substring_hits[0]
            return TitleMatch(episode=episode, title=title, strength=_TITLE_SUBSTRING)
        if len(substring_hits) > 1:
            return None

    input_base, input_part = _strip_part_number(normalized)
    if input_base:
        base_hits = [
            (episode, title, key_part)
            for key, (episode, title) in lookup.items()
            for key_base, key_part in [_strip_part_number(key)]
            if key_base == input_base
        ]
        if len(base_hits) == 1:
            episode, title, _ = base_hits[0]
            return TitleMatch(episode=episode, title=title, strength=_TITLE_PART_NUMBER)
        if input_part and len(base_hits) > 1:
            by_part = [
                (episode, title)
                for episode, title, key_part in base_hits
                if key_part == input_part
            ]
            if len(by_part) == 1:
                episode, title = by_part[0]
                return TitleMatch(
                    episode=episode, title=title, strength=_TITLE_PART_NUMBER,
                )

    return None


def resolve_file(
    *,
    parsed_episodes: tuple[int, ...],
    raw_title: str | None,
    is_season_relative: bool,
    season_titles: dict[int, str],
) -> Resolution:
    """Apply the 6-rule resolution policy for one file against one season."""
    valid_numbers = tuple(e for e in parsed_episodes if e in season_titles)
    title_match = match_title_in_titles(raw_title, season_titles)
    strong_title = (
        title_match is not None and title_match.strength >= STRONG_TITLE_STRENGTH
    )

    if valid_numbers and title_match is not None:
        if title_match.episode in valid_numbers:
            return Resolution(  # rule 1
                episodes=valid_numbers,
                confidence=CONF_AGREE,
                evidence=frozenset({"number", "title-agree"}),
            )
        if strong_title:
            return Resolution(  # rule 2
                episodes=(title_match.episode,),
                confidence=CONF_TITLE_WINS,
                evidence=frozenset({"title-strong", "number-disagree"}),
            )
        return Resolution(  # rule 3
            episodes=valid_numbers,
            confidence=CONF_WEAK_TITLE_NUMBER_CAP,
            evidence=frozenset({"number", "title-weak-disagree"}),
        )

    if valid_numbers:  # rule 4
        confidence = CONF_NUMBER_RELATIVE if is_season_relative else CONF_NUMBER_INFERRED
        evidence = {"number"}
        if is_season_relative:
            evidence.add("season-relative")
        return Resolution(
            episodes=valid_numbers,
            confidence=confidence,
            evidence=frozenset(evidence),
        )

    if title_match is not None and strong_title:  # rule 5
        return Resolution(
            episodes=(title_match.episode,),
            confidence=CONF_TITLE_ONLY,
            evidence=frozenset({"title-strong"}),
        )

    if parsed_episodes:
        return Resolution(episodes=(), reason=REASON_NOT_IN_SEASON)
    if raw_title:
        return Resolution(episodes=(), reason=REASON_NO_TITLE_MATCH)
    return Resolution(episodes=(), reason=REASON_NO_PARSE)
```

(Move the `import re` to the top of the file with the other imports — shown inline above only for locality.)

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_episode_resolution.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```powershell
git add plex_renamer/engine/_episode_resolution.py tests/test_episode_resolution.py
git commit -m "feat: shared 6-rule episode resolution policy with title strength"
```

---

### Task 4: Projection — table to PreviewItems

**Files:**
- Modify: `plex_renamer/engine/models.py:63-76` (add `file_id` to `PreviewItem`)
- Create: `plex_renamer/engine/_episode_projection.py`
- Test: `tests/test_episode_projection.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_episode_projection.py`:

```python
"""Projection tests: assignment table -> PreviewItem rows."""

from pathlib import Path

from plex_renamer.engine.episode_assignments import (
    ORIGIN_AUTO,
    ORIGIN_MANUAL,
    REASON_NO_PARSE,
    REASON_NO_TITLE_MATCH,
    EpisodeAssignmentTable,
    EpisodeSlot,
)
from plex_renamer.engine._episode_projection import project_preview_items

SHOW_INFO = {"id": 99, "name": "Demo Show", "year": "2020"}
MEDIA_FIELDS = {"media_id": 99, "media_name": "Demo Show"}
ROOT = Path("C:/lib/Demo Show (2020)")


def make_table() -> EpisodeAssignmentTable:
    table = EpisodeAssignmentTable()
    for episode, title in [(1, "Pilot"), (2, "The Heist"), (3, "Endgame")]:
        table.add_slot(EpisodeSlot(season=1, episode=episode, title=title))
    table.add_slot(EpisodeSlot(season=0, episode=1, title="Special A"))
    return table


def project(table):
    return project_preview_items(
        table, show_info=SHOW_INFO, root=ROOT, media_fields=MEDIA_FIELDS,
    )


class TestProjection:
    def test_assigned_file_gets_rename(self):
        table = make_table()
        entry = table.add_file(ROOT / "src" / "demo.s01e01.mkv")
        table.assign(entry.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=0.96)
        items = project(table)
        assert len(items) == 1
        item = items[0]
        assert item.file_id == entry.file_id
        assert item.status == "OK"
        assert item.season == 1 and item.episodes == [1]
        assert item.new_name == "Demo Show (2020) - S01E01 - Pilot.mkv"
        assert item.target_dir == ROOT / "Season 01"
        assert item.episode_confidence == 0.96

    def test_multi_episode_name(self):
        table = make_table()
        entry = table.add_file(ROOT / "demo.s01e01-e03.mkv")
        table.assign(entry.file_id, 1, [1, 2, 3], origin=ORIGIN_MANUAL)
        items = project(table)
        assert items[0].episodes == [1, 2, 3]
        assert "S01E01-E03" in items[0].new_name

    def test_specials_target_dir(self):
        table = make_table()
        entry = table.add_file(ROOT / "Specials" / "special a.mkv")
        table.assign(entry.file_id, 0, [1], origin=ORIGIN_AUTO, confidence=0.9)
        items = project(table)
        assert items[0].target_dir == ROOT / "Season 00"

    def test_low_confidence_is_review(self):
        table = make_table()
        entry = table.add_file(ROOT / "demo 3.mkv")
        table.assign(entry.file_id, 1, [3], origin=ORIGIN_AUTO, confidence=0.5)
        items = project(table)
        assert items[0].is_episode_review

    def test_approved_review_is_ok(self):
        table = make_table()
        entry = table.add_file(ROOT / "demo 3.mkv")
        table.assign(entry.file_id, 1, [3], origin=ORIGIN_AUTO, confidence=0.5)
        table.set_approved(entry.file_id)
        items = project(table)
        assert items[0].status == "OK"

    def test_manual_is_never_review(self):
        table = make_table()
        entry = table.add_file(ROOT / "demo 3.mkv")
        table.assign(entry.file_id, 1, [3], origin=ORIGIN_MANUAL)
        items = project(table)
        assert items[0].status == "OK"
        assert items[0].episode_confidence == 1.0

    def test_conflict_rows(self):
        table = make_table()
        a = table.add_file(ROOT / "Season 1" / "x.mkv")
        b = table.add_file(ROOT / "Season 2" / "x.mkv")
        table.assign(a.file_id, 0, [1], origin=ORIGIN_AUTO, confidence=0.9)
        table.assign(b.file_id, 0, [1], origin=ORIGIN_AUTO, confidence=0.9)
        items = project(table)
        assert all(item.is_conflict for item in items)
        assert "S00E01" in items[0].status

    def test_unassigned_no_parse(self):
        table = make_table()
        entry = table.add_file(ROOT / "junk.mkv")
        table.mark_unassigned(entry.file_id, REASON_NO_PARSE)
        items = project(table)
        assert items[0].new_name is None
        assert items[0].status == "SKIP: could not parse episode number"

    def test_unassigned_special_is_unmatched_not_silent_ok(self):
        table = make_table()
        entry = table.add_file(
            ROOT / "Specials" / "mystery.mkv", folder_season=0,
        )
        table.mark_unassigned(entry.file_id, REASON_NO_TITLE_MATCH)
        items = project(table)
        assert items[0].is_unmatched
        assert not items[0].is_actionable

    def test_unassigned_extras_file_moves_to_unmatched(self):
        table = make_table()
        entry = table.add_file(
            ROOT / "Season 1" / "Extras" / "bts.mkv",
            folder_season=0, from_extras_folder=True,
        )
        table.mark_unassigned(entry.file_id, REASON_NO_TITLE_MATCH)
        items = project(table)
        assert items[0].is_unmatched
        assert items[0].new_name == "bts.mkv"
        assert items[0].target_dir == ROOT / "Unmatched" / "Extras"

    def test_every_file_yields_exactly_one_item(self):
        table = make_table()
        a = table.add_file(ROOT / "a.mkv")
        b = table.add_file(ROOT / "b.mkv")
        table.assign(a.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=0.9)
        table.mark_unassigned(b.file_id, REASON_NO_PARSE)
        items = project(table)
        assert {item.file_id for item in items} == {a.file_id, b.file_id}

    def test_ordering_by_season_episode_then_unassigned(self):
        table = make_table()
        unparsed = table.add_file(ROOT / "zzz.mkv")
        ep2 = table.add_file(ROOT / "e2.mkv")
        ep1 = table.add_file(ROOT / "e1.mkv")
        table.mark_unassigned(unparsed.file_id, REASON_NO_PARSE)
        table.assign(ep2.file_id, 1, [2], origin=ORIGIN_AUTO, confidence=0.9)
        table.assign(ep1.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=0.9)
        items = project(table)
        assert [item.file_id for item in items] == [
            ep1.file_id, ep2.file_id, unparsed.file_id,
        ]
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_episode_projection.py -v`
Expected: FAIL (`ModuleNotFoundError` on `_episode_projection`).

- [ ] **Step 3: Implement**

First, in `plex_renamer/engine/models.py`, add the projection link field to `PreviewItem` directly under `source_relative_folder: str = ""` (line 76):

```python
    file_id: int | None = None   # Link back to EpisodeAssignmentTable.files
```

Then create `plex_renamer/engine/_episode_projection.py`:

```python
"""Project an EpisodeAssignmentTable into PreviewItem rows.

This is the ONLY place episode preview status strings are minted.
"""

from __future__ import annotations

from pathlib import Path

from ..parsing import build_tv_name
from ._movie_scanner import _build_subtitle_companions
from ._state import get_episode_auto_accept_threshold
from .episode_assignments import (
    ORIGIN_MANUAL,
    REASON_NO_PARSE,
    REASON_NO_TITLE_MATCH,
    EpisodeAssignmentTable,
    FileEntry,
)
from .models import EPISODE_REVIEW_STATUS_PREFIX, PreviewItem

_UNASSIGNED_STATUS = {
    REASON_NO_PARSE: "SKIP: could not parse episode number",
}


def _season_dir_name(season: int) -> str:
    return f"Season {season:02d}"


def _conflict_status(season: int, episode: int, other: FileEntry) -> str:
    other_source = other.source_relative_folder or other.path.parent.name
    return (
        f"CONFLICT: duplicate episode claim S{season:02d}E{episode:02d} "
        f"also claimed by {other_source}"
    )


def _unassigned_item(
    entry: FileEntry,
    reason: str,
    root: Path,
    media_fields: dict,
) -> PreviewItem:
    if entry.folder_season == 0 and reason == REASON_NO_TITLE_MATCH:
        if entry.from_extras_folder:
            return PreviewItem(
                original=entry.path,
                new_name=entry.path.name,
                target_dir=root / "Unmatched" / entry.path.parent.name,
                season=0,
                episodes=list(entry.parsed_episodes),
                status="UNMATCHED: no TMDB special found - moving to Unmatched",
                file_id=entry.file_id,
                source_relative_folder=entry.source_relative_folder,
                **media_fields,
            )
        return PreviewItem(
            original=entry.path,
            new_name=None,
            target_dir=None,
            season=0,
            episodes=list(entry.parsed_episodes),
            status="UNMATCHED: no TMDB special title match",
            file_id=entry.file_id,
            source_relative_folder=entry.source_relative_folder,
            **media_fields,
        )

    status = _UNASSIGNED_STATUS.get(reason, f"SKIP: {reason}")
    return PreviewItem(
        original=entry.path,
        new_name=None,
        target_dir=None,
        season=entry.folder_season,
        episodes=list(entry.parsed_episodes),
        status=status,
        file_id=entry.file_id,
        source_relative_folder=entry.source_relative_folder,
        **media_fields,
    )


def project_preview_items(
    table: EpisodeAssignmentTable,
    *,
    show_info: dict,
    root: Path,
    media_fields: dict,
) -> list[PreviewItem]:
    """Produce exactly one PreviewItem per FileEntry, in guide order."""
    threshold = get_episode_auto_accept_threshold()
    conflicted = table.conflicted_file_ids()
    items: list[PreviewItem] = []

    for file_id, entry in table.files.items():
        assignment = table.assignment_for(file_id)
        if assignment is None:
            reason = table.unassigned_reasons.get(file_id, "")
            items.append(_unassigned_item(entry, reason, root, media_fields))
            continue

        season = assignment.season
        episodes = list(assignment.episodes)
        titles = [
            table.slots[(season, episode)].title or f"Episode {episode}"
            for episode in episodes
        ]
        new_name = build_tv_name(
            show_info["name"],
            show_info.get("year", ""),
            season,
            episodes,
            titles,
            entry.path.suffix,
        )
        target_dir = root / _season_dir_name(season)

        if file_id in conflicted:
            slot_key = next(
                (season, episode)
                for episode in episodes
                if len(table.claims(season, episode)) > 1
            )
            other = next(
                table.files[claim.file_id]
                for claim in table.claims(*slot_key)
                if claim.file_id != file_id
            )
            status = _conflict_status(slot_key[0], slot_key[1], other)
        elif (
            assignment.origin != ORIGIN_MANUAL
            and not assignment.approved
            and assignment.confidence < threshold
        ):
            status = (
                f"{EPISODE_REVIEW_STATUS_PREFIX} "
                f"({assignment.confidence:.0%} < {threshold:.0%})"
            )
        else:
            status = "OK"

        item = PreviewItem(
            original=entry.path,
            new_name=new_name,
            target_dir=target_dir,
            season=season,
            episodes=episodes,
            status=status,
            episode_confidence=assignment.confidence,
            file_id=file_id,
            source_relative_folder=entry.source_relative_folder,
            **media_fields,
        )
        if status.startswith(("OK", "REVIEW")):
            item.companions = _build_subtitle_companions(entry.path, new_name)
        items.append(item)

    items.sort(
        key=lambda item: (
            item.season if item.season is not None else 9999,
            item.episodes[0] if item.episodes else 9999,
            item.is_conflict,
            item.original.name.casefold(),
        )
    )
    return items
```

Check `build_tv_name`'s multi-episode output in `plex_renamer/_parsing_names.py` before relying on the `"S01E01-E03"` assertion; if it formats differently (e.g. `S01E01-E02-E03`), adjust the test to the actual existing convention — do not change `build_tv_name`.

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_episode_projection.py tests/test_episode_assignments.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```powershell
git add plex_renamer/engine/models.py plex_renamer/engine/_episode_projection.py tests/test_episode_projection.py
git commit -m "feat: project assignment table into PreviewItem rows"
```

---

### Task 5: Table-based confidence floors and caps

**Files:**
- Modify: `plex_renamer/engine/_episode_resolution.py` (append)
- Test: `tests/test_episode_resolution.py` (extend)

The floors/caps from `_tv_scanner_postprocess.apply_episode_confidence_adjustments` move here and read `FileEntry` evidence instead of re-parsing filenames. Constants keep their current names and values.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_episode_resolution.py`)

```python
from pathlib import Path

from plex_renamer.engine.episode_assignments import (
    ORIGIN_AUTO,
    EpisodeAssignmentTable,
    EpisodeSlot,
)
from plex_renamer.engine._episode_resolution import (
    COMPATIBLE_PREFIX_FLOOR,
    CONTRADICTORY_PREFIX_CAP,
    EPISODE_TITLE_MATCH_FLOOR,
    EXACT_COVERAGE_FLOOR,
    EXPLICIT_EPISODE_FLOOR,
    apply_confidence_adjustments,
)

SHOW = {"id": 7, "name": "Demo Show", "year": "2020"}


def coverage_table(count: int = 3) -> EpisodeAssignmentTable:
    table = EpisodeAssignmentTable()
    for episode in range(1, count + 1):
        table.add_slot(EpisodeSlot(season=1, episode=episode, title=f"Ep {episode}"))
    return table


class TestConfidenceAdjustments:
    def test_explicit_episode_floor(self):
        table = coverage_table()
        entry = table.add_file(
            Path("Demo Show S01E01.mkv"), is_season_relative=True,
        )
        table.assign(entry.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=0.5)
        apply_confidence_adjustments(table, show_info=SHOW)
        assert table.assignment_for(entry.file_id).confidence >= EXPLICIT_EPISODE_FLOOR

    def test_title_match_floor(self):
        table = coverage_table()
        entry = table.add_file(
            Path("Demo Show S01E02 - Ep 2.mkv"),
            is_season_relative=True, raw_title="Ep 2",
        )
        table.assign(entry.file_id, 1, [2], origin=ORIGIN_AUTO, confidence=0.5)
        apply_confidence_adjustments(table, show_info=SHOW)
        assert table.assignment_for(entry.file_id).confidence >= EPISODE_TITLE_MATCH_FLOOR

    def test_exact_coverage_floor(self):
        table = coverage_table(3)
        for episode in range(1, 4):
            entry = table.add_file(
                Path(f"demo - {episode}.mkv"), is_season_relative=False,
            )
            table.assign(entry.file_id, 1, [episode], origin=ORIGIN_AUTO, confidence=0.5)
        apply_confidence_adjustments(table, show_info=SHOW)
        for assignment in table.assignments():
            assert assignment.confidence >= EXACT_COVERAGE_FLOOR

    def test_conflicted_season_gets_no_coverage_floor(self):
        table = coverage_table(3)
        first = table.add_file(Path("a.mkv"), is_season_relative=False)
        second = table.add_file(Path("b.mkv"), is_season_relative=False)
        table.assign(first.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=0.5)
        table.assign(second.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=0.5)
        apply_confidence_adjustments(table, show_info=SHOW)
        assert table.assignment_for(first.file_id).confidence == 0.5

    def test_contradictory_source_prefix_caps(self):
        table = coverage_table()
        entry = table.add_file(
            Path("Totally Different Show S01E01.mkv"), is_season_relative=True,
        )
        table.assign(entry.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=0.9)
        apply_confidence_adjustments(table, show_info=SHOW)
        assert (
            table.assignment_for(entry.file_id).confidence
            <= CONTRADICTORY_PREFIX_CAP
        )
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_episode_resolution.py -v -k Adjustments`
Expected: FAIL (`ImportError: apply_confidence_adjustments`)

- [ ] **Step 3: Implement** (append to `plex_renamer/engine/_episode_resolution.py`)

```python
# ── post-resolution confidence floors and caps ──────────────────────
# Same semantics as the retired _tv_scanner_postprocess adjustments,
# rebased onto FileEntry evidence instead of filename re-parsing.
EXPLICIT_EPISODE_FLOOR = 0.86
COMPATIBLE_PREFIX_FLOOR = 0.88
EPISODE_TITLE_MATCH_FLOOR = 0.92
PLEX_READY_EPISODE_FLOOR = 1.0
EXACT_COVERAGE_FLOOR = 0.80
SINGLE_SEASON_PERFECT_SHOW_EXACT_COVERAGE_FLOOR = 0.85
NEAR_COMPLETE_COVERAGE_FLOOR = 0.74
CONTRADICTORY_PREFIX_CAP = 0.45

# NOTE: extend the module's existing episode_assignments import with
# ORIGIN_MANUAL (used below):
#   from .episode_assignments import (
#       ORIGIN_MANUAL, REASON_NO_PARSE, REASON_NO_TITLE_MATCH, REASON_NOT_IN_SEASON,
#   )


def apply_confidence_adjustments(
    table: "EpisodeAssignmentTable",
    *,
    show_info: dict,
    show_match_confidence: float | None = None,
) -> None:
    """Raise/cap auto-assignment confidence from corroborating evidence."""
    from ..parsing import (
        build_tv_name,
        extract_source_title_prefix,
        normalize_for_match,
        normalize_for_specials,
    )

    show_name = show_info.get("name", "")
    show_norm = normalize_for_match(show_name)
    conflicted = table.conflicted_file_ids()

    season_slots: dict[int, set[int]] = {}
    for (season, episode) in table.slots:
        season_slots.setdefault(season, set()).add(episode)

    season_has_issue: set[int] = set()
    matched_by_season: dict[int, set[int]] = {}
    for assignment in table.assignments():
        if assignment.origin == ORIGIN_MANUAL:
            continue
        if assignment.file_id in conflicted:
            season_has_issue.add(assignment.season)
            continue
        matched_by_season.setdefault(assignment.season, set()).update(
            assignment.episodes
        )

    for assignment in table.assignments():
        if assignment.origin == ORIGIN_MANUAL or assignment.file_id in conflicted:
            continue
        entry = table.files[assignment.file_id]
        confidence = assignment.confidence

        if entry.is_season_relative:
            confidence = max(confidence, EXPLICIT_EPISODE_FLOOR)

        source_title = extract_source_title_prefix(entry.path.name)
        if source_title:
            source_norm = normalize_for_match(source_title)
            compatible = bool(show_norm) and (
                source_norm == show_norm
                or source_norm.startswith(show_norm)
                or show_norm.startswith(source_norm)
            )
            if compatible and entry.is_season_relative:
                confidence = max(confidence, COMPATIBLE_PREFIX_FLOOR)
            if not compatible:
                confidence = min(confidence, CONTRADICTORY_PREFIX_CAP)

        first_slot = table.slots.get((assignment.season, assignment.episodes[0]))
        if (
            entry.raw_title
            and first_slot is not None
            and first_slot.title
            and normalize_for_specials(entry.raw_title)
            == normalize_for_specials(first_slot.title)
        ):
            confidence = max(confidence, EPISODE_TITLE_MATCH_FLOOR)

        titles = [
            (table.slots[(assignment.season, episode)].title or f"Episode {episode}")
            for episode in assignment.episodes
        ]
        expected_name = build_tv_name(
            show_name,
            show_info.get("year", ""),
            assignment.season,
            list(assignment.episodes),
            titles,
            entry.path.suffix,
        )
        if expected_name == entry.path.name:
            confidence = max(confidence, PLEX_READY_EPISODE_FLOOR)

        table.set_confidence(assignment.file_id, confidence)

    single_regular_season = (
        sum(1 for season in season_slots if season > 0) == 1
    )
    perfect_show = show_match_confidence is not None and show_match_confidence >= 1.0

    for season, expected in season_slots.items():
        if season == 0 or season in season_has_issue or not expected:
            continue
        matched = matched_by_season.get(season, set())
        missing = expected - matched
        if matched == expected:
            floor = EXACT_COVERAGE_FLOOR
            if single_regular_season and perfect_show:
                floor = SINGLE_SEASON_PERFECT_SHOW_EXACT_COVERAGE_FLOOR
        elif matched and matched <= expected and (
            len(missing) <= 1 or len(matched) / max(len(expected), 1) >= 0.90
        ):
            floor = NEAR_COMPLETE_COVERAGE_FLOOR
        else:
            continue
        for assignment in table.assignments():
            if (
                assignment.season == season
                and assignment.origin != ORIGIN_MANUAL
                and assignment.file_id not in conflicted
            ):
                table.set_confidence(
                    assignment.file_id, max(assignment.confidence, floor),
                )
```

Air-date-aware "expected" filtering (the `_expected_episode_numbers` future-episode handling) carries over: when building `season_slots`, skip slots whose `air_date` parses to a future date *if* at least one slot in that season has an aired date. Implement as a small helper `_expected_for_season(slots: list[EpisodeSlot]) -> set[int]` mirroring `_tv_scanner_postprocess._expected_episode_numbers` (lines 162-183) and use it in the coverage loop.

Note the simplified prefix-compatibility check vs `_source_title_is_compatible`: the old season-name-aware variant lives at `_tv_scanner_postprocess.py:126-142`. Port it whole (copy `_is_generic_season_name`, `_title_is_compatible`, `_source_title_is_compatible` into `_episode_resolution.py` and call with `season_name=table-derived name ""`) rather than the simplified form above if any existing scanner test regresses in Task 6.

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_episode_resolution.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```powershell
git add plex_renamer/engine/_episode_resolution.py tests/test_episode_resolution.py
git commit -m "feat: table-based episode confidence floors and caps"
```

---

### Task 6: Scanner — normal and specials paths build the table

**Files:**
- Modify: `plex_renamer/engine/_tv_scanner_normal.py` (full rework of `build_normal_preview`)
- Modify: `plex_renamer/engine/_tv_scanner_specials.py` (resolution goes through policy)
- Modify: `plex_renamer/engine/_tv_scanner.py:144-251`
- Modify: `plex_renamer/engine/__init__.py` (export new names)
- Test: `tests/test_scan_improvements.py` (extend with table assertions)

This is the heart of the change. `build_normal_preview` becomes `build_normal_table`, returning `EpisodeAssignmentTable`. `TVScanner.scan()` keeps its public signature, stores the table on `self.assignment_table`, and returns the projection.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_scan_improvements.py` (reuse that file's existing fake-TMDB fixture pattern; if its fake differs, adapt construction — the assertions are the contract). Use `tmp_path` fixtures:

```python
class FakeTMDB:
    """Minimal TMDB stand-in for scanner tests."""

    def __init__(self, seasons: dict):
        # seasons: {num: {"titles": {ep: title}, "posters": {}, "episodes": {}, "count": n}}
        self._seasons = seasons
        self.language = "en-US"

    def get_season_map(self, show_id):
        return self._seasons, None

    def get_season(self, show_id, season_num):
        return self._seasons.get(
            season_num, {"titles": {}, "posters": {}, "episodes": {}},
        )

    def get_tv_details(self, show_id):
        return {"seasons": []}


SHOW_INFO = {"id": 5, "name": "Demo Show", "year": "2020"}


def _seasons(spec: dict[int, dict[int, str]]) -> dict:
    return {
        num: {
            "titles": titles,
            "posters": {},
            "episodes": {},
            "count": len(titles),
        }
        for num, titles in spec.items()
    }


def make_scanner(root, seasons):
    from plex_renamer.engine._tv_scanner import TVScanner

    return TVScanner(FakeTMDB(_seasons(seasons)), SHOW_INFO, root)


class TestTableDrivenScan:
    def test_scan_produces_assignment_table(self, tmp_path):
        season_dir = tmp_path / "Season 01"
        season_dir.mkdir()
        (season_dir / "Demo Show S01E01.mkv").touch()
        scanner = make_scanner(tmp_path, {1: {1: "Pilot", 2: "Two"}})
        items, _ = scanner.scan()
        assert scanner.assignment_table is not None
        assert len(scanner.assignment_table.files) == 1
        assert items[0].file_id is not None
        assert items[0].status == "OK"

    def test_special_title_beats_wrong_number(self, tmp_path):
        # The headline bug: local S00E03 named "Special A" while TMDB
        # says e02 is "Special A" -> must map to e02, not e03.
        specials = tmp_path / "Specials"
        specials.mkdir()
        (specials / "S00E03 - Special A.mkv").touch()
        scanner = make_scanner(
            tmp_path,
            {0: {1: "Opening", 2: "Special A", 3: "Special C"},
             1: {1: "Pilot"}},
        )
        items, _ = scanner.scan()
        special = next(item for item in items if item.season == 0)
        assert special.episodes == [2]
        assert special.episode_confidence < 1.0

    def test_unmatched_special_is_not_silent_ok(self, tmp_path):
        specials = tmp_path / "Specials"
        specials.mkdir()
        (specials / "random home video.mkv").touch()
        scanner = make_scanner(
            tmp_path, {0: {1: "Opening"}, 1: {1: "Pilot"}},
        )
        items, _ = scanner.scan()
        special = next(item for item in items if item.season == 0)
        assert special.is_unmatched

    def test_same_named_specials_in_two_seasons_conflict(self, tmp_path):
        for season_name in ("Season 01", "Season 02"):
            directory = tmp_path / season_name
            directory.mkdir()
            (directory / "S00E01 - Opening.mkv").touch()
        scanner = make_scanner(
            tmp_path, {0: {1: "Opening"}, 1: {1: "Pilot"}, 2: {1: "Reboot"}},
        )
        items, _ = scanner.scan()
        conflicted = [item for item in items if item.is_conflict]
        assert len(conflicted) == 2
        assert scanner.assignment_table.conflicts()

    def test_episode_confidence_set_on_specials(self, tmp_path):
        specials = tmp_path / "Specials"
        specials.mkdir()
        (specials / "S00E01.mkv").touch()  # number only, no title
        scanner = make_scanner(
            tmp_path, {0: {1: "Opening"}, 1: {1: "Pilot"}},
        )
        items, _ = scanner.scan()
        special = next(item for item in items if item.season == 0)
        assert special.episode_confidence < 1.0
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_scan_improvements.py -v -k TableDrivenScan`
Expected: FAIL (`AttributeError: assignment_table` etc.)

- [ ] **Step 3: Rework `_tv_scanner_normal.py`**

Replace `build_normal_preview` with `build_normal_table`. Keep the season-dir iteration, extras detection, and `file_season == 0` redirection logic intact; what changes is that every file becomes a `FileEntry` + a `resolve_file` call instead of inline `PreviewItem` construction:

```python
"""Normal per-season table building for TVScanner."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from ..constants import VIDEO_EXTENSIONS
from ..parsing import extract_episode, extract_season_number, is_extras_folder
from ._episode_resolution import resolve_file
from .episode_assignments import EpisodeAssignmentTable, EpisodeSlot
from .models import SeasonFolderEntry, iter_season_folder_paths


def _register_season_slots(
    table: EpisodeAssignmentTable,
    season_num: int,
    titles: dict,
    episodes_meta: dict,
) -> None:
    for episode_num, title in titles.items():
        meta = (episodes_meta or {}).get(episode_num, {}) or {}
        table.add_slot(EpisodeSlot(
            season=season_num,
            episode=episode_num,
            title=title,
            air_date=str(meta.get("air_date", "") or ""),
            overview=str(meta.get("overview", "") or ""),
        ))


def _resolve_into_table(
    table: EpisodeAssignmentTable,
    *,
    file_path: Path,
    season_num: int,
    season_titles: dict[int, str],
    from_extras_folder: bool = False,
) -> None:
    episode_numbers, raw_title, is_season_relative = extract_episode(file_path.name)
    season_hint = extract_season_number(file_path.name) if is_season_relative else None
    entry = table.add_file(
        file_path,
        parsed_episodes=tuple(episode_numbers),
        raw_title=raw_title,
        is_season_relative=is_season_relative,
        season_hint=season_hint,
        folder_season=season_num,
        from_extras_folder=from_extras_folder,
    )
    resolution = resolve_file(
        parsed_episodes=tuple(episode_numbers),
        raw_title=raw_title,
        is_season_relative=is_season_relative,
        season_titles=season_titles,
    )
    if resolution.episodes:
        table.assign(
            entry.file_id,
            season_num,
            list(resolution.episodes),
            origin="auto",
            confidence=resolution.confidence,
            evidence=resolution.evidence,
        )
    else:
        table.mark_unassigned(entry.file_id, resolution.reason or "")


def build_normal_table(
    *,
    season_dirs: list[tuple[Path, int]],
    tmdb_seasons: dict,
    tmdb,
    show_info: dict,
    root: Path,
    season_folders: dict[int, SeasonFolderEntry] | None,
    store_tmdb_data: Callable[[int, dict, dict, dict | None], None],
) -> EpisodeAssignmentTable:
    table = EpisodeAssignmentTable()
    s0_titles: dict[int, str] | None = None

    def ensure_s0_titles() -> dict[int, str]:
        nonlocal s0_titles
        if s0_titles is None:
            if 0 in tmdb_seasons:
                data = tmdb_seasons[0]
            else:
                data = tmdb.get_season(show_info["id"], 0)
            s0_titles = data.get("titles", {})
            if s0_titles:
                store_tmdb_data(0, s0_titles, data.get("posters", {}), data.get("episodes", {}))
                _register_season_slots(table, 0, s0_titles, data.get("episodes", {}))
        return s0_titles

    registered_seasons: set[int] = set()
    for season_dir, season_num in season_dirs:
        if season_num in tmdb_seasons:
            season_data = tmdb_seasons[season_num]
        else:
            season_data = tmdb.get_season(show_info["id"], season_num)
        titles = season_data.get("titles", {})
        store_tmdb_data(
            season_num, titles,
            season_data.get("posters", {}), season_data.get("episodes", {}),
        )
        if season_num == 0:
            ensure_s0_titles()
            titles = s0_titles or titles
        elif season_num not in registered_seasons:
            _register_season_slots(table, season_num, titles, season_data.get("episodes", {}))
            registered_seasons.add(season_num)

        explicit_season_folder = season_dir == root
        if not explicit_season_folder and season_folders:
            explicit_season_folder = any(
                folder == season_dir
                for folder_entry in season_folders.values()
                for folder in iter_season_folder_paths(folder_entry)
            )
        nested_specials_folder = bool(re.search(
            r"(?:^|[\s._\-])specials?$|(?:^|[\s._\-])season[\s._\-]*0+$",
            season_dir.name, re.IGNORECASE,
        ))
        extras_folder = (
            season_num == 0
            and not explicit_season_folder
            and not nested_specials_folder
            and season_dir.name.lower().strip() not in (
                "specials", "special", "season 00", "season 0",
                "season00", "season0",
            )
        )

        for entry_path in sorted(season_dir.iterdir()):
            if entry_path.is_file() and entry_path.suffix.lower() in VIDEO_EXTENSIONS:
                _, _, is_season_relative = extract_episode(entry_path.name)
                file_season = (
                    extract_season_number(entry_path.name)
                    if is_season_relative else None
                )
                if season_num == 0 or file_season == 0:
                    _resolve_into_table(
                        table,
                        file_path=entry_path,
                        season_num=0,
                        season_titles=ensure_s0_titles(),
                        from_extras_folder=extras_folder and season_num == 0,
                    )
                else:
                    _resolve_into_table(
                        table,
                        file_path=entry_path,
                        season_num=season_num,
                        season_titles=titles,
                    )
            elif entry_path.is_dir() and season_num != 0 and is_extras_folder(entry_path.name):
                for extras_file in sorted(entry_path.iterdir()):
                    if (
                        extras_file.is_file()
                        and extras_file.suffix.lower() in VIDEO_EXTENSIONS
                    ):
                        _resolve_into_table(
                            table,
                            file_path=extras_file,
                            season_num=0,
                            season_titles=ensure_s0_titles(),
                            from_extras_folder=True,
                        )

    return table
```

`_tv_scanner_specials.py` keeps `load_specials_context`/`build_title_lookup` for the consolidated path's reuse and the detail panel, but `match_special` and `scan_nested_extras` are deleted once nothing imports them (verify with `Grep` for `match_special|scan_nested_extras` before deleting; update `engine/__init__.py` and `_tv_scanner.py` accordingly).

- [ ] **Step 4: Rework `TVScanner` glue** (`_tv_scanner.py`)

Add to `__init__` (after line 89): `self.assignment_table: EpisodeAssignmentTable | None = None` (import `EpisodeAssignmentTable` from `.episode_assignments`).

Replace `_build_normal_preview` (lines 223-251) with:

```python
    def _build_normal_preview(
        self,
        season_dirs: list[tuple[Path, int]],
        tmdb_seasons: dict,
    ) -> list[PreviewItem]:
        from ._episode_projection import project_preview_items
        from ._episode_resolution import apply_confidence_adjustments
        from ._tv_scanner_normal import build_normal_table

        table = build_normal_table(
            season_dirs=season_dirs,
            tmdb_seasons=tmdb_seasons,
            tmdb=self.tmdb,
            show_info=self.show_info,
            root=self.root,
            season_folders=self._season_folders,
            store_tmdb_data=self._store_tmdb_data,
        )
        apply_confidence_adjustments(
            table,
            show_info=self.show_info,
            show_match_confidence=self._show_match_confidence,
        )
        self.assignment_table = table
        return project_preview_items(
            table,
            show_info=self.show_info,
            root=self.root,
            media_fields=self._media_fields,
        )
```

Delete `_resolve_duplicate_episodes`, `_match_special`, `_fuzzy_match_special`, `_scan_nested_extras` methods and their imports from `_tv_scanner.py`; the table replaces all of them on this path. (Consolidated path is Task 7 — until then it still calls `self._resolve_duplicate_episodes`, so in THIS task keep `_resolve_duplicate_episodes` and only delete it in Task 7.)

- [ ] **Step 5: Run the scanner tests and the full suite**

Run: `python -m pytest tests/test_scan_improvements.py tests/test_episode_mapping_projection.py tests/test_haikyuu_matching.py tests/test_jojo_matching.py -v`
Expected: new tests PASS. Existing tests that pinned old behavior need review:
- Tests asserting `SKIP: duplicate episode` → now expect `CONFLICT: duplicate episode claim`.
- Tests asserting silent-OK unmatched specials → now expect `UNMATCHED`.
Update those assertions — they encode the bugs this redesign fixes. Anything else that breaks is a regression; fix the code, not the test.

Then: `python -m pytest tests -x -q --ignore=tests/test_qt_main_window.py`
Expected: ≥ baseline count.

- [ ] **Step 6: Commit**

```powershell
git add plex_renamer/engine tests
git commit -m "feat: normal and specials scan paths resolve through the assignment table"
```

---

### Task 7: Consolidated path ingestion

**Files:**
- Modify: `plex_renamer/engine/_tv_scanner_consolidated.py:140-271`
- Modify: `plex_renamer/engine/_tv_scanner.py:300-313`
- Create helper in: `plex_renamer/engine/episode_assignments.py` (append)
- Test: `tests/test_episode_assignments.py` (extend)

The consolidated (absolute-order) matcher keeps its internal logic but its output is ingested into a table so every scan path yields one. Multi-claims become conflicts via the table instead of `resolve_duplicate_episodes`.

- [ ] **Step 1: Write the failing test** (append to `tests/test_episode_assignments.py`)

```python
from plex_renamer.engine.episode_assignments import ingest_preview_items
from plex_renamer.engine.models import PreviewItem


class TestIngestion:
    def test_ingest_assigned_and_skipped_items(self):
        table = make_table()
        ok_item = PreviewItem(
            original=Path("a.mkv"), new_name="x.mkv", target_dir=Path("out"),
            season=1, episodes=[2], status="OK", episode_confidence=0.7,
        )
        skip_item = PreviewItem(
            original=Path("b.mkv"), new_name=None, target_dir=None,
            season=0, episodes=[], status="SKIP: could not match episode title to TMDB",
        )
        ingest_preview_items(table, [ok_item, skip_item])
        assert table.claimant(1, 2) is not None
        assert len(table.unassigned_files()) == 1
        assert ok_item.file_id is not None

    def test_ingest_duplicate_claims_conflict(self):
        table = make_table()
        items = [
            PreviewItem(
                original=Path(name), new_name="x.mkv", target_dir=Path("out"),
                season=1, episodes=[2], status="OK", episode_confidence=0.7,
            )
            for name in ("a.mkv", "b.mkv")
        ]
        ingest_preview_items(table, items)
        assert (1, 2) in table.conflicts()
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_episode_assignments.py -v -k Ingestion`
Expected: FAIL (`ImportError: ingest_preview_items`)

- [ ] **Step 3: Implement** (append to `plex_renamer/engine/episode_assignments.py`)

```python
def ingest_preview_items(
    table: EpisodeAssignmentTable,
    items: list,
) -> None:
    """Ingest already-built PreviewItems (consolidated path) into a table.

    Sets ``item.file_id`` on each item so the GUI can address files.
    Assigned items become auto claims; everything else is unassigned with
    the item's status text as the reason.
    """
    from ..parsing import extract_episode, extract_season_number

    for item in items:
        episode_numbers, raw_title, is_season_relative = extract_episode(
            item.original.name,
        )
        entry = table.add_file(
            item.original,
            parsed_episodes=tuple(episode_numbers),
            raw_title=raw_title,
            is_season_relative=is_season_relative,
            season_hint=(
                extract_season_number(item.original.name)
                if is_season_relative else None
            ),
            folder_season=item.season,
            source_relative_folder=item.source_relative_folder,
        )
        item.file_id = entry.file_id
        if (
            item.season is not None
            and item.episodes
            and item.new_name is not None
            and not item.is_skipped
            and not item.is_unmatched
        ):
            valid = [
                episode for episode in item.episodes
                if (item.season, episode) in table.slots
            ]
            if valid == list(item.episodes):
                table.assign(
                    entry.file_id,
                    item.season,
                    valid,
                    origin=ORIGIN_AUTO,
                    confidence=item.episode_confidence,
                    evidence=frozenset({"consolidated"}),
                )
                continue
        table.mark_unassigned(entry.file_id, item.status or REASON_NO_PARSE)
```

- [ ] **Step 4: Wire into `_build_consolidated_preview`** in `_tv_scanner.py` (lines 300-313): after obtaining `items` from `_build_consolidated_preview(...)`, register slots and ingest:

```python
    def _build_consolidated_preview(
        self,
        season_dirs: list[tuple[Path, int]],
        tmdb_seasons: dict,
    ) -> list[PreviewItem]:
        from ._episode_resolution import apply_confidence_adjustments
        from ._episode_projection import project_preview_items
        from ._tv_scanner_normal import _register_season_slots
        from .episode_assignments import EpisodeAssignmentTable, ingest_preview_items

        items = _build_consolidated_preview(
            season_dirs=season_dirs,
            tmdb_seasons=tmdb_seasons,
            root=self.root,
            show_info=self.show_info,
            media_fields=self._media_fields,
            store_tmdb_data=self._store_tmdb_data,
        )
        table = EpisodeAssignmentTable()
        for season_num, season_data in tmdb_seasons.items():
            _register_season_slots(
                table, season_num,
                season_data.get("titles", {}), season_data.get("episodes", {}),
            )
        ingest_preview_items(table, items)
        apply_confidence_adjustments(
            table,
            show_info=self.show_info,
            show_match_confidence=self._show_match_confidence,
        )
        self.assignment_table = table
        return project_preview_items(
            table,
            show_info=self.show_info,
            root=self.root,
            media_fields=self._media_fields,
        )
```

Remove the `resolve_duplicate_episodes` parameter from `build_consolidated_preview` in `_tv_scanner_consolidated.py` (delete both `resolve_duplicate_episodes(items)` calls and the parameter; the table handles duplicates). Now delete `_resolve_duplicate_episodes` from `_tv_scanner.py` and `resolve_duplicate_episodes`, `apply_episode_confidence_adjustments`, `apply_episode_review_threshold` from `_tv_scanner_postprocess.py` (grep first: `python -m pytest` plus `Grep` for each name; `apply_episode_review_threshold` is also imported in `engine/__init__.py` — update exports).

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests -x -q --ignore=tests/test_qt_main_window.py`
Expected: ≥ baseline. Same migration rule as Task 6 for tests pinning `SKIP: duplicate episode`.

- [ ] **Step 6: Commit**

```powershell
git add plex_renamer/engine tests
git commit -m "feat: consolidated scan path ingests into the assignment table"
```

---

### Task 8: ScanState wiring and sibling-table reconciliation

**Files:**
- Modify: `plex_renamer/engine/models.py:165-206` (`ScanState.assignments`)
- Modify: `plex_renamer/app/controllers/_tv_state_helpers.py:47-63`
- Modify: `plex_renamer/engine/_batch_tv_episode_claims.py`
- Test: `tests/test_episode_assignments.py` (extend), existing reconcile tests

- [ ] **Step 1: Write the failing tests** (append to `tests/test_episode_assignments.py`)

```python
from plex_renamer.engine.episode_assignments import merge_tables


class TestMergeTables:
    def test_merge_remaps_file_ids_and_detects_cross_state_conflicts(self):
        primary = make_table()
        sibling = make_table()
        a = primary.add_file(Path("s1/opening.mkv"), source_relative_folder="s1")
        b = sibling.add_file(Path("s2/opening.mkv"), source_relative_folder="s2")
        primary.assign(a.file_id, 0, [1], origin=ORIGIN_AUTO, confidence=0.9)
        sibling.assign(b.file_id, 0, [1], origin=ORIGIN_AUTO, confidence=0.9)
        merge_tables(primary, sibling)
        assert len(primary.files) == 2
        assert (0, 1) in primary.conflicts()

    def test_merge_keeps_unassigned_reasons(self):
        primary = make_table()
        sibling = make_table()
        entry = sibling.add_file(Path("x.mkv"))
        sibling.mark_unassigned(entry.file_id, "could not parse episode number")
        merge_tables(primary, sibling)
        assert len(primary.unassigned_files()) == 1


class TestManualCarryOver:
    def test_manual_assignments_survive_rescan_of_same_show(self):
        from plex_renamer.engine.episode_assignments import (
            carry_over_manual_assignments,
        )
        old = make_table()
        entry_old = old.add_file(Path("lib/show/e1.mkv"))
        old.assign(entry_old.file_id, 1, [2], origin=ORIGIN_MANUAL)

        new = make_table()
        entry_new = new.add_file(Path("lib/show/e1.mkv"))
        new.assign(entry_new.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=0.9)

        carry_over_manual_assignments(old, new)
        restored = new.assignment_for(entry_new.file_id)
        assert restored.episodes == (2,)
        assert restored.origin == ORIGIN_MANUAL

    def test_manual_carry_over_skips_files_missing_from_new_scan(self):
        from plex_renamer.engine.episode_assignments import (
            carry_over_manual_assignments,
        )
        old = make_table()
        gone = old.add_file(Path("lib/show/deleted.mkv"))
        old.assign(gone.file_id, 1, [1], origin=ORIGIN_MANUAL)
        new = make_table()
        carry_over_manual_assignments(old, new)  # must not raise
        assert new.assignments() == []
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_episode_assignments.py -v -k Merge`
Expected: FAIL (`ImportError: merge_tables`)

- [ ] **Step 3: Implement `merge_tables`** (append to `episode_assignments.py`)

```python
def merge_tables(
    primary: EpisodeAssignmentTable,
    other: EpisodeAssignmentTable,
) -> dict[int, int]:
    """Absorb *other* into *primary*; returns old->new file id mapping."""
    id_map: dict[int, int] = {}
    for slot in other.slots.values():
        if slot.key not in primary.slots:
            primary.add_slot(slot)
    for old_id, entry in sorted(other.files.items()):
        new_entry = primary.add_file(
            entry.path,
            parsed_episodes=entry.parsed_episodes,
            raw_title=entry.raw_title,
            is_season_relative=entry.is_season_relative,
            season_hint=entry.season_hint,
            folder_season=entry.folder_season,
            from_extras_folder=entry.from_extras_folder,
            source_relative_folder=entry.source_relative_folder,
        )
        id_map[old_id] = new_entry.file_id
        assignment = other.assignment_for(old_id)
        if assignment is not None:
            primary.assign(
                new_entry.file_id,
                assignment.season,
                list(assignment.episodes),
                origin=assignment.origin,
                confidence=assignment.confidence,
                evidence=assignment.evidence,
            )
            if assignment.approved:
                primary.set_approved(new_entry.file_id)
        else:
            primary.mark_unassigned(
                new_entry.file_id, other.unassigned_reasons.get(old_id, ""),
            )
    return id_map


def carry_over_manual_assignments(
    old: EpisodeAssignmentTable,
    new: EpisodeAssignmentTable,
) -> None:
    """Re-apply manual assignments from a previous scan of the SAME show.

    Matches files by path. Files that vanished or episodes no longer in
    TMDB are skipped silently (the rescan reflects current reality).
    Spec: manual assignments survive re-scans of the same show match;
    a rematch to a different show id discards the old table entirely.
    """
    new_by_path = {entry.path: entry.file_id for entry in new.files.values()}
    for assignment in old.assignments():
        if assignment.origin != ORIGIN_MANUAL:
            continue
        entry = old.files[assignment.file_id]
        new_id = new_by_path.get(entry.path)
        if new_id is None:
            continue
        try:
            new.assign(
                new_id,
                assignment.season,
                list(assignment.episodes),
                origin=ORIGIN_MANUAL,
                displace=True,
            )
        except ValueError:
            continue
```

- [ ] **Step 4: Wire `ScanState` and the scan helper**

In `plex_renamer/engine/models.py` add to `ScanState` after `completeness: CompletenessReport | None = None` (line 170):

```python
    assignments: "EpisodeAssignmentTable | None" = None
```

with a `TYPE_CHECKING` import: `from .episode_assignments import EpisodeAssignmentTable  # noqa: F401`. Also clear it in `reset_scan()` (`self.assignments = None`).

In `_tv_state_helpers.run_tv_scan` (line 54-63), after the `items, has_mismatch = scanner.scan()` / consolidated branch and before `state.preview_items = items`, store the table and carry over manual fixes from any previous scan of the same show:

```python
    new_table = getattr(scanner, "assignment_table", None)
    old_table = state.assignments
    if (
        new_table is not None
        and old_table is not None
        and state.show_id == scanner.show_info.get("id")
    ):
        carry_over_manual_assignments(old_table, new_table)
        from ...engine._episode_projection import project_preview_items
        items = project_preview_items(
            new_table,
            show_info=state.media_info,
            root=state.folder,
            media_fields={
                "media_id": state.show_id,
                "media_name": state.media_info.get("name"),
            },
        )
    state.assignments = new_table
```

(`carry_over_manual_assignments` imported from `...engine.episode_assignments`. The rematch-to-a-different-show flow goes through `reset_scan()`, which clears `state.assignments` — so a different show never inherits manual fixes.)

In `_batch_tv_episode_claims.reconcile_scanned_episode_claims`, inside the per-group loop after `primary` is chosen: instead of the status-string claim merge (lines 49-62), merge tables and reproject when all group members have tables:

```python
        tables = [state.assignments for state in ordered]
        if all(table is not None for table in tables):
            for state in ordered:
                assign_preview_source_folders(state, library_root)
                if state is not primary:
                    for entry in state.assignments.files.values():
                        if not entry.source_relative_folder:
                            entry.source_relative_folder = _relative_folder(
                                entry.path.parent, library_root,
                            )
                    merge_tables(primary.assignments, state.assignments)
                    removed.add(id(state))
                    replacements[id(state)] = primary
            from ._episode_projection import project_preview_items
            primary.preview_items = project_preview_items(
                primary.assignments,
                show_info=primary.media_info,
                root=primary.folder,
                media_fields={
                    "media_id": primary.show_id,
                    "media_name": primary.media_info.get("name"),
                },
            )
        else:
            # Legacy path for states scanned before the table existed:
            # keep the CURRENT body of the per-group loop (the
            # `_episode_claim_keys` / `claimed` dict merge at lines 49-62
            # of the existing file) verbatim in this else-branch.
```

Also set `entry.source_relative_folder` for the primary's own files the same way before projecting. Keep the rest of the function (counts, `checked`, completeness recompute) as-is, operating on the projected `primary.preview_items`.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests -x -q --ignore=tests/test_qt_main_window.py`
Expected: ≥ baseline. Reconcile-related tests asserting merged ordering still pass (projection sorts identically).

- [ ] **Step 6: Commit**

```powershell
git add plex_renamer/engine plex_renamer/app/controllers/_tv_state_helpers.py tests
git commit -m "feat: store assignment table on ScanState and merge sibling tables"
```

---

### Task 9: Specials-only folders scan Season 0; S00 evidence feeds show scoring

**Files:**
- Modify: `plex_renamer/engine/models.py:296-364` (`collect_direct_episode_evidence`, `infer_explicit_season_assignment`)
- Modify: `plex_renamer/engine/matching.py:301-339` (`_tv_episode_evidence_adjustment`)
- Test: `tests/test_scan_improvements.py`, `tests/test_alt_title_matching.py` (extend)

- [ ] **Step 1: Write the failing tests** (append to `tests/test_scan_improvements.py`)

```python
class TestSpecialsOnlyShow:
    def test_specials_only_folder_scans_season_zero(self, tmp_path):
        specials = tmp_path / "Specials"
        specials.mkdir()
        (specials / "S00E01 - Opening.mkv").touch()
        scanner = make_scanner(
            tmp_path, {0: {1: "Opening"}, 1: {1: "Pilot"}},
        )
        items, _ = scanner.scan()
        assert all(item.season == 0 for item in items)

    def test_infer_season_assignment_returns_zero_for_all_s00_evidence(self):
        from plex_renamer.engine.models import (
            DirectEpisodeEvidence,
            infer_explicit_season_assignment,
        )
        evidence = [
            DirectEpisodeEvidence(0, 1, "Opening"),
            DirectEpisodeEvidence(0, 2, "Recap"),
        ]
        assert infer_explicit_season_assignment(
            Path("Some Show"), evidence,
        ) == 0

    def test_collect_evidence_descends_specials_folder(self, tmp_path):
        from plex_renamer.engine.models import collect_direct_episode_evidence
        specials = tmp_path / "Specials"
        specials.mkdir()
        (specials / "S00E01 - Opening.mkv").touch()
        evidence = collect_direct_episode_evidence(tmp_path)
        assert any(item.season_num == 0 for item in evidence)
```

- [ ] **Step 2: Run to verify which fail**

Run: `python -m pytest tests/test_scan_improvements.py -v -k SpecialsOnly`
Some may already pass (`get_season("Specials")` → 0 means the scanner path can be fine); fix only what fails. Expected failures: `infer_explicit_season_assignment` returns `None` for all-S00 evidence (line 350-352 filters `season_num > 0`).

- [ ] **Step 3: Implement the fixes**

In `models.infer_explicit_season_assignment` (line 349-352), replace:

```python
    direct_evidence = evidence if evidence is not None else collect_direct_episode_evidence(folder)
    explicit_seasons = {item.season_num for item in direct_evidence if item.season_num > 0}
    if len(explicit_seasons) == 1:
        return next(iter(explicit_seasons))
```

with:

```python
    direct_evidence = evidence if evidence is not None else collect_direct_episode_evidence(folder)
    explicit_seasons = {item.season_num for item in direct_evidence}
    if len(explicit_seasons) == 1:
        return next(iter(explicit_seasons))
```

(Single-season evidence of `{0}` now yields 0 — a specials-only folder is hinted at Season 0 instead of falling through to the Season-1 default in `resolve_tv_season_dirs`.)

In `matching._tv_episode_evidence_adjustment` (lines 311-315), make season-0 evidence count toward coverage, replace:

```python
    explicit_seasons = {item.season_num for item in evidence if item.season_num > 0}
    if explicit_seasons:
        tmdb_regular_seasons = {sn for sn in tmdb_seasons if sn > 0}
        coverage = len(explicit_seasons & tmdb_regular_seasons) / len(explicit_seasons)
```

with:

```python
    explicit_seasons = {item.season_num for item in evidence}
    if explicit_seasons:
        tmdb_known_seasons = {int(sn) for sn in tmdb_seasons}
        coverage = len(explicit_seasons & tmdb_known_seasons) / len(explicit_seasons)
```

If `test_collect_evidence_descends_specials_folder` fails, the cause is `collect_direct_episode_evidence`'s child-dir loop (`models.py:329-334`): `get_season(child)` returns 0 for "Specials" which passes the `is None` check, so it should already descend — debug from the actual failure, do not guess.

- [ ] **Step 4: Run the suite**

Run: `python -m pytest tests/test_scan_improvements.py tests/test_alt_title_matching.py tests/test_haikyuu_matching.py tests/test_jojo_matching.py -q`
Expected: PASS. Verify the show-scoring change doesn't flip the Haikyuu/JoJo disambiguation fixtures; if a fixture regresses, the coverage denominator change is the suspect — scope it to only add S0 when `0 in tmdb_seasons`.

- [ ] **Step 5: Commit**

```powershell
git add plex_renamer/engine/models.py plex_renamer/engine/matching.py tests
git commit -m "fix: specials-only folders hint season 0 and S00 evidence feeds show scoring"
```

---

### Task 10: EpisodeMappingService — table-backed operations

**Files:**
- Modify: `plex_renamer/app/services/episode_mapping_service.py` (major rework)
- Modify: `plex_renamer/app/models/state_models.py:163-198` (choice models)
- Test: `tests/test_episode_mapping_projection.py` (extend)

- [ ] **Step 1: Write the failing tests** (append to `tests/test_episode_mapping_projection.py`; reuse that file's existing `ScanState` fixture helpers — if it builds states by hand, mirror that. The fixture below is self-contained):

```python
from pathlib import Path

from plex_renamer.engine import ScanState
from plex_renamer.engine.episode_assignments import (
    ORIGIN_AUTO,
    EpisodeAssignmentTable,
    EpisodeSlot,
)
from plex_renamer.engine._episode_projection import project_preview_items
from plex_renamer.app.services.episode_mapping_service import EpisodeMappingService

ROOT = Path("C:/lib/Demo Show (2020)")
SHOW = {"id": 9, "name": "Demo Show", "year": "2020"}


def table_state() -> ScanState:
    table = EpisodeAssignmentTable()
    for episode, title in [(1, "Pilot"), (2, "Heist"), (3, "Endgame"), (4, "Coda")]:
        table.add_slot(EpisodeSlot(season=1, episode=episode, title=title))
    ok = table.add_file(ROOT / "e1.mkv")
    table.assign(ok.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=0.9)
    stray = table.add_file(ROOT / "stray.mkv")
    table.mark_unassigned(stray.file_id, "could not parse episode number")
    state = ScanState(folder=ROOT, media_info=SHOW)
    state.assignments = table
    state.preview_items = project_preview_items(
        table, show_info=SHOW, root=ROOT,
        media_fields={"media_id": 9, "media_name": "Demo Show"},
    )
    state.scanned = True
    return state


class TestTableBackedService:
    def test_assign_unassigned_file_to_missing_episodes(self):
        state = table_state()
        service = EpisodeMappingService()
        stray = next(p for p in state.preview_items if p.new_name is None)
        service.assign_file(state, stray, season=1, episodes=[2, 3])
        updated = next(
            p for p in state.preview_items if p.original.name == "stray.mkv"
        )
        assert updated.episodes == [2, 3]
        assert updated.status == "OK"
        assert updated.episode_confidence == 1.0

    def test_assign_displaces_existing_claimant(self):
        state = table_state()
        service = EpisodeMappingService()
        stray = next(p for p in state.preview_items if p.new_name is None)
        service.assign_file(state, stray, season=1, episodes=[1])
        displaced = next(
            p for p in state.preview_items if p.original.name == "e1.mkv"
        )
        assert displaced.new_name is None  # back to unassigned

    def test_unassign_file(self):
        state = table_state()
        service = EpisodeMappingService()
        mapped = next(p for p in state.preview_items if p.status == "OK")
        service.unassign_file(state, mapped)
        assert all(
            p.new_name is None
            for p in state.preview_items if p.original.name == "e1.mkv"
        )

    def test_approve_file(self):
        state = table_state()
        table = state.assignments
        low = table.add_file(ROOT / "low.mkv")
        table.assign(low.file_id, 1, [4], origin=ORIGIN_AUTO, confidence=0.5)
        service = EpisodeMappingService()
        service.reproject(state)
        review = next(p for p in state.preview_items if p.is_episode_review)
        service.approve_file(state, review)
        approved = next(
            p for p in state.preview_items if p.original.name == "low.mkv"
        )
        assert approved.status == "OK"

    def test_slot_choices_show_claim_state(self):
        state = table_state()
        service = EpisodeMappingService()
        choices = service.episode_slot_choices(state)
        claimed = next(c for c in choices if (c.season, c.episode) == (1, 1))
        free = next(c for c in choices if (c.season, c.episode) == (1, 2))
        assert claimed.claimed_by == "e1.mkv"
        assert free.claimed_by is None

    def test_guide_lists_unassigned_with_reason(self):
        state = table_state()
        service = EpisodeMappingService()
        guide = service.build_episode_guide(state)
        assert guide.summary.unmapped_primary_files == 1
        assert guide.unmapped_primary_files[0].reason == (
            "could not parse episode number"
        )
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_episode_mapping_projection.py -v -k TableBacked`
Expected: FAIL (`AttributeError: assign_file` etc.)

- [ ] **Step 3: Implement**

In `plex_renamer/app/models/state_models.py`, add after `UnmappedFileRow` (line 188):

```python
@dataclass(slots=True)
class EpisodeSlotChoice:
    """One pickable episode slot for the assignment dialog."""

    season: int
    episode: int
    title: str = ""
    claimed_by: str | None = None

    @property
    def label(self) -> str:
        text = f"S{self.season:02d}E{self.episode:02d}"
        if self.title:
            text = f"{text} - {self.title}"
        return text
```

In `episode_mapping_service.py`, add table-backed operations to `EpisodeMappingService` (keep `build_episode_guide`/`build_queue_preflight`; they already read projected `preview_items` and keep working — `_is_episode_mapped` and the summary counts are projection-driven). New methods:

```python
    # ── table-backed mutations ──────────────────────────────────────

    @staticmethod
    def _require_table(state: ScanState) -> "EpisodeAssignmentTable":
        table = state.assignments
        if table is None:
            raise ValueError("This show has no assignment table (rescan needed)")
        return table

    def reproject(self, state: ScanState) -> None:
        from ...engine._episode_projection import project_preview_items

        table = self._require_table(state)
        state.preview_items = project_preview_items(
            table,
            show_info=state.media_info,
            root=state.folder,
            media_fields={
                "media_id": state.show_id,
                "media_name": state.media_info.get("name"),
            },
        )
        if state.scanner is not None:
            checked = {
                index for index, item in enumerate(state.preview_items)
                if item.status == "OK"
            }
            state.completeness = state.scanner.get_completeness(
                state.preview_items, checked_indices=checked,
            )
        state.reset_gui_state()

    def assign_file(
        self,
        state: ScanState,
        preview: PreviewItem,
        *,
        season: int,
        episodes: list[int],
    ) -> None:
        from ...engine.episode_assignments import ORIGIN_MANUAL

        table = self._require_table(state)
        if preview.file_id is None:
            raise ValueError("Preview row is not linked to a scanned file")
        table.assign(
            preview.file_id, season, episodes,
            origin=ORIGIN_MANUAL, displace=True,
        )
        self.reproject(state)

    def unassign_file(self, state: ScanState, preview: PreviewItem) -> None:
        table = self._require_table(state)
        if preview.file_id is None:
            raise ValueError("Preview row is not linked to a scanned file")
        table.unassign(preview.file_id)
        self.reproject(state)

    def approve_file(self, state: ScanState, preview: PreviewItem) -> None:
        table = self._require_table(state)
        if preview.file_id is None:
            raise ValueError("Preview row is not linked to a scanned file")
        table.set_approved(preview.file_id)
        self.reproject(state)

    def approve_all(self, state: ScanState) -> int:
        table = self._require_table(state)
        count = 0
        for preview in state.preview_items:
            if preview.is_episode_review and preview.file_id is not None:
                table.set_approved(preview.file_id)
                count += 1
        if count:
            self.reproject(state)
        return count

    def resolve_conflict(
        self, state: ScanState, season: int, episode: int, winner: PreviewItem,
    ) -> None:
        table = self._require_table(state)
        if winner.file_id is None:
            raise ValueError("Preview row is not linked to a scanned file")
        table.resolve_conflict(season, episode, winner_file_id=winner.file_id)
        self.reproject(state)

    # ── choices for the dialogs ─────────────────────────────────────

    def episode_slot_choices(self, state: ScanState) -> list[EpisodeSlotChoice]:
        table = self._require_table(state)
        choices: list[EpisodeSlotChoice] = []
        for key, slot in sorted(table.slots.items()):
            claimant = table.claimant(*key)
            choices.append(EpisodeSlotChoice(
                season=slot.season,
                episode=slot.episode,
                title=slot.title,
                claimed_by=claimant.path.name if claimant else None,
            ))
        return choices

    def unassigned_file_previews(self, state: ScanState) -> list[PreviewItem]:
        table = self._require_table(state)
        unassigned_ids = {entry.file_id for entry, _ in table.unassigned_files()}
        return [
            preview for preview in state.preview_items
            if preview.file_id in unassigned_ids
        ]
```

(Imports: add `EpisodeSlotChoice` to the `..models` import; `PreviewItem` is already imported.)

Update `build_episode_guide`'s unmapped rows to carry the table reason when available: where it appends `UnmappedFileRow(..., reason=preview.status, ...)`, use `reason=state.assignments.unassigned_reasons.get(preview.file_id, preview.status) if state.assignments is not None and preview.file_id is not None else preview.status`.

Delete the legacy `episode_choices` and `remap_preview_to_episode` methods AFTER Task 12 rewires their only caller (`_media_workspace_actions.py`); leave them in place for this task.

Also update `build_queue_preflight`: when `state.assignments` is present, take `conflicts = len(state.assignments.conflicts())` instead of counting projected conflict rows (same number, but table is authoritative).

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_episode_mapping_projection.py tests/test_episode_projection_cache.py tests/test_media_controller.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```powershell
git add plex_renamer/app tests
git commit -m "feat: table-backed EpisodeMappingService operations and slot choices"
```

---

### Task 11: GUI — per-row actions menu on episode guide rows

**Files:**
- Modify: `plex_renamer/gui_qt/widgets/_workspace_widgets.py:420-579` (`EpisodeGuideRowWidget`)
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_preview.py:744-787`
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_actions.py` (dispatch)
- Test: `tests/test_qt_workspace_widgets.py`

All sizing through `_scale` — no bare pixel literals.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_qt_workspace_widgets.py`, following that file's existing Qt fixture conventions — it already has a `qapp`-style fixture; reuse it):

```python
from plex_renamer.gui_qt.widgets._workspace_widgets import EpisodeGuideRowWidget


class TestEpisodeGuideRowActions:
    def test_actions_menu_button_present(self, qapp):
        widget = EpisodeGuideRowWidget(
            title="S01E01 - Pilot", status="Mapped",
            actions=[("reassign", "Reassign..."), ("unassign", "Unassign")],
        )
        assert widget.actions_button() is not None
        labels = [action.text() for action in widget.actions_menu().actions()]
        assert labels == ["Reassign...", "Unassign"]

    def test_action_signal_carries_action_id(self, qapp):
        widget = EpisodeGuideRowWidget(
            title="S01E01 - Pilot", status="Mapped",
            actions=[("unassign", "Unassign")],
        )
        fired: list[str] = []
        widget.action_requested.connect(fired.append)
        widget.actions_menu().actions()[0].trigger()
        assert fired == ["unassign"]

    def test_no_actions_hides_button(self, qapp):
        widget = EpisodeGuideRowWidget(
            title="S01E02 - Missing", status="Missing File", actions=[],
        )
        assert widget.actions_button() is None or not widget.actions_button().isVisible()

    def test_approve_quick_button_only_for_review(self, qapp):
        review = EpisodeGuideRowWidget(
            title="S01E01", status="Review",
            actions=[("approve", "Approve"), ("reassign", "Reassign...")],
        )
        mapped = EpisodeGuideRowWidget(
            title="S01E01", status="Mapped",
            actions=[("reassign", "Reassign...")],
        )
        assert review.approve_button().isVisibleTo(review)
        assert not mapped.approve_button().isVisibleTo(mapped)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_qt_workspace_widgets.py -v -k EpisodeGuideRowActions`
Expected: FAIL (`TypeError: unexpected keyword 'actions'`)

- [ ] **Step 3: Rework `EpisodeGuideRowWidget`**

Replace the two-signal/two-button design with an action list:

- Constructor gains `actions: list[tuple[str, str]] | None = None` (list of `(action_id, label)`).
- Replace `approve_requested = Signal()` / `fix_requested = Signal()` with `action_requested = Signal(str)`.
- Keep an inline **Approve** `QPushButton` shown only when an `("approve", …)` action is present (one-click for the common case); clicking emits `action_requested.emit("approve")`.
- Add a `⋯` `QToolButton` (`setText("⋯")`, `setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)`, fixed height `_scale.row_height(rows=1, padding=10)`, fixed width `_scale.px(28)`) with a `QMenu` containing every action except `approve`; each `QAction.triggered` emits `action_requested.emit(action_id)`.
- Expose test hooks: `def actions_button(self) -> QToolButton | None`, `def actions_menu(self) -> QMenu`, `def approve_button(self) -> QPushButton`.
- When `actions` is empty, don't create the tool button.
- Existing geometry code stays; the buttons join the existing `confidence_row` layout where `_approve_button`/`_fix_button` sat (lines 536-562). Delete `_fix_button`.
- While editing this widget, replace the bare literals in its `__init__` with scale tokens: `layout.setContentsMargins(8, 7, 8, 7)` → `layout.setContentsMargins(_scale.margins(7, 8))`, `layout.setSpacing(8)` → `layout.setSpacing(_scale.px(8))`, `body.setSpacing(3)` → `body.setSpacing(_scale.px(3))`, `top_row.setSpacing(8)` → `top_row.setSpacing(_scale.px(8))`, `confidence_row.setSpacing(8)` → `confidence_row.setSpacing(_scale.px(8))`. (`margins()` returns `QMargins` — pass it via `layout.setContentsMargins(_scale.margins(7, 8))` which accepts a QMargins overload.)

- [ ] **Step 4: Rewire the caller** in `_media_workspace_preview.py` `_attach_episode_guide_widget` (lines 755-787): compute the action list from the row and connect once:

```python
    def _attach_episode_guide_widget(self, item: QListWidgetItem, state: ScanState, row) -> None:
        original = row.primary_file.original.name if row.primary_file is not None else ""
        companions = [companion.original.name for companion in row.companions]
        title = f"S{row.season:02d}E{row.episode:02d}"
        if row.title:
            title = f"{title} - {row.title}"
        actions = self._episode_row_actions(row)
        widget = _EpisodeGuideRowWidget(
            title=title,
            status=row.status,
            original=original,
            target=row.target_rename,
            confidence=row.confidence_label,
            companions=companions,
            actions=actions,
            parent=self._list_widget,
        )
        if self._episode_row_action is not None:
            widget.action_requested.connect(
                lambda action_id, state=state, row=row: self._episode_row_action(
                    state, row, action_id,
                )
            )
        widget.clicked.connect(lambda item=item: self._list_widget.setCurrentItem(item))
        self._sync_item_height(item, widget)
        self._list_widget.setItemWidget(item, widget)

    @staticmethod
    def _episode_row_actions(row) -> list[tuple[str, str]]:
        if row.status == "Missing File":
            return [("assign_file", "Assign file...")]
        if row.status == "Conflict":
            return [
                ("keep_this", "Keep this file (unassign others)"),
                ("reassign", "Reassign..."),
                ("unassign", "Unassign"),
            ]
        actions: list[tuple[str, str]] = []
        if row.status == "Review":
            actions.append(("approve", "Approve"))
        actions.append(("reassign", "Reassign..."))
        actions.append(("unassign", "Unassign"))
        return actions
```

The widget's constructor signature changes; the old `approve_episode_callback`/`fix_episode_callback` constructor params of the preview component (lines 59-71) become one `episode_row_action_callback` (`self._episode_row_action`). Update the component construction site (grep for `approve_episode_callback` — it is wired in `_media_workspace_ui.py` or `media_workspace.py`) to pass the coordinator dispatch from Task 12. Until Task 12 lands, pass a no-op lambda so this task stays green.

- [ ] **Step 5: Run Qt widget tests**

Run: `python -m pytest tests/test_qt_workspace_widgets.py tests/test_qt_media_workspace.py -v`
Expected: PASS (update any test pinning `approve_requested`/`fix_requested` signal names to the new `action_requested`).

- [ ] **Step 6: Commit**

```powershell
git add plex_renamer/gui_qt tests
git commit -m "feat: per-row actions menu on episode guide rows"
```

---

### Task 12: GUI — assignment dialog (both directions) and dispatch

**Files:**
- Create: `plex_renamer/gui_qt/widgets/episode_assign_dialog.py`
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_actions.py` (replace `EpisodeChoiceDialog`, `prompt_fix_episode_mapping`, `approve_episode_mapping`, `approve_all_episode_mappings`; add `handle_episode_row_action`)
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_preview.py` (unassigned-files section)
- Modify: `plex_renamer/app/services/episode_mapping_service.py` (delete legacy `episode_choices` / `remap_preview_to_episode`)
- Test: `tests/test_qt_media_workspace.py`

- [ ] **Step 1: Write the failing dialog tests** (append to `tests/test_qt_media_workspace.py`):

```python
from plex_renamer.app.models.state_models import EpisodeSlotChoice
from plex_renamer.gui_qt.widgets.episode_assign_dialog import EpisodeAssignDialog


def slot_choices():
    return [
        EpisodeSlotChoice(season=1, episode=1, title="Pilot", claimed_by="e1.mkv"),
        EpisodeSlotChoice(season=1, episode=2, title="Heist"),
        EpisodeSlotChoice(season=1, episode=3, title="Endgame"),
        EpisodeSlotChoice(season=2, episode=1, title="Reboot"),
    ]


class TestEpisodeAssignDialog:
    def test_contiguous_same_season_selection_enables_ok(self, qapp):
        dialog = EpisodeAssignDialog(slots=slot_choices())
        dialog.set_checked([(1, 2), (1, 3)])
        assert dialog.is_selection_valid()

    def test_non_contiguous_selection_disables_ok(self, qapp):
        dialog = EpisodeAssignDialog(slots=slot_choices())
        dialog.set_checked([(1, 1), (1, 3)])
        assert not dialog.is_selection_valid()
        assert "contiguous" in dialog.validation_text().lower()

    def test_cross_season_selection_disables_ok(self, qapp):
        dialog = EpisodeAssignDialog(slots=slot_choices())
        dialog.set_checked([(1, 3), (2, 1)])
        assert not dialog.is_selection_valid()
        assert "season" in dialog.validation_text().lower()

    def test_claimed_slot_shows_claimant(self, qapp):
        dialog = EpisodeAssignDialog(slots=slot_choices())
        assert "e1.mkv" in dialog.slot_row_text(1, 1)

    def test_selected_episodes_returned(self, qapp):
        dialog = EpisodeAssignDialog(slots=slot_choices())
        dialog.set_checked([(1, 2), (1, 3)])
        assert dialog.selected_episodes() == [(1, 2), (1, 3)]
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_qt_media_workspace.py -v -k EpisodeAssignDialog`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Implement the dialog**

Create `plex_renamer/gui_qt/widgets/episode_assign_dialog.py`:

```python
"""Episode assignment dialog: multi-select slots or pick a file.

Both directions of the fix flow share this module:
  - ``EpisodeAssignDialog`` (file -> episodes, multi-select, contiguity-gated)
  - ``EpisodeAssignDialog.pick_file`` (episode -> file, single-select)

All sizing flows through gui_qt._scale (HiDPI requirement).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from .. import _scale
from ...app.models.state_models import EpisodeSlotChoice

_SLOT_ROLE = Qt.ItemDataRole.UserRole


class EpisodeAssignDialog(QDialog):
    """Season-grouped multi-select episode picker with contiguity gating."""

    def __init__(self, *, slots: list[EpisodeSlotChoice], parent=None, title: str = "Assign Episodes") -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(_scale.px(420))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(_scale.margins(8))
        layout.setSpacing(_scale.px(6))

        self._list = QListWidget(self)
        self._list.setUniformItemSizes(True)
        current_season: int | None = None
        for choice in slots:
            if choice.season != current_season:
                current_season = choice.season
                header_text = "Specials" if choice.season == 0 else f"Season {choice.season:02d}"
                header = QListWidgetItem(header_text)
                header.setFlags(Qt.ItemFlag.NoItemFlags)
                self._list.addItem(header)
            text = choice.label
            if choice.claimed_by:
                text = f"{text}    [claimed by {choice.claimed_by}]"
            else:
                text = f"{text}    [missing]"
            item = QListWidgetItem(text)
            item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setData(_SLOT_ROLE, (choice.season, choice.episode))
            self._list.addItem(item)
        self._list.itemChanged.connect(lambda _item: self._revalidate())
        layout.addWidget(self._list)

        self._validation = QLabel("", self)
        self._validation.setProperty("cssClass", "caption")
        self._validation.setWordWrap(True)
        layout.addWidget(self._validation)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)
        self._revalidate()

    # ── selection state ─────────────────────────────────────────────

    def _checked_keys(self) -> list[tuple[int, int]]:
        keys: list[tuple[int, int]] = []
        for index in range(self._list.count()):
            item = self._list.item(index)
            key = item.data(_SLOT_ROLE)
            if key is not None and item.checkState() == Qt.CheckState.Checked:
                keys.append(tuple(key))
        return sorted(keys)

    def selected_episodes(self) -> list[tuple[int, int]]:
        return self._checked_keys()

    def set_checked(self, keys: list[tuple[int, int]]) -> None:
        wanted = set(keys)
        for index in range(self._list.count()):
            item = self._list.item(index)
            key = item.data(_SLOT_ROLE)
            if key is None:
                continue
            item.setCheckState(
                Qt.CheckState.Checked if tuple(key) in wanted
                else Qt.CheckState.Unchecked
            )
        self._revalidate()

    def _validate(self) -> str:
        keys = self._checked_keys()
        if not keys:
            return "Select at least one episode."
        seasons = {season for season, _episode in keys}
        if len(seasons) > 1:
            return "All selected episodes must be in the same season."
        episodes = [episode for _season, episode in keys]
        if any(b - a != 1 for a, b in zip(episodes, episodes[1:])):
            return "Selected episodes must be a contiguous run."
        return ""

    def is_selection_valid(self) -> bool:
        return self._validate() == ""

    def validation_text(self) -> str:
        return self._validation.text()

    def slot_row_text(self, season: int, episode: int) -> str:
        for index in range(self._list.count()):
            item = self._list.item(index)
            if item.data(_SLOT_ROLE) == (season, episode):
                return item.text()
        return ""

    def _revalidate(self) -> None:
        message = self._validate()
        self._validation.setText(message)
        ok = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok is not None:
            ok.setEnabled(message == "")

    # ── entry points ────────────────────────────────────────────────

    @classmethod
    def pick_episodes(
        cls,
        *,
        parent,
        title: str,
        slots: list[EpisodeSlotChoice],
        preselected: list[tuple[int, int]] | None = None,
    ) -> list[tuple[int, int]] | None:
        dialog = cls(slots=slots, parent=parent, title=title)
        if preselected:
            dialog.set_checked(preselected)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        selection = dialog.selected_episodes()
        return selection or None

    @staticmethod
    def pick_file(
        *,
        parent,
        title: str,
        unassigned: list[tuple[int, str]],
        assigned: list[tuple[int, str]],
    ) -> int | None:
        """Single-select file picker; returns the chosen file_id."""
        dialog = QDialog(parent)
        dialog.setWindowTitle(title)
        dialog.setMinimumWidth(_scale.px(420))
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(_scale.margins(8))
        layout.setSpacing(_scale.px(6))

        list_widget = QListWidget(dialog)

        def add_group(header_text: str, entries: list[tuple[int, str]]) -> None:
            if not entries:
                return
            header = QListWidgetItem(header_text)
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            list_widget.addItem(header)
            for file_id, label in entries:
                item = QListWidgetItem(label)
                item.setData(_SLOT_ROLE, file_id)
                list_widget.addItem(item)

        add_group("Unassigned files", unassigned)
        add_group("Already assigned (will be reassigned)", assigned)
        list_widget.itemDoubleClicked.connect(lambda _item: dialog.accept())
        layout.addWidget(list_widget)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        item = list_widget.currentItem()
        if item is None:
            return None
        file_id = item.data(_SLOT_ROLE)
        return int(file_id) if file_id is not None else None
```

- [ ] **Step 4: Replace the coordinator flows** in `_media_workspace_actions.py`:

Delete `EpisodeChoiceDialog` (lines 56-101). Replace `approve_episode_mapping` / `approve_all_episode_mappings` / `prompt_fix_episode_mapping` bodies with service delegation, and add the dispatch:

```python
    def handle_episode_row_action(self, state: ScanState, row, action_id: str) -> None:
        workspace = self._workspace
        if state.queued or state.scanning:
            workspace.status_message.emit(
                "Finish or cancel the queued/scanning state first.", 3000,
            )
            return
        service = EpisodeMappingService()
        preview = row.primary_file
        try:
            if action_id == "approve" and preview is not None:
                service.approve_file(state, preview)
                message = "Episode mapping approved."
            elif action_id == "unassign" and preview is not None:
                service.unassign_file(state, preview)
                message = "File unassigned."
            elif action_id == "keep_this" and preview is not None:
                service.resolve_conflict(state, row.season, row.episode, preview)
                message = "Conflict resolved."
            elif action_id == "reassign" and preview is not None:
                selection = EpisodeAssignDialog.pick_episodes(
                    parent=workspace,
                    title=f"Assign \"{preview.original.name}\"",
                    slots=service.episode_slot_choices(state),
                    preselected=[
                        (preview.season, episode)
                        for episode in preview.episodes
                        if preview.season is not None
                    ],
                )
                if selection is None:
                    return
                season = selection[0][0]
                episodes = [episode for _season, episode in selection]
                service.assign_file(state, preview, season=season, episodes=episodes)
                message = "Episode mapping updated."
            elif action_id == "assign_file":
                table = state.assignments
                unassigned: list[tuple[int, str]] = []
                for candidate in service.unassigned_file_previews(state):
                    if candidate.file_id is None:
                        continue
                    reason = table.unassigned_reasons.get(candidate.file_id, "")
                    label = (
                        f"{candidate.original.name}  ({reason})"
                        if reason else candidate.original.name
                    )
                    unassigned.append((candidate.file_id, label))
                assigned = [
                    (item.file_id, item.original.name)
                    for item in state.preview_items
                    if item.file_id is not None and item.new_name is not None
                ]
                file_id = EpisodeAssignDialog.pick_file(
                    parent=workspace,
                    title=f"Assign file to S{row.season:02d}E{row.episode:02d}",
                    unassigned=unassigned,
                    assigned=assigned,
                )
                if file_id is None:
                    return
                target = next(
                    item for item in state.preview_items if item.file_id == file_id
                )
                service.assign_file(
                    state, target, season=row.season, episodes=[row.episode],
                )
                message = "File assigned."
            else:
                return
        except ValueError as exc:
            QMessageBox.warning(workspace, "Episode Assignment Failed", str(exc))
            return
        workspace._ensure_check_bindings(state)
        _refresh_episode_projection(workspace, state)
        workspace._populate_preview(state)
        workspace._update_action_bar()
        workspace.status_message.emit(message, 3000)
```

Import `EpisodeAssignDialog` at the top. `approve_episode_mapping` becomes `service.approve_file(...)` + the same refresh tail; `approve_all_episode_mappings` becomes `count = service.approve_all(state)` + refresh tail. Wire `handle_episode_row_action` as the preview component's `episode_row_action_callback` from Task 11 (replace the no-op lambda at the construction site).

Unassigned-files section in `_media_workspace_preview.py`: in the episode-guide render path (where `guide.rows` are rendered), render `guide.unmapped_primary_files` FIRST under a header `"NEEDS ASSIGNMENT"`; each as an `_EpisodeGuideRowWidget` with `title=row.original.name`, `status="Unassigned"`, `original=str(row.reason)`, `actions=[("reassign", "Assign to episode...")]`, and a synthetic guide-row object for dispatch: reuse `EpisodeGuideRow(season=preview.season or 0, episode=preview.episodes[0] if preview.episodes else 0, status="Unassigned", primary_file=row.preview)`. Find the render loop by grepping `_attach_episode_guide_widget` callers in the same file.

Delete the now-unused legacy service methods `episode_choices` and `remap_preview_to_episode` and their callers.

- [ ] **Step 5: Run the Qt suites**

Run: `python -m pytest tests/test_qt_media_workspace.py tests/test_qt_workspace_widgets.py tests/test_episode_mapping_projection.py -v`
Expected: PASS. Then run the smoke wrapper: `scripts\test-smoke.cmd` and check exit code 0 (full log in `.pytest_cache/smoke/latest.log`).

- [ ] **Step 6: Commit**

```powershell
git add plex_renamer tests
git commit -m "feat: bidirectional episode assignment dialog and row action dispatch"
```

---

### Task 13: Queue-boundary parity and final verification

**Files:**
- Test: `tests/test_episode_projection.py` (extend)
- Modify: none expected (this task is verification; fix regressions where found)

- [ ] **Step 1: Write the parity test** (append to `tests/test_episode_projection.py`)

```python
class TestQueueBoundaryParity:
    def test_projection_feeds_rename_ops(self, tmp_path):
        """scan -> table -> projection -> RenameOps stays well-formed."""
        from plex_renamer.engine._queue_bridge import build_rename_job_from_state
        from plex_renamer.engine import ScanState

        root = tmp_path / "Demo Show (2020)"
        season = root / "Season 01"
        season.mkdir(parents=True)
        (season / "Demo Show S01E01.mkv").touch()
        (season / "Demo Show S01E02 - Heist.mkv").touch()

        table = make_table()
        first = table.add_file(
            season / "Demo Show S01E01.mkv", is_season_relative=True,
        )
        second = table.add_file(
            season / "Demo Show S01E02 - Heist.mkv",
            is_season_relative=True, raw_title="Heist",
        )
        table.assign(first.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=0.96)
        table.assign(second.file_id, 1, [2], origin=ORIGIN_AUTO, confidence=0.96)

        state = ScanState(folder=root, media_info=SHOW_INFO)
        state.assignments = table
        state.preview_items = project_preview_items(
            table, show_info=SHOW_INFO, root=root, media_fields=MEDIA_FIELDS,
        )
        state.scanned = True
        checked = {0, 1}
        job = build_rename_job_from_state(
            state, tmp_path, tmp_path, checked_indices=checked,
        )
        video_ops = [op for op in job.rename_ops if op.file_type == "video"]
        assert len(video_ops) == 2
        assert all(op.new_name for op in video_ops)
        assert video_ops[0].episodes == [1]
        assert video_ops[1].episodes == [2]
```

(Adjust `make_table` import/reuse — it lives in this test module from Task 4; `SHOW_INFO`/`MEDIA_FIELDS` constants are defined at the top. The table here needs S1 slots named to match: reuse `make_table()` which registers `Pilot`/`The Heist`/`Endgame`.)

- [ ] **Step 2: Run it**

Run: `python -m pytest tests/test_episode_projection.py -v -k Parity`
Expected: PASS (this guards the boundary; failure means projection broke `is_actionable`/status contracts).

- [ ] **Step 3: Full suite + smoke**

Run: `python -m pytest tests -q --ignore=tests/test_qt_main_window.py`
Then: `python -m pytest tests/test_qt_main_window.py -q`
Then: `scripts\test-smoke.cmd`
Expected: everything ≥ baseline, smoke exit 0.

- [ ] **Step 4: Dead-code sweep**

Grep for and remove if orphaned: `match_special`, `scan_nested_extras`, `fuzzy_match_special` (engine `__init__.py` exports too), `resolve_duplicate_episodes`, `apply_episode_confidence_adjustments`, `apply_episode_review_threshold`, `EpisodeChoiceDialog`, `remap_preview_to_episode`, `episode_choices`. `fuzzy_match_special` stays only if `_tv_scanner_consolidated.py` or the detail panel still imports it.

- [ ] **Step 5: Commit**

```powershell
git add -A
git commit -m "test: queue-boundary parity for table projection; remove dead matching paths"
```

---

## Self-review checklist (run after Task 13)

1. **Spec coverage** — every numbered problem in the spec's Problem section maps to: (1)+(2) Task 3 rules 2/3 + Task 6 specials tests; (3) Task 4/6 unmatched-specials tests; (4) Task 9; (5) Task 6 conflict test + Task 12 `keep_this`; (6) Task 1; (7) Tasks 10-12; (8) Task 9 + Task 5 calibration. Manual-survives-rescan: Task 8 `carry_over_manual_assignments`.
2. **HiDPI** — grep new/modified GUI files for `setContentsMargins(` / `setSpacing(` / `setFixedWidth(` / `setMinimumWidth(` with integer literals not wrapped in `_scale.`; fix any.
3. **Duplicate/version room** — `role` field round-trips through `merge_tables` and is never read by policy except as default `primary`.
4. **mkvmerge room** — row actions are data-driven `(action_id, label)` lists; adding "Tracks…" later is one list entry + one dispatch branch.
