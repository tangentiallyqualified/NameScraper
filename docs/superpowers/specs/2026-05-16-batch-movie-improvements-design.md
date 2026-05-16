# Batch Movie Tab Improvements Design

**Date:** 2026-05-16
**Scope:** Three independent improvements to the batch movie workflow, packaged as one spec so they can be reviewed together and implemented in any order.

---

## Summary

Three issues identified by the user after reworking the batch TV mode:

1. **Movie match confidence is binary.** The roster confidence bar shows 0.5 for REVIEW rows and 1.0 for everything else, regardless of the underlying TMDB score. The real `score_results` confidence is computed and then discarded.
2. **Middle-panel preview rows show a per-file checkbox in movie mode.** Each movie has exactly one video file, so the per-row checkbox duplicates the roster checkbox and adds visual noise.
3. **Approving a match does not auto-check the roster row.** The shared `approve_scan_match` helper accepts a `set_actionable_preview_checks` callback as a parameter but never calls it — a latent bug that affects both TV and movie modes.

---

## Issue 1: Movie match confidence

### Current behavior

- [`engine/matching.py::score_results`](../../../plex_renamer/engine/matching.py) computes a real `0.0..1.0` confidence (title similarity 70% + year match 30% + exact-title bonus +0.15), optionally boosted by alternative TMDB titles in `boost_scores_with_alt_titles`.
- [`engine/_movie_scanner.MovieScanner._best_match`](../../../plex_renamer/engine/_movie_scanner.py) returns the top `(result, confidence)` tuple, but the confidence is only used to decide whether to stamp the `REVIEW:` status string. The numeric value is not carried onto the `PreviewItem`.
- [`app/controllers/_movie_state_helpers.build_movie_library_states`](../../../plex_renamer/app/controllers/_movie_state_helpers.py) hard-codes `state.confidence = 1.0` when `media_id` is present, `0.5` when the status starts with `REVIEW`, and `0.0` otherwise. The roster bar therefore only ever shows those three values.

### New behavior

Mirror the TV episode confidence improvement pattern (see `docs/superpowers/plans/2026-05-15-episode-match-confidence-improvements.md`): keep confidence as a `0.0..1.0` score, apply evidence-based floors and caps after initial scoring, never exceed `1.0`.

**Pipeline:**

```
score_results
  → boost_scores_with_alt_titles
  → apply_movie_confidence_adjustments   (new)
  → preview.episode_confidence           (existing per-row confidence field, media-neutral)
  → state.confidence                     (sourced from preview, not hard-coded)
```

### Evidence sources, floors, and caps

| Evidence | Type | Threshold |
|---|---|---|
| Filename year exactly matches TMDB year | floor | 0.85 |
| Filename has year, differs by ≥3 from TMDB year | cap | 0.45 |
| Parent folder name normalizes to TMDB title (or `Title (Year)`) | floor | 0.88 |
| Exact normalized title match (filename or folder) | floor | 0.95 |
| Sequel-number mismatch (e.g. `Movie 2` vs `Movie`, `Part II` vs `Part I`) | cap | 0.50 |
| Manual approve | floor | 1.0 (unchanged) |

**Precedence:** caps win over floors. Floors are `confidence = max(confidence, floor)`; caps are `confidence = min(confidence, cap)`; caps are applied after floors so a year-mismatch cap can override a folder-name floor.

### Surfacing in the GUI

- Roster confidence bar in [`gui_qt/widgets/_workspace_widgets.RosterRowWidget`](../../../plex_renamer/gui_qt/widgets/_workspace_widgets.py) renders the real value — no code change required, it already reads `state.confidence`.
- `REVIEW:` status string continues to be set by the scanner when `confidence < get_auto_accept_threshold()` (unchanged). The fix is that `build_movie_library_states` stops overwriting `state.confidence` with `0.5` when the status starts with `REVIEW`; the real adjusted confidence is preserved end-to-end.

### Architecture notes

- `apply_movie_confidence_adjustments(results, raw_name, year_hint, folder)` lives in `engine/matching.py` next to the TV equivalent. Pure function: takes the chosen result plus parsed evidence, returns adjusted confidence.
- Sequel-mismatch detection uses a small helper (e.g. `_extract_sequel_number(title)`) that returns an integer or None from tokens like `2`, `II`, `Part 2`, `Chapter Two`.
- Folder-name corroboration reuses `clean_folder_name` and `normalize_for_match` from `parsing`.

### Out of scope (future)

- Exposing evidence weights and thresholds in the Settings tab. Constants stay in code for now so they can be iterated quickly.
- Runtime, original_language, or popularity-based evidence.

---

## Issue 2: Hide middle-panel checkbox in movie mode

