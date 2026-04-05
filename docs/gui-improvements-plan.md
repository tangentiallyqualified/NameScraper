# GUI Improvements Plan

Date: 2026-04-04

## Purpose

This document tracks targeted UX improvements to the PySide6 shell identified through hands-on use. These are post-migration refinements — the shell is at functional parity and tkinter has been retired. The goal is to make the Qt shell feel polished and trustworthy, not to redesign the workflow.

Items are organized by surface area. Priority reflects user-facing impact, not implementation effort.

---

## Queue and History Tab

### Q.1 — Integrate select-all into the table header (Layout — High)

**Problem:** The select-all checkbox lives in a separate `_selection_bar` section above the table instead of in the table itself. It looks disconnected from the rows it controls.

**Fix:** Remove `_selection_bar` from `_JobListTab`. Place a tri-state checkbox in the header cell of column 0 (the empty checkbox column) using a custom `QHeaderView` section or delegate. The checkbox should toggle all visible rows and display tri-state when partially checked. Remove the separate "Select All" / "Clear All" buttons from `QueueTab`.

**Files:** `plex_renamer/gui_qt/widgets/_job_list_tab.py` (lines 81-95), `plex_renamer/gui_qt/widgets/queue_tab.py` (lines 59-67)

### Q.2 — Highlight full rows on hover, not individual cells (Visual — High)

**Problem:** The queue/history table still paints interaction state at the cell level instead of as a single row. On hover this makes the table feel broken, and on focus/selection it creates segmented highlights plus repeated vertical emphasis in each cell instead of one clear row treatment.

**Fix:** Move row interaction painting fully into the delegate (or an equivalent row-aware paint path) instead of letting Qt paint per-cell hover/selection backgrounds. Suppress both built-in hover and selected-cell painting, draw one contiguous row background for the hovered/current row, and draw the accent/vertical emphasis only once in column 0. While a row is focused, individual cells should not add their own extra hover highlight.

**Files:** `plex_renamer/gui_qt/widgets/_job_list_tab.py` (table view setup), `plex_renamer/gui_qt/resources/theme.qss`

### Q.3 — Remove move-up/move-down buttons, add "Remove Checked" (Layout — High)

**Problem:** The move-up and move-down buttons in `QueueTab` are low-value — users rarely reorder queued jobs by single positions. The blank space they leave makes the toolbar feel sparse. There is no "Remove Checked" button alongside "Execute Selected."

**Fix:**
1. Remove the Move Up and Move Down buttons from `QueueTab._build_actions()` (lines 87-100).
2. Replace "Move Up" / "Move Down" right-click context actions with a single "Move to Top of Queue" action.
3. Add a "Remove Checked" button in the action bar alongside "Execute Selected."
4. Remove the empty space left by the removed buttons. Increase the table height to fill the reclaimed vertical space by removing fixed-height constraints on the action bar.

**Files:** `plex_renamer/gui_qt/widgets/queue_tab.py` (lines 87-100, 200-214), `plex_renamer/gui_qt/widgets/_job_list_tab.py` (context menu at line 254)

### Q.4 — Remove the refresh button (Layout — Low)

**Problem:** The refresh button in the toolbar is redundant. The queue and history views already refresh automatically on every job lifecycle event via `_on_queue_changed`.

**Fix:** Remove the refresh button from `_JobListTab._finish_toolbar()`. If a manual refresh is ever needed for debugging, it can be triggered via a keyboard shortcut (F5) without a permanent button.

**Files:** `plex_renamer/gui_qt/widgets/_job_list_tab.py` (line 124)

### Q.5 — Pre-select first job on tab switch (Workflow — High)

**Problem:** When switching to the Queue or History tab, the detail panel is empty until the user clicks a row. This makes the tab look broken on first view.

**Fix:** In `QueueTab.refresh()` and `HistoryTab.refresh()`, after populating the model, if no row is currently selected and the model has rows, programmatically select row 0 via `_table.selectRow(0)` and emit the selection-changed signal so the detail panel populates.

**Files:** `plex_renamer/gui_qt/widgets/queue_tab.py` (line 108), `plex_renamer/gui_qt/widgets/history_tab.py` (line 94)

### Q.6 — Clear selections on tab entry (Workflow — Medium)

**Problem:** Checkbox state persists when leaving and returning to the queue/history tab. Users expect a clean slate each time they open the tab — stale selections from a previous visit lead to accidental bulk actions.

