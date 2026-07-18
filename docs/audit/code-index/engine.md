<!-- Generated from audit input a74d9b12c50b; do not edit. regenerate: scripts\audit.cmd --fast -->


# Package detail: engine


### `plex_renamer/engine/__init__.py` — Rename engine package — re-exports the public API of the old ``engine`` module.
- Tests: tests/test_alt_title_matching.py, tests/test_alt_title_matching_orchestrator.py, tests/test_automux_service.py, tests/test_bulk_assign_panel.py, tests/test_command_gating_service.py, tests/test_conflict_queue_protection.py, tests/test_episode_expansion.py, tests/test_episode_expansion_confidence.py, tests/test_episode_mapping_projection.py, tests/test_episode_metadata_ownership.py, tests/test_episode_projection_cache.py, tests/test_extras_and_prefix_fixes.py, tests/test_haikyuu_matching.py, tests/test_jojo_matching.py, tests/test_manual_assign_queueable.py, tests/test_media_controller.py, tests/test_media_controller_scan_show.py, tests/test_movie_confidence_adjustments.py, tests/test_qt_async_guide.py, tests/test_qt_main_window.py, tests/test_qt_media_workspace.py, tests/test_qt_media_workspace_review_actions.py, tests/test_qt_perf_guards.py, tests/test_qt_queue_history.py, tests/test_qt_workspace_widgets.py, tests/test_queue_bridge_mux.py, tests/test_queue_controller.py, tests/test_roster_classification.py, tests/test_scan_improvements.py, tests/test_scan_state_scanner.py, tests/test_workspace_expansion.py

### `plex_renamer/engine/_batch_orchestrators.py` — Batch orchestration for TV and movie library discovery/scanning.
- `BatchTVOrchestrator` — Discovers TV show folders in a library root, matches each to TMDB, (used by: plex_renamer.app.controllers._controller_session_models, plex_renamer.app.controllers._tab_session_helpers, plex_renamer.app.controllers._tv_batch_helpers, plex_renamer.app.controllers.media_controller, plex_renamer.engine, plex_renamer.engine._core)
- `BatchMovieOrchestrator` — Discovers movie folders in a library root, matches each to TMDB, (used by: plex_renamer.engine, plex_renamer.engine._core)
- Tests: tests/test_batch_autoaccept_guards.py

### `plex_renamer/engine/_batch_tv_duplicates.py` — Duplicate-labeling helpers for batch TV discovery.
- `normalized_relative_folder(relative_folder, fallback) -> str` — (no docstring) (used by: plex_renamer.engine._batch_orchestrators, plex_renamer.engine._batch_tv_episode_claims, plex_renamer.engine._batch_tv_season_merge)
- `duplicate_priority(state) -> tuple[float, int, int, str]` — (no docstring)
- `apply_duplicate_labels(states) -> None` — Mark lower-priority TMDB matches as duplicates deterministically. (used by: plex_renamer.engine._batch_orchestrators)

### `plex_renamer/engine/_batch_tv_episode_claims.py` — Episode-claim reconciliation for scanned batch TV siblings.
- `assign_preview_source_folders(state, library_root) -> None` — Populate source-folder labels for scanned preview rows. (used by: plex_renamer.engine._batch_orchestrators)
- `reconcile_scanned_episode_claims(states, library_root) -> dict[int, ScanState]` — Merge scanned same-show TV siblings by episode claim. (used by: plex_renamer.engine._batch_orchestrators)
- Tests: tests/test_merged_show_checked_gating.py

### `plex_renamer/engine/_batch_tv_match_policy.py` — Match-selection helpers for batch TV discovery.
- `count_season_subdirs(folder) -> int` — Count Season NN subdirectories to estimate episode volume. (used by: plex_renamer.engine._batch_orchestrators)
- `episode_count_tiebreak(tmdb, scored, file_count, threshold, compare_seasons, explicit_seasons) -> tuple[dict, float, bool]` — Re-rank near-tied TMDB candidates by episode/season count proximity. (used by: plex_renamer.engine._batch_orchestrators)
- `primary_name_breaks_tie(best, runner_up, query_name, year_hint) -> bool` — True when the winner's identity evidence clearly beats the runner-up's. (used by: plex_renamer.engine._batch_orchestrators)
- `year_hint_breaks_tie(best, runner_up, year_hint) -> bool` — True when the folder's year hint matches exactly one candidate. (used by: plex_renamer.engine._batch_orchestrators)
- Tests: tests/test_show_details.py, tests/test_tiebreak_discrimination.py

