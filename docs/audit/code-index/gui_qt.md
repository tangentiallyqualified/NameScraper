<!-- Generated from audit input 71631f57942b; do not edit. regenerate: scripts\audit.cmd --fast -->


# Package detail: gui_qt


### `plex_renamer/gui_qt/__init__.py` — PySide6 shell for NameScraper.
- Tests: tests/test_automux_tracks_widget.py, tests/test_episode_expansion.py, tests/test_episode_table_delegate.py, tests/test_gui_theme.py, tests/test_qt_main_window.py, tests/test_qt_media_workspace.py, tests/test_qt_queue_history.py, tests/test_qt_scale.py, tests/test_qt_workspace_widgets.py, tests/test_roster_delegate.py, tests/test_work_panel.py

### `plex_renamer/gui_qt/_main_window_bootstrap.py` — Bootstrap helpers for the main window shell.
- `MainWindowBootstrapCoordinator` (used by: plex_renamer.gui_qt.main_window)

### `plex_renamer/gui_qt/_main_window_bridges.py` — Qt bridge helpers for main-window controller callbacks.
- `ControllerBridge` — Marshal MediaController callbacks onto the Qt main thread.
- `QueueBridge` — Marshal QueueController callbacks onto the Qt main thread.
- `install_controller_bridge(window) -> ControllerBridge` (used by: plex_renamer.gui_qt.main_window)
- `install_queue_bridge(window) -> QueueBridge` (used by: plex_renamer.gui_qt.main_window)
- Tests: tests/test_qt_main_window.py

### `plex_renamer/gui_qt/_main_window_chrome.py` — Menu-bar and shortcut helpers for the main window.
- `MainWindowChromeCoordinator` (used by: plex_renamer.gui_qt.main_window)

### `plex_renamer/gui_qt/_main_window_feedback.py` — Feedback and status helpers for the main window.
- `MainWindowFeedbackCoordinator` (used by: plex_renamer.gui_qt.main_window)

### `plex_renamer/gui_qt/_main_window_scan.py` — Scan and workspace refresh helpers for the main window.
- `MainWindowScanCoordinator` (used by: plex_renamer.gui_qt.main_window)
- Tests: tests/test_qt_main_window.py

### `plex_renamer/gui_qt/_main_window_shell.py` — Remaining shell helpers for the main window.
- `MainWindowShellCoordinator` (used by: plex_renamer.gui_qt.main_window)

### `plex_renamer/gui_qt/_main_window_shortcuts.py` — Shortcut behavior helpers for the main window.
- `MainWindowShortcutCoordinator` (used by: plex_renamer.gui_qt.main_window)

### `plex_renamer/gui_qt/_main_window_state.py` — State and settings helpers for the main window.
- `MainWindowStateCoordinator` (used by: plex_renamer.gui_qt.main_window)

### `plex_renamer/gui_qt/_main_window_tabs.py` — Tab and startup wiring helpers for the main window.
- `MainWindowTabsCoordinator` (used by: plex_renamer.gui_qt.main_window)

### `plex_renamer/gui_qt/_main_window_tmdb.py` — TMDB client lifecycle helpers for the main window.
- `MainWindowTmdbCoordinator` (used by: plex_renamer.gui_qt.main_window)

### `plex_renamer/gui_qt/_scale.py` — Centralized scale helpers for the PySide6 GUI.
- `px(n) -> int` — Convert logical 4px-grid units to physical pixels.
- `row_height(rows, padding) -> int` — Return a row height derived from the application font's line spacing.
- `icon(token) -> QSize` — Return a named, DPI-scaled icon size as a ``QSize``.
- `margins(*tokens) -> QMargins` — Build a ``QMargins`` from 1, 2, or 4 grid-unit tokens.
- Tests: tests/test_roster_delegate.py

### `plex_renamer/gui_qt/app.py` — PySide6 application bootstrap.
- `run() -> None` — Create the QApplication, main window, and enter the event loop. (used by: plex_renamer.__main__)
- Tests: tests/test_qt_app_popup_filter.py, tests/test_qt_main_window.py

### `plex_renamer/gui_qt/main_window.py` — Main application window — Phase 3 shell.
- `MainWindow` — Top-level window with menu bar, tab bar, and status bar. (used by: plex_renamer.gui_qt.app)
- Tests: tests/test_qt_chrome.py, tests/test_qt_main_window.py, tests/test_qt_queue_history.py, tests/test_recent_menus.py, tests/test_tab_badge.py

### `plex_renamer/gui_qt/models/__init__.py` — Qt item models for the PySide6 shell.

### `plex_renamer/gui_qt/models/job_status_filter_proxy_model.py` — Status-based proxy model for queue and history tables.
- `JobStatusFilterProxyModel` — Filter RenameJob rows by a set of allowed status strings. (used by: plex_renamer.gui_qt.models, plex_renamer.gui_qt.widgets._job_list_tab)

