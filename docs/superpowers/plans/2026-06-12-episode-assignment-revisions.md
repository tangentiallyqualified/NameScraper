# Episode Assignment Revisions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix six defects in the episode-assignment redesign: chained multi-episode parsing, two-bucket review categorization, mixed-folder specials/title matching, specials confidence trust, and extending a file to a second episode.

**Architecture:** Build on the existing `EpisodeAssignmentTable` + `resolve_file` policy. The consolidated/mixed-folder scan path is brought onto the same table-building approach as the normal path (register all season slots including Season 0, route every file through `resolve_file`). The roster gains a shared `has_episode_problems` predicate driving two review groups. No data-model changes.

**Tech Stack:** Python 3, PySide6 (Qt), pytest. Windows + PowerShell. Commits go through `scripts/git-publish.cmd` per `CLAUDE.md`; the `git commit` lines below show the intended message/scope — use the publish workflow to actually commit.

**Spec:** `docs/superpowers/specs/2026-06-12-episode-assignment-revisions-design.md`

**Run tests with:** `python -m pytest <path> -v` from the repo root. Qt smoke runs use `scripts/test-smoke.cmd`.

---

## File Structure

Files created or modified, by responsibility:

- `plex_renamer/_parsing_episodes.py` — `extract_episode`: collect chained multi-episode runs (Task 1).
- `plex_renamer/engine/_episode_resolution.py` — title-vs-number exact-override guard + specials number-only confidence + season-0 floor guard + `season` param on `resolve_file` (Tasks 2, 3).
- `plex_renamer/engine/_tv_scanner_normal.py` — pass `season` into `resolve_file` (Task 3).
- `plex_renamer/engine/_tv_scanner_consolidated.py` — new `build_consolidated_table` (Task 4).
- `plex_renamer/engine/_tv_scanner.py` — `_build_consolidated_preview` uses the new table builder (Task 4).
- `plex_renamer/gui_qt/widgets/_media_helpers.py` — `has_episode_problems` + two-bucket `roster_group`/`state_status`/`state_status_tone` (Task 5).
- `plex_renamer/gui_qt/widgets/_media_workspace_roster.py` — two review group headers (Task 5).
- `plex_renamer/gui_qt/widgets/_media_workspace_refresh.py` — update the two `roster_group` key references (Task 5).
- `plex_renamer/app/services/episode_mapping_service.py` — `assign_or_extend_file` (Task 6).
- `plex_renamer/gui_qt/widgets/_media_workspace_actions.py` — missing-row action calls `assign_or_extend_file` (Task 6).
- Tests: `tests/test_episode_resolution.py` (extend), `tests/test_episode_mapping_projection.py` (extend), `tests/test_consolidated_assignments.py` (new), `tests/test_roster_classification.py` (new), `tests/test_qt_workspace_widgets.py` (update one assertion).

---

## Task 1: Parser — chained multi-episode ranges

**Files:**
- Modify: `plex_renamer/_parsing_episodes.py:21-75` (the `S##E##` and `NxNN` branches of `extract_episode`)
- Test: `tests/test_episode_resolution.py` (the existing `TestMultiEpisodeRuns` / `TestRangeFalsePositives` classes already cover most cases)

The `S##E##` regex captures a single optional range-end, so `S01E01-E02-E03` drops `E03`. Collect every chained segment into one list; expand only a lone gapped endpoint as a range.

- [ ] **Step 1: Add failing tests for chained runs**

Add to the `TestMultiEpisodeRuns` class in `tests/test_episode_resolution.py`:

```python
    def test_chained_dash_e_run_three(self):
        eps, _, rel = extract_episode(
            "ChalkZone.S01E01-E02-E03.DVDRip.1080p.mkv"
        )
        assert eps == [1, 2, 3]
        assert rel is True

    def test_chained_dash_e_run_four(self):
        eps, _, rel = extract_episode("Show S01E01-E02-E03-E04.mkv")
        assert eps == [1, 2, 3, 4]
        assert rel is True

    def test_chained_nxnn_run_three(self):
        eps, _, rel = extract_episode("Show 1x01-1x02-1x03.mkv")
        assert eps == [1, 2, 3]
        assert rel is True

    def test_chained_nxnn_bare_run_three(self):
        eps, _, rel = extract_episode("Show 1x01-02-03.mkv")
        assert eps == [1, 2, 3]
        assert rel is True
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `python -m pytest tests/test_episode_resolution.py::TestMultiEpisodeRuns -v`
Expected: the four new tests FAIL (e.g. `assert [1, 2] == [1, 2, 3]`); the pre-existing ones PASS.

- [ ] **Step 3: Replace the `S##E##` branch**

In `plex_renamer/_parsing_episodes.py`, replace the first `match = re.search(...)` block (currently lines 41-54, the one matching `S(\d+)((?:E\d+)+)...`) with:

```python
    sxe = re.search(r"S(\d+)((?:E\d+)+)", name, re.IGNORECASE)
    if sxe:
        points = [int(num) for num in re.findall(r"E(\d+)", sxe.group(2), re.IGNORECASE)]
        rest = name[sxe.end():]
        segment_re = re.compile(
            r"^(?:-E(\d+)\b|-(\d+)\b(?![a-zA-Z])|\s+-\s+E(\d+)\b)",
            re.IGNORECASE,
        )
        while True:
            seg = segment_re.match(rest)
            if not seg:
                break
            points.append(int(seg.group(1) or seg.group(2) or seg.group(3)))
            rest = rest[seg.end():]
        if len(points) == 2 and points[1] - points[0] > 1:
            episodes = _expand_range(points[0], points[1])
        else:
            episodes = points
        title = re.sub(r"^\s*[-.]?\s*", "", rest).strip() or None
        return episodes, title, True
```