### `plex_renamer/engine/_batch_tv_season_merge.py` — Season-merge helpers for batch TV orchestration.
- `preview_single_season(state) -> int | None` — Return the one season covered by ``preview_items``, or ``None``.
- `resolve_season_folder(folder, season_num) -> Path` — Return the actual directory containing episode files. (used by: plex_renamer.engine._batch_orchestrators)
- `represented_seasons(state) -> set[int]` — (no docstring) (used by: plex_renamer.engine._batch_orchestrators)
- `expanded_season_folders(state) -> dict[int, SeasonFolderEntry]` — (no docstring) (used by: plex_renamer.engine._batch_orchestrators)
- `season_merge_priority(state) -> tuple[int, float, int, str]` — (no docstring) (used by: plex_renamer.engine._batch_orchestrators)
- `merge_season_siblings(states) -> list[ScanState]` — Merge states that share a TMDB ID and have distinct season assignments. (used by: plex_renamer.engine._batch_orchestrators)
- `merge_umbrella_siblings(states) -> list[ScanState]` — Absorb explicit-season sibling folders into a same-show multi-season state. (used by: plex_renamer.engine._batch_orchestrators)
- Tests: tests/test_umbrella_season_merge.py

### `plex_renamer/engine/_core.py` — Compatibility re-export layer for the old engine monolith.

### `plex_renamer/engine/_discovery_ports.py` — Structural ports for application-owned library discovery.
- `TVDiscoveryCandidateLike` — (no docstring)
- `MovieDiscoveryCandidateLike` — (no docstring)
- `TVLibraryDiscoverer` — (no docstring) (used by: plex_renamer.engine._batch_orchestrators, plex_renamer.engine._movie_scanner)
- `MovieLibraryDiscoverer` — (no docstring) (used by: plex_renamer.engine._batch_orchestrators)

### `plex_renamer/engine/_episode_projection.py` — Project an EpisodeAssignmentTable into PreviewItem rows.
- `project_preview_items(table, *, show_info, root, media_fields) -> list[PreviewItem]` — Produce exactly one PreviewItem per FileEntry, in guide order. (used by: plex_renamer.app.controllers._tv_state_helpers, plex_renamer.app.services.episode_mapping_service, plex_renamer.engine._batch_tv_episode_claims, plex_renamer.engine._tv_scanner)
- Tests: tests/test_conflict_queue_protection.py, tests/test_duplicate_copies.py, tests/test_episode_mapping_projection.py, tests/test_episode_projection.py, tests/test_media_controller.py, tests/test_qt_media_workspace.py, tests/test_roster_classification.py, tests/test_workspace_expansion.py

