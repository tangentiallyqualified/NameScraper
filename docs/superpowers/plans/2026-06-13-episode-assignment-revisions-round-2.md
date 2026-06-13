# Episode Assignment Revisions Round 2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix four reproduced specials/title-matching defects (Adventure Time `(Pilot)`/`(Again)`, Animaniacs featurettes, Tigtone off-by-one + pilot) and add two assignment actions ("Assign to more…" and sharing a matched file into a missing episode).

**Architecture:** All engine changes build on the existing `extract_episode` → `resolve_file` → `apply_confidence_adjustments` → `project_preview_items` pipeline and the table-backed `EpisodeMappingService`. A new descriptor-preserving title cleaner feeds clean title evidence into matching; the resolution policy gains a "strong-but-inexact title overrides number, in Review" rule with a cap that survives the confidence floors; the normal scan path gains a narrow cross-season special pull; the GUI gains one row action and a "share" group in the file picker. No data-model changes.

**Tech Stack:** Python 3, PySide6 (Qt), pytest. Windows + PowerShell. **Spec:** `docs/superpowers/specs/2026-06-13-episode-assignment-revisions-round-2-design.md`.

**Run tests with:** `python -m pytest <path> -v` from the repo root. Qt smoke runs use `scripts/test-smoke.cmd`. Commits go through `scripts/git-publish.cmd` per `CLAUDE.md`; the `git commit` lines below show the intended message/scope — use the publish workflow to actually commit.

---

## File Structure

Files created or modified, by responsibility:

- `plex_renamer/_parsing_titles.py` — new `clean_title_evidence` + `_strip_quality_parens` (Task 1).
- `plex_renamer/_parsing_episodes.py` — `extract_episode` uses `clean_title_evidence` (Task 1).
- `plex_renamer/engine/_tv_scanner_normal.py` — clean the specials title-evidence fallback + store it; thread `specials_titles` for cross-season pull (Tasks 2, 5).
- `plex_renamer/engine/_episode_resolution.py` — `CONF_TITLE_WINS_INEXACT`; rule-2b (inexact title overrides → review); season-0 guard on the contradictory-prefix cap; cap-last loop for review-locked evidence (Tasks 3, 4, 5).
- `plex_renamer/app/services/episode_mapping_service.py` — `shareable_file_choices` (Task 7).
- `plex_renamer/gui_qt/widgets/_media_workspace_preview.py` — add the `assign_to_more` row action (Task 6).
- `plex_renamer/gui_qt/widgets/_media_workspace_actions.py` — handle `assign_to_more`; split the missing-row picker into share vs reassign groups (Tasks 6, 7).
- `plex_renamer/gui_qt/widgets/episode_assign_dialog.py` — `pick_file` renders a "share / extend" group (Task 7).
- Tests: `tests/test_episode_resolution.py`, `tests/test_tv_scanner_normal.py`, `tests/test_episode_mapping_projection.py`, `tests/test_qt_workspace_widgets.py`.

---

## Task 1: Descriptor-preserving title cleaner

Quality parentheticals (`(480p TVRip x265 ImE)`) must be stripped from extracted episode titles, but
descriptive ones (`(Pilot)`, `(Again)`) must be kept so specials match their TMDB titles. `clean_name`
strips both. Add a sibling cleaner that strips only parentheticals containing a release-noise token, and
use it in `extract_episode`.

**Files:**
- Modify: `plex_renamer/_parsing_titles.py` (add `_strip_quality_parens`, `clean_title_evidence`)
- Modify: `plex_renamer/_parsing_episodes.py:9,34` (import + use the new cleaner)
- Test: `tests/test_episode_resolution.py` (extend `TestRangeFalsePositives` area)

- [ ] **Step 1: Write failing tests**

Add to `tests/test_episode_resolution.py` (top imports already include `extract_episode`). Append a new
class at the end of the parser-test section (after `TestRangeFalsePositives`, before the line
`from plex_renamer.engine._episode_resolution import (`):

```python
class TestDescriptiveParentheticals:
    def test_pilot_parenthetical_preserved(self):
        _eps, title, _rel = extract_episode(
            "Adventure Time (2008) - S00E01 - Adventure Time (Pilot) (480p TVRip x265 ImE).mkv"
        )
        assert title == "Adventure Time (Pilot)"

    def test_again_parenthetical_preserved(self):
        _eps, title, _rel = extract_episode(
            "Adventure Time (2008) - S00E13 - Frog Seasons Spring (Again) (1080p BluRay x265 ImE).mkv"
        )
        assert title == "Frog Seasons Spring (Again)"

    def test_quality_parenthetical_stripped(self):
        _eps, title, _rel = extract_episode(
            "Show - S01E05 - The Wizard Hunt (1080p BluRay x265 ImE).mkv"
        )
        assert title == "The Wizard Hunt"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_episode_resolution.py::TestDescriptiveParentheticals -v`