### `plex_renamer/gui_qt/models/job_table_model.py` — Table model for queue/history jobs.
- `files_cell_text(job) -> str` — Spec §11 Files column: '3 files (2 comp.)'; companion suffix drops at 0.
- `JobTableModel` — Read-only model exposing RenameJob rows to a QTableView. (used by: plex_renamer.gui_qt.models, plex_renamer.gui_qt.widgets._job_list_tab)
- Tests: tests/test_qt_queue_history.py, tests/test_queue_tab_remux.py

### `plex_renamer/gui_qt/theme.py` — GUI V4 design tokens — the single source of truth for color and shape.
- `color(name) -> str`
- `qcolor(name) -> QColor` (used by: plex_renamer.gui_qt.models.job_table_model)
- `radius(name) -> int`
- `rgba(name, alpha) -> str`
- `render_template(text) -> str`
- `load_stylesheet() -> str`

### `plex_renamer/gui_qt/widgets/__init__.py` — Phase 3+ widget modules for the PySide6 shell.
- Tests: tests/test_episode_expansion.py, tests/test_episode_table_delegate.py, tests/test_gui_theme.py, tests/test_roster_model.py, tests/test_workspace_automux.py, tests/test_workspace_expansion.py, tests/test_workspace_poster_warmup.py

### `plex_renamer/gui_qt/widgets/_automux_tracks.py` — AutoMux tracks section (spec §8.1/§8.2): embedded-track keep/strip and
- `AutoMuxTracksWidget` (used by: plex_renamer.gui_qt.widgets._media_workspace_automux)
- Tests: tests/test_automux_tracks_widget.py, tests/test_episode_expansion.py, tests/test_work_panel.py, tests/test_workspace_automux.py

### `plex_renamer/gui_qt/widgets/_bulk_assign_panel.py` — BulkAssignPanel — two-pane files→slots surface for GUI V4 Plan 4 (Bulk Assign).
- `BulkFilesModel` — All-file rows: stageable pool files, read-only assigned files, staged
- `BulkFilesView` — Drag source: file rows, single-select.
- `BulkSlotsModel` — Season-grouped slot rows: header rows + claim/staged/missing slot rows.
- `BulkSlotsView` — Drop target: emits pair_dropped when a file is dragged onto a slot row.
- `BulkAssignPanel` — Files/slots two-pane staging surface for GUI V4 Plan 4 Bulk Assign. (used by: plex_renamer.gui_qt.widgets._work_panel)
- Tests: tests/test_bulk_assign_panel.py

### `plex_renamer/gui_qt/widgets/_episode_expansion.py` — EpisodeExpansionCard — persistent-editor detail card for an expanded
- `episode_row_actions(row) -> list[tuple[str, str]]` — Action ids + labels available for one episode-guide row.
- `EpisodeExpansionCard` (used by: plex_renamer.gui_qt.widgets._media_workspace_state)
- Tests: tests/test_episode_expansion.py, tests/test_episode_table_delegate.py, tests/test_qt_workspace_widgets.py, tests/test_workspace_automux.py, tests/test_workspace_expansion.py

### `plex_renamer/gui_qt/widgets/_episode_table_delegate.py` — Painted episode-table rows: EpisodeTableDelegate + EpisodeTableView (GUI V4 Plan 3).
- `EpisodeTableDelegate` (used by: plex_renamer.gui_qt.widgets._work_panel)
- `EpisodeTableView` (used by: plex_renamer.gui_qt.widgets._work_panel)
- Tests: tests/test_episode_expansion.py, tests/test_episode_table_delegate.py, tests/test_qt_perf_guards.py

### `plex_renamer/gui_qt/widgets/_episode_table_model.py` — Read-model over ScanState + EpisodeGuide for the work-panel episode table (GUI V4 Plan 3).
- `EpisodeRowData` (used by: plex_renamer.gui_qt.widgets._episode_table_delegate)
- `EpisodeTableModel` (used by: plex_renamer.gui_qt.widgets._work_panel)
- Tests: tests/conftest_qt.py, tests/test_episode_table_delegate.py, tests/test_episode_table_model.py, tests/test_qt_async_guide.py, tests/test_qt_media_workspace.py, tests/test_qt_perf_guards.py, tests/test_workspace_expansion.py

### `plex_renamer/gui_qt/widgets/_formatting.py` — Small shared formatting helpers for Qt widgets.
- `clamped_percent(score) -> int` (used by: plex_renamer.gui_qt.widgets._episode_table_model, plex_renamer.gui_qt.widgets._roster_model, plex_renamer.gui_qt.widgets._work_panel)
- `percent_text(score) -> str` (used by: plex_renamer.gui_qt.widgets._match_picker_results)

### `plex_renamer/gui_qt/widgets/_history_tab_banner.py` — Revert-banner presentation helpers for HistoryTab.
- `show_revert_banner(banner, revert_button, info_label, *, info_text) -> None` (used by: plex_renamer.gui_qt.widgets.history_tab)
- `hide_revert_banner(banner, revert_button) -> None` (used by: plex_renamer.gui_qt.widgets.history_tab)