### `plex_renamer/engine/_episode_resolution.py` — Shared episode resolution policy and confidence calibration.
- `TitleMatch` — (no docstring)
- `Resolution` — Outcome of resolving one file against one season's titles. (used by: plex_renamer.engine._tv_scanner_consolidated, plex_renamer.engine._tv_scanner_normal)
- `match_title_in_titles(raw_text, titles) -> TitleMatch | None` — Fuzzy-match *raw_text* against episode titles, with a strength score. (used by: plex_renamer.engine._tv_scanner_normal)
- `match_segmented_title_run(raw_title, titles, expected_count) -> tuple[tuple[int, ...], bool] | None` — Resolve a combined multi-segment title into an episode run by titles.
- `resolve_file(*, parsed_episodes, raw_title, is_season_relative, season_titles, season, season_hint) -> Resolution` — Apply the 6-rule resolution policy for one file against one season. (used by: plex_renamer.engine._tv_scanner_consolidated, plex_renamer.engine._tv_scanner_normal)
- `resolve_table_conflicts(table) -> None` — Public entry: resolve slot conflicts (used after sibling table merges). (used by: plex_renamer.engine._batch_tv_episode_claims)
- `apply_confidence_adjustments(table, *, show_info, show_match_confidence) -> None` — Raise/cap auto-assignment confidence from corroborating evidence. (used by: plex_renamer.engine._tv_scanner)
- `apply_uniform_offset_rescue(table) -> None` — Follow a uniform title-anchor offset for number-only siblings. (used by: plex_renamer.engine._tv_scanner)
- `rescue_cross_season_titles(table) -> None` — Rescue single-episode files SKIPped as 'episode not in TMDB season' — (used by: plex_renamer.engine._tv_scanner)
- `rescue_explicit_hint_slots(table) -> None` — Re-anchor lost-conflict files to their explicit S##E## slots (RC44). (used by: plex_renamer.engine._tv_scanner)
- `rescue_cross_season_segmented(table) -> None` — Re-home multi-segment files whose titles match nothing in their (used by: plex_renamer.engine._tv_scanner)
- `unassign_same_season_scattered_titles(table) -> None` — Queue files whose segment titles pin >=2 episodes of their OWN season (used by: plex_renamer.engine._tv_scanner)
- `rescue_same_season_fuzzy_titles(table) -> None` — Lost-conflict / no-match / not-in-season files whose (possibly fuzzy) (used by: plex_renamer.engine._tv_scanner)
- Tests: tests/test_acronym_titles.py, tests/test_air_date_clusters.py, tests/test_confidence_adjustment_guards.py, tests/test_conflict_resolution.py, tests/test_conflict_snapshot_staleness.py, tests/test_consolidated_assignments.py, tests/test_cross_season_number_claims.py, tests/test_disc_grouped_run_ambiguity.py, tests/test_duplicate_copies.py, tests/test_episode_resolution.py, tests/test_explicit_special_numbers.py, tests/test_extras_and_prefix_fixes.py, tests/test_fragment_anchor_guard.py, tests/test_fuzzy_title_matching.py, tests/test_lost_conflict_rescue.py, tests/test_multisegment_zero_match.py, tests/test_near_exact_titles.py, tests/test_offset_inference.py, tests/test_parsing_edgecases.py, tests/test_positional_fill_overlap.py, tests/test_run_extension.py, tests/test_run_extension_guards.py, tests/test_same_season_rescue.py, tests/test_same_season_scattered.py, tests/test_segmented_group_separators.py, tests/test_segmented_positional_fill.py, tests/test_show_name_title_and_hint_rescue.py, tests/test_specials_guards.py, tests/test_squatter_chain_rescue.py, tests/test_token_aligned_substring.py, tests/test_underscore_segments.py

### `plex_renamer/engine/_movie_scanner.py` — Movie scanning helpers and scanner implementation.
- `MovieScanner` — Scan movie files and build PreviewItems using TMDB data. (used by: plex_renamer.app.controllers._controller_movie_workflows, plex_renamer.app.controllers._controller_session_models, plex_renamer.app.controllers._movie_state_helpers, plex_renamer.app.controllers._tab_session_helpers, plex_renamer.app.controllers.media_controller, plex_renamer.engine, plex_renamer.engine._batch_orchestrators, plex_renamer.engine._core)
- Tests: tests/test_alt_title_matching_orchestrator.py, tests/test_companion_subtitles.py, tests/test_scanner_protocol_conformance.py

### `plex_renamer/engine/_mux_planner.py` — Pure mux planning: (probe, companion subs, settings) → MuxPlan.
- `MuxSettings` — Snapshot of the automux_* settings relevant to planning. (used by: plex_renamer.app.services.automux_service)
- `TrackDecision` — (no docstring)
- `SubtitleMergeDecision` — (no docstring)
- `MuxPlan` — (no docstring) (used by: plex_renamer._job_execution_remux, plex_renamer._mkv_command)
- `build_mux_plan(*, probe, companion_subs, settings, new_name, mkvmerge_path) -> MuxPlan | None` — Build the remux plan for one file, or None when no remux is needed. (used by: plex_renamer.app.services.automux_service)
- Tests: tests/test_mkv_command.py, tests/test_mkv_metadata_helpers.py, tests/test_mkvmerge_integration.py, tests/test_mux_planner.py