Expected: FAIL — titles come back without the parenthetical (e.g. `"Adventure Time"`).

- [ ] **Step 3: Add the cleaner to `_parsing_titles.py`**

In `plex_renamer/_parsing_titles.py`, add `RELEASE_NOISE` to the existing `from .constants import (...)`
block (line 7-13), then add directly after `clean_name` (after line 112):

```python
def _strip_quality_parens(text: str) -> str:
    """Remove only parenthetical groups that contain a release-noise token.

    Keeps descriptive groups like ``(Pilot)``/``(Again)`` and part numbers
    like ``(1)`` while dropping ``(480p BluRay x265 ImE)`` and similar.
    """
    def repl(match: re.Match) -> str:
        inner = match.group(1)
        if RELEASE_NOISE.search(f" {inner} "):
            return " "
        return match.group(0)

    return re.sub(r"\(([^()]*)\)", repl, text)


def clean_title_evidence(name: str) -> str:
    """Normalize a filename for episode-TITLE extraction.

    Like ``clean_name`` but PRESERVES descriptive parentheticals such as
    ``(Pilot)``/``(Again)`` (so specials match their TMDB titles) while still
    dropping quality/source parentheticals. Strips square-bracketed tags and
    turns dots/underscores into spaces.
    """
    name = re.sub(r"\[.*?\]", "", name)
    name = _strip_quality_parens(name)
    name = name.replace(".", " ").replace("_", " ")
    return re.sub(r"\s+", " ", name).strip()
```

- [ ] **Step 4: Use it in `extract_episode`**

In `plex_renamer/_parsing_episodes.py`, change the import on line 9 from:

```python
from ._parsing_titles import clean_name
```

to:

```python
from ._parsing_titles import clean_name, clean_title_evidence
```

and change line 34 from:

```python
    name = clean_name(raw_stem)
```

to:

```python
    name = clean_title_evidence(raw_stem)
```

(`clean_name` stays imported — `extract_season_number` still uses it on line 152.)

- [ ] **Step 5: Run the parser suite**

Run: `python -m pytest tests/test_episode_resolution.py tests/test_tv_scanner_normal.py -v`
Expected: ALL pass — the three new tests plus every pre-existing `TestMultiEpisodeRuns` /
`TestRangeFalsePositives` case. (If a `TestRangeFalsePositives` case regresses because a kept
`(word digit)` group introduced a stray number, narrow `_strip_quality_parens` to also strip groups
matching `\d` — but verify the new tests still pass.)

- [ ] **Step 6: Commit**

```bash
git add plex_renamer/_parsing_titles.py plex_renamer/_parsing_episodes.py tests/test_episode_resolution.py
git commit -m "fix: preserve descriptive parentheticals (Pilot)/(Again) in episode titles"
```

---

## Task 2: Clean the specials title-evidence fallback

When a special has no parsed title, `_resolve_into_table` builds title evidence from the **raw**
`file_path.stem`, so quality tags pollute matching. Route it through `clean_title_evidence` and store the
result as the file entry's `raw_title` so the title-match floor can see it.

**Files:**
- Modify: `plex_renamer/engine/_tv_scanner_normal.py:11-12,45-69`
- Test: `tests/test_tv_scanner_normal.py`

- [ ] **Step 1: Write a failing test**

Add to `tests/test_tv_scanner_normal.py`:

```python
def test_specials_title_evidence_strips_quality_tags():
    table = EpisodeAssignmentTable()
    table.add_slot(EpisodeSlot(season=0, episode=2, title="The Writers Flipped, They Have No Script"))
    _resolve_into_table(
        table,
        file_path=Path("The Writers Flipped, They Have No Script (480p DVD x265 HEVC 10bit AAC 2.0 Ghost).mkv"),
        season_num=0,
        season_titles={2: "The Writers Flipped, They Have No Script"},
    )
    entry = next(iter(table.files.values()))
    assert "480p" not in (entry.raw_title or "")
    assignment = table.assignment_for(entry.file_id)
    assert assignment is not None
    assert assignment.episodes == (2,)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_tv_scanner_normal.py::test_specials_title_evidence_strips_quality_tags -v`
Expected: FAIL — `entry.raw_title` is `None` (current code never stores stem evidence) so the assertion
on `"480p"` passes vacuously but the assignment is missing/0.9; more importantly the title evidence used
for matching still contains `480p`. (If it passes for the wrong reason, also assert
`assignment.confidence >= 0.85` to force the failure.)

- [ ] **Step 3: Update `_resolve_into_table`**

In `plex_renamer/engine/_tv_scanner_normal.py`, change the import on line 10-11 to add the cleaner:

```python
from ..parsing import extract_episode, extract_season_number, is_extras_folder
from ._episode_resolution import resolve_file
from .._parsing_titles import clean_title_evidence
```