- [ ] **Step 4: Replace the `NxNN` branch**

Immediately below, replace the second `match = re.search(...)` block (currently lines 60-75, the `\b(\d{1,2})x(\d{2,3})...` one) with:

```python
    nxn = re.search(r"\b(\d{1,2})x(\d{2,3})", name, re.IGNORECASE)
    if nxn:
        season_prefix = nxn.group(1)
        points = [int(nxn.group(2))]
        rest = name[nxn.end():]
        segment_re = re.compile(
            rf"^(?:-(?:{season_prefix}x)?(\d{{2,3}})(?![a-zA-Z])"
            rf"|\s+-\s+{season_prefix}x(\d{{2,3}})(?![a-zA-Z]))",
            re.IGNORECASE,
        )
        while True:
            seg = segment_re.match(rest)
            if not seg:
                break
            points.append(int(seg.group(1) or seg.group(2)))
            rest = rest[seg.end():]
        if len(points) == 2 and points[1] - points[0] > 1:
            episodes = _expand_range(points[0], points[1])
        else:
            episodes = points
        title = re.sub(r"^\s*[-.]?\s*", "", rest).strip() or None
        return episodes, title, True
```

- [ ] **Step 5: Run the full parser suite**

Run: `python -m pytest tests/test_episode_resolution.py::TestMultiEpisodeRuns tests/test_episode_resolution.py::TestRangeFalsePositives -v`
Expected: ALL pass (new chained tests + every pre-existing range / false-positive case).

- [ ] **Step 6: Commit**

```bash
git add plex_renamer/_parsing_episodes.py tests/test_episode_resolution.py
git commit -m "fix: collect chained multi-episode runs (S01E01-E02-E03)"
```

---

## Task 2: Resolution policy — title-vs-number exact-override guard

**Files:**
- Modify: `plex_renamer/engine/_episode_resolution.py:182-199` (the `valid_numbers and title_match` block in `resolve_file`)
- Test: `tests/test_episode_resolution.py` (`TestResolutionRules`)

A substring (non-exact) title match for a *different* episode currently overrides a valid parsed number (rule 2). Restrict the override to **exact** title matches so a valid number is only displaced when the title is an exact match for another episode; otherwise keep the number and cap it (rule 3, lands in review).

- [ ] **Step 1: Add a failing test**

Add to the `TestResolutionRules` class in `tests/test_episode_resolution.py`:

```python
    def test_substring_offnumber_does_not_override_valid_number(self):
        # Parsed E2 is valid; title substring-matches E3 only. Keep the
        # number (capped to review) rather than silently renumbering to E3.
        res = resolve_file(
            parsed_episodes=(2,), raw_title="Endgame",
            is_season_relative=True,
            season_titles={1: "Pilot", 2: "The Heist", 3: "Endgame Saga"},
        )
        assert res.episodes == (2,)
        assert res.confidence <= CONF_WEAK_TITLE_NUMBER_CAP
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_episode_resolution.py::TestResolutionRules::test_substring_offnumber_does_not_override_valid_number -v`
Expected: FAIL — currently returns `episodes == (3,)` at `CONF_TITLE_WINS`.

- [ ] **Step 3: Tighten the override condition**

In `plex_renamer/engine/_episode_resolution.py`, the block currently reads:

```python
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
```

Change the rule-2 condition from `if strong_title:` to require an exact match:

```python
        if strong_title and title_match.strength >= _TITLE_EXACT:
            return Resolution(  # rule 2
                episodes=(title_match.episode,),
                confidence=CONF_TITLE_WINS,
                evidence=frozenset({"title-strong", "number-disagree"}),
            )
```

(`_TITLE_EXACT == 1.0` is already defined at module top. Leave rules 1 and 3 unchanged.)

- [ ] **Step 4: Run the resolution suite**

Run: `python -m pytest tests/test_episode_resolution.py::TestResolutionRules tests/test_episode_resolution.py::TestTitleStrength -v`
Expected: ALL pass (the new test plus `test_rule2_strong_title_beats_number`, which uses the exact title "Special A").

- [ ] **Step 5: Commit**

```bash
git add plex_renamer/engine/_episode_resolution.py tests/test_episode_resolution.py
git commit -m "fix: only exact title overrides a valid episode number"
```

---

## Task 3: Resolution policy — specials number-only forces review

**Files:**
- Modify: `plex_renamer/engine/_episode_resolution.py` (`resolve_file` signature + rule-4 block; `apply_confidence_adjustments` floor guard; new constant)
- Modify: `plex_renamer/engine/_tv_scanner_normal.py:63-68` (pass `season` into `resolve_file`)
- Test: `tests/test_episode_resolution.py`

TMDB Season 0 numbering is unreliable. A special resolved on the `S00E##` number with no title corroboration must land in review (confidence below the auto-accept threshold), and the season-relative confidence floor must not lift it back up.

- [ ] **Step 1: Add failing tests**

