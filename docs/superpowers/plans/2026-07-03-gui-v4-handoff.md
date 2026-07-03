# GUI V4 — Session Handoff

> **Purpose:** live handoff so a fresh session can resume mid-stream. Update after every milestone.
> **Branch:** `dev/GUI4` (created 2026-07-03 from `dev/GUI3` @ 9794499)

## Current status (updated 2026-07-03, end of design/planning session)

- [x] Branch `dev/GUI4` created and checked out
- [x] Codebase exploration (findings below)
- [x] Design spec: [docs/superpowers/specs/2026-07-03-gui-v4-design.md](../specs/2026-07-03-gui-v4-design.md) — self-reviewed, committed
- [x] Roadmap index: [2026-07-03-gui-v4-implementation.md](2026-07-03-gui-v4-implementation.md) (9 plans mapped to spec sections)
- [x] Plan 1 (theme foundation + de-Plex + chrome fixes): [2026-07-03-gui-v4-plan1-theme-foundation.md](2026-07-03-gui-v4-plan1-theme-foundation.md) — complete, executable, TDD steps
- [ ] **USER REVIEW GATE (blocking):** user must review spec + Plan 1 and pick an execution mode. NO IMPLEMENTATION until approved.
- [ ] Plans 2–9: NOT written yet — write each with `superpowers:writing-plans` when its predecessor lands (see roadmap standing rules)

## How to resume

1. **If the user has approved spec + Plan 1:** execute Plan 1 with `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans`. Plan 1 is fully self-contained (exact code, tests, commands, commits).
2. **If the user requested spec/plan changes:** edit the spec first, re-run its self-review, cascade changes into the roadmap/Plan 1, re-commit, re-ask.
3. **If Plan 1 has landed:** write Plan 2 (roster model/delegate + grouping, spec §3.1/§4/§7) via `superpowers:writing-plans`, then continue down the roadmap table.
4. Always update this file + the roadmap status column at each milestone.

## Open questions for the user (also in spec §15)

1. **App display name** — spec assumes **"NameScraper"** replaces "Plex Renamer" (window title, app name, About). Confirm or supply another.
2. Episode description + air date placement = expanded episode row; show overview = work-panel header (spec §3.2). Confirm.
3. Roster poster size ~64×94 logical. Confirm/adjust.
4. Bulk Assign MVP scope (spec §6, §15.7). Confirm.

## Key design decisions (spec is authoritative; summary)

- **Approach A**: model/view rebuild (QAbstractItemModel + QStyledItemDelegate, like the queue tab) replaces per-row live widgets; expanded row = single persistent-editor widget. Delete `warm_preview_cache`, render-key retention, all `processEvents` in workspace.
- **2-panel**: enlarged poster-forward roster (+season chips, new group taxonomy incl. `Specials & Unmapped Only`, `plex-ready`→`fully-ready`) + work panel (show header / season strip / toolbar / virtualized episode table with ghost missing-rows + in-place expansion / footer file-breakdown + Fix Match + Queue buttons). `MediaDetailPanel` deleted; movie mode gets same shell minus season strip.
- **Bulk Assign mode** in-panel (check files → assign-in-order to contiguous slots; auto-map remaining; apply once). Unassign All becomes danger-outline + confirm + bulk-assign offer.
- **Theme**: `gui_qt/theme.py` tokens + `theme.qss.tmpl`; Jellyfin palette (accent #00a4dc etc.); radii sm4/md8/lg12/pill10; ALL fringes removed (cards get ≤6% alpha tone washes); guard tests: no hex outside theme.py, no "Plex" string literals in gui_qt (AST-based, allowlists plex_renamer/PLEX_RENAMER identifiers).
- **Perf budget**: 300-ep show switch <100ms; no event-loop block >200ms without BusyOverlay.
- **mkvmerge**: seams only (disabled Merge… slot in expanded row, Files section layout, queue-detail grouping, hidden Settings "Tools" section). NOT wired.
- Ctrl+Z undo removed (Task 5, plan 1); recent-folder menus switch tab before load (Task 6, plan 1).

## Codebase findings (exploration complete — trust these, verified 2026-07-03)

- Workspace: `widgets/media_workspace.py` QStackedWidget EMPTY/SCANNING/READY; READY = QSplitter [320,540,380]: roster (`_media_workspace_roster.py`, per-row `RosterRowWidget` via setItemWidget), preview (`_media_workspace_preview.py`, `EpisodeGuideRowWidget` TV / `PreviewRowWidget` movie, render-cache keyed `id(state)` keeps hidden items of ALL shows in one QListWidget), detail (`media_detail_panel.py` — owns Fix Match + primary buttons, rebound in `_media_workspace_ui.py:_build_detail_panel`).
- Perf bugs: per-row live widgets; `processEvents` every 25 (roster) / 30 (guide) rows; `warm_preview_cache` (`_media_workspace_state.py:93`) synchronously pre-builds widgets for EVERY scanned show; full rebuilds on change; no busy indicator.
- Data for chips already exists: `engine/models.py` `CompletenessReport.seasons[n] = SeasonCompleteness{expected, matched, missing[]}` + specials; `app/models/state_models.py` `EpisodeGuide{rows, unmapped_primary_files, duplicate_files, orphan_companion_files, summary}`.
- Groups today (`_media_helpers.roster_group`): queued/plex-ready/matched/review-match/review-episodes/unmatched/duplicate. Status strings minted in `_media_helpers.state_status`. `is_plex_ready_state` → `CommandGatingService` (internal name, rename in Plan 2).
- Theme: `resources/theme.qss` ~1007 lines Plex amber (#e5a00d); ~65 more hexes across 11 py files (`_media_helpers` 21, `_workspace_widget_primitives` 14, `job_table_model` 7, `_image_utils` 6, `toast_manager` 5, `scan_progress` 5, `_job_list_tab` 3 + stripe painting, `tab_badge`/`job_detail_panel`/`_match_picker_selection`/`_media_detail_artwork` 1 each). Fringe sites: roster/preview cards + callout-banner (QSS), toast card (inline py), table selected-row stripe (`_job_list_tab.py` delegate).
- QSS loaded in `app.py:142-146` from `_THEME_PATH`; app name set at `app.py:137`; title `main_window.py:67`; About `_main_window_shell.py:71-79`.
- Shortcuts in `_main_window_chrome.py` (Ctrl+Z undo at lines 43-45); recent menus in `_main_window_state.py:86-105` (no tab switch — the bug).
- Queue/History already model/view (`_job_list_tab.py` + `models/job_table_model.py` + `job_status_filter_proxy_model.py`) — pattern to copy for workspace.
- Tests: fast sweep `scripts\test-fast.cmd`; Qt smoke `scripts\test-smoke.cmd` (log at `.pytest_cache/smoke/latest.log`). Tests referencing `plex-ready`: `test_qt_queue_history.py:612`, `test_qt_media_workspace.py:3716`. Real-library harness `scripts/scan_real_library.py` (needs P: drive; exits 2 if missing).
- Scaling: `gui_qt/_scale.py` (`px()` logical-DPI). Keep for everything.

## Session log

- 2026-07-03: branch created → exploration → spec written + self-reviewed → committed 32cee9a → roadmap + Plan 1 written → this handoff updated → committed (see git log) → session ended at user review gate.
