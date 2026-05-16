# Code Review & Refactor Plan

Last reviewed: 2026-04-13

Verification snapshot:
- Full suite: 392 passed in 15.92s via `python -m pytest`
- Qt smoke: 85 passed in 9.13s via [scripts/test-smoke.cmd](../scripts/test-smoke.cmd)
- Current repo state is stable enough to prioritize structural refactors over test triage.

## Progress

- [x] **#4** cache/policy consolidation — `PersistentCacheService` delegates freshness to `RefreshPolicyService` via DI.
- [x] **#5** TMDB persistence — `TMDBClient` now reads/writes L2 via the persistent cache; wired in `main_window`.
- [x] **#1** engine.py split — converted to `engine/` package (`_core.py`, `models.py`, `_state.py`, `matching.py`), public API preserved via `__init__.py`.
- [x] **#3** matching consolidation — 9 scoring functions extracted to [plex_renamer/engine/matching.py](../plex_renamer/engine/matching.py).
- [x] **#10** fast vs smoke split — added [scripts/test-fast.cmd](../scripts/test-fast.cmd) / [test-fast.ps1](../scripts/test-fast.ps1) / [test_fast_runner.py](../scripts/test_fast_runner.py); runs the non-Qt suite with the same concise-summary format as `test-smoke`.
- [x] **#9** test shape rebalance — split the Qt smoke surface into focused files plus shared [tests/conftest_qt.py](../tests/conftest_qt.py); backfilled unit coverage for cache, gating, refresh-policy, and settings services.
- [x] **#2** media workspace split — extracted shared widget pieces to [plex_renamer/gui_qt/widgets/_workspace_widgets.py](../plex_renamer/gui_qt/widgets/_workspace_widgets.py); `media_workspace.py` is no longer the monolithic hotspot it once was.
- [x] **#6** centralize threading — replaced most ad hoc worker-thread call sites with the shared executor in [plex_renamer/thread_pool.py](../plex_renamer/thread_pool.py). `QueueExecutor` remains intentionally separate.
- [x] **#7** magic numbers to constants — moved repeated parsing and scoring literals into [plex_renamer/constants.py](../plex_renamer/constants.py).
- [x] **#8** settings schema validation — added explicit schema validation to [plex_renamer/app/services/settings_service.py](../plex_renamer/app/services/settings_service.py).
- [x] **#11** automate release steps — added [scripts/release.ps1](../scripts/release.ps1) + [scripts/release.cmd](../scripts/release.cmd).
- [x] **#12** add CI — added [.github/workflows/ci.yml](../.github/workflows/ci.yml) for fast-suite coverage on PRs and pushes.
- [x] **#13** batch TV orchestration policy split — extracted duplicate labeling, season-merge helpers, and near-tie match policy from [plex_renamer/engine/_batch_orchestrators.py](../plex_renamer/engine/_batch_orchestrators.py) into private engine modules; `discover_shows()` now reads as workflow orchestration.
- [x] **#14** TVScanner helper split — extracted specials matching and consolidated-preview logic from [plex_renamer/engine/_tv_scanner.py](../plex_renamer/engine/_tv_scanner.py) into private helper modules while keeping `TVScanner` as the public facade.
- [x] **#15** TVScanner normal-preview and postprocess split — extracted the normal preview builder plus duplicate-episode resolution and completeness reporting from [plex_renamer/engine/_tv_scanner.py](../plex_renamer/engine/_tv_scanner.py); `TVScanner` remains the cache-owning facade.
- [x] **#16** JobStore path-propagation split — extracted queued-job path rewrite logic from [plex_renamer/job_store.py](../plex_renamer/job_store.py) into [plex_renamer/_job_path_propagation.py](../plex_renamer/_job_path_propagation.py); `JobStore` remains the persistence facade and now has focused coverage for downstream path updates.
- [x] **#17** job executor filesystem split — extracted queued rename move/cleanup helpers from [plex_renamer/job_executor.py](../plex_renamer/job_executor.py) into [plex_renamer/_job_execution_filesystem.py](../plex_renamer/_job_execution_filesystem.py); `QueueExecutor`, `_execute_rename()`, and `revert_job()` remain stable entry points.
- [x] **#18** JobStore bootstrap split — extracted SQLite connection setup, schema initialization, and migration helpers from [plex_renamer/job_store.py](../plex_renamer/job_store.py) into [plex_renamer/_job_store_db.py](../plex_renamer/_job_store_db.py); `_get_conn()` and `_migrate_db()` remain as compatibility wrappers on the facade.
- [x] **#19** JobStore codec split — extracted JSON serialization and row-mapping helpers from [plex_renamer/job_store.py](../plex_renamer/job_store.py) into [plex_renamer/_job_store_codec.py](../plex_renamer/_job_store_codec.py); `_row_to_job()` remains as the compatibility wrapper on the facade.
- [x] **#20** JobStore ordering split — extracted queue position compaction and pending-job reorder helpers from [plex_renamer/job_store.py](../plex_renamer/job_store.py) into [plex_renamer/_job_store_ordering.py](../plex_renamer/_job_store_ordering.py); the facade still owns locking and commit boundaries.
- [x] **#21** TV discovery classifier split — extracted TV folder-classification heuristics from [plex_renamer/app/services/tv_library_discovery_service.py](../plex_renamer/app/services/tv_library_discovery_service.py) into [plex_renamer/app/services/_tv_library_classification.py](../plex_renamer/app/services/_tv_library_classification.py); the service now reads primarily as traversal and candidate construction.