### Current behavior

[`gui_qt/widgets/_workspace_widgets.PreviewRowWidget`](../../../plex_renamer/gui_qt/widgets/_workspace_widgets.py) builds a `ToggleSwitch` and shows it whenever `preview.is_actionable and checkable`. This is correct for TV (per-episode toggles) but redundant for movies where each preview row corresponds to a single video file already controlled by the roster checkbox.

### New behavior

`PreviewRowWidget` gains a `media_type: str` argument. When `media_type == "movie"`:

- The `ToggleSwitch` is constructed but hidden (`setVisible(False)`).
- The `check_toggled` signal still exists but has no source, so no spurious emits.
- The layout slot for the switch is preserved so movie rows align horizontally with TV rows and the change stays a one-branch edit in `__init__`.
- Companion subtitle rows in movie mode also get no per-file checkbox.

Row click still selects the item (already independent of the checkbox).

### Wiring

[`gui_qt/widgets/_media_workspace_preview.attach_preview_widget`](../../../plex_renamer/gui_qt/widgets/_media_workspace_preview.py) passes `media_type=self._media_type` through to `PreviewRowWidget`. The same `media_type` is already stored on the workspace view, so no new plumbing.

---

## Issue 3: Approve auto-checks the roster row

### Current behavior

[`app/controllers/_match_state_helpers.approve_scan_match`](../../../plex_renamer/app/controllers/_match_state_helpers.py) accepts `set_actionable_preview_checks` as a parameter and never calls it. After approve, `state.checked` stays `False` and the user must tick the roster checkbox manually.

### New behavior

Add the missing call:

```python
def approve_scan_match(
    state: ScanState,
    *,
    resolve_movie_preview_review,
    set_actionable_preview_checks,
) -> bool:
    if (
        state.show_id is None
        or state.queued
        or state.scanning
        or state.duplicate_of is not None
    ):
        return False
    state.match_origin = "manual"
    resolve_movie_preview_review(state)
    set_actionable_preview_checks(state, True)
    return True
```

### Scope

The fix applies to both TV and movie modes. `set_actionable_preview_checks` already gates per `item.is_actionable`, so rows in `Conflict`, `Duplicate`, or `REVIEW` status remain unchecked. Approve means "I've verified this match, queue what's queueable" — the gate behavior is correct for both media types.

---

## Test plan

### Movie confidence (Issue 1)

- `Inception.2010.mkv` matched against TMDB `Inception (2010)` → confidence ≥ 0.95 (exact title floor).
- `Inception (2010)/Inception.mkv` (folder has year, filename does not) → confidence ≥ 0.88 (folder-name floor).
- `Inception.2008.mkv` matched against TMDB `Inception (2010)` → confidence ≤ 0.45 (year-mismatch cap, even with perfect title).
- `Iron Man 2.mkv` matched against TMDB `Iron Man` → confidence ≤ 0.50 (sequel-mismatch cap).
- `Iron Man.mkv` matched against TMDB `Iron Man 2` → confidence ≤ 0.50 (sequel-mismatch cap, reverse direction).
- After manual approve via the match picker, `state.confidence == 1.0` regardless of underlying evidence.
- After scan, `state.confidence` is the real adjusted value, not a hard-coded 0.5/1.0.

### Middle-panel checkbox (Issue 2)

- In movie mode, `PreviewRowWidget._check.isVisible()` is `False`.
- In TV mode, `PreviewRowWidget._check.isVisible()` is unchanged.
- Movie preview rows still respond to clicks (selection works).
- Companion subtitle rows in movie mode have no visible checkbox.

### Approve auto-check (Issue 3)

- Approving a movie match sets `state.checked == True` and the roster ToggleSwitch is on.
- Approving a TV match sets `state.checked == True` and ticks each actionable preview row's per-index binding.
- Approving a TV show with a `Conflict` row leaves the conflict row's binding unchecked but checks the rest.
- Approving while `state.queued`, `state.scanning`, or `state.duplicate_of is not None` is still a no-op.

### Suggested commands

```
python -m pytest tests/test_movie_scanner.py tests/test_media_controller.py -q
scripts/test-smoke.cmd
```

---

## Assumptions

- The existing `episode_confidence` field on `PreviewItem` is treated as a media-neutral per-row confidence in movie mode (no field rename needed). If a rename becomes desirable later, that's a separate refactor.
- `state.confidence` continues to feed the roster bar and the auto-accept threshold check; no new state field is added.
- The default `auto_accept_threshold` (currently configurable in settings) remains the gate for the `REVIEW:` label.
- All evidence weights and thresholds stay as module-level constants until the Settings-tab exposure becomes a real ask.