Then replace the body of `_resolve_into_table` from line 45 through line 69 (the `extract_episode`
through `resolution = resolve_file(...)` section) with:

```python
    episode_numbers, raw_title, is_season_relative = extract_episode(file_path.name)
    season_hint = extract_season_number(file_path.name) if is_season_relative else None
    title_evidence = raw_title
    if season_num == 0 and not title_evidence:
        # Specials numbering varies across sources; the filename itself is
        # often the only title evidence. Clean it so quality tags don't
        # pollute the match (mirrors the retired match_special stem fallback).
        cleaned_stem = clean_title_evidence(file_path.stem)
        cleaned_stem = _SPECIAL_STEM_PREFIX_RE.sub("", cleaned_stem).strip()
        title_evidence = cleaned_stem or None
    entry = table.add_file(
        file_path,
        parsed_episodes=tuple(episode_numbers),
        raw_title=title_evidence,
        is_season_relative=is_season_relative,
        season_hint=season_hint,
        folder_season=season_num,
        from_extras_folder=from_extras_folder,
    )
    resolution = resolve_file(
        parsed_episodes=tuple(episode_numbers),
        raw_title=title_evidence,
        is_season_relative=is_season_relative,
        season_titles=season_titles,
        season=season_num,
    )
```

(The `if resolution.episodes:` assign/mark-unassigned block on lines 70-83 stays unchanged.)

- [ ] **Step 4: Run the scanner suite**

Run: `python -m pytest tests/test_tv_scanner_normal.py -v`
Expected: ALL pass.

- [ ] **Step 5: Commit**

```bash
git add plex_renamer/engine/_tv_scanner_normal.py tests/test_tv_scanner_normal.py
git commit -m "fix: clean specials title evidence so quality tags don't break matching"
```

---

## Task 3: Don't apply the contradictory-source-prefix cap to Season 0

A specials filename legitimately has no show-name prefix; the contradictory-prefix cap (0.45) wrongly
fires on title-only specials. Guard it with `season != 0`, mirroring the existing season-0 floor guards.

**Files:**
- Modify: `plex_renamer/engine/_episode_resolution.py:343-344`
- Test: `tests/test_episode_resolution.py` (`TestConfidenceAdjustments`)

- [ ] **Step 1: Write a failing test**

Add to the `TestConfidenceAdjustments` class in `tests/test_episode_resolution.py`:

```python
    def test_season0_title_only_not_capped_by_prefix(self):
        table = EpisodeAssignmentTable()
        table.add_slot(EpisodeSlot(season=0, episode=2, title="The Writers Flipped"))
        entry = table.add_file(
            Path("The Writers Flipped (480p DVD x265 Ghost).mkv"),
            is_season_relative=False,
            raw_title="The Writers Flipped",
            folder_season=0,
        )
        table.assign(
            entry.file_id, 0, [2], origin=ORIGIN_AUTO,
            confidence=CONF_TITLE_ONLY, evidence=frozenset({"title-strong"}),
        )
        apply_confidence_adjustments(table, show_info=SHOW)
        assert table.assignment_for(entry.file_id).confidence >= CONF_TITLE_ONLY
```

(`CONF_TITLE_ONLY` is already imported near line 154; if not, add it to that import block.)

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest "tests/test_episode_resolution.py::TestConfidenceAdjustments::test_season0_title_only_not_capped_by_prefix" -v`
Expected: FAIL — the assignment is capped to `CONTRADICTORY_PREFIX_CAP` (0.45).

- [ ] **Step 3: Add the guard**

In `plex_renamer/engine/_episode_resolution.py`, in `apply_confidence_adjustments`, change lines 343-344
from:

```python
            if not compatible:
                contradicted.add(assignment.file_id)
```

to:

```python
            if not compatible and assignment.season != 0:
                contradicted.add(assignment.file_id)
```

- [ ] **Step 4: Run the resolution suite**

Run: `python -m pytest tests/test_episode_resolution.py -v`
Expected: ALL pass.

- [ ] **Step 5: Commit**

```bash
git add plex_renamer/engine/_episode_resolution.py tests/test_episode_resolution.py
git commit -m "fix: do not apply contradictory-prefix cap to season-0 specials"
```

---

## Task 4: Title-wins → review (inexact override), with cap survival

A strong-but-inexact (substring) title match for a different episode currently keeps the number (rule 3).
Make it override the number, but at a sub-threshold confidence that **survives the floors** so it lands in
Review (not silently auto-accepted). Exact overrides keep `CONF_TITLE_WINS` (0.90, OK) as before.

**Files:**
- Modify: `plex_renamer/engine/_episode_resolution.py` (new constant; rule-2b; cap-last loop)
- Test: `tests/test_episode_resolution.py` (`TestResolutionRules`, `TestConfidenceAdjustments`)

- [ ] **Step 1: Write failing tests + flip the superseded one**

In `tests/test_episode_resolution.py`, add `CONF_TITLE_WINS_INEXACT` to the import block at line 149-160:

```python
    CONF_TITLE_WINS,
    CONF_TITLE_WINS_INEXACT,
    CONF_WEAK_TITLE_NUMBER_CAP,