### `plex_renamer/gui_qt/widgets/_history_tab_state.py` — State and revert workflow helpers for HistoryTab.
- `HistoryToolbarState`
- `HistoryRevertBannerState`
- `build_history_toolbar_state(jobs, *, shown_count, has_current_selection) -> HistoryToolbarState` (used by: plex_renamer.gui_qt.widgets.history_tab)
- `sync_pending_revert_job_ids(pending_job_ids, jobs) -> list[str]` (used by: plex_renamer.gui_qt.widgets.history_tab)
- `is_revertible_job(job) -> bool`
- `completed_revertible_jobs(jobs) -> list`
- `can_revert_checked_jobs(jobs) -> bool` (used by: plex_renamer.gui_qt.widgets.history_tab)
- `pending_revert_selection_changed(pending_job_ids, selected_jobs) -> bool` (used by: plex_renamer.gui_qt.widgets.history_tab)
- `begin_revert_banner_state(jobs) -> HistoryRevertBannerState | None` (used by: plex_renamer.gui_qt.widgets.history_tab)
- `collect_confirm_revert_jobs(history_jobs, pending_job_ids) -> list` (used by: plex_renamer.gui_qt.widgets.history_tab)
- `revert_jobs(queue_controller, jobs) -> list[str]` (used by: plex_renamer.gui_qt.widgets.history_tab)

### `plex_renamer/gui_qt/widgets/_image_utils.py` — Shared image conversion helpers for Qt worker-thread handoff.
- `pil_to_raw(pil_image) -> tuple[bytes, int, int]` — Convert a PIL image into raw RGBA bytes for thread-safe transport. (used by: plex_renamer.gui_qt.widgets._job_detail_poster, plex_renamer.gui_qt.widgets._roster_model)
- `raw_to_pixmap(raw_data) -> QPixmap` — Convert raw RGBA bytes into a QPixmap on the main Qt thread. (used by: plex_renamer.gui_qt.widgets._job_detail_poster, plex_renamer.gui_qt.widgets._roster_model)
- `scale_pixmap_for_device(pixmap, size, *, device_pixel_ratio, aspect_mode) -> QPixmap` — Return a pixmap scaled for the target logical size on a HiDPI display. (used by: plex_renamer.gui_qt.widgets._job_detail_poster, plex_renamer.gui_qt.widgets._roster_delegate)
- `build_placeholder_pixmap(size, *, title, subtitle, accent, device_pixel_ratio) -> QPixmap` — Create a styled placeholder artwork card for empty poster slots. (used by: plex_renamer.gui_qt.widgets._roster_delegate)
- Tests: tests/test_qt_queue_history.py

### `plex_renamer/gui_qt/widgets/_job_detail_data.py` — Formatting and path helpers for JobDetailPanel.
- `build_job_summary(job) -> str` (used by: plex_renamer.gui_qt.widgets.job_detail_panel)
- `build_job_meta_line(job, *, history_mode) -> str` (used by: plex_renamer.gui_qt.widgets.job_detail_panel)
- `format_job_timestamp(value) -> str`
- `build_job_fact_values(job) -> dict[str, str]` (used by: plex_renamer.gui_qt.widgets.job_detail_panel)
- `folder_preview_data(job) -> tuple[str, str] | None` (used by: plex_renamer.gui_qt.widgets._job_detail_preview)
- `folder_preview_source_name(job, *, include_media_name) -> str | None` (used by: plex_renamer.gui_qt.widgets._job_detail_preview)
- `movie_target_folder_name(job) -> str | None`
- `target_paths(job) -> list[Path]`
- `job_target_root(job) -> Path`
- `primary_target_path(job) -> Path | None` (used by: plex_renamer.gui_qt.widgets.job_detail_panel)
- `final_target_dir_relative(job, op) -> Path` (used by: plex_renamer.gui_qt.widgets._job_detail_preview)
- `resolve_openable_path(path) -> Path | None` (used by: plex_renamer.gui_qt.widgets.job_detail_panel)
- Tests: tests/test_qt_job_detail_panel.py

### `plex_renamer/gui_qt/widgets/_job_detail_poster.py` — Poster loading workflow for JobDetailPanel.
- `JobDetailPosterWorkflow` (used by: plex_renamer.gui_qt.widgets.job_detail_panel)

### `plex_renamer/gui_qt/widgets/_job_detail_preview.py` — Preview tree data builders for JobDetailPanel.
- `JobPreviewRow` (used by: plex_renamer.gui_qt.widgets.job_detail_panel)
- `JobPreviewGroup` (used by: plex_renamer.gui_qt.widgets.job_detail_panel)
- `type_badge(file_type) -> str`
- `pair_companions_with_videos(video_ops, companion_ops) -> tuple[dict[int, list[RenameOp]], list[RenameOp]]` — Pair each companion with the video whose target stem prefixes the
- `build_job_preview_entries(job) -> list[JobPreviewEntry]` (used by: plex_renamer.gui_qt.widgets.job_detail_panel)
- Tests: tests/test_job_preview_grouping.py, tests/test_qt_job_detail_panel.py