**Fix:** In `QueueTab.refresh()` and `HistoryTab.refresh()`, call `_model.clear_checked()` (or equivalent) at the start of each refresh triggered by a tab switch. Distinguish tab-switch refreshes from in-tab refreshes (e.g. after executing a job) to avoid clearing selections mid-workflow. Use a flag set by `MainWindow._on_tab_changed()`.

**Files:** `plex_renamer/gui_qt/widgets/queue_tab.py`, `plex_renamer/gui_qt/widgets/history_tab.py`, `plex_renamer/gui_qt/main_window.py` (tab changed handler)

### Q.7 — Disable checkboxes on reverted history jobs (Workflow — Medium)

**Problem:** Reverted jobs in the history tab still have checkboxes, but selecting them has no useful action — they can't be reverted again or executed.

**Fix:** In `JobTableModel`, return `Qt.ItemFlag(0)` (no `ItemIsUserCheckable`) for column 0 when the job status is `REVERTED` or `REVERT_FAILED`. The row should still be selectable for viewing details, but not checkable.

**Files:** `plex_renamer/gui_qt/models/job_table_model.py` (flags method)

### Q.8 — Move "Clear History" to settings (Layout — Medium)

**Problem:** The "Clear History" button on the history tab is a destructive action sitting alongside everyday controls. It's rarely used and takes up toolbar space.

**Fix:** Remove the "Clear History" button from `HistoryTab`. Add a "Clear Job History" button in `SettingsTab` under a "Data Management" section, alongside the existing cache controls. Keep the confirmation dialog.

**Files:** `plex_renamer/gui_qt/widgets/history_tab.py` (lines 49-56, 184-197), `plex_renamer/gui_qt/widgets/settings_tab.py`

### Q.9 — Split Files column into Primary Files and Companion Files (Layout — Medium)

**Problem:** The "Files" column shows a single count that conflates primary rename operations with companion file operations (subtitles, etc.). Users can't tell at a glance how many actual media files vs companion files are in a job.

**Fix:** Replace the "Files" column with two narrower columns: "Files" (primary renames only) and "Companions" (subtitle/companion operations). Reduce the "When" column width slightly to accommodate. Update `JobTableModel.data()` to compute each count from `job.operations` and `job.companion_operations` (or equivalent fields on `RenameJob`).

**Files:** `plex_renamer/gui_qt/models/job_table_model.py` (line 13 headers, data method), `plex_renamer/job_store.py` (verify field availability)

### Q.10 — Use local timezone for job timestamps (Bug — High)

**Problem:** `_fmt_dt()` in `job_table_model.py:34` calls `datetime.fromisoformat(value).strftime(...)` without timezone conversion. If timestamps are stored in UTC, they display as UTC rather than the user's local time.

**Fix:** After parsing with `fromisoformat()`, convert to local time via `.astimezone()` before formatting. If timestamps are already local (naive), document that assumption and leave as-is.

**Files:** `plex_renamer/gui_qt/models/job_table_model.py` (line 34-38)

### Q.11 — Fix tab badge sizing and centering (Visual — Medium)

**Problem:** The queue badge is too wide for single-digit counts, and badge numbers aren't visually centered within the badge.

**Fix:** Set a minimum width on the count label rather than a fixed width. Use `QLabel.setAlignment(Qt.AlignCenter)` and add symmetric horizontal padding in QSS. Review the `tab-badge-count` QSS selector for asymmetric margins.

**Files:** `plex_renamer/gui_qt/widgets/tab_badge.py` (line 12-40), `plex_renamer/gui_qt/resources/theme.qss` (`tab-badge-count` selector)

### Q.12 — Replace red dot tab indicator with a clearer signal (Visual — Medium)

**Problem:** The small red failure pip next to the queue badge count is unclear — users don't immediately understand what it means.

**Fix:** Replace the pip with a text badge variant: when failed jobs exist, change the badge background to the error color and display the count in white. Alternatively, show a separate "(N failed)" text label beside the badge. The signal should be self-explanatory without requiring the user to learn what the dot means.

**Files:** `plex_renamer/gui_qt/widgets/tab_badge.py`, `plex_renamer/gui_qt/resources/theme.qss`

### Q.13 — Put the job detail panel on the right, not the left (Layout — High)

**Problem:** The queue/history shell currently mounts `JobDetailPanel` to the left of the table pane. That is the opposite of the batch-mode workspace, so the user has to mentally flip panel orientation when switching between the review and queue workflows.