## Current Assessment

### What changed

- The original engine, queue, discovery-service, TMDB transport, media-workspace action, widget, controller, and MainWindow bootstrap hotspots have been reduced substantially through helper modules and thin facades.
- The remaining structural debt is now spread across smaller UI coordination seams, where new behavior landing in detail panels or cross-tab glue matters more than raw line count.
- File size is now a weaker signal than mixed ownership. The better signal is whether new features start rebuilding unrelated responsibilities inside otherwise-thin facades.

## Current High-Value Targets

### 1. Monitor MainWindow flow only if more cross-tab glue lands there

[plex_renamer/gui_qt/main_window.py](../plex_renamer/gui_qt/main_window.py) is no longer the main structural hotspot after the bootstrap split. It should still be watched if future work starts rebuilding startup orchestration, queue-feedback wiring, or tab-coordination logic inline.

**Why now:**
- Phase 13 moved service/controller bootstrap and startup feedback state behind a dedicated helper boundary.
- The shell is now closer to its intended role as a thin test-facing facade over coordinators.
- Another MainWindow split is only worth doing if new behavior starts re-concentrating mixed responsibilities there.

**Refactor direction:**
- Keep `MainWindow` as the stable top-level Qt shell and current patch point for tests.
- Prefer small follow-on helper extractions only when new glue accumulates.
- Preserve existing `main_window.py` patch points used by Qt tests and isolated Qt fixtures.

### 2. Reassess detail panels only when new behavior lands

[plex_renamer/gui_qt/widgets/job_detail_panel.py](../plex_renamer/gui_qt/widgets/job_detail_panel.py) and [plex_renamer/gui_qt/widgets/media_detail_panel.py](../plex_renamer/gui_qt/widgets/media_detail_panel.py) are no longer urgent hotspots. They should only move again if new poster, preview-tree, or metadata behavior starts rebuilding dense logic in those facades.

## Do Not Prioritize Yet

- [plex_renamer/gui_qt/widgets/media_workspace.py](../plex_renamer/gui_qt/widgets/media_workspace.py) — now a thin wrapper over workspace coordinators rather than the old monolithic widget.
- [plex_renamer/gui_qt/main_window.py](../plex_renamer/gui_qt/main_window.py) — bootstrap and startup feedback initialization now live in [plex_renamer/gui_qt/_main_window_bootstrap.py](../plex_renamer/gui_qt/_main_window_bootstrap.py); watch the shell, but do not force another split without a fresh mixed-responsibility seam.
- [plex_renamer/tmdb.py](../plex_renamer/tmdb.py) — transport is already extracted, and the remaining facade is cohesive enough for now.
- [plex_renamer/gui_qt/widgets/_workspace_widgets.py](../plex_renamer/gui_qt/widgets/_workspace_widgets.py) — row widgets are now intentionally separated from low-level primitives.
- [plex_renamer/engine/_batch_orchestrators.py](../plex_renamer/engine/_batch_orchestrators.py), [plex_renamer/engine/_tv_scanner.py](../plex_renamer/engine/_tv_scanner.py), [plex_renamer/job_store.py](../plex_renamer/job_store.py), and [plex_renamer/job_executor.py](../plex_renamer/job_executor.py) — recent helper splits mean the main refactor pressure has moved elsewhere.

