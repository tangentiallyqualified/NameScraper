<!-- Generated from audit input 6d57e67cd7d3; do not edit. regenerate: scripts\audit.cmd --fast -->


# Package detail: root


### `plex_renamer/__init__.py` — NameScraper — rename media files into a library-standard (Plex/Jellyfin) naming format.
- Tests: tests/conftest_qt.py, tests/test_mkv_locate.py, tests/test_mkv_probe.py, tests/test_mkvmerge_integration.py, tests/test_queue_executor_progress.py, tests/test_remux_execution.py, tests/test_thread_pool.py

### `plex_renamer/__main__.py` — Entry point for NameScraper.
- `main()` — (no docstring)

### `plex_renamer/_job_execution_filesystem.py` — Filesystem helpers for queued rename execution.
- `remap_target_into_final_root(target_dir, root_folder, final_root) -> Path` — Route root-relative targets into the final renamed show folder. (used by: plex_renamer.job_executor)
- `apply_top_dir_remap(path, remap) -> Path` — Move a path under a remapped top-level output directory. (used by: plex_renamer._job_execution_metadata, plex_renamer.job_executor)
- `output_target_collision_remap(*, output_root, renames) -> dict[Path, Path]` — Choose numbered top-level output siblings for collided targets. (used by: plex_renamer.job_executor)
- `apply_rename_plan(renames, result) -> set[str]` — Execute the planned file moves and record undo metadata. (used by: plex_renamer.job_executor)
- `normalize_season_directories(*, root_folder, source_dirs, renames, result) -> None` — Normalize season directory names after a successful rename pass. (used by: plex_renamer.job_executor)
- `cleanup_source_directories(*, media_type, library_root, root_folder, source_dirs, source_to_target, successful_destinations, result) -> None` — Move leftover files and remove emptied source directories. (used by: plex_renamer.job_executor)

### `plex_renamer/_job_execution_metadata.py` — Decorate phase: write metadata sidecars and embed titles after a
- `run_mkvpropedit(args) -> tuple[int, str]` — Run mkvpropedit. Returns (returncode, output tail).
- `materialized_extras(entry, fetch_image_bytes, result, display_name)` — Yield (tags_path, cover_path) temp files for one embed_extras (used by: plex_renamer.job_executor)
- `execute_metadata_plan(job, *, result, fetch_image_bytes, propedit_runner) -> None` — Apply job.metadata_plan to the output folder. (used by: plex_renamer.job_executor)
- Tests: tests/test_job_execution_metadata.py

### `plex_renamer/_job_execution_remux.py` — mkvmerge execution for REMUX job ops (spec §7).
- `run_mkvmerge(args, on_percent) -> tuple[int, str]` — Run mkvmerge, streaming progress.  Returns (returncode, output tail).
- `execute_remux_op(op, *, source_root, output_root, result, on_percent, set_active_temp, runner, title, tags_path, cover_path) -> bool` — Execute one mux op.  Returns True on success; errors go to *result*. (used by: plex_renamer.job_executor)
- Tests: tests/test_executor_metadata_integration.py, tests/test_remux_embed_extras.py

### `plex_renamer/_job_path_propagation.py` — Helpers for rewriting queued job paths after directory renames.
- `rewrite_job_paths(*, library_root, source_folder, rename_ops, renamed_dirs) -> tuple[str, list[dict[str, Any]], bool]` — Apply renamed directory prefixes to one queued job payload. (used by: plex_renamer.job_store)
- `rebase_path(path_str, old_prefix, new_prefix) -> str` — If *path_str* starts with *old_prefix*, replace that prefix.

### `plex_renamer/_job_store_codec.py` — Row-mapping and JSON serialization helpers for the job store.
- `serialize_rename_ops(rename_ops) -> str` — Serialize rename ops using their existing to_dict contract. (used by: plex_renamer.job_store)
- `serialize_rename_op_dicts(rename_ops) -> str` — Serialize already-expanded rename-op payloads. (used by: plex_renamer.job_store)
- `deserialize_rename_op_dicts(raw_rename_ops) -> list[dict[str, Any]]` — Parse the stored rename-op JSON payload. (used by: plex_renamer.job_store)
- `serialize_undo_data(undo_data) -> str | None` — Serialize undo data when present. (used by: plex_renamer.job_store)
- `deserialize_undo_data(raw_undo_data) -> dict | None` — Parse the stored undo-data JSON payload.
- `row_to_job(row, *, rename_op_from_dict, job_factory) -> Any` — Build one job object from a SQLite row. (used by: plex_renamer.job_store)

