# GUI3 PySide6 Migration Plan

## Purpose

This document turns the GUI migration discussion into a concrete plan that can be audited before committing to a rewrite.

The goal is not to redesign the product from scratch. The goal is to preserve the current workflow that works, fix the weak points that do not, and create a UI shell that can grow into a broader suite of queue-driven tools.

Primary constraints:

- Keep the current media workflow recognizable.
- Keep `main` and `dev/alpha` isolated while GUI3 is explored.
- Preserve data integrity over perceived speed.
- Move long-lived logic out of the UI layer before or during migration.
- Treat PySide6 as the target shell, not as a reason to rewrite stable backend code.

## Executive Summary

Recommended direction:

1. Keep the current backend core and continue hardening it.
2. Stop adding major new tkinter-specific UI complexity.
3. Introduce a UI-neutral application layer between the core logic and the GUI.
4. Build a new PySide6 shell in stages while preserving the current three-panel workflow.
5. Use the migration to fix current UX gaps around progress presentation, queue eligibility, and scan state clarity.

This should be treated as a shell migration plus application-layer refactor, not as a backend rewrite.

## Current System Assessment

## What Currently Works Well

The current app already has several strengths worth preserving:

1. The domain logic is not fully trapped inside the GUI.
2. The three-panel workflow is understandable and effective.
3. Queue and history are already separate concepts, not bolted-on afterthoughts.
4. TV, movie, queue, history, and settings already map naturally to top-level tabs.
5. The backend modules are good candidates for reuse across multiple future tools.

Current backend modules that are already reusable:

- `plex_renamer/parsing.py`
- `plex_renamer/tmdb.py`
- `plex_renamer/engine.py`
- `plex_renamer/job_store.py`
- `plex_renamer/job_executor.py`
- `plex_renamer/constants.py`

## What Is Currently Holding the GUI Back

The main problem is not the business logic. The main problem is that the tkinter layer is carrying too much responsibility for rendering, interaction, state bridging, and asynchronous feedback.

### 1. Data presentation is effective in places, but uneven

Useful current presentation patterns:

1. Left-side library roster gives a strong high-level scan summary.
2. Center preview cards are good at showing rename intent.
3. Right-side detail panel provides useful metadata context.
4. Queue/history separation is conceptually correct.

Where the presentation weakens:

1. Scan lifecycle is not presented as a first-class state machine.
2. Queue eligibility is mostly inferred by the user instead of explained by the UI.
3. There is no strong distinction between "not ready", "ready", "queued", "blocked", and "stale".
4. Current status visibility is spread across badge text, roster text, status-bar text, and popups.
5. Some high-value states are only visible after clicking into a specific pane.

### 2. Progress presentation is a serious weak point

The current implementation uses a status bar string, a percent bar, and a basic overlay, primarily from `plex_renamer/gui/app.py`.

Observed weaknesses:

1. Progress is mostly textual and phase-local rather than entity-local.
2. The scanning overlay is visually prominent but shallow: it shows a message and a single mutable text field rather than structured progress.
3. There is no persistent per-show progress model in the UI.
4. There is no explicit cancellation strategy.
5. There is no strong distinction between discovery, TMDB matching, local cache lookup, scan, and post-scan validation.
6. Progress is not consistently reflected across roster, preview, and queue eligibility.

Concrete code signals:

- `PlexRenamerApp._show_scan_overlay()` and `_update_scan_overlay()` provide only a lightweight overlay.
- `PlexRenamerApp._set_scan_buttons_enabled()` only disables folder selection buttons, not all actions that should be gated during scan activity.
- Scanning progress is spread across `status_var`, `progress_var`, roster text, and preview placeholder states.

Impact:

1. Users cannot easily tell what the app is currently doing.
2. Users cannot easily tell what is safe to do next.
3. The app feels busy without feeling trustworthy.

### 3. Access control for adding items to the queue is a serious weak point

Current queue gating is mostly procedural, not visual.

Observed weaknesses:

1. The `Add to Queue` action is visible even when the current content is not actually ready.
2. Eligibility is determined deep in click handlers instead of being surfaced clearly in the UI.
3. The user often learns something is blocked only after clicking and getting a popup or a passive status message.
4. Batch logic silently skips states that are unscanned, currently scanning, duplicate, already queued, or non-actionable.
5. Queue access control is distributed across multiple code paths for TV, single-item, and movie batch flows.
6. The app has no unified "why can or can't I queue this?" explanation model.

Concrete code signals:

- `_add_single_to_queue()` performs readiness checks only at action time.
- `_add_movie_batch_to_queue()` and `_add_batch_to_queue()` silently skip ineligible items in several branches.
- `_set_scan_buttons_enabled()` does not disable queue actions.
- The roster marks items as queued or scanning, but those statuses are not tied to an explicit command-availability model.

Impact:

1. Queue submission feels inconsistent.
2. The UI does not reliably prevent invalid or premature actions.
3. The mental model for queue readiness is weaker than it should be for a queue-centric tool.

### 4. The current tkinter rendering model is expensive to keep extending

Large portions of the UI are custom-drawn or manually coordinated:

- `plex_renamer/gui/preview_canvas.py`
- `plex_renamer/gui/result_views.py`
- `plex_renamer/gui/library_panel.py`
- `plex_renamer/gui/helpers.py`
- parts of `plex_renamer/gui/queue_panel.py`

That approach has already required:

1. Manual hit testing.
2. Manual redraw logic.
3. Manual scroll routing.
4. Manual selection visuals.
5. Manual progress overlays.
6. Manual bridging between ScanState and ad hoc UI state.

This is manageable for a focused utility. It is the wrong long-term foundation for a growing suite.

## Existing GUI Data Presentation Audit

The migration should preserve the useful presentation patterns and redesign the weak ones.

### Preserve

1. Top-level tabs for media domains and utility areas.
2. Left roster, center preview, right detail workflow.
3. Card-like preview with original name, target name, and status.
4. Queue/history as operational tabs rather than secondary dialogs.
5. Rich detail panel with posters and metadata.

### Improve

1. Make scan stages explicit.
2. Make queue readiness explicit.
3. Show stale-versus-fresh state for cached metadata.
4. Give unmatched and review states stronger grouping and clearer action paths.
5. Make background activity visible without forcing the user to infer from status text.

### Replace

1. Single-string status reporting as the main progress language.
2. Action-time-only validation for queue eligibility.
3. Canvas-heavy list rendering where model/view widgets are a better fit.

## Migration Principles

1. Preserve domain logic before replacing visuals.
2. Prefer moving logic into UI-neutral services rather than directly from tkinter to PySide6 widgets.
3. Build the new shell in slices that can be validated independently.
4. Keep GUI3 shippable in partial form as long as the current shell remains available.
5. Use the migration to fix weak UX flows, not only to restyle the app.

## Target Architecture

## Layers

### 1. Core domain layer

This layer should remain Python-first and UI-agnostic.

Keep and evolve:

- `plex_renamer/constants.py`
- `plex_renamer/parsing.py`
- `plex_renamer/tmdb.py`
- `plex_renamer/engine.py`
- `plex_renamer/job_store.py`
- `plex_renamer/job_executor.py`
- `plex_renamer/undo_log.py` — retire after `Ctrl+Z` is routed through `revert_job` (see Phase 1 cleanup)

This layer should not depend on PySide6.

### 2. Application layer

This layer does not fully exist yet. It should be introduced as the bridge between the core and the future UI.

New responsibility areas:

1. Session orchestration.
2. Scan lifecycle state.
3. Queue eligibility and command gating.
4. Refresh policy and cooldown rules.
5. Persistent cache coordination.
6. UI-facing view models.

Current package structure (implemented):

```text
plex_renamer/app/
    __init__.py
    controllers/
        __init__.py                      # re-exports domain types for PySide6 shell
        media_controller.py              # TV/movie session orchestration
        queue_controller.py              # job queue management
    models/
        __init__.py                      # ScanProgress, QueueEligibility, etc.
    services/
        __init__.py
        cache_service.py
        command_gating_service.py
        movie_library_discovery_service.py
        refresh_policy_service.py
        settings_service.py
        tv_library_discovery_service.py
```

### 3. UI shell layer

This will be PySide6-specific.

Suggested new package:

```text
plex_renamer/gui_qt/
    __init__.py
    app.py
    main_window.py
    resources/
    widgets/
        roster_panel.py
        preview_panel.py
        detail_panel.py
        progress_panel.py
        queue_panel.py
        history_panel.py
        settings_panel.py
    dialogs/
        media_picker_dialog.py
        refresh_dialog.py
        api_keys_dialog.py
    models/
        roster_item_model.py
        preview_item_model.py
        queue_item_model.py
```

Note on presenters: presenter and view-model classes should live in `plex_renamer/app/` rather than inside `plex_renamer/gui_qt/`. If presenters import Qt types they belong in the widget layer and serve only as thin adapters. Placing presentation logic in `gui_qt/presenters/` defeats the purpose of the application layer as a toolkit-independent seam.

## Module Boundary Plan

## What Stays

These modules should remain, though some internals may be refactored:

- `plex_renamer/parsing.py`
- `plex_renamer/constants.py`
- `plex_renamer/job_store.py`
- `plex_renamer/job_executor.py`
- most of `plex_renamer/engine.py`
- the low-level TMDB HTTP responsibilities in `plex_renamer/tmdb.py`

These are the durable product core.

## What Moves Out of tkinter

The following concerns currently live in or near the tkinter shell and should move into the new application layer:

1. Scan progress state and phase tracking.
2. Queue command availability logic.
3. Unified status classification for preview items and scan states.
4. Roster grouping logic for matched, review, unmatched, duplicate, queued, stale, and blocked states.
5. Background refresh policies and cooldowns.
6. Session restoration and cache-backed scan snapshot restoration.
7. TV/movie session routing logic currently encoded in `_active_content_mode` and `_active_library_mode` flag pairs.

Current sources that contain logic likely to move:

- `plex_renamer/gui/app.py`
- parts of `plex_renamer/gui/library_panel.py`
- parts of `plex_renamer/gui/preview_canvas.py`