### `plex_renamer/gui_qt/widgets/_job_detail_tree.py` — Tree presentation helpers for JobDetailPanel.
- `job_detail_empty_message(*, history_mode) -> str` (used by: plex_renamer.gui_qt.widgets.job_detail_panel)
- `create_preview_group_header(parent, label) -> QTreeWidgetItem` (used by: plex_renamer.gui_qt.widgets.job_detail_panel)
- `set_preview_group_header_label(item, *, expanded) -> None` (used by: plex_renamer.gui_qt.widgets.job_detail_panel)
- `toggle_preview_group_item(item) -> bool` (used by: plex_renamer.gui_qt.widgets.job_detail_panel)
- `refresh_preview_item_sizes(tree) -> None` (used by: plex_renamer.gui_qt.widgets.job_detail_panel)

### `plex_renamer/gui_qt/widgets/_job_list_tab.py` — Shared base class for queue and history job-list tabs.
- Tests: tests/test_qt_queue_history.py

### `plex_renamer/gui_qt/widgets/_match_picker_results.py` — Result scoring and display helpers for MatchPickerDialog.
- `MatchPickerResultEntry`
- `build_match_picker_result_entries(results, *, title_key, raw_name, year_hint, score_results_callback) -> list[MatchPickerResultEntry]` (used by: plex_renamer.gui_qt.widgets._match_picker_selection)
- `label_for_match_result(result, title_key, score) -> str`

### `plex_renamer/gui_qt/widgets/_match_picker_search.py` — Async search workflow for MatchPickerDialog.
- `MatchPickerSearchCoordinator` (used by: plex_renamer.gui_qt.widgets.match_picker_dialog)

### `plex_renamer/gui_qt/widgets/_match_picker_selection.py` — Selection and list-state helpers for MatchPickerDialog.
- `MatchPickerSelectionCoordinator` (used by: plex_renamer.gui_qt.widgets.match_picker_dialog)

### `plex_renamer/gui_qt/widgets/_media_helpers.py` — Pure helper functions for media workspace presentation logic.
- `confidence_band(score, *, state, media_type) -> str` (used by: plex_renamer.gui_qt.widgets._roster_model)
- `confidence_fill_color(score, *, state, media_type) -> str` (used by: plex_renamer.gui_qt.widgets._roster_model)
- `band_color(band) -> str`
- `state_status(state, *, media_type) -> tuple[str, QColor]` (used by: plex_renamer.gui_qt.widgets._roster_model, plex_renamer.gui_qt.widgets._work_panel)
- `state_status_tone(state, *, media_type) -> str` (used by: plex_renamer.gui_qt.widgets._roster_model, plex_renamer.gui_qt.widgets._work_panel)
- `is_fully_ready_state(state) -> bool` (used by: plex_renamer.gui_qt.widgets._media_workspace_queue_actions)
- `is_state_queue_approvable(state, *, media_type) -> bool` (used by: plex_renamer.gui_qt.widgets._media_workspace_action_bar, plex_renamer.gui_qt.widgets._media_workspace_queue_actions, plex_renamer.gui_qt.widgets._media_workspace_refresh, plex_renamer.gui_qt.widgets._media_workspace_roster, plex_renamer.gui_qt.widgets._media_workspace_sync, plex_renamer.gui_qt.widgets._roster_model)
- `has_episode_problems(state) -> bool` — True when the show match is settled but episode mapping has issues:
- `is_specials_unmapped_only_state(state) -> bool` — All regular (season >= 1) episodes mapped cleanly; the remaining
- `roster_group(state, *, media_type) -> str` (used by: plex_renamer.gui_qt.widgets._media_workspace_refresh, plex_renamer.gui_qt.widgets._roster_model)
- `auto_accept_threshold(settings) -> float`
- `state_key(state) -> str` (used by: plex_renamer.gui_qt.widgets._media_workspace_state)
- `roster_item_key(state) -> str` (used by: plex_renamer.gui_qt.widgets._roster_model)
- `roster_selection_key(state) -> str | None` (used by: plex_renamer.gui_qt.widgets._media_workspace_match_actions, plex_renamer.gui_qt.widgets._media_workspace_queue_actions, plex_renamer.gui_qt.widgets._media_workspace_refresh, plex_renamer.gui_qt.widgets._media_workspace_view)
- `placeholder_initials(text) -> str` (used by: plex_renamer.gui_qt.widgets._roster_model)
- `preview_status_label(preview) -> str` (used by: plex_renamer.gui_qt.widgets._episode_table_model)
- `preview_status_tone(preview) -> str` (used by: plex_renamer.gui_qt.widgets._episode_table_model)
- `season_label(season_num, *, name) -> str` (used by: plex_renamer.gui_qt.widgets._episode_table_model)
- `repolish(widget) -> None` (used by: plex_renamer.gui_qt.widgets._settings_tab_state)
- `format_batch_result(result) -> str` (used by: plex_renamer.gui_qt.widgets._media_workspace_queue_actions)
- Tests: tests/test_manual_assign_queueable.py, tests/test_qt_media_workspace.py, tests/test_qt_workspace_widgets.py, tests/test_roster_classification.py

