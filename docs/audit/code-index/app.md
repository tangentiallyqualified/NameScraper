<!-- Generated from audit input 3e52a6d46901; do not edit. regenerate: scripts\audit.cmd --fast -->


# Package detail: app


### `plex_renamer/app/__init__.py` — UI-neutral application-layer services and models for NameScraper.

### `plex_renamer/app/controllers/__init__.py` — Application controllers — UI-neutral orchestration layer.
- Tests: tests/test_queue_output_targets.py

### `plex_renamer/app/controllers/_controller_event_helpers.py` — Helpers for controller listeners, progress, and runtime settings.
- `add_controller_listener(listeners, on_library_changed, on_progress, on_scan_complete, on_mode_changed) -> int` — (no docstring) (used by: plex_renamer.app.controllers.media_controller)
- `notify_controller_listeners(listeners, event, *args) -> None` — (no docstring) (used by: plex_renamer.app.controllers.media_controller)
- `build_scan_progress(lifecycle, *, phase, done, total, current_item, message) -> ScanProgress` — (no docstring) (used by: plex_renamer.app.controllers._scan_operation_helpers)
- `apply_runtime_settings_to_states(auto_accept_threshold, episode_auto_accept_threshold, states) -> None` — (no docstring) (used by: plex_renamer.app.controllers.media_controller)

### `plex_renamer/app/controllers/_controller_lifecycle_workflow.py` — Scan lifecycle coordination for MediaController.
- `MediaControllerLifecycleWorkflow` — (no docstring) (used by: plex_renamer.app.controllers.media_controller)

### `plex_renamer/app/controllers/_controller_match_helpers.py` — Helpers for controller-owned match mutation workflows.
- `approve_controller_match(controller, state) -> None` — (no docstring) (used by: plex_renamer.app.controllers.media_controller)
- `assign_controller_season(controller, state, season_num) -> ScanState` — (no docstring) (used by: plex_renamer.app.controllers._controller_tv_workflows)
- `rematch_controller_tv_state(controller, state, new_match, *, tmdb, best_tv_match_title, extract_year, score_tv_results, score_results, pick_alternate_matches) -> ScanState` — (no docstring) (used by: plex_renamer.app.controllers._controller_tv_workflows)
- `rematch_controller_movie_state(controller, state, new_match, *, clean_folder_name, extract_year, score_results) -> None` — (no docstring) (used by: plex_renamer.app.controllers._controller_movie_workflows)
- `routed_library_states(controller) -> list[ScanState]` — (no docstring)

### `plex_renamer/app/controllers/_controller_movie_workflows.py` — Movie-specific workflow routing for MediaController.
- `MediaControllerMovieWorkflow` — (no docstring) (used by: plex_renamer.app.controllers.media_controller)

### `plex_renamer/app/controllers/_controller_projection_workflow.py` — Completed-job projection and queued-state sync for MediaController.
- `MediaControllerProjectionWorkflow` — (no docstring) (used by: plex_renamer.app.controllers.media_controller)

### `plex_renamer/app/controllers/_controller_session_models.py` — Private state containers for MediaController session ownership.
- `ControllerModeState` — (no docstring) (used by: plex_renamer.app.controllers.media_controller)
- `TVControllerSession` — (no docstring) (used by: plex_renamer.app.controllers.media_controller)
- `MovieControllerSession` — (no docstring) (used by: plex_renamer.app.controllers.media_controller)

### `plex_renamer/app/controllers/_controller_state_helpers.py` — Helpers for controller-owned session routing and selection state.
- `routed_library_states(controller) -> list[ScanState]` — (no docstring) (used by: plex_renamer.app.controllers.media_controller)
- `accept_tv_show_session(controller, folder, tmdb, show_info, *, scanner_factory) -> ScanState` — (no docstring) (used by: plex_renamer.app.controllers._controller_tv_workflows)
- `select_library_show(controller, index) -> ScanState | None` — (no docstring) (used by: plex_renamer.app.controllers.media_controller)

### `plex_renamer/app/controllers/_controller_tv_workflows.py` — TV-specific workflow routing for MediaController.
- `MediaControllerTVWorkflow` — (no docstring) (used by: plex_renamer.app.controllers.media_controller)