### `plex_renamer/_job_store_db.py` — SQLite connection and schema helpers for the persistent job queue.
- `connect_job_store(db_path) -> sqlite3.Connection` — Create one SQLite connection configured for the job queue. (used by: plex_renamer.job_store)
- `initialize_job_store(conn) -> None` — Create the schema and run any needed migrations. (used by: plex_renamer.job_store)
- `migrate_job_store(conn, current_version) -> None` — Upgrade an existing job-store schema in place.

### `plex_renamer/_job_store_ordering.py` — Queue ordering helpers for the persistent job store.
- `compact_positions(conn) -> None` — Reassign positions 1..N for pending/running jobs.
- `reorder_pending_job(conn, *, job_id, new_position, now) -> None` — Move one pending job to a new queue position. (used by: plex_renamer.job_store)
- `move_pending_jobs(conn, *, job_ids, direction, now) -> bool` — Move a block of pending jobs up or down while preserving order. (used by: plex_renamer.job_store)
- `move_pending_jobs_to_top(conn, *, job_ids, now) -> bool` — Move the given pending jobs to the top while preserving order. (used by: plex_renamer.job_store)

### `plex_renamer/_lang_normalize.py` — Language-tag normalization for AutoMux.
- `normalize_lang(tag) -> str | None` — Return the canonical ISO 639-2/B code for *tag*, or None. (used by: plex_renamer._mkv_probe, plex_renamer.engine._mux_planner, plex_renamer.gui_qt.widgets._settings_automux_page)
- `normalize_lang_list(values) -> list[str]` — Normalize a list of tags: order-preserving, deduped, invalid dropped. (used by: plex_renamer.engine._mux_planner, plex_renamer.gui_qt.widgets._settings_automux_page)
- Tests: tests/test_lang_normalize.py

### `plex_renamer/_mkv_command.py` — Build the mkvmerge argv for one remux op from its MuxPlan.
- `build_mkvmerge_args(*, mkvmerge_path, source, output, plan, resolve_sub, title, global_tags_path, cover_path) -> list[str]` — (no docstring) (used by: plex_renamer._job_execution_remux)
- `build_mkvpropedit_args(propedit_path, target, *, title, tags_path, cover_path) -> list[str]` — argv for in-place container edits (title/tags/cover, no remux). (used by: plex_renamer._job_execution_metadata)
- Tests: tests/test_mkv_command.py, tests/test_mkv_metadata_helpers.py

### `plex_renamer/_mkv_locate.py` — Locate the mkvmerge executable (spec §3.1).
- `find_mkvmerge(explicit_path) -> Path | None` — Resolve the mkvmerge binary. (used by: plex_renamer._job_execution_remux, plex_renamer.app.services.automux_service, plex_renamer.gui_qt.widgets._settings_automux_page)
- `find_mkvpropedit(mkvmerge_setting) -> Path | None` — Resolve mkvpropedit — it ships beside mkvmerge in MKVToolNix. (used by: plex_renamer._job_execution_metadata, plex_renamer.app.services.metadata_service, plex_renamer.gui_qt.widgets._settings_metadata_page)
- Tests: tests/test_mkv_locate.py, tests/test_mkv_metadata_helpers.py, tests/test_mkvmerge_integration.py

### `plex_renamer/_mkv_probe.py` — Track inspection via ``mkvmerge -J`` with a stat-keyed result cache.
- `MediaTrack` — (no docstring) (used by: plex_renamer.engine._mux_planner)
- `ProbeResult` — (no docstring) (used by: plex_renamer.app.services.automux_service, plex_renamer.engine._mux_planner)
- `parse_identify_json(path, payload) -> ProbeResult` — Pure parse of a ``mkvmerge -J`` JSON document.
- `clear_probe_cache() -> None` — (no docstring)
- `probe_file(mkvmerge_path, video_path) -> ProbeResult` — Run ``mkvmerge -J`` on *video_path*; cached on (path, size, mtime). (used by: plex_renamer.app.services.automux_service)
- Tests: tests/test_automux_service.py, tests/test_mkv_probe.py, tests/test_mkvmerge_integration.py, tests/test_mux_planner.py, tests/test_queue_submission_automux.py, tests/test_workspace_automux.py