## What Gets Replaced Entirely

These modules are strongly tied to tkinter rendering and should be treated as temporary UI implementations, not migration targets:

- `plex_renamer/gui/app.py`
- `plex_renamer/gui/library_panel.py`
- `plex_renamer/gui/preview_canvas.py`
- `plex_renamer/gui/detail_panel.py`
- `plex_renamer/gui/result_views.py`
- `plex_renamer/gui/dialogs.py`
- `plex_renamer/gui/helpers.py`
- `plex_renamer/gui/queue_panel.py`
- `plex_renamer/styles.py`

Some behavior from these files should survive. The files themselves should not define the future architecture.

## What Needs to Be Split Before UI Migration Progresses Too Far

### `engine.py`

`engine.py` is valuable, but it is accumulating presentation-adjacent concerns.

Recommended direction:

Keep in `engine.py`:

1. scanners
2. rename planning
3. preview item generation
4. duplicate detection
5. completeness logic

Move out of `engine.py` over time:

1. UI-facing status semantics that depend on how states should be presented
2. command gating rules for queueing
3. persistence orchestration for refresh states

### `tmdb.py`

Keep `tmdb.py` as the network and in-process cache client, but move persistence-aware caching policy into a new service layer.

Keep in `tmdb.py`:

1. HTTP session management
2. rate limiting
3. request retry behavior
4. raw TMDB endpoint access
5. in-process image caching

Move out to `cache_service.py` and related services:

1. persistent cache storage
2. stale-while-revalidate policy
3. show-status-based TTL rules
4. manual refresh cooldown rules
5. cache invalidation from filesystem changes

## Proposed UI Structure in PySide6

## Main window

Keep the current high-level layout concept:

1. Top tab bar.
2. TV tab.
3. Movies tab.
4. Queue tab.
5. History tab.
6. Settings tab.
7. Later tool tabs can be added without changing the shell model.

## TV and Movies workspace layout

Preserve the same mental model:

1. Left: roster/library panel.
2. Center: preview panel.
3. Right: detail and completeness panel.

Replace custom canvas-heavy rendering with Qt widgets and model/view components.

Suggested widget choices:

1. `QSplitter` for main panel layout.
2. `QListView` or `QTreeView` with delegates for the roster.
3. `QListView` or `QTreeView` with grouped sections for preview items.
4. `QStackedWidget` in the center panel for preview, scanning state, results state, and empty state.
5. Dedicated detail pane widgets rather than redraw-driven content.

## Queue and History

Use `QTreeView` or `QTableView` with proper item models.

Desired improvements:

1. Explicit job state icons.
2. Clear explanation of why a job is pending, blocked, running, failed, or reverted.
3. Stronger integration with roster state and queue eligibility.

## Critical UX Changes Required During Migration

## 1. Progress presentation redesign

This is not optional.

Required target behavior:

1. Show current scan phase explicitly.
2. Show unit of progress explicitly.
3. Show entity-level progress where relevant.
4. Show whether work is local, cached, or remote.
5. Keep progress visible in the roster for each relevant entity.
6. Provide a clear busy/idle/failed/cancelled state model.

Suggested scan phases:

1. Folder discovery
2. Query preparation
3. Cache lookup
4. Remote TMDB match fetch
5. Episode or movie scan build
6. Duplicate reconciliation
7. Preview readiness

Suggested UI surfaces for progress:

1. Global progress banner in the workspace.
2. Per-item progress/status in the roster.
3. Detailed activity panel or expandable status area.
4. Optional activity log tab later if needed.

Required state model:

```text
idle
discovering
matching
scanning
refreshing_cache
ready
warning
failed
cancelled
```

## 2. Queue access control redesign

This is also not optional.

Queue actions should become command-driven and state-derived, not click-handler-derived.

Required target behavior:

1. Disable queue commands when nothing eligible is selected.
2. Explain why queue commands are disabled.
3. Distinguish between not scanned, scanning, review required, duplicate, already queued, and conflict states.
4. Allow adding only items that are genuinely actionable.
5. Surface how many jobs and files are eligible before the user clicks.
6. Keep queue eligibility visible in roster and preview surfaces.

Suggested command states:

```text
enabled
disabled_no_selection
disabled_scanning
disabled_unresolved_review
disabled_conflict
disabled_already_queued
disabled_no_action_needed
```

Suggested UI treatment:

1. Queue button label includes eligible count.
2. Tooltip or inline helper text explains disabled reason.
3. Batch actions show exact queued, skipped, and blocked counts before submission.

## 3. Refresh and cache visibility

Required target behavior based on current product direction:

1. Stale data refreshes automatically in the background.
2. Manual refresh is allowed but throttled.
3. The UI shows when data is stale, refreshing, recently refreshed, or fresh.
4. TV metadata expiry varies by show status.
5. Folder changes force at least subdirectory-level rescan for integrity.

Suggested presentation:

1. Small freshness badges in roster and detail views.
2. Last refresh time in detail or metadata section.
3. Manual refresh action with cooldown messaging.
4. Refresh reason text when data is being refreshed automatically.

