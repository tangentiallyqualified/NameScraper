# GUI3 PySide6 Migration Plan

Canonical note: this is the authoritative tracked GUI3 migration plan for the repository. Temporary audit notes, drafts, and scratch migration writeups should go under `docs/local/` instead of being created as parallel top-level plan files.

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
4. Explicit checkbox-driven bulk selection instead of overloading row selection.
5. Left-side detail panel plus right-side job list so operational preview stays visible.
6. Burst-safe notification behavior that aggregates fast success events.

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

Required selection-model treatment:

1. Keep inspection focus separate from bulk-action selection.
2. Use explicit checkboxes for roster batch selection, queue selection, and history selection.
3. Add a tri-state master checkbox at the top of each selectable list.
4. Persist checked state independently from the currently focused row.
5. Treat row click as navigation and preview, not implicit inclusion in bulk actions.

## 2.5 Notification aggregation redesign

This is required for operational trust, not optional polish.

Current problem to avoid:

1. Fast queue runs can emit several completion toasts in the same moment.
2. Limiting the number of simultaneous toasts is not enough if the first few still flash independently.
3. Success feedback becomes noisy exactly when the app is working well.

Required target behavior:

1. Keep failed-job notifications itemized and persistent.
2. Aggregate rapid success events into a short rolling summary.
3. Prefer one queue-run summary toast plus failure exceptions over one success toast per job.
4. Use a short debounce window so adjacent completions collapse naturally.
5. Never let success notifications obscure actionable failure notifications.

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
6. Checkbox-based bulk selection in queue and history with tri-state header checkbox.
7. Two-panel queue/history layout with persistent job detail preview.
8. Right-click actions, open-folder actions, and full rename preview for selected jobs.
9. Aggregated success notifications with per-job failure surfacing.

Note: revert actions in Phase 4 must use `revert_job` exclusively. The `undo_log`/`execute_undo` path will have been retired by the Phase 1 cleanup. There should be no ambiguity about which revert path to call.

Exit criteria:

1. Queue/history are more usable than the tkinter versions.
2. Job state, error state, and action availability are clearer than today.
3. Bulk actions no longer depend on ambiguous table row selection.

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
8. Checkbox-based roster selection with tri-state master checkbox above the list.
9. Action bar and queue wording aligned to checked-state workflow rather than select-all/select-none buttons.
10. Plex Ready visibility fixes via grouping, filtering, and collapse behavior rather than a new tab.

Exit criteria:

1. Core scanning and preview workflow is functionally usable.
2. Progress is clearer than in tkinter.
3. Queue eligibility is visibly understandable.
4. Bulk selection in the roster is explicit and consistent with queue/history.

## Phase 6: Port detail, dialogs, and rematch flows

Goal:

Rebuild the rich interaction layer.

Deliverables:

1. Detail pane.
2. Poster and metadata presentation.
3. TV and movie rematch dialogs.
4. Refresh actions with cooldown awareness.
5. Cache freshness display.
6. Episode still wiring for TV episode detail and preview-related poster surfaces.
7. Post-rematch state updates that immediately unblock queueing when review is resolved.
8. Threshold-driven confidence presentation that matches actual matching behavior.

Exit criteria:

1. TV and movie manual correction workflows are equal or better than current behavior.
2. Refresh and stale-data logic is visible and understandable.
3. Settings that affect review and confidence behavior are no longer misleading.

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

## Priority Reset — April 1, 2026

The next implementation pass should be sequenced by operational trust first, then by interaction-model cleanup, then by visual polish.

### Priority 1: Fix trust-breaking behavior

1. Make the user-defined confidence threshold actually drive match-review behavior and related confidence presentation.
2. Fix rematch approval so resolved items leave `Needs Review` immediately and can be queued without an extra hidden step.
3. Aggregate rapid success notifications during queue execution; keep failures explicit and actionable.
4. Prefer filtering and collapse rules for `Plex Ready` over adding more top-level navigation.

### Priority 2: Unify checkbox-driven selection UX

1. Convert the batch roster to explicit checkbox selection with a tri-state master checkbox above the list.
2. Convert queue and history bulk actions to the same checkbox model.
3. Separate row focus from bulk-action membership everywhere.
4. Move bulk-action copy and placement to reflect checked-state workflow.

