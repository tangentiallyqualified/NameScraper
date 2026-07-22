# Provider-Map Correctness Final-Review Fix Report

## Scope and outcome

- Baseline reviewed and fixed: `3b9a731` on `codex/provider-map-correctness`.
- Source findings: `.superpowers/sdd/final-review-findings.md`.
- Approved plan: `docs/current-plans/2026-07-21-02-provider-map-correctness.md`.
- Result: all four Important findings and the Minor compatibility finding are addressed.
- An independent final reviewer found two additional integration/boundary edges during the fix wave; both were driven through new RED/GREEN regressions. The final bounded re-review reported no remaining Critical or Important issues and `Ready to merge: Yes`.
- No change was made to `docs/deferred-work.md`, any audit baseline, or any suppression/allowlist.

## Finding 1 — legacy season-map snapshots bypass strict reads

### Root cause

TMDB exported and imported season-map snapshots without a contract version. A pre-contract failure-shaped map could therefore survive restart, populate the runtime map cache, and be returned before a strict provider request.

### Fix

- Added `season_map_contract_version = 1` to exported TMDB metadata snapshots.
- Legacy snapshots still restore show, individual-season, and movie caches, but do not restore their season-map cache.
- Version-1 season-map entries are validated and normalized into local values before a cache assignment; malformed entries are skipped without partially inserting them.
- Explicit valid empty maps remain valid and round-trip.

### Files and regressions

- `plex_renamer/_tmdb_metadata_cache.py`
- `plex_renamer/tmdb.py`
- `tests/test_tmdb.py`

The migration regression restores a poisoned legacy snapshot with `clear_existing=True`, proves unrelated caches survive, and proves `get_season_map()` performs a fresh strict two-request fetch.

## Finding 2 — malformed inner records can be cached or trusted

### Root cause

- TVDB accepted arbitrary episode mappings, skipped invalid identifiers, and could cache an empty or partial result.
- TMDB allowed malformed season/episode identifiers to become invalid keys or escape through the metadata builder as untyped exceptions.
- The scanner validated only the tuple and outer mapping shape, not the tuple count or required nested map fields.
- Nested provider values such as non-text names/posters and malformed TVDB extended-detail records could still poison a provider cache or escape untyped before optional matching could abstain.

### Fix

- TMDB now rejects boolean/missing/non-integer season and episode identifiers, negative counts, non-text season/episode names, non-text/non-null still paths, and malformed crew/guest-star containers as `SeasonMapUnavailableError` before map caching.
- TVDB validates every page before extending the local episode list, including identifiers and raw non-null title/poster values. A later malformed page invalidates the whole request and no map is cached.
- TVDB validates all extended-detail collection element/container shapes needed by normalization. Malformed detail data becomes the typed provider error on strict reads and `None` on the existing safe detail path.
- Scanner validation now requires non-boolean integer season and episode keys, a non-negative integer tuple total/count, dictionary `titles`/`posters`/`episodes`, text titles, text-or-null posters, dictionary metadata values, and valid optional name/season-poster values. The scanner cache is assigned only after the complete map validates.
- Two scanner test doubles were updated from the invalid `(map, None)` shape to a real non-special episode total; production validation was not weakened.

### Files and regressions

- `plex_renamer/tmdb.py`
- `plex_renamer/tvdb.py`
- `plex_renamer/engine/_tv_scanner.py`
- `tests/test_provider_season_map_failures.py`
- `tests/test_scan_improvements.py`
- `tests/test_tv_scanner_normal.py`

Coverage includes missing/string/boolean identifiers, invalid tuple totals, malformed required nested fields and keys, invalid truthy and falsey raw provider values, mixed valid/invalid TVDB pages, malformed extended-detail records, empty-cache assertions, and valid explicit empty maps.

## Finding 3 — optional discovery evidence propagates map outages

### Root cause

Episode-evidence scoring calls `get_season_map()` before a `ScanState` exists. A typed provider outage therefore aborted discovery instead of allowing the later strict scan to create an actionable per-show error.

### Fix

`score_tv_results()` catches only `SeasonMapUnavailableError` around the optional episode-evidence boost and returns the already-computed title/alternative-title scores. Generic defects still propagate. The subsequent strict scan still fails visibly with the standard actionable error.