**Fix:** Reverse the splitter order in `_JobListTab` so the list pane is on the left and the detail panel is on the right. Preserve the existing splitter-persistence behavior, but reset or migrate saved sizes if necessary so older stored positions do not produce a collapsed panel after the swap.

**Files:** `plex_renamer/gui_qt/widgets/_job_list_tab.py`, `plex_renamer/app/services/settings_service.py` (only if splitter persistence needs migration)

### Q.14 — Remove the black gutter between the toolbar row and content panels (Visual — Medium)

**Problem:** There is a full-width black strip between the toolbar/action row and the two panels beneath it. This reads as an unintended gap rather than deliberate spacing because it exposes the window background between two adjacent panel surfaces.

**Fix:** Remove the parent layout gap in `_JobListTab` by eliminating the outer `QVBoxLayout` spacing between the toolbar and splitter, then keep breathing room inside the panels via their own margins. The toolbar and content region should stack cleanly without a visible background seam.

**Files:** `plex_renamer/gui_qt/widgets/_job_list_tab.py`

---

## Job Detail Panel

### D.1 — Make rename previews explicit and non-truncated (Layout — High)

**Problem:** The rename preview is now more explicit than the original text box, but the layout still treats it as secondary content inside the right-hand text column beside the poster. That means the preview does not use the full panel width and cannot extend beneath the poster, even though the rename mapping is the main reason to open the detail panel.

**Fix:** Restructure `JobDetailPanel` into a top summary region and a full-width preview region underneath it. Keep poster, title, metadata, and folder actions in the top region, then let the rename preview span the entire panel width below that header so rows can extend beneath the poster. Keep the two-column `QTreeWidget` treatment, full filenames, season grouping, and explicit rename mapping, but make the preview the dominant body content instead of something constrained by the poster column.

**Files:** `plex_renamer/gui_qt/widgets/job_detail_panel.py` (lines 97-106)

### D.2 — Collapsible season headers in job preview (Layout — Medium)

**Problem:** Job previews for TV shows list all files flat. For a 24-episode season, this is a wall of text with no structure.

**Fix:** When building the preview for TV jobs, group operations by season number. Display collapsible season headers ("Season 01 (12 files)") that default to collapsed. Include an "Other Files" section at the bottom for companion files, subtitles, or files that don't parse to a season. Reuse the collapsible header pattern from the media workspace roster.

**Files:** `plex_renamer/gui_qt/widgets/job_detail_panel.py`

### D.3 — Hide "Open Target Folder" in queue, show only in history (Workflow — High)

**Problem:** Both "Open Source Folder" and "Open Target Folder" buttons are always visible, even when no job is selected. "Open Target Folder" doesn't make sense for pending jobs in the queue — the target folder hasn't been created yet.

**Fix:**
1. Hide both buttons when no job is selected (when `set_job(None)` is called or panel is cleared).
2. In queue mode, hide "Open Target Folder" entirely — only show "Open Source Folder."
3. In history mode, show both buttons, but disable "Open Target Folder" if the target path doesn't exist (already partially handled by `can_open_target_folder()`).
4. `JobDetailPanel` needs a `set_mode(queue_or_history)` method or constructor parameter to distinguish context.

**Files:** `plex_renamer/gui_qt/widgets/job_detail_panel.py` (lines 80-88), `plex_renamer/gui_qt/widgets/_job_list_tab.py`

### D.4 — Larger and centered preview poster (Visual — Medium)

**Problem:** The job detail poster is small (120x180) and appears off-center relative to the metadata beside it.

**Fix:** Increase poster size to at least 160x240. Align the poster vertically to the top of the detail panel body, and ensure the metadata column starts at the same top edge. If the poster is taller than the metadata, let it extend below — don't compress it.

**Files:** `plex_renamer/gui_qt/widgets/job_detail_panel.py` (line 50, poster label sizing)

### D.5 — Move revert confirmation closer to the revert button (Workflow — Medium)

**Problem:** The inline revert confirmation banner in `HistoryTab` puts the "Confirm Revert" button far from the "Revert Selected" button that triggered it. The user's cursor has to travel across the toolbar.

**Fix:** Position the confirmation banner directly below or adjacent to the "Revert Selected" button, not as a full-width banner at the top. Alternatively, use a compact inline popover anchored to the revert button. The confirm action should be within one click-radius of the trigger.

