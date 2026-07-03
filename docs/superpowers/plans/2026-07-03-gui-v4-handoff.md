# GUI V4 — Session Handoff

> **Purpose:** live handoff so a fresh session can resume mid-stream. Update after every milestone.
> **Branch:** `dev/GUI4` (created 2026-07-03 from `dev/GUI3` @ 9794499)
> **Scope of this session:** design + planning ONLY. No implementation code. Implementation is a separate task per the user.

## Current status

- [x] Branch `dev/GUI4` created and checked out
- [x] Codebase exploration (COMPLETE — findings below)
- [ ] Design doc at `docs/superpowers/specs/2026-07-03-gui-v4-design.md` (IN PROGRESS)
- [ ] Spec self-review
- [ ] Implementation plan at `docs/superpowers/plans/2026-07-03-gui-v4-implementation.md`
- [ ] Commit design + plan + this handoff
- [ ] User review of spec + plan (BLOCKING GATE — do not implement until user approves)

## Process notes

- Following `superpowers:brainstorming` → `superpowers:writing-plans`. Session is autonomous, so interactive Q&A is replaced by documented assumptions/open questions in the design doc.
- HARD GATE: no implementation until the user approves the design. Next session: if design+plan exist and user approved → `superpowers:executing-plans`; if user requested changes → revise spec first.

## User's brief (condensed — full text in first user message of session 2026-07-03)

Primary goals:
1. 3-panel → 2-panel GUI (consolidate middle+right) for BOTH TV and movie batch modes.
2. Remove extraneous info not useful for renaming.
3. Fix GUI lag on show navigation / rearrangement; never lock up without visible loading animation.
4. Make episode match fixing + bulk reassignment intuitive.
5. Plex color scheme → Jellyfin dark mode; remove "Plex" mentions ("Plex Ready" → "Fully Ready").
6. Enlarge left panel; posters more prominent (compensates for losing right panel).
7. At-a-glance seasonal completeness (current: left shows file count, right shows episode count — confusing).
8. Groundwork + GUI room for mkvmerge feature (subtitle merge during rename; multi-part merge). DO NOT wire it yet.
9. Toasts: expandable + copyable text for error troubleshooting.
10. Redo loading screen + animation (data duplication, bad animation); accurate progress + fun filler messages.
11. Kill AI-slop colored left-edge fringe on cards → graceful shading instead.
12. Restyle queue + history tabs (usability, modern feel).
13. Restyle settings page (facelift; unstyled checkboxes).
14. Consistent corner rounding; reduce crammed fine lines.
15. Movie batch mode gets same revisions where relevant.
16. Maintain high-DPI/scaling compatibility.

Pain points (beyond the goals): middle panel too compressed; companion files poorly presented (workspace AND queue/history); long input/output filenames truncated unreadably; missing episodes not obvious; bulk remap after "Unassign All" requires per-file modal grind; right panel nearly useless — keep only its buttons + show/episode descriptions + air date; left-panel file-count+confidence clutter (keep confidence); REMOVE Ctrl+Z undo shortcut (dangerous, revisit post-mkvmerge); "Unassign All" styled like a filter yet destructive; left panel needs separate headers for "all regular episodes matched" vs "only specials/unmapped need review"; recent TV/movie folder menus clickable from the wrong tab.

## Codebase findings (exploration COMPLETE)