### `plex_renamer/_mkv_tags_render.py` — Render Matroska global-tags XML from cached TMDB payloads.
- `render_movie_tags(details) -> str` — (no docstring) (used by: plex_renamer.app.services.metadata_service)
- `render_episode_tags(show_details, blocks) -> str` — Layered 70 (show) / 60 (season) / 50 (per-episode) tags. (used by: plex_renamer.app.services.metadata_service)
- Tests: tests/test_mkv_tags_render.py

### `plex_renamer/_nfo_render.py` — Render Kodi-convention NFO XML from cached TMDB payloads.
- `render_tvshow_nfo(details) -> str` — (no docstring) (used by: plex_renamer.app.services.metadata_service)
- `render_movie_nfo(details) -> str` — (no docstring) (used by: plex_renamer.app.services.metadata_service)
- `render_episode_nfo(blocks) -> str` — One <episodedetails> root per block, concatenated after a single (used by: plex_renamer.app.services.metadata_service)
- Tests: tests/test_nfo_render.py

### `plex_renamer/_parsing_episodes.py` — Episode-number extraction helpers.
- `extract_episode(filename) -> tuple[list[int], str | None, bool]` — Extract episode number(s) and title text from a filename. (used by: plex_renamer.parsing)
- `extract_season_number(filename) -> int | None` — Extract the explicit season number from a season/episode filename pattern. (used by: plex_renamer.parsing)

### `plex_renamer/_parsing_names.py` — Name-building and fuzzy-normalization helpers.
- `build_tv_name(show, year, season, episodes, titles, ext) -> str` — Build a library-standard (Plex/Jellyfin) TV episode filename. (used by: plex_renamer.parsing)
- `build_movie_name(title, year, ext) -> str` — Build a library-standard (Plex/Jellyfin) movie filename. (used by: plex_renamer.parsing)
- `build_show_folder_name(show, year) -> str` — Build a library-standard (Plex/Jellyfin) TV show root folder name. (used by: plex_renamer.parsing)
- `normalize_for_match(text) -> str` — Normalize a title for fuzzy comparison. (used by: plex_renamer.parsing)
- `normalize_for_specials_spaced(text) -> str` — Symbol-folded, space-tokenized normal form (for token-level fuzzy). (used by: plex_renamer.parsing)
- `normalize_for_specials(text) -> str` — Normalize text for specials/extras fuzzy matching. (used by: plex_renamer.parsing)
- `is_already_complete(items) -> bool` — Check if all OK items are already properly named (no rename needed). (used by: plex_renamer.parsing)
- Tests: tests/test_run_extension_guards.py, tests/test_symbol_folding.py

### `plex_renamer/_parsing_seasons.py` — Season-folder parsing helpers.
- `get_season(folder) -> int | None` — Extract the season number from a folder name. (used by: plex_renamer.parsing)
- `is_season_only_name(folder_name) -> bool` — Return True if *folder_name* is primarily a season label. (used by: plex_renamer._parsing_tv, plex_renamer.parsing)
- `get_year_season(folder_name) -> int | None` — Return the 4-digit release year of a bare ``S<YYYY>`` season folder. (used by: plex_renamer.parsing)

### `plex_renamer/_parsing_subtitles.py` — Companion subtitle pairing helpers.
- `find_companion_subtitles(video_path) -> list[tuple[Path, str]]` — Find subtitle files in the same directory that pair with a video file. (used by: plex_renamer.parsing)

### `plex_renamer/_parsing_titles.py` — Title cleaning and year-extraction helpers.
- `clean_folder_name(name, *, include_year) -> str` — Extract a human-readable title from a release-group style folder name. (used by: plex_renamer._parsing_tv, plex_renamer.parsing)
- `clean_name(name) -> str` — Normalize a filename for pattern matching. (used by: plex_renamer._parsing_episodes, plex_renamer.parsing)
- `clean_title_evidence(name) -> str` — Normalize a filename for episode-TITLE extraction. (used by: plex_renamer._parsing_episodes, plex_renamer.engine._tv_scanner_consolidated, plex_renamer.engine._tv_scanner_normal)
- `strip_release_junk_title(title) -> str | None` — Truncate an extracted episode title at the first release-noise token. (used by: plex_renamer._parsing_episodes)
- `sanitize_filename(name) -> str` — Remove or replace characters that are illegal in filenames on (used by: plex_renamer._parsing_names, plex_renamer.parsing)
- `extract_year(text) -> str | None` — Extract a plausible release year (1920-2099) from a string. (used by: plex_renamer._parsing_tv, plex_renamer.parsing)
- Tests: tests/test_episode_resolution.py, tests/test_release_junk_titles.py