### `plex_renamer/app/controllers/_job_projection_helpers.py` — Helpers for completed-job projection and queued-state syncing.
- `CompletedJobProjection` — (no docstring)
- `apply_completed_job_projection(job, states, movie_preview_items) -> CompletedJobProjection` — (no docstring) (used by: plex_renamer.app.controllers._controller_projection_workflow)
- `sync_queued_state_flags(queue_jobs, tv_states, movie_states) -> None` — (no docstring) (used by: plex_renamer.app.controllers._controller_projection_workflow)

### `plex_renamer/app/controllers/_match_state_helpers.py` — Helpers for approve, season assignment, and rematch state transitions.
- `SeasonAssignmentResult` — (no docstring)
- `TVRematchResult` — (no docstring)
- `MovieRematchResult` — (no docstring)
- `approve_scan_match(state, *, resolve_movie_preview_review, set_actionable_preview_checks) -> bool` — (no docstring) (used by: plex_renamer.app.controllers._controller_match_helpers)
- `assign_state_season(state, season_num, *, batch_states, batch_orchestrator, movie_library_states, apply_movie_duplicate_labels) -> SeasonAssignmentResult` — (no docstring) (used by: plex_renamer.app.controllers._controller_match_helpers)
- `rematch_tv_scan_state(state, new_match, *, batch_states, batch_orchestrator, tmdb, best_tv_match_title, extract_year, score_tv_results, score_results, pick_alternate_matches) -> TVRematchResult` — (no docstring) (used by: plex_renamer.app.controllers._controller_match_helpers)
- `rematch_movie_scan_state(state, new_match, *, movie_preview_items, movie_scanner, clean_folder_name, extract_year, score_results) -> MovieRematchResult` — (no docstring) (used by: plex_renamer.app.controllers._controller_match_helpers)

### `plex_renamer/app/controllers/_movie_batch_helpers.py` — Helpers for movie batch scanning workflows.
- `start_movie_batch_session(controller, folder, tmdb, scanner_factory) -> None` — (no docstring) (used by: plex_renamer.app.controllers._controller_movie_workflows)
- `retarget_movie_items_to_output(items, output_root) -> None` — Retarget actionable movie preview items into the configured output root. (used by: plex_renamer.app.controllers._controller_match_helpers)
- Tests: tests/test_media_controller.py

### `plex_renamer/app/controllers/_movie_state_helpers.py` — Helpers for building and updating movie scan-state rows.
- `build_movie_library_states(items, scanner, movie_folder) -> list[ScanState]` — (no docstring) (used by: plex_renamer.app.controllers._controller_movie_workflows)
- `apply_movie_duplicate_labels(states, movie_folder) -> None` — (no docstring) (used by: plex_renamer.app.controllers._controller_match_helpers)
- `movie_state_relative_folder(state, movie_folder) -> str` — (no docstring)
- `set_actionable_preview_checks(state, checked) -> None` — (no docstring) (used by: plex_renamer.app.controllers._controller_match_helpers)
- `resolve_movie_preview_review(state, preview_items) -> None` — (no docstring) (used by: plex_renamer.app.controllers._controller_match_helpers)

### `plex_renamer/app/controllers/_queue_history_helpers.py` — Helpers for queue history, undo, and poster backfill behavior.
- `revert_queue_job(job_store, job_id, *, revert_runner) -> tuple[bool, list[str]]` — (no docstring) (used by: plex_renamer.app.controllers.queue_controller)
- `backfill_missing_queue_job_poster_paths(job_store, tmdb) -> int` — (no docstring) (used by: plex_renamer.app.controllers.queue_controller)
- `close_queue_resources(executor, job_store) -> None` — (no docstring) (used by: plex_renamer.app.controllers.queue_controller)

