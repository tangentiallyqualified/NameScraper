# Episode Assignment Redesign — Design

Date: 2026-06-11
Status: Approved design, pending implementation plan
Scope: TV episode matching, confidence logic, specials mapping, and the
episode fixing UI flow. Movies are out of scope except where shared
helpers are touched.

## Problem

Episode-level matching has accumulated divergent half-policies and the
fixing UI cannot express common corrections:

1. `match_special` never sets `episode_confidence`, so every specials
   assignment defaults to 1.0 and bypasses review even when it matched on
   the `S00E##` number alone.
2. When a filename's embedded title and its episode number point at
   different TMDB episodes, specials silently trust the number (the
   "`s00e03 - Special A`" mismatch) and regular episodes silently
   renumber to the title match. Neither path records reduced confidence.
3. Unmatched specials outside extras folders are passed through with
   status "OK" and their original name, hiding failures.
4. A show folder containing only a specials folder scans as Season 1
   instead of Season 0.
5. Same-named specials inside different season folders collide; the
   duplicate resolver picks a winner via filename-prefix heuristics and
   the loser becomes an unfixable `SKIP`.
6. `extract_episode` caps at 2 episodes for `S01E01E02` patterns and 3
   for dash ranges; longer runs are silently truncated.
7. The Fix Episode action is only offered on rows in REVIEW status, the
   picker is single-select, and "Missing File" guide rows carry no file,
   so: files cannot be assigned to 3+ episodes, unmatched files cannot
   be assigned to unmatched episodes, and OK/skipped/conflict rows
   cannot be corrected at all.
8. Show-level matching sometimes picks the wrong show, and correct
   matches land in manual review too often (confidence calibration).

## Decisions (from brainstorming)

- Approach: first-class assignment table as source of truth in the
  scan/preview layer (option B), with `PreviewItem` becoming a
  projection. The queue boundary (`build_rename_job_from_state` →
  `RenameOp`) is unchanged.
- Fix scope: every file row gets fix actions regardless of status, and
  missing-episode rows get an "Assign file…" action (both directions).
- Multi-episode assignment: multi-select picker; selections must be
  same-season and contiguous.
- Title vs number disagreement: strong title match wins; weak or
  ambiguous title keeps the number but caps confidence so the row lands
  in REVIEW.
- Episode data source: TMDB only. Alternate sources (TVDB ordering)
  remain future work; the manual fix flow covers numbering
  disagreements.
- mkvmerge track stripping/renaming: architecture room only — a
  per-row actions menu and an extensible assignment record; no track
  code or stub fields in the rename pipeline now.
- Duplicate/version support (Plex multiple copies of an episode):
  schema room only — claims are stored as a list per episode slot and
  assignments carry a `role` field (`primary` now, `version` reserved).
  Policy decides whether multiple claims are a conflict (today) or
  versions (future); no duplicate UI or naming is built now.

## 1. Architecture and data model

New engine module `plex_renamer/engine/episode_assignments.py` owning a
per-show `EpisodeAssignmentTable`, stored on `ScanState.assignments`.

Records:

- `FileEntry` — one per discovered video file. Carries parse evidence
  captured at scan time: parsed episode numbers, season hint, embedded
  title, season-relative flag, source folder, companions,
  sample/companion-video flags. Evidence is immutable after scan; fixes
  never overwrite it.
- `EpisodeSlot` — one per TMDB episode (season, episode, title,
  air date, overview), including Season 0. Built from the season data
  the scanner already fetches.
- `Assignment` — links one `FileEntry` to 1..N contiguous
  `EpisodeSlot`s in a single season. Fields: `origin`
  (`auto` | `manual`), `confidence`, evidence flags that produced it,
  and `role` (`primary`; `version` reserved for future duplicate
  support).

Invariants (enforced by policy, not schema, where noted):

- Claims per episode slot are stored as a list. Current policy treats
  2+ claims as a conflict record — both claimants kept, neither wins
  silently. A future duplicates policy may reinterpret extra claims as
  versions without a data-model migration.
- A file has at most one assignment. Files without one are
  "unassigned" with a recorded reason (replaces the SKIP/UNMATCHED
  status-string soup).
- Manual assignments have confidence 1.0 and survive re-scans of the
  same show match. Rematching to a different TMDB id discards the
  table (and manual assignments, which referenced the old show's
  slots); a toast informs the user.

Operations: `assign(file, episodes, origin)`, `unassign(file)`,
`resolve_conflict(episode, winner)`. Queries: `unassigned_files()`,
`unclaimed_slots()`, `conflicts()`, `claimant(season, episode)`.

Projection: `to_preview_items(...)` produces the `PreviewItem` list —
names via `build_tv_name`, target dirs, retargeted companions, status
strings, confidence. It is the only place status strings are minted.
`EpisodeMappingService` and the GUI mutate the table and reproject;
they stop hand-editing `PreviewItem` fields. Existing consumers of
`state.preview_items` (roster, queue bridge, completeness, history)
keep working unchanged.

`reconcile_scanned_episode_claims` (sibling same-show states) is
reworked to merge sibling tables instead of pattern-matching status
strings; cross-season duplicate specials become ordinary multi-claim
conflicts with full fix actions.

## 2. Matching and confidence policy

One shared resolution policy in the new module, used by both the
regular-season and specials scan paths.

Candidate generation per file:

- Number candidate: parsed `S##E##`/range, validated against the TMDB
  slots that exist for that season.
- Title candidate: fuzzy match of the embedded title against that
  season's TMDB episode titles (`fuzzy_match_special` promoted to all
  seasons, returning a match strength, not just a hit).

Resolution rules, in order:

1. Number and title agree → assign, confidence ≥ 0.95.
2. Strong title, disagreeing number (exact normalized match or unique
   unambiguous substring) → title wins, confidence ≈ 0.90.