### `plex_renamer/engine/_queue_bridge.py` — Helpers for converting scan preview state into persistent queue jobs.
- `get_checked_indices_from_state(state) -> set[int]` — Return indices of checked, actionable preview items from a scan state. (used by: plex_renamer.app.services.command_gating_service, plex_renamer.engine, plex_renamer.engine._core)
- `build_rename_job_from_state(state, library_root, output_root, show_folder_rename, checked_indices, mux_plans) -> RenameJob` — Create a RenameJob from a TV batch scan state. (used by: plex_renamer.app.controllers._queue_submission_helpers, plex_renamer.engine, plex_renamer.engine._core)
- `build_rename_job_from_items(items, checked_indices, media_type, tmdb_id, media_name, library_root, output_root, source_folder, show_folder_rename, poster_path, mux_plans) -> RenameJob` — Create a RenameJob from raw preview items. (used by: plex_renamer.app.controllers._queue_submission_helpers, plex_renamer.engine, plex_renamer.engine._core)
- Tests: tests/test_episode_projection.py, tests/test_queue_output_targets.py, tests/test_queue_submission_automux.py

### `plex_renamer/engine/_rename_execution.py` — Rename execution helpers shared by the direct-rename and queue flows.
- `check_duplicates(items) -> None` — Flag items that would collide on the same target path. (used by: plex_renamer.app.controllers.media_controller, plex_renamer.engine, plex_renamer.engine._batch_orchestrators, plex_renamer.engine._core)
- `execute_rename(items, checked_indices, show_name, root_folder, show_folder_name) -> RenameResult` — Perform the actual file renames and moves for checked preview items. (used by: plex_renamer.engine, plex_renamer.engine._core)

### `plex_renamer/engine/_scan_runtime.py` — Shared scan-control primitives for long-running engine operations.
- `ScanCancelledError` — Raised when a long-running scan is cancelled by the user. (used by: plex_renamer.app.controllers._movie_batch_helpers, plex_renamer.app.controllers._tv_batch_helpers, plex_renamer.engine, plex_renamer.engine._batch_orchestrators, plex_renamer.engine._core)

### `plex_renamer/engine/_state.py` — Mutable engine state shared across submodules.
- `get_auto_accept_threshold() -> float` — (no docstring) (used by: plex_renamer.engine, plex_renamer.engine._batch_orchestrators, plex_renamer.engine._movie_scanner, plex_renamer.engine.matching, plex_renamer.engine.models)
- `set_auto_accept_threshold(value) -> float` — Update the runtime auto-accept threshold used by scan/review logic. (used by: plex_renamer.app.controllers._controller_event_helpers, plex_renamer.app.controllers.media_controller, plex_renamer.engine)
- `get_episode_auto_accept_threshold() -> float` — (no docstring) (used by: plex_renamer.engine, plex_renamer.engine._episode_projection, plex_renamer.engine._tv_scanner_postprocess)
- `set_episode_auto_accept_threshold(value) -> float` — Update the runtime threshold used for episode auto-mapping review. (used by: plex_renamer.app.controllers._controller_event_helpers, plex_renamer.app.controllers.media_controller, plex_renamer.engine)
- Tests: tests/test_episode_resolution.py

### `plex_renamer/engine/_tv_scanner.py` — TV scanning implementation for episode preview and completeness logic.
- `TVScanner` — Scans a TV series folder and builds PreviewItems using TMDB data. (used by: plex_renamer.app.controllers.media_controller, plex_renamer.engine, plex_renamer.engine._batch_orchestrators, plex_renamer.engine._core)
- Tests: tests/test_scan_improvements.py, tests/test_scanner_protocol_conformance.py, tests/test_tv_scanner_normal.py

