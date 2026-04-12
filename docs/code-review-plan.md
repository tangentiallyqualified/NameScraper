# Code Review & Refactor Plan

Stats snapshot: ~18.6k LOC source, ~13.1k LOC tests across 10 files. Threading: 1 raw `threading.Thread` site (QueueExecutor), all others routed through shared `ThreadPoolExecutor`.

## Progress

- [x] **#4** cache/policy consolidation — `PersistentCacheService` delegates freshness to `RefreshPolicyService` via DI.
- [x] **#5** TMDB persistence — `TMDBClient` now reads/writes L2 via the persistent cache; wired in `main_window`.
- [x] **#1** engine.py split — converted to `engine/` package (`_core.py`, `models.py`, `_state.py`, `matching.py`), public API preserved via `__init__.py`.
- [x] **#3** matching consolidation — 9 scoring functions extracted to [plex_renamer/engine/matching.py](../plex_renamer/engine/matching.py).
- [x] **#10** fast vs smoke split — added [scripts/test-fast.cmd](../scripts/test-fast.cmd) / [test-fast.ps1](../scripts/test-fast.ps1) / [test_fast_runner.py](../scripts/test_fast_runner.py); runs the non-Qt suite (244 tests, ~2.7s) with the same concise-summary format as `test-smoke`.
- [x] **#9** test shape rebalance — split 3,946-line `test_gui_qt_smoke.py` (85 tests) into 5 feature-area files + shared [conftest_qt.py](../tests/conftest_qt.py); backfilled unit tests for `cache_service` (18), `command_gating_service` (21), `refresh_policy_service` (24). Fast suite: 244 → 307 tests.
- [x] **#2** media_workspace split — extracted 11 widget classes (~590 lines) to [_workspace_widgets.py](../plex_renamer/gui_qt/widgets/_workspace_widgets.py); `media_workspace.py` reduced from 2,228 → 1,673 lines. Backward-compatible alias imports preserved for tests.
- [x] **#6** centralize threading — replaced 10 raw `threading.Thread` sites across 7 files with a shared `ThreadPoolExecutor` in [thread_pool.py](../plex_renamer/thread_pool.py). `QueueExecutor` (persistent worker loop) intentionally unchanged.
- [x] **#7** magic numbers to constants — added `YEAR_MIN`/`YEAR_MAX`/`YEAR_MIN_EXTRACT`, `RESOLUTION_NUMBERS`, and `SCORE_TIE_MARGIN` to [constants.py](../plex_renamer/constants.py); replaced 8 inline literals across `parsing.py` and `engine/_core.py`.
- [x] **#8** settings schema validation — added `_SCHEMA` type map and `_validate()` to [settings_service.py](../plex_renamer/app/services/settings_service.py); unknown keys are stripped and wrong-type values reset to defaults on load with log warnings. 6 new tests.
- [x] **#11** automate release steps — [release.ps1](../scripts/release.ps1) + [release.cmd](../scripts/release.cmd): bumps version in `pyproject.toml`, prepends dated changelog entry from commit log, commits, and tags. `-Push` to push.
- [x] **#12** add CI — [ci.yml](../.github/workflows/ci.yml): runs fast (non-Qt) test suite on PRs and pushes to main.

## High Value

### 1. Split `engine.py` (3,710 lines)
[plex_renamer/engine.py](../plex_renamer/engine.py) holds `BatchTVOrchestrator`, `BatchMovieOrchestrator`, `TVScanner`, `MovieScanner`, scoring, normalization, companion-file logic, and preview dataclasses in one module. Hard to navigate, hard to test in isolation.

**Action:** Split into:
- `engine/orchestrators.py` — BatchTVOrchestrator, BatchMovieOrchestrator
- `engine/scanners.py` — TVScanner, MovieScanner
- `engine/matching.py` — scoring + normalization
- `engine/models.py` — PreviewItem, ScanState, CompanionFile

### 2. Break up `media_workspace.py` (2,228 lines)
[plex_renamer/gui_qt/widgets/media_workspace.py](../plex_renamer/gui_qt/widgets/media_workspace.py) is a single widget handling roster, preview list, detail panel, poster requests, batch queue, and action-bar gating.