Add to `tests/test_episode_resolution.py`. First extend the policy import block near line 118 to include the new constant and the threshold default:

```python
from plex_renamer.engine._episode_resolution import (
    CONF_AGREE,
    CONF_NUMBER_INFERRED,
    CONF_NUMBER_RELATIVE,
    CONF_SPECIAL_NUMBER_ONLY,
    CONF_TITLE_ONLY,
    CONF_TITLE_WINS,
    CONF_WEAK_TITLE_NUMBER_CAP,
    STRONG_TITLE_STRENGTH,
    match_title_in_titles,
    resolve_file,
)
from plex_renamer.engine._state import DEFAULT_EPISODE_AUTO_ACCEPT_THRESHOLD
```

Then add a new test class:

```python
class TestSpecialsTrust:
    def test_special_number_only_forces_review(self):
        res = resolve_file(
            parsed_episodes=(8,), raw_title=None,
            is_season_relative=True,
            season_titles={8: "How to Draw Eddy"}, season=0,
        )
        assert res.episodes == (8,)
        assert res.confidence == CONF_SPECIAL_NUMBER_ONLY
        assert res.confidence < DEFAULT_EPISODE_AUTO_ACCEPT_THRESHOLD

    def test_special_strong_title_still_wins(self):
        # Exact title for E12 overrides the parsed S00E08 number.
        res = resolve_file(
            parsed_episodes=(8,), raw_title="The Grim Adventures of the KND",
            is_season_relative=True,
            season_titles={8: "How to Draw Eddy", 12: "The Grim Adventures of the KND"},
            season=0,
        )
        assert res.episodes == (12,)
        assert res.confidence == CONF_TITLE_WINS

    def test_regular_season_number_only_unchanged(self):
        res = resolve_file(
            parsed_episodes=(4,), raw_title=None,
            is_season_relative=True, season_titles=S1_TITLES, season=1,
        )
        assert res.confidence == CONF_NUMBER_RELATIVE
```

Add to the `TestConfidenceAdjustments` class (near line 275) a test that the cap survives adjustment:

```python
    def test_special_number_only_survives_adjustments(self):
        from plex_renamer.engine._episode_resolution import CONF_SPECIAL_NUMBER_ONLY
        from plex_renamer.engine._state import DEFAULT_EPISODE_AUTO_ACCEPT_THRESHOLD
        table = EpisodeAssignmentTable()
        table.add_slot(EpisodeSlot(season=0, episode=8, title="How to Draw Eddy"))
        entry = table.add_file(
            Path("Demo Show - S00E08 - Some Special.mkv"),
            is_season_relative=True, raw_title="Some Special",
        )
        table.assign(
            entry.file_id, 0, [8], origin=ORIGIN_AUTO,
            confidence=CONF_SPECIAL_NUMBER_ONLY,
            evidence=frozenset({"number", "special-number-only"}),
        )
        apply_confidence_adjustments(table, show_info=SHOW)
        assert (
            table.assignment_for(entry.file_id).confidence
            < DEFAULT_EPISODE_AUTO_ACCEPT_THRESHOLD
        )
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_episode_resolution.py::TestSpecialsTrust tests/test_episode_resolution.py::TestConfidenceAdjustments::test_special_number_only_survives_adjustments -v`
Expected: FAIL — `CONF_SPECIAL_NUMBER_ONLY` does not exist and `resolve_file` has no `season` parameter (ImportError / TypeError).

- [ ] **Step 3: Add the constant**

In `plex_renamer/engine/_episode_resolution.py`, in the calibration-constants block (near line 28-35), add:

```python
CONF_SPECIAL_NUMBER_ONLY = 0.50  # season-0 number with no title match -> REVIEW
```

- [ ] **Step 4: Add the `season` parameter and the specials branch to `resolve_file`**

Change the signature (currently line 168-174):

```python
def resolve_file(
    *,
    parsed_episodes: tuple[int, ...],
    raw_title: str | None,
    is_season_relative: bool,
    season_titles: dict[int, str],
    season: int | None = None,
) -> Resolution:
    """Apply the 6-rule resolution policy for one file against one season."""
```

In the rule-4 block (currently lines 201-217), insert the season-0 branch before the existing relative/inferred confidence logic:

```python
    if valid_numbers:
        if _has_ambiguous_title_evidence(raw_title, season_titles):  # rule 3 (ambiguous)
            return Resolution(
                episodes=valid_numbers,
                confidence=CONF_WEAK_TITLE_NUMBER_CAP,
                evidence=frozenset({"number", "title-ambiguous"}),
            )
        if season == 0:
            # Season-0 numbering varies by source; a bare number is not
            # trustworthy on its own -> force review.
            return Resolution(
                episodes=valid_numbers,
                confidence=CONF_SPECIAL_NUMBER_ONLY,
                evidence=frozenset({"number", "special-number-only"}),
            )
        # rule 4: no usable title evidence
        confidence = CONF_NUMBER_RELATIVE if is_season_relative else CONF_NUMBER_INFERRED
        evidence = {"number"}
        if is_season_relative:
            evidence.add("season-relative")
        return Resolution(
            episodes=valid_numbers,
            confidence=confidence,
            evidence=frozenset(evidence),
        )
```

- [ ] **Step 5: Guard the season-relative floors for Season 0**