### `plex_renamer/engine/_tv_scanner_consolidated.py` — Consolidated-preview helpers for TVScanner.
- `collect_absolute_files(season_dirs) -> list[AbsoluteFileEntry]` — Collect all video files sorted by absolute episode number. (used by: plex_renamer.engine._tv_scanner)
- `match_file_title_to_tmdb(raw_title, title_lookup, number_lookup, used, spaced_lookup) -> tuple[int, int, str] | None` — Match a file's title against the cross-season TMDB title lookup. (used by: plex_renamer.engine._tv_scanner)
- `try_title_based_matching(all_files, tmdb_seasons, show_name) -> list[tuple[int, int, str] | None] | None` — Two-phase matching: title claims first (all seasons incl. S0), then (used by: plex_renamer.engine._tv_scanner)
- `build_consolidated_preview(*, season_dirs, tmdb_seasons, root, show_info, media_fields, store_tmdb_data) -> list[PreviewItem]` — Build preview mapping files in absolute order to TMDB structure.
- `apply_air_date_cluster_mapping(table, tmdb_seasons) -> None` — Map folder-season-N files onto the Nth airing cluster of a single
- `build_consolidated_table(*, season_dirs, tmdb_seasons, tmdb, show_info, root, store_tmdb_data) -> EpisodeAssignmentTable` — Build the assignment table for flat/mixed multi-season folders. (used by: plex_renamer.engine._tv_scanner)
- Tests: tests/test_air_date_clusters.py, tests/test_consolidated_assignments.py, tests/test_consolidated_two_phase.py, tests/test_matching_helpers.py, tests/test_show_name_title_and_hint_rescue.py

### `plex_renamer/engine/_tv_scanner_normal.py` — Normal per-season table building for TVScanner.
- `build_normal_table(*, season_dirs, tmdb_seasons, tmdb, show_info, root, season_folders, store_tmdb_data) -> EpisodeAssignmentTable` — (no docstring) (used by: plex_renamer.engine._tv_scanner)
- Tests: tests/test_confidence_adjustment_guards.py, tests/test_conflict_resolution.py, tests/test_explicit_special_numbers.py, tests/test_extras_and_prefix_fixes.py, tests/test_parsing_edgecases.py, tests/test_specials_guards.py, tests/test_tv_scanner_normal.py

### `plex_renamer/engine/_tv_scanner_postprocess.py` — Postprocessing helpers for TVScanner previews and completeness.
- `apply_episode_review_threshold(items) -> None` — Mark low-confidence episode mappings for manual approval. (used by: plex_renamer.app.controllers._controller_event_helpers)
- `build_completeness_report(tmdb_seasons, items, checked_indices) -> CompletenessReport` — Compute completeness of matched episodes vs TMDB expectations. (used by: plex_renamer.engine._tv_scanner)
- Tests: tests/test_completeness_review_counts.py

### `plex_renamer/engine/_tv_scanner_seasons.py` — Season directory resolution helpers for TVScanner.
- `resolve_tv_season_dirs(root, *, season_hint, season_folders, get_season, match_dirs_to_tmdb_seasons) -> list[tuple[Path, int]]` — (no docstring) (used by: plex_renamer.engine._tv_scanner)
- `match_tv_dirs_to_tmdb_seasons(dirs, already_matched, *, show_info, tmdb, clean_folder_name, logger) -> list[tuple[Path, int]]` — (no docstring) (used by: plex_renamer.engine._tv_scanner)
- Tests: tests/test_extras_and_prefix_fixes.py