## Plan of Attack

### Phase 1: Extract engine policy from orchestration

Status: completed on 2026-04-12.

Start with [plex_renamer/engine/_batch_orchestrators.py](../plex_renamer/engine/_batch_orchestrators.py).

Goals:
- Pull duplicate labeling, season merge logic, and match ranking/tiebreak policy into helper modules.
- Preserve current orchestrator public APIs and call flow.
- Add or tighten targeted tests around duplicate handling, season merges, and tie scenarios before moving logic.

Success criteria:
- The orchestrator file becomes materially smaller.
- Duplicate and season-merge logic can be tested without instantiating the full workflow.

Concrete extraction checklist:

- [ ] Lock the current behavior with targeted coverage runs before moving code.
- [ ] Guardrail files for this phase are [tests/test_scan_improvements.py](../tests/test_scan_improvements.py), [tests/test_jojo_matching.py](../tests/test_jojo_matching.py), and the merge-related integration scenarios in [tests/test_media_controller.py](../tests/test_media_controller.py).
- [ ] Keep this phase scoped to `BatchTVOrchestrator` internals first.
- [ ] Do not redesign `BatchMovieOrchestrator`, controller call sites, or public engine exports in the same pass.
- [ ] Extract the duplicate-policy cluster into a private helper module.
- [ ] Duplicate-policy extraction should move `_normalized_relative_folder`, `_duplicate_priority`, and the logic currently inside `_apply_duplicate_labels()` into a private helper module such as `_batch_tv_duplicates.py`.
- [ ] Convert duplicate labeling to a helper that operates on `list[ScanState]` rather than mutating through orchestrator-only state.
- [ ] The orchestrator should remain responsible for storing `self.states`, but duplicate policy should not need the whole class.
- [ ] Extract the season-merge policy cluster into its own private helper module.
- [ ] Season-merge extraction should move `_preview_single_season`, `_represented_seasons`, `_expanded_season_folders`, and `_season_merge_priority` into a private helper module such as `_batch_tv_season_merge.py`.
- [ ] Keep path-resolution behavior stable while extracting season-merge helpers.
- [ ] Preserve the current handling of explicit `season_assignment`, inferred single-season previews, and `season_folders` expansion while moving season-merge logic.
- [ ] Extract near-tie match ranking into a dedicated policy helper.
- [ ] Near-tie ranking extraction should move `_episode_count_tiebreak` and any related count-comparison helpers such as `_count_season_subdirs` into a dedicated policy helper such as `_batch_tv_match_policy.py`.
- [ ] Do not fold TMDB querying or discovery walking into the new helper modules yet.
- [ ] `discover_shows()` should still own the workflow: discovery, batch query, scoring call, state creation, and post-processing.
- [ ] After the policy helpers are in place, split `discover_shows()` into smaller private workflow steps without changing behavior.
- [ ] Suggested private method boundaries for `discover_shows()` are `build discovery candidates`, `build unmatched state`, `select best scored result`, and `post-process states`.
- [ ] Preserve the current public entry points and data shape.
- [ ] `BatchTVOrchestrator.__init__()` and `discover_shows()` should not change signature in this phase.
- [ ] Keep helper extraction functional before making naming/style cleanup edits.
- [ ] No opportunistic algorithm changes in the same PR.

Suggested implementation order:

1. Extract duplicate priority and duplicate labeling.
2. Extract season-representation and season-merge helpers.
3. Extract episode-count tie resolution.
4. Slice `discover_shows()` into internal workflow helpers.
5. Run the full regression bar and only then consider cleanup.

Verification checklist for Phase 1:

- [ ] Run targeted engine coverage with `python -m pytest tests/test_scan_improvements.py tests/test_jojo_matching.py`.
- [ ] Re-run merge/integration scenarios that consume the orchestrator shape with `python -m pytest tests/test_media_controller.py`.
- [ ] Run the full suite with `python -m pytest` after the extraction settles.
- [ ] Run [scripts/test-smoke.cmd](../scripts/test-smoke.cmd) before closing the phase.

Phase 1 done means:

- Duplicate labeling is no longer implemented inline inside [plex_renamer/engine/_batch_orchestrators.py](../plex_renamer/engine/_batch_orchestrators.py).
- Season merge policy is isolated from the top-level workflow.
- Near-tie ranking is isolated from `discover_shows()`.
- `discover_shows()` reads as orchestration rather than a mixed policy-and-workflow method.

### Phase 2: Split TV scanner builders

Status: completed on 2026-04-12.

Move next to [plex_renamer/engine/_tv_scanner.py](../plex_renamer/engine/_tv_scanner.py).

Goals:
- Separate normal preview building from consolidated preview building.
- Isolate specials matching and related title-resolution helpers.
- Keep `TVScanner` as the compatibility facade so the rest of the app does not change shape.

Success criteria:
- The scanner reads as an orchestrator instead of a large implementation blob.
- Preview-building behavior is covered by narrower tests with less fixture setup.

Completed in the current slice:
- Extracted specials and extras matching to [plex_renamer/engine/_tv_scanner_specials.py](../plex_renamer/engine/_tv_scanner_specials.py).
- Extracted consolidated-preview and title-based absolute matching to [plex_renamer/engine/_tv_scanner_consolidated.py](../plex_renamer/engine/_tv_scanner_consolidated.py).
- Extracted the normal preview builder to [plex_renamer/engine/_tv_scanner_normal.py](../plex_renamer/engine/_tv_scanner_normal.py).
- Extracted duplicate-episode resolution and completeness reporting to [plex_renamer/engine/_tv_scanner_postprocess.py](../plex_renamer/engine/_tv_scanner_postprocess.py).
- Preserved `TVScanner` public APIs and existing scanner-focused tests.
- Kept TMDB season-cache ownership on `TVScanner` so helper modules stay stateless and the facade still owns cache invalidation.

Phase 2 done means:

- The scanner no longer embeds specials, consolidated-preview, and normal-preview logic inline in one file.
- Duplicate-episode resolution and completeness reporting are isolated from the core scan workflow.
- `TVScanner` acts primarily as the public facade, cache owner, and workflow entry point.

### Phase 3: Untangle queue persistence and execution

Address [plex_renamer/job_store.py](../plex_renamer/job_store.py) and [plex_renamer/job_executor.py](../plex_renamer/job_executor.py) together, but in two small passes rather than one big rewrite.

Status: in progress on 2026-04-12.

Goals:
- First split `JobStore` into facade + extracted persistence/path-propagation helpers.
- Then split `job_executor.py` into queue orchestration + filesystem operation helpers.
- Preserve job model and listener APIs so GUI/controller code stays stable.

Success criteria:
- Queue-domain rules are no longer buried inside persistence plumbing.
- Rename/revert logic becomes easier to reason about independently from queue sequencing.