### `plex_renamer/app/controllers/_queue_submission_helpers.py` — Helpers for queue job creation and batch submission.
- `BatchQueueResult` — Summary of a batch queue submission. (used by: plex_renamer.app.controllers.queue_controller)
- `add_single_queue_job(job_store, *, items, checked_indices, media_type, tmdb_id, media_name, library_root, output_root, source_folder, show_folder_rename, poster_path, settings_service, tmdb_client) -> RenameJob` — (no docstring) (used by: plex_renamer.app.controllers.queue_controller)
- `add_tv_batch_jobs(job_store, *, states, library_root, output_root, command_gating, settings_service, tmdb_client) -> BatchQueueResult` — (no docstring) (used by: plex_renamer.app.controllers.queue_controller)
- `add_movie_batch_jobs(job_store, *, states, library_root, output_root, command_gating, settings_service, tmdb_client) -> BatchQueueResult` — (no docstring) (used by: plex_renamer.app.controllers.queue_controller)
- Tests: tests/test_queue_metadata_wiring.py, tests/test_queue_submission_automux.py

### `plex_renamer/app/controllers/_scan_operation_helpers.py` — Helpers for controller scan progress and cancellation state.
- `ScanOperationTracker` — Own the active scan cancellation token and its synchronization. (used by: plex_renamer.app.controllers._controller_lifecycle_workflow)
- `update_scan_progress(notify, lifecycle, *, phase, done, total, current_item, message) -> ScanProgress` — (no docstring) (used by: plex_renamer.app.controllers._controller_lifecycle_workflow)

### `plex_renamer/app/controllers/_single_show_scan_helpers.py` — Helpers for single-show TV scan workflows.
- `start_single_show_scan(controller, state, tmdb, *, scanner_factory, duplicate_checker) -> None` — (no docstring) (used by: plex_renamer.app.controllers._controller_tv_workflows)

### `plex_renamer/app/controllers/_tab_session_helpers.py` — Helpers for in-memory TV and movie tab session snapshots.
- `TVTabSnapshot` — (no docstring)
- `MovieTabSnapshot` — (no docstring)
- `snapshot_tv_session(batch_mode, batch_states, active_scan, batch_orchestrator, tv_root_folder, library_selected_index) -> TVTabSnapshot` — (no docstring) (used by: plex_renamer.app.controllers._controller_tv_workflows)
- `restore_tv_session(controller, snapshot) -> None` — (no docstring) (used by: plex_renamer.app.controllers._controller_tv_workflows)
- `snapshot_movie_session(movie_library_states, movie_preview_items, movie_scanner, movie_folder, movie_media_info, library_selected_index) -> MovieTabSnapshot` — (no docstring) (used by: plex_renamer.app.controllers._controller_movie_workflows)
- `restore_movie_session(controller, snapshot) -> None` — (no docstring) (used by: plex_renamer.app.controllers._controller_movie_workflows)

### `plex_renamer/app/controllers/_tv_batch_helpers.py` — Helpers for TV batch discovery and bulk episode scans.
- `start_tv_batch_session(controller, folder, tmdb, discovery_service) -> None` — (no docstring) (used by: plex_renamer.app.controllers._controller_tv_workflows)
- `scan_all_tv_batch_shows(controller) -> None` — (no docstring) (used by: plex_renamer.app.controllers._controller_tv_workflows)
- `retarget_tv_state_to_output(state, output_root) -> None` — Retarget actionable TV preview items into the configured output root. (used by: plex_renamer.app.controllers._controller_match_helpers, plex_renamer.app.controllers._single_show_scan_helpers)
- Tests: tests/test_media_controller.py

### `plex_renamer/app/controllers/_tv_state_helpers.py` — Helpers for TV scan-state setup and execution.
- `build_accepted_tv_state(folder, tmdb, show_info, scanner_factory) -> ScanState` — (no docstring) (used by: plex_renamer.app.controllers._controller_state_helpers)
- `ensure_tv_scanner(state, tmdb, scanner_factory)` — (no docstring) (used by: plex_renamer.app.controllers._single_show_scan_helpers)
- `run_tv_scan(state, tmdb, scanner_factory, duplicate_checker) -> None` — (no docstring) (used by: plex_renamer.app.controllers._single_show_scan_helpers)

### `plex_renamer/app/controllers/media_controller.py` — UI-neutral orchestration of TV and movie scanning sessions.
- `MediaController` — UI-neutral orchestration of TV and movie scanning sessions. (used by: plex_renamer.app, plex_renamer.app.controllers, plex_renamer.gui_qt.main_window)
- Tests: tests/test_media_controller.py

