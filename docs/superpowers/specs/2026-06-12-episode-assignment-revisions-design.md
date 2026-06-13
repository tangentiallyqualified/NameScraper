# Episode Assignment Revisions — Design

Date: 2026-06-12
Status: Approved design, pending implementation plan
Scope: Follow-up revisions to the 2026-06-11 episode-assignment redesign.
TV episode matching, confidence policy, specials handling, roster
categorization, and the episode fixing UI. Movies are out of scope except
for the shared roster-routing helper.

## Background

The 2026-06-11 episode-assignment redesign
(`docs/superpowers/specs/2026-06-11-episode-assignment-redesign-design.md`)
introduced the first-class `EpisodeAssignmentTable`, the shared
`resolve_file` policy, and the assignment-driven episode guide. In use,
seven issues surfaced. Six are real defects; one (problem-filter) was a
false alarm and is dropped. The fixes below build on the existing
architecture — no data-model changes.

## Problems (as reported)

1. A file auto-matched to one episode cannot be extended to also cover a
   second contiguous episode without first unassigning it
   (e.g. a "Bargaining" file vs. TMDB's "Bargaining (1)" / "Bargaining
   (2)").
2. Chained multi-episode filenames lose episodes past the first range
   segment: `ChalkZone.S01E01-E02-E03...` maps to E01–E02 only.
3. Shows with conflicting files or unmapped primary files are still filed
   under "Matched". "Matched" should mean *clean*: no conflicts, no
   unmapped primaries, all episode rows at/above threshold. The single
   "Needs Review" bucket should split into two headers.
4. (Dropped — reporter confirmed the per-show problem filter still works.)
5. Specials fail to map in mixed/complete-series folders (Aqua Teen
   Hunger Force complete series; Ed, Edd n Eddy specials).
6. Special and regular matching trust the parsed episode number at face
   value instead of weighting the embedded title: a special titled
   "The Grim Adventures of the KND" (`S00E08`) maps to TMDB's `S00E08`
   ("How to Draw Eddy"); a regular `S02E06` "Sibling Revile-ry" maps to
   `S02E10` despite the exact title match.
7. An unmapped primary file cannot be assigned to a special.

## Decisions (from brainstorming)

- **Review routing:** when a show has both an uncertain TMDB show match
  and episode-level problems, **Review Match wins** — it appears only
  under Review Match until the match is settled.
- **Extend assignment:** the `Reassign…` multi-select picker opens with
  the file's current episode(s) pre-checked, and assigning a file from a
  missing-episode row **adds** to the file's run when the target is
  contiguous with its existing assignment instead of silently replacing.
- **Specials trust:** a special resolved on the `S00E##` number with no
  corroborating title match is accepted (mapped) but forced into review
  via a capped confidence. A strong title match still wins and may
  auto-accept.

## 1. Parser — chained multi-episode ranges (issue 2)

File: `plex_renamer/_parsing_episodes.py` (`extract_episode`).

The current `S##E##` regex captures a single optional range-end group, so
in `S01E01-E02-E03` the `-E03` segment falls through into the title and is
lost. Extend extraction so **all** chained episode segments are collected
into one contiguous run:

- `S01E01E02E03E04` (already works — keep).
- `S01E01-E02-E03`, `S01E01-E02-E03-E04` (dash-`E` chains).
- `S01E01-04` / `S01E01-E04` (range to an end — keep).
- `1x01-1x02-1x03` and `1x01-02-03` (the `NxNN` mirror).

Rules preserved:
- `_MAX_RANGE_SPAN` (12) sanity cap on expanded ranges stays, to guard
  against `1080`-style false positives.
- Digit-leading-title guards stay: a spaced bare-digit (` - 04 Title`) is
  still a title, not a range; a bare digit immediately followed by a
  letter is not a range end.
- `extract_season_number` keeps returning the single season int; chained
  episodes never imply multiple seasons.

The expanded run is validated downstream by `EpisodeAssignmentTable.assign`
(contiguity + slot existence), so a chained run that overflows a season
boundary still falls back to `REASON_AMBIGUOUS_RUN` rather than raising.

## 2. Roster — two review subcategories (issue 3)

Files: `plex_renamer/gui_qt/widgets/_media_helpers.py`
(`roster_group`, `state_status`, `state_status_tone`),
`plex_renamer/gui_qt/widgets/_media_workspace_roster.py`
(`_desired_entries` group list).

Replace the single `review` group with two:

| Group key | Header | Routes when |
| --- | --- | --- |
| `review-match` | Review Match | `state.needs_review`, manual-match-needed, or movie duplicate (`state.duplicate_of`) |
| `review-episodes` | Review Episode Matching | show match is settled but the assignment table has any conflict, any unmapped **primary** file, or any episode row below the auto-accept threshold |

Routing precedence (highest first): `queued` → `unmatched`
(`show_id is None`) → `review-match` → `review-episodes` →
`plex-ready` → `matched`. (Movie `duplicate` keeps its existing slot
under the movie media type; for movies `duplicate_of` already routes to
`duplicate`, so the `review-match` duplicate clause applies only where
that earlier branch does not.)

A show reaches **`matched`** only when: it has a show id, is not in
show-match review, and its assignment table has **no conflicts, no
unmapped primary files, and no below-threshold episode rows**.

New shared predicate (next to `roster_group`) so the same definition
backs `roster_group`, `state_status`, `state_status_tone`, and the queue
gating already in `is_state_queue_approvable`:

- `has_episode_problems(state) -> bool`: True if `state.assignments` has
  `conflicts()`, has any unmapped file that is a *primary* (non-companion)
  video, or any `preview_items` row `is_episode_review`. When
  `state.assignments is None` (legacy/unscanned), fall back to the current
  `is_episode_review` check only.

"Primary" excludes companion/orphan files: a file is an unmapped primary
when it is in `table.unassigned_files()` and its preview item is not a
companion (mirrors `EpisodeMappingService._is_episode_mapped` /
`unmapped_primary_files`). Reuse `EpisodeMappingService.build_episode_guide`'s
`unmapped_primary_files` count where a service instance is available to
avoid divergent definitions.

`_desired_entries` group order becomes:

```python
groups = [
    ("queued", "Queued"),
    ("plex-ready", "Plex Ready"),
    ("matched", "Matched"),
    ("review-match", "Review Match"),
    ("review-episodes", "Review Episode Matching"),
    ("unmatched", "No Match Found"),
    ("duplicate", "Duplicates"),
]
```

`state_status` / `state_status_tone` gain the two labels ("Review Match",
"Review Episode Matching") with the existing accent tone so the row badge
matches the bucket.

## 3. Unify the consolidated/mixed-folder scan path (issues 5, 6, 7)

Files: `plex_renamer/engine/_tv_scanner.py`
(`_build_consolidated_preview`), `plex_renamer/engine/_tv_scanner_normal.py`
(shared helpers), `plex_renamer/engine/_tv_scanner_consolidated.py`,
`plex_renamer/engine/episode_assignments.py`
(`ingest_preview_items` retirement).

Today `build_normal_table` runs the shared `resolve_file` policy per file,
but `_build_consolidated_preview` builds `PreviewItem`s with the legacy
matcher and then `ingest_preview_items` trusts each item's parsed number at
face value. It also registers slots only for the seasons present in
`tmdb_seasons`, which can omit Season 0. This is the root cause of the
mixed-folder specials failures (5), the title-not-weighted mismatches in
multi-season folders (6), and the inability to assign to a special (7).

Change the consolidated path to build the table the same way the normal
path does, with two consolidated-specific behaviors retained:

1. **Register every TMDB season's slots, including Season 0.** Fetch the
   specials season (as `build_normal_table.ensure_s0_titles` already does)
   and register its slots so specials can be matched *and* manually
   assigned. Registering S0 slots is what unblocks issue 7 — the existing
   `episode_slot_choices` already lists S0 slots once they exist, and the
   unmapped-file "Assign to episode…" action already targets them.
2. **Absolute → (season, episode) mapping stays** for the
   absolute-numbered case (the reason the consolidated path exists), but
   the resulting candidate season/episode is **reconciled through the
   shared policy** against that season's TMDB titles before assignment:
   - Regular files: feed `resolve_file` with the parsed number(s) *for the
     mapped season's slots* plus the embedded title, so title evidence can
     correct or corroborate the absolute mapping using the same rules as
     the normal path.
   - Files that parse as `S00E##` or live in a specials/extras folder are
     routed through the specials policy (section 4), not absolute
     position.

After building, the consolidated path runs `apply_confidence_adjustments`
(already called) and projects via `project_preview_items` (already called)
— unchanged. `ingest_preview_items` and the legacy
`build_consolidated_preview` item-builder are removed once the table-first
consolidated builder replaces them; if `build_consolidated_preview` still
supplies the absolute-offset computation, that computation is extracted
into a helper the new builder calls (no behavioral duplication).

Note for implementation: confirm by reproduction whether
"As Told By Ginger (Season 1-3)" actually takes the consolidated path
(flat-folder + multi-season detection in `_tv_scanner.py` around
lines 140–166) or the normal path. If normal, its `S02E06 → S02E10`
misfire is purely the section-4 title-vs-number guard; if consolidated,
this unification plus section 4 both apply.

## 4. Resolution policy — specials trust and title-vs-number (issues 5, 6)

File: `plex_renamer/engine/_episode_resolution.py`.

### Specials number-only → forced review

Add a season-0 branch to the number-only paths (rules 3-ambiguous and 4).
When `season == 0` and the assignment is being made on the number with no
title agreement, cap confidence below the auto-accept threshold so the row
lands in Review Episode Matching:

- New constant `CONF_SPECIAL_NUMBER_ONLY` (≈ 0.50, below the default
  threshold), used in place of `CONF_NUMBER_RELATIVE` / `CONF_NUMBER_INFERRED`
  when the resolved season is 0 and evidence carries no `title-*` flag.
- Rules 1 (number+title agree), 2 (strong title overrides), and 5 (strong
  title, no number) are unchanged for season 0 — a strong title match
  still wins and can auto-accept.

`resolve_file` does not currently receive the season number; thread the
mapped season (or an `is_special: bool`) into `resolve_file` so the
season-0 branch can fire. The single call site in `_tv_scanner_normal._resolve_into_table`
already knows `season_num`; pass it through. The new consolidated builder
(section 3) passes the mapped season too.

### Title-vs-number guard (no false strong override)

Rule 2 ("strong title overrides a disagreeing number") must not fire when
the parsed number's own slot also matches the title. Concretely, in
`resolve_file`, before returning the rule-2 override:

- If `title_match.episode not in valid_numbers` AND the title *also*
  matches one of the `valid_numbers` slots at >= the rule-1 strength,
  prefer the number (rule 1). Exact number+exact title agreement always
  wins over a competing substring/part-number title hit elsewhere.

Tighten `match_title_in_titles` substring candidacy so a short or partial
overlap can't be promoted to a strong (`_TITLE_SUBSTRING`) hit:

- Keep `_MIN_SUBSTRING_LEN` / `_MIN_KEY_SUBSTRING_LEN`, but require the
  overlap to be the *containment* of the shorter normalized string within
  the longer (current behavior) **and** that the matched key is not itself
  a strict substring of a different candidate key that the input matches
  more fully — i.e. when multiple keys contain the input, the existing
  "2+ candidates → None (ambiguous)" guard already applies; ensure the
  `S02E06`/`S02E10` case is covered by a regression fixture, and if it
  resolves via part-number base matching, require the part number to match
  (`by_part` path) rather than accepting the first base hit.

The calibration constants stay co-located at the top of the module with
the existing pointer comment to this spec.

## 5. Assignment UI — extend without unassigning (issue 1)

Files: `plex_renamer/gui_qt/widgets/_media_workspace_actions.py`
(`handle_episode_row_action`),
`plex_renamer/app/services/episode_mapping_service.py` (`assign_file`),
`plex_renamer/gui_qt/widgets/episode_assign_dialog.py` (verify
pre-check).

Two flows:

- **From the file's row — `Reassign…`:** the picker already preselects the
  file's current episodes (`preselected` in `handle_episode_row_action`).
  Verify the pre-check renders and that selecting an adjacent episode
  yields a contiguous multi-run that `assign_file` accepts. No new code
  expected beyond a covering test; fix if the preselect is dropped for
  season-0 or claimed slots.
- **From a missing-episode row — `Assign file…`:** currently
  `service.assign_file(state, target, season=row.season, episodes=[row.episode])`
  replaces the picked file's assignment. Change to **extend** when the
  target episode is contiguous with the picked file's existing run in the
  same season:
  - New service method `assign_or_extend_file(state, preview, *, season, episode)`:
    if the file already has an assignment in `season` whose run is
    contiguous with `episode` (i.e. `episode == min(run) - 1` or
    `episode == max(run) + 1`), assign the union run; otherwise assign just
    `[episode]` (current replace behavior, with displacement).
  - `handle_episode_row_action`'s `assign_file` branch calls the new
    method. Cross-season or non-contiguous targets keep replacing and
    surface the existing displacement; conflicts surface via the existing
    `ValueError`/warning-box path.

Manual extensions are still `ORIGIN_MANUAL` (confidence 1.0) and survive
re-scans via `carry_over_manual_assignments` (multi-episode runs already
carried as a unit).

## 6. Error handling and testing

Error handling:
- All table mutations keep validating before mutating; bad runs raise
  `ValueError` surfaced through the existing warning-box pattern. The
  table is never left half-mutated.
- Projection stays total: every `FileEntry` yields exactly one
  `PreviewItem`.
- Queue preflight contract unchanged (conflicts and reviews block
  submission), now reading the table queries.

Testing (pytest, existing layout):
- **Parser** (`tests/...` extending current `extract_episode` coverage):
  `S01E01-E02-E03`, `S01E01-E02-E03-E04`, `1x01-1x02-1x03`, `1x01-02-03`,
  plus regression of every current case and the `1080p`/year/`x265`
  false-positive guards.
- **Policy** (`tests/test_episode_resolution.py`): specials number-only →
  capped confidence below threshold (forced review); strong title still
  wins for season 0; number+title-agree is not overridden by a competing
  substring title hit (the `S02E06`/`S02E10` regression); the
  `S00E08`/"Grim Adventures" specials title case.
- **Consolidated path** (engine integration): a mixed/complete-series
  fixture registers Season 0 slots, title weighting applies, and an
  unmapped special can be assigned via `episode_slot_choices`; queue
  boundary (`build_rename_job_from_state` → `RenameOp`) parity preserved
  for well-behaved fixtures.
- **Roster classification** (unit): a show with a conflict, a show with an
  unmapped primary, and a show below threshold each route to
  `review-episodes`; a show with both a show-match concern and episode
  problems routes to `review-match`; a clean show routes to `matched`.
- **Assignment UI** (GUI smoke via `scripts/test-smoke.cmd`): `Reassign…`
  opens pre-checked; assigning a file from a contiguous missing-episode
  row extends the run instead of replacing; non-contiguous still replaces.
- Calibration constants remain named in `_episode_resolution.py` with the
  spec pointer comment.

## Out of scope

- Issue 4 (problem filter) — confirmed working, no change.
- mkvmerge track operations.
- Duplicate/version naming and UI.
- Alternate episode-order sources (TVDB).
- Movie matching changes beyond the shared roster-routing helper.