### `plex_renamer/gui_qt/widgets/_media_workspace_action_bar.py` — Button-state orchestration for the media workspace action bar.
- `update_action_bar(workspace) -> None` (used by: plex_renamer.gui_qt.widgets._media_workspace_actions)
- `set_roster_queue_button_text(workspace, text) -> None` (used by: plex_renamer.gui_qt.widgets._media_workspace_actions)
- `sync_action_button_metrics(workspace) -> None` (used by: plex_renamer.gui_qt.widgets._media_workspace_actions)

### `plex_renamer/gui_qt/widgets/_media_workspace_action_state.py` — Action-label and eligibility helpers for the media workspace.
- `media_noun(workspace) -> str` (used by: plex_renamer.gui_qt.widgets._media_workspace_actions, plex_renamer.gui_qt.widgets._media_workspace_queue_actions)
- `queue_selected_label(workspace) -> str` (used by: plex_renamer.gui_qt.widgets._media_workspace_actions)
- `primary_action_label(workspace, state) -> str` (used by: plex_renamer.gui_qt.widgets._media_workspace_action_bar, plex_renamer.gui_qt.widgets._media_workspace_actions)
- `fix_match_label(_workspace, state) -> str` (used by: plex_renamer.gui_qt.widgets._media_workspace_action_bar, plex_renamer.gui_qt.widgets._media_workspace_actions, plex_renamer.gui_qt.widgets._media_workspace_match_actions)
- `fix_match_tone(state) -> str` (used by: plex_renamer.gui_qt.widgets._media_workspace_action_bar)
- `needs_inline_match_choice(state) -> bool` (used by: plex_renamer.gui_qt.widgets._media_workspace_action_bar, plex_renamer.gui_qt.widgets._media_workspace_actions)
- `can_inline_assign_season(workspace, state) -> bool` (used by: plex_renamer.gui_qt.widgets._media_workspace_action_bar, plex_renamer.gui_qt.widgets._media_workspace_actions)
- `can_inline_approve(state) -> bool` (used by: plex_renamer.gui_qt.widgets._media_workspace_action_bar, plex_renamer.gui_qt.widgets._media_workspace_actions)
- `can_fix_match(state) -> bool` (used by: plex_renamer.gui_qt.widgets._media_workspace_action_bar, plex_renamer.gui_qt.widgets._media_workspace_actions)
- `can_unassign_all(state) -> bool` — True when the selected show has at least one assigned file to clear. (used by: plex_renamer.gui_qt.widgets._media_workspace_actions)

### `plex_renamer/gui_qt/widgets/_media_workspace_actions.py` — Action orchestration helpers for the media workspace.
- `MediaWorkspaceActionCoordinator` (used by: plex_renamer.gui_qt.widgets.media_workspace)

### `plex_renamer/gui_qt/widgets/_media_workspace_automux.py` — AutoMux session coordinator for the media workspace (spec §8).
- `MediaWorkspaceAutoMuxCoordinator` (used by: plex_renamer.gui_qt.widgets.media_workspace)
- Tests: tests/test_workspace_automux.py

### `plex_renamer/gui_qt/widgets/_media_workspace_lifecycle.py` — Lifecycle and state-switching helpers for the media workspace.
- `MediaWorkspaceLifecycleCoordinator` (used by: plex_renamer.gui_qt.widgets.media_workspace)
- Tests: tests/test_workspace_poster_warmup.py

### `plex_renamer/gui_qt/widgets/_media_workspace_match_actions.py` — Rematch and approval workflows for the media workspace.
- `fix_match(workspace, *, match_picker_dialog, warning_box) -> None` (used by: plex_renamer.gui_qt.widgets._media_workspace_actions)
- `approve_match(workspace, state) -> None` (used by: plex_renamer.gui_qt.widgets._media_workspace_actions)
- `prompt_assign_season(workspace, state, *, input_dialog, warning_box) -> None` (used by: plex_renamer.gui_qt.widgets._media_workspace_actions)
- `apply_alternate_match(workspace, state, match, *, warning_box) -> None` (used by: plex_renamer.gui_qt.widgets._media_workspace_actions)
- `apply_selected_match(workspace, state, chosen, *, tmdb, warning_box) -> None`
- `finish_tv_rematch(workspace, updated_state, tmdb) -> None`

### `plex_renamer/gui_qt/widgets/_media_workspace_queue_actions.py` — Queue-oriented action workflows for the media workspace.
- `queue_selected_state(workspace, *, warning_box) -> None` (used by: plex_renamer.gui_qt.widgets._media_workspace_actions)
- `queue_checked(workspace, *, question_box, warning_box) -> None` (used by: plex_renamer.gui_qt.widgets._media_workspace_actions)
- `summarize_skip_reasons(workspace, states) -> dict[str, int]` (used by: plex_renamer.gui_qt.widgets._media_workspace_actions)
- `queue_states(workspace, states, *, empty_message, warning_box) -> None` (used by: plex_renamer.gui_qt.widgets._media_workspace_actions)
- `queue_eligibility(workspace, states)` (used by: plex_renamer.gui_qt.widgets._media_workspace_action_bar, plex_renamer.gui_qt.widgets._media_workspace_actions)
- Tests: tests/test_qt_media_workspace.py