### `plex_renamer/app/controllers/queue_controller.py` — UI-neutral job queue management.
- `QueueController` — UI-neutral job queue management. (used by: plex_renamer.app, plex_renamer.app.controllers, plex_renamer.gui_qt.main_window)
- Tests: tests/test_qt_job_detail_panel.py, tests/test_qt_main_window.py, tests/test_qt_media_workspace.py, tests/test_qt_queue_history.py, tests/test_queue_controller.py, tests/test_queue_executor_progress.py

### `plex_renamer/app/models/__init__.py` — Typed application-layer models shared across controllers and services.
- Tests: tests/test_cache_service.py, tests/test_command_gating_service.py, tests/test_conflict_queue_protection.py, tests/test_manual_assign_queueable.py, tests/test_media_controller.py, tests/test_movie_discovery.py, tests/test_qt_main_window.py, tests/test_qt_workspace_widgets.py, tests/test_refresh_policy_service.py, tests/test_scan_improvements.py

### `plex_renamer/app/models/state_models.py` — Structured application-layer state models used by Phase 1 services.
- `utc_now_iso() -> str` — Return the current UTC time as an ISO-8601 string.
- `ScanLifecycle` — Normalized scan lifecycle states for UI-neutral progress reporting. (used by: plex_renamer.app, plex_renamer.app.controllers, plex_renamer.app.controllers._controller_event_helpers, plex_renamer.app.controllers._controller_lifecycle_workflow, plex_renamer.app.controllers._controller_state_helpers, plex_renamer.app.controllers._movie_batch_helpers, plex_renamer.app.controllers._scan_operation_helpers, plex_renamer.app.controllers._single_show_scan_helpers, plex_renamer.app.controllers._tv_batch_helpers, plex_renamer.app.controllers.media_controller, plex_renamer.app.models, plex_renamer.gui_qt._main_window_scan, plex_renamer.gui_qt.widgets.scan_progress)
- `RefreshState` — Freshness state for cached metadata and scan snapshots. (used by: plex_renamer.app, plex_renamer.app.models, plex_renamer.app.services.cache_service, plex_renamer.app.services.refresh_policy_service)
- `QueueCommandState` — State model for queue command gating. (used by: plex_renamer.app, plex_renamer.app.models, plex_renamer.app.services.command_gating_service)
- `TVDirectoryRole` — Directory classification used during nested batch-TV discovery. (used by: plex_renamer.app.models, plex_renamer.app.services._tv_library_classification, plex_renamer.app.services.tv_library_discovery_service)
- `ScanProgress` — Structured progress payload replacing free-form status strings. (used by: plex_renamer.app, plex_renamer.app.controllers, plex_renamer.app.controllers._controller_event_helpers, plex_renamer.app.controllers._controller_lifecycle_workflow, plex_renamer.app.controllers._scan_operation_helpers, plex_renamer.app.controllers.media_controller, plex_renamer.app.models, plex_renamer.gui_qt._main_window_bridges, plex_renamer.gui_qt._main_window_scan, plex_renamer.gui_qt.main_window)
- `CacheEntry` — A persisted cache entry with freshness and eviction metadata. (used by: plex_renamer.app, plex_renamer.app.models, plex_renamer.app.services.cache_service)
- `CacheLookup` — Result of a cache lookup with the resolved freshness state. (used by: plex_renamer.app, plex_renamer.app.models, plex_renamer.app.services.cache_service)
- `QueueEligibility` — Queue gating result for a single item set or scan state. (used by: plex_renamer.app, plex_renamer.app.controllers, plex_renamer.app.models, plex_renamer.app.services.command_gating_service)
- `EpisodeGuideSummary` — (no docstring) (used by: plex_renamer.app.models, plex_renamer.app.services.episode_mapping_service)
- `EpisodeGuideRow` — (no docstring) (used by: plex_renamer.app.models, plex_renamer.app.services.episode_mapping_service, plex_renamer.gui_qt.widgets._episode_expansion, plex_renamer.gui_qt.widgets._episode_table_model)
- `UnmappedFileRow` — (no docstring) (used by: plex_renamer.app.models, plex_renamer.app.services.episode_mapping_service)
- `EpisodeSlotChoice` — One pickable episode slot for the assignment dialog. (used by: plex_renamer.app.models, plex_renamer.app.services.episode_mapping_service, plex_renamer.gui_qt.widgets.episode_assign_dialog)
- `EpisodeGuide` — (no docstring) (used by: plex_renamer.app.controllers.media_controller, plex_renamer.app.models, plex_renamer.app.services.episode_mapping_service, plex_renamer.app.services.episode_projection_cache, plex_renamer.gui_qt.widgets._episode_table_model)
- `TVDiscoveryCandidate` — A discovered TV show root found during recursive library traversal. (used by: plex_renamer.app.models, plex_renamer.app.services.tv_library_discovery_service)
- `MovieDirectoryRole` — Directory classification used during nested batch-movie discovery. (used by: plex_renamer.app.models, plex_renamer.app.services._movie_library_classification, plex_renamer.app.services.movie_library_discovery_service)
- `MovieDiscoveryCandidate` — A discovered movie root or multi-movie folder found during recursive library traversal. (used by: plex_renamer.app.models, plex_renamer.app.services.movie_library_discovery_service)
- Tests: tests/test_episode_expansion.py, tests/test_episode_table_delegate.py, tests/test_episode_table_model.py, tests/test_qt_media_workspace.py, tests/test_work_panel.py

