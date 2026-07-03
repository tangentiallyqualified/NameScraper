# Batch TV Bug Investigation — Round 2 Root Causes (2026-07-02)

**Status: fixed — see [2026-07-02-batch-tv-round2-fixes.md](2026-07-02-batch-tv-round2-fixes.md)**
(RC29 deferred by design). Regression tests per RC:
RC16 `tests/test_symbol_folding.py` + `tests/test_show_scoring_no_year.py`;
RC17 `tests/test_release_junk_titles.py`;
RC18a/b/d + RC18c/e `tests/test_consolidated_two_phase.py`;
RC19 `tests/test_air_date_clusters.py`;
RC20(1) `tests/test_symbol_folding.py`; RC20(2) `tests/test_fuzzy_title_matching.py`;
RC20(3) `tests/test_run_extension.py`; RC20(4) `tests/test_same_season_rescue.py`;
RC21 `tests/test_underscore_segments.py`;
RC22 `tests/test_multisegment_zero_match.py`;
RC23/RC24b/RC25/RC26 `tests/test_specials_guards.py` (+ RC26 consolidated-path
case in `tests/test_consolidated_two_phase.py`);
RC27 `tests/test_bare_episode_prefix_titles.py`;
RC28 `tests/test_duplicate_copies.py`.

Re-validated 2026-07-02 against the real library via `scripts/scan_real_library.py`
(dumps in `.scan-dumps\`); all Task-19 checks met. Notes from validation:
- CatDog's "Sumo Enchanted Evening and Hotel CatDog" lands at S02E35-E36 at
  0.96 via the two-phase title claim (stronger than the review-level
  cross-season rescue the plan predicted — same destination).
- Rugrats' mis-filed S7 packs cross-season-rescue to their true S8 slots at
  0.70; known residual: single-atom mis-titled files with an agreeing number
  ("S07E01 - Finsterella" → 0.88 OK) are excluded from the RC22 cap by design
  (the cap requires ≥2 parsed episodes so ordinary "X and Y" single-episode
  titles keep auto-accepting).
- Catscratch: exact segmented runs auto-accept at 0.90 (title-strong);
  only the fuzzy-atom runs (Bringin'/Livesavers) park at 0.70 review.
- Reno 911: no S01E01 interleave; S1-6 title-anchored at 0.96 (sibling
  Complete Series copies); S7/S8 files park as SKIP not-in-season. The ~9
  revival episodes that also exist as S0 46-54 are NOT S0-matched — the
  S7/S8-only umbrella fails the consolidated title-pass 50% gate and
  alternate-entry probing is RC29 (deferred).
- KaBlam's root specials needed an RC26 follow-up: the show scans via the
  consolidated path, so the stem-title S0 fallback was added to
  `build_consolidated_table` too (Henry & June → S00E02, Off-Beats →
  S00E03, Loopy Gala-Bration → S00E01 at 0.88).

Follow-up to
[2026-07-01-batch-tv-bug-investigation.md](2026-07-01-batch-tv-bug-investigation.md)
(RC1–RC15, all fixed). User review after the 7-01 fixes produced a new bug
list; every item is reproduced and root-caused below. RC numbering continues
from RC15.

Reproduced with a rebuilt throwaway harness (scratchpad `repro_round2.py`,
same shape as the deleted `scripts/repro_batch_bugs.py`: `BatchTVOrchestrator`
+ `get_api_key("TMDB")` + `discover_shows()` + `scan_all()`) against
`P:\data\downloads\in progress files`. Per-show dumps (preview items,
assignment table, evidence, conflicts, TMDB slots) were written to the session
scratchpad `out\` directory. Key parser behaviors were additionally verified
in isolation (`extract_episode`, `normalize_for_specials`,
`match_segmented_title_run`, `resolve_file`, `build_tv_name`).

## User bug list → root causes

| User report | RC |
|---|---|
| Frieren/Hells Paradise/JJK show confidence not auto-match | RC16 |
| Only JJK needs per-episode approval | RC17 (+RC18b) |
| Oshi no Ko not offset, mapped S01E0x | RC19 (+RC18c) |
| Animaniacs E01 file not S01E01-E03; E02 file kept wrong number | RC17 (REPACK) + RC22 |
| Archer Heart of Archness parts all wrong | RC23 |
| CatDog E37-E38 file only maps E37 | RC20 (typo) |
| CatDog S2-content primaries unmapped / "failed to map to s2" | RC18a+e |
| Catscratch no multi-episode mapping | RC21 (+RC22) |
| Dexter's Lab duplicate S01E07 conflict + double-counted | RC28 |
| Doctor Who S02E10 → special | RC24 |
| Doctor Who Clarence/She Said prequels lose S00E13 | RC25 |
| KaBlam Henry & June special unmapped | RC26 |
| Lucy needs approval, why? | RC27 |
| Reno 911 S01 all conflicts, cross-season claim fights | RC18c+d + RC27 + RC29 |
| Rugrats S04E21 file should also claim E20 | RC20 |
| Rugrats S7+ dangerous auto-mapping ignoring titles | RC22 |
| Angry Beavers 3 unmapped ↔ 3 missing same-title episodes | RC20 |
| Tom Goes to the Mayor S02 files fail to map | RC20 |

## RC16 — Show scores capped for year-less release folders (Frieren 0.73, JJK 0.73, Hell's Paradise 0.556)

`score_results` = `title*0.7 + year*0.3`; a folder with no year
("JUJUTSU.KAISEN.S03.1080p…") forfeits the whole 0.3 year component, so even
an exact-name match tops out ≈0.70–0.73 — below the user's GUI auto-accept
threshold 0.82 (settings.json; engine default is 0.55, which is why the
harness shows `needs_review=False`). The episode-evidence boost then makes it
WORSE: `_tv_episode_evidence_adjustment` computes season coverage from the
folder's explicit season ({3} for JJK), which is missing from TMDB →
`(0 − 0.5) * 0.24 = −0.12`, and the per-episode title-similarity boost
(`+0.24` max) is skipped entirely because `tmdb_seasons.get(3)` is None.
Hell's Paradise additionally loses title similarity to apostrophe
tokenization ("Hells" vs "Hell's" — same class as RC3).
Evidence: discovery dump — Oshi no Ko folder has "(2023)" → 1.030 auto;
the three year-less folders sit at 0.556–0.730.
Fix: renormalize weights when no year hint exists (title-only scoring);
when the hinted season is missing from TMDB, match evidence titles against
ALL seasons' titles instead of skipping; compact-form apostrophe folding in
show-title scoring.

## RC17 — Release junk survives in raw_title, degrading exact title evidence (JJK approvals, Animaniacs REPACK, Archer)

`extract_episode` keeps trailing junk in the title:
`'Execution 1080p CR WEB-DL DUAL AAC2 0 H 264-VARYG'`,
`'De-Zanitized, The Monkey Song & Nighty-Night Toon REPACK'`,
`'Heart of Archness Part 1 1080p NF WEB-DL DDP5 1 AV1-DBMS'`.
`clean_title_evidence` does NOT strip any of these (verified — output equals
input). Consequences:
- JJK: every title match is substring (0.90) instead of exact (1.0) → rule 2b
  `title-strong-inexact` 0.70 review-locked; the rest are offset-inferred 0.70
  (by design). That is the entire answer to "why does only JJK need individual
  episode approval" — with clean titles they would be exact rule-2 overrides
  at 0.90 auto.
- Animaniacs: a single trailing "REPACK" makes the LAST segment atom fail
  exact matching, so `match_segmented_title_run` fails for every REPACK file →
  wrong disc numbers kept at 0.70 (E01/E02/E03… files). Files without REPACK
  decompose fine (E04 → S01E10,11 at 0.90). The user's "file says s01e01 but
  contains three titles" is this: the run was never assigned, so the preview
  kept a single-episode name (`build_tv_name` is verified correct for runs —
  it produces `S01E01-E03`).
Fix: strip release-junk tokens (resolution/codec/source/group, REPACK/PROPER,
bracketed groups) from raw_title before it is stored as FileEntry evidence.

## RC18 — Consolidated-scan defects (CatDog, Reno 911, JJK path, Oshi no Ko)

The consolidated path (`_tv_scanner_consolidated.py`) triggers whenever a
folder season is missing from TMDB (CatDog "Season 4", Reno "Season 7/8",
JJK/Oshi "S03"). Five distinct defects:

a) **Number claims consume slots before title claims.**
`try_title_based_matching` walks files in absolute-number order; its first
branch lets a file whose (hint, number) exists in TMDB claim that slot
immediately. CatDog "S03 E01-E02 - Sumo Enchanted Evening and Hotel CatDog"
(real content = TMDB S2E35-36) number-claims S3E01-E02; when the genuinely
titled "S03 E27-E28 - Monster Truck Folly and CatDog's Gold" file arrives its
slots are `used` → match None.

b) **8-char substring floor + word-order variants starve the 50% gate.**
JJK 'Passion' (7), 'Cog' (3) excluded as keys; 'Tokyo No 1 Colony Part N' vs
TMDB 'Tokyo Colony No. 1 (N)' never substring-matches → 5/12 < 50% → the
title pass is abandoned for the sequential fallback even though 5 files had
unambiguous title hits.

c) **Sequential fallback ignores explicit season hints.** Files are slotted
in absolute order regardless of their S## label. Reno: S07E01/S08E01/S07E02…
interleave into S01E01,E02,E03… at 0.80 (0.50 inferred + exact-coverage
floor). Oshi no Ko: S03E01-E11 → S01E01-E11 at 0.50. The dump's "S1E01
CONFLICT … src=…S07E01 - Meet Jeffy" is exactly the user's "e01.the pilot vs
s07e01 - meet jeffy claim fight".

d) **Season 0 is excluded from the consolidated title lookup** — but TMDB
2187 lists most Reno revival episodes as S0 specials 46–54 ('Space Force',
'Weekend at Bernie', "Let's Shoot A White Guy", "Jackie's Birthday", …). With
S0 in the lookup those S7 files would title-match their real slots.

e) **Match-None files are marked NOT_IN_SEASON without ever running
`resolve_file`.** `build_consolidated_table` only resolves files that got a
preview mapping; SKIPped files die with "episode not in TMDB season".
Verified in isolation: `resolve_file(parsed=(27,28), raw="Monster Truck Folly
and CatDog's Gold", season_titles=S3)` → `(1,2)` at 0.90 `title-segmented`.
The whole CatDog "unmapped multiepisode primaries" group (S03 E27-E38) would
resolve correctly via seg-runs against the hinted season.

Fix: two-phase claiming (exact/segmented title claims first, then
number/hint fills); include S0 titles at review confidence; drop the 8-char
key floor to the `_MIN_KEY_SUBSTRING_LEN`-style 4 (with used-slot handling);
never sequence-map a file whose explicit season hint is missing from TMDB —
run it through `resolve_file` against candidate seasons and otherwise mark
review; always `resolve_file` leftover files against their hinted/folder
season before marking NOT_IN_SEASON.

## RC19 — Oshi no Ko: offset unknowable from titles (files carry none)

All 11 files have `raw_title=None` (`Oshi no Ko (2023) S03E0x (…)`), so the
RC2 anchor-offset rescue has zero anchors (needs ≥2 title-matched siblings).
TMDB consolidates the show into one 35-slot season; correct mapping is
S03E01→S01E25 ("Down Bad"). The engine currently leaves S01E01-E11 at 0.50
REVIEW (RC2(a) correctly blocks auto-accept, but the mapping offered is
wrong). Slots already carry `air_date`; the three cours are separated by
multi-month gaps (11 + 13 + 11 episodes). Fix: when the folder's explicit
season N is missing from TMDB and the consolidated season's air dates
cluster into runs, map folder-season N onto the Nth cluster (bonus
corroboration when file count == cluster size), at review confidence.
(Alternative/extra: TMDB episode-groups API.)

## RC20 — Near-miss titles have no fuzzy fallback; rule 2b drops the rest of a run (CatDog E37/38, Rugrats E20/21, Angry Beavers, Tom Goes to the Mayor)

Exact/substring matching is defeated by one-character differences and
notation variants, verified against TMDB slot titles:
- CatDog file "Neferkitty and Curiou**s**ity Almost Killed The Cat" vs TMDB
  'Curiosity Almost Killed The Cat' → seg-run fails; unique substring
  'Neferkitty' → rule 2b assigns ONLY E37 (user bug: E38 dropped).
- Rugrats "The Mattress & Looking for Jack" → only 'Looking for Jack'
  matched → single E21 (user bug: E20 dropped). Neighbors seg-run fine at −2.
- Tom Goes to the Mayor "201 - My **Bigs** Cups" / "210 - **Friend**
  Alliance" vs 'My Big Cups' / 'Friendship Alliance' → SKIP (numbers 201/210
  invalid, typo blocks title).
- Angry Beavers: 'H-2 Whoa' vs 'H²-Whoa!' (norms 'h2whoa' vs 'hwhoa'),
  "I'm Not an Animal... I'm Scientist No. 1" vs "I Am Not an Animal, I'm
  Scientist #1", 'Dagski & Norb' vs 'Dagski and Norb' (norms 'dagskinorb' vs
  'dagskiandnorb' — '&' is dropped, 'and' kept). All three number-claim
  wrong slots, lose conflicts, and die: `rescue_cross_season_titles` requires
  a DIFFERENT season + exact title, RC11's gap rescue requires a uniform
  neighbor offset. The 3 unmapped files ↔ 3 unclaimed same-season slots.
