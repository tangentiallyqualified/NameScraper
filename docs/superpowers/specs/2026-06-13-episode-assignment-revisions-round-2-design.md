# Episode Assignment Revisions, Round 2 — Design

**Status:** Approved (design), pending implementation plan.
**Date:** 2026-06-13
**Predecessor:** `docs/superpowers/specs/2026-06-12-episode-assignment-revisions-design.md`
(Tasks 1–6 of the predecessor are shipped; this round fixes residual specials/title defects
those changes exposed, plus two assignment-action refinements.)

## Goal

Fix four reproduced specials / title-matching defects and add two assignment actions:

1. Adventure Time S00E01 "(Pilot)" forced into Review.
2. Adventure Time S00E09 / S00E13 "Frog Seasons … (Again)" colliding on one slot.
3. Animaniacs Featurettes (no episode number) forced into Review despite a near-exact special title.
4. Tigtone whole-season off-by-one mis-mapping + a duplicate E10 claim + a pilot that belongs in S0.
5. A dedicated **"Assign to more…"** action (extend a file to a contiguous second episode) split out
   of Reassign.
6. **Share** an already-matched file into an unmatched (missing) episode without unassigning it from
   its current episode.

No data-model changes. Builds on the existing `EpisodeAssignmentTable` + `resolve_file` policy +
`apply_confidence_adjustments` floors/caps, and the table-backed `EpisodeMappingService`.

## Reproduced diagnosis (real TMDB + real files)

All findings below were reproduced against live TMDB data and the actual files on `P:\in progress files`.
The episode auto-accept threshold is the default **0.85**. A row shows **Review** only when an
assignment is auto-origin, unapproved, and `confidence < 0.85`.

### Adventure Time (id 15260) — Season 0

TMDB S0 numbering matches the release **exactly** (E1 "Adventure Time (Pilot)", E9 "Frog Seasons: Spring",
E13 "Frog Seasons: Spring (Again)"). Yet the real scan produced:

- **S00E01 → Review (0.60).** `extract_episode` returns the title `"Adventure Time"` — `clean_name`
  stripped the `(Pilot)` parenthetical. The bare phrase substring-matches E1/E3/E16/E17, so the title
  match collapses to ambiguous (`None`) → rule-3 ambiguous → 0.60.
- **S00E09 + S00E13 → Conflict on E9.** `extract_episode` returns `"Frog Seasons Spring"` for the E13
  file — `(Again)` was stripped — which now matches E9 **exactly**, so the exact-override (predecessor
  Task 2) routes E13 to E9 (0.90), colliding with the real E9 file (0.96).

**Single shared root cause:** the title cleaner discards descriptive parentheticals
(`(Pilot)`, `(Again)`) along with quality tags.

### Animaniacs (id 82) — Featurettes folder (extras → Season 0)

Files have **no episode number** and a `(480p DVD x265 HEVC 10bit AAC 2.0 Ghost)` suffix. Real resolution
of "The Writers Flipped, They Have No Script":

- Title evidence comes from the **raw stem fallback** in `_tv_scanner_normal._resolve_into_table`
  (quality tags not stripped) → substring-matches the correct special E2 at strength 0.9 → rule-5
  title-only → **0.88** (which would pass).
- `apply_confidence_adjustments` then runs `extract_source_title_prefix` on the raw filename; the
  `(480p…)` suffix lets the prefix regex latch the number "480", so it extracts the **episode title
  itself** as a "show prefix", finds it ≠ `animaniacs`, and applies `CONTRADICTORY_PREFIX_CAP` →
  **0.45 → Review.**

(Note: the 4th featurette "They're Totally Insan-y…" is a genuine release typo vs TMDB "Insane-y"; it
will not title-match and is expected to need manual assignment. Out of scope.)

### Tigtone (id 86501) — flat `Tigtone.S01…` folder (normal path, season 1 only)

The release bundles the pilot as S01E01, so every file is numbered **+1** vs TMDB S1. Real scan:

| Release file | TMDB title match | Current result |
|---|---|---|
| S01E01 "…the Pilot" | **S0E1** "Tigtone and the Pilot" @0.9 | S1E1, **0.88 OK** (number; lifted by compatible-prefix floor) |
| S01E02 "…His Fellowship Of" | S1E1 @0.9 (substring) | S1E2, **0.88 OK** (number kept; substring can't override under Task 2) |
| S01E03–E09 | each → S1E(n-1) @0.9 | S1E(n), **0.88 OK** (all silently off-by-one) |
| S01E10 "…Singing Blade" | S1E9 @0.9 | **Conflict** S1E10 (0.60) |
| S01E11 "…vs Nothing" | S1E10 @0.9 (E11 not in S1) | **Conflict** S1E10 (0.88) |

Two compounding problems: (a) strong-but-inexact title matches cannot override a wrong number
(Task 2 restricted override to exact), and the **compatible-prefix floor (0.88) silently lifts the wrong
number mappings to OK**; (b) the pilot's title matches only a **Season-0** special, which the per-season
normal path never consults.

## Decisions (from brainstorming)

- **Feature shape:** the two UX requests are one operation ("add episode(s) to a file's run without
  dropping its current ones"), exposed from two entry points.
- **Add range:** **contiguous only** (adjacent extension). Non-contiguous / gapped additions
  (e.g. recovering E05 on an `S01E03E05` file mapped only to E03) are **out of scope** this round.
- **Title vs number:** a strong-but-inexact (substring) title match **wins over the number but lands in
  Review** (not silently auto-accepted).
- **Tigtone pilot:** **auto cross-season pull** — a regular-folder file whose title strongly matches a
  Season-0 special (and not its own season) is routed to S0, in Review.

## Design

### Part A — Engine: specials & title-matching correctness

#### A1. Preserve descriptive parentheticals in extracted episode titles

The episode **title** must retain plain-word parentheticals (`(Pilot)`, `(Again)`, `(Part 2)`) while
still dropping **quality / source / year** parentheticals (those containing a resolution/codec/release
token or a 4-digit year). Episode-*number* parsing continues to use the fully-cleaned name.

- **Locus:** a small dedicated title-evidence cleaner used by `extract_episode` for the returned title
  (and by A2's fallback). **Not** a change to the widely-used `clean_name`, to avoid disturbing
  show-name matching.
- **Acceptance:**
  - `extract_episode("Adventure Time (2008) - S00E01 - Adventure Time (Pilot) (480p TVRip x265 ImE).mkv")`
    → title contains `Pilot` (e.g. `"Adventure Time (Pilot)"`); quality/year groups removed.
  - `extract_episode("… - S00E13 - Frog Seasons Spring (Again) (1080p BluRay x265 ImE).mkv")`
    → title contains `Again`.
  - `resolve_file` for the E1 file → exact match E1 → `CONF_AGREE` (0.96), OK.
  - `resolve_file` for the E13 file → exact match E13 → `CONF_AGREE` (0.96), OK; **no E9 conflict**.

#### A2. Clean the specials title-evidence fallback

`_tv_scanner_normal._resolve_into_table` currently builds title evidence from the **raw**
`file_path.stem` when there is no parsed title. Route that stem through the same quality-stripping
cleaner (A1) and store the cleaned evidence as the file entry's title evidence so downstream floors and
adjustments see a clean title.

- **Acceptance:** for "The Writers Flipped, They Have No Script (480p DVD x265 …).mkv", the title
  evidence has no quality tokens and matches Animaniacs S0 E2 at strength 1.0 (exact).

#### A3. Don't apply the contradictory-source-prefix cap to Season 0

Guard the contradictory-prefix logic in `apply_confidence_adjustments` with `assignment.season != 0`
(mirrors Task 3's existing season-0 floor guards). Specials filenames legitimately have no show-name
prefix, so a "non-matching prefix" is not evidence against the match.

- **Acceptance:** a season-0 title-only assignment whose filename's leading text differs from the show
  name keeps its resolved confidence (≈0.88) instead of being capped to 0.45. The Animaniacs featurette
  ends at **OK**.

#### A4. Title-wins → Review, with cap survival (supersedes Task 2 exact-only)

Relax rule 2 so a **strong** title match (strength ≥ `STRONG_TITLE_STRENGTH`, which includes substring
0.90) for a different episode overrides the parsed number:

- **Exact** title override (strength == 1.0): keep `CONF_TITLE_WINS` (0.90) → OK (unchanged from Task 2).
- **Inexact** strong override (0.85 ≤ strength < 1.0): assign the title's episode at a new
  sub-threshold confidence `CONF_TITLE_WINS_INEXACT` (≈ 0.70) and tag the evidence (e.g.
  `"title-override-inexact"`). `apply_confidence_adjustments` must **cap such assignments last** (after
  all floors), below the threshold, so the compatible-prefix / coverage floors cannot lift them to OK.
  This mirrors the existing `CONTRADICTORY_PREFIX_CAP` "cap last" mechanism.

- **Acceptance:**
  - `resolve_file(parsed=(2,), raw_title="…Fellowship Of", season_titles=S1, season=1)` where the title
    substring-matches S1E1 → `episodes == (1,)`, `confidence == CONF_TITLE_WINS_INEXACT`, and the
    confidence stays `< 0.85` after `apply_confidence_adjustments` even with a compatible source prefix.
  - Tigtone E02–E10 map to the correct S1 episode in Review; E11 → S1E10; **the S1E10 conflict is gone.**
  - **Regression:** "As Told By Ginger – S02E06 – Sibling Revile-ry" stays on E06 (its title matches its
    own number → rule 1 agree, not an override). Add a fixture confirming this. Update the single Task-2
    unit test (`test_substring_offnumber_does_not_override_valid_number`) whose expectation intentionally
    flips to "title episode, in review".

#### A5. Auto cross-season special pull

In the normal per-season path, after computing a file's own-season resolution, if **all** of:

- the own-season resolution is **not** a confident title agreement (i.e. number-only / disagreeing /
  weak), and
- the file's title **strongly matches a Season-0 special** (exact or strong substring), and
- the file's title does **not** confidently match its own season,

then route the file to Season 0 (register S0 slots for the check) at a Review-level confidence.

- **Locus:** `_tv_scanner_normal` (`build_normal_table` already has `ensure_s0_titles()`; pass S0 titles
  into the per-file resolve and re-target to S0 when the cross-check wins).
- **Acceptance:** Tigtone S01E01 "…the Pilot" → **S00E01** (Review); the S1E1 collision with the
  Fellowship file is gone. A regular episode with a normal own-season title agreement is **not** pulled
  to S0.

### Part B — UX: assignment actions (contiguous-only)

#### B1. "Assign to more…" action

Add an `assign_to_more` row action on matched / review / conflict file rows (alongside Reassign /
Unassign). It offers the **adjacent** episode slot(s) (the existing run's neighbors that exist as TMDB
slots) and **extends** the file's run without dropping its current episodes, reusing
`EpisodeMappingService.assign_or_extend_file` (which already unions contiguous runs and otherwise
replaces — here it is only ever called with a contiguous neighbor). Reassign remains pure replace.

- **Locus:** `_media_workspace_preview._episode_row_actions` (add the action),
  `_media_workspace_actions.handle_episode_row_action` (handle it).
- **Acceptance:** a file at S01E03 + "Assign to more…" → choose E04 → file maps to E03–E04;
  its current E03 assignment is retained.

#### B2. Make "share" explicit on missing-episode rows

The missing-row "Assign file…" picker already lists already-assigned files and calls
`assign_or_extend_file` (extend if contiguous, else replace). Make sharing **discoverable and safe**:

- In `EpisodeAssignDialog`, label an already-assigned file whose run is **contiguous-adjacent** to the
  target episode as *"share / extend (keeps current)"*, distinct from non-adjacent assigned files
  labeled *"reassign (replaces)"*.
- Confirm that selecting an adjacent assigned file **extends** (does not unassign its prior episode).

- **Acceptance:** an episode E04 is missing; the picker offers the file at E03 as "share / extend";
  choosing it maps that file to E03–E04 (E03 retained).

## Testing

- **TDD per fix** with unit fixtures built from the real TMDB titles captured in this spec
  (`tests/test_episode_resolution.py`, `tests/test_consolidated_assignments.py` /
  `tests/test_tv_scanner_normal.py` as appropriate, `tests/test_episode_mapping_projection.py`,
  the Qt workspace/widget tests).
- **Real-folder reproduction sweep** confirming the exact transitions in this spec:
  Adventure Time S0 (S00E01 OK, no E9 conflict), Animaniacs Featurettes (The Writers Flipped → OK),
  Tigtone (E01 → S00E01 review; E02–E11 correct; no E10 conflict), and the As Told By Ginger E06
  regression.
- Full suite (`python -m pytest -q`) + Qt smoke (`scripts/test-smoke.cmd`) green.

## Out of scope

- Non-contiguous / gapped multi-episode additions (e.g. `S01E03E05` mapped only to E03).
- Release titles that genuinely differ from TMDB (e.g. Animaniacs "Insan-y" vs "Insane-y") — these
  remain manual assignments.
- Any change to the show-level (movie/series) matching threshold or `clean_name` semantics for show
  names.