### `plex_renamer/app/services/__init__.py` — Phase 1 application-layer services.
- Tests: tests/test_alt_title_matching.py, tests/test_automux_service.py, tests/test_batch_autoaccept_guards.py, tests/test_jojo_matching.py, tests/test_movie_confidence_adjustments.py, tests/test_movie_discovery.py, tests/test_queue_submission_automux.py, tests/test_scan_improvements.py, tests/test_workspace_automux.py, tests/test_workspace_expansion.py

### `plex_renamer/app/services/_movie_library_classification.py` — Folder-classification helpers for recursive movie library discovery.
- `DirChild` — (no docstring)
- `ClassifiedDirectory` — (no docstring) (used by: plex_renamer.app.services.movie_library_discovery_service)
- `MovieDirectoryClassifier` — Encapsulate movie folder classification heuristics. (used by: plex_renamer.app.services.movie_library_discovery_service)

### `plex_renamer/app/services/_settings_schema.py` — Schema, defaults, and validation helpers for SettingsService.
- `build_valid_settings_data(stored, *, logger) -> dict[str, object]` — (no docstring) (used by: plex_renamer.app.services.settings_service)
- Tests: tests/test_settings_metadata_keys.py

### `plex_renamer/app/services/_tv_library_classification.py` — Folder-classification helpers for recursive TV library discovery.
- `DirChild` — (no docstring)
- `ClassifiedDirectory` — (no docstring) (used by: plex_renamer.app.services.tv_library_discovery_service)
- `TVDirectoryClassifier` — Encapsulate TV folder classification heuristics. (used by: plex_renamer.app.services.tv_library_discovery_service)

### `plex_renamer/app/services/automux_service.py` — Session-scoped AutoMux planning: probe files and attach mux plans.
- `mux_settings_from_service(svc) -> MuxSettings` — (no docstring)
- `resolve_mkvmerge(svc) -> Path | None` — (no docstring)
- `automux_active(svc) -> bool` — AutoMux UI exists only when a toggle is on AND mkvmerge resolves (used by: plex_renamer.app.controllers._queue_submission_helpers)
- `companion_subs_for_item(item, source_root) -> list[tuple[str, str]]` — (source_relative, raw_lang_tag) pairs for the item's subtitle
- `plan_for_item(state, index, *, probe, settings, mkvmerge_path, source_root) -> dict | None` — Serialized MuxPlan for one preview item, or None when no remux.
- `ensure_state_plans(state, svc, source_root, *, prober, only_index) -> None` — Probe + plan actionable preview items, storing results on *state*. (used by: plex_renamer.app.controllers._queue_submission_helpers)
- `item_mux_probe_eligible(item) -> bool` — Probe-eligible even when the name is already correct (round6 §1):
- `state_has_mux_actions(state) -> bool` — (no docstring) (used by: plex_renamer.gui_qt.widgets._roster_model)
- `state_mux_eligible(state) -> bool` — True when any cached plan carries actions, regardless of the
- `effective_mux_plans(state) -> dict[int, dict] | None` — Plans to bake into a queue job — None when AutoMux contributes (used by: plex_renamer.app.controllers._queue_submission_helpers)
- Tests: tests/test_automux_service.py