Fix: (1) normalization folding: '&'→'and', '#'→'number'/strip, superscript
digits, common contractions ("I'm"/"I am"); (2) bounded fuzzy match (edit
distance ≤2 or token-set ratio) for title lookup AND seg-run atoms, at
review confidence when inexact; (3) when a multi-number file rule-2b matches
one segment, extend the assignment to the parsed-count run anchored at the
matched segment's position (review confidence); (4) same-season rescue: a
lost-conflict/no-match file whose fuzzy title hits exactly one UNCLAIMED slot
in its own season → review-assign.

## RC21 — Underscore segment separator lost in parsing (Catscratch)

`Catscratch.S01E01.To.The.Moon_Bringin'.Down.The.Mouse` →
`raw_title="To The Moon Bringin' Down The Mouse"` — the `_` between segment
titles is normalized to a space before `_SEGMENT_SEP` (only `& / , and`) can
see it, so NO Catscratch file can decompose (each file = 2 segments,
TMDB lists 40 segment episodes). Each file keeps its bare disc number:
half map to the wrong episode and are auto-accepted at 0.88 (RC22), e.g.
S01E02 file (content 'Unicorn Club'/'Go Gomez Go' = TMDB E03-E04) → assigned
E02 'Bringing Down the Mouse' 0.88 OK. Also 'Bringin'' vs 'Bringing' is an
RC20 near-miss. Fix: treat `_` as a segment separator (preserve it into
raw_title or record atom boundaries before space-normalization); then rule-1
style agreement should claim the full (2n-1, 2n) runs.

