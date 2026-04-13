# Code Review & Refactor Plan

Last reviewed: 2026-04-12

Verification snapshot:
- Full suite: 377 passed in 8.82s via `python -m pytest`
- Qt smoke: 85 passed in 5.41s via [scripts/test-smoke.cmd](../scripts/test-smoke.cmd)
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

## Current Assessment

### What changed

- The original GUI/controller hotspots have been reduced substantially through coordinators and helper modules.
- The remaining structural debt is now concentrated in engine scanning/orchestration and the queue persistence/execution path.
- File size is no longer the main signal by itself. The stronger signal is responsibility spread: files that still combine orchestration, heuristics, state mutation, and I/O should move first.

### Large-file snapshot worth tracking

- [plex_renamer/engine/_batch_orchestrators.py](../plex_renamer/engine/_batch_orchestrators.py) — 920 lines
- [plex_renamer/engine/_tv_scanner.py](../plex_renamer/engine/_tv_scanner.py) — 746 lines
- [plex_renamer/job_store.py](../plex_renamer/job_store.py) — 658 lines
- [plex_renamer/job_executor.py](../plex_renamer/job_executor.py) — 567 lines
- [plex_renamer/gui_qt/widgets/_workspace_widgets.py](../plex_renamer/gui_qt/widgets/_workspace_widgets.py) — 492 lines
- [plex_renamer/gui_qt/widgets/job_detail_panel.py](../plex_renamer/gui_qt/widgets/job_detail_panel.py) — 460 lines
- [plex_renamer/app/services/tv_library_discovery_service.py](../plex_renamer/app/services/tv_library_discovery_service.py) — 425 lines
- [plex_renamer/gui_qt/widgets/_media_workspace_actions.py](../plex_renamer/gui_qt/widgets/_media_workspace_actions.py) — 389 lines
- [plex_renamer/app/controllers/media_controller.py](../plex_renamer/app/controllers/media_controller.py) — 369 lines
- [plex_renamer/gui_qt/main_window.py](../plex_renamer/gui_qt/main_window.py) — 295 lines
- [plex_renamer/gui_qt/widgets/media_workspace.py](../plex_renamer/gui_qt/widgets/media_workspace.py) — 281 lines

## Current High-Value Targets

### 1. Split batch orchestration policy from batch workflow

[plex_renamer/engine/_batch_orchestrators.py](../plex_renamer/engine/_batch_orchestrators.py) is the clearest current hotspot. It mixes filesystem discovery, TMDB matching, confidence/tiebreak policy, duplicate labeling, season merging, and batch scan workflow in one place.

**Why now:**
- The file still owns too many policy decisions for one module.
- Duplicate handling and season merging are subtle, high-risk behaviors that deserve isolated tests and smaller review surfaces.
- This is now the main place where engine complexity remains concentrated after the earlier engine package split.

**Refactor direction:**
- Extract duplicate labeling logic into a focused helper or strategy module.
- Extract season merge/consolidation logic into its own module.
- Extract match ranking and tiebreak policy into a smaller scoring/policy helper.
- Keep the public `BatchTVOrchestrator` and `BatchMovieOrchestrator` entry points stable while moving internals out.

### 2. Break TV preview building into smaller builders

[plex_renamer/engine/_tv_scanner.py](../plex_renamer/engine/_tv_scanner.py) still combines mismatch detection, season-dir resolution, normal preview building, consolidated preview building, specials matching, and TMDB season caching in one class.

**Why now:**
- The large preview-building methods are hard to reason about and hard to regression-test surgically.
- Specials and consolidated-preview logic are policy-heavy enough to justify their own units.
- This file is the other major engine module where complexity remains centralized.

**Refactor direction:**
- Extract a normal-preview builder.
- Extract a consolidated-preview builder.
- Extract specials matching / episode-title resolution into a dedicated helper.
- Leave `TVScanner` as the thin orchestration facade and cache owner.

### 3. Separate job persistence plumbing from queue-domain rules

[plex_renamer/job_store.py](../plex_renamer/job_store.py) currently owns SQLite connection lifecycle, schema and migration setup, job CRUD, queue ordering, and path propagation behavior.

**Why now:**
- Persistence concerns and queue-domain behavior are coupled together.
- Path propagation is domain logic and should not be buried inside the same class that manages schema and connections.
- This file is large for a reason, but the split line is now clear enough to act on safely.

**Refactor direction:**
- Extract database/bootstrap concerns behind a smaller persistence helper.
- Extract path propagation / downstream-job update behavior into a dedicated helper.
- Keep `JobStore` as the user-facing facade so callers do not churn.

### 4. Thin queue execution into orchestration plus filesystem operations

[plex_renamer/job_executor.py](../plex_renamer/job_executor.py) still combines queue worker lifecycle, rename execution, target remapping, cleanup, leftover-file handling, and revert behavior.

**Why now:**
- `_execute_rename()` is doing too much at once.
- Filesystem move logic and post-rename cleanup are coupled to queue orchestration even though they are separable concerns.
- Undo/revert behavior becomes easier to reason about once operation execution and queue sequencing are not intertwined.