```

Replace the existing `test_substring_offnumber_does_not_override_valid_number` (lines 281-290) with:

```python
    def test_substring_offnumber_overrides_into_review(self):
        # Parsed E2 is valid; title substring-matches E3 only. Title wins,
        # but lands in review (below threshold) rather than auto-accepting.
        res = resolve_file(
            parsed_episodes=(2,), raw_title="Endgame",
            is_season_relative=True,
            season_titles={1: "Pilot", 2: "The Heist", 3: "Endgame Saga"},
        )
        assert res.episodes == (3,)
        assert res.confidence == CONF_TITLE_WINS_INEXACT
        assert res.confidence < DEFAULT_EPISODE_AUTO_ACCEPT_THRESHOLD
        assert "title-strong-inexact" in res.evidence
```

Add to `TestConfidenceAdjustments` a cap-survival test:

```python
    def test_inexact_title_override_survives_floors(self):
        table = EpisodeAssignmentTable()
        for ep in range(1, 4):
            table.add_slot(EpisodeSlot(season=1, episode=ep, title=f"Ep {ep}"))
        entry = table.add_file(
            Path("Demo Show - S01E02 - Ep 1 extras.mkv"),
            is_season_relative=True, raw_title="Ep 1 extras",
        )
        table.assign(
            entry.file_id, 1, [1], origin=ORIGIN_AUTO,
            confidence=CONF_TITLE_WINS_INEXACT,
            evidence=frozenset({"title-strong-inexact", "number-disagree"}),
        )
        apply_confidence_adjustments(table, show_info=SHOW, show_match_confidence=1.0)
        assert (
            table.assignment_for(entry.file_id).confidence
            < DEFAULT_EPISODE_AUTO_ACCEPT_THRESHOLD
        )
```

(Add `CONF_TITLE_WINS_INEXACT` to the second import block at lines 330-336 too.)

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_episode_resolution.py::TestResolutionRules tests/test_episode_resolution.py::TestConfidenceAdjustments -v`
Expected: FAIL — `CONF_TITLE_WINS_INEXACT` does not exist (ImportError).

- [ ] **Step 3: Add the constant**

In `plex_renamer/engine/_episode_resolution.py`, in the calibration block (after line 35
`CONF_SPECIAL_NUMBER_ONLY = 0.50`), add:

```python
CONF_TITLE_WINS_INEXACT = 0.70  # strong-but-inexact title overrides number -> REVIEW
```

- [ ] **Step 4: Add rule-2b in `resolve_file`**

In `plex_renamer/engine/_episode_resolution.py`, the rule-2 / rule-3 block currently reads (lines 191-201):

```python
        if strong_title and title_match.strength >= _TITLE_EXACT:
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

Replace it with:

```python
        if strong_title and title_match.strength >= _TITLE_EXACT:
            return Resolution(  # rule 2: exact title overrides, auto-accept
                episodes=(title_match.episode,),
                confidence=CONF_TITLE_WINS,
                evidence=frozenset({"title-strong", "number-disagree"}),
            )
        if strong_title:
            return Resolution(  # rule 2b: strong inexact title overrides, REVIEW
                episodes=(title_match.episode,),
                confidence=CONF_TITLE_WINS_INEXACT,
                evidence=frozenset({"title-strong-inexact", "number-disagree"}),
            )
        return Resolution(  # rule 3
            episodes=valid_numbers,
            confidence=CONF_WEAK_TITLE_NUMBER_CAP,
            evidence=frozenset({"number", "title-weak-disagree"}),
        )
```

- [ ] **Step 5: Add the cap-last loop**

In `apply_confidence_adjustments`, the function currently ends with the contradictory-prefix loop
(lines 405-410):

```python
    for file_id in contradicted:
        assignment = table.assignment_for(file_id)
        if assignment is not None:
            table.set_confidence(
                file_id, min(assignment.confidence, CONTRADICTORY_PREFIX_CAP),
            )
```

Add directly after it (still inside the function):

```python
    # Review-locked evidence (inexact title override, cross-season special)
    # must stay below threshold no matter what floors ran above.
    for assignment in table.assignments():
        if assignment.evidence & {"title-strong-inexact", "cross-season-special"}:
            table.set_confidence(
                assignment.file_id,
                min(assignment.confidence, CONF_TITLE_WINS_INEXACT),
            )