## RC22 — Number-only auto-accept when the title matches NOTHING in the season (Rugrats S7+, CatDog S3E01-12, Catscratch, Animaniacs)

Rule 4 (`season-relative` 0.86) plus the EXPLICIT_EPISODE_FLOOR /
COMPATIBLE_PREFIX_FLOOR (0.86/0.88) auto-accepts mis-numbered files even when
they carry rich multi-segment titles that match zero slots in the assigned
season. The `title-multi-segment` review-lock only fires when the title
AMBIGUOUSLY matches (2+ substring hits); zero hits → no cap. Evidence:
Rugrats "S07E02-E04 - Angelicon & Dil's Binkie & Big Brother Chuckie" →
S07E02-04 at 0.88 OK with evidence `['number','season-relative']` while its
titles live elsewhere; S07E20+ overflow files SKIP not-in-season. CatDog
"S03 E01-E02 - Sumo Enchanted Evening and Hotel CatDog" (content S2E35-36) →
S03E01-02 at 0.86. This is the user's "dangerously mapping files that don't
match automatically and ignoring episode title matching logic".
Fix: when raw_title splits into ≥2 segment atoms (or is a nontrivial title)
and NO title evidence supports the assigned run while the season has titled
slots, cap at review (extend the multi-segment lock to the zero-match case)
and attempt seg-run resolution against other seasons (cross-season segmented
rescue, review confidence).