**Action:** Extract `RosterPanel`, `PreviewPanel`, and a small state/event coordinator. Once separated, [_media_helpers.py](../plex_renamer/gui_qt/widgets/_media_helpers.py) can stop being a dumping ground.

### 3. Consolidate matching / normalization
Title cleaning, similarity, and folder-name normalization exist in both [parsing.py](../plex_renamer/parsing.py) (`normalize_for_match`, `best_tv_match_title`) and [engine.py](../plex_renamer/engine.py) (TV scanner re-cleans inline while scoring).

**Action:** Single `matching` module that both parsing and engine call, so scoring and display stay consistent.

### 4. Merge cache_service / refresh_policy_service freshness logic
[cache_service.py](../plex_renamer/app/services/cache_service.py) and [refresh_policy_service.py](../plex_renamer/app/services/refresh_policy_service.py) independently implement "is this entry fresh / recently refreshed / currently refreshing" logic. `cache_service` hardcodes a 300s window; `refresh_policy_service` accepts it as a parameter. TTL drift here is a silent correctness bug.

**Action:** Pick one as authoritative; have the other delegate.

### 5. Persist TMDB cache across sessions
[tmdb.py](../plex_renamer/tmdb.py) keeps in-memory `_show_cache` / `_season_cache` dicts, lost every launch, while [cache_service.py](../plex_renamer/app/services/cache_service.py) already persists to disk.

**Action:** Wire TMDB lookups through the persistent cache; drop the ad-hoc dicts. Audit `get_tv_details` / `get_season_details` call sites in engine scanners for duplicate hits within a single batch while there.

## Medium

### 6. Centralize threading
12 `threading.Thread(target=...)` sites across 8 files with Events for cancellation and no shared pool.

**Action:** Small `ThreadPoolExecutor` wrapper in `media_controller` with a single cancellation token.

### 7. Move magic numbers to constants
Year range `1900..2099`, resolution set `{480,720,1080,2160}`, auto-accept thresholds — scattered across [parsing.py](../plex_renamer/parsing.py) and [engine.py](../plex_renamer/engine.py).

**Action:** Move to [constants.py](../plex_renamer/constants.py).

### 8. Validate settings schema
[settings_service.py](../plex_renamer/app/services/settings_service.py) loads JSON and silently falls back to defaults on missing/typo keys.

**Action:** Pydantic model (or dataclass with explicit validation) to surface bad config immediately.

### 9. Rebalance test shape
[test_gui_qt_smoke.py](../tests/test_gui_qt_smoke.py) is 3,946 lines — almost a third of the test suite in one file. `cache_service`, `command_gating_service`, `refresh_policy_service`, and `job_executor` have no dedicated unit tests.

**Action:** Split the smoke file by feature area; backfill service-level unit tests.

## Workflow / DX

### 10. Fast vs smoke test split
[scripts/test-smoke.cmd](../scripts/test-smoke.cmd) hardcodes the venv path and always boots a full Qt app.

**Action:** Split into `test-fast` (engine + controllers + services, no Qt) and `test-smoke` (Qt integration). Local loop gets quicker; smoke stays for pre-publish.

### 11. Automate release steps
[docs/ai-publish-workflow.md](ai-publish-workflow.md) + [git-publish.ps1](../scripts/git-publish.ps1) handle commit/push but there's no version bump, tag, or changelog step.

**Action:** Minimal `bump + tag + CHANGELOG append` add-on.

### 12. Add CI
No `.github/workflows` found.

**Action:** Single "fast tests on PR" job to catch regressions the smoke script exists to find.

## Suggested Order

1. **#4** (cache/policy consolidation) and **#5** (TMDB persistence) — small, high-leverage, do first.
2. **#1** (engine.py split) — unblocks everything else, including the shared matching module.
3. **#3** (matching consolidation) — falls out naturally from #1.
4. **#9** / **#10** (test split) — slot alongside #1 so the refactor has guardrails.
5. **#2** (media_workspace) — biggest GUI win but can wait until the backend is tidier.
6. Remaining medium / DX items as capacity allows.
