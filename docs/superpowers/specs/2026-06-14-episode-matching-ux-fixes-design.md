# Episode Matching UX Fixes — Design

**Status:** Approved (design), pending implementation plan.
**Date:** 2026-06-14
**Predecessor:** `docs/superpowers/specs/2026-06-13-episode-assignment-revisions-round-2-design.md`
(Round 2 added the `assign_to_more` / share actions and specials/title-matching fixes; this round
fixes four UX/rendering defects those flows exposed.)

## Goal

Fix four reproduced episode-matching UX defects:

1. **Reassign pre-checks the current episode.** Reassigning an already-matched file opens the picker
   with the file's current episode(s) already checked. Pre-checking should belong to *Assign to more*,
   not *Reassign*.
2. **Approve All does not recategorize the show.** After approving all of a show's episode mappings,
   the show stays under *Review Episode Matching* in the left roster and never gains a queue checkbox;
   the only way to queue it is the right-panel *Queue This Show* button.
3. **The episode-assignment modal is unusable.** It opens as a cramped box with two scrollbars
   (horizontal + vertical), is not DPI-aware in its sizing, and has no way to collapse seasons — you
   scroll past every episode of every season to find a slot.
4. **Missing specials do not render.** When a show has any missing regular-season episode, its missing
   *specials* (Season 0) rows disappear from the episode guide entirely.

No data-model changes. Builds on the existing `EpisodeAssignmentTable`, the table-backed
`EpisodeMappingService`, the roster/refresh coordinators, and `gui_qt._scale`.

## Root-cause diagnosis

### Issue 1 — Reassign pre-checks current episode

[`_media_workspace_actions.handle_episode_row_action`](../../../plex_renamer/gui_qt/widgets/_media_workspace_actions.py)
(lines 177–198): the `reassign` branch builds `preselected` from `preview.season`/`preview.episodes`
and passes it to `EpisodeAssignDialog.pick_episodes(..., preselected=...)`, which checks those rows via
`set_checked`. The `assign_to_more` branch (lines 199–223) does **not** preselect; it offers only the
run's adjacent neighbors and unions the result with the existing run afterward.

### Issue 2 — Approve All does not recategorize / no checkbox

[`_media_workspace_actions.approve_all_episode_mappings`](../../../plex_renamer/gui_qt/widgets/_media_workspace_actions.py)
(lines 121–148) mutates the live state via `EpisodeMappingService.approve_all` (which reprojects
`state.preview_items`), then refreshes only the center panel (`_populate_preview`) and the action bar
(`_update_action_bar`). It never calls `refresh_from_controller()`, which is what re-syncs the left
roster's grouping (`roster_group`) and per-row checkable state (`is_state_queue_approvable`).
By contrast, `approve_match` (the show-level approve) *does* call `refresh_from_controller()`.

Because `_current_states()` returns the controller's live `batch_states` and `_selected_state()`
returns one of those same objects, the in-place mutation is already visible to a roster re-sync — the
re-sync simply is not invoked. The same gap exists in single-row `handle_episode_row_action`
(lines 263–267).

### Issue 3 — Modal unusable

[`episode_assign_dialog.py`](../../../plex_renamer/gui_qt/widgets/episode_assign_dialog.py): the dialog
sets only `setMinimumWidth(_scale.px(420))` — no height and no screen-relative sizing, so it opens
cramped. The `QListWidget` permits a horizontal scrollbar (long `[claimed by …]` text) in addition to
the vertical one → two scrollbars. Season groups are flat, non-collapsible header rows
(`NoItemFlags`), so a multi-season show forces a long scroll. The `pick_file` static variant has the
same sizing/scrollbar flaws.

### Issue 4 — Missing specials dropped

[`_tv_scanner_postprocess`](../../../plex_renamer/engine/_tv_scanner_postprocess.py) (lines 76–92)
builds `total_missing` from seasons with `season_num > 0` only (intentionally consistent with
`total_expected`/`total_matched`, which exclude specials from the completeness %).
[`EpisodeMappingService._missing_episode_rows`](../../../plex_renamer/app/services/episode_mapping_service.py)
(lines 380–389) then **early-returns `total_missing`** whenever it is non-empty:

```python
if completeness.total_missing:
    return list(completeness.total_missing)   # specials never reached
```

So the moment any regular-season episode is missing, the specials-missing branch below it is skipped
and missing Season-0 rows are dropped from `build_episode_guide`, hence from the center panel.
`CompletenessReport` is constructed in exactly one place (postprocess), so this is the only locus.

## Decisions (from brainstorming)

- **Issue 1 / Issue 2 intent confirmed with the user:**
  - *Reassign* opens with **nothing checked**. *Assign to more* shows the **current run pre-checked**
    alongside the adjacent slots, so it is clear you are keeping the current episode(s) and extending.
  - After *Approve All*, the show becomes **checkable AND auto-checked** (Approve All is a strong
    "this show is ready" signal), provided nothing still blocks it (conflict / unmapped file).