## RC23 — Specials "Part N" can never match "(N)" titles (Archer Heart of Archness)

Files S00E04/05/06 "Heart.of.Archness.Part.1/2/3" vs TMDB S00E03/04/05
'Heart of Archness (1)/(2)/(3)' — source S0 numbering is off by one, and the
title cannot rescue because: (a) RC17 junk blocks the base comparison; (b)
`_strip_part_number` removes only the DIGITS — the word "Part" stays, so
input_base 'heart of archness part' ≠ key_base 'heart of archness'; (c) even
when it matches, `_TITLE_PART_NUMBER` = 0.80 < STRONG_TITLE_STRENGTH 0.85, so
a part-number match can never override a disagreeing number (rules 2/2b/5).
Result: all three claim their wrong literal S0 numbers at 0.50
`special-number-only` (E04→'(2)', E05→'(3)', E06→'L'Espion Mal Fait').
Fix: strip part-marker words ('part', 'pt') in `_strip_part_number`; treat a
unique base+part-number specials match as review-assignable override
(specials numbering is known-unreliable — the number should not outrank a
unique titled part).

## RC24 — Cross-season-special hijacks a valid own-season episode (Doctor Who S02E10)

File "S02E10 - Love and Monsters": TMDB titles it 'Love **&** Monsters' →
normalization gap ('loveandmonsters' vs 'lovemonsters') → own-season match
fails → resolution is rule-4 without `title-agree` → the specials branch in
`_resolve_into_table` runs, and 'Love and Monsters' substring-matches S0's
'Tardisode 10: Love And Monsters' → override to S00E28 at 0.70. RC6's
"never rescue a valid own-season S##E##" guard was only added to
`rescue_cross_season_titles`, not to this branch.
Fix: '&'→'and' folding (also fixes the own-season match, restoring
`title-agree` 0.96); additionally guard the specials branch: a file whose
explicit season+episode is valid in its own season may only be pulled to S0
on an EXACT title match that beats an absent own-season match.

## RC25 — Prequel/extras files claim S0 slots with their PARENT episode number (Doctor Who Clarence / She Said)

"Prequel - S07E13 - The Name of the Doctor - Clarence and the Whispermen"
(Featurettes folder → scanned as S0) parses `episodes=(13,)`,
`season_hint=7`. The extras guard only drops numbers when NOT
season-relative, so both prequels number-claim S00E13 ('Planet of the Dead'),
lose the conflict, and die — while their true slots S00E85/E86 ('She Said, He
Said (The Name of the Doctor Prequel)' / 'Clarence and the Whispermen (…)')
stay unclaimed. Title matching can't save them because the file form
'X - Y' vs TMDB 'Y (X Prequel)' fails substring both ways.
Fix: an extras/S0-scanned file whose season_hint ≠ 0 must not make S0 number
claims (the number refers to its parent episode); match titles by segment —
try the last ' - ' segment (and full stem) against S0 titles, with RC20
fuzzy/subset matching to bridge the '(X Prequel)' suffix.

## RC26 — Unparseable root files never get the stem-title fallback (KaBlam)

`The Henry & June Show (1999).mp4` sits in the show ROOT (not a specials
folder): no episode number parses → `REASON_NO_PARSE`, and the
cleaned-stem-as-title fallback in `_resolve_into_table` only applies to files
scanned with `season_num == 0`. TMDB S00E02 is literally 'The Henry & June
Show'. Same for 'The Off-Beats Valentine's Special (1998)' vs S00E03 "An
Off-Beats Valentine's" (also needs RC20 fuzz for The/An + 'Special').
Fix: for any video file with no parsed episodes, use the cleaned stem as
title evidence against its season AND S0 (review confidence for inexact).

## RC27 — `E##.Title` filenames lose their title (Lucy; Reno Complete Series)

`extract_episode("E01.He's Not the Messiah, He's a DJ.mkv")` → `eps=[1],
title=None` (verified). Lucy's 11 files therefore carry number-only evidence:
0.50 inferred, lifted to exactly 0.80 by the exact-coverage floor — under the
0.85 threshold, hence "why do Lucy episode matches need approval". With
titles parsed they'd be rule-1 0.96 auto. The same pattern breaks Reno's
Complete Series files ('E01.The Pilot' etc.), removing the title anchors that
would have kept its seasons honest.
Fix: capture the remainder after a bare `E##`/`##` prefix (dot- or
dash-separated) as raw_title in `extract_episode`.

## RC28 — Duplicate copies with different numbers stay as conflicts and double-count (Dexter's Laboratory)

Same folder holds "S01E07 - Dexter's Rival" and "S01E34 - Dexter's Rival"
(also S03E11/S03E36 'A Mom Cartoon'). Both exact-title-claim E07 (strengths
tie at 3); `_claims_are_duplicate_copies` requires IDENTICAL
`parsed_episodes`, so they are left as a visible CONFLICT, listed inline, and
both count toward the season header's file count. User requirement: duplicate
copies must not render as inline conflicts nor inflate season counts.
Fix: treat tied exact-title claimants whose normalized titles are equal as
duplicate copies even when parsed numbers differ (prefer the number-agreeing
claimant); give the loser a distinct DUPLICATE status/role in projection so
the GUI can group it separately and exclude it from season header counts.

## RC29 — Seasons that live under a different TMDB entry (Reno 911 revival)

TMDB 2187 has S1–6 only; the 2020 revival is a separate show ('Reno 911!'
103190 / 'Reno 911! Defunded' 158505) while ~9 revival episodes ALSO appear
as S0 specials 46–54 on 2187. The S7/S8 folders therefore always mismatch.
RC18c+d and RC27 fixes stop the catastrophic interleaving (S7/S8 files
title-match S0 or park at review; S1–6 files anchor by title). Longer-term
option: when an explicit season is missing from TMDB, probe the alternate
search results (already in `state.search_results`) for a show whose season N
matches the folder's episode titles/count, and surface a "seasons split
across TMDB entries" warning instead of guessing.

## Notes

- Frieren's 0.96 'title-agree' assignments are circular: the consolidated
  preview picks slots BY TITLE, then `resolve_file` re-matches the same title
  against the mapped number and calls it agreement. Correct here, but the
  same mechanism can self-confirm a wrong substring pick; worth a
  `title-consolidated` evidence tag rather than 'number'+'title-agree'.
- `_rescue_group` tags offset-inferred assignments with 'season-relative'
  from the FileEntry even when the resolution deliberately treated the file
  as NOT season-relative (hint mismatch). Harmless today (0.70 lock wins) but
  misleading in dumps.
- Suggested implementation order: RC17+RC27+RC20(1) parsing/normalization
  fixes first (they shrink RC18/22/23/24 blast radius), then RC18, RC22,
  RC25/26, RC23, RC28 (with the GUI duplicate grouping), RC19, RC16, RC29.
- Thresholds: episode auto-accept 0.85, user show auto-accept 0.82
  (settings.json), engine default 0.55.