### `plex_renamer/engine/episode_assignments.py` — First-class file<->episode assignment table for TV scans.
- `lost_conflict_reason(season, episode) -> str` — Lost-conflict reason naming the slot the file lost the match for.
- `duplicate_copy_reason(season, episode) -> str` — Reason marking a losing duplicate copy of one episode. (used by: plex_renamer.engine._episode_resolution)
- `EpisodeSlot` — One TMDB episode (including Season 0 specials). (used by: plex_renamer.engine._episode_resolution, plex_renamer.engine._tv_scanner_normal)
- `FileEntry` — One discovered video file with its scan-time parse evidence. (used by: plex_renamer.engine._episode_projection)
- `Assignment` — Links one file to 1..N contiguous episodes in a single season.
- `EpisodeAssignmentTable` — Per-show registry of files, episode slots, and claims. (used by: plex_renamer.app.services.episode_mapping_service, plex_renamer.engine._episode_projection, plex_renamer.engine._episode_resolution, plex_renamer.engine._tv_scanner, plex_renamer.engine._tv_scanner_consolidated, plex_renamer.engine._tv_scanner_normal, plex_renamer.engine.models)
- `merge_tables(primary, other) -> dict[int, int]` — Absorb *other* into *primary*; returns old->new file id mapping. (used by: plex_renamer.engine._batch_tv_episode_claims)
- `carry_over_manual_assignments(old, new) -> None` — Re-apply manual assignments from a previous scan of the SAME show. (used by: plex_renamer.app.controllers._tv_state_helpers)
- Tests: tests/test_air_date_clusters.py, tests/test_bulk_assign_panel.py, tests/test_confidence_adjustment_guards.py, tests/test_conflict_queue_protection.py, tests/test_conflict_resolution.py, tests/test_conflict_snapshot_staleness.py, tests/test_cross_season_number_claims.py, tests/test_duplicate_copies.py, tests/test_episode_assignments.py, tests/test_episode_expansion.py, tests/test_episode_mapping_projection.py, tests/test_episode_projection.py, tests/test_episode_resolution.py, tests/test_explicit_special_numbers.py, tests/test_extras_and_prefix_fixes.py, tests/test_lost_conflict_rescue.py, tests/test_manual_assign_queueable.py, tests/test_media_controller.py, tests/test_multisegment_zero_match.py, tests/test_offset_inference.py, tests/test_parsing_edgecases.py, tests/test_qt_async_guide.py, tests/test_qt_media_workspace.py, tests/test_qt_perf_guards.py, tests/test_roster_classification.py, tests/test_same_season_rescue.py, tests/test_same_season_scattered.py, tests/test_scan_state_scanner.py, tests/test_show_name_title_and_hint_rescue.py, tests/test_specials_guards.py, tests/test_squatter_chain_rescue.py, tests/test_tv_scanner_normal.py, tests/test_workspace_expansion.py

### `plex_renamer/engine/matching.py` — Title scoring and TMDB match ranking.
- `title_similarity(a, b) -> float` — Compute a simple title similarity score between 0.0 and 1.0. (used by: plex_renamer.engine, plex_renamer.engine._core)
- `score_results(results, raw_name, year_hint, title_key) -> list[tuple[dict, float]]` — Score a list of TMDB search results against a cleaned name. (used by: plex_renamer.app.controllers.media_controller, plex_renamer.engine, plex_renamer.engine._batch_orchestrators, plex_renamer.engine._core, plex_renamer.engine._movie_scanner, plex_renamer.gui_qt.widgets._match_picker_results)
- `pick_alternate_matches(scored, *, selected_id, limit) -> list[dict]` — Return the highest-ranked alternate matches excluding the selected id. (used by: plex_renamer.app.controllers.media_controller, plex_renamer.engine, plex_renamer.engine._batch_orchestrators, plex_renamer.engine._core)
- `boost_scores_with_alt_titles(scored, raw_name, year_hint, tmdb, title_key, media_type, preferred_country, force) -> list[tuple[dict, float]]` — Re-score top candidates using TMDB alternative titles. (used by: plex_renamer.engine, plex_renamer.engine._batch_orchestrators, plex_renamer.engine._core, plex_renamer.engine._movie_scanner)
- `boost_tv_scores_with_episode_evidence(tmdb, scored, evidence) -> list[tuple[dict, float]]` — (no docstring) (used by: plex_renamer.engine, plex_renamer.engine._core)
- `apply_movie_confidence_adjustments(*, raw_confidence, file_path, tmdb_title, tmdb_year) -> float` — Return *raw_confidence* adjusted by evidence floors and caps. (used by: plex_renamer.engine, plex_renamer.engine._batch_orchestrators, plex_renamer.engine._movie_scanner)
- `score_tv_results(results, raw_name, year_hint, tmdb, *, folder, folder_score_name, episode_evidence) -> list[tuple[dict, float]]` — Score TV search results using the same logic as batch discovery. (used by: plex_renamer.app.controllers.media_controller, plex_renamer.engine, plex_renamer.engine._batch_orchestrators, plex_renamer.engine._core, plex_renamer.gui_qt.widgets._media_workspace_match_actions)
- Tests: tests/test_batch_autoaccept_guards.py, tests/test_matching_helpers.py, tests/test_movie_confidence_adjustments.py, tests/test_show_scoring_no_year.py, tests/test_show_scoring_token_subset.py