- **Issue 2 scope:** apply the roster re-sync to single-row episode actions too (same root cause), but
  **without** auto-check — auto-check is specific to Approve All.
- **Issue 3 widget choice:** redesign the picker around a `QTreeWidget` (native collapse/expand,
  checkboxes on episode leaves only). Seasons default to **collapsed except the focus season**
  (the file's season); headers show episode counts. All sizing flows through `gui_qt._scale`.
- **Current-slot labelling:** a slot the file already holds is tagged `[current]`, never
  `[claimed by <itself>]`.

## Design

### Part A — Issue 4: render missing specials

#### A1. Include specials in the missing-episode rows

In `EpisodeMappingService._missing_episode_rows`, stop early-returning `total_missing` alone. Build the
regular-season rows from `total_missing`, then always append the specials' missing rows:

```python
completeness = state.completeness
if completeness is None:
    return []
rows = list(completeness.total_missing)                      # season > 0
if completeness.specials is not None:
    rows.extend((0, ep, title) for ep, title in completeness.specials.missing)
return rows
```

`total_missing`/`total_expected`/`total_matched` keep excluding specials (completeness % unchanged);
only the render list gains the Season-0 rows. `build_episode_guide` already de-dupes against mapped
keys, and the center panel already auto-collapses an all-missing season.

- **Locus:** `app/services/episode_mapping_service.py`.
- **Acceptance:** for a show with ≥1 missing regular-season episode **and** ≥1 missing special, the
  guide rows include the season-0 missing episode(s) with `status == "Missing File"`; they render under
  a *Specials* header in the center panel. A show with no missing specials is unchanged.

### Part B — Issue 2: Approve All recategorizes + auto-checks

#### B1. Re-sync the roster after Approve All, and auto-check

After `approve_all` (or the legacy status mutation) succeeds with `count > 0`:

1. `_refresh_episode_projection(workspace, state)` (refresh the guide cache for the mutated state).
2. `workspace._ensure_check_bindings(state)`; set every actionable item's binding to `True` and
   `state.checked = True`.
3. `workspace.refresh_from_controller()` — re-syncs the roster (recomputes `roster_group`, moving the
   show out of *Review Episode Matching*; recomputes `is_state_queue_approvable`, rendering the
   checkbox) and re-populates preview + action bar. Its `normalize_queue_selection` keeps the show
   checked when it is queue-approvable, or safely clears the binding if a conflict/unmapped file still
   blocks it (in which case it correctly stays in Review).

The standalone `_populate_preview` / `_update_action_bar` calls are removed in favor of
`refresh_from_controller()`, which performs both. `refresh_from_controller` preserves the selected show
by roster key, so focus does not jump.

#### B2. Re-sync the roster after single-row episode actions

At the end of `handle_episode_row_action`, replace the standalone `_populate_preview` /
`_update_action_bar` with `workspace.refresh_from_controller()` (no auto-check). This keeps roster
grouping/checkable state correct after approve/unassign/reassign/keep_this/assign_file on a single row
(e.g. approving the last Review row leaves Review).

- **Locus:** `gui_qt/widgets/_media_workspace_actions.py`.
- **Acceptance:**
  - A TV show under *Review Episode Matching* whose only problems are auto-origin Review rows: after
    *Approve All*, `roster_group(state)` is no longer `"review-episodes"`, `is_state_queue_approvable`
    is `True`, and `state.checked` is `True`.
  - A show that still has a conflict after Approve All stays in `"review-episodes"` and
    `state.checked` is `False`.
  - Approving the single remaining Review row via the row action moves the show out of
    `"review-episodes"` and makes it checkable (but not auto-checked).

### Part C — Issue 1: Reassign vs. Assign-to-more selection

#### C1. Reassign opens empty; Assign-to-more pre-checks the current run

In `handle_episode_row_action`:

- **`reassign`:** call `pick_episodes(..., preselected=None, current_keys={(season, e) for e in run})`.
  Nothing is checked; the file's own slots are tagged `[current]` (not "claimed by itself"); the file's
  season is auto-expanded (see C2).
- **`assign_to_more`:** offer slots for `run ∪ adjacent-neighbors` in the run's season (instead of
  neighbors-only), with `preselected = current_keys = {(season, e) for e in run}`. The current run
  shows checked and tagged `[current]`; the user ticks an adjacent slot to extend. Contiguity
  validation already gates the OK button. Keep the post-selection union with `run` (harmless and
  defensive).

#### C2. Dialog: `current_keys` tag and focus expansion

`EpisodeAssignDialog` / `pick_episodes` gain a `current_keys: set[tuple[int, int]] | None` parameter:

- Slot suffix precedence: `[current]` if the key is in `current_keys`; else `[claimed by X]` if claimed
  by another file; else `[missing]`.