### Architecture
- `gui_qt/main_window.py`: QMainWindow, 5 tabs — Settings=0, TV=1, Movies=2, Queue=3, History=4. Logic delegated to `_main_window_*.py` coordinators (chrome=menus/shortcuts, state, scan, shell, tabs, feedback, bootstrap, bridges, tmdb, shortcuts).
- `widgets/media_workspace.py`: per-media-type workspace. QStackedWidget: EMPTY(0)=`empty_state.py` drop zone → SCANNING(1)=`scan_progress.py` → READY(2)=3-panel QSplitter sizes `[320, 540, 380]` (persisted via settings `splitter_positions`).
  - LEFT `_media_workspace_roster.py` (`MediaWorkspaceRosterPanel`): QListWidget + per-row `RosterRowWidget` via setItemWidget. Groups (in order): queued / **plex-ready** / matched / review-match / review-episodes / unmatched / duplicate; collapsible headers (`_roster_collapsed`, plex-ready collapsed by default). Footer: master tri-state check + "N of M checked" + "Queue Checked" button. Posters 48×70 px, LRU cache 128, bg fetch via thread_pool + signal bridge.
  - MIDDLE `_media_workspace_preview.py` (`MediaWorkspacePreviewPanel`): QListWidget + per-row widgets. TV mode = episode guide (season sections w/ collapse, sticky header overlay, filters All/Problems/Unmapped, Approve All + **Unassign All styled exactly like the filter buttons** (`secondary`+`compact`)); movie mode = flat PreviewRowWidget list + master check. Renders are cached per state via `_PREVIEW_RENDER_KEY_ROLE` = `id(state)` — hidden items from OTHER shows stay in the same QListWidget.
  - RIGHT `media_detail_panel.py` (`MediaDetailPanel`): poster/backdrop w/ shimmer, facts grid (6 rows), overview, extra caption, queue-preflight label, **Fix Match + primary action buttons** (the preview panel's own copies are hidden; workspace rebinds to detail panel's buttons in `_media_workspace_ui.py:_build_detail_panel`).