### Files and regressions

- `plex_renamer/engine/matching.py`
- `tests/test_batch_autoaccept_guards.py`

The regressions prove typed outage abstention, successful state creation, later actionable scan failure, and propagation of an unexpected `RuntimeError`.

## Finding 4 — secondary scan entry points do not fail closed

### Root cause

The single-show/rematch worker logged exceptions and then reported `READY` while retaining stale state. Merged rescans only logged errors. Command gating trusted stale previews instead of independently rejecting `scan_error`. During review, a further UI integration issue was found: the normal completion event from a failed single-show scan caused the main window to auto-start a bulk retry and mask `FAILED` as `READY`.

### Fix

- Added one shared `fail_scan_state()` transition that resets scanner/previews/completeness/assignments/GUI state, unchecks the show, and records a stable typed or generic user message.
- Applied it to typed bulk failures, generic bulk failures, single-show/rematch failures, and merged-rescan failures.
- Single-show failures now publish `ScanLifecycle.FAILED`, do not refresh a stale episode guide, and still publish the final failed state through the established completion callback.
- The main-window completion coordinator handles `FAILED` before bulk auto-scan, surfaces the failed state and error feedback, and does not auto-scan states carrying `scan_error`.
- Command gating rejects `scan_error` before considering stale selections/previews, and such a state is never classified as fully ready.

### Files and regressions

- `plex_renamer/engine/_scan_runtime.py`
- `plex_renamer/engine/_batch_orchestrators.py`
- `plex_renamer/app/controllers/_single_show_scan_helpers.py`
- `plex_renamer/app/services/command_gating_service.py`
- `plex_renamer/gui_qt/_main_window_scan.py`
- `tests/test_batch_autoaccept_guards.py`
- `tests/test_media_controller_scan_show.py`
- `tests/test_merged_show_checked_gating.py`
- `tests/test_command_gating_service.py`
- `tests/test_qt_main_window.py`

Typed and generic failures are covered for single-show and merged-rescan paths, including stale state clearing, `checked=False`, final callback state, lifecycle, no guide refresh, queue rejection, and no UI auto-retry/masking.

## Minor finding — TVDB safe-method compatibility

### Root cause

Public `get_season()` and seasonal `fetch_poster()` inherited strict map exceptions after the original correctness implementation.

### Fix

Public `get_season()` catches only `SeasonMapUnavailableError` and returns the established empty season payload. Seasonal poster fetch consequently remains `None` when the guide is unavailable. Strict `get_season_map()` remains strict, and malformed detail data is typed before the safe method catches it.

### Files and regressions

- `plex_renamer/tvdb.py`
- `tests/test_tvdb.py`
- `tests/test_provider_season_map_failures.py`

## Audit-driven import-cycle correction

The first full-suite run exposed the branch-level cycle `providers -> tmdb/tvdb -> providers`. The public exception had been defined in the registry while both registered clients imported it back. The exception now lives in leaf module `plex_renamer/_provider_errors.py`; `plex_renamer.providers` explicitly re-exports the same class, preserving public imports and exception identity. TMDB/TVDB import the leaf directly. No cycle baseline was edited.

Files:

- `plex_renamer/_provider_errors.py`
- `plex_renamer/providers.py`
- `plex_renamer/tmdb.py`
- `plex_renamer/tvdb.py`

## TDD evidence

### Baseline

```text
python -m pytest tests/test_provider_season_map_failures.py tests/test_batch_autoaccept_guards.py tests/test_scan_improvements.py tests/test_queue_submission_automux.py tests/test_tmdb.py tests/test_tvdb.py -q
175 passed in 1.30s
```

### RED, before production edits

```text
python -m pytest tests/test_tmdb.py tests/test_provider_season_map_failures.py tests/test_batch_autoaccept_guards.py tests/test_media_controller_scan_show.py tests/test_merged_show_checked_gating.py tests/test_command_gating_service.py tests/test_tvdb.py -q --tb=short
40 failed, 110 passed in 5.77s
```

The corrected scan/gating-only RED subset independently produced `6 failed, 33 deselected in 0.69s`, all on the intended stale-state/lifecycle/gating assertions.

Additional reviewer-driven RED evidence:

```text
Qt failed-completion integration: 1 failed in 1.95s (bulk retry was called)
Nested TMDB/TVDB values and malformed extended details: 6 failed, 60 deselected in 0.37s
Falsey raw TVDB values: 2 failed, 2 passed in 0.32s
```

### GREEN progression

```text
Original seven-file RED matrix: 150 passed in 1.04s
Expanded provider/scanner/matching/discovery/single/merged/queue matrix: 302 passed in 2.03s
Cycle audit plus provider/TMDB/TVDB suites: 105 passed in 6.29s
Provider/cache/TVDB/discovery after nested validation: 117 passed in 0.73s
Qt failed-completion regression: 1 passed in 0.86s
Falsey raw TVDB regression: 4 passed in 0.22s
Final focused matrix including Qt: 357 passed in 6.52s
```

## Final verification

All executables came from the repository's canonical virtual environment at `C:\Users\roxie\OneDrive\Documents\Code Projects\NameScraper\.venv\Scripts`.

### Tests

```text
python -m pytest tests/test_provider_season_map_failures.py tests/test_tmdb.py tests/test_tvdb.py tests/test_tv_scanner_normal.py tests/test_scan_improvements.py tests/test_matching_helpers.py tests/test_alt_title_matching.py tests/test_alt_title_matching_orchestrator.py tests/test_provider_agnostic_matching.py tests/test_fallback_matching.py tests/test_batch_autoaccept_guards.py tests/test_media_controller_scan_show.py tests/test_merged_show_checked_gating.py tests/test_command_gating_service.py tests/test_queue_submission_automux.py tests/test_qt_main_window.py -q --tb=short
357 passed in 6.52s
```

```text
python -m pytest -q --tb=short
2754 passed, 4 skipped, 9 xfailed, 58 subtests passed in 181.40s
```

The first pre-cycle-correction full run was `2744 passed, 4 skipped, 9 xfailed, 1 failed`; its sole failure was the dependency-cycle repository contract. The focused cycle audit passed after the leaf-module correction, and the final full run is clean.

### Ruff

```text
ruff format <all 22 touched Python files>
22 files left unchanged

ruff check <all 22 touched Python files>
All checks passed!
```

### Pyright

```text
pyright plex_renamer/_provider_errors.py plex_renamer/providers.py plex_renamer/tvdb.py plex_renamer/engine/_tv_scanner.py plex_renamer/engine/matching.py plex_renamer/engine/_scan_runtime.py plex_renamer/app/controllers/_single_show_scan_helpers.py plex_renamer/app/services/command_gating_service.py plex_renamer/gui_qt/_main_window_scan.py tests/test_provider_season_map_failures.py
0 errors, 0 warnings, 0 informations
```

A deliberately broader diagnostic run that also included the already-adjudicated cache/batch/TMDB files reported 30 existing findings: one pre-existing `_tmdb_metadata_cache.py` inference, 28 pre-existing `_batch_orchestrators.py` findings, and the pre-existing Pillow `Image.LANCZOS` finding in `tmdb.py`. The two new test-double typing findings seen during the first diagnostic were fixed; the clean focused command above covers the changed boundary code. No baseline or suppression was changed.

### Repository integrity

```text
git diff --check
<no output; exit 0>

git diff -- docs/deferred-work.md scripts/audit
<no output; exit 0>
```

## Self-review

- Verified each exception scope: provider boundaries convert known transport/data failures to the typed error; discovery and TVDB public compatibility catch only that type; generic discovery defects still propagate.
- Verified atomicity: provider/scanner/snapshot maps are built and validated locally before their cache assignments; mixed-page failures leave no season-map cache entry.
- Verified all scan failure paths use the shared reset/uncheck/error transition and the single-show result contract reports the actual failed state.
- Verified queue safety does not depend on producers successfully clearing stale rows because `scan_error` is an independent gate.
- Verified legacy migration affects only the pre-contract season-map snapshot namespace.
- Verified explicit empty responses remain successful and cacheable.
- Verified no audit baseline, deferred-work document, suppression, or allowlist was modified.

## Remaining concerns

No open correctness concern remains from the final review. The scoped Pyright command is clean; the broader repository files retain their previously adjudicated type findings and were deliberately not expanded into unrelated cleanup.
