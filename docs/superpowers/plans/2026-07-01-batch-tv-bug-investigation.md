# Batch TV Bug Investigation — Root Causes (2026-07-01)

**Status (2026-07-02): all RCs fixed, regression-tested, and re-validated
against the real library (zero unresolved conflicts across 21 scanned shows;
repro harness deleted).**
RC1 `tests/test_umbrella_season_merge.py`; RC2+RC11 `tests/test_offset_inference.py`;
RC3-RC5 `tests/test_extras_and_prefix_fixes.py`; RC6, RC8-RC10
`tests/test_conflict_resolution.py`; RC7 `tests/test_episode_resolution.py`
(TestSingleNumberSegmentedRun); RC12-RC13 + Brak-Show note
`tests/test_scan_improvements.py`; RC14 `tests/test_parsing_edgecases.py`
(year-range start); RC15 `tests/test_queue_output_targets.py`.

RC6 follow-up found in re-validation: TPB's TMDB S00E03 is literally titled
"Trailer Park Boys", so show-name-prefixed file titles inexact-matched it and
rode over valid S11 numbers. Fixed by rejecting specials matches whose matched
title normalizes to the show name (`_tv_scanner_normal.py`), keeping the
legitimate pilot/special pulls intact.

Manual note: the Reno 911 "(2003) Season 1-8" primary only holds S7/S8 files
on disk; seasons 1-6 live in the nested "Complete Series" copy now labeled
duplicate — unmark it before executing if S1-6 should be renamed.

Reproduced with `scripts/repro_batch_bugs.py` (throwaway harness, delete when done) against
`P:\data\downloads\in progress files`. Raw outputs: `%TEMP%\repro_discover2.txt`,
`%TEMP%\repro_scan1.txt` (anime/Watchmen/Gundam), `%TEMP%\repro_scan2.txt`
(Animaniacs/ATHF/MASH/Rawhide/Squidbillies/Reno), `%TEMP%\repro_scan3.txt`
(Catscratch/Futurama/Jimmy/RocketPower/Rugrats/DS9/TNG/TPB).

## RC1 — Umbrella season collapse (Archer, Futurama missing episodes)
`infer_explicit_season_assignment` gives multi-season umbrella folders named with a
range ("S01-S14", "Season 1-7", "S01-11") `season_assignment=1` even though they have
direct season subdirs. When a same-show sibling exists (Archer S09 folder, Futurama
S08–S13 folders), `merge_season_siblings` treats the umbrella as covering ONLY season 1:
`expanded_season_folders()` returns `{1: <umbrella>\Season 01}` → seasons 0,2..14 dropped.
Evidence: merged Archer state `season_folders={9:…, 1:…\Season 01}`; Futurama
`{1:…\Season 1, 8:…,9:…,10:…,11:…,12:…,13:…}` with S02–S07 unclaimed after scan.
Fix: don't infer an explicit season assignment for folders with direct season subdirs
(range in name ≠ single season); make `expanded_season_folders` enumerate direct season
subdirs when `has_direct_season_subdirs`.

## RC2 — Season-missing-on-TMDB mapping (Oshi no Ko, JJK, Frieren, Hells Paradise, Futurama S12/S13)
TMDB consolidates these shows into one long season. Folder-season files (S03E06) fall to
consolidated scan; when their title doesn't match (e.g. "Cog", or no title at all — Oshi
no Ko), the sequential/number fallback maps S03E06→S01E06 and rule 4 gives
`season-relative` 0.86→0.88 floor = auto-accept. Evidence: Oshi no Ko S03E01–E11 →
S01E01–E11 all "OK" at 0.88; JJK S03E06–E11 → S01E06–E11 at 0.88 while siblings
title-matched to S01E48–E59.
Fix: (a) when the assigned season ≠ the file's explicit season hint, never treat the
number as season-relative (use inferred 0.50 → review); (b) anchor-offset inference:
title-matched siblings imply per-folder offset (JJK S03E01→E48 ⇒ offset 47 ⇒ Cog→E53);
apply at review confidence.