### `plex_renamer/gui_qt/widgets/_media_workspace_refresh.py` — Refresh and queue-normalization helpers for the media workspace.
- `MediaWorkspaceRefreshCoordinator` (used by: plex_renamer.gui_qt.widgets.media_workspace)

### `plex_renamer/gui_qt/widgets/_media_workspace_roster.py` — Roster panel: RosterListView + RosterModel + RosterDelegate (GUI V4 §3.1/§7).
- `MediaWorkspaceRosterPanel` (used by: plex_renamer.gui_qt.widgets._media_workspace_ui)
- Tests: tests/test_roster_autoselect.py

### `plex_renamer/gui_qt/widgets/_media_workspace_state.py` — State lookup and work-panel population helpers for the media workspace.
- `MediaWorkspaceStateCoordinator` (used by: plex_renamer.gui_qt.widgets.media_workspace)
- Tests: tests/test_workspace_expansion.py

### `plex_renamer/gui_qt/widgets/_media_workspace_sync.py` — Selection and checkbox synchronization helpers for the media workspace.
- `MediaWorkspaceSyncCoordinator` (used by: plex_renamer.gui_qt.widgets.media_workspace)

### `plex_renamer/gui_qt/widgets/_media_workspace_ui.py` — UI construction helpers for the media workspace.
- `MediaWorkspaceUiCoordinator` (used by: plex_renamer.gui_qt.widgets.media_workspace)

### `plex_renamer/gui_qt/widgets/_media_workspace_view.py` — Detail and selection view helpers for the media workspace.
- `MediaWorkspaceViewCoordinator` (used by: plex_renamer.gui_qt.widgets.media_workspace)
- Tests: tests/test_qt_media_workspace.py

### `plex_renamer/gui_qt/widgets/_queue_tab_actions.py` — Action workflow helpers for QueueTab.
- `remux_confirmation_message(jobs) -> str` — Confirmation copy when *jobs* include pending remuxes (spec §7.5). (used by: plex_renamer.gui_qt.widgets.queue_tab)
- `toggle_queue_running(queue_controller) -> None` (used by: plex_renamer.gui_qt.widgets.queue_tab)
- `execute_pending_jobs(queue_controller, jobs) -> list[str]` (used by: plex_renamer.gui_qt.widgets.queue_tab)
- `execute_focused_pending_job(queue_controller, focused_job) -> bool | None` (used by: plex_renamer.gui_qt.widgets.queue_tab)
- `pending_job_ids(jobs) -> list[str]` (used by: plex_renamer.gui_qt.widgets.queue_tab)
- `build_remove_confirmation_message(pending_jobs) -> str` (used by: plex_renamer.gui_qt.widgets.queue_tab)
- Tests: tests/test_remux_confirmation.py

### `plex_renamer/gui_qt/widgets/_queue_tab_presentation.py` — Presentation helpers for QueueTab widgets.
- `apply_remove_button_state(button, *, enabled) -> None` (used by: plex_renamer.gui_qt.widgets.queue_tab)

### `plex_renamer/gui_qt/widgets/_queue_tab_state.py` — Pure view-state helpers for QueueTab.
- `QueueToolbarState`
- `QueueActionState`
- `build_queue_toolbar_state(jobs, *, shown_count, has_current_selection, is_running) -> QueueToolbarState` (used by: plex_renamer.gui_qt.widgets.queue_tab)
- `build_queue_action_state(focused_job, checked_jobs) -> QueueActionState` (used by: plex_renamer.gui_qt.widgets.queue_tab)
- `remove_button_css_class(*, enabled) -> str` (used by: plex_renamer.gui_qt.widgets._queue_tab_presentation)
- `checked_pending_jobs(jobs) -> list` (used by: plex_renamer.gui_qt.widgets.queue_tab)
- Tests: tests/test_qt_queue_history.py

### `plex_renamer/gui_qt/widgets/_roster_delegate.py` — Painted roster rows: RosterDelegate + RosterListView (GUI V4 §7).
- `RosterDelegate` (used by: plex_renamer.gui_qt.widgets._media_workspace_roster)
- `RosterListView` (used by: plex_renamer.gui_qt.widgets._media_workspace_roster)
- Tests: tests/test_roster_delegate.py

### `plex_renamer/gui_qt/widgets/_roster_model.py` — Read-model exposing ScanStates to the roster QListView (GUI V4 §7).
- `RosterRowData` (used by: plex_renamer.gui_qt.widgets._roster_delegate)
- `RosterModel` (used by: plex_renamer.gui_qt.widgets._media_workspace_roster)
- Tests: tests/conftest_qt.py, tests/test_qt_media_workspace.py, tests/test_roster_delegate.py, tests/test_roster_model.py, tests/test_workspace_automux.py, tests/test_workspace_expansion.py, tests/test_workspace_poster_warmup.py

### `plex_renamer/gui_qt/widgets/_settings_automux_page.py` — AutoMux settings page (spec §3) — replaces the hidden Tools shell.
- `AutoMuxSettingsPage` (used by: plex_renamer.gui_qt.widgets._settings_tab_sections)
- Tests: tests/test_settings_tab_automux.py