## Caching Architecture

### Design Intent

The caching layer exists to minimize redundant TMDB API calls and to persist job history for undo. It does not exist to restore the full GUI session state across restarts. The filesystem is always the source of truth for what media exists and how it is organized. TMDB is the source of truth for metadata. The cache is an optimization layer between the app and TMDB, not a persistence layer for UI state.

### What Gets Cached

1. **TMDB search results and metadata** — stored in `cache_service.py` (SQLite, `~/.plex_renamer/cache.db`). Keyed by namespace + query/ID. Used to avoid re-requesting data that has not expired.

2. **Job history and undo data** — stored in `job_store.py` (SQLite, `~/.plex_renamer/job_queue.db`). Per-job undo data enables reverting completed jobs from previous sessions, provided the relevant files can still be located.

3. **Poster images** — currently cached in-process by the TMDB client. Should be extended to persist poster files to disk so they survive app restarts without re-downloading.

### What Does Not Get Cached

1. **Scan state** — preview items, checked/unchecked flags, selected indices, completeness reports, duplicate labels. These are derived from the filesystem + TMDB data on each scan and should not persist across sessions.

2. **GUI layout state** — panel sizes, scroll positions, collapsed sections. These are ephemeral.

3. **Discovery results** — folder classification and traversal results. These depend on the current filesystem state and must be recomputed on each scan.

### TTL Rules

Governed by `refresh_policy_service.py`:

1. **Released movies**: 30-day TTL. Unlikely to receive metadata updates.
2. **Ended or cancelled TV shows**: 30-day TTL. Metadata is stable.
3. **Returning, in-production, planned, or pilot TV shows**: 12-hour TTL. New episode data is potentially available weekly.
4. **Unknown-status TV shows**: 7-day TTL. Conservative default.
5. **Manual refresh cooldown**: 15 minutes. Prevents TMDB API abuse.

### Startup and Rescan Flow

The correct flow on startup or folder selection:

1. Discovery service walks the filesystem to find media roots.
2. For each discovered root, check `cache_service.py` for a cached TMDB match.
3. If the cache entry is fresh (within TTL), use it without an API call.
4. If the cache entry is stale or missing, query TMDB and store the result.
5. Build all scan state (preview items, duplicates, completeness) from the fresh filesystem scan + TMDB data.
6. Display results. No prior session state influences the outcome.

This ensures that rescans are fast when TMDB data is cached but never show stale filesystem state.

## Migration Phases

## Phase 0: Guardrails and audit

Goal:

Create the architectural seams needed for migration without rewriting the UI immediately.

Deliverables:

1. This migration plan document.
2. A list of backend modules to preserve.
3. A list of tkinter modules that are temporary implementations.
4. A go or no-go checkpoint before writing major GUI3 code.

Exit criteria:

1. Agreement on PySide6 as the target shell.
2. Agreement on preserving the three-panel workflow.
3. Agreement that progress and queue gating are first-class redesign items.

## Phase 1: Backend hardening before UI porting

Goal:

Stabilize the non-UI architecture so the new shell does not inherit the old UI coupling.

### Phase 1 completion status

Phase 1 is substantially complete and has passed static and manual validation. A cleanup pass is required before Phase 2 begins. See the Phase 1 cleanup section below for the specific items.

Completed in the current working tree:

1. Added `plex_renamer/app/` as the new UI-neutral application package.
2. Added structured state models for scan lifecycle, refresh state, queue command state, progress payloads, and queue eligibility.
3. Added `cache_service.py` with persistent SQLite-backed cache storage, stale-state handling, and eviction bounded by both total size and item count.
4. Added `refresh_policy_service.py` with TV-status-aware TTL rules, manual refresh cooldown rules, stale-background-refresh decisions, and changed-subdirectory rescan scope logic.
5. Added `scan_snapshot_service.py` for serializing and restoring `ScanState`, `PreviewItem`, and completeness data. **Note: this service is now slated for retirement in Cleanup 4. Full session state restore caused regressions and exceeds the intended caching scope.**
6. Added `command_gating_service.py` so queue eligibility can be computed outside tkinter click handlers.
7. Updated `engine.py` to expose reusable actionable-item semantics and to let queue job creation accept explicit checked indices.
8. Updated `tmdb.py` with cache snapshot import/export hooks so persistence can be layered on without moving network responsibilities into the UI.
9. Updated `gui/app.py` so current queue submission paths use the centralized command gating service instead of duplicating action-time checks.
10. Wired the persistent cache service into TMDB client bootstrap so cached TMDB state can be restored across sessions.
11. Wired scan snapshot persistence into startup, scan completion, rematch, and shutdown paths for TV single-show, TV batch, and movie sessions. **Note: this wiring will be removed as part of Cleanup 4.**
12. Wired the structured scan progress model into the current tkinter shell so discovery, scan, warning, failure, and ready states now flow through one app-level state object.
13. Added a resilient API key fallback in `keys.py` so the app can start without the optional `keyring` package by falling back to local storage under the app data directory.
14. Cleaned up Phase 1 persistence by tracking the active session snapshot explicitly, rehydrating restored movie metadata/search caches, debouncing repeated snapshot/cache writes via `_request_persistence` / `_flush_pending_persistence`, and consolidating duplicated batch TV scan orchestration in `gui/app.py`.
15. Hardened restored-session behavior by normalizing TMDB cache snapshot keys after JSON reload, healing restored scan-state flags when preview/completeness data already exists, refreshing the TV roster immediately after on-demand scans, and deferring restored TV detail rendering until layout settles so posters scale correctly on first load.