### Priority 3: Strengthen queue and history operational surfaces

1. Move job detail to a persistent side panel and keep the list taller.
2. Add right-click menus, whole-row hover, and open-folder actions.
3. Expand job detail to show folder rename plans and per-operation summaries.

### Priority 4: Improve media clarity

1. Wire episode stills into TV detail and preview-adjacent poster surfaces.
2. Replace ambiguous confidence-only cues with threshold-aware labels and clearer status language.
3. Add stronger placeholder artwork and sharper roster poster rendering.

### Priority 5: Deepen correction workflows

1. Support per-file fixes inside TV series.
2. Allow unmatched files in TV folders to be matched to specific episodes.
3. Add better duplicate resolution paths, including keep-both or second-copy handling where safe.

## Progress Update — April 1, 2026 (Night)

The current `dev/GUI3` working tree has completed or substantially completed the first four priorities from the April 1 reset.

Delivered in this pass:

1. **Priority 1 is complete**: the confidence threshold now drives live review semantics, manual rematch approval clears `Needs Review` immediately, and rapid success notifications aggregate during queue runs.
2. **Priority 2 is complete**: roster, queue, and history now use explicit checkbox-driven bulk selection with tri-state master checkboxes and a clean separation between focused row and bulk-action membership.
3. **Priority 3 is substantially complete**: queue and history now use a persistent split layout with job detail at the left, list operations at the right, right-click operational menus, open-folder actions, richer rename preview, and corrected queue/history panel framing.
4. **Priority 4 is largely complete**: TV detail now prefers episode still artwork when available, match language is threshold-aware in both roster and detail, roster posters use sharper cached pixmaps, and placeholder artwork is now intentional rather than raw fallback text. Episode selections in detail also use a shorter landscape artwork frame to leave more room for context.

Remaining recommended work:

1. **Priority 5** remains the main unfinished implementation block.
2. Media-clarity follow-up is now polish-level rather than trust-level: preview-adjacent still treatment, poster-hero styling, and any remaining artwork consistency cleanup.
3. The `MatchPickerDialog` UI-thread blocking bug remains a separate retirement blocker called out in the Phase 7 audit.

Validation completed during this pass:

1. Targeted Qt smoke coverage passed for the queue/history split shell, context actions, folder actions, and richer job detail preview.
2. Targeted Qt smoke coverage passed for threshold-aware match language, episode-still detail artwork, landscape episode placeholders, and roster placeholder thumbnails.

### Phase mapping for the next pass

1. Start with Priority 1 items across current Phase 4-6 surfaces.
2. Fold Priority 2 into Phase 4 for queue/history and Phase 5 for roster.
3. Treat Priority 3 as the completion bar for Phase 4 usability.
4. Treat Priority 4 as targeted Phase 5-6 polish only after trust and selection are fixed.
5. Defer Priority 5 until the selection and rematch foundations are stable.

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

### March 29 2026 progress update

The recent stabilization and parity pass moved Phase 7 materially forward, but did not yet clear the final retirement gate.

Completed in this pass:

1. Stabilized the Qt media workspace around selection churn, row-host rendering, preview/detail flicker, and transient popup windows during TV navigation.
2. Tightened the left roster card layout, removed horizontal scroll pressure, and changed review cards so alternate suggestions swap cleanly into an accept/cancel confirmation state.
3. Ensured TV batch discovery shows the ready workspace before automatic episode scanning continues, so reviewable TV matches are visible instead of being hidden behind the scanning screen.
4. Restored TV suggestion parity with movies by keeping the top-ranked alternate matches for low-confidence TV results even when their scores fall below the old hard threshold.
5. Hardened TV batch discovery for release-style show folders whose names contain tokens like `S01` while still containing real child season directories, fixing cases such as Akiba Maid War style folders.
6. Fixed the Qt TV loading flow so batch TV scans no longer expose the ready workspace too early and then flip state underneath the user.
7. Corrected Qt roster grouping so folders that still need rename work remain under `Matched` instead of incorrectly switching to `Plex Ready` after preview load.
8. Fixed stacked toast layout sizing so wrapped multi-toast messages no longer clip in the Qt shell.
9. Expanded TMDB session pool sizing to reduce `urllib3` connection-pool warnings during concurrent poster fetches without changing the existing request-rate limiter.
10. Persisted poster images, source images, TMDB metadata snapshots, and per-job `poster_path` values so queue/history poster views can survive restarts without redownloading artwork.
11. Added both lazy and one-shot startup backfill of missing job poster paths in Qt using cached TMDB metadata only, preserving first-run safety while healing older job records.