### `plex_renamer/gui_qt/widgets/_settings_metadata_page.py` — Metadata export settings page (spec: local-metadata-artwork).
- `MetadataSettingsPage` (used by: plex_renamer.gui_qt.widgets._settings_tab_sections)

### `plex_renamer/gui_qt/widgets/_settings_tab_actions.py` — Action and status helpers for the settings tab.
- `SettingsTabActionsCoordinator` (used by: plex_renamer.gui_qt.widgets.settings_tab)
- `format_bytes(size_bytes) -> str`
- `repolish_widget(widget) -> None`

### `plex_renamer/gui_qt/widgets/_settings_tab_sections.py` — Section-building helpers for the settings tab.
- `SettingsSectionCard` — A settings section card with a title header row and content area. (used by: plex_renamer.gui_qt.widgets._settings_automux_page, plex_renamer.gui_qt.widgets._settings_metadata_page)
- `SettingsTabSectionsBuilder` (used by: plex_renamer.gui_qt.widgets.settings_tab)
- Tests: tests/test_settings_tab_cache.py

### `plex_renamer/gui_qt/widgets/_settings_tab_state.py` — State synchronization helpers for the settings tab.
- `SettingsTabStateCoordinator` (used by: plex_renamer.gui_qt.widgets.settings_tab)

### `plex_renamer/gui_qt/widgets/_toast_manager_layout.py` — Layout and overflow helpers for toast notifications.
- `ToastManagerGeometry`
- `count_direct_toasts(toasts, *, summary_toast) -> int` (used by: plex_renamer.gui_qt.widgets.toast_manager)
- `summary_toast_copy(overflow_count) -> tuple[str, str]` (used by: plex_renamer.gui_qt.widgets.toast_manager)
- `plan_toast_manager_geometry(parent_width, parent_height, *, toast_heights, spacing, margin, min_width, max_width) -> ToastManagerGeometry` (used by: plex_renamer.gui_qt.widgets.toast_manager)
- Tests: tests/test_qt_toasts.py

### `plex_renamer/gui_qt/widgets/_work_panel.py` — MediaWorkPanel — header / season strip / toolbar / episode table
- `MediaWorkPanel` (used by: plex_renamer.gui_qt.widgets._media_workspace_ui)
- Tests: tests/test_qt_async_guide.py, tests/test_work_panel.py, tests/test_workspace_automux.py, tests/test_workspace_expansion.py

### `plex_renamer/gui_qt/widgets/_workspace_widget_primitives.py` — Primitive widgets shared by media workspace roster and preview rows.
- `paint_check_indicator(painter, rect, state) -> None` — Paint the rounded indicator shared by MasterCheckBox and the roster delegate. (used by: plex_renamer.gui_qt.widgets._roster_delegate)
- `paint_mini_progress(painter, rect, *, value, color) -> None` — Paint the roster delegate's compact track-and-fill progress bar. (used by: plex_renamer.gui_qt.widgets._roster_delegate)
- `RosterPosterBridge` (used by: plex_renamer.gui_qt.widgets._roster_model)
- `MasterCheckBox` — Tri-state display checkbox that toggles like a normal binary control. (used by: plex_renamer.gui_qt.widgets._media_workspace_roster, plex_renamer.gui_qt.widgets._work_panel)
- `ElidedLabel` (used by: plex_renamer.gui_qt.widgets.scan_progress)
- Tests: tests/test_episode_table_model.py, tests/test_qt_workspace_widgets.py

### `plex_renamer/gui_qt/widgets/busy_overlay.py` — BusyOverlay: translucent scrim + spinner + label over any panel (spec §7).
- `Spinner` — Rotating accent arc.  Plan 6's loading screen reuses this widget.
- `BusyOverlay`
- `busy_scope(target, text, *, delay_ms, immediate)` (used by: plex_renamer.gui_qt._main_window_state, plex_renamer.gui_qt.widgets._media_workspace_actions, plex_renamer.gui_qt.widgets._media_workspace_queue_actions)
- Tests: tests/test_qt_busy_overlay.py, tests/test_qt_chrome.py, tests/test_qt_media_workspace.py

### `plex_renamer/gui_qt/widgets/empty_state.py` — Empty-state widget shown when no folder has been selected.
- `EmptyStateWidget` — Centered drop zone with folder picker and recent folders. (used by: plex_renamer.gui_qt.widgets._media_workspace_ui)

### `plex_renamer/gui_qt/widgets/episode_assign_dialog.py` — Episode assignment dialog: multi-select slots or pick a file.
- `EpisodeAssignDialog` — Season-grouped, collapsible multi-select episode picker. (used by: plex_renamer.gui_qt.widgets._media_workspace_actions)
- Tests: tests/test_qt_media_workspace.py

### `plex_renamer/gui_qt/widgets/history_tab.py` — History tab — controller-backed history view for Phase 4.
- `HistoryTab` — History tab backed by QueueController. (used by: plex_renamer.gui_qt._main_window_tabs)
- Tests: tests/test_qt_queue_history.py