```

- [ ] **Step 6: Run the resolution suite**

Run: `python -m pytest tests/test_episode_resolution.py -v`
Expected: ALL pass (note `test_rule2_strong_title_beats_number` and
`test_special_strong_title_still_wins` still pass — they use exact titles).

- [ ] **Step 7: Commit**

```bash
git add plex_renamer/engine/_episode_resolution.py tests/test_episode_resolution.py
git commit -m "fix: strong inexact title overrides number into review with cap survival"
```

---

## Task 5: Auto cross-season special pull

A regular-folder file whose title strongly matches a Season-0 special (and not its own season) is routed
to S0, in Review. This pulls the Tigtone pilot to S00E01. The matched S0 slot is registered just-in-time
so shows without specials are unaffected.

**Files:**
- Modify: `plex_renamer/engine/_tv_scanner_normal.py` (`_resolve_into_table` signature + cross-season block; `build_normal_table` passes `specials_titles` to regular-file calls)
- Test: `tests/test_tv_scanner_normal.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_tv_scanner_normal.py` (extend the imports at the top to include
`match_title_in_titles` is **not** needed; only `EpisodeSlot` already imported):

```python
def test_cross_season_pulls_pilot_to_specials():
    table = make_season1_table()  # S1 slots 1-5
    _resolve_into_table(
        table,
        file_path=Path("Tigtone S01E01 - Tigtone and the Pilot.mkv"),
        season_num=1,
        season_titles={1: "Tigtone and His Fellowship Of", 2: "Tigtone and the Beautiful War"},
        specials_titles={1: "Tigtone and the Pilot"},
    )
    entry = next(e for e in table.files.values() if "Pilot" in e.path.name)
    assignment = table.assignment_for(entry.file_id)
    assert assignment is not None
    assert assignment.season == 0
    assert assignment.episodes == (1,)
    assert "cross-season-special" in assignment.evidence


def test_cross_season_does_not_pull_normal_episode():
    table = make_season1_table()
    _resolve_into_table(
        table,
        file_path=Path("Show S01E02 - Ep 2.mkv"),
        season_num=1,
        season_titles=SEASON_TITLES,           # {1:"Ep 1", ... 5:"Ep 5"}
        specials_titles={1: "Ep 2 Behind the Scenes"},
    )
    entry = next(iter(table.files.values()))
    assignment = table.assignment_for(entry.file_id)
    assert assignment is not None
    assert assignment.season == 1            # own-season title agreement wins
    assert assignment.episodes == (2,)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_tv_scanner_normal.py::test_cross_season_pulls_pilot_to_specials tests/test_tv_scanner_normal.py::test_cross_season_does_not_pull_normal_episode -v`
Expected: FAIL — `_resolve_into_table` has no `specials_titles` parameter (TypeError).

- [ ] **Step 3: Add the cross-season block to `_resolve_into_table`**

In `plex_renamer/engine/_tv_scanner_normal.py`, extend the imports (the `._episode_resolution` line):

```python
from ._episode_resolution import (
    CONF_TITLE_WINS_INEXACT,
    STRONG_TITLE_STRENGTH,
    Resolution,
    match_title_in_titles,
    resolve_file,
)
```

Change the `_resolve_into_table` signature (currently lines 37-44) to add `specials_titles`:

```python
def _resolve_into_table(
    table: EpisodeAssignmentTable,
    *,
    file_path: Path,
    season_num: int,
    season_titles: dict[int, str],
    specials_titles: dict[int, str] | None = None,
    from_extras_folder: bool = False,
) -> None:
```

Then, immediately **after** the `resolution = resolve_file(...)` call (added in Task 2) and **before** the
`if resolution.episodes:` block, insert:

```python
    season_for_assign = season_num
    if (
        season_num != 0
        and specials_titles
        and title_evidence
        and "title-agree" not in resolution.evidence
    ):
        own_match = match_title_in_titles(title_evidence, season_titles)
        s0_match = match_title_in_titles(title_evidence, specials_titles)
        if (
            s0_match is not None
            and s0_match.strength >= STRONG_TITLE_STRENGTH
            and (own_match is None or s0_match.strength > own_match.strength)
        ):
            if (0, s0_match.episode) not in table.slots:
                table.add_slot(EpisodeSlot(
                    season=0, episode=s0_match.episode,
                    title=specials_titles[s0_match.episode],
                ))
            resolution = Resolution(
                episodes=(s0_match.episode,),
                confidence=CONF_TITLE_WINS_INEXACT,
                evidence=frozenset({"title-strong", "cross-season-special"}),
            )
            season_for_assign = 0
```

Finally, change the assign call (the `table.assign(entry.file_id, season_num, ...)` added in Task 2) to
use `season_for_assign`:

```python
    if resolution.episodes:
        try:
            table.assign(
                entry.file_id,
                season_for_assign,
                list(resolution.episodes),
                origin="auto",
                confidence=resolution.confidence,
                evidence=resolution.evidence,
            )
        except ValueError:
            table.mark_unassigned(entry.file_id, REASON_AMBIGUOUS_RUN)
    else:
        table.mark_unassigned(entry.file_id, resolution.reason or "")
