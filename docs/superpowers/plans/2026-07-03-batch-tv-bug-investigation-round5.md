# Batch TV Bug Investigation — Round 5 Root Causes (2026-07-03)

**Status: fixed and re-validated 2026-07-03** against the real library via
`scripts/scan_real_library.py` (per-fix targeted reruns; Animaniacs 2020 and
each untouched show byte-identical as controls). Validation highlights:
Animaniacs 'Useless Facts...' file → S01E113-E116 (was stealing S01E44 'The
Flame'); cascade wins: 'Schnitzelbank...' file → S01E147-E150 (was stealing
S01E56), 'It, Dot - The Macadamia Nut & Bully for Skippy' → S05E04-E06 at
0.90 `title-strong` (evicting the misnumbered 'Hooray for North Hollywood'
parts from S05E05/06); all seven scattered Rugrats S9 pairs now queue with
"segment titles match Season 9 non-contiguously" (three were presented at
wrong slots, two were bare lost-conflicts, two were half-rescued single-slot
renames that dropped a segment); Animaniacs 'Very Special Opening, A
Christmas Plotz...' no longer number-steals S01E49 'The Boids'; Powerpuff
pilot resolves to the (Color) print with the (Pencil) print queued as
`DUPLICATE: duplicate copy of S00E01` instead of an unresolved conflict
pair. Regression tests:
RC49 `tests/test_disc_grouped_run_ambiguity.py`;
RC50 `tests/test_same_season_scattered.py`;
RC51 `tests/test_duplicate_copies.py` (two new cases).

Follow-up to
[2026-07-03-batch-tv-bug-investigation-round4.md](2026-07-03-batch-tv-bug-investigation-round4.md)
(RC41–RC48, fixed). RC numbering continues from RC48. Harness thresholds:
show auto-accept 0.55 (engine default), episode auto-accept 0.85.

## User bug list → root causes

| User report | RC |
|---|---|
| Animaniacs S01E44 gets the wrong file by number despite no title match; next three episodes unmapped | RC49 |
| Rugrats S9 multi-part files unmatched; only one file identified as non-contiguous | RC50 |
| Powerpuff specials: two files claim the same special, neither prioritized | RC51 |

## RC49 — disagreeing disc-grouped run sizes treated as equal witnesses (Animaniacs S01E44)

'Useless Facts, The Senses, The World Can Wait & Kiki's Kitten' (file
number 44; TMDB E113 'Useless Fact', E114 'The Senses Song', E115 'The
World Can Wait', E116 "Kiki's Kitten"). The disc-grouped branch tries
decompositions at sizes 2/3/4. Size 4 finds E113-E116 with THREE groups
matching titles directly (one fuzzy, two exact) plus one positional fill
('The Senses' → 'The Senses Song'). But size 3 ALSO produced E114-E116 by
merging 'Useless Facts, The Senses' into one group and force-filling the
merged group into E114 (they share the token 'senses'). Two distinct runs
→ "ambiguous" → the file fell back to its parsed number and stole S01E44
'The Flame' from the file that actually contains it, which then lost its
own number conflict and left E45-E47 unmapped.

**Fix:** rank disagreeing runs by how many groups matched a title directly
(unverified positional fills don't count); only a tie is real ambiguity.
`_match_segmented_title_run_scored` now returns that count and the
disc-grouped branch keeps the unique best run. RC42's Flipper-Parody case
(whose only run comes from a merged-group fill) has a single candidate and
is unaffected.

## RC50 — same-season scattered segment titles fall back to number claims (Rugrats S9)

Rugrats' AMZN files pair segments by broadcast half-hour while TMDB S9
orders them differently, so 'Bug Off & The Crawl Space' is E02 + E17 — a
file that cannot be a run anywhere in its season. The explicit
identification ("segment titles match Season N non-contiguously") only
existed in the CROSS-season rescue (`_scattered_atom_seasons` skips the
file's own season), so same-season scattered files instead kept weak
number claims presented at wrong slots, lost conflicts with uninformative
reasons, or got single-slot fuzzy rescues that renamed a two-segment file
as one episode.

**Fix:** new pass `unassign_same_season_scattered_titles` — files stuck on
weak evidence (`title-ambiguous`/`title-no-match` number claims, or
lost-conflict/no-match/not-in-season reasons) whose atom groups
exact-match ≥2 own-season titles NON-contiguously are unassigned with the
same reason string. Adjacent atoms are also tried merged (sizes 1-3) so a
separator inside one title ('Diapies and Dragons' splits at 'and' but
names 'Diapies & Dragons') still counts. Contiguous matches are left
alone — they are a real run another pass may still place. Runs after
`rescue_cross_season_segmented` and before `rescue_same_season_fuzzy_titles`
in both scanner paths, so scattered files are excluded from single-slot
rescues.

## RC51 — variant-tagged duplicate prints stay an unresolved conflict (Powerpuff pilot)

'The Whoopass Girls - A Sticky Situation! (Color)' and '(Pencil)' both
resolve to S00E01 at 0.50 (`special-number-only`), tie on the evidence
ladder, and `_claims_are_duplicate_copies` rejected them because the
substring rule can't bridge the differing trailing tags — so both stayed
assigned and projected as an unresolved CONFLICT pair.

**Fix:** titles identical after stripping ONE trailing NON-numeric
parenthesized qualifier are duplicate copies ('(Color)'/'(Pencil)' are
prints of one episode). Numeric tags ('(1)', '(2)') are part numbers —
different episodes — and never fold. The existing duplicate tie-break
(parsed-number agreement, then first-registered file) picks the (Color)
print; the loser projects as DUPLICATE and routes to the manual queue.

## Accepted trade-offs (honest queue over partial/wrong claims)

- Animaniacs 'S01E24 - Yakko's World of Baldness, Opportunity Knox & Wings
  Take Heart' lost its partial E55 rescue: RC49 freed E56, so the fuzzy
  rescue now sees two candidate slots and backs off. The file (two real
  episodes behind an unlisted gag opening) goes to the manual queue whole.
- Animaniacs 'S01E20 - Hitchcock Opening, Hearts of Twilight & The Boids'
  lost its E48 half-rescue the same way after RC50 freed E49 (the E49
  number-thief was queued). E48/E49 are unclaimed; the file queues whole.

## Known gaps left for a future round

- Unlisted leading gag segments (Animaniacs S01E08/E20/E21/E24/E35/E40/E50):
  a noise atom at index 0 breaks positional fill under the RC42
  zero-overlap rule; no "leading atoms are extras" interpretation exists.
- Decompositions above 4 groups: S01E35 (5 segments) and S01E50 (6) can
  never resolve (`expected` only tries 2-4).
- 'S01E21 - The Flame, Four Score and Seven Migrains Ago Wakko's America &
  Davy Omelette': a missing comma fuses two titles into one atom (3 atoms,
  4 episodes) — unreachable without atom splitting; now queued with the
  RC50 reason.
- `;` is not a segment separator and acronyms inside atoms ('The Return of
  TGW') don't fold, so the S03E13 six-segment file queues with a
  "non-contiguously" reason even though its segments are the contiguous
  E41-E46 block. Destination (manual queue) is right; wording imperfect.
- 'Hooray for North Hollywood, Part 1/2' cannot reach S05E11/12 ('Hooray
  For North Hollywood (1)/(2)'): part-number title strength (0.80) is
  below the strong-title bar and both slots tie for the fuzzy rescue.