In `apply_confidence_adjustments` (currently lines 320-332), the floors keyed on `is_season_relative` must not lift a Season-0 number-only assignment. Change:

```python
        if entry.is_season_relative:
            confidence = max(confidence, EXPLICIT_EPISODE_FLOOR)
```

to:

```python
        if entry.is_season_relative and assignment.season != 0:
            confidence = max(confidence, EXPLICIT_EPISODE_FLOOR)
```

and in the source-prefix block just below, change:

```python
            if compatible and entry.is_season_relative:
                confidence = max(confidence, COMPATIBLE_PREFIX_FLOOR)
```

to:

```python
            if compatible and entry.is_season_relative and assignment.season != 0:
                confidence = max(confidence, COMPATIBLE_PREFIX_FLOOR)
```

(The title-match floor and Plex-ready floor below stay as-is: a special corroborated by an exact title is still allowed to rise.)

- [ ] **Step 6: Thread `season` into the normal scan call site**

In `plex_renamer/engine/_tv_scanner_normal.py`, the `resolve_file` call in `_resolve_into_table` (currently lines 63-68) becomes:

```python
    resolution = resolve_file(
        parsed_episodes=tuple(episode_numbers),
        raw_title=title_evidence,
        is_season_relative=is_season_relative,
        season_titles=season_titles,
        season=season_num,
    )
```

- [ ] **Step 7: Run the resolution and normal-scanner suites**

Run: `python -m pytest tests/test_episode_resolution.py tests/test_tv_scanner_normal.py -v`
Expected: ALL pass.

- [ ] **Step 8: Commit**

```bash
git add plex_renamer/engine/_episode_resolution.py plex_renamer/engine/_tv_scanner_normal.py tests/test_episode_resolution.py
git commit -m "fix: specials number-only mapping forced into review"
```

---

## Task 4: Consolidated path — table built through the shared policy

**Files:**
- Modify: `plex_renamer/engine/_tv_scanner_consolidated.py` (new `build_consolidated_table` + `_apply_resolution`)
- Modify: `plex_renamer/engine/_tv_scanner.py:244-280` (`_build_consolidated_preview`)
- Test: `tests/test_consolidated_assignments.py` (new)

The consolidated/mixed-folder path builds items with the legacy matcher and `ingest_preview_items` (trusts parsed numbers, may omit Season 0 slots). Replace that with a table builder that registers **all** season slots including Season 0, routes specials through the specials policy, and reconciles each regular file's absolute-mapped candidate through `resolve_file` (so title evidence applies).

- [ ] **Step 1: Write the failing test**

Create `tests/test_consolidated_assignments.py`:

```python
from __future__ import annotations

from pathlib import Path

from plex_renamer.engine._episode_resolution import CONF_SPECIAL_NUMBER_ONLY
from plex_renamer.engine._tv_scanner_consolidated import build_consolidated_table

SHOW = {"id": 7, "name": "Demo Show", "year": "2020"}


class _NoTmdb:
    """Season 0 is provided inline; get_season must not be called."""

    def get_season(self, show_id, season_num):  # pragma: no cover - guard
        raise AssertionError("Season 0 already supplied in tmdb_seasons")


def _seasons():
    return {
        0: {
            "titles": {8: "How to Draw Eddy", 12: "The Grim Adventures of the KND"},
            "posters": {}, "episodes": {}, "count": 12,
        },
        1: {
            "titles": {1: "Pilot", 2: "The Heist"},
            "posters": {}, "episodes": {}, "count": 2,
        },
    }


def _build(tmp_path, filenames):
    root = tmp_path / "Demo Show"
    root.mkdir()
    for name in filenames:
        (root / name).write_text("x")
    return build_consolidated_table(
        season_dirs=[(root, 1)],
        tmdb_seasons=_seasons(),
        tmdb=_NoTmdb(),
        show_info=SHOW,
        root=root,
        store_tmdb_data=lambda *a, **k: None,
    )


def test_registers_season_zero_slots(tmp_path):
    table = _build(tmp_path, ["Demo Show - S01E01 - Pilot.mkv"])
    assert (0, 8) in table.slots
    assert (0, 12) in table.slots


def test_special_maps_by_title_not_number(tmp_path):
    table = _build(
        tmp_path,
        ["Demo Show - S00E08 - The Grim Adventures of the KND.mkv"],
    )
    claimant = table.claimant(0, 12)
    assert claimant is not None
    assert claimant.path.name.startswith("Demo Show - S00E08")
    assert table.claimant(0, 8) is None  # not the bare-number slot


def test_special_number_only_lands_in_review(tmp_path):
    table = _build(tmp_path, ["Demo Show - S00E08 - Mystery Clip.mkv"])
    assignment = table.claims(0, 8)
    assert assignment, "expected the special to map by number"
    assert assignment[0].confidence == CONF_SPECIAL_NUMBER_ONLY
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_consolidated_assignments.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_consolidated_table'`.

- [ ] **Step 3: Implement `build_consolidated_table`**

In `plex_renamer/engine/_tv_scanner_consolidated.py`, add these imports at the top (after the existing imports):

```python
from .episode_assignments import (
    REASON_AMBIGUOUS_RUN,
    REASON_NO_PARSE,
    REASON_NOT_IN_SEASON,
    EpisodeAssignmentTable,
)
```

Then add at the end of the module:

```python
def _apply_resolution(table, file_id, season, resolution) -> None:
    if resolution.episodes:
        try:
            table.assign(
                file_id,
                season,
                list(resolution.episodes),
                origin="auto",
                confidence=resolution.confidence,
                evidence=resolution.evidence,
            )
            return
        except ValueError:
            table.mark_unassigned(file_id, REASON_AMBIGUOUS_RUN)
            return
    table.mark_unassigned(file_id, resolution.reason or "")


def build_consolidated_table(
    *,
    season_dirs: list[tuple[Path, int]],
    tmdb_seasons: dict,
    tmdb,
    show_info: dict,
    root: Path,
    store_tmdb_data: Callable[[int, dict, dict, dict | None], None],
) -> EpisodeAssignmentTable:
    """Build the assignment table for flat/mixed multi-season folders.

    Registers every TMDB season's slots (including Season 0), routes
    specials through the specials policy, and reconciles each regular
    file's absolute-mapped candidate through ``resolve_file`` so title
    evidence applies (the normal path already does this per file).
    """
    from ._episode_resolution import resolve_file
    from ._tv_scanner_normal import _SPECIAL_STEM_PREFIX_RE, _register_season_slots

    table = EpisodeAssignmentTable()

    for season_num in sorted(s for s in tmdb_seasons if s != 0):
        season_data = tmdb_seasons[season_num]
        _register_season_slots(
            table, season_num,
            season_data.get("titles", {}), season_data.get("episodes", {}),
        )
        store_tmdb_data(
            season_num, season_data.get("titles", {}),
            season_data.get("posters", {}), season_data.get("episodes", {}),
        )

    if 0 in tmdb_seasons:
        s0_data = tmdb_seasons[0]
    else:
        s0_data = tmdb.get_season(show_info["id"], 0)
    s0_titles = s0_data.get("titles", {})
    if s0_titles:
        _register_season_slots(table, 0, s0_titles, s0_data.get("episodes", {}))
        store_tmdb_data(
            0, s0_titles, s0_data.get("posters", {}), s0_data.get("episodes", {}),
        )

    items = build_consolidated_preview(
        season_dirs=season_dirs,
        tmdb_seasons=tmdb_seasons,
        root=root,
        show_info=show_info,
        media_fields={},
        store_tmdb_data=store_tmdb_data,
    )
    mapped_by_path = {item.original: item for item in items}

    for (
        file_path, _abs_num, raw_title, episode_numbers,
        is_season_relative, season_hint,
    ) in collect_absolute_files(season_dirs):
        entry = table.add_file(
            file_path,
            parsed_episodes=tuple(episode_numbers),
            raw_title=raw_title,
            is_season_relative=is_season_relative,
            season_hint=season_hint if is_season_relative else None,
            folder_season=season_hint,
        )

        if season_hint == 0:
            title_evidence = raw_title or (
                _SPECIAL_STEM_PREFIX_RE.sub("", file_path.stem).strip() or None
            )
            resolution = resolve_file(
                parsed_episodes=tuple(episode_numbers),
                raw_title=title_evidence,
                is_season_relative=is_season_relative,
                season_titles=s0_titles,
                season=0,
            )
            _apply_resolution(table, entry.file_id, 0, resolution)
            continue

        item = mapped_by_path.get(file_path)
        if item is not None and item.season and item.episodes and item.season != 0:
            cand_season = item.season
            cand_titles = tmdb_seasons.get(cand_season, {}).get("titles", {})
            resolution = resolve_file(
                parsed_episodes=tuple(item.episodes),
                raw_title=raw_title,
                is_season_relative=is_season_relative,
                season_titles=cand_titles,
                season=cand_season,
            )
            _apply_resolution(table, entry.file_id, cand_season, resolution)
        else:
            table.mark_unassigned(
                entry.file_id,
                REASON_NO_PARSE if not episode_numbers else REASON_NOT_IN_SEASON,
            )

    return table
```

- [ ] **Step 4: Run the new test**

Run: `python -m pytest tests/test_consolidated_assignments.py -v`
Expected: all three tests PASS.

- [ ] **Step 5: Wire the scanner to the new builder**

In `plex_renamer/engine/_tv_scanner.py`, replace the body of `_build_consolidated_preview` (currently lines 244-280) with:

```python
    def _build_consolidated_preview(
        self,
        season_dirs: list[tuple[Path, int]],
        tmdb_seasons: dict,
    ) -> list[PreviewItem]:
        from ._episode_projection import project_preview_items
        from ._episode_resolution import apply_confidence_adjustments
        from ._tv_scanner_consolidated import build_consolidated_table

        table = build_consolidated_table(
            season_dirs=season_dirs,
            tmdb_seasons=tmdb_seasons,
            tmdb=self.tmdb,
            show_info=self.show_info,
            root=self.root,
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

Then remove the now-unused imports `_register_season_slots` and `ingest_preview_items` and the `EpisodeAssignmentTable` import line if it is only used by the old body — check with `python -m pyflakes plex_renamer/engine/_tv_scanner.py` and delete whatever it reports as unused. (Leave `ingest_preview_items` defined in `episode_assignments.py`; only its use here is removed.)

- [ ] **Step 6: Run the engine suite**

Run: `python -m pytest tests/test_consolidated_assignments.py tests/test_tv_scanner_normal.py tests/test_episode_projection.py tests/test_scan_improvements.py -v`
Expected: ALL pass.

- [ ] **Step 7: Commit**

```bash
git add plex_renamer/engine/_tv_scanner_consolidated.py plex_renamer/engine/_tv_scanner.py tests/test_consolidated_assignments.py
git commit -m "fix: consolidated scan path builds table via shared resolution policy"
```

> **Reproduction note for the executor:** After unit tests pass, scan the reported real folders (Aqua Teen Hunger Force complete series; As Told By Ginger Season 1-3; Ed, Edd n Eddy Season 6 + Specials) and confirm specials map and `S02E06` "Sibling Revile-ry" stays on E06. If a regular episode still lands in the wrong season, the absolute mapping (`try_title_based_matching`) chose the wrong season *before* reconciliation — capture that fixture and tighten `try_title_based_matching` (it is title-aware and lives in the same module), but do not weaken the per-season title reconciliation added here.

---

## Task 5: Roster — two review subcategories

**Files:**
- Modify: `plex_renamer/gui_qt/widgets/_media_helpers.py:63-136` (`state_status`, `state_status_tone`, `is_plex_ready_state` area, `roster_group`; add `has_episode_problems`)
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_roster.py:218-226` (group list)
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_refresh.py:60,140` (key references)
- Modify: `tests/test_qt_workspace_widgets.py:23` (update expectation)
- Test: `tests/test_roster_classification.py` (new)

Split the single `review` bucket into `review-match` (show-level) and `review-episodes` (episode-level: conflicts, unmapped primaries, below-threshold rows). Review Match wins when both apply. A clean show (no conflicts / no unmapped primaries / no review rows) reaches `matched`.

- [ ] **Step 1: Write the failing classification test**

Create `tests/test_roster_classification.py`:

```python
from __future__ import annotations

from pathlib import Path

from plex_renamer.engine import ScanState
from plex_renamer.engine._episode_projection import project_preview_items
from plex_renamer.engine.episode_assignments import (
    ORIGIN_AUTO,
    EpisodeAssignmentTable,
    EpisodeSlot,
)
from plex_renamer.gui_qt.widgets._media_helpers import has_episode_problems, roster_group

ROOT = Path("C:/lib/Demo Show (2020)")
SHOW = {"id": 9, "name": "Demo Show", "year": "2020"}


def _state(table: EpisodeAssignmentTable, *, needs_review: bool = False) -> ScanState:
    state = ScanState(folder=ROOT, media_info=SHOW)
    state.show_id = 9
    state.scanned = True
    state.needs_review = needs_review
    state.assignments = table
    state.preview_items = project_preview_items(
        table, show_info=SHOW, root=ROOT,
        media_fields={"media_id": 9, "media_name": "Demo Show"},
    )
    return state


def _table(count: int = 3) -> EpisodeAssignmentTable:
    table = EpisodeAssignmentTable()
    for episode in range(1, count + 1):
        table.add_slot(EpisodeSlot(season=1, episode=episode, title=f"Ep {episode}"))
    return table


def test_conflict_routes_to_review_episodes():
    table = _table()
    a = table.add_file(ROOT / "a.mkv")
    b = table.add_file(ROOT / "b.mkv")
    table.assign(a.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=1.0)
    table.assign(b.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=1.0)
    state = _state(table)
    assert has_episode_problems(state) is True
    assert roster_group(state, media_type="tv") == "review-episodes"


def test_unmapped_primary_routes_to_review_episodes():
    table = _table()
    ok = table.add_file(ROOT / "ok.mkv")
    table.assign(ok.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=1.0)
    stray = table.add_file(ROOT / "stray.mkv")
    table.mark_unassigned(stray.file_id, "could not parse episode number")
    state = _state(table)
    assert roster_group(state, media_type="tv") == "review-episodes"


def test_needs_review_wins_over_episode_problems():
    table = _table()
    a = table.add_file(ROOT / "a.mkv")
    b = table.add_file(ROOT / "b.mkv")
    table.assign(a.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=1.0)
    table.assign(b.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=1.0)
    state = _state(table, needs_review=True)
    assert roster_group(state, media_type="tv") == "review-match"


def test_clean_show_is_not_a_review_bucket():
    table = _table()
    for episode in range(1, 4):
        entry = table.add_file(ROOT / f"e{episode}.mkv")
        table.assign(entry.file_id, 1, [episode], origin=ORIGIN_AUTO, confidence=1.0)
    state = _state(table)
    assert has_episode_problems(state) is False
    assert roster_group(state, media_type="tv") not in {"review-match", "review-episodes"}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_roster_classification.py -v`
Expected: FAIL with `ImportError: cannot import name 'has_episode_problems'`.

- [ ] **Step 3: Add `has_episode_problems`**

In `plex_renamer/gui_qt/widgets/_media_helpers.py`, add directly above `roster_group` (currently line 121):

```python
def has_episode_problems(state: ScanState) -> bool:
    """True when the show match is settled but episode mapping has issues:
    a conflict, an unmapped primary file, or a below-threshold row.
    """
    table = state.assignments
    if table is not None:
        if table.conflicts():
            return True
        if table.unassigned_files():
            return True
    return any(item.is_episode_review for item in state.preview_items)