```

- [ ] **Step 4: Pass `specials_titles` from `build_normal_table`**

In `build_normal_table`, the regular-season file branch currently calls (lines 174-180):

```python
                else:
                    _resolve_into_table(
                        table,
                        file_path=entry_path,
                        season_num=season_num,
                        season_titles=titles,
                    )
```

Change it to thread the S0 titles (fetched without forcing slot registration):

```python
                else:
                    _resolve_into_table(
                        table,
                        file_path=entry_path,
                        season_num=season_num,
                        season_titles=titles,
                        specials_titles=ensure_s0_titles(),
                    )
```

`ensure_s0_titles()` already returns `{}` when the show has no specials, so cross-season is a no-op there;
when it returns titles it also registers all S0 slots (existing behavior), which is harmless. The
just-in-time `add_slot` in Step 3 covers the case where `ensure_s0_titles` registered nothing yet.

- [ ] **Step 5: Run the scanner suite**

Run: `python -m pytest tests/test_tv_scanner_normal.py -v`
Expected: ALL pass.

- [ ] **Step 6: Commit**

```bash
git add plex_renamer/engine/_tv_scanner_normal.py tests/test_tv_scanner_normal.py
git commit -m "feat: pull regular-folder files matching a season-0 special into specials"
```

---

## Task 6: "Assign to more…" row action

Split extending a file to a contiguous neighbor out of Reassign into its own action on matched / review /
conflict rows.

**Files:**
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_preview.py:793-808`
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_actions.py:177` (new branch in `handle_episode_row_action`)
- Test: `tests/test_qt_workspace_widgets.py`

- [ ] **Step 1: Write a failing test for the action list**

Add to `tests/test_qt_workspace_widgets.py`. `_episode_row_actions` is a `@staticmethod` on
`MediaWorkspacePreviewPanel` (the only class in `_media_workspace_preview.py`), so it can be called
without constructing the widget:

```python
def test_matched_row_offers_assign_to_more():
    from plex_renamer.gui_qt.widgets._media_workspace_preview import (
        MediaWorkspacePreviewPanel,
    )

    class _Row:
        status = "Mapped"
    actions = MediaWorkspacePreviewPanel._episode_row_actions(_Row())
    ids = [a for a, _label in actions]
    assert "assign_to_more" in ids
    assert "reassign" in ids
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_qt_workspace_widgets.py::test_matched_row_offers_assign_to_more -v`
Expected: FAIL — `assign_to_more` not in the action list.

- [ ] **Step 3: Add the action to `_episode_row_actions`**

In `plex_renamer/gui_qt/widgets/_media_workspace_preview.py`, replace `_episode_row_actions`
(lines 793-808) with:

```python
    @staticmethod
    def _episode_row_actions(row) -> list[tuple[str, str]]:
        if row.status == "Missing File":
            return [("assign_file", "Assign file...")]
        if row.status == "Conflict":
            return [
                ("keep_this", "Keep this file (unassign others)"),
                ("reassign", "Reassign..."),
                ("assign_to_more", "Assign to more..."),
                ("unassign", "Unassign"),
            ]
        actions: list[tuple[str, str]] = []
        if row.status == "Review":
            actions.append(("approve", "Approve"))
        actions.append(("reassign", "Reassign..."))
        actions.append(("assign_to_more", "Assign to more..."))
        actions.append(("unassign", "Unassign"))
        return actions
```

- [ ] **Step 4: Handle the action**

In `plex_renamer/gui_qt/widgets/_media_workspace_actions.py`, in `handle_episode_row_action`, add a new
branch directly after the `reassign` branch ends (after line 198,
`service.assign_file(state, preview, season=season, episodes=episodes)` /
`message = "Episode mapping updated."`):

```python
            elif action_id == "assign_to_more" and preview is not None:
                if preview.season is None or not preview.episodes:
                    return
                season = preview.season
                run = sorted(preview.episodes)
                neighbors = {run[0] - 1, run[-1] + 1}
                slots = [
                    choice for choice in service.episode_slot_choices(state)
                    if choice.season == season and choice.episode in neighbors
                ]
                if not slots:
                    workspace.status_message.emit(
                        "No adjacent episode to extend into.", 4000,
                    )
                    return
                selection = assign_dialog.pick_episodes(
                    parent=workspace,
                    title=f"Extend \"{preview.original.name}\"",
                    slots=slots,
                )
                if selection is None:
                    return
                episodes = sorted(set(run) | {episode for _season, episode in selection})
                service.assign_file(state, preview, season=season, episodes=episodes)
                message = "File extended to additional episode(s)."