### `plex_renamer/_parsing_tv.py` — TV/movie classification and title inference helpers.
- `is_extras_folder(name) -> bool` — Check if a folder name indicates supplemental/extras content. (used by: plex_renamer.parsing)
- `has_explicit_special_episode(filename) -> bool` — Return True when a file name carries an explicit S00E## marker. (used by: plex_renamer.parsing)
- `is_sample_file(filepath) -> bool` — Return True if a file is a release sample clip, not the main film. (used by: plex_renamer.parsing)
- `is_companion_video_file(filepath) -> bool` — Return True when a video file is a TV companion extra, not an episode. (used by: plex_renamer.parsing)
- `looks_like_tv_episode(filepath) -> bool` — Quick heuristic check for whether a file is likely a TV episode. (used by: plex_renamer.parsing)
- `extract_source_title_prefix(filename) -> str | None` — Extract a conservative show-title prefix from an episodic filename. (used by: plex_renamer.parsing)
- `best_tv_match_title(folder, *, include_year, name_fallback_folder) -> str` — Return the best available TV title for matching/search. (used by: plex_renamer.parsing)
- `is_generic_show_folder_name(name) -> bool` — True when *name* is only a season/collection label, not a show title. (used by: plex_renamer.parsing)

### `plex_renamer/_tmdb_batch_search.py` — Batch search orchestration helpers for the TMDB client.
- `resolve_movie_batch_query(query, year, *, search_with_fallback, search_fn) -> list[dict]` — (no docstring) (used by: plex_renamer.tmdb)
- `resolve_tv_batch_query(query, year, *, search_with_fallback, search_fn) -> list[dict]` — (no docstring) (used by: plex_renamer.tmdb)
- `run_batch_search(queries, *, search_query, max_workers, progress_callback) -> list[list[dict]]` — (no docstring) (used by: plex_renamer.tmdb)

### `plex_renamer/_tmdb_image_cache.py` — Image and poster cache helpers for the TMDB client.

### `plex_renamer/_tmdb_metadata_builder.py` — Pure metadata shaping helpers for TMDB client responses.
- `build_tv_search_results(data) -> list[dict]` — (no docstring) (used by: plex_renamer.tmdb)
- `build_movie_search_results(data) -> list[dict]` — (no docstring) (used by: plex_renamer.tmdb)
- `build_empty_season_payload() -> dict[str, Any]` — (no docstring) (used by: plex_renamer.tmdb)
- `build_season_payload(data) -> dict[str, Any]` — (no docstring) (used by: plex_renamer.tmdb)
- `select_logo_path(details, language) -> str | None` — Best clearlogo path from a widened details payload. (used by: plex_renamer.app.services.metadata_service)
- Tests: tests/test_tmdb_export_assets.py

### `plex_renamer/_tmdb_metadata_cache.py` — Persistent metadata cache helpers for the TMDB client.

### `plex_renamer/_tmdb_search_helpers.py` — Search and alternate-title helpers for the TMDB client.
- `extract_alternative_titles(data) -> list[tuple[str, str]]` — (no docstring) (used by: plex_renamer.tmdb)
- `search_with_fallback(query, search_fn, min_words, **kwargs) -> list[dict]` — (no docstring) (used by: plex_renamer.tmdb)

### `plex_renamer/_tmdb_transport.py` — Transport helpers for TMDB client networking and retry behavior.
- `TMDBError` — Base class for TMDB client errors. (used by: plex_renamer.tmdb)
- `TMDBNetworkError` — Network or connection failure — transient, may be retried. (used by: plex_renamer.tmdb)
- `TMDBRateLimitError` — API rate limit hit (HTTP 429). (used by: plex_renamer.tmdb)
- `TMDBAPIError` — Non-retryable API error (4xx other than 429). (used by: plex_renamer.tmdb)
- `TMDBTransport` — Own the HTTP session, token bucket, and retry policy for TMDB requests. (used by: plex_renamer.tmdb)
- Tests: tests/test_tmdb_transport.py

