# Batch TV Bug Investigation — Round 3 Root Causes (2026-07-02)

**Status: fixed and re-validated 2026-07-02** against the real library via
`scripts/scan_real_library.py` (fresh dumps in `.scan-dumps\`). Validation
highlights: Tigtone S1 fully exact-mapped at 0.92 with zero conflicts;
Jimmy Neutron's specials match 'The Adventures of Jimmy Neutron: Boy Genius'
(2129) at 0.78; Limitless tie=False; Samurai Jack returns a full preview
(its genuinely off-by-one roman-numeral naming parks as visible conflicts /
review, per the "review over guessing" directive); IT Crowd S00E01 at 0.86
`special-explicit`; Blue Submarine files park as honest no-title-match
unmapped primaries (queueable, manual-assign workflow); Off the Air 'Sex' →
S13E01 0.88; Rick and Morty S01E04 → 0.96 rule-1; Animaniacs E03 → S01E07-09
0.90 via positional fill (unassigned count 11 → 9, the rest are 4-6-segment
compilations left at review); Ren & Stimpy 'Son of Stimpy'/'Ol' Blue
Nose'/'Stupid Sidekick Union' rescued to S03E05/S04E24/S04E25 at 0.70;
Powerpuff Show & Tell → exact S00E10-12, only the legitimate Color/Pencil
S00E01 conflict remains (numbered pair, hard-blocks queueing); Rocket Power
'The Big Day' → S03E41 0.70; Rugrats 'Murmur' → S09E27, squatter packs
unassign with "segment titles match Season N non-contiguously". Zero engine
errors in the run (Samurai Jack and KaBlam crashes gone).
Regression tests: RC30 `tests/test_run_extension_guards.py`;
RC31 `tests/test_segmented_positional_fill.py`;
RC32 `tests/test_conflict_snapshot_staleness.py`;
RC33 `tests/test_token_aligned_substring.py`;
RC34 `tests/test_explicit_special_numbers.py`;
RC35 `tests/test_lost_conflict_rescue.py`;
RC36 `tests/test_cross_season_number_claims.py`;
RC37 `tests/test_show_scoring_token_subset.py`;
RC38 `tests/test_tiebreak_discrimination.py` + `tests/test_scan_improvements.py`;
RC39 `tests/test_conflict_queue_protection.py` + `tests/test_roster_classification.py`
+ `tests/test_command_gating_service.py`.

Follow-up to
[2026-07-02-batch-tv-bug-investigation-round2.md](2026-07-02-batch-tv-bug-investigation-round2.md)
(RC16–RC28, fixed; RC29 deferred). User review after the round-2 fixes
produced a new bug list; every item is reproduced and root-caused below
against a fresh full-library run of `scripts/scan_real_library.py`
(dumps in `.scan-dumps\`, engine.log included). RC numbering continues
from RC29.

Harness thresholds for this run: show auto-accept 0.55 (engine default —
the harness does not load the user's settings.json), episode auto-accept
0.85. GUI behavior described below assumes the user's 0.82 show threshold.

## User bug list → root causes

| User report | RC |
|---|---|
| Jimmy Neutron matched to Jimmy Kimmel despite verbatim folder/file text | RC37 |
| Limitless "ties" in choose-match all lower than the 100% pick | RC38 |
| Tigtone mass conflicts + single files labeled multi-episode | RC30 |
| Max filename size should increase to 170 chars | RC39(e) (the "truncation" seen was actually RC30+RC39(d)) |
| Ren & Stimpy lost-conflict files ↔ missing episodes with same title | RC35 |
| Powerpuff S00E01 conflict displayed as two inline copies of the episode | RC39(c) |
| Must not be able to queue a show with conflicts | RC39(b) |
| Powerpuff Show & Tell specials mismatch despite exact filenames | RC30 |
| IT Crowd special needs review despite exact S00E01 + show match | RC34 |
| Animaniacs multi-episode fell apart from the E03 file on | RC31 |
| Samurai Jack episodes not returned at all | RC32 |
| Blue Submarine 6 unqueueable after manual assign; "fix match" prompt | RC33 + RC39(a) |
| Manual unassign + approve-all → unqueueable | RC39(a) |
| Shows with unmapped primary files must be queueable | RC39(a) |
| Off the Air: one episode failed where siblings matched | RC33 |
| Rick and Morty S01E04 regression | RC30 (via RC21 underscore fix) |
| Rocket Power S4 title match not recognized for unmapped file | RC35(c) |
| Rugrats S7 files errantly mapped cross-season to non-title matches | RC36 |

Issues found that the user did not report: RC40 (KaBlam scan-summary
crash on `None` season keys; swallowed per-show scan errors leave a show
silently empty with no user-visible error).

## RC30 — `_extend_partial_title_run` over-extends single-episode files (Tigtone, Powerpuff Show & Tell, Rick and Morty S01E04)

Round 2's RC20(3) run extension fires far too eagerly:

- **Exact full-title matches still extend.** Every Tigtone title is
  "Tigtone and the X" — `_segment_atom_spans` splits at "and", so a
  single-parsed file whose FULL title exactly matches one slot
  ('Tigtone and the Wine Crisis' = S01E03) is treated as a 2-atom run
  anchored at the matching atom → S01E02-E03 at 0.70 `run-extended`.
  Nine S1 files inflate this way, overlap, and produce the conflict
  chain S01E02–E08 (dump: `show_Tigtone…`). Same mechanics give
  Powerpuff 'Show & Tell - Blossom/Buttercup/Bubbles' (exact TMDB
  titles S00E10/11/12) runs E09-10/E10-11/E11-12 — two visible
  conflicts plus the legitimate `S00E12 - Making of…` number claim
  displaced to lost-conflict. An exact full-string match consumes the
  entire title; there is NO leftover segment naming a neighbor.
- **Junk leftover atoms count as segments.** RC21's underscore→`&`
  rewrite turns `S01E04.M.Night.Shaym-Aliens!_new.mkv` into
  'M Night Shaym-Aliens! & new'; the 'new' atom (3 chars, matches
  nothing) makes the file look like a 2-episode run → claims E04-E05 →
  loses the E05 conflict to the real E05 file → whole file unassigned.
  This is the R&M S01E04 regression.

Fix: (1) never run-extend when the full-title match strength is exact —
return the single-episode rule-2 override; (2) only extend when every
unmatched leftover atom is a plausible title (≥2 tokens — 'The
Mattress' qualifies, 'new'/'Tigtone' do not); (3) tighten RC21: only
rewrite `_` to `&` when the right-hand side itself is dot-spaced
(contains a `.` word separator) — `_new`-style duplicate markers become
plain spaces again. Regression guard: Rugrats
"S04E21 - The Mattress & Looking for Jack" must still extend to (20,21),
CatDog 'Neferkitty…' to (37,38), Catscratch underscores must still split.

## RC31 — Segmented runs are all-or-nothing; duplicate-titled atoms abort the whole run (Animaniacs)

`match_segmented_title_run` drops duplicate TMDB titles from its lookup
("a duplicated title can't disambiguate"), so Animaniacs
"S01E03 - H.M.S. Yakko, Slappy Goes Walnuts & Yakko's Universe" fails:
"Yakko's Universe" appears twice in TMDB's S1. The run (7,8,9) is
abandoned, the file keeps its bare (3,) number claim, loses the conflict
to the E01 file's (1,2,3) seg-run, and dies. Eleven S1 files are
unassigned this way (dump `show_Animaniacs _1993_…`), all following the
same shape — the user's "worked until the third file labeled e03".

Fix: positional fill — when ≥2 atoms match unique consecutive episodes
and an unmatched atom's POSITIONAL slot (prev+1 / next−1) carries a
title exactly equal to that atom (duplicate-title case), accept the run;
exact evidence, normal confidence. When the unmatched atom's positional
slot title does NOT equal the atom (title missing from TMDB), accept the
run at review confidence (0.70, new review-locked tag
`title-partial-run`) only when a single atom is unverified. Files that
still fail must surface as review, not lose number conflicts silently
(covered by RC35's post-conflict rescue).

## RC32 — Stale conflict snapshot crashes the whole scan (Samurai Jack)

`_auto_resolve_strong_title_conflicts` iterates
`list(table.conflicts().items())` — a snapshot. Resolving one slot can
unassign a file that is the pre-computed winner of a later slot;
`table.resolve_conflict` then raises `File 28 does not claim S03E06`
(engine.log:677), `scan_all` catches it, and Samurai Jack returns NO
preview at all (`scanned=False`, empty dump). Per the user: don't get
clever with Samurai Jack's naming — just make the scan survive and park
edge cases at review.

Fix: inside the loop, re-fetch `claims = table.claims(season, episode)`
per slot and skip slots that are no longer conflicted or whose
pre-computed winner no longer claims; never let conflict resolution
raise mid-scan. See also RC40 for the orchestrator-level swallow.

## RC33 — Compact substring matching is not token-aligned and floors short keys (Blue Submarine No. 6, Off the Air 'Sex')

The substring tier compares compact normalizations, so:

- 'blues' (S01E01 'Blues') is a substring of
  'bluesubmarineno6toonamiversion' ACROSS a token boundary
  ('blue s|ubmarine'). All four Blue Submarine files (movie + three
  Toonami promos) hit the same slot → 3+ pile-up → every file dies as
  "ambiguous claim for S01E01" at SKIP.
- Keys shorter than the substring floor can never match: unclaimed slot
  S13E01 'Sex' vs `Sex ｜ Off the Air ｜ Adult Swim.mp4` — every sibling
  ('Coping', 'Drugs', 'Farts') matched at 0.88 `title-strong`; 'sex'
  (3 chars) is below the floor, so the one file reports "no TMDB title
  match".

Fix: substring hits must verify token alignment in the spaced
normalization (`'blues'` is not a token-substring of
`'blue submarine no 6 …'`, `'tell blossom'` IS one of
`'show and tell blossom'`); keys below the length floor are allowed when
they match as an exact token sequence at a token boundary ('sex' in
'sex off the air adult swim'). Blue Submarine's files then match nothing
and surface as unmapped primaries (queueable per RC39(a), manual
assignment supported — the user's actual workflow).

## RC34 — Explicit S00E## files with no title evidence still forced to review (IT Crowd)

`S00E01.mkv` in the `season 0` folder resolves `special-number-only`
0.50 (dump `show_The IT Crowd…`): season-0 numbers are treated as
untrustworthy even when the filename says S00E01 explicitly, the folder
is a season-0 folder, and the file carries NO contradicting title. The
round-2 stem-title fallback also stored the useless stem 'S00E01' as
raw_title.

Fix: when the file's own name carries an explicit S00E## marker
(season-relative with hint 0) and there is no title evidence disagreeing
(raw_title empty/junk or matching the slot), assign at the explicit
episode floor (0.86 — auto-accept). Files with rich titles that match
nothing (Ren & Stimpy's Adult-Party-Cartoon 'Stimpy's Pregnant' et al.)
keep the 0.50 review lock. The stem-title fallback must not mint titles
that are pure episode markers.

## RC35 — Lost-conflict files never get rescued; consolidated path lacks the cross-season title rescue (Ren & Stimpy, Rugrats, Powerpuff, Rocket Power)

Three related sequencing/wiring gaps:

a) **Rescues run BEFORE conflict resolution.** Both preview builders run
`rescue_cross_season_titles` → `rescue_cross_season_segmented` →
`rescue_same_season_fuzzy_titles` on the fresh table; conflicts are only
resolved at the END (`apply_confidence_adjustments` →
`_auto_resolve_strong_title_conflicts`). Files unassigned by LOSING a
conflict never see a rescue pass. Evidence: Ren & Stimpy
'S02E11 - Son of Stimpy' lost S02E11 while unclaimed S03E05 is literally
'Son of Stimpy'; 'S05E01 - Ol' Blue Nose' ↔ unclaimed S04E24;
'S05E02 - Stupid Sidekick Union' ↔ unclaimed S04E25. Rugrats
'S04E03 - Vacation' ↔ S05E01 'Vacation', 'S04E26 - The Turkey Who Came
to Dinner' ↔ S05E25.

b) **`rescue_cross_season_titles` only accepts REASON_NOT_IN_SEASON.**
Lost-conflict reasons are excluded even though the same exact-title,
unique-unclaimed-slot logic applies.

c) **The consolidated builder never calls `rescue_cross_season_titles`.**
Rocket Power scans consolidated (S4 folder missing from TMDB); its
'S00E04 - The Big Day' (NOT_IN_SEASON) exactly matches unclaimed S03E41
'The Big Day' but the single-title rescue is simply not wired into
`_build_consolidated_preview`.

Fix: wire `rescue_cross_season_titles` into the consolidated path;
accept lost-conflict reasons in the single-title rescue; after conflict
resolution, run one post-pass of the rescues over newly-unassigned
lost-conflict files and re-resolve conflicts once (no loop).

## RC36 — Own-season number claims with zero title support but an exact unique title match ELSEWHERE (Rugrats S8/S9)

RC22 capped multi-segment zero-match files but left two holes:

- **Single-atom titles.** 'Rugrats - S08E18 - Murmur On The Ornery
  Express' AUTO-ACCEPTS at 0.88 `['number','season-relative']` while its
  title exactly matches unclaimed S09E27 — a wrong auto-accept. Rule 4
  never consults other seasons.
- **Multi-segment files whose atoms match other seasons
  non-contiguously** keep their misleading number mapping at 0.70:
  'S08E16-E17 - Happy Taffy & Imagine That' (titles = S09E01 and S09E10)
  sits on S08E16-17 (TMDB: 'Falling Stars'/'Dayscare'); the
  'Dayscare & The Great Unknown & Wash Dry Story' pack (S08E17,18 + S08E36)
  sits on S07E11-13. These claims also BLOCK the legitimate S7-pack
  rescues into S8 slots. The user reads these as "errantly mapped across
  multiple seasons to non title matching episodes".

Fix: when a file's title matches nothing in its assigned season but
exactly matches a unique UNCLAIMED slot in exactly one other regular
season, rescue it there at 0.70 `cross-season-rescue` (single-atom case).
When a multi-segment file's atoms exact-match slots in another season
but do NOT form a contiguous run, unassign to review with reason
"segment titles match Season N non-contiguously" instead of keeping the
number mapping — honest review beats a wrong-looking claim, and the
freed slots let the S7-pack rescues land.

## RC37 — Show scoring: token-subset queries crushed by length ratio; specials-folder year hijacks the hint (Jimmy Neutron → Jimmy Kimmel)

The Jimmy Neutron pack's Seasons 1–3 are empty on disk (already
processed), so discovery correctly fans out to the `Specials (2003-06)`
subfolder with the parent's title via the generic-name fallback. The
match then fails twice over (`title_similarity`, matching.py:29):

- Substring branch scores `len(shorter)/len(longer)`:
  'jimmy neutron' ⊂ 'adventures of jimmy neutron boy genius' → **0.33**,
  while the char-LCS Dice gives 'jimmy kimmel live' **~0.67** just for
  sharing the 'jimmy ' prefix. An exact token-subset (both query tokens
  present, in order) must not lose to a prefix-sharing unrelated title.
- `_build_show_candidates` takes `year_hint` from the CANDIDATE folder
  first: `extract_year('Specials (2003-06)')` → 2003 = Jimmy Kimmel's
  first-air year (bonus 0.3), while the true show (2002, parent says
  2001) gets diff-1 credit. When the name fallback is active the year
  hint must come from the fallback (parent) folder first.

Evidence: engine.log:225 (top result 0.63), dump `show_Jimmy Kimmel…`
(search_results contain the correct id 2129 as runner-up). Fix: add a
token-aware tier to `title_similarity` (ordered token-subset →
`max(existing, 0.65 + 0.3 * token_coverage)` style), prefer fallback
year, and let the episode-count tiebreak see the corrected scores.

## RC38 — Tie flagged even when the episode-count tiebreak discriminated (Limitless)

TMDB has three shows literally named 'Limitless'; all exact-match the
query at the same raw score, `_primary_name_breaks_tie` can't help
(runner-up is also exact), so `tie_detected=True` → needs_review, even
though `episode_count_tiebreak` picked 62687 with a strictly better
episode-count distance. In the choose-match dialog the user then sees
the winner at 100% and "ties" at lower scores — because the tie was
computed on raw scores the dialog doesn't show.

Fix: `episode_count_tiebreak` returns whether the count evidence
discriminated (unique minimum distance, winner distance strictly
smaller than every same-score contender); suppress `tie_detected` when
it did. Keep the tie for genuinely indistinguishable candidates.

## RC39 — GUI queueing/eligibility and conflict presentation

a) **Unmapped primary files block queueing everywhere.**
`has_episode_problems` (_media_helpers.py:123) counts ANY
`table.unassigned_files()` as a blocker and `is_state_queue_approvable`
refuses those shows; `normalize_queue_selection` then un-checks them
after Approve All. This is the Blue Submarine complaint, the
manual-unassign + approve-all trap, and the general "shows with unmapped
primary files are not possible to queue". Fix: unassigned files keep
routing the show into "Review Episode Matching" in the left panel
(`roster_group`/`state_status` unchanged) but stop blocking
approvability/queueing; only conflicts and unapproved review rows block.
Unassigned files simply produce no jobs.

b) **Conflicts do NOT reliably block queueing.**
`evaluate_preview_items` returns ENABLED whenever any actionable row is
selected — the conflict check only runs when nothing is selected. A
checked show with a live conflict queues. Fix: conflicts present →
DISABLED_CONFLICT, period (the user's "protect from someone queueing a
show with conflicts").

c) **Conflicted claimants render as two inline copies of the episode.**
`build_episode_guide` emits one row per (preview, episode); two
claimants of S00E01 (Powerpuff Whoopass Color/Pencil copies) produce two
identical-looking S00E01 rows. Fix: group claimants of the same
conflicted slot into one guide entry (single episode row listing both
files with keep-this actions), so a conflict reads as one problem, not
two episodes.

d) **`_common_title_base` produced "Tigtone and".** The collapsed base for
a (wrongly extended, RC30) run kept a dangling conjunction — this is what
the user took for length truncation. Per user correction: episode titles
containing "and" must never be truncated; the real fix is RC30 (each
Tigtone file is ONE episode and keeps its full title). For genuine runs
whose common prefix ends in a conjunction, `_common_title_base` returns
None so the FULL joined titles are used — no trimming.

e) **Raise `MAX_FILENAME` 150 → 170** (explicit user request;
_parsing_names.py:18).

## RC40 — Scan failures are swallowed silently; scan-summary crashes on `None` seasons (KaBlam, Samurai Jack)

`scan_all` catches per-show exceptions with `_log.error(...)` and moves
on; the GUI shows an empty show with no explanation (Samurai Jack). The
"Scan complete" log line itself crashes when any preview has
`season=None` (`dict(sorted(by_season.items()))`,
_batch_orchestrators.py:607) — KaBlam hit this AFTER its previews were
stored, so only the log line and anything after it was lost. Fix: sort
the season summary with a None-safe key; record a user-visible scan
error on the state (`state.scan_error`) so failed shows surface as
errors instead of vanishing; log the full traceback.

## Notes

- Rugrats S9 pack files pairing non-adjacent TMDB titles
  ('Bestest of Show & Hold The Pickles' = S09E09 + S09E04) cannot be a
  contiguous run; after RC36 they surface as unassigned review with a
  cross-season/non-contiguous reason — correct per the user's
  "prefer review over aggressive guessing".
- Jimmy Neutron's `Movie (2001)` subfolder is movie content inside a TV
  umbrella; out of scope here (movie pipeline).
- Reno 911 revival remains RC29 (deferred).
- Implementation order: RC30 (+RC39(d/e)) first — it removes the Tigtone/
  Powerpuff/R&M noise; then RC32+RC40 (crash-proofing), RC33, RC31,
  RC35, RC36, RC34, RC37, RC38, RC39(a-c) GUI last (with Qt smoke).