```

- [ ] **Step 5: Run the widget test + smoke**

Run: `python -m pytest tests/test_qt_workspace_widgets.py -v`
Expected: PASS.
Run: `scripts/test-smoke.cmd`
Expected: exit code 0; summary shows passing (exercises the episode actions menu + picker).

- [ ] **Step 6: Commit**

```bash
git add plex_renamer/gui_qt/widgets/_media_workspace_preview.py plex_renamer/gui_qt/widgets/_media_workspace_actions.py tests/test_qt_workspace_widgets.py
git commit -m "feat: add Assign to more action to extend a file to a contiguous episode"
```

---

## Task 7: Share an already-matched file into a missing episode

On a missing-episode row, offer adjacent already-matched files as "share / extend" (keeps their current
episode), distinct from non-adjacent files that would be reassigned.

**Files:**
- Modify: `plex_renamer/app/services/episode_mapping_service.py` (add `shareable_file_choices`)
- Modify: `plex_renamer/gui_qt/widgets/episode_assign_dialog.py:166-196` (`pick_file` shareable group)
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_actions.py:199-226` (split groups, pass shareable)
- Test: `tests/test_episode_mapping_projection.py` (`TestTableBackedService`)

- [ ] **Step 1: Write a failing test for the service helper**

Add to the `TestTableBackedService` class in `tests/test_episode_mapping_projection.py`:

```python
    def test_shareable_file_choices_lists_adjacent_assigned(self):
        state = table_state()  # e1.mkv -> [1]; slots 1-4 exist
        service = EpisodeMappingService()
        choices = service.shareable_file_choices(state, season=1, episode=2)
        names = [name for _fid, name in choices]
        assert any("e1.mkv" in name for name in names)

    def test_shareable_file_choices_excludes_nonadjacent(self):
        state = table_state()
        service = EpisodeMappingService()
        choices = service.shareable_file_choices(state, season=1, episode=4)
        assert choices == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest "tests/test_episode_mapping_projection.py::TestTableBackedService::test_shareable_file_choices_lists_adjacent_assigned" "tests/test_episode_mapping_projection.py::TestTableBackedService::test_shareable_file_choices_excludes_nonadjacent" -v`
Expected: FAIL — `AttributeError: 'EpisodeMappingService' object has no attribute 'shareable_file_choices'`.

- [ ] **Step 3: Implement `shareable_file_choices`**

In `plex_renamer/app/services/episode_mapping_service.py`, add directly after `unassigned_file_choices`
(after line 177):

```python
    def shareable_file_choices(
        self, state: ScanState, *, season: int, episode: int,
    ) -> list[tuple[int, str]]:
        """Assigned files whose run is contiguous-adjacent to (season, episode).

        These can be extended into the target episode without unassigning
        them from their current run.
        """
        table = self._require_table(state)
        result: list[tuple[int, str]] = []
        for assignment in table.assignments():
            if assignment.season != season:
                continue
            run = sorted(assignment.episodes)
            if episode == run[0] - 1 or episode == run[-1] + 1:
                entry = table.files[assignment.file_id]
                result.append((assignment.file_id, entry.path.name))
        return result
```

- [ ] **Step 4: Run the service tests**

Run: `python -m pytest tests/test_episode_mapping_projection.py -v`
Expected: ALL pass.

- [ ] **Step 5: Render a "share" group in `pick_file`**

In `plex_renamer/gui_qt/widgets/episode_assign_dialog.py`, change the `pick_file` signature (lines 166-173)
to accept `shareable`:

```python
    @staticmethod
    def pick_file(
        *,
        parent,
        title: str,
        unassigned: list[tuple[int, str]],
        assigned: list[tuple[int, str]],
        shareable: list[tuple[int, str]] | None = None,
    ) -> int | None:
        """Single-select file picker; returns the chosen file_id."""
```

Then change the group-adding section (lines 195-196) from:

```python
        add_group("Unassigned files", unassigned)
        add_group("Already assigned (will be reassigned)", assigned)
```

to:

```python
        add_group("Unassigned files", unassigned)
        add_group("Share / extend (keeps current episode)", shareable or [])
        add_group("Already assigned (will be reassigned)", assigned)
```

- [ ] **Step 6: Split the groups in the missing-row action**

In `plex_renamer/gui_qt/widgets/_media_workspace_actions.py`, the `assign_file` branch builds the
`assigned` list and calls `pick_file` (lines 199-214). Replace from
`unassigned = service.unassigned_file_choices(state)` through the `pick_file(...)` call with:

```python
                unassigned = service.unassigned_file_choices(state)
                unassigned_ids = {fid for fid, _label in unassigned}
                shareable = service.shareable_file_choices(
                    state, season=row.season, episode=row.episode,
                )
                shareable_ids = {fid for fid, _label in shareable}
                assigned = [
                    (item.file_id, item.original.name)
                    for item in state.preview_items
                    if item.file_id is not None
                    and item.new_name is not None
                    and item.file_id not in unassigned_ids
                    and item.file_id not in shareable_ids
                ]
                file_id = assign_dialog.pick_file(
                    parent=workspace,
                    title=f"Assign file to S{row.season:02d}E{row.episode:02d}",
                    unassigned=unassigned,
                    assigned=assigned,
                    shareable=shareable,
                )
```

