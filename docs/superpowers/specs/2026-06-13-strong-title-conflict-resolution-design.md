# Strong-Title Conflict Auto-Resolution — Design

**Status:** Approved (design), pending implementation plan.
**Date:** 2026-06-13
**Predecessor:** `docs/superpowers/specs/2026-06-13-episode-assignment-revisions-round-2-design.md`
(Surfaced by the round-2 real-folder reproduction sweep — the As Told By Ginger regression check.)

## Goal

When an episode slot is claimed by two auto-assigned files — one via an **exact title match** and the
other via a **bare release number** — auto-resolve the conflict in favour of the exact-title claimant
instead of surfacing a hard conflict. The number-only loser becomes unassigned (`REASON_LOST_CONFLICT`)
so it is surfaced for manual placement.

No data-model changes. Builds on the existing `EpisodeAssignmentTable` conflict machinery
(`conflicts()`, `resolve_conflict()`, `REASON_LOST_CONFLICT`) and the post-build
`apply_confidence_adjustments` pass.

## Reproduced diagnosis (real TMDB + real files)

Reproduced against live TMDB and the real folder
`P:\data\downloads\in progress files\As Told By Ginger (2000) … \Season 2`.

TMDB id **1760** ("As Told by Ginger") Season 2 has **24 episodes**; this release's `Season 2` folder
holds the same episodes **offset by +4** (TMDB's first four S2 episodes live in another folder). The
release filenames are cleanly numbered `S02E01…E20`, but each file's **title** matches TMDB at +4:

| Release file | Real episode (by title) | TMDB slot | Resolution |
|---|---|---|---|
| S02E01 "Never Can Say Goodbye" | that episode | TMDB **E05** | exact title → E05 (OK) |
| S02E06 "Sibling Revile-ry" | that episode | TMDB **E10** | exact title → E10 (OK) |
| S02E10 "April's Fools" | "April Fools" (release variant) | TMDB **E14** | title **no match** → falls back to release number **E10** |

Because "April's Fools" (release E10) does not match TMDB's "April Fools" (E14), it resolves via the
number-only rule to **E10** — the slot already correctly won by "Sibling Revile-ry" via an exact title
match. The two collide into a hard **conflict on S02E10**.

This behaviour is **pre-existing** (the exact-title override predates the round-2 work; the sweep
confirmed identical output at the pre-round-2 commit `3bc024d`). The round-2 design's regression note
("Sibling Revile-ry stays on E06") was based on an incorrect assumption about the TMDB data — that title
is in fact TMDB E10, not E6.

**Decision (from brainstorming):** titles are ground truth, so the +4 re-mapping is correct. The only
defect is the spurious conflict: a weak number-only claim must not be allowed to collide with a confident
exact-title claim for the same slot.

## Design

### Auto-resolve evidence-asymmetric conflicts

Add a private helper in `plex_renamer/engine/_episode_resolution.py`:

`_auto_resolve_strong_title_conflicts(table: EpisodeAssignmentTable) -> None`

For each conflicted slot returned by `table.conflicts()`:

- **Winners** = claimants whose `evidence` contains `"title-agree"` (rule 1) or `"title-strong"`
  (rule 2, exact override). These represent a file whose title exactly matches this slot.
- If there is **exactly one** winner **and every other claimant on the slot lacks** exact-title
  evidence (none of `"title-agree"` / `"title-strong"`), award the slot to the winner via
  `table.resolve_conflict(season, episode, winner_file_id=<winner>)`, which marks the other claimants
  `REASON_LOST_CONFLICT`.
- Otherwise leave the conflict untouched for manual resolution.

**Locus / ordering:** call the helper at the **start** of `apply_confidence_adjustments`, before it
computes `conflicted = table.conflicted_file_ids()` and applies floors. This way the surviving winner is
no longer conflicted and receives normal confidence treatment, and the unassigned loser is excluded from
the floor passes. Both scan pipelines (normal and consolidated) already call
`apply_confidence_adjustments`, so both benefit with no call-site changes.

### Safety guards

- **Exactly one** exact-title claimant is required. Genuine ambiguities are left as conflicts: two or
  more exact-title claimants (e.g. duplicate files), or a slot whose claimants are all number-only.
- `"title-strong-inexact"` (rule 2b substring/review) is **deliberately excluded** from "winner"
  evidence — an uncertain substring override must not auto-evict a competitor.
- `ORIGIN_MANUAL` claims are never auto-evicted; if any claimant on the slot is manual, the slot is left
  for manual resolution (the user's choices win).

## Acceptance

- A slot with one exact-title (`title-strong`/`title-agree`) claimant and one number-only claimant →
  title claimant keeps the slot (assignment intact); number-only claimant becomes unassigned with
  `REASON_LOST_CONFLICT`; the slot is no longer in `table.conflicts()`.
- A slot with two number-only claimants, or two exact-title claimants, or one `title-strong-inexact`
  vs one number-only → **still a conflict** (unchanged).
- A slot where a number-only **manual** claim competes with an auto exact-title claim → **still a
  conflict** (manual not evicted).
- Real-folder sweep: As Told By Ginger S2 has **no S02E10 conflict** ("Sibling Revile-ry" stays OK on
  E10; "April's Fools" is unassigned/needs-manual). Adventure Time, Animaniacs, and Tigtone results are
  **unchanged**.

## Testing

- **TDD** with unit fixtures in `tests/test_episode_resolution.py` (`TestConfidenceAdjustments` or a new
  `TestConflictResolution` class) covering each acceptance bullet above against `apply_confidence_adjustments`.
- A synthetic regression mirroring the As Told By Ginger E10 case (one file exact-title→E10, one file
  number-only→E10).
- Correct the now-inaccurate comment on the existing `test_title_matching_own_number_is_not_overridden`
  fixture (reframe as a generic "title agreeing with its own number is rule-1 agreement" principle test;
  drop the false claim that real As Told By Ginger S02E06 is "Sibling Revile-ry").
- Full suite (`python -m pytest -q`) + Qt smoke (`scripts/test-smoke.cmd`) green, plus a re-run of the
  real-folder reproduction sweep.

## Out of scope

- Fuzzy / near-miss title matching ("April's Fools" → "April Fools"); the genuinely-mismatched file
  stays a manual assignment, consistent with the round-2 policy for release-vs-TMDB title differences
  (e.g. Animaniacs "Insan-y" vs "Insane-y").
- Whole-season offset detection — the existing "titles win" exact-override already re-maps offset
  seasons correctly; this design only removes the spurious conflict the leftover number-only file caused.
- Any change to conflict resolution for manual assignments or to the conflict UI.