Validation completed for this pass:

1. `tests/test_scan_improvements.py`
2. `tests/test_media_controller.py`
3. `tests/test_haikyuu_matching.py`
4. `tests/test_jojo_matching.py`
5. `tests/test_gui_qt_smoke.py`
6. `tests/test_queue_controller.py`
7. `tests/test_tmdb.py`
8. Focused regressions for the latest cache/startup pass: `41 passed`
9. Result across the earlier TV parity/discovery sweep: `79 passed`

## Phase 8: Code review — performance, correctness, and polish

Date: 2026-03-29

This phase addresses findings from the comprehensive code review performed against the Phase 7 parity audit, the migration plan, and the UI design document. Issues are grouped by priority.

### 8.1 — Fix flickering transparent popups (High) ✅

**Root cause (multi-layered):**
1. Background threads were creating `QPixmap` and `PIL.ImageQt.ImageQt` (a `QImage` subclass) off the main thread, which touches Qt's platform layer and spawns transient native windows on Windows.
2. Qt's own platform integration creates short-lived ToolTip/SplashScreen-flagged helper windows during heavy widget operations (style cascades, QListWidget rebuilds) on the main thread.
3. The original event filter used `obj.hide()` on Show events, but hide() itself triggers a native message and the show→hide sequence is visible as flicker.

**Fix (applied):**
- Eliminated all Qt object creation from background threads across three files. Worker threads now pass raw `(bytes, width, height)` tuples through signals; `QImage`/`QPixmap` conversion happens on the main thread only.
- Restored the transient window event filter with a non-destructive strategy: `setWindowOpacity(0)` (synchronous on Windows via `SetLayeredWindowAttributes`) instead of hide/close/delete. This makes transient windows invisible before the compositor renders the next frame without disrupting Qt's internal lifecycle.
- Added `QMainWindow` to the filter exclusion list to prevent false positives.
- Removed unnecessary `setToolTip()` calls from recent-folder menu actions.
- Fixed `QFont::setPixelSize: Pixel size <= 0` warnings from `font-size: 0px` in theme QSS.
- Fixed `RuntimeError: Signal source has been deleted` crash in poster backfill thread.

**Files:** `plex_renamer/gui_qt/app.py`, `plex_renamer/gui_qt/widgets/media_workspace.py`, `plex_renamer/gui_qt/widgets/media_detail_panel.py`, `plex_renamer/gui_qt/widgets/job_detail_panel.py`, `plex_renamer/gui_qt/main_window.py`, `plex_renamer/gui_qt/resources/theme.qss`

**Follow-up (2026-03-29):** A residual tiny-window flicker remained during TV roster switching even after the broader transient-window suppression work. Debug logging on the Qt popup filter showed the flashing widget was our own `_ToggleSwitch` at `42x24`, not a separate platform helper window. The switches in roster and preview rows were being constructed without a parent, allowing them to exist briefly as top-level windows before layout attachment. The fix was to parent `_ToggleSwitch` at construction time in both row widgets and add smoke-test assertions that these controls are not windows. Logging bootstrap in `plex_renamer/__main__.py` was also updated so `PLEX_RENAMER_DEBUG_TRANSIENT_WINDOWS=1` raises startup logging to `DEBUG` automatically when diagnostics are needed.

### 8.2 — Eliminate full roster rebuilds on every queue event (High) ✅

**Problem:** `MainWindow._on_queue_changed()` calls `refresh_from_controller()` on *both* media workspaces unconditionally.

**Fix (applied):** Only the active visible workspace refreshes on queue events. The off-screen workspace sets a deferred refresh flag (`_tv_needs_queue_refresh` / `_movie_needs_queue_refresh`) which is consumed when the user switches tabs.