3. Weak or ambiguous title with a valid number → number wins,
   confidence capped ≈ 0.60 → REVIEW.
4. Number only, no title → current floors: 0.86 season-relative, 0.5
   inferred; review threshold applies as today.
5. Title only, no usable number (extras folders, named specials) →
   assign if strong; otherwise unassigned with reason. No silent "OK"
   pass-through for unmatched specials.
6. Nothing → unassigned ("could not parse").

Multiple files resolving to the same slot become claims on that slot;
the table's conflict policy takes over. The filename-prefix duplicate
resolver (`resolve_duplicate_episodes`) is retired in favor of explicit
conflicts.

Specials-specific fixes:

- `episode_confidence` set explicitly on every specials assignment.
- A show folder containing only a specials folder scans Season 0;
  `infer_explicit_season_assignment` and the evidence collector treat
  season-0 evidence as evidence rather than noise.

Show-level matching:

- Specials-aware episode evidence feeds `score_tv_results` (S00E##
  files currently contribute nothing to disambiguation).
- Existing floors/caps in `_tv_scanner_postprocess.py` are kept but
  rebased onto assignment evidence flags instead of re-parsing
  filenames.
- Calibration goal: corroborated matches stop landing in review;
  uncorroborated ones keep landing there.

Parser: `extract_episode` extended to arbitrary multi-episode runs —
`S01E01E02E03E04`, `S01E01-04`, `S01E01-E04`, `1x01-1x04` — returning
the full list. Dash-range expansion keeps a sanity cap (span ≤ 12 and
within season bounds) to avoid `1080`-style false positives.

## 3. UI flow

The episode guide remains the central surface; rows render straight
from the assignment table. Every row gets a per-row actions menu (a
`⋯` button opening a `QMenu`) instead of the hardcoded Approve/Fix
pair. Future per-file operations (e.g. "Tracks…" for mkvmerge) are
additional menu actions — this is the extension point.

Row types and actions:

| Row | Shown when | Menu actions |
| --- | --- | --- |
| Assigned episode | Slot has one claim | Approve (if review), Reassign…, Unassign |
| Conflict episode | Slot has 2+ claims | Keep this file… (per claimant; losers become unassigned), Reassign claimant… |
| Missing episode | Slot has no claim | Assign file… |
| Unassigned file | File has no assignment | Assign to episode… (reason shown: "could not parse", "no title match", "lost conflict") |

Unassigned files move out of the summary line into their own visible
section at the top of the guide.

Episode picker (replaces the single-select `EpisodeChoiceDialog`); one
dialog serves both directions:

- Assigning a file: season-grouped multi-select checklist of episode
  slots. Each row shows `S01E05 – Title` plus current state
  (`missing` / `claimed by <file>`). Multi-selection requires same
  season and a contiguous run; the OK button disables with an inline
  explanation otherwise. Selecting a claimed episode warns that the
  other file becomes unassigned.
- Assigning to an episode (from a missing row): single-select list of
  unassigned files with parse evidence as hint text, plus a collapsed
  "all files" group for stealing an already-assigned file.

Both directions funnel into the same `EpisodeMappingService` table
operations, then reproject, resync check bindings, and refresh.

State gating: actions disabled while the show is queued or scanning.
Manual assignments render at 100% confidence with origin "manual".

### HiDPI requirement

All new GUI code (actions menu, picker dialog, unassigned section, row
widgets) must size exclusively through the built-in scale helpers in
`plex_renamer/gui_qt/_scale.py` — `px()`, `row_height()`, `icon()`,
`margins()` — with no bare pixel literals. Retrofitting widgets for
>100% display scaling has been a persistent pain point; new code must
be correct at non-96-DPI scales from the start.

## 4. Error handling and testing

Error handling:

- Table operations validate before mutating (unknown file/slot,
  cross-season or non-contiguous multi-episode selections raise
  `ValueError`); the GUI surfaces these via the existing warning-box
  pattern. The table is never left half-mutated.
- Projection is total: every `FileEntry` always yields exactly one
  `PreviewItem`, so files cannot vanish from the preview.
- Queue preflight keeps its contract (conflicts and reviews block
  submission) but reads the table's conflict/review queries instead of
  parsing status strings.

Testing (pytest, existing layout):

- Unit — table: assign/unassign/reassign, multi-claim conflict
  recording and resolution, role round-trip, contiguity/season
  validation, projection snapshots for every row state.
- Unit — policy: synthetic filename fixture matrix covering each
  resolution rule, including the reported cases: `s00e03 - Special A`
  with shuffled TMDB S0 ordering → maps to Special A; same-named
  specials in two season folders → conflict with both claimants;
  specials-only show folder → Season 0 scan; weak-title disagreement →
  REVIEW; `S01E01E02E03E04` and `E01-E05` runs; `1080p`/year
  false-positive guards.
- Unit — parser: extended multi-episode patterns plus regression of
  all current `extract_episode` cases.
- Integration: scan → table → projection → `build_rename_job_from_state`
  produces identical `RenameOp`s to today for well-behaved fixtures
  (guards the queue boundary), plus new fixtures for fixed behaviors.
- GUI smoke: extend `tests/test_gui_qt_smoke.py` via
  `scripts/test-smoke.cmd` — actions menu present per row type, picker
  contiguity gating, both assignment directions, conflict resolution.
- Confidence calibration values live as named constants in one module,
  with the same comment-pointer convention as `MOVIE_FLOOR_*`.

## Out of scope

- mkvmerge track operations (architecture room only).
- Duplicate/version naming and UI (schema room only).
- Alternate episode-order sources (TVDB).
- Movie matching changes beyond shared-helper fallout.