### `plex_renamer/gui_qt/widgets/job_detail_panel.py` — Shared job detail panel for queue and history tabs.
- `JobDetailPanel` — Shows the selected job summary, preview, and optional poster. (used by: plex_renamer.gui_qt.widgets._job_list_tab)
- Tests: tests/test_qt_job_detail_panel.py, tests/test_queue_tab_remux.py

### `plex_renamer/gui_qt/widgets/match_picker_dialog.py` — Dialog for choosing or searching TMDB matches in the Qt shell.
- `MatchPickerDialog` — Pick from cached TMDB results or run a new search. (used by: plex_renamer.gui_qt.widgets.media_workspace)
- Tests: tests/test_qt_media_workspace.py

### `plex_renamer/gui_qt/widgets/media_workspace.py` — Media workspace widget for TV Shows and Movies tabs.
- `MediaWorkspace` — TV or Movie tab workspace with state-driven content switching. (used by: plex_renamer.gui_qt._main_window_tabs)
- Tests: tests/test_qt_media_workspace.py, tests/test_workspace_expansion.py

### `plex_renamer/gui_qt/widgets/queue_tab.py` — Queue tab — controller-backed queue view for Phase 4.
- `QueueTab` — Queue tab backed by QueueController. (used by: plex_renamer.gui_qt._main_window_tabs)
- Tests: tests/test_qt_queue_history.py

### `plex_renamer/gui_qt/widgets/scan_progress.py` — Scanning progress dashboard shown while batch scans are running.
- `conveyor_offset(elapsed_ms, slot_w, cycle_ms) -> float`
- `overall_progress_fraction(checklist_len, active_index, done, total, completed) -> float` — Whole-scan progress in [0,1]: each phase is an equal slice; the active
- `ScanProgressWidget` — Structured progress dashboard for active batch scans. (used by: plex_renamer.gui_qt.widgets._media_workspace_ui, plex_renamer.gui_qt.widgets.media_workspace)
- Tests: tests/test_qt_workspace_widgets.py, tests/test_scan_progress.py

### `plex_renamer/gui_qt/widgets/segmented_control.py` — Compact segmented control widget for toolbar-style filters.
- `SegmentedControl` — Exclusive segmented buttons keyed by their visible labels. (used by: plex_renamer.gui_qt.widgets._bulk_assign_panel, plex_renamer.gui_qt.widgets._job_list_tab, plex_renamer.gui_qt.widgets._work_panel)

### `plex_renamer/gui_qt/widgets/settings_tab.py` — Settings tab.
- `SettingsTab` — Scrollable settings panel with section cards. (used by: plex_renamer.gui_qt._main_window_tabs)
- Tests: tests/test_qt_main_window.py, tests/test_settings_longpath.py, tests/test_settings_tab_automux.py, tests/test_settings_tab_cache.py

### `plex_renamer/gui_qt/widgets/status_chip.py` — Season/status chips shared by the roster delegate and (Plan 3) season strip.
- `ChipSpec` (used by: plex_renamer.gui_qt.widgets._episode_expansion, plex_renamer.gui_qt.widgets._roster_model)
- `season_chip_specs(report, *, max_chips, drop_empty) -> list[ChipSpec]` (used by: plex_renamer.gui_qt.widgets._roster_model)
- `season_strip_specs(report) -> list[tuple[int, ChipSpec]]` — Season-strip chip specs: one per season (sorted) + specials last as (used by: plex_renamer.gui_qt.widgets._work_panel)
- `chip_font_metrics() -> QFontMetrics` — Metrics for the chip font — hit-testing must use these, not the view (used by: plex_renamer.gui_qt.widgets._roster_delegate)
- `chip_row_height() -> int` (used by: plex_renamer.gui_qt.widgets._episode_expansion)
- `chip_rects(origin_x, origin_y, chips, font_metrics) -> list[QRect]` (used by: plex_renamer.gui_qt.widgets._episode_expansion)
- `paint_chip_row(painter, origin_x, origin_y, chips) -> None` (used by: plex_renamer.gui_qt.widgets._episode_expansion)
- `chip_rects_wrapped(origin_x, origin_y, chips, font_metrics, max_width) -> list[QRect]` — Lay chips left-to-right, wrapping to a new row when the next chip would (used by: plex_renamer.gui_qt.widgets._roster_delegate)
- `chip_wrapped_height(chips, font_metrics, max_width) -> int` (used by: plex_renamer.gui_qt.widgets._roster_delegate)
- `paint_chip_row_wrapped(painter, origin_x, origin_y, chips, max_width) -> None` (used by: plex_renamer.gui_qt.widgets._roster_delegate)
- Tests: tests/test_roster_delegate.py, tests/test_status_chip.py

### `plex_renamer/gui_qt/widgets/tab_badge.py` — Small tab badge widgets for queue and history counts.
- `TabBadge` — Tab-side count badge with optional failure pip. (used by: plex_renamer.gui_qt._main_window_tabs)
- Tests: tests/test_tab_badge.py

### `plex_renamer/gui_qt/widgets/toast_manager.py` — Lightweight toast notifications for the Qt shell.
- `ToastManager` — Bottom-right stacked toast notification container. (used by: plex_renamer.gui_qt.main_window)
- Tests: tests/test_qt_toasts.py