## RC3 — Punctuation-hostile prefix compatibility (MASH 0.45, Frieren 0.45, Hells Paradise 0.45)
`normalize_for_match("M*A*S*H")` = `"m a s h"` vs `"mash"`; `"Hell's"` = `"hell s"` vs
`"hells"` → `_source_prefix_compatible` false → CONTRADICTORY_PREFIX_CAP 0.45 slashes
otherwise perfect title-agree (0.96) assignments. Every MASH file = REVIEW.
Fix: compare space-collapsed compact forms in `_source_prefix_compatible`.

## RC4 — get_season("Extras")==0 drops root episodes (Gundam 0083)
Root has 13 dash-numbered episodes + `Extras/` subdir. `get_season("Extras")` returns 0,
so `resolve_tv_season_dirs` returns `[(Extras, 0)]` only — the 13 real episodes are never
scanned. Fix: include the root as a season dir when it has direct video files.

## RC5 — Extras/companion files claim numbered special slots (Gundam NCOP/NCED, TNG "Extra N")
`extract_episode` parses bare numbers from "NCED1"/"Season 2 Extra 1" (→ episode 2!) and
resolve gives `special-number-only` 0.50 claims → mass conflicts on S00E0N.
Fix: files from extras folders (and `is_companion_video_file` NCOP/NCED) must not make
number-only claims; title match or unmatched.

## RC6 — Show-name-as-episode-title evidence (Trailer Park Boys S10 → S00E03, Futurama S09E01 → S09E09)
Files titled with the show name ("Trailer Park Boys - S10E01 - Trailer Park Boys") match
a special/episode whose title contains the show name; the cross-season specials rescue in
`_resolve_into_table` rides over valid own-season numbers (all 10 S10 files + 2 S11 → one
S00E03 slot). Futurama "S09E01 Futurama" title-substring-matched an S9 title → conflicted
with the real E09 file.
Fix: ignore raw_title as title evidence when it normalizes to the show name; never
cross-season-rescue a file whose explicit S##E## is valid in its own season.

## RC7 — Segment-titled files with single grouping number (Animaniacs 1993, Catscratch, CatDog residual)
TMDB lists segments as episodes (Animaniacs S1 has 171 slots); files are numbered per
disc grouping (E01 = 3 segments) with combined titles. `match_segmented_title_run` only
runs when parsed_episodes ≥ 2, so number wins (`title-ambiguous` 0.88 auto-approved,
wrong). Evidence: S01E06 file (segments 16–19 region) → S01E06; exact-title files (
"Taming of the Screwy"→E12) then conflict with number claims (E12 file lost conflict).
Fix: attempt segmented-title runs for expected counts 2..4 even when only one number
parsed; prefer title-derived runs; number-only multi-segment titles vs segment-indexed
seasons must be review, not 0.88.

## RC8 — Double-episode premiere trims (DS9, TNG S01E01E02)
TMDB lists "Emissary"/"Encounter at Farpoint" as E01 only(+E02 separate titled ep). File
"S01E01-E02 Emissary" claims E01,E02 (rule 1 — title matches E01 in run); file "S01E03
Past Prologue" title-overrides to E02 → conflict at E02. Both claimants have exact-title
evidence so `_auto_resolve_strong_title_conflicts` skips.
Fix: when a conflicted slot is at the EDGE of a multi-episode run whose title matches a
different episode of the run, trim the run instead of conflicting; prefer the exact-title
single claimant for the slot.

## RC9 — Duplicate source copies become conflicts (Squidbillies S05, Reno 911)
Two physical copies of the same season (Squidbillies (2004) Season 5 + Squidbillies
(2005)\Season 5; Reno "Complete Series" S1–6 + "(2003) Season 1-8" S1–6) merge via
`reconcile_scanned_episode_claims` → pairwise conflicts on every episode. User invariant:
an episode must never be listed twice with an unresolved conflict.
Fix: claims from distinct source roots with equal evidence for the same slot = duplicate
copy → keep primary (better quality/priority), mark other as duplicate/skip, not conflict.
Reno also: the 8-season folder was labeled dup of the 6-season nested one; duplicate
priority should prefer the superset folder.