**Files:** `plex_renamer/gui_qt/main_window.py`

### 8.3 — Deduplicate poster thread spawning (High) ✅

**Problem:** `_request_roster_poster()` spawns duplicate threads for the same poster when `refresh_from_controller()` is called repeatedly.

**Fix (applied):** Added `_poster_inflight: set[tuple[str, int]]` to `MediaWorkspace`. Requests are skipped when the key is already in-flight; the key is discarded in a `finally` block in the worker thread.

**Files:** `plex_renamer/gui_qt/widgets/media_workspace.py`

### 8.4 — Replace per-widget inline setStyleSheet with QSS properties (Medium) ✅

**Problem:** Every `_RosterRowWidget._apply_style()` and `_PreviewRowWidget._apply_style()` calls `setStyleSheet()` with hardcoded hex colors. Per-widget `setStyleSheet()` forces a full style recalculation cascade. With 50+ roster items and 200+ preview items, this is expensive on every rebuild.

**Fix (applied):** Converted roster and preview row widgets to use QSS classes and dynamic properties instead of rebuilding inline per-widget stylesheets on every state change. Row cards now expose properties like `band`, `selectionState`, and pill `tone`, and the theme owns the actual colors/borders via selectors in `theme.qss`. Added smoke assertions that these widgets no longer carry local inline stylesheets.

**Files:** `plex_renamer/gui_qt/widgets/media_workspace.py`, `plex_renamer/gui_qt/resources/theme.qss`

### 8.5 — Cap metadata detail cache growth (Medium) ✅

**Problem:** `MediaDetailPanel._metadata_cache` grows unbounded over a session. Each unique token stores a dict + QPixmap. No eviction policy exists.

**Fix (applied):** Replaced the unbounded metadata cache in `MediaDetailPanel` with a bounded LRU (`OrderedDict`) capped at 64 entries. Added an explicit `clear_metadata_cache()` hook and wired it into workspace transitions to empty/scanning states so new folder/scan sessions do not retain stale metadata indefinitely. Added a smoke test covering eviction and explicit clearing.

**Files:** `plex_renamer/gui_qt/widgets/media_detail_panel.py`

### 8.6 — Fix thread-unsafe QTimer.singleShot in settings API test (Medium) ✅

**Problem:** `SettingsTab._on_test_key()` marshals results from a background thread via `QTimer.singleShot(0, lambda)`. If the widget is destroyed between thread completion and timer execution, this crashes.

**Fix (applied):** Replaced the background-thread `QTimer.singleShot()` callback in `SettingsTab._on_test_key()` with a dedicated `QObject` signal bridge owned by the widget. The worker thread now emits a result signal back to the UI thread and safely no-ops if the widget has already been destroyed. Added a smoke test that drives the async TMDB key test path and verifies the UI is updated via the bridge.

**Files:** `plex_renamer/gui_qt/widgets/settings_tab.py`

### 8.7 — Minor correctness and cleanup (Low) ✅

1. ~~**Duplicate call:** `_fix_match_btn.setEnabled(False)` called twice at `media_workspace.py:330-331`.~~ Fixed.
2. ~~**Dead branch:** `_preview_target_text()` returns the same string for both compact and non-compact modes (`media_workspace.py:1372-1376`).~~ Fixed.
3. ~~**Duplicate utility:** `_clamped_percent()` is defined identically in both `media_workspace.py` and `media_detail_panel.py`. Extract to a shared module.~~ Fixed via shared Qt formatting helper.
4. ~~**Stale labels:** Cache section buttons in `settings_tab.py:235-244` still say "not yet wired" and "Phase 4". Either wire them or remove the placeholder text.~~ Fixed.
5. ~~**Muted confidence color:** `_confidence_fill_color(score)` does not accept a `ScanState`, so queued/scanning/duplicate items show score-based colors instead of muted gray.~~ Fixed.

**Files:** `plex_renamer/gui_qt/widgets/media_workspace.py`, `plex_renamer/gui_qt/widgets/media_detail_panel.py`, `plex_renamer/gui_qt/widgets/settings_tab.py`, `plex_renamer/gui_qt/widgets/_formatting.py`