- Row widgets `_workspace_widgets.py`: `RosterRowWidget` (toggle switch, poster, title, hidden status pill, meta "N file(s) · TMDB - 93%", confidence bar), `PreviewRowWidget` (movies), `EpisodeGuideRowWidget` (TV: "S01E02 - Title", status pill, original ElideMiddle, target ElideMiddle, companions elided, confidence bar, inline Approve + ⋯ QMenu w/ reassign/assign-to-more/unassign/keep-this), `FolderPreviewRowWidget`. Primitives in `_workspace_widget_primitives.py` (ClickableRow, ElidedLabel, MasterCheckBox, MiniProgressBar, ToggleSwitch, shimmer).
- Data models: `engine/models.py` — `ScanState` (confidence, needs_review, preview_items, `completeness: CompletenessReport`, `assignments`, season_names/folders, orphan_companion_files, scan_error…), `CompletenessReport` (per-season `SeasonCompleteness {expected, matched, missing[], matched_episodes[]}` + specials + totals + pct). `app/models/state_models.py` — `EpisodeGuide{rows, unmapped_primary_files, duplicate_files, orphan_companion_files, summary}`, `EpisodeGuideRow{season, episode, title, status: Mapped|Review|Conflict|Missing File, confidence_label, overview, air_date, target_rename, companions}`, `EpisodeSlotChoice`, `QueuePreflightSummary`. **Everything needed for at-a-glance seasonal completeness already exists in CompletenessReport.**
- Presentation helpers `_media_helpers.py`: status strings (**"Plex Ready"** at line 81), roster_group (**"plex-ready"** key), confidence bands, season_label, `make_section_header` (hardcoded amber #f0b429 on #2a2110), sort keys, companion summary.
- Queue/History: `_job_list_tab.py` shared base — QTableView + `JobTableModel`/`JobStatusFilterProxyModel` (real model/view!), checkable header, hover delegate that paints **4px amber left-accent on selected row**, segmented filter control, splitter to `job_detail_panel.py`. Queue adds Start Queue/Run Selected/Remove Selected; history adds banner/revert (`_history_tab_*.py`).
- Toasts `toast_manager.py`: `_ToastCard` — **inline stylesheet, border-left 4px tone fringe**, title+message word-wrap, optional action button, countdown progress bar, max 3 direct + overflow summary card, no expand/copy. Positioned bottom-right by `_toast_manager_layout.py`.
- Loading `scan_progress.py`: centered fixed-width (680px) card — title, `_ScannerAnimation` (orbiting dots on rings, amber), phase heading, message label, progress bar + count, "Current: …" + Elapsed row (message/current often duplicate), phase checklist (○/●/✓ 2-col grid), Cancel. Text updates throttled to 650ms.
- Settings `settings_tab.py` + `_settings_tab_sections.py`: left nav QListWidget + QStackedWidget of `SettingsSectionCard` pages (Destinations, Display, Matching, API keys, Cache, Advanced…). Plain QCheckBox/QComboBox/QSlider styled minimally in QSS.
- Dialogs: `match_picker_dialog.py` (+_match_picker_* : search/results/selection) for show-level Fix Match; `episode_assign_dialog.py` — `EpisodeAssignDialog` (file→episodes multi-select, contiguity-validated, season-grouped QTreeWidget) and `pick_file` (episode→file). **One file per dialog round-trip; no bulk mode.**
- Scaling `_scale.py`: `px(n)` logical-DPI ratio (96 base), `row_height`, `icon`, `margins`. Sound approach; keep using it.
- Shortcuts (`_main_window_chrome.py:build_shortcuts` + menu accels): **Ctrl+Z → Undo Last Rename (REMOVE)**, Ctrl+O open TV, Ctrl+Q queue selected, Ctrl+Shift+Q queue checked, Space toggle check, Esc cancel-scan/dismiss-toast, F5 fix match, Del remove (queue), Enter run (queue), Ctrl+1..5 tab switch.
- **Recent-folders bug confirmed** `_main_window_state.py:rebuild_recent_menus`: actions call `load_folder` on the target workspace but never switch tabs (and both menus are enabled regardless of active tab).

### Root causes of GUI lag (primary perf goal)
1. Per-row live QWidgets via `QListWidget.setItemWidget` for roster + preview (expensive construct/layout/destroy per refresh).
2. `QApplication.processEvents()` sprinkled in sync loops (roster every 25 rows, episode guide every 30) — reentrancy hazard + still slow.
3. `warm_preview_cache` (`_media_workspace_state.py`) synchronously builds row widgets for **every scanned show** into the shared QListWidget after refresh; hidden-but-alive widgets accumulate (render key = `id(state)`).
4. Full-list rebuild on any structural change (`_remove_render_items` + re-add); no incremental model updates.
5. No busy indicator during these rebuilds — window just freezes (user's complaint).

### Theming facts
- `resources/theme.qss` (~1007 lines): Plex palette — accent #e5a00d/#f0b429/#7a5a10, bg #0d0d0d/#151515/#1c1c1c/#242424, selected #1f1a0e (amber-tinted), success #3ea463, error #d44040, info #4a9eda, borders #2a2a2a/#3a3a3a. Radii inconsistent: 0 (panelVariant=square), 4, 5, 6, 8, 10, 12px.
- ~285 hex colors ALSO hardcoded across 12 py files (worst: `_media_helpers.py` 21, `_workspace_widget_primitives.py` 14, job_table_model 7, _image_utils 6, toast_manager 5, scan_progress 5, _job_list_tab 3…). Toast card + scan animation + section headers + table delegates bypass QSS entirely.
- Fringe pattern (`border-left: N px solid`): roster-row-card (4px), preview-row-card (3px), callout-banner (4px), toast card (4px), selected table row (4px painted). All slated for removal per user.
- User-facing "Plex": window title + app name ("Plex Renamer"), About dialog, "Plex Ready" status/group header, "already Plex-ready" skip reason (`_media_workspace_queue_actions.py:91`), theme.qss header comment.
- Jellyfin dark reference palette (for design): bg #101010, surface #202020, card ~#252525, primary accent #00a4dc, secondary accent #aa5cc3 (brand gradient blue→purple), text rgba(255,255,255,.87).

## Key decisions so far

- Design direction (to be written up): 2-panel = roster (enlarged, poster-forward, seasonal completeness chips) + unified work panel (show header w/ poster context + description/air date + actions, episode table). Performance = replace per-row widget lists with QListView/QTreeView + custom delegates (model/view, like queue tab already does); async population; busy overlay component. Theme = token-driven QSS template + Python token module to kill the 285 hardcoded hexes. Details in spec.

## Next step (if resuming here)

Write the design doc to `docs/superpowers/specs/2026-07-03-gui-v4-design.md` covering: requirements (from brief), 2-panel layout design, seasonal completeness UX, remap workflow, perf architecture (model/view + delegates + busy overlay), Jellyfin theme tokens, toasts, loading screen, queue/history/settings restyle, mkvmerge groundwork (data model + reserved UI affordances only), shortcuts/menu fixes, testing strategy, open questions. Then self-review, then `superpowers:writing-plans` for the implementation plan, then commit everything together on `dev/GUI4`.