- Default-expanded seasons = the set of seasons appearing in `preselected ∪ current_keys`; if that set
  is empty, expand all. (Reassign passes `current_keys` for the file's season → that season expands;
  assign-to-more's slots are single-season anyway.)

- **Locus:** `gui_qt/widgets/_media_workspace_actions.py`,
  `gui_qt/widgets/episode_assign_dialog.py`. The `[current]` distinction is driven entirely by the
  caller-supplied `current_keys` (the workspace already knows the file's `preview.season` /
  `preview.episodes`); `EpisodeMappingService.episode_slot_choices` is unchanged.
- **Acceptance:**
  - Reassign on an `S02E05` file: dialog opens with **no** rows checked, Season 02 expanded, other
    seasons collapsed, and the `S02E05` row tagged `[current]`.
  - Assign-to-more on the same file: dialog opens with `S02E05` **checked** and tagged `[current]`,
    `S02E06` (and `S02E04` if present) available to tick; choosing `S02E06` yields run `E05–E06`.

### Part D — Issue 3: modal redesign (collapsible, DPI-aware, single scrollbar)

Applies to both the multi-select `EpisodeAssignDialog` (file → episodes) and the single-select
`pick_file` (episode → file) variant.

#### D1. Collapsible groups via `QTreeWidget`

Replace the flat `QListWidget` with a `QTreeWidget`:

- Top-level items = season groups (`Specials`, `Season NN`) with an episode count, e.g.
  `SEASON 02 (24)`; expandable, **not** checkable, no selection role of their own.
- Child items = episode slots with `Qt.ItemFlag.ItemIsUserCheckable` (multi-select) or selectable rows
  (single-select `pick_file`, where the groups are the existing file categories).
- Default expansion per C2 (focus season expanded, rest collapsed). For `pick_file`, all file-category
  groups start expanded (they are short).
- `itemChanged` (check toggles) drives `_revalidate()`; checked-key collection iterates leaves.
  Preserve the public API: `selected_episodes()`, `set_checked()`, `is_selection_valid()`,
  `validation_text()`, `slot_row_text()`, and the `pick_episodes` / `pick_file` entry points.

#### D2. Single scrollbar + DPI-aware sizing

- `tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)`; long rows elide
  (`Qt.TextElideMode.ElideMiddle`) with the full text available as the item tooltip → no horizontal
  scrollbar; a single vertical scrollbar appears only when content exceeds the height.
- A `_dialog_size()` helper computes, from `QGuiApplication.primaryScreen().availableGeometry()` and
  `_scale`: initial size ≈ `(min(screen_w * 0.5, px(620)), min(screen_h * 0.6, px(640)))`, clamped to a
  minimum of `(px(460), px(420))`; `resize()` to it and `setMinimumSize(...)`. The dialog stays
  user-resizable and centers on its parent.
- Add an instruction label ("Assign this file to one or more contiguous episodes:") and the file name
  (elided, full name as tooltip) above the tree. All margins/spacing/icon sizes via `_scale`.

- **Locus:** `gui_qt/widgets/episode_assign_dialog.py` (all sizing through `gui_qt._scale`).
- **Acceptance:**
  - With QApplication at 96 DPI and again at a HiDPI scale, the dialog opens at the computed size (not
    the cramped default) and never smaller than the minimum.
  - Long claimed-by labels do not produce a horizontal scrollbar; their full text is the tooltip.
  - Season groups collapse/expand on click; a multi-season show opens with only the focus season
    expanded.

## Testing

- **TDD per fix:**
  - Issue 4: `tests/test_episode_mapping_projection.py` — a completeness report with missing
    regular-season **and** missing specials yields guide rows including the season-0 missing rows.
  - Issue 2: a Qt workspace test — a state under `review-episodes` whose only problems are Review rows
    transitions out of `review-episodes`, becomes `is_state_queue_approvable`, and is `checked` after
    `approve_all_episode_mappings`; a conflict-bearing state stays in Review and unchecked.
  - Issue 1: a dialog/service test — reassign passes `preselected=None`; assign-to-more preselects the
    current run; `current_keys` rows render `[current]`; focus season is expanded.
  - Issue 3: a Qt smoke/widget test asserting the dialog's initial size ≥ minimum and that the
    horizontal scrollbar policy is off; collapse/expand toggles child visibility.
- Full suite (`python -m pytest -q`) + Qt smoke (`scripts/test-smoke.cmd`) green.

## Out of scope

- Changes to the completeness percentage (`total_expected`/`total_matched`/`pct`) — specials remain
  excluded from the %.
- Non-contiguous / gapped multi-episode additions (unchanged from Round 2).
- Locking the pre-checked `[current]` rows in assign-to-more (they remain user-toggleable); revisit if
  the un-tick-then-extend path proves confusing.
- Restyling the center-panel episode guide or the roster beyond the grouping/checkbox refresh in
  Issue 2.