### `plex_renamer/app/services/cache_service.py` — Persistent metadata cache with freshness tracking and bounded eviction.
- `PersistentCacheService` — SQLite-backed cache for persisted metadata and scan-related state. (used by: plex_renamer.app, plex_renamer.app.controllers.media_controller, plex_renamer.app.services, plex_renamer.gui_qt.main_window)
- Tests: tests/conftest_qt.py, tests/test_cache_service.py, tests/test_media_controller.py, tests/test_qt_job_detail_panel.py, tests/test_qt_main_window.py, tests/test_qt_media_workspace.py, tests/test_qt_queue_history.py, tests/test_settings_longpath.py, tests/test_settings_tab_cache.py, tests/test_tmdb.py

### `plex_renamer/app/services/command_gating_service.py` — Queue command gating extracted from widget click handlers.
- `CommandGatingService` — Compute queue eligibility independently of any GUI toolkit. (used by: plex_renamer.app, plex_renamer.app.controllers._movie_state_helpers, plex_renamer.app.controllers._queue_submission_helpers, plex_renamer.app.controllers.media_controller, plex_renamer.app.controllers.queue_controller, plex_renamer.app.services, plex_renamer.gui_qt.main_window, plex_renamer.gui_qt.widgets._media_helpers, plex_renamer.gui_qt.widgets._media_workspace_actions, plex_renamer.gui_qt.widgets._media_workspace_refresh, plex_renamer.gui_qt.widgets._media_workspace_sync)
- Tests: tests/test_command_gating_service.py, tests/test_conflict_queue_protection.py, tests/test_manual_assign_queueable.py, tests/test_media_controller.py, tests/test_qt_job_detail_panel.py, tests/test_qt_main_window.py, tests/test_qt_media_workspace.py, tests/test_qt_queue_history.py, tests/test_queue_controller.py, tests/test_queue_submission_automux.py, tests/test_workspace_expansion.py

### `plex_renamer/app/services/episode_mapping_service.py` — Build TV episode-guide projections.
- `EpisodeMappingService` — Project raw scan preview state into episode-guide workflow state. (used by: plex_renamer.app.controllers._controller_event_helpers, plex_renamer.app.services, plex_renamer.app.services.episode_projection_cache, plex_renamer.gui_qt.widgets._episode_table_model, plex_renamer.gui_qt.widgets._media_workspace_actions)
- Tests: tests/test_bulk_assign_panel.py, tests/test_conflict_queue_protection.py, tests/test_episode_mapping_projection.py, tests/test_episode_projection_cache.py, tests/test_manual_assign_queueable.py, tests/test_qt_async_guide.py, tests/test_qt_media_workspace.py, tests/test_qt_perf_guards.py

### `plex_renamer/app/services/episode_projection_cache.py` — Cache scan-time TV episode-guide projections for batch UI rendering.
- `EpisodeProjectionCacheService` — (no docstring) (used by: plex_renamer.app.controllers.media_controller)
- Tests: tests/test_episode_projection_cache.py, tests/test_qt_async_guide.py, tests/test_qt_perf_guards.py