(The rest of the branch — resolving `target` and calling
`service.assign_or_extend_file(state, target, season=row.season, episode=row.episode)` on lines 217-226 —
stays unchanged. `assign_or_extend_file` already extends a contiguous-adjacent file and replaces a
non-adjacent one, so a shared file keeps its current episode.)

- [ ] **Step 7: Run the service tests + smoke**

Run: `python -m pytest tests/test_episode_mapping_projection.py -v`
Expected: PASS.
Run: `scripts/test-smoke.cmd`
Expected: exit code 0; summary shows passing.

- [ ] **Step 8: Commit**

```bash
git add plex_renamer/app/services/episode_mapping_service.py plex_renamer/gui_qt/widgets/episode_assign_dialog.py plex_renamer/gui_qt/widgets/_media_workspace_actions.py tests/test_episode_mapping_projection.py
git commit -m "feat: share an already-matched file into a missing episode without unassigning"
```

---

## Task 8: Full verification + real-folder reproduction sweep

**Files:** none (verification only)

- [ ] **Step 1: Run the full Python suite**

Run: `python -m pytest -q`
Expected: all tests pass.

- [ ] **Step 2: Run the Qt smoke suite**

Run: `scripts/test-smoke.cmd`
Expected: exit code 0; printed summary reports no failures.

- [ ] **Step 3: Real-folder reproduction sweep**

Run a headless scan against each reported folder (TMDB key + the `P:\in progress files` folders are
available) and confirm the transitions. Use a script of the shape:

```python
from pathlib import Path
from plex_renamer.keys import get_api_key
from plex_renamer.tmdb import TMDBClient
from plex_renamer.engine._tv_scanner import TVScanner

tm = TMDBClient(get_api_key("TMDB"))

def run(query, root, hint, year=None):
    s = tm.search_tv(query, year=year)[0]
    info = {"id": s["id"], "name": s["name"], "year": str(s.get("year") or "")}
    items, _ = TVScanner(tm, info, Path(root), season_hint=hint, show_match_confidence=1.0).scan()
    for it in items:
        epi = f"S{it.season:02d}E{'-'.join(f'{e:02d}' for e in it.episodes)}" if it.season is not None and it.episodes else "--"
        print(f"  {it.status[:34]:34} {epi:10} {it.original.name[:46]}")
```

Confirm:
- **Adventure Time** S0 (`...\Season 00`, hint 0, year 2010): S00E01 (Pilot) is **OK** (was Review);
  S00E09 and S00E13 are both **OK** with no conflict (E13 stays on E13).
- **Animaniacs** Featurettes (the `...\Featurettes` folder via the full show root scan, or the extras path):
  "The Writers Flipped, They Have No Script" is **OK** (was Review). ("They're Totally Insan-y…" remaining
  unmatched is expected — release typo vs TMDB "Insane-y".)
- **Tigtone** (`Tigtone.S01...`, hint 1): the pilot maps to **S00E01** (Review); E02–E11 map to the
  correct S1 episodes (E02→S1E01 … E11→S1E10) with **no S01E10 conflict**.
- **As Told By Ginger** regression: S02E06 "Sibling Revile-ry" stays on **S02E06** (its title matches its
  own number — not an override).

- [ ] **Step 4: Commit any test-fixup changes**

```bash
git add -A
git commit -m "test: align suite with episode-assignment round 2"
```

---

## Self-Review

**Spec coverage:**
- A1 (preserve `(Pilot)`/`(Again)`) → Task 1.
- A2 (clean specials title-evidence fallback) → Task 2.
- A3 (no contradictory-prefix cap on S0) → Task 3.
- A4 (title-wins → review + cap survival, supersedes Task 2 exact-only) → Task 4.
- A5 (auto cross-season special pull) → Task 5.
- B1 ("Assign to more…") → Task 6.
- B2 (share into missing episode) → Task 7.
- Testing (TDD per fix + real-folder sweep + As Told By Ginger regression) → every task + Task 8.

**Placeholder scan:** No TBD/TODO; every code step shows complete code; every run step shows the command
and expected outcome.

**Type/name consistency:** `clean_title_evidence` / `_strip_quality_parens` (Task 1) are used in Tasks 2
and referenced by the `_resolve_into_table` rewrite. `CONF_TITLE_WINS_INEXACT` (Task 4) is reused by the
cross-season pull (Task 5) and the cap-last loop. Evidence tags `"title-strong-inexact"` and
`"cross-season-special"` are produced in Tasks 4/5 and consumed by the single cap-last loop in Task 4.
`shareable_file_choices` (Task 7) is called with the same `season=`/`episode=` keywords it defines, and
`pick_file`'s new `shareable` parameter matches the call site. `_episode_row_actions` returns
`(action_id, label)` pairs whose `assign_to_more` id matches the new handler branch.
