# Audit Change Log

## Audit 2026-07-13 (bef7acc) vs baseline (1d26997)

- Headline: 176 modules, 38404 LOC, 0 high-confidence dead symbols, 2 cycles
- No notable changes since baseline.

## Audit 2026-07-13 (1d26997) vs baseline (486aaef)

- Headline: 176 modules, 38404 LOC, 0 high-confidence dead symbols, 2 cycles
- Added: `plex_renamer/engine/_discovery_ports.py`
- Notable movements:
  - `plex_renamer/app/controllers/_queue_history_helpers.py`: coverage 79.1 -> 94.1
  - `plex_renamer/app/controllers/media_controller.py`: resolved dead symbol `_movie_discovery` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/app/controllers/queue_controller.py`: resolved dead symbol `get_latest_revertible_job` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/app/controllers/queue_controller.py`: resolved dead symbol `record_completed_job` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/app/models/state_models.py`: new dead symbol `actionable_indices` (dynamic-or-unresolved, 60%)
  - `plex_renamer/app/models/state_models.py`: resolved dead symbol `ignored` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/app/models/state_models.py`: resolved dead symbol `is_active` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/app/models/state_models.py`: resolved dead symbol `is_fresh` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/app/services/tv_library_discovery_service.py`: resolved dead symbol `_child_title_matches_parent` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/app/services/tv_library_discovery_service.py`: resolved dead symbol `_counts_as_season_subdir` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/app/services/tv_library_discovery_service.py`: resolved dead symbol `_scan_children` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/engine/_batch_orchestrators.py`: resolved dead symbol `_boost_tv_scores_with_episode_evidence` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/engine/_batch_orchestrators.py`: resolved dead symbol `is_tv_library` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/engine/_batch_orchestrators.py`: resolved dead symbol `rematch_movie` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/engine/_tv_scanner.py`: resolved dead symbol `get_mismatch_info` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/engine/_tv_scanner.py`: resolved dead symbol `invalidate_cache` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/engine/episode_assignments.py`: resolved dead symbol `ingest_preview_items` (was test-referenced, 60%)
  - `plex_renamer/engine/models.py`: resolved dead symbol `actionable_file_count` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/engine/models.py`: resolved dead symbol `all_skipped` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/engine/models.py`: resolved dead symbol `is_move` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/engine/models.py`: resolved dead symbol `match_pct` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/app.py`: resolved dead symbol `_popup_filter` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/main_window.py`: resolved dead symbol `_active_media_workspace_for_shortcuts` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/main_window.py`: resolved dead symbol `_active_workspace` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/main_window.py`: resolved dead symbol `_capture_active_snapshot` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/main_window.py`: resolved dead symbol `_refresh_media_workspaces` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/main_window.py`: resolved dead symbol `_restore_tmdb_cache_snapshot` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/main_window.py`: resolved dead symbol `_save_window_state` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/main_window.py`: resolved dead symbol `_text_input_focused` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_bulk_assign_panel.py`: new dead symbol `_claimed_file_by_key` at line 550 (dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_bulk_assign_panel.py`: resolved dead symbol `_claimed_file_by_key` at line 442 (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_bulk_assign_panel.py`: resolved dead symbol `_claimed_file_by_key` at line 551 (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_episode_expansion.py`: new dead symbol `_copy_buttons` at line 390 (dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_episode_expansion.py`: new dead symbol `_header_row` at line 212 (dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_episode_expansion.py`: resolved dead symbol `_copy_buttons` at line 158 (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_episode_expansion.py`: resolved dead symbol `_copy_buttons` at line 392 (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_episode_expansion.py`: resolved dead symbol `_header_row` at line 162 (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_episode_expansion.py`: resolved dead symbol `_header_row` at line 214 (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_episode_table_delegate.py`: resolved dead symbol `expansion_requested` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_episode_table_model.py`: resolved dead symbol `collapsible` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_episode_table_model.py`: resolved dead symbol `episode_search` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_episode_table_model.py`: resolved dead symbol `refresh_checks` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_episode_table_model.py`: resolved dead symbol `search_text` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_formatting.py`: coverage 60.0 -> 0.0
  - `plex_renamer/gui_qt/widgets/_image_utils.py`: resolved dead symbol `ShimmerOverlay` (was medium-confidence, 60%)
  - `plex_renamer/gui_qt/widgets/_job_detail_poster.py`: resolved dead symbol `_poster_pixmap` at line 90 (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_job_detail_poster.py`: resolved dead symbol `_poster_pixmap` at line 110 (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_job_list_tab.py`: resolved dead symbol `_insert_panel_before_detail` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_media_helpers.py`: resolved dead symbol `companion_summary` (was medium-confidence, 60%)
  - `plex_renamer/gui_qt/widgets/_media_helpers.py`: resolved dead symbol `file_count_for_state` (was medium-confidence, 60%)
  - `plex_renamer/gui_qt/widgets/_media_helpers.py`: resolved dead symbol `make_section_header` (was medium-confidence, 60%)
  - `plex_renamer/gui_qt/widgets/_media_helpers.py`: resolved dead symbol `match_label` (was medium-confidence, 60%)
  - `plex_renamer/gui_qt/widgets/_media_helpers.py`: resolved dead symbol `preview_band` (was medium-confidence, 60%)
  - `plex_renamer/gui_qt/widgets/_media_helpers.py`: resolved dead symbol `preview_heading` (was medium-confidence, 60%)
  - `plex_renamer/gui_qt/widgets/_media_helpers.py`: resolved dead symbol `preview_target_text` (was medium-confidence, 60%)
  - `plex_renamer/gui_qt/widgets/_media_helpers.py`: resolved dead symbol `roster_signature` (was medium-confidence, 60%)
  - `plex_renamer/gui_qt/widgets/_media_helpers.py`: resolved dead symbol `state_match_summary` (was medium-confidence, 60%)
  - `plex_renamer/gui_qt/widgets/_media_helpers.py`: resolved dead symbol `tv_preview_sort_key` (was medium-confidence, 60%)
  - `plex_renamer/gui_qt/widgets/_media_workspace_ui.py`: resolved dead symbol `_roster_selection_summary` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_settings_automux_page.py`: resolved dead symbol `_default_sub_edit` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_settings_automux_page.py`: resolved dead symbol `_retain_audio_edit` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_settings_automux_page.py`: resolved dead symbol `_retain_subs_edit` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_settings_automux_page.py`: resolved dead symbol `_strip_audio_cb` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_settings_automux_page.py`: resolved dead symbol `_strip_names_cb` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_settings_automux_page.py`: resolved dead symbol `_strip_subs_cb` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_settings_automux_page.py`: resolved dead symbol `_untagged_sub_edit` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_settings_metadata_page.py`: resolved dead symbol `_clearlogo_cb` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_settings_metadata_page.py`: resolved dead symbol `_embed_cover_cb` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_settings_metadata_page.py`: resolved dead symbol `_embed_tags_cb` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_settings_metadata_page.py`: resolved dead symbol `_embed_title_cb` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_settings_metadata_page.py`: resolved dead symbol `_episode_nfo_cb` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_settings_metadata_page.py`: resolved dead symbol `_episode_thumbs_cb` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_settings_metadata_page.py`: resolved dead symbol `_fanart_cb` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_settings_metadata_page.py`: resolved dead symbol `_nfo_cb` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_settings_metadata_page.py`: resolved dead symbol `_plex_naming_cb` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_settings_metadata_page.py`: resolved dead symbol `_poster_cb` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_settings_metadata_page.py`: resolved dead symbol `_season_posters_cb` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_workspace_widget_primitives.py`: resolved dead symbol `ClickableRow` (was medium-confidence, 60%)
  - `plex_renamer/gui_qt/widgets/_workspace_widget_primitives.py`: resolved dead symbol `MiniProgressBar` (was medium-confidence, 60%)
  - `plex_renamer/gui_qt/widgets/_workspace_widget_primitives.py`: resolved dead symbol `ToggleSwitch` (was medium-confidence, 60%)
  - `plex_renamer/gui_qt/widgets/job_detail_panel.py`: resolved dead symbol `_poster_pixmap` at line 231 (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/job_detail_panel.py`: resolved dead symbol `_poster_pixmap` at line 432 (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/job_detail_panel.py`: resolved dead symbol `_poster_pixmap` at line 461 (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/media_workspace.py`: resolved dead symbol `_folder_plan_text` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/media_workspace.py`: resolved dead symbol `_normalize_queue_selection` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/media_workspace.py`: resolved dead symbol `_preferred_batch_focus_index` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/media_workspace.py`: resolved dead symbol `_season_expected_count` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/media_workspace.py`: resolved dead symbol `_selected_preview` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/media_workspace.py`: resolved dead symbol `_update_preview_master_state` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/media_workspace.py`: resolved dead symbol `splitter` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/queue_tab.py`: resolved dead symbol `_navigate_to_media` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/scan_progress.py`: resolved dead symbol `QPointF` (was dynamic-or-unresolved, 90%)
  - `plex_renamer/gui_qt/widgets/settings_tab.py`: resolved dead symbol `_set_key_status` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/tab_badge.py`: resolved dead symbol `show_failure_pip` (was dynamic-or-unresolved, 100%)
  - `plex_renamer/gui_qt/widgets/toast_manager.py`: resolved dead symbol `full_message` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/job_store.py`: resolved dead symbol `_compact_positions` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/job_store.py`: resolved dead symbol `_migrate_db` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/job_store.py`: resolved dead symbol `_rebase_path` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/job_store.py`: resolved dead symbol `get_queued_tmdb_ids` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/job_store.py`: resolved dead symbol `get_running` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/job_store.py`: resolved dead symbol `is_terminal` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/job_store.py`: resolved dead symbol `remove_job` (was dynamic-or-unresolved, 60%)
  - `plex_renamer/tmdb.py`: resolved dead symbol `_get` (was dynamic-or-unresolved, 60%)
- Documentation status changes:
  - `CLAUDE.md`: current -> stale

## Audit 2026-07-13 (486aaef) vs baseline (5a19847)

- Headline: 175 modules, 39056 LOC, 0 high-confidence dead symbols, 2 cycles
- Notable movements:
  - coverage methodology changed or is unknown; per-module coverage movements suppressed

## Audit 2026-07-13 (0325ca8) vs baseline (85f4d45)

- Headline: 175 modules, 39056 LOC, 17 high-confidence dead symbols, 2 cycles
- No notable changes since baseline.

## Audit 2026-07-13 (85f4d45) vs baseline (a703ff7)

- Headline: 175 modules, 39056 LOC, 17 high-confidence dead symbols, 2 cycles
- No notable changes since baseline.

## Audit 2026-07-13 (a703ff7) vs baseline (7d129cb)

- Headline: 175 modules, 39056 LOC, 17 high-confidence dead symbols, 2 cycles
- No notable changes since baseline.

## Audit 2026-07-12 (7d129cb) vs baseline (9964529)

- Headline: 175 modules, 39056 LOC, 17 high-confidence dead symbols, 2 cycles
- No notable changes since baseline.

## Audit 2026-07-12 (9964529) vs baseline (a491dc2)

_Artifact of a partial-coverage import (evidence restored at e374638; import path now guarded)._

- Headline: 175 modules, 39056 LOC, 17 high-confidence dead symbols, 2 cycles
- Notable movements:
  - `plex_renamer/_job_execution_filesystem.py`: coverage 83.6 -> 0.0
  - `plex_renamer/_job_execution_metadata.py`: coverage 82.9 -> 0.0
  - `plex_renamer/_job_execution_remux.py`: coverage 79.6 -> 0.0
  - `plex_renamer/_job_path_propagation.py`: coverage 95.1 -> 0.0
  - `plex_renamer/_job_store_codec.py`: coverage 100.0 -> 0.0
  - `plex_renamer/_job_store_db.py`: coverage 100.0 -> 0.0
  - `plex_renamer/_job_store_ordering.py`: coverage 82.2 -> 0.0
  - `plex_renamer/_lang_normalize.py`: coverage 100.0 -> 0.0
  - `plex_renamer/_mkv_command.py`: coverage 98.1 -> 0.0
  - `plex_renamer/_mkv_locate.py`: coverage 90.2 -> 0.0
  - `plex_renamer/_mkv_probe.py`: coverage 92.2 -> 0.0
  - `plex_renamer/_mkv_tags_render.py`: coverage 98.0 -> 0.0
  - `plex_renamer/_nfo_render.py`: coverage 96.9 -> 0.0
  - `plex_renamer/_parsing_episodes.py`: coverage 97.1 -> 36.8
  - `plex_renamer/_parsing_names.py`: coverage 94.2 -> 48.8
  - `plex_renamer/_parsing_seasons.py`: coverage 96.3 -> 27.8
  - `plex_renamer/_parsing_subtitles.py`: coverage 75.6 -> 22.0
  - `plex_renamer/_parsing_titles.py`: coverage 91.7 -> 72.5
  - `plex_renamer/_parsing_tv.py`: coverage 98.3 -> 39.7
  - `plex_renamer/_tmdb_batch_search.py`: coverage 97.6 -> 16.7
  - `plex_renamer/_tmdb_image_cache.py`: coverage 83.6 -> 27.0
  - `plex_renamer/_tmdb_metadata_builder.py`: coverage 91.8 -> 14.3
  - `plex_renamer/_tmdb_metadata_cache.py`: coverage 92.4 -> 29.4
  - `plex_renamer/_tmdb_search_helpers.py`: coverage 95.7 -> 17.4
  - `plex_renamer/_tmdb_transport.py`: coverage 77.0 -> 23.0
  - `plex_renamer/app/__init__.py`: coverage 100.0 -> 0.0
  - `plex_renamer/app/controllers/__init__.py`: coverage 100.0 -> 0.0
  - `plex_renamer/app/controllers/_controller_event_helpers.py`: coverage 97.4 -> 0.0
  - `plex_renamer/app/controllers/_controller_lifecycle_workflow.py`: coverage 96.3 -> 0.0
  - `plex_renamer/app/controllers/_controller_match_helpers.py`: coverage 87.2 -> 0.0
  - `plex_renamer/app/controllers/_controller_movie_workflows.py`: coverage 92.3 -> 0.0
  - `plex_renamer/app/controllers/_controller_projection_workflow.py`: coverage 95.2 -> 0.0
  - `plex_renamer/app/controllers/_controller_session_models.py`: coverage 100.0 -> 0.0
  - `plex_renamer/app/controllers/_controller_state_helpers.py`: coverage 100.0 -> 0.0
  - `plex_renamer/app/controllers/_controller_tv_workflows.py`: coverage 96.8 -> 0.0
  - `plex_renamer/app/controllers/_job_projection_helpers.py`: coverage 77.0 -> 0.0
  - `plex_renamer/app/controllers/_match_state_helpers.py`: coverage 81.1 -> 0.0
  - `plex_renamer/app/controllers/_movie_batch_helpers.py`: coverage 68.9 -> 0.0
  - `plex_renamer/app/controllers/_movie_state_helpers.py`: coverage 88.0 -> 0.0
  - `plex_renamer/app/controllers/_queue_history_helpers.py`: coverage 79.1 -> 0.0
  - `plex_renamer/app/controllers/_queue_submission_helpers.py`: coverage 84.6 -> 0.0
  - `plex_renamer/app/controllers/_scan_operation_helpers.py`: coverage 96.9 -> 0.0
  - `plex_renamer/app/controllers/_single_show_scan_helpers.py`: coverage 71.9 -> 0.0
  - `plex_renamer/app/controllers/_tab_session_helpers.py`: coverage 100.0 -> 0.0
  - `plex_renamer/app/controllers/_tv_batch_helpers.py`: coverage 84.1 -> 0.0
  - `plex_renamer/app/controllers/_tv_state_helpers.py`: coverage 94.1 -> 0.0
  - `plex_renamer/app/controllers/media_controller.py`: coverage 96.1 -> 0.0
  - `plex_renamer/app/controllers/queue_controller.py`: coverage 80.6 -> 0.0
  - `plex_renamer/app/models/__init__.py`: coverage 100.0 -> 0.0
  - `plex_renamer/app/models/state_models.py`: coverage 95.0 -> 0.0
  - `plex_renamer/app/services/__init__.py`: coverage 100.0 -> 0.0
  - `plex_renamer/app/services/_movie_library_classification.py`: coverage 92.9 -> 0.0
  - `plex_renamer/app/services/_settings_schema.py`: coverage 95.8 -> 0.0
  - `plex_renamer/app/services/_tv_library_classification.py`: coverage 93.8 -> 0.0
  - `plex_renamer/app/services/automux_service.py`: coverage 91.2 -> 0.0
  - `plex_renamer/app/services/cache_service.py`: coverage 99.1 -> 0.0
  - `plex_renamer/app/services/command_gating_service.py`: coverage 91.7 -> 0.0
  - `plex_renamer/app/services/episode_mapping_service.py`: coverage 81.7 -> 0.0
  - `plex_renamer/app/services/episode_projection_cache.py`: coverage 98.5 -> 0.0
  - `plex_renamer/app/services/metadata_service.py`: coverage 88.6 -> 0.0
  - `plex_renamer/app/services/movie_library_discovery_service.py`: coverage 86.6 -> 0.0
  - `plex_renamer/app/services/output_destination_service.py`: coverage 92.7 -> 0.0
  - `plex_renamer/app/services/refresh_policy_service.py`: coverage 98.8 -> 0.0
  - `plex_renamer/app/services/settings_service.py`: coverage 87.2 -> 0.0
  - `plex_renamer/app/services/tv_library_discovery_service.py`: coverage 86.0 -> 0.0
  - `plex_renamer/engine/_batch_orchestrators.py`: coverage 73.1 -> 12.0
  - `plex_renamer/engine/_batch_tv_duplicates.py`: coverage 81.2 -> 14.6
  - `plex_renamer/engine/_batch_tv_episode_claims.py`: coverage 87.7 -> 16.0
  - `plex_renamer/engine/_batch_tv_match_policy.py`: coverage 70.7 -> 13.3
  - `plex_renamer/engine/_batch_tv_season_merge.py`: coverage 81.1 -> 8.8
  - `plex_renamer/engine/_episode_projection.py`: coverage 100.0 -> 24.0
  - `plex_renamer/engine/_episode_resolution.py`: coverage 93.7 -> 57.9
  - `plex_renamer/engine/_movie_scanner.py`: coverage 78.1 -> 17.4
  - `plex_renamer/engine/_mux_planner.py`: coverage 98.6 -> 0.0
  - `plex_renamer/engine/_queue_bridge.py`: coverage 85.9 -> 12.8
  - `plex_renamer/engine/_scan_runtime.py`: coverage 85.7 -> 71.4
  - `plex_renamer/engine/_state.py`: coverage 82.6 -> 39.1
  - `plex_renamer/engine/_tv_scanner.py`: coverage 87.3 -> 25.4
  - `plex_renamer/engine/_tv_scanner_consolidated.py`: coverage 89.3 -> 7.9
  - `plex_renamer/engine/_tv_scanner_normal.py`: coverage 98.4 -> 0.0
  - `plex_renamer/engine/_tv_scanner_postprocess.py`: coverage 98.1 -> 11.3
  - `plex_renamer/engine/_tv_scanner_seasons.py`: coverage 87.5 -> 10.2
  - `plex_renamer/engine/episode_assignments.py`: coverage 95.2 -> 62.2
  - `plex_renamer/engine/matching.py`: coverage 92.3 -> 13.0
  - `plex_renamer/engine/models.py`: coverage 89.7 -> 55.1
  - `plex_renamer/engine/show_details.py`: coverage 100.0 -> 84.2
  - `plex_renamer/gui_qt/_main_window_bootstrap.py`: coverage 18.4 -> 0.0
  - `plex_renamer/gui_qt/_main_window_bridges.py`: coverage 41.8 -> 0.0
  - `plex_renamer/gui_qt/_main_window_chrome.py`: coverage 10.5 -> 0.0
  - `plex_renamer/gui_qt/_main_window_feedback.py`: coverage 14.5 -> 0.0
  - `plex_renamer/gui_qt/_main_window_scan.py`: coverage 15.2 -> 0.0
  - `plex_renamer/gui_qt/_main_window_shell.py`: coverage 30.0 -> 0.0
  - `plex_renamer/gui_qt/_main_window_shortcuts.py`: coverage 25.9 -> 0.0
  - `plex_renamer/gui_qt/_main_window_state.py`: coverage 17.4 -> 0.0
  - `plex_renamer/gui_qt/_main_window_tabs.py`: coverage 20.5 -> 0.0
  - `plex_renamer/gui_qt/_main_window_tmdb.py`: coverage 22.0 -> 0.0
  - `plex_renamer/gui_qt/_scale.py`: coverage 94.4 -> 0.0
  - `plex_renamer/gui_qt/app.py`: coverage 46.0 -> 0.0
  - `plex_renamer/gui_qt/main_window.py`: coverage 51.3 -> 0.0
  - `plex_renamer/gui_qt/models/__init__.py`: coverage 100.0 -> 0.0
  - `plex_renamer/gui_qt/models/job_status_filter_proxy_model.py`: coverage 29.2 -> 0.0
  - `plex_renamer/gui_qt/models/job_table_model.py`: coverage 17.5 -> 0.0
  - `plex_renamer/gui_qt/theme.py`: coverage 100.0 -> 0.0
  - `plex_renamer/gui_qt/widgets/_automux_tracks.py`: coverage 67.9 -> 0.0
  - `plex_renamer/gui_qt/widgets/_bulk_assign_panel.py`: coverage 34.1 -> 0.0
  - `plex_renamer/gui_qt/widgets/_episode_expansion.py`: coverage 81.9 -> 0.0
  - `plex_renamer/gui_qt/widgets/_episode_table_delegate.py`: coverage 58.8 -> 0.0
  - `plex_renamer/gui_qt/widgets/_episode_table_model.py`: coverage 61.1 -> 0.0
  - `plex_renamer/gui_qt/widgets/_formatting.py`: coverage 80.0 -> 0.0
  - `plex_renamer/gui_qt/widgets/_history_tab_banner.py`: coverage 37.5 -> 0.0
  - `plex_renamer/gui_qt/widgets/_history_tab_state.py`: coverage 40.8 -> 0.0
  - `plex_renamer/gui_qt/widgets/_image_utils.py`: coverage 50.5 -> 0.0
  - `plex_renamer/gui_qt/widgets/_job_detail_data.py`: coverage 30.8 -> 0.0
  - `plex_renamer/gui_qt/widgets/_job_detail_poster.py`: coverage 26.5 -> 0.0
  - `plex_renamer/gui_qt/widgets/_job_detail_preview.py`: coverage 85.6 -> 0.0
  - `plex_renamer/gui_qt/widgets/_job_detail_tree.py`: coverage 18.6 -> 0.0
  - `plex_renamer/gui_qt/widgets/_job_list_tab.py`: coverage 14.2 -> 0.0
  - `plex_renamer/gui_qt/widgets/_match_picker_results.py`: coverage 43.8 -> 0.0
  - `plex_renamer/gui_qt/widgets/_match_picker_search.py`: coverage 35.0 -> 0.0
  - `plex_renamer/gui_qt/widgets/_match_picker_selection.py`: coverage 40.0 -> 0.0
  - `plex_renamer/gui_qt/widgets/_media_helpers.py`: coverage 46.2 -> 0.0
  - `plex_renamer/gui_qt/widgets/_media_workspace_action_bar.py`: coverage 73.8 -> 0.0
  - `plex_renamer/gui_qt/widgets/_media_workspace_action_state.py`: coverage 69.4 -> 0.0
  - `plex_renamer/gui_qt/widgets/_media_workspace_actions.py`: coverage 22.0 -> 0.0
  - `plex_renamer/gui_qt/widgets/_media_workspace_automux.py`: coverage 64.3 -> 0.0
  - `plex_renamer/gui_qt/widgets/_media_workspace_lifecycle.py`: coverage 24.6 -> 0.0
  - `plex_renamer/gui_qt/widgets/_media_workspace_match_actions.py`: coverage 13.8 -> 0.0
  - `plex_renamer/gui_qt/widgets/_media_workspace_queue_actions.py`: coverage 13.1 -> 0.0
  - `plex_renamer/gui_qt/widgets/_media_workspace_refresh.py`: coverage 53.3 -> 0.0
  - `plex_renamer/gui_qt/widgets/_media_workspace_roster.py`: coverage 87.2 -> 0.0
  - `plex_renamer/gui_qt/widgets/_media_workspace_state.py`: coverage 64.7 -> 0.0
  - `plex_renamer/gui_qt/widgets/_media_workspace_sync.py`: coverage 43.5 -> 0.0
  - `plex_renamer/gui_qt/widgets/_media_workspace_ui.py`: coverage 99.0 -> 0.0
  - `plex_renamer/gui_qt/widgets/_media_workspace_view.py`: coverage 32.3 -> 0.0
  - `plex_renamer/gui_qt/widgets/_queue_tab_actions.py`: coverage 50.0 -> 0.0
  - `plex_renamer/gui_qt/widgets/_queue_tab_presentation.py`: coverage 30.0 -> 0.0
  - `plex_renamer/gui_qt/widgets/_queue_tab_state.py`: coverage 50.0 -> 0.0
  - `plex_renamer/gui_qt/widgets/_roster_delegate.py`: coverage 74.9 -> 0.0
  - `plex_renamer/gui_qt/widgets/_roster_model.py`: coverage 66.0 -> 0.0
  - `plex_renamer/gui_qt/widgets/_settings_automux_page.py`: coverage 87.4 -> 0.0
  - `plex_renamer/gui_qt/widgets/_settings_metadata_page.py`: coverage 94.0 -> 0.0
  - `plex_renamer/gui_qt/widgets/_settings_tab_actions.py`: coverage 21.0 -> 0.0
  - `plex_renamer/gui_qt/widgets/_settings_tab_sections.py`: coverage 98.1 -> 0.0
  - `plex_renamer/gui_qt/widgets/_settings_tab_state.py`: coverage 38.4 -> 0.0
  - `plex_renamer/gui_qt/widgets/_toast_manager_layout.py`: coverage 57.1 -> 0.0
  - `plex_renamer/gui_qt/widgets/_work_panel.py`: coverage 71.8 -> 0.0
  - `plex_renamer/gui_qt/widgets/_workspace_widget_primitives.py`: coverage 77.8 -> 0.0
  - `plex_renamer/gui_qt/widgets/busy_overlay.py`: coverage 27.7 -> 0.0
  - `plex_renamer/gui_qt/widgets/empty_state.py`: coverage 55.4 -> 0.0
  - `plex_renamer/gui_qt/widgets/episode_assign_dialog.py`: coverage 13.9 -> 0.0
  - `plex_renamer/gui_qt/widgets/history_tab.py`: coverage 19.6 -> 0.0
  - `plex_renamer/gui_qt/widgets/job_detail_panel.py`: coverage 15.3 -> 0.0
  - `plex_renamer/gui_qt/widgets/match_picker_dialog.py`: coverage 25.3 -> 0.0
  - `plex_renamer/gui_qt/widgets/media_workspace.py`: coverage 64.4 -> 0.0
  - `plex_renamer/gui_qt/widgets/queue_tab.py`: coverage 18.9 -> 0.0
  - `plex_renamer/gui_qt/widgets/scan_progress.py`: coverage 67.4 -> 0.0
  - `plex_renamer/gui_qt/widgets/segmented_control.py`: coverage 88.9 -> 0.0
  - `plex_renamer/gui_qt/widgets/settings_tab.py`: coverage 83.6 -> 0.0
  - `plex_renamer/gui_qt/widgets/status_chip.py`: coverage 82.2 -> 0.0
  - `plex_renamer/gui_qt/widgets/tab_badge.py`: coverage 22.7 -> 0.0
  - `plex_renamer/gui_qt/widgets/toast_manager.py`: coverage 15.8 -> 0.0
  - `plex_renamer/job_executor.py`: coverage 70.7 -> 0.0
  - `plex_renamer/job_store.py`: coverage 79.5 -> 0.0
  - `plex_renamer/keys.py`: coverage 44.4 -> 0.0
  - `plex_renamer/thread_pool.py`: coverage 93.1 -> 0.0
  - `plex_renamer/tmdb.py`: coverage 75.7 -> 18.6

## Audit 2026-07-12 (a491dc2) vs baseline (0a637a3)

- Headline: 175 modules, 39056 LOC, 17 high-confidence dead symbols, 2 cycles
- No notable changes since baseline.

## Audit 2026-07-12 (0a637a3) vs baseline (b57f426)

- Headline: 175 modules, 39056 LOC, 17 high-confidence dead symbols, 2 cycles
- No notable changes since baseline.