Completed in the current slice:
- Extracted queued-job path rewrite logic to [plex_renamer/_job_path_propagation.py](../plex_renamer/_job_path_propagation.py).
- Kept [plex_renamer/job_store.py](../plex_renamer/job_store.py) as the caller-facing facade and compatibility home for `_rebase_path()`.
- Added explicit store-level coverage for downstream path propagation so future queue refactors can move faster without relying on indirect executor behavior.
- Extracted queued rename move/cleanup helpers to [plex_renamer/_job_execution_filesystem.py](../plex_renamer/_job_execution_filesystem.py).
- Kept [plex_renamer/job_executor.py](../plex_renamer/job_executor.py) focused on job lifecycle, rename-plan construction, and public queue/revert entry points.
- Extracted SQLite connection setup, schema initialization, and migration helpers to [plex_renamer/_job_store_db.py](../plex_renamer/_job_store_db.py).
- Kept [plex_renamer/job_store.py](../plex_renamer/job_store.py) as the queue/persistence facade so existing tests and controller call sites still go through `_get_conn()` and `JobStore` methods.
- Extracted JSON serialization and row-mapping helpers to [plex_renamer/_job_store_codec.py](../plex_renamer/_job_store_codec.py).
- Added explicit round-trip coverage for companion-file rename ops and stored undo payloads so future persistence refactors do not regress queue history and detail views.
- Extracted queue ordering helpers to [plex_renamer/_job_store_ordering.py](../plex_renamer/_job_store_ordering.py).
- Added direct coverage for reorder, block-move, and move-to-top behavior so the remaining store facade can be treated as stable orchestration glue.

Next slice:
- Phase 3 is now in a reasonable stopping state; the remaining `JobStore` methods are mostly facade-level queries and simple writes.
- Consider a follow-on executor slice only if `revert_job()` or final-root routing starts to grow again; the move/cleanup path is no longer the primary hotspot.

### Phase 4: Clean up discovery services

Then refactor [plex_renamer/app/services/tv_library_discovery_service.py](../plex_renamer/app/services/tv_library_discovery_service.py).

Status: completed on 2026-04-12.

Goals:
- Separate folder classification from recursive traversal.
- Keep current discovery behavior and symlink guards intact.
- Add explicit tests around edge-case directory classification before extracting.

Success criteria:
- Discovery heuristics are easier to evolve without touching traversal logic.
- The service entry point remains stable while the internal responsibilities become clearer.

Completed in the current slice:
- Extracted TV folder-classification heuristics to [plex_renamer/app/services/_tv_library_classification.py](../plex_renamer/app/services/_tv_library_classification.py).
- Kept [plex_renamer/app/services/tv_library_discovery_service.py](../plex_renamer/app/services/tv_library_discovery_service.py) as the traversal and candidate-building facade.
- Added direct classification coverage for explicit-episode roots and specials-only container bundles so discovery behavior is not protected only through orchestrator-level tests.

Phase 4 done means:

- Folder classification is no longer implemented inline with recursive traversal.
- TV discovery behavior is covered both directly at the service layer and indirectly through orchestrator discovery tests.
- The remaining service code is mostly traversal orchestration, candidate construction, and compatibility wrappers.

### Phase 5: Re-evaluate GUI hotspots after backend simplification

Once engine and queue debt are reduced, reassess [plex_renamer/gui_qt/widgets/job_detail_panel.py](../plex_renamer/gui_qt/widgets/job_detail_panel.py) and [plex_renamer/gui_qt/widgets/_media_workspace_actions.py](../plex_renamer/gui_qt/widgets/_media_workspace_actions.py).

Status: completed on 2026-04-12.

Goals:
- Avoid premature GUI churn while backend contracts are still moving.
- Only split GUI files where the resulting boundaries are obvious and stable.

Completed in the current slice:
- Reassessed both GUI hotspots after the backend simplification work.
- Left [plex_renamer/gui_qt/widgets/job_detail_panel.py](../plex_renamer/gui_qt/widgets/job_detail_panel.py) alone because it is already mostly a shell over extracted data, poster, preview, and tree helpers.
- Extracted media-workspace queue workflows to [plex_renamer/gui_qt/widgets/_media_workspace_queue_actions.py](../plex_renamer/gui_qt/widgets/_media_workspace_queue_actions.py).
- Extracted rematch/approval workflows to [plex_renamer/gui_qt/widgets/_media_workspace_match_actions.py](../plex_renamer/gui_qt/widgets/_media_workspace_match_actions.py).
- Extracted label and predicate helpers to [plex_renamer/gui_qt/widgets/_media_workspace_action_state.py](../plex_renamer/gui_qt/widgets/_media_workspace_action_state.py), leaving [plex_renamer/gui_qt/widgets/_media_workspace_actions.py](../plex_renamer/gui_qt/widgets/_media_workspace_actions.py) as a thinner coordinator.
- Extracted action-bar/button-state orchestration to [plex_renamer/gui_qt/widgets/_media_workspace_action_bar.py](../plex_renamer/gui_qt/widgets/_media_workspace_action_bar.py), leaving the coordinator as a wrapper over queue, match, and UI-state helpers.