**Files:** `plex_renamer/gui_qt/widgets/history_tab.py` (lines 70-90)

### D.6 — Remove library/source/target path text from the job detail body (Layout — Medium)

**Problem:** The always-visible path summary in `JobDetailPanel` adds a dense block of low-value text (`Library`, `Source`, `Target`) above the rename preview. It competes with the real payload of the panel and makes the queue/history detail view feel cluttered.

**Fix:** Remove the always-visible `_paths` text block from the detail layout. Keep the source/target folder buttons as the primary path affordances. If path inspection is still needed for debugging, move it behind an optional disclosure or a less prominent secondary surface rather than keeping it in the main reading flow.

**Files:** `plex_renamer/gui_qt/widgets/job_detail_panel.py`

---

## Batch Mode Refinements

### B.1 — Show match confidence in Fix Match dialog results (Workflow — High)

**Problem:** `MatchPickerDialog` displays TMDB results as `"Title (Year)"` with no confidence score. When the user is choosing between similar results, there's no indication of how well each result matches the folder/filename.

**Fix:** Score each result in the list using `score_results()` against the current query, and display the confidence as a suffix or secondary label: `"Neon Genesis Evangelion (1995) — 85%"`. Highlight results above the auto-accept threshold with the success color. This requires passing the `raw_name` and `year_hint` into the dialog or computing scores in the callback.

**Files:** `plex_renamer/gui_qt/widgets/match_picker_dialog.py` (lines 25-28 `_label_for_result`, line 177), `plex_renamer/gui_qt/widgets/media_workspace.py` (dialog invocation)

### B.2 — Fix preview panel after unqueueing a previously queued show (Bug — High)

**Problem:** In batch mode, after unqueueing a job for a show and returning to that show in the roster, the preview panel fails to populate. The show appears in the roster but clicking it shows an empty preview.

**Fix:** Investigate the state lifecycle when a job is unqueued. The likely cause is that the `ScanState` for the show has its `queued` flag cleared but the scanner/preview data is not rehydrated — the preview items may have been cleared when the job was created. After unqueueing, the controller should either restore the cached preview items or trigger a rescan of the show's episodes.

**Files:** `plex_renamer/app/controllers/media_controller.py` (queue/unqueue state management), `plex_renamer/gui_qt/widgets/media_workspace.py` (preview population)

### B.3 — Fix duplicate movie approval controls and post-approve regrouping (Bug — High)

**Problem:** Duplicate movie rows still expose `Approve Match`, and approving them can leave the roster in an incoherent state where the item styling/grouping no longer matches the duplicate section header. This makes duplicate handling feel unreliable at exactly the point where the UI should be most strict.

**Fix:** Treat duplicates as a separate resolution path, not as normal review items. Hide `Approve Match` whenever `duplicate_of` is set, even if the state also has `needs_review` and `show_id`. After any approve/rematch action, force an immediate roster refresh so section membership, header counts, and row widgets are rebuilt from the latest controller state. Confirm that a movie only moves out of `Duplicates` once the duplicate state is actually cleared.

**Files:** `plex_renamer/gui_qt/widgets/media_workspace.py` (`_approve_match`, `_RosterRowWidget`), `plex_renamer/gui_qt/widgets/_media_helpers.py` (`roster_group`, `state_status`)

---

## April 5 2026 Assessment Pass

This pass folds the latest queue/detail polish list into the working plan.

- The duplicate-match approval issue is a new operational bug, not just polish, and should be treated as a high-priority batch-mode fix before broader queue refinements.
- The focused-row highlight problem is already represented by Q.2, but the acceptance criteria needed to be tightened because the current delegate only suppresses cell-level hover painting, not the selected-row segmentation the user still sees.
- The panel-orientation mismatch, full-width rename-preview requirement, path-text clutter, and toolbar/content gutter are all real issues in the current Qt shell and were not explicitly captured in the plan before this pass.

---

## Implementation Notes

- Items are independent and can be addressed in any order.
- Start with high-priority items that affect trust and usability: B.3, Q.2, Q.13, D.1, D.3, Q.14, Q.1, Q.3, Q.5, Q.10, B.2.
- Visual polish items (Q.11, Q.12, D.4) can be batched together once the queue/detail layout issues are stable.
- Q.6 (clear selections on tab entry) and Q.7 (disable reverted checkboxes) are quick wins.
- D.1, D.2, and D.6 should be done together as they share the same widget and reading flow.