### `plex_renamer/engine/models.py` — Engine data structures — pure data classes with no scanning logic.
- `iter_season_folder_paths(entry) -> tuple[Path, ...]` — (no docstring) (used by: plex_renamer.engine._batch_tv_season_merge, plex_renamer.engine._tv_scanner_normal, plex_renamer.engine._tv_scanner_seasons)
- `CompanionFile` — A non-video file renamed alongside its parent media file. (used by: plex_renamer.app.controllers._job_projection_helpers, plex_renamer.engine, plex_renamer.engine._movie_scanner)
- `PreviewItem` — One file's rename plan.  The GUI reads these to build the preview. (used by: plex_renamer.app.controllers, plex_renamer.app.controllers._controller_match_helpers, plex_renamer.app.controllers._controller_movie_workflows, plex_renamer.app.controllers._controller_projection_workflow, plex_renamer.app.controllers._controller_session_models, plex_renamer.app.controllers._job_projection_helpers, plex_renamer.app.controllers._match_state_helpers, plex_renamer.app.controllers._movie_state_helpers, plex_renamer.app.controllers._queue_submission_helpers, plex_renamer.app.controllers._tab_session_helpers, plex_renamer.app.controllers.media_controller, plex_renamer.app.controllers.queue_controller, plex_renamer.app.services.automux_service, plex_renamer.app.services.command_gating_service, plex_renamer.app.services.episode_mapping_service, plex_renamer.engine, plex_renamer.engine._batch_orchestrators, plex_renamer.engine._batch_tv_episode_claims, plex_renamer.engine._episode_projection, plex_renamer.engine._movie_scanner, plex_renamer.engine._queue_bridge, plex_renamer.engine._rename_execution, plex_renamer.engine._tv_scanner, plex_renamer.engine._tv_scanner_consolidated, plex_renamer.engine._tv_scanner_postprocess, plex_renamer.gui_qt.widgets._media_helpers)
- `RenameResult` — Outcome of an execute_rename call. (used by: plex_renamer._job_execution_filesystem, plex_renamer._job_execution_metadata, plex_renamer._job_execution_remux, plex_renamer.app.controllers.queue_controller, plex_renamer.engine, plex_renamer.engine._rename_execution, plex_renamer.gui_qt._main_window_feedback, plex_renamer.gui_qt.main_window, plex_renamer.job_executor)
- `SeasonCompleteness` — Completeness info for a single season. (used by: plex_renamer.engine, plex_renamer.engine._tv_scanner_postprocess, plex_renamer.gui_qt.widgets.status_chip)
- `CompletenessReport` — Full completeness report for a TV series. (used by: plex_renamer.app.controllers, plex_renamer.engine, plex_renamer.engine._tv_scanner, plex_renamer.engine._tv_scanner_postprocess, plex_renamer.gui_qt.widgets.status_chip)
- `TVScanStateScanner` — Episode metadata capability retained by a TV ``ScanState``. (used by: plex_renamer.app.services.episode_mapping_service, plex_renamer.app.services.episode_projection_cache)
- `TVScannerOperations` — Full TV scan operations used by controllers and reconciliation. (used by: plex_renamer.app.controllers._tv_state_helpers, plex_renamer.app.services.episode_mapping_service, plex_renamer.engine._batch_tv_episode_claims)
- `MovieScanStateScanner` — Movie scanner capabilities retained by a shared ``ScanState``. (used by: plex_renamer.app.controllers._match_state_helpers)
- `ScanState` — Per-show scan state — decouples show-level data from the GUI. (used by: plex_renamer.app.controllers, plex_renamer.app.controllers._controller_event_helpers, plex_renamer.app.controllers._controller_match_helpers, plex_renamer.app.controllers._controller_movie_workflows, plex_renamer.app.controllers._controller_projection_workflow, plex_renamer.app.controllers._controller_session_models, plex_renamer.app.controllers._controller_state_helpers, plex_renamer.app.controllers._controller_tv_workflows, plex_renamer.app.controllers._job_projection_helpers, plex_renamer.app.controllers._match_state_helpers, plex_renamer.app.controllers._movie_state_helpers, plex_renamer.app.controllers._queue_submission_helpers, plex_renamer.app.controllers._single_show_scan_helpers, plex_renamer.app.controllers._tab_session_helpers, plex_renamer.app.controllers._tv_batch_helpers, plex_renamer.app.controllers._tv_state_helpers, plex_renamer.app.controllers.media_controller, plex_renamer.app.controllers.queue_controller, plex_renamer.app.services.automux_service, plex_renamer.app.services.command_gating_service, plex_renamer.app.services.episode_mapping_service, plex_renamer.app.services.episode_projection_cache, plex_renamer.engine, plex_renamer.engine._batch_orchestrators, plex_renamer.engine._batch_tv_duplicates, plex_renamer.engine._batch_tv_episode_claims, plex_renamer.engine._batch_tv_season_merge, plex_renamer.engine._queue_bridge, plex_renamer.gui_qt.widgets._episode_expansion, plex_renamer.gui_qt.widgets._episode_table_model, plex_renamer.gui_qt.widgets._media_helpers, plex_renamer.gui_qt.widgets._media_workspace_action_bar, plex_renamer.gui_qt.widgets._media_workspace_action_state, plex_renamer.gui_qt.widgets._media_workspace_actions, plex_renamer.gui_qt.widgets._media_workspace_match_actions, plex_renamer.gui_qt.widgets._media_workspace_queue_actions, plex_renamer.gui_qt.widgets._media_workspace_refresh, plex_renamer.gui_qt.widgets._media_workspace_roster, plex_renamer.gui_qt.widgets._media_workspace_state, plex_renamer.gui_qt.widgets._media_workspace_view, plex_renamer.gui_qt.widgets._roster_model, plex_renamer.gui_qt.widgets._work_panel, plex_renamer.gui_qt.widgets.media_workspace)
- `plan_has_actions(plan) -> bool` — Mirror of MuxPlan.has_actions for serialized plans (user edits can (used by: plex_renamer.app.services.automux_service)
- `file_mux_active(state, index) -> bool` — True when this preview item will actually be muxed: cached plan (used by: plex_renamer.app.services.automux_service, plex_renamer.app.services.command_gating_service, plex_renamer.engine._queue_bridge)
- `DirectEpisodeEvidence` — Direct child file evidence for TMDB TV disambiguation. (used by: plex_renamer.engine, plex_renamer.engine._batch_orchestrators, plex_renamer.engine.matching)
- `collect_direct_episode_evidence(folder) -> list[DirectEpisodeEvidence]` — Collect explicit ``S##E##`` evidence for a show folder. (used by: plex_renamer.engine, plex_renamer.engine._batch_orchestrators, plex_renamer.engine.matching)
- `infer_explicit_season_assignment(folder, evidence, show_name) -> int | None` — Infer a season assignment from folder name or consistent S##E## files. (used by: plex_renamer.engine, plex_renamer.engine._batch_orchestrators)
- Tests: tests/test_automux_service.py, tests/test_completeness_review_counts.py, tests/test_episode_metadata_ownership.py, tests/test_episode_projection.py, tests/test_episode_table_delegate.py, tests/test_episode_table_model.py, tests/test_job_execution_metadata.py, tests/test_merged_show_checked_gating.py, tests/test_mkvmerge_integration.py, tests/test_qt_media_workspace.py, tests/test_queue_bridge_mux.py, tests/test_queue_metadata_wiring.py, tests/test_queue_output_targets.py, tests/test_queue_submission_automux.py, tests/test_remux_embed_extras.py, tests/test_remux_execution.py, tests/test_roster_autoselect.py, tests/test_roster_delegate.py, tests/test_roster_model.py, tests/test_scan_improvements.py, tests/test_scanner_protocol_conformance.py, tests/test_status_chip.py, tests/test_umbrella_season_merge.py, tests/test_work_panel.py, tests/test_workspace_automux.py, tests/test_workspace_poster_warmup.py

### `plex_renamer/engine/show_details.py` — Provider-neutral show detail payload.
- `SeasonSummary` — (no docstring)
- `ShowDetails` — (no docstring) (used by: plex_renamer.engine._batch_tv_match_policy)
- `show_details_from_tmdb(raw) -> ShowDetails | None` — Normalize a raw TMDB TV-details payload. (used by: plex_renamer.engine._batch_orchestrators, plex_renamer.engine._batch_tv_match_policy)
- Tests: tests/test_show_details.py