```

- [ ] **Step 4: Update `roster_group`**

Replace the `roster_group` body (currently lines 121-136) with:

```python
def roster_group(state: ScanState, *, media_type: str = "tv") -> str:
    if state.queued:
        return "queued"
    if state.duplicate_of is not None and media_type == MediaType.MOVIE:
        return "duplicate"
    if state.show_id is None:
        return "unmatched"
    if state.needs_review or state.duplicate_of is not None:
        return "review-match"
    if has_episode_problems(state):
        return "review-episodes"
    if is_plex_ready_state(state):
        return "plex-ready"
    return "matched"
```

- [ ] **Step 5: Update `state_status` and `state_status_tone`**

In `state_status` (currently lines 72-77), replace the combined review branch:

```python
    if (
        state.duplicate_of is not None
        or state.needs_review
        or any(item.is_episode_review for item in state.preview_items)
    ):
        return "Needs Review", QColor("#e5a00d")
```

with:

```python
    if state.needs_review or state.duplicate_of is not None:
        return "Review Match", QColor("#e5a00d")
    if has_episode_problems(state):
        return "Review Episode Matching", QColor("#e5a00d")
```

In `state_status_tone` (currently lines 94-99), replace:

```python
    if (
        state.duplicate_of is not None
        or state.needs_review
        or any(item.is_episode_review for item in state.preview_items)
    ):
        return "accent"
```

with:

```python
    if state.needs_review or state.duplicate_of is not None:
        return "accent"
    if has_episode_problems(state):
        return "accent"
```

- [ ] **Step 6: Run the classification + helper tests**

Run: `python -m pytest tests/test_roster_classification.py -v`
Expected: all four tests PASS.

- [ ] **Step 7: Update the roster panel group list**

In `plex_renamer/gui_qt/widgets/_media_workspace_roster.py`, replace the `groups` list in `_desired_entries` (currently lines 219-226) with:

```python
        groups = [
            ("queued", "Queued"),
            ("plex-ready", "Plex Ready"),
            ("matched", "Matched"),
            ("review-match", "Review Match"),
            ("review-episodes", "Review Episode Matching"),
            ("unmatched", "No Match Found"),
            ("duplicate", "Duplicates"),
        ]
```

- [ ] **Step 8: Update the refresh-helper key references**

In `plex_renamer/gui_qt/widgets/_media_workspace_refresh.py`:

Line ~60, change `) not in {"matched", "review"}` to:

```python
                ) not in {"matched", "review-match", "review-episodes"}
```

Line ~140, change `for group in ("matched", "review"):` to:

```python
        for group in ("matched", "review-match", "review-episodes"):
```

- [ ] **Step 9: Update the existing widget test**

In `tests/test_qt_workspace_widgets.py:23`, the TV duplicate now routes to `review-match`. Change:

```python
        self.assertEqual(roster_group(duplicate_state, media_type="tv"), "review")
```

to:

```python
        self.assertEqual(roster_group(duplicate_state, media_type="tv"), "review-match")
```

- [ ] **Step 10: Run the GUI workspace tests**

Run: `python -m pytest tests/test_qt_workspace_widgets.py tests/test_roster_classification.py -v`
Expected: ALL pass.

- [ ] **Step 11: Commit**

```bash
git add plex_renamer/gui_qt/widgets/_media_helpers.py plex_renamer/gui_qt/widgets/_media_workspace_roster.py plex_renamer/gui_qt/widgets/_media_workspace_refresh.py tests/test_roster_classification.py tests/test_qt_workspace_widgets.py
git commit -m "feat: split needs-review into Review Match and Review Episode Matching"
```

---

## Task 6: Assignment — extend a file to a second episode

**Files:**
- Modify: `plex_renamer/app/services/episode_mapping_service.py:56-73` (add `assign_or_extend_file`)
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_actions.py:199-226` (missing-row action)
- Test: `tests/test_episode_mapping_projection.py` (`TestTableBackedService`)

Assigning a file to a missing episode currently replaces its assignment. When the target episode is contiguous with the file's existing run in the same season, extend the run instead.

- [ ] **Step 1: Write failing tests**

Add to the `TestTableBackedService` class in `tests/test_episode_mapping_projection.py`:

```python
    def test_assign_or_extend_extends_contiguous(self):
        state = table_state()  # e1.mkv auto-assigned to [1]; slots 1-4 exist
        service = EpisodeMappingService()
        e1 = next(p for p in state.preview_items if p.status == "OK")
        service.assign_or_extend_file(state, e1, season=1, episode=2)
        updated = next(p for p in state.preview_items if p.original.name == "e1.mkv")
        assert updated.episodes == [1, 2]
        assert updated.episode_confidence == 1.0

    def test_assign_or_extend_replaces_when_not_contiguous(self):
        state = table_state()
        service = EpisodeMappingService()
        e1 = next(p for p in state.preview_items if p.status == "OK")
        service.assign_or_extend_file(state, e1, season=1, episode=4)
        updated = next(p for p in state.preview_items if p.original.name == "e1.mkv")
        assert updated.episodes == [4]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest "tests/test_episode_mapping_projection.py::TestTableBackedService::test_assign_or_extend_extends_contiguous" "tests/test_episode_mapping_projection.py::TestTableBackedService::test_assign_or_extend_replaces_when_not_contiguous" -v`
Expected: FAIL with `AttributeError: 'EpisodeMappingService' object has no attribute 'assign_or_extend_file'`.