Previously deferred items (now complete):

1. `job_store.py` and `job_executor.py` were audited in Cleanup 7. The `QueueExecutor` listener pattern was confirmed and is now wrapped by `QueueController`.
2. Phase 2 controllers (`MediaController`, `QueueController`) are now complete with 29 tests.
3. Session state is now owned by `MediaController`. `ScanSnapshotService` was retired in Cleanup 4 — no cross-session state restore.

Validation status:

1. Static validation on the touched Python files passed.
2. The startup blocker caused by missing `keyring` was fixed by adding a local fallback path in `keys.py`.
3. Local application testing went well after the final integration pass.
4. Manual validation of restored TV sessions surfaced and then cleared the main remaining Phase 1 restore regressions.
5. Phase 1 should now be treated as complete enough to move into cleanup and then Phase 2, unless new issues are found in broader manual testing.

Deliverables produced:

- `plex_renamer/app/services/cache_service.py`
- `plex_renamer/app/services/refresh_policy_service.py`
- `plex_renamer/app/services/scan_snapshot_service.py` — slated for retirement in Cleanup 4
- `plex_renamer/app/services/command_gating_service.py`
- `plex_renamer/app/services/tv_library_discovery_service.py`
- `plex_renamer/app/services/movie_library_discovery_service.py`

Files modified:

- `plex_renamer/tmdb.py`
- `plex_renamer/engine.py`
- `plex_renamer/gui/app.py`

Exit criteria (met):

1. GUI-neutral scan and refresh state is available.
2. Queue eligibility can be computed without tkinter widgets.
3. Persistent cache behavior is testable independently.

### Phase 1 cleanup — completed

All Phase 1 cleanup items have been resolved. Summary of completed work:

#### Cleanup 1 — Retire `execute_undo` and `undo_log`-based undo — DONE

Unified dual undo paths. `revert_job` in `job_executor.py` is now the sole revert implementation. Parent-directory walking cascade was added to match the old `execute_undo` behavior. `undo_log.py` usage removed.

#### Cleanup 2 — Document mode flag state space — DONE

All valid `(_active_content_mode, _active_library_mode)` combinations documented. This mapping directly informed the `MediaController` session model in Phase 2.

#### Cleanup 3 — Route status messages through `_set_scan_progress` — DONE

Added `_set_status_message()` helper. All direct `status_var.set()` calls replaced.

#### Cleanup 4 — Retire `ScanSnapshotService` — DONE

Removed `scan_snapshot_service.py` (~530 lines removed net). Removed all snapshot persistence calls, debounce logic, and snapshot constants from `gui/app.py`. Removed `SCAN_SNAPSHOT_FILE` from `constants.py`. Startup no longer restores session state; the TMDB cache handles API optimization and the filesystem is always rescanned.

#### Cleanup 5 — Remove dead guard in `_add_batch_to_queue` — DONE

Dead `state.queued` guard removed.

#### Cleanup 6 — Delegate `is_actionable_item` — DONE

`CommandGatingService.is_actionable_item()` now delegates to `item.is_actionable`.

#### Cleanup 7 — Audit `job_executor.py` interface — DONE

`QueueExecutor.add_listener()` confirmed as the correct pattern. `revert_job` confirmed as the entry point. `QueueController` wraps both cleanly.

## Phase 2: Introduce application controllers and view models — COMPLETE

Goal:

Replace direct widget-driven orchestration with application-layer state objects.

### Pre-Phase 2 gate — passed

All Phase 1 cleanup items completed. Pre-Phase 2 design questions answered in the implementation plan (`C:\Users\roxie\.claude\plans\giggly-percolating-clock.md`):

1. **State ownership**: `batch_states`, `active_scan`, `_movie_library_states`, `_movie_preview_items` all moved into `MediaController`. GUI-only state (`check_vars`, `card_positions`, `display_order`, `collapsed_seasons`) stays in the widget.
2. **Mode mapping**: `(TV, TV)` → TV session active; `(MOVIE, MOVIE)` → movie session active; `(MOVIE, None)` → movie detail view; `(TV, None)` → transitional. Controller tracks mode as properties, widget reads to determine layout.
3. **Session restore**: `_restore_last_session_snapshot` was retired in Cleanup 4. Session save/restore in `MediaController` is lightweight dict snapshots for tab-switching, not cross-session persistence.

### Phase 2 completion status

Phase 2 is complete. All deliverables produced and tested.

**Design decisions:**