### `plex_renamer/constants.py` — Shared constants and configuration for NameScraper.
- `ensure_log_dir() -> None` — Create the log directory if it doesn't exist. Called lazily on first use. (used by: plex_renamer._job_store_db, plex_renamer.app.services.cache_service, plex_renamer.app.services.settings_service, plex_renamer.keys)
- `JobStatus` — Status values for job queue entries. (used by: plex_renamer.app.controllers._queue_history_helpers, plex_renamer.app.controllers.queue_controller, plex_renamer.gui_qt.models.job_table_model, plex_renamer.gui_qt.widgets._history_tab_state, plex_renamer.gui_qt.widgets._job_detail_data, plex_renamer.gui_qt.widgets._job_list_tab, plex_renamer.gui_qt.widgets._queue_tab_actions, plex_renamer.gui_qt.widgets._queue_tab_state, plex_renamer.gui_qt.widgets.history_tab, plex_renamer.gui_qt.widgets.queue_tab, plex_renamer.job_executor, plex_renamer.job_store)
- `JobKind` — Job type discriminator — extensible for future task types. (used by: plex_renamer.engine._queue_bridge, plex_renamer.gui_qt.widgets._queue_tab_actions, plex_renamer.job_executor, plex_renamer.job_store)
- `MediaType` — Media type constants — StrEnum for type safety and string compatibility. (used by: plex_renamer._job_execution_filesystem, plex_renamer.app.controllers._controller_event_helpers, plex_renamer.app.controllers._controller_match_helpers, plex_renamer.app.controllers._controller_projection_workflow, plex_renamer.app.controllers._controller_session_models, plex_renamer.app.controllers._controller_state_helpers, plex_renamer.app.controllers._job_projection_helpers, plex_renamer.app.controllers._match_state_helpers, plex_renamer.app.controllers._movie_batch_helpers, plex_renamer.app.controllers._movie_state_helpers, plex_renamer.app.controllers._queue_submission_helpers, plex_renamer.app.controllers._tab_session_helpers, plex_renamer.app.controllers._tv_batch_helpers, plex_renamer.app.controllers.media_controller, plex_renamer.app.services.metadata_service, plex_renamer.app.services.refresh_policy_service, plex_renamer.engine._movie_scanner, plex_renamer.engine._queue_bridge, plex_renamer.engine.models, plex_renamer.gui_qt.widgets._media_helpers, plex_renamer.job_executor, plex_renamer.job_store)
- Tests: tests/test_executor_metadata_integration.py, tests/test_job_execution_metadata.py, tests/test_media_controller.py, tests/test_metadata_embed_extras.py, tests/test_metadata_local_inventory.py, tests/test_metadata_service.py, tests/test_qt_job_detail_panel.py, tests/test_qt_main_window.py, tests/test_qt_media_workspace.py, tests/test_qt_queue_history.py, tests/test_queue_bridge_mux.py, tests/test_queue_controller.py, tests/test_queue_executor_progress.py, tests/test_queue_metadata_wiring.py, tests/test_queue_submission_automux.py, tests/test_queue_tab_remux.py, tests/test_refresh_policy_service.py, tests/test_remux_confirmation.py, tests/test_remux_embed_extras.py, tests/test_remux_job_model.py, tests/test_remux_revert.py, tests/test_scan_improvements.py

### `plex_renamer/job_executor.py` — Job queue executor — processes jobs from the queue.
- `revert_job(job) -> tuple[bool, list[str]]` — Revert a single completed job using its stored undo data. (used by: plex_renamer.app.controllers.queue_controller)
- `QueueExecutor` — Background worker that processes pending jobs from the queue. (used by: plex_renamer.app.controllers._queue_history_helpers, plex_renamer.app.controllers.queue_controller)
- Tests: tests/test_executor_metadata_integration.py, tests/test_queue_executor_progress.py, tests/test_remux_embed_extras.py, tests/test_remux_revert.py, tests/test_scan_improvements.py

