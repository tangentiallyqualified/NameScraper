# TV Episode-Level Duplicate Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:test-driven-development`, then `superpowers:executing-plans` or `superpowers:subagent-driven-development` to implement task-by-task.

**Goal:** Replace TV folder-level duplicate handling with episode-level claim reconciliation so partially overlapping folders keep useful episodes visible while duplicate episode claims move into review/conflict rows.

**Architecture:** Keep current independent folder-to-TMDB matching intact. After TV states scan, reconcile same-show scanned siblings by `PreviewItem` episode keys instead of by folder identity. Preserve the narrow Succession disjoint-folder merge as a safe fast path, but add a scanned-claim reconciliation path for partial overlaps it intentionally refuses.

---

## Summary

TV duplicates should stop being a stable left-panel category. For TV, duplicate is an episode-level condition: one folder can contain both useful unique episodes and overlapping claims. Movie duplicates remain unchanged because movies do not have salvageable episode-level granularity.

A same-show TV group should produce one reviewable card where:
- unique episode claims stay queueable;
- overlapping claims become `CONFLICT: duplicate episode claim ...` rows;
- fully redundant folders appear as conflict/review evidence inside the show card, not as separate TV duplicate cards;
- source-folder information remains visible through row status/source text.

## Key Changes

- Add an optional `source_relative_folder: str = ""` field to `PreviewItem`; populate it after TV scans from the batch library root so merged rows still identify their original folder.
- Add internal TV claim reconciliation in `plex_renamer/engine/_batch_tv_episode_claims.py`:
  - group scanned TV states by `show_id`;
  - choose the primary state using existing confidence and claim priority;
  - merge preview rows from same-show siblings into the primary;
  - treat each `(season, episode)` in a preview item as an episode claim;
  - keep first/best claim for a key as mapped;
  - mark later claimants for the same key as `CONFLICT: duplicate episode claim SxxEyy also claimed by <source>`;
  - if a multi-episode file has any overlapping key, mark the whole file as conflict because it cannot be split safely.
- Update `BatchTVOrchestrator.scan_all()` and single-show scan reconciliation to run claim reconciliation after relevant same-show siblings have preview items.
- For TV, stop relying on `duplicate_of` to create a left-panel Duplicates group. Keep movie duplicate labeling unchanged.
- Update roster grouping so TV duplicate-like states fall under `Needs Review` if any legacy `duplicate_of` values remain; movie states continue using `Duplicates`.
- Preserve queue/preflight behavior where non-conflicting `OK` rows remain queueable even when conflict rows exist in the same TV card; conflict rows themselves never produce rename ops.

## Test Plan

- Add a TV partial-overlap regression:
  - folder A has `S04E01` and `S04E09`;
  - folder B has `S04E09` and `S04E10`;
  - after `discover_shows()` and `scan_all()`, one Succession card contains `S04E01`, one queueable `S04E09`, `S04E10`, and one conflict row for the duplicate `S04E09`.
- Keep the recently added narrow Succession test passing:
  - disjoint same-season `succession season 04` plus standalone `S04E09` still consolidates into one card with no duplicate state.
- Add a fully redundant TV sibling test:
  - second folder only repeats episodes already claimed;
  - it does not appear in a TV Duplicates roster group;
  - its files appear as conflict/review evidence inside the main show card.
- Add a movie duplicate guard:
  - two movie states for the same TMDB movie still render under `Duplicates` and remain non-queueable as before.
- Add queue/preflight tests:
  - unique `OK` TV rows remain eligible while conflict rows are skipped;
  - selected conflict/review rows do not produce rename ops.
- Run:
  - `python -m pytest tests/test_scan_improvements.py -q`
  - `python -m pytest tests/test_media_controller.py tests/test_qt_media_workspace.py -q`
  - `python -m pytest -q`

## Assumptions

- Show matching accuracy must not be boosted by grouping. Reconciliation only runs after folders independently match the same `show_id`.
- The existing narrow disjoint-folder merge remains in place during this change to preserve the solved Succession scenario.
- TV left-panel `Duplicates` can be retired because episode-level conflict/review rows preserve more useful information.
- Movie duplicate behavior is out of scope except for regression tests proving it remains unchanged.