- No new view model types were needed. Existing types suffice: `ScanState`, `PreviewItem`, `ScanProgress`, `QueueEligibility`, `RenameJob`.
- Controllers fire callbacks from any thread (worker threads during scanning). The widget layer marshals to the main thread (`root.after()` in tkinter, signals in PySide6).
- The listener pattern matches the existing `QueueExecutor` pattern: `add_listener()`, `clear_listeners()`, event-based callbacks.
- The tkinter shell (`gui/app.py`) was NOT modified — controllers are additive. Phase 3 wires the PySide6 shell to controllers; Phase 4 optionally migrates the tkinter shell.

**Deliverables produced:**

1. `plex_renamer/app/controllers/__init__.py` — re-exports domain types (`ScanState`, `PreviewItem`, `RenameJob`, `ScanProgress`, etc.) so the PySide6 shell imports from `app.controllers` without touching `engine.py` directly.
2. `plex_renamer/app/controllers/media_controller.py` (~610 lines) — UI-neutral orchestration of TV and movie scanning sessions. Owns: `batch_states`, `active_scan`, `movie_library_states`, mode flags, scan progress. Methods: `accept_tv_show()`, `start_tv_batch()`, `scan_all_shows()`, `scan_show()`, `start_movie_batch()`, `select_show()`, session save/restore, `sync_queued_states()`.
3. `plex_renamer/app/controllers/queue_controller.py` (~288 lines) — UI-neutral job queue management. Wraps `QueueExecutor` and `JobStore` with structured `BatchQueueResult`. Methods: `add_single_job()`, `add_tv_batch()`, `add_movie_batch()`, `revert_job()`, `start()`, `stop()`, query helpers.
4. `tests/test_media_controller.py` — 17 tests covering init state, accept TV show, select show, TV batch discovery, session save/restore, queued-state sync, and listener notifications.
5. `tests/test_queue_controller.py` — 12 tests covering job submission, duplicate detection, revert, query, count by status, and listener registration.

**View models:** Roster and preview view models were not needed as separate types. `ScanState` already serves as the roster item model, and `PreviewItem` serves as the preview item model. These are re-exported from `app/controllers/__init__.py`.

**Validation:** All 94 tests pass (65 existing + 29 new controller tests).

Exit criteria (met):

1. The future PySide6 shell can bind to application state without importing engine internals directly.
2. The current tkinter shell could theoretically consume the same state for a transition period.

## Phase 2.5: Wire tkinter shell through controllers and fix review findings

Goal:

Eliminate the parallel-implementation problem identified in the code review: the tkinter shell
and the application controllers currently duplicate orchestration logic. Phase 2.5 wires the
tkinter shell through the controllers so behavior changes only need to happen in one place,
reducing drift risk before Phase 3 builds the PySide6 shell.

### Code review findings addressed in Phase 2.5

1. **Bug fix — movie batch checkbox filtering** (High): `add_movie_batch` in both
   `QueueController` and `gui/app.py` did not check `state.checked` before queueing,
   unlike the TV batch path. Every eligible movie was queued regardless of the user's
   roster selection. Fixed in both the controller and the GUI path.

2. **Wire queue submission through QueueController** (Medium-High): `_add_batch_to_queue`,
   `_add_movie_batch_to_queue`, and `_add_single_to_queue` in `gui/app.py` previously
   called `build_rename_job_from_items`/`build_rename_job_from_state` and `job_store.add_job`
   directly. These now delegate to `QueueController.add_single_job()`, `add_tv_batch()`,
   and `add_movie_batch()`. The GUI methods handle only UI feedback (dialogs, status messages,
   badge updates, library panel refresh).

3. **Wire sync/revert/close through controllers** (Medium-High): `_sync_queued_library_states`,
   `_restore_queued_states`, `_on_close`, and revert paths now delegate to controller methods
   instead of accessing `JobStore`/`QueueExecutor` directly.

4. **Clarify session snapshot method names** (Medium): `save_tv_session`/`restore_tv_session`
   and `save_movie_session`/`restore_movie_session` in `MediaController` renamed to
   `snapshot_tv_for_tab_switch`/`restore_tv_from_tab_switch` and
   `snapshot_movie_for_tab_switch`/`restore_movie_from_tab_switch` to make clear these
   are in-memory tab-switch snapshots, not cross-session persistence. The migration plan
   explicitly rejects cross-session state restore (Cleanup 4), and the old method names
   created confusion with reviewers.

5. **Reviewer finding 4 (queue panel split)** was acknowledged but deferred. The tkinter
   `queue_panel.py` still imports `QueueExecutor` and `JobStore` directly. This will be
   resolved naturally in Phase 3 when the PySide6 queue panel is built against
   `QueueController` exclusively. Wiring the tkinter queue panel through the controller
   would require significant widget refactoring for a shell that is being replaced.

### Deliverables

- `gui/app.py` queue submission methods delegate to `QueueController`
- `gui/app.py` sync/close methods delegate to controllers
- `MediaController` session methods renamed for clarity
- Movie batch checkbox bug fixed with regression test
- All existing tests pass

### Exit criteria

1. The tkinter shell no longer calls `build_rename_job_from_items`, `build_rename_job_from_state`,
   or `job_store.add_job` directly for queue submission.