### `plex_renamer/job_store.py` — Persistent job queue backed by SQLite.
- `RenameOp` — One file's rename plan — fully serializable, no Path objects. (used by: plex_renamer.app.services.metadata_service, plex_renamer.engine._queue_bridge, plex_renamer.gui_qt.widgets._job_detail_preview)
- `RenameJob` — A single unit of work in the job queue. (used by: plex_renamer.app.controllers, plex_renamer.app.controllers._queue_history_helpers, plex_renamer.app.controllers._queue_submission_helpers, plex_renamer.app.controllers.queue_controller, plex_renamer.engine._queue_bridge, plex_renamer.gui_qt._main_window_feedback, plex_renamer.gui_qt.main_window, plex_renamer.gui_qt.models.job_table_model, plex_renamer.gui_qt.widgets._job_detail_data, plex_renamer.gui_qt.widgets._job_detail_poster, plex_renamer.gui_qt.widgets._job_detail_preview, plex_renamer.gui_qt.widgets._job_list_tab, plex_renamer.gui_qt.widgets.job_detail_panel, plex_renamer.job_executor)
- `DuplicateJobError` — Raised when adding a job that duplicates a pending/running job. (used by: plex_renamer.app.controllers._queue_submission_helpers)
- `JobStore` — SQLite-backed persistent job queue with path propagation. (used by: plex_renamer.app.controllers._queue_history_helpers, plex_renamer.app.controllers.media_controller, plex_renamer.app.controllers.queue_controller, plex_renamer.gui_qt.main_window, plex_renamer.job_executor)
- Tests: tests/conftest_qt.py, tests/test_executor_metadata_integration.py, tests/test_job_execution_metadata.py, tests/test_job_preview_grouping.py, tests/test_job_store_metadata_plan.py, tests/test_media_controller.py, tests/test_metadata_embed_extras.py, tests/test_metadata_local_inventory.py, tests/test_metadata_service.py, tests/test_mkvmerge_integration.py, tests/test_qt_job_detail_panel.py, tests/test_qt_main_window.py, tests/test_qt_media_workspace.py, tests/test_qt_queue_history.py, tests/test_queue_controller.py, tests/test_queue_executor_progress.py, tests/test_queue_tab_remux.py, tests/test_remux_confirmation.py, tests/test_remux_embed_extras.py, tests/test_remux_execution.py, tests/test_remux_job_model.py, tests/test_remux_revert.py, tests/test_scan_improvements.py

### `plex_renamer/keys.py` — API key storage with OS keyring preference and local fallback.
- `save_api_key(service, key) -> None` — Persist an API key using keyring when available, else local fallback. (used by: plex_renamer.gui_qt.widgets._settings_tab_actions)
- `get_api_key(service) -> str | None` — Retrieve a stored API key from keyring or the local fallback file. (used by: plex_renamer.gui_qt._main_window_bootstrap, plex_renamer.gui_qt.main_window, plex_renamer.gui_qt.widgets._settings_tab_sections)

### `plex_renamer/parsing.py` — Filename parsing and name-building utilities.
- Tests: tests/test_bare_episode_prefix_titles.py, tests/test_companion_subtitles.py, tests/test_episode_resolution.py, tests/test_extras_and_prefix_fixes.py, tests/test_filename_formatting.py, tests/test_haikyuu_matching.py, tests/test_jojo_matching.py, tests/test_parsing_corpus.py, tests/test_parsing_edgecases.py, tests/test_release_junk_titles.py, tests/test_run_extension_guards.py, tests/test_scan_improvements.py, tests/test_symbol_folding.py, tests/test_tv_scanner_normal.py, tests/test_umbrella_season_merge.py, tests/test_underscore_segments.py

### `plex_renamer/thread_pool.py` — Shared thread pool for background work.
- `submit(fn, *args, **kwargs) -> Future` — Submit *fn* to the shared pool.  Returns a :class:`~concurrent.futures.Future`. (used by: plex_renamer.app.controllers._movie_batch_helpers, plex_renamer.app.controllers._single_show_scan_helpers, plex_renamer.app.controllers._tv_batch_helpers, plex_renamer.gui_qt.main_window, plex_renamer.gui_qt.widgets._episode_table_model, plex_renamer.gui_qt.widgets._job_detail_poster, plex_renamer.gui_qt.widgets._match_picker_search, plex_renamer.gui_qt.widgets._media_workspace_automux, plex_renamer.gui_qt.widgets._roster_model, plex_renamer.gui_qt.widgets._work_panel, plex_renamer.gui_qt.widgets.settings_tab)
- `drain(timeout) -> bool` — Cancel queued work and wait (bounded) for running work to finish.
- `shutdown(wait) -> None` — Shut down the shared pool (also registered as an *atexit* hook).

### `plex_renamer/tmdb.py` — TMDB (The Movie Database) API client.
- `TMDBClient` — TMDB client with connection pooling, response caching, rate limiting, (used by: plex_renamer.app.services.metadata_service, plex_renamer.engine._batch_orchestrators, plex_renamer.engine._batch_tv_match_policy, plex_renamer.engine._movie_scanner, plex_renamer.engine._tv_scanner, plex_renamer.engine.matching, plex_renamer.gui_qt.main_window)
- Tests: tests/test_tmdb.py, tests/test_tmdb_export_assets.py
