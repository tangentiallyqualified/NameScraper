# Episode Match Confidence Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:test-driven-development`, then `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement task-by-task.

**Goal:** Improve episode match confidence with evidence-based weighting while preserving user-controlled thresholds and existing season mapping behavior.

**Architecture:** Keep scanners responsible for episode/season assignment. Add a post-mapping confidence pass that applies confidence floors and caps from filename evidence, title compatibility, season coverage, extras filtering, duplicate/conflict evidence, and aired-episode availability.

---

## Summary

Confidence remains a `0.0..1.0` score and must never exceed `1.0`. Improvements use `max(existing, evidence_floor)` and mismatch caps, not additive boosts.

Explicit `S01E01` numbering is strong evidence, not certainty. A mapped file's source title prefix must be compatible with either the show title or the mapped season name before receiving high confidence. Example: `K.Return.of.Kings.01...` is compatible with season 2 of `K (2012)` when TMDB names season 2 `K: Return of Kings`.

Exact season coverage uses a `0.80` floor, intentionally below the default episode threshold of `0.85`.
For single-season shows with exact clean coverage and a perfect `1.0` show match, the exact coverage floor is raised to `0.85`.
Rows that are already Plex-ready no-op episode renames receive `1.0` confidence independently, even when other rows in the same directory still need renaming.

## Key Changes

- Add parsing helpers exported through `plex_renamer.parsing`:
  - `is_companion_video_file(path)` for `NCOP`, `NCED`, `Creditless Opening`, `Clean Ending`, etc.
  - `extract_source_title_prefix(filename)` to read title text before episode tokens.
- Preserve TMDB season names in `tmdb_seasons` from `get_season_map()` using existing `season_info["name"]`; no new TMDB call path.
- Change explicit season-relative mappings so they no longer start at `1.0`; use `0.86` unless title/season evidence raises or caps them.
- Add `apply_episode_confidence_adjustments(items, tmdb_seasons, show_info, show_match_confidence=None, today=None)` in TV scanner postprocessing and call it after duplicate resolution but before episode review thresholding.
- Apply floors and caps:
  - Exact clean aired/expected regular-season coverage floor: `0.80`.
  - Single-season exact clean aired/expected coverage with a perfect show match floor: `0.85`.
  - Near-complete clean coverage floor: `0.74`.
  - Compatible source title prefix floor: `0.88`.
  - Assigned TMDB episode title match floor: `0.92`.
  - Already Plex-ready no-op episode row floor: `1.0`, applied per row rather than per show.
  - Contradictory source title prefix cap: `0.45`.
  - Manual episode remaps may remain `1.0`.

## Matching Rules

- A source title prefix is compatible if it normalizes close to:
  - the show title,
  - the mapped TMDB season name,
  - or a combination/variant of show title plus season name.
- Generic season names like `Season 2` should not make a mismatched prefix compatible by themselves.
- Coverage calculations consider regular non-special candidates only:
  - include season `> 0` video preview items mapped or attempted against regular episodes;
  - exclude season `0`, nested extras/specials, unmatched extras, companion videos, and samples.
- Duplicates and conflicts are not exempt:
  - they count as regular-season evidence when non-special;
  - they prevent exact/near-complete "clean coverage" floors because they represent count or ownership mismatches.
- For currently airing seasons:
  - if TMDB episode metadata includes future `air_date` values, expected episodes are only those with `air_date <= today`;
  - if metadata is missing or would yield an empty expected set, fall back to the full TMDB season set.

## Test Plan

- Add scanner confidence tests:
  - `King of the Hill/Season 01/SpongeBob - S01E01.mkv` is capped below threshold despite explicit numbering.
  - `King of the Hill - S01E01 - Pilot.mkv` gets high confidence from compatible prefix/title evidence, not numbering alone.
  - `K/Season 02/K.Return.of.Kings.01.mkv` is treated as compatible with TMDB season name `K: Return of Kings`.
  - Already Plex-ready episodes such as `Bartender (2006)/Season 01/Bartender (2006) - S01E01 - Bartender.mkv` get `1.0`.
  - A mixed directory with one already Plex-ready episode and one episode needing rename keeps the Plex-ready row at `1.0`.
  - Bartender-style bare `01..11` exact coverage gets `0.80` by default, or `0.85` when the show match confidence is `1.0`.
  - Multi-season folders with exact per-season coverage get `0.80` without changing season assignment.
  - `NCOP`/`NCED` files in a season folder do not count against exact coverage.
  - Nested `Extras`/`Specials` directories do not affect regular season coverage.
  - Duplicate regular episode claims prevent coverage floors for that season.
  - Conflict regular episode rows prevent coverage floors for that season.
  - Currently airing `4/13` season with future air dates treats the first 4 aired episodes as the expected set.
- Update existing tests that assumed explicit `SxxEyy` confidence is always `1.0`.
- Run:
  - `python -m pytest tests/test_scan_improvements.py tests/test_jojo_matching.py -q`
  - `python -m pytest tests/test_media_controller.py tests/test_episode_mapping_projection.py -q`

## Assumptions

- The helper changes confidence only; existing threshold logic remains the only approval gate.
- `0.80` exact coverage is intentionally below the default `0.85`.
- Title-prefix mismatch is a hard warning signal, but mapped season names can satisfy title compatibility.
- Season `0` confidence improvements are out of scope for this pass.