2. Movie batch queueing respects roster checkbox state.
3. Session snapshot methods have unambiguous names.

---

## Phase 3: Build the PySide6 shell skeleton

Goal:

Create the new shell without trying to reach full feature parity immediately.

Deliverables:

1. Main window.
2. Top-level tabs.
3. Split-pane workspace.
4. Basic roster, preview, detail, queue, history, and settings placeholders.
5. Application bootstrap entry point for GUI3.

Suggested new entry point:

- `plex_renamer/gui_qt/app.py`
- optionally `plex_renamer/__main_gui3__.py` during transition

Exit criteria:

1. GUI3 launches reliably.
2. Navigation shell exists.
3. No business logic has been duplicated in widgets.

## Phase 4: Port queue and history first

Goal:

Port the most structured tabs first, because they fit Qt's model/view strengths and create immediate value.

Why first:

1. Queue/history are less canvas-dependent.
2. They validate the app-layer state flow.
3. They are strong candidates for future suite-wide shared infrastructure.

Deliverables:

1. Queue model and view.
2. History model and view.
3. Poster loading integration.
4. Reorder, remove, revert, and start execution flows.
5. Clear status and error presentation.

Note: revert actions in Phase 4 must use `revert_job` exclusively. The `undo_log`/`execute_undo` path will have been retired by the Phase 1 cleanup. There should be no ambiguity about which revert path to call.

Exit criteria:

1. Queue/history are more usable than the tkinter versions.
2. Job state, error state, and action availability are clearer than today.

## Phase 5: Port roster and preview workflow

Goal:

Rebuild the main media workflow while preserving the current mental model.

Deliverables:

1. TV roster panel.
2. Movie roster panel.
3. Preview list with grouping and status rendering.
4. Show/movie folder rename preview in the preview panel. The current tkinter preview only shows per-file renames. The PySide6 preview should show the planned root folder rename (e.g. "naruto.2002.1080p" → "Naruto (2002)") as a header or dedicated card above the file rename list. The data is already available via `build_show_folder_name()` in `parsing.py` — it just needs a display surface before queue time.
5. Unmatched grouping improvements.
6. Review and duplicate action paths.
7. Better progress representation during scan.

Exit criteria:

1. Core scanning and preview workflow is functionally usable.
2. Progress is clearer than in tkinter.
3. Queue eligibility is visibly understandable.

## Phase 6: Port detail, dialogs, and rematch flows

Goal:

Rebuild the rich interaction layer.

Deliverables:

1. Detail pane.
2. Poster and metadata presentation.
3. TV and movie rematch dialogs.
4. Refresh actions with cooldown awareness.
5. Cache freshness display.

Exit criteria:

1. TV and movie manual correction workflows are equal or better than current behavior.
2. Refresh and stale-data logic is visible and understandable.

## Phase 7: Parity review and tkinter retirement decision

Goal:

Decide whether GUI3 is ready to replace the current shell.

Required audit categories:

1. Feature parity.
2. Performance.
3. Trustworthiness of progress feedback.
4. Queue access clarity.
5. Restart and cache behavior.
6. Packaging and startup behavior.

Exit criteria:

1. GUI3 is stable enough for normal use.
2. The current shell is no longer the safer operational choice.

## Current-to-Target File Mapping

### Current files that map to app-layer logic

| Current file | Future home |
| --- | --- |
| `plex_renamer/gui/app.py` | split across `plex_renamer/app/controllers/*` and `plex_renamer/gui_qt/*` |
| `plex_renamer/gui/library_panel.py` | `plex_renamer/gui_qt/widgets/roster_panel.py` plus app-layer view model |
| `plex_renamer/gui/preview_canvas.py` | `plex_renamer/gui_qt/widgets/preview_panel.py` plus app-layer view model |
| `plex_renamer/gui/detail_panel.py` | `plex_renamer/gui_qt/widgets/detail_panel.py` |
| `plex_renamer/gui/queue_panel.py` | `plex_renamer/gui_qt/widgets/queue_panel.py` and `history_panel.py` |
| `plex_renamer/gui/dialogs.py` | `plex_renamer/gui_qt/dialogs/*` |
| `plex_renamer/styles.py` | Qt palette, stylesheet, and reusable widget styling |

### Current files that should mostly stay where they are

| Current file | Direction |
| --- | --- |
| `plex_renamer/parsing.py` | keep |
| `plex_renamer/constants.py` | keep |
| `plex_renamer/job_store.py` | keep, expand carefully |
| `plex_renamer/job_executor.py` | keep; audit interface before Phase 2 |
| `plex_renamer/undo_log.py` | retire during Phase 1 cleanup |
| `plex_renamer/tmdb.py` | keep network responsibilities, trim policy responsibilities |
| `plex_renamer/engine.py` | keep scanners and rename planning, remove `execute_undo` during Phase 1 cleanup |
| `plex_renamer/app/services/cache_service.py` | keep |
| `plex_renamer/app/services/refresh_policy_service.py` | keep |
| `plex_renamer/app/services/command_gating_service.py` | keep |
| `plex_renamer/app/services/tv_library_discovery_service.py` | keep |
| `plex_renamer/app/services/movie_library_discovery_service.py` | keep |
| `plex_renamer/app/services/scan_snapshot_service.py` | retired (Cleanup 4, complete) |
| `plex_renamer/app/controllers/media_controller.py` | keep (Phase 2, complete) |
| `plex_renamer/app/controllers/queue_controller.py` | keep (Phase 2, complete) |