Phase 5 done means:

- The next GUI split followed an already-stable boundary instead of forcing churn into a panel that had already been decomposed.
- `media_workspace.py` wrapper methods and dialog patch points stayed stable for the existing Qt tests.
- The remaining action coordinator code is a thin routing layer over extracted workflows and button-state helpers.

### Phase 6: Clean up movie discovery service

Refactor [plex_renamer/app/services/movie_library_discovery_service.py](../plex_renamer/app/services/movie_library_discovery_service.py) using the same traversal-versus-classification split that already worked for TV discovery.

Status: completed on 2026-04-12.

Goals:
- Separate folder classification from recursive traversal.
- Keep current multi-movie, extras, and TV-exclusion behavior intact.
- Add direct classification coverage for movie-specific heuristics before or during extraction.

Completed in the current slice:
- Extracted movie folder-classification heuristics to [plex_renamer/app/services/_movie_library_classification.py](../plex_renamer/app/services/_movie_library_classification.py).
- Kept [plex_renamer/app/services/movie_library_discovery_service.py](../plex_renamer/app/services/movie_library_discovery_service.py) focused on traversal, candidate construction, and compatibility wrappers.
- Added direct classification coverage for multi-movie folders and majority-TV-content folders in [tests/test_movie_discovery.py](../tests/test_movie_discovery.py).

Phase 6 done means:

- Movie discovery heuristics can evolve without touching recursive traversal.
- The public service entry point and result shape stay stable for orchestrators and tests.
- Movie discovery now follows the same internal pattern as TV discovery, which makes future maintenance less ad hoc.

### Phase 7: Clean up TMDB client transport

Refactor [plex_renamer/tmdb.py](../plex_renamer/tmdb.py) so the public client remains the stable facade while the HTTP session, rate limiter, retry loop, and raw download logic move into a dedicated transport helper.

Status: completed on 2026-04-12.

Goals:
- Separate transport concerns from metadata and image orchestration.
- Keep `TMDBClient` attributes and method behavior stable for existing callers and tests.
- Add direct coverage for the extracted retry and error-handling behavior.

Completed in the current slice:
- Extracted HTTP session setup, token-bucket rate limiting, retry policy, and raw byte download helpers to [plex_renamer/_tmdb_transport.py](../plex_renamer/_tmdb_transport.py).
- Kept [plex_renamer/tmdb.py](../plex_renamer/tmdb.py) as the public facade over batch search, metadata caches, poster orchestration, and fallback search helpers.
- Added direct transport-behavior coverage for 404 handling, transient network retry, and non-retryable API errors in [tests/test_tmdb.py](../tests/test_tmdb.py).

Phase 7 done means:

- TMDB transport mechanics can evolve without tangling the higher-level client methods.
- `TMDBClient` still exposes the same top-level session and rate-limiter attributes expected by the current tests.
- Future TMDB work can target transport, metadata shaping, and image caching as separate concerns instead of one large client file.

### Phase 8: Clean up workspace widget primitives

Refactor [plex_renamer/gui_qt/widgets/_workspace_widgets.py](../plex_renamer/gui_qt/widgets/_workspace_widgets.py) so shared checkbox, label, and progress controls live separately from the roster and preview row widgets that the media workspace uses directly.

Status: completed on 2026-04-12.

Goals:
- Separate low-level reusable Qt controls from the higher-level row widgets.
- Keep the row widget classes and their import surface stable for existing media-workspace tests.
- Add direct Qt coverage for the extracted primitive controls.