## Recommended Next Steps

Phases 0 through 8 are now effectively complete on `dev/GUI3`. The recommended work order for reaching a tkinter retirement decision is:

### Phase 9 — Pre-retirement cleanup and polish

The following items were identified in a full code review on 2026-03-30. They are organized by priority relative to a tkinter retirement decision.

#### ~~9.1 — MatchPickerDialog TMDB search blocks the UI thread (Bug — High)~~ Fixed

**Problem:** `MatchPickerDialog._run_search()` calls `self._search_callback(query, ...)` synchronously on the main thread. This performs an HTTP request to TMDB that freezes the UI for 1-5 seconds.

**Fix:** Move the search call to a worker thread with a `QObject` signal bridge, matching the pattern used in `SettingsTab._on_test_key()` and `MediaDetailPanel._build_payload()`. Show a loading state on the result list while the search is in flight.

**Files:** `plex_renamer/gui_qt/widgets/match_picker_dialog.py`

#### ~~9.2 — Dead code cleanup (Cleanup — Medium)~~ Fixed

**Problem:** Eight functions/methods in `media_workspace.py` are defined but never called. They are leftovers from earlier rendering approaches that were replaced by custom row widgets.

Dead functions:
1. `MediaWorkspace._format_roster_text()` (line 829)
2. `MediaWorkspace._state_tooltip()` (line 855)
3. `MediaWorkspace._state_color()` (line 863)
4. `MediaWorkspace._format_preview_text()` (line 866)
5. `MediaWorkspace._preview_tooltip()` (line 881)
6. `_is_movie_state()` (line 1301)
7. `_confidence_bar_stylesheet()` (line 1363)
8. `_preview_color()` (line 1483)

**Fix:** Delete all eight. ~60 lines of dead code.

**Files:** `plex_renamer/gui_qt/widgets/media_workspace.py`

#### ~~9.3 — Extract shared base class for QueueTab and HistoryTab (Refactor — Medium)~~ Fixed

**Problem:** `QueueTab` and `HistoryTab` share ~70% identical code: `select_job()`, `_selected_jobs()`, `_apply_filter()`, `_select_all()`, `_clear_selection()`, toolbar layout structure, and table setup. This duplication makes it easy for fixes in one tab to be missed in the other.

**Fix:** Extract a `_JobListTab` base class providing the table, model/proxy, selection helpers, filter control, and toolbar skeleton. Each subclass adds its specific actions and filter sets.

**Files:** `plex_renamer/gui_qt/widgets/queue_tab.py`, `plex_renamer/gui_qt/widgets/history_tab.py`

#### ~~9.4 — Consolidate PIL-to-QPixmap conversion utilities (Refactor — Medium)~~ Fixed

**Problem:** The PIL → raw bytes → QPixmap conversion pipeline is implemented in three separate places:
- `media_workspace.py` (`_pil_to_raw`, `_raw_to_pixmap`)
- `media_detail_panel.py` (`_build_payload`, inline)
- `job_detail_panel.py` (`_request_poster._worker`, inline)

**Fix:** Extract to a shared `_image_utils.py` module in `gui_qt/widgets/` with `pil_to_raw()` and `raw_to_pixmap()` functions.

**Files:** `plex_renamer/gui_qt/widgets/media_workspace.py`, `plex_renamer/gui_qt/widgets/media_detail_panel.py`, `plex_renamer/gui_qt/widgets/job_detail_panel.py`

#### ~~9.5 — Migrate remaining inline setStyleSheet calls to QSS (Polish — Medium)~~ Fixed

**Problem:** Phase 8.4 converted roster/preview row widgets to QSS properties, but inline `setStyleSheet()` calls remain in:
- `settings_tab.py` — 8 calls for API key status colors
- `scan_progress.py` — 6 calls for checklist icon colors
- `empty_state.py` — 3 calls for label styling
- `history_tab.py` — revert banner border
- `media_workspace.py` `_ActionBar` — background and border

These bypass the theme and make restyling harder.

**Fix:** Convert to QSS dynamic properties (e.g., `tone="success"` / `tone="error"` on the key status label, `phase="active"` / `phase="done"` on checklist icons). Add corresponding selectors to `theme.qss`.