## Risks

## Technical risks

1. Recreating too much logic directly inside Qt widgets.
2. Splitting state incorrectly between core, application, and UI layers.
3. Carrying forward the same queue gating weaknesses under a nicer UI.
4. Mixing persistent cache logic directly into widgets instead of services.
5. ~~Beginning Phase 2 controller work before the `_active_content_mode` / `_active_library_mode` state space is mapped, leading to an incomplete or incorrect session model.~~ (Resolved: state space documented, controllers implemented.)
6. ~~Leaving the dual undo paths active into Phase 4, causing the revert behavior seen in queue history to diverge from the behavior behind `Ctrl+Z`.~~ (Resolved: dual undo paths unified in Cleanup 1.)

## Product risks

1. Losing the current workflow's speed and familiarity.
2. Over-designing GUI3 before hardening the cache and state model.
3. Building a prettier UI that is not more trustworthy.

## Operational risks

1. Shipping GUI3 before restart behavior and queue semantics are trustworthy.
2. Creating two shells that diverge in behavior rather than only in presentation.

## Decision Gates

This project should have explicit stop or proceed checkpoints.

### Gate 1: Before building major Qt screens — PASSED

All criteria met:

1. Phase 1 cleanup items are complete (all 7 cleanups resolved).
2. Application layer design accepted and implemented (Phase 2 complete).
3. Mode state space documented and encoded in `MediaController`.
4. Progress and queue gating are first-class concerns in the controller layer.

### Gate 2: After queue/history port

Proceed only if:

1. Qt already feels structurally better than tkinter for the job views.
2. The application layer is reducing duplication instead of increasing it.

### Gate 3: Before retiring tkinter

Proceed only if:

1. GUI3 is clearer than the old UI in scan progress.
2. GUI3 is clearer than the old UI in queue access control.
3. GUI3 behaves safely under cache hits and stale refreshes. Rescans always re-walk the filesystem; no session state is restored from a prior run.

## Recommended Next Steps

Phases 0, 1, 2, and 2.5 are complete. If work resumes now, the recommended order is:

1. **Phase 3: Build the PySide6 shell skeleton.** Create `plex_renamer/gui_qt/` with main window, top-level tabs, split-pane workspace, and placeholder panels. Wire the bootstrap entry point. Controllers and services are ready to consume.
2. **Phase 4: Port queue and history tabs.** These are the most structured tabs and validate the app-layer state flow through `QueueController`. Use `QTreeView`/`QTableView` with proper item models.
3. **Phase 5: Port roster and preview workflow.** Rebuild the main media workflow using `MediaController` for state and scanning orchestration.

The application layer (`app/controllers/`, `app/services/`, `app/models/`) is complete and the tkinter shell now delegates queue submission through the controllers. The PySide6 shell should import from `plex_renamer.app.controllers` for all domain types and orchestration.

## Audit Checklist

Use this checklist before approving progress to each new phase:

1. Are the backend modules being preserved rather than rewritten unnecessarily?
2. Are progress and queue gating being treated as real redesign items rather than polish tasks?
3. Is a UI-neutral application layer being introduced before large widget work begins?
4. Is GUI3 preserving the current workflow instead of replacing it with a different interaction model?
5. Is cache and refresh logic staying out of the widget layer?
6. Does the plan support future top-level tabs and queue-driven tools without another shell rewrite?
7. Have the Phase 1 cleanup items been completed before Phase 2 begins? **Yes — all 7 cleanups complete.**
8. Is there only one revert/undo path active at any given time? **Yes — `revert_job` only, wrapped by `QueueController`.**
9. Is the session mode state space (`_active_content_mode` / `_active_library_mode`) fully documented before controller design begins? **Yes — encoded in `MediaController` properties.**
10. Is the filesystem always rescanned on startup and folder selection, with the TMDB cache used only as an API optimization — never as a substitute for the current filesystem state? **Yes.**
11. Has `scan_snapshot_service.py` been retired, with no replacement session-restore mechanism introduced? **Yes — retired in Cleanup 4.**

## Recommendation

Proceed with GUI3 on PySide6, but do it as a staged shell migration on top of a stronger application layer.

Do not proceed as a direct tkinter-to-PySide6 file-for-file port.

That would preserve the wrong architecture and carry the current weak points forward under a different toolkit.

Phase 1 cleanup and Phase 2 controller extraction are complete. `scan_snapshot_service.py` has been retired. Mode routing and session state are now owned by `MediaController`. Queue orchestration is owned by `QueueController`. The application layer is ready for the PySide6 shell to consume. The primary structural risk going into Phase 3 is ensuring the PySide6 widgets bind to controller state via listeners rather than duplicating orchestration logic — the controllers were designed specifically to prevent this.