- [ ] **Step 3: Implement `assign_or_extend_file`**

In `plex_renamer/app/services/episode_mapping_service.py`, add directly after `assign_file` (after line 73):

```python
    def assign_or_extend_file(
        self,
        state: ScanState,
        preview: PreviewItem,
        *,
        season: int,
        episode: int,
    ) -> None:
        """Assign a file to one episode, extending its run when contiguous.

        If the file already has an assignment in *season* whose run is
        adjacent to *episode*, the episode is added to that run; otherwise
        the file is assigned to just *episode* (replacing any prior run).
        """
        from ...engine.episode_assignments import ORIGIN_MANUAL

        table = self._require_table(state)
        if preview.file_id is None:
            raise ValueError("Preview row is not linked to a scanned file")
        episodes = [episode]
        existing = table.assignment_for(preview.file_id)
        if existing is not None and existing.season == season:
            run = sorted(existing.episodes)
            if episode == run[0] - 1 or episode == run[-1] + 1:
                episodes = sorted(set(run) | {episode})
        table.assign(
            preview.file_id, season, episodes,
            origin=ORIGIN_MANUAL, displace=True,
        )
        self.reproject(state)
```

- [ ] **Step 4: Run the service tests**

Run: `python -m pytest tests/test_episode_mapping_projection.py -v`
Expected: ALL pass.

- [ ] **Step 5: Wire the missing-episode row action to extend**

In `plex_renamer/gui_qt/widgets/_media_workspace_actions.py`, in `handle_episode_row_action`, the `assign_file` branch currently ends with (around line 223):

```python
                service.assign_file(
                    state, target, season=row.season, episodes=[row.episode],
                )
                message = "File assigned."
```

Replace those lines with:

```python
                service.assign_or_extend_file(
                    state, target, season=row.season, episode=row.episode,
                )
                message = "File assigned."
```

- [ ] **Step 6: Verify the Reassign pre-check path via smoke**

Run: `scripts/test-smoke.cmd`
Expected: exit code 0, summary shows passing. (This exercises the episode actions menu and picker. The `Reassign…` path already pre-checks the file's current episodes via `preselected` in `handle_episode_row_action`; the smoke run confirms the menu/picker still build. If smoke surfaces a dropped pre-check for season-0 or claimed slots, fix `EpisodeAssignDialog.set_checked`/`pick_episodes` so `preselected` keys render checked.)

- [ ] **Step 7: Commit**

```bash
git add plex_renamer/app/services/episode_mapping_service.py plex_renamer/gui_qt/widgets/_media_workspace_actions.py tests/test_episode_mapping_projection.py
git commit -m "feat: extend a file to a contiguous second episode without unassigning"
```

---

## Task 7: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full Python test suite**

Run: `python -m pytest -q`
Expected: all tests pass. If any pre-existing test asserted the old single `review` group key or `"Needs Review"` status string, update it to the new keys/labels (`review-match` / `review-episodes`, "Review Match" / "Review Episode Matching") and re-run.

- [ ] **Step 2: Run the Qt smoke suite**

Run: `scripts/test-smoke.cmd`
Expected: exit code 0; the printed summary reports no failures. Full output is at `.pytest_cache/smoke/latest.log`.

- [ ] **Step 3: Real-folder reproduction sweep**

Scan each reported folder and confirm the fix:
- `ChalkZone ... S01E01-E02-E03 ...` → maps to E01–E03 (Task 1).
- Ed, Edd n Eddy `S00E08 - The Grim Adventures of the KND` → maps by title, not to "How to Draw Eddy" (Tasks 3, 4).
- As Told By Ginger `S02E06 - Sibling Revile-ry` → stays on S02E06 (Tasks 2, 4).
- Aqua Teen Hunger Force complete series → specials map / are assignable (Task 4).
- A two-part "Bargaining (1)/(2)" file → assignable to both episodes via the missing-row "Assign file…" extend path (Task 6).
- A show with a conflict or an unmapped primary → appears under "Review Episode Matching", not "Matched" (Task 5).

- [ ] **Step 4: Commit any test-fixup changes**

```bash
git add -A
git commit -m "test: align suite with episode-assignment revisions"
```

---

## Self-Review

**Spec coverage:**
- §1 Parser chained ranges → Task 1.
- §2 Roster two subcategories + Review Match priority → Task 5 (`has_episode_problems`, `roster_group`, group list, status labels).
- §3 Consolidated unification (register S0, specials via policy, reconcile regular) → Task 4.
- §4 Specials number-only → review (Task 3) + title-vs-number guard (Task 2).
- §5 Extend without unassigning → Task 6.
- §6 Testing → tests in every task + Task 7 sweep.
- Issue 7 (assign unmapped → special) → covered by Task 4 registering Season 0 slots (`episode_slot_choices` then lists them; the unmapped-file "Assign to episode…" action already targets them) and verified in Task 7.

**Placeholder scan:** No TBD/TODO; every code step shows complete code; every run step shows the command and expected outcome.

**Type/name consistency:** `has_episode_problems`, `assign_or_extend_file`, `build_consolidated_table`, `_apply_resolution`, `CONF_SPECIAL_NUMBER_ONLY`, and the `season` keyword on `resolve_file` are used identically wherever referenced. Group keys `review-match` / `review-episodes` are consistent across `roster_group`, the roster panel list, and the refresh-helper references.