**Files:** `plex_renamer/gui_qt/widgets/settings_tab.py`, `plex_renamer/gui_qt/widgets/scan_progress.py`, `plex_renamer/gui_qt/widgets/empty_state.py`, `plex_renamer/gui_qt/widgets/history_tab.py`, `plex_renamer/gui_qt/widgets/media_workspace.py`, `plex_renamer/gui_qt/resources/theme.qss`

#### ~~9.6 — Cap roster poster cache size (Optimization — Low)~~ Fixed

**Problem:** `MediaWorkspace._roster_poster_cache` is an unbounded `dict`. For large libraries, this can accumulate significant memory. The detail panel's metadata cache was already capped at 64 entries in Phase 8.5, but the roster poster cache was not.

**Fix:** Replace with an LRU-bounded cache (e.g., `OrderedDict` with eviction at 128 entries).

**Files:** `plex_renamer/gui_qt/widgets/media_workspace.py`

#### ~~9.7 — Replace full roster rebuilds with incremental updates (Optimization — Low)~~ Fixed

**Problem:** `refresh_from_controller()` clears the entire `QListWidget` and recreates all items on every queue state change. For libraries with many shows, this causes visible flicker and unnecessary widget churn.

**Fix:** Compare the current roster state to the controller state and update only changed items (status pill, checked state, confidence bar) without destroying and recreating the entire list.

**Files:** `plex_renamer/gui_qt/widgets/media_workspace.py`

#### ~~9.8 — Cap toast stack depth (Polish — Low)~~ Fixed

**Problem:** If many jobs fail quickly, error toasts (`duration_ms=0`) stack indefinitely with no limit. They persist until manually dismissed and can overflow the visible area.

**Fix:** Cap visible toasts at 3-4. When the limit is reached, collapse excess into a summary toast (e.g., "3 more notifications") or auto-dismiss the oldest non-error toast.

**Files:** `plex_renamer/gui_qt/widgets/toast_manager.py`

#### ~~9.9 — Wire or hide non-functional settings sections (Polish — Low)~~ Fixed

**Problem:** The Cache section's "Clear TMDB Cache" and "Clear All Data" buttons are permanently disabled. The Advanced section's log level combo and "Export Diagnostic Log" button have no connected signals. These look broken to users.

**Fix:** Either wire them to real functionality or hide the sections behind a feature flag / remove them until they're implemented.

**Files:** `plex_renamer/gui_qt/widgets/settings_tab.py`

#### ~~9.10 — Minor correctness issues (Cleanup — Low)~~ Fixed

1. **Duplicate import:** `QMessageBox` is imported at the top of `main_window.py` (line 23) and again locally in `_on_about()` (line 710). Remove the local import.
2. **Missing blank line:** `_DetailBridge` class definition in `media_detail_panel.py` (line 30) starts immediately after `_format_runtime()` with no PEP 8 blank line separator.
3. **Fragile movie detection:** `media_detail_panel.py:244` uses `state.media_info.get("title")` as a heuristic for movie vs. TV. Consider using an explicit `_media_type` field consistently.
4. **`_format_rating(0.0)` returns empty string:** `if not vote_average` is falsy for 0.0. Should be `if vote_average is None`.

**Files:** `plex_renamer/gui_qt/main_window.py`, `plex_renamer/gui_qt/widgets/media_detail_panel.py`

### GUI flow improvements (Post-Phase 9)

These are UX refinements to address after the cleanup items above. They do not block tkinter retirement but should be prioritized for the Qt shell's post-parity improvement phase.

1. **Disambiguate the two "Add to Queue" buttons.** Fixed. The preview header button now uses a single-item label and the bottom action bar uses a checked-items batch label.

2. **Add keyboard shortcut for queueing.** Fixed. Ctrl+Q now queues the selected item in the active media workspace and Ctrl+Shift+Q queues all checked items in that workspace.

3. **Restructure Queue Tab toolbar.** Fixed. Navigation moved into the top toolbar and the actions are grouped with spacing so the queue controls are less cramped.

4. **Improve cancelled/failed scan feedback.** Fixed. Empty-result cancelled and failed scans now surface a toast so the empty state does not appear unexplained.