**Refactor direction:**
- Extract file-move execution helpers.
- Extract directory cleanup / leftover relocation helpers.
- Keep `QueueExecutor` focused on job lifecycle, listener dispatch, and sequencing.

### 5. Split TV discovery walking from folder classification

[plex_renamer/app/services/tv_library_discovery_service.py](../plex_renamer/app/services/tv_library_discovery_service.py) is a medium-priority target. It blends recursive walking, symlink handling, folder-role classification, and TV-specific heuristics.

**Why now:**
- The service has a coherent domain, but too many sub-responsibilities.
- Discovery heuristics are easier to evolve when the classifier and recursive walker are separate.
- This is a good follow-on refactor after the engine and queue work.

**Refactor direction:**
- Extract a directory-classification helper.
- Extract recursive walking / visited-path management.
- Keep the service entry point stable for callers and tests.

## Secondary / Watch List

### 6. Keep an eye on job detail panel growth

[plex_renamer/gui_qt/widgets/job_detail_panel.py](../plex_renamer/gui_qt/widgets/job_detail_panel.py) mixes panel layout, preview-tree behavior, poster workflow integration, and presentation logic. It is not the first file to modularize, but it is the first GUI file likely to tip into unnecessary complexity if more behavior lands there.

### 7. Keep media workspace action policy from becoming a second controller

[plex_renamer/gui_qt/widgets/_media_workspace_actions.py](../plex_renamer/gui_qt/widgets/_media_workspace_actions.py) centralizes queueing, approval, rematch, season assignment, and action-bar state. It is still manageable, but it should not accumulate more controller-grade business logic.

## Do Not Prioritize Yet

- [plex_renamer/gui_qt/main_window.py](../plex_renamer/gui_qt/main_window.py) — already coordinator-driven; still central, but no longer a monolith.
- [plex_renamer/gui_qt/widgets/media_workspace.py](../plex_renamer/gui_qt/widgets/media_workspace.py) — now a wrapper over workspace coordinators rather than the original God widget.
- [plex_renamer/app/controllers/media_controller.py](../plex_renamer/app/controllers/media_controller.py) — still important, but helper extraction has already reduced the pressure here.
- [plex_renamer/tmdb.py](../plex_renamer/tmdb.py) — large but relatively cohesive after cache and batch-search extraction.
- [plex_renamer/gui_qt/widgets/_workspace_widgets.py](../plex_renamer/gui_qt/widgets/_workspace_widgets.py) — large because it contains multiple focused widget classes, not because it mixes unrelated domains.

## Plan of Attack

### Phase 1: Extract engine policy from orchestration

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

Move next to [plex_renamer/engine/_tv_scanner.py](../plex_renamer/engine/_tv_scanner.py).

Goals:
- Separate normal preview building from consolidated preview building.
- Isolate specials matching and related title-resolution helpers.
- Keep `TVScanner` as the compatibility facade so the rest of the app does not change shape.

Success criteria:
- The scanner reads as an orchestrator instead of a large implementation blob.
- Preview-building behavior is covered by narrower tests with less fixture setup.

### Phase 3: Untangle queue persistence and execution

Address [plex_renamer/job_store.py](../plex_renamer/job_store.py) and [plex_renamer/job_executor.py](../plex_renamer/job_executor.py) together, but in two small passes rather than one big rewrite.

Goals:
- First split `JobStore` into facade + extracted persistence/path-propagation helpers.
- Then split `job_executor.py` into queue orchestration + filesystem operation helpers.
- Preserve job model and listener APIs so GUI/controller code stays stable.

Success criteria:
- Queue-domain rules are no longer buried inside persistence plumbing.
- Rename/revert logic becomes easier to reason about independently from queue sequencing.

### Phase 4: Clean up discovery services

Then refactor [plex_renamer/app/services/tv_library_discovery_service.py](../plex_renamer/app/services/tv_library_discovery_service.py).

Goals:
- Separate folder classification from recursive traversal.
- Keep current discovery behavior and symlink guards intact.
- Add explicit tests around edge-case directory classification before extracting.

Success criteria:
- Discovery heuristics are easier to evolve without touching traversal logic.
- The service entry point remains stable while the internal responsibilities become clearer.

### Phase 5: Re-evaluate GUI hotspots after backend simplification

Once engine and queue debt are reduced, reassess [plex_renamer/gui_qt/widgets/job_detail_panel.py](../plex_renamer/gui_qt/widgets/job_detail_panel.py) and [plex_renamer/gui_qt/widgets/_media_workspace_actions.py](../plex_renamer/gui_qt/widgets/_media_workspace_actions.py).

Goals:
- Avoid premature GUI churn while backend contracts are still moving.
- Only split GUI files where the resulting boundaries are obvious and stable.

## Working Rules for the Refactor

- Keep public APIs stable where possible; prefer internal extraction over surface redesign.
- Refactor behind existing tests first, then add targeted tests for the behavior being extracted.
- Preserve behavior before chasing naming/style cleanup.
- Avoid simultaneous engine and GUI rewrites in the same pass.
- Treat the full pytest run and the Qt smoke wrapper as the minimum verification bar for each phase.