Completed in the current slice:
- Extracted shared checkbox, elision, click-row, progress-bar, and poster-bridge primitives to [plex_renamer/gui_qt/widgets/_workspace_widget_primitives.py](../plex_renamer/gui_qt/widgets/_workspace_widget_primitives.py).
- Kept [plex_renamer/gui_qt/widgets/_workspace_widgets.py](../plex_renamer/gui_qt/widgets/_workspace_widgets.py) focused on roster, preview, and folder-preview row widgets while re-exporting the shared primitives.
- Added direct Qt coverage for the extracted controls in [tests/test_qt_workspace_widgets.py](../tests/test_qt_workspace_widgets.py).

Phase 8 done means:

- Shared workspace controls can evolve without forcing churn in the row-widget file.
- Existing media-workspace imports and `isinstance` checks for row widgets stay stable.
- The workspace widget layer now has a clearer split between reusable primitives and media-specific row composition.

### Phase 9: Split controller session storage

Refactor [plex_renamer/app/controllers/media_controller.py](../plex_renamer/app/controllers/media_controller.py) so TV session state, movie session state, and mode-selection state live in dedicated private containers instead of one controller file owning every raw field directly.

Status: completed on 2026-04-12.

Goals:
- Separate raw controller storage from the wrapper methods and helper-module entry points.
- Keep `MediaController` public methods and the existing private helper attribute surface stable.
- Make a later TV-vs-movie controller split easier without forcing that bigger redesign now.

Completed in the current slice:
- Extracted TV, movie, and mode-selection state containers to [plex_renamer/app/controllers/_controller_session_models.py](../plex_renamer/app/controllers/_controller_session_models.py).
- Kept [plex_renamer/app/controllers/media_controller.py](../plex_renamer/app/controllers/media_controller.py) as the stable facade, with compatibility properties preserving the `_batch_*`, `_movie_*`, and mode fields used by current helper modules.
- Left the controller's public wrapper methods and current test-facing API unchanged while reducing direct state ownership in the facade.

Phase 9 done means:

- `MediaController` no longer stores every TV, movie, and selection field inline in its constructor.
- Existing helper modules can keep routing through the controller's current private attribute surface while the real storage lives in dedicated session containers.
- A future controller split can target TV/movie behavior rather than first untangling raw state ownership.

### Phase 10: Separate MediaController behavior by media type

Refactor [plex_renamer/app/controllers/media_controller.py](../plex_renamer/app/controllers/media_controller.py) further so the stable facade delegates TV-specific and movie-specific workflow behavior through dedicated private helpers.

Status: completed on 2026-04-12.

Goals:
- Keep `MediaController` as the stable public wrapper surface used by tests and Qt wiring.
- Separate TV-specific workflow routing from movie-specific workflow routing.
- Preserve listener semantics, scan-progress updates, and current wrapper-method names.

Completed in the current slice:
- Extracted TV-specific workflow routing to [plex_renamer/app/controllers/_controller_tv_workflows.py](../plex_renamer/app/controllers/_controller_tv_workflows.py).
- Extracted movie-specific workflow routing to [plex_renamer/app/controllers/_controller_movie_workflows.py](../plex_renamer/app/controllers/_controller_movie_workflows.py).
- Kept [plex_renamer/app/controllers/media_controller.py](../plex_renamer/app/controllers/media_controller.py) as the stable wrapper surface, including the module-level patch points used by controller tests.

Phase 10 done means:

- TV and movie workflow behavior no longer share one dense facade implementation.
- The controller facade mostly owns listener dispatch, progress routing, and mode selection.
- Future controller work can target one media type at a time instead of touching one cross-cutting file.

### Phase 11: Isolate controller projection and queue sync

Refactor the remaining shared controller state-projection logic so [plex_renamer/app/controllers/media_controller.py](../plex_renamer/app/controllers/media_controller.py) delegates completed-job projection and queued-state synchronization through a dedicated private helper boundary.

Status: completed on 2026-04-13.

Goals:
- Keep `MediaController` wrapper methods stable.
- Separate job-to-state projection from general controller orchestration.
- Keep TV and movie queued-state synchronization behavior unchanged.