5. **Consider revert banner as overlay.** The history tab's revert confirmation banner pushes the table down. An overlay or toast-style confirmation would avoid layout shift.

The application layer (`app/controllers/`, `app/services/`, `app/models/`) is complete and the tkinter shell now delegates queue submission through the controllers. The PySide6 shell should import from `plex_renamer.app.controllers` for all domain types and orchestration.

### Phase 10 — Post-parity polish and workflow improvements

Date added: 2026-04-02

Phase 9 cleanup is complete and the Qt shell is at functional parity with tkinter. Phase 10 addresses the remaining workflow gaps, visual polish, and code quality improvements that make the Qt shell feel like a genuine upgrade rather than a reskin.

Items are organized by priority. Higher-priority items have the most user-facing impact relative to effort.

#### ~~10.1 — Keyboard shortcuts for core workflows (Workflow — High)~~ Implemented

**Problem:** The design document specifies several keyboard shortcuts that are still unimplemented. These are the most common user actions after visual review, and keyboard-driven users currently must reach for the mouse.

**Missing shortcuts:**
- `Space` — toggle checkbox on focused roster/queue/history row
- `Escape` — cancel current scan or dismiss topmost toast
- `Delete` — remove selected pending job from queue
- `Enter` — execute selected pending queue job
- `F5` — force rematch on selected roster item

`Space` and `Escape` are the highest-value additions: `Space` enables keyboard-driven batch selection, and `Escape` provides the expected safety valve for scan cancellation without clicking.

**Files:** `plex_renamer/gui_qt/widgets/media_workspace.py`, `plex_renamer/gui_qt/main_window.py`, `plex_renamer/gui_qt/widgets/queue_tab.py`, `plex_renamer/gui_qt/widgets/toast_manager.py`

#### ~~10.2 — Queue eligibility tooltips on disabled buttons (Workflow — High)~~ Implemented

**Problem:** When the "Queue This Show" or "Queue N Checked" button is disabled, there is no explanation. Users must infer the reason from status badges scattered across the roster. The design document calls for explicit "why can't I queue this?" feedback.

**Fix:** Pull reasons from `CommandGatingService` and set a tooltip on the disabled queue button. Example: "2 items still scanning, 1 needs review." This is a small change with outsized clarity impact.

**Files:** `plex_renamer/gui_qt/widgets/media_workspace.py`, `plex_renamer/app/services/command_gating_service.py`

#### ~~10.3 — Batch queue pre-flight summary for skipped items (Workflow — High)~~ Implemented

**Problem:** When "Queue N Checked" is clicked, ineligible items are silently skipped. The success toast reports counts after the fact but the user does not learn which items were skipped or why before committing.

**Fix:** Show a pre-flight confirmation when any checked items will be skipped: "Queueing 5 of 8 checked — 2 need review, 1 already queued. Proceed?" This can be an inline banner or a lightweight dialog. Skip the confirmation when all checked items are eligible.

**Files:** `plex_renamer/gui_qt/widgets/media_workspace.py`

#### ~~10.4 — Alternate match discovery indicator on roster cards (Workflow — Medium)~~ Implemented

**Problem:** Alternate matches are only visible after clicking into a needs-review roster row. There is no signal on the roster card itself that alternatives exist. Users must click into every review item to discover whether alternatives are available.

**Fix:** Add a small indicator on roster cards that have alternate matches — e.g. "2 alternatives" caption text or a subtle icon. This makes review items self-documenting.

**Files:** `plex_renamer/gui_qt/widgets/media_workspace.py`

#### ~~10.5 — Poster hero blur backdrop in detail panel (Visual — Medium)~~ Implemented

**Problem:** The design document calls for a blurred, darkened poster backdrop behind the detail panel metadata area (similar to Plex or Jellyfin). This is the single highest-visual-impact polish item and would make the detail panel feel like a media application rather than a data table.

**Implementation:** Use `QGraphicsBlurEffect` on a scaled poster copy, darkened to ~30% opacity, behind the metadata area. Fall back to solid `bg_mid` gradient when no poster is available.

**Files:** `plex_renamer/gui_qt/widgets/media_detail_panel.py`, `plex_renamer/gui_qt/resources/theme.qss`