## RC10 — Rugrats seg-run vs rule-1 overlap (S05E07, S09E08)
Seg-run assignment (E06,E07) and a rule-1 combined-title run (E07,E08) overlap: rule 1
confirms a whole run when the combined title matches ANY episode in the run, even though
adjacent files' segment titles imply a +1 shift. Fix: for multi-ep files, when
seg-run resolution of a NEIGHBOR overlaps a rule-1 run, re-run the rule-1 file through
segmented resolution against remaining slots; at minimum surface once, not twice.

## RC11 — Rawhide S5 conflict-loser gap rescue
Source is offset −1 from TMDB (titles rescued e01→E02 …). Files whose titles didn't
match (e14, e23) number-claim slots already title-claimed → lose conflict → SKIP, while
adjacent slots (E16, E24 — and E01) stay unclaimed. Fix: post-pass — a lost-conflict
file whose neighbors show a consistent offset and an adjacent unclaimed slot exists →
review-assign into the gap.

## RC12 — Specials-only folders fan out as standalone shows (Wild Thornberries → "Specials", IT Crowd/season 0 → "Fairy Tail")
Umbrella containers whose non-specials season folders are EMPTY (Thornberries seasons,
IT Crowd) leave only the specials child, which becomes its own candidate searched by its
own folder name ("Specials (1998-2003)" → TMDB show "Specials"). Fix: when a discovered
candidate is a specials/season-0 folder, search with the PARENT folder's title (and
season_assignment=0), like nested-season candidates do. ("Bobs Burgers…/Series" →
"J9 Series" is the same class: generic child name should inherit parent context.)

## RC13 — Watchmen TIE with "Watchmen: Motion Comic"
Score 1.00 with tie flag: runner-up within SCORE_TIE_MARGIN after episode-count
boosts (Motion Comic also has ~1 season). Needs scoring dump during fix; likely the
9-file count matches Motion Comic's episode count (+0.10) — tiebreak should weight
exact-name+year and popularity.

## RC14 — Jimmy Neutron → "Rich, Jimmy & Kait's Castle" (0.88)
Folder "JIMMY NEUTRON (2001-2013) - Complete Movie, ANIMATED TV Series, and Planet
Sheen…" cleaned query likely retains junk; real show "The Adventures of Jimmy Neutron:
Boy Genius" needs alt-title/episode-evidence boost. Reproduce scoring during fix.

## RC15 — Manual match → "Target path is outside the output root" (Watchmen queue failure)
After a manual rematch, `rematch_controller_tv_state` only retargets when
`state.scanned` (false right after `reset_scan()`); the subsequent
`start_single_show_scan` worker NEVER calls `retarget_tv_state_to_output`. Preview
items keep `target_dir = <source folder>\Season NN`; `_build_rename_ops` fails
`relative_to(output_root)` and stores the ABSOLUTE source path in
`target_dir_relative`; executor `output_root / <absolute>` → outside boundary → job
fails. Fix: retarget after single-show scans (and after claim reconciliation); at
queue-build time, rebuild non-relativizable target dirs as
`output_root/show_folder/Season NN` instead of persisting absolute source paths.

## Notes
- Caprica scans clean; the "nested show" report was likely The Brak Show (2000)
  (1 special file, sibling of Space Ghost) which produced NO candidate — verify
  classifier on a 1-special-file folder. Birdgirl (2021) folder is empty (0 files).
- Thornberries Season 1–5 folders and IT Crowd S01–S05 are EMPTY on disk.
- Episode auto-accept threshold 0.85; show threshold 0.55 (`engine/_state.py`).