Completed in the current slice:
- Extracted completed-job projection and queued-state synchronization to [plex_renamer/app/controllers/_controller_projection_workflow.py](../plex_renamer/app/controllers/_controller_projection_workflow.py).
- Slimmed [plex_renamer/app/controllers/_controller_state_helpers.py](../plex_renamer/app/controllers/_controller_state_helpers.py) back to session-routing responsibilities.
- Kept [plex_renamer/app/controllers/media_controller.py](../plex_renamer/app/controllers/media_controller.py) as the stable wrapper surface for `apply_completed_job_to_state()` and `sync_queued_states()`.

Phase 11 done means:

- Completed-job projection no longer lives as an incidental helper path on the main controller facade.
- Queue-sync logic has an explicit home separate from listener and scan-lifecycle concerns.
- The next controller refactor can focus on orchestration polish rather than state-projection plumbing.

### Phase 12: Separate MediaController lifecycle coordination

Refactor [plex_renamer/app/controllers/media_controller.py](../plex_renamer/app/controllers/media_controller.py) so scan-operation tracking, progress updates, and related lifecycle wiring delegate through a dedicated private coordinator.

Status: completed on 2026-04-13.

Goals:
- Keep `MediaController` wrapper methods and listener semantics stable.
- Separate scan lifecycle and cancellation management from session routing and workflow delegation.
- Preserve current progress payloads used by controller and Qt tests.

Completed in the current slice:
- Extracted scan-progress and cancellation coordination to [plex_renamer/app/controllers/_controller_lifecycle_workflow.py](../plex_renamer/app/controllers/_controller_lifecycle_workflow.py).
- Kept [plex_renamer/app/controllers/media_controller.py](../plex_renamer/app/controllers/media_controller.py) as the stable wrapper surface for `_set_progress()`, `cancel_scan()`, and the direct `_scan_progress` compatibility path used by current tests.

Phase 12 done means:

- `MediaController` no longer owns raw scan-operation lifecycle mechanics inline.
- Progress updates and cancel-token coordination have an explicit home separate from session and workflow routing.
- The next remaining large seams will be in UI shell/bootstrap code rather than controller internals.

### Phase 13: Reassess MainWindow bootstrap and app-flow wiring

Refactor [plex_renamer/gui_qt/main_window.py](../plex_renamer/gui_qt/main_window.py) only if the current service/bootstrap and app-flow wiring can be isolated behind another stable coordinator boundary without disturbing the existing test patch points.

Status: completed on 2026-04-13.

Goals:
- Keep `main_window.py` as the stable shell and current patch point for Qt tests.
- Reduce the amount of service/bootstrap and global app-flow wiring that still lives in the top-level window class.
- Preserve current queue feedback, undo, startup, and tab-switch behavior.

Completed in the current slice:
- Extracted service/controller bootstrap and bridge installation to [plex_renamer/gui_qt/_main_window_bootstrap.py](../plex_renamer/gui_qt/_main_window_bootstrap.py).
- Moved startup queue-feedback state and success-toast timer initialization behind the bootstrap coordinator instead of keeping that setup inline in [plex_renamer/gui_qt/main_window.py](../plex_renamer/gui_qt/main_window.py).
- Kept `main_window.py` as the stable patch point for `SettingsService`, `PersistentCacheService`, `JobStore`, `QTimer.singleShot`, and `QMessageBox.question`, which current Qt fixtures and tests patch directly.

Phase 13 done means:

- The app shell no longer owns as much bootstrap and cross-tab wiring inline.
- MainWindow remains a stable test-facing shell while more of the app-flow setup lives behind dedicated helpers.
- The remaining refactor pressure shifts from broad structural cleanup toward incremental polish and only narrow follow-on extractions.

## Working Rules for the Refactor

- Keep public APIs stable where possible; prefer internal extraction over surface redesign.
- Refactor behind existing tests first, then add targeted tests for the behavior being extracted.
- Preserve behavior before chasing naming/style cleanup.
- Avoid simultaneous engine and GUI rewrites in the same pass.
- Treat the full pytest run and the Qt smoke wrapper as the minimum verification bar for each phase.