#### ~~10.6 — Sticky season headers with progress bars in preview (Visual — Medium)~~ Implemented

**Problem:** The design document specifies that season headers should pin to the top of the preview scroll area when scrolling past, with a thin progress bar showing the season match ratio. Currently headers are static group labels with no progress indicator.

**Files:** `plex_renamer/gui_qt/widgets/media_workspace.py`

#### ~~10.7 — Tab badge scale-pulse animation (Visual — Low)~~ Implemented

**Problem:** Tab badges update their count but do not animate on change. The design document calls for a brief scale-pulse (200ms to 1.15x and back) when the count changes.

**Fix:** Add a `QPropertyAnimation` on scale transform to `TabBadge.set_count()` when the new count differs from the old count.

**Files:** `plex_renamer/gui_qt/widgets/tab_badge.py`

#### ~~10.8 — Toast auto-dismiss progress bar (Visual — Low)~~ Already implemented

**Problem:** Toasts auto-dismiss after a timer, but there is no visual indicator of remaining time. The design document calls for a thin depleting progress bar at the toast bottom.

**Fix:** Add a 2px-height progress bar to toast widgets that animates from full to empty over the dismiss duration.

**Files:** `plex_renamer/gui_qt/widgets/toast_manager.py`

#### 10.9 — Job completion and failure transition animations (Visual — Low)

**Problem:** Queue job state transitions (pending → running → completed/failed) are instant. The design document calls for a brief color tint (200ms green fade on completion, red on failure) before settling to the final state.

**Fix:** Use `QPropertyAnimation` on background color for job row widgets during state transitions.

**Files:** `plex_renamer/gui_qt/widgets/_job_list_tab.py`, `plex_renamer/gui_qt/resources/theme.qss`

#### 10.10 — Poster loading placeholder shimmer (Visual — Low)

**Problem:** While roster posters and detail panel artwork load, the space is empty. A shimmer placeholder or small spinner would signal that content is coming, not missing.

**Files:** `plex_renamer/gui_qt/widgets/media_workspace.py`, `plex_renamer/gui_qt/widgets/media_detail_panel.py`

#### ~~10.11 — Spacing normalization to 4px grid (Visual — Low)~~ Implemented

**Problem:** The theme establishes a 4px base grid, but some widget padding values are inconsistent (e.g. 10px preview row padding vs 8px roster row padding). A normalization pass would tighten the visual rhythm.

**Files:** `plex_renamer/gui_qt/widgets/media_workspace.py`, `plex_renamer/gui_qt/resources/theme.qss`

#### ~~10.12 — Empty state icon replacement (Visual — Low)~~ Implemented

**Problem:** The empty state folder picker uses an emoji instead of a proper icon. The design document calls for a Lucide `folder-open` icon at 64px. The emoji looks out of place in an otherwise icon-driven UI.

**Files:** `plex_renamer/gui_qt/widgets/empty_state.py`

#### 10.13 — Confirmation for large destructive batch operations (Workflow — Low)

**Problem:** Removing or clearing large batches (10+ jobs) in queue/history proceeds without extra confirmation. Only revert has an inline banner.

**Fix:** Add confirmation for bulk remove and bulk clear when the selection exceeds a threshold.

**Files:** `plex_renamer/gui_qt/widgets/queue_tab.py`, `plex_renamer/gui_qt/widgets/history_tab.py`

#### 10.14 — Refactor media_workspace.py (Code Quality — Medium)

**Problem:** `media_workspace.py` is 1,777 lines and carries roster building, preview rendering, poster caching, checkbox sync, detail rendering, and alternate-match flows. This accumulation makes it hard to test, navigate, or modify any single concern without risk of side effects.

**Recommended split:**
1. Extract `_RosterPanel` — roster list, grouping, poster loading, checkbox sync
2. Extract `_PreviewPanel` — season groups, file cards, companion file rendering
3. Keep `MediaWorkspace` as a thin coordinator binding the panels to `MediaController`

This is not urgent but becomes increasingly important as more features (sticky headers, animations, deeper correction workflows) are added to these surfaces.

**Files:** `plex_renamer/gui_qt/widgets/media_workspace.py`

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