### `plex_renamer/app/services/metadata_service.py` — Metadata/artwork export planning (spec: local-metadata-artwork).
- `metadata_active(svc) -> bool` — Metadata export runs only when the master switch is on. (used by: plex_renamer.app.controllers._queue_submission_helpers)
- `build_metadata_plan(job, tmdb_client, svc) -> dict | None` — Serializable MetadataPlan for one job, or None when inapplicable.
- `finalize_plan(plan) -> dict | None` — Drop unfulfilled artwork placeholders; None when nothing remains.
- `inventory_local_metadata(source_dir, video_ops, media_type, library_root) -> dict[str, Path]` — Map artifact slot keys to pre-existing companion files.
- `apply_prefer_local(job, plan, library_root) -> None` — Fulfill plan slots from existing local files (spec: sourcing policy).
- `attach_metadata_plan(job, *, tmdb_client, settings_service, library_root) -> None` — Bake the metadata plan onto *job* at queue-submission time. (used by: plex_renamer.app.controllers._queue_submission_helpers)
- `make_image_fetcher(*, get_client, api_key_lookup, cache_service, language)` — Artwork downloader for the executor's decorate phase. (used by: plex_renamer.gui_qt._main_window_bootstrap)
- Tests: tests/test_metadata_embed_extras.py, tests/test_metadata_local_inventory.py, tests/test_metadata_service.py, tests/test_queue_metadata_wiring.py

### `plex_renamer/app/services/movie_library_discovery_service.py` — Recursive movie-library discovery for nested batch scan workflows.
- `MovieLibraryDiscoveryService` — Discover nested movie roots without misclassifying container or TV folders. (used by: plex_renamer.app.services)

### `plex_renamer/app/services/output_destination_service.py` — Validation helpers for user-configured output destinations.
- `output_path_risks_long_paths(root, *, reserve) -> bool` — True when *root* is long enough that a generated rename path could
- `long_path_warning_text(root) -> str` — User-facing, non-blocking warning for *root*, or "" if not at risk. (used by: plex_renamer.gui_qt.widgets._settings_tab_state)
- `OutputDestinationStatus` — (no docstring) (used by: plex_renamer.app.services.settings_service)
- `validate_output_folder(path_value) -> OutputDestinationStatus` — Validate that *path_value* names an existing directory. (used by: plex_renamer.app.services.settings_service)
- `validate_scan_output_relationship(source_folder, output_folder) -> OutputDestinationStatus` — Validate that output is not the selected scan source or nested under it. (used by: plex_renamer.app.services.settings_service)
- Tests: tests/test_output_destination_service.py

### `plex_renamer/app/services/refresh_policy_service.py` — Refresh policy rules for metadata TTLs, cooldowns, and rescan scope.
- `ManualRefreshDecision` — (no docstring)
- `RefreshPolicyService` — Central refresh policy rules, independent of any GUI toolkit. (used by: plex_renamer.app, plex_renamer.app.controllers.media_controller, plex_renamer.app.services, plex_renamer.app.services.cache_service, plex_renamer.gui_qt.main_window)
- Tests: tests/test_cache_service.py, tests/test_media_controller.py, tests/test_refresh_policy_service.py, tests/test_tmdb.py

### `plex_renamer/app/services/settings_service.py` — Lightweight JSON-backed user preferences.
- `SettingsService` — Read/write user preferences backed by a JSON file. (used by: plex_renamer.app.controllers.media_controller, plex_renamer.app.services, plex_renamer.app.services.automux_service, plex_renamer.gui_qt.main_window, plex_renamer.gui_qt.widgets._media_workspace_roster, plex_renamer.gui_qt.widgets.empty_state, plex_renamer.gui_qt.widgets.media_workspace, plex_renamer.gui_qt.widgets.settings_tab)
- Tests: tests/conftest_qt.py, tests/test_alt_title_matching.py, tests/test_automux_service.py, tests/test_automux_settings.py, tests/test_media_controller.py, tests/test_qt_job_detail_panel.py, tests/test_qt_main_window.py, tests/test_qt_media_workspace.py, tests/test_qt_queue_history.py, tests/test_queue_submission_automux.py, tests/test_recent_menus.py, tests/test_settings_longpath.py, tests/test_settings_service.py, tests/test_settings_tab_automux.py, tests/test_settings_tab_cache.py, tests/test_workspace_automux.py, tests/test_workspace_expansion.py

### `plex_renamer/app/services/tv_library_discovery_service.py` — Recursive TV-library discovery for nested batch scan workflows.
- `TVLibraryDiscoveryService` — Discover nested TV show roots without misclassifying container folders. (used by: plex_renamer.app.controllers._tv_batch_helpers, plex_renamer.app.controllers.media_controller, plex_renamer.app.services)
- Tests: tests/test_haikyuu_matching.py
