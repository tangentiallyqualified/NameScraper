# Batch TV Bug Investigation — Round 4 Root Causes (2026-07-03)

**Status: fixed and re-validated 2026-07-03** against the real library via
`scripts/scan_real_library.py`. Validation highlights: Rawhide REVIEW 3 → 0
(S5E15/16/24 now 0.90 `title-strong`, S6E16 0.96 `title-agree`); Animaniacs
E04 → S01E10-E11 at 0.90 OK and E06 → S01E13-E15 at review; Archer S9E07
DBMS copy 0.96 `title-agree` with the EDGE copy as a duplicate; Rugrats
squatter chain fully unwound (Back To School → S09E21-22, Cat Got Your
Tongue → S08E19-21, And The Winner Is → S08E22-24, Accidents Happen &
Pee Wee Scouts → S07E15-16, Chuckie's New Shirt & Cavebabies → S07E17-18)
with the non-contiguous Big Showdown & Doctor Susie file left unmapped as
directed; Squidbillies and Archer arrive unchecked; all four ST:TNG
Stardate/Energized specials map to S00E01-E04; ancillary wins in Space
Ghost (REVIEW 6 → 0), Cow and Chicken (2 → 0), Gundam 0083 (Mayfly part 2
→ S00E02 instead of duplicate-parked). Regression tests:
RC41 `tests/test_segmented_group_separators.py`;
RC42 `tests/test_positional_fill_overlap.py` (+ updated
`tests/test_segmented_positional_fill.py`, `tests/test_episode_resolution.py`);
RC43 `tests/test_fragment_anchor_guard.py` + `tests/test_duplicate_copies.py`;
RC44 `tests/test_show_name_title_and_hint_rescue.py`;
RC45 `tests/test_squatter_chain_rescue.py`;
RC46 `tests/test_near_exact_titles.py`;
RC47 `tests/test_merged_show_checked_gating.py`;
RC48 `tests/test_acronym_titles.py`.

Follow-up to
[2026-07-02-batch-tv-bug-investigation-round3.md](2026-07-02-batch-tv-bug-investigation-round3.md)
(RC30–RC40, fixed). User review after the round-3 fixes produced a new bug
list; every item is reproduced and root-caused below against a fresh
full-library run of `scripts/scan_real_library.py` (dumps in `.scan-dumps\`,
previous run archived in `.scan-dumps\prev-runs\`). RC numbering continues
from RC40.

Harness thresholds for this run: show auto-accept 0.55 (engine default),
episode auto-accept 0.85.

## User bug list → root causes

| User report | RC |
|---|---|
| Animaniacs E04 needs approval for Hooked on a Ceiling; Goodfeathers unmapped | RC41 |
| Animaniacs E06 segments unmapped after losing the E06 conflict; no rescue | RC42 |
| Archer S9: exactly one episode lost its conflict to the duplicate source | RC43 |
| Futurama S09E01 unmatched; file lost a conflict to a season-6 episode, no rescue | RC44 |
| Rugrats S07E12/E14: e14 gets a file matching no titles; cascade after | RC45 |
| Episode titles with apostrophes need approval (Rawhide) | RC46 |
| Squidbillies checked by default despite sitting in Review Episodes | RC47 |
| ST:TNG specials with strong title matches unmapped (Stardate Revisited) | RC48 |

## RC41 — segmented groups match with separator text glued in (Animaniacs E04)

`match_segmented_title_run` merges adjacent atoms by slicing the raw title
span INCLUDING the separator. `_fold_title_symbols` folds `&` to the word
"and", so the group "Goodfeathers **&** The Beginning" normalizes to
`goodfeathersandthebeginning`, which can never equal TMDB's
"Goodfeathers**:** The Beginning" (`goodfeathersthebeginning`). Decomposition
fails; the file falls to rule 2b (single episode E10 'Hooked On a Ceiling' at
0.70), and `_extend_partial_title_run` is blocked by the RC30 one-word-atom
guard ("Goodfeathers"). Same shape recurs across many Animaniacs multi-part
files where TMDB titles the combined segment with a colon.

**Fix:** when matching a merged group, try BOTH the raw span (titles that
genuinely contain "and") and the separator-stripped join of the atom texts.

## RC42 — positional fill tolerates zero-overlap pieces → runs ambiguous across expected counts (Animaniacs E06)

'Flipper Parody, Temporary Insanity, Operation Lollipop & What Are We'
(TMDB: E13 'Temporary Insanity', E14 'Operation: Lollipop', E15 'What Are
We?'; "Flipper Parody" has no TMDB slot). Decomposition yields
`(13,14,15)` at expected=3 **and** `(12,13,14,15)` at expected=4 — the
latter positionally fills E12 'Taming of the Screwy' with the atom
"Flipper Parody" (zero token overlap; tolerated as the one unverified
fill). Two distinct runs → `len(runs) != 1` → decomposition discarded →
the file keeps its bogus number claim (6,), floored to 1.0 (plex-ready
pattern), loses the E06 conflict to the real segment run, and ends fully
unassigned. No rescue applies (its combined title matches nothing whole).

**Fix:** an unverified positional fill must share tokens with the slot
title (containment or ≥1 content-token overlap). "Flipper Parody" vs
'Taming of the Screwy' rejects the expected=4 run; the expected=3 grouping
(whose fill piece "Flipper Parody, Temporary Insanity" CONTAINS slot 13's
title as a token run) survives → unique run (13,14,15).

## RC43 — run extension anchors on fragment atoms (Archer S9E07)

The DBMS file title "Danger Island Comparative Wickedness of Civilized
**and** Unenlightened Peoples" splits at the interior "and". The atom
"Unenlightened Peoples" substring-matches E07 (the atom is a FRAGMENT of
the title), and `_extend_partial_title_run` anchors there, inventing E06
from the branding fragment "Danger Island Comparative Wickedness of
Civilized" → episodes (6,7) at 0.70. After the run edge is trimmed, the
E07 conflict pits its `title-strong-inexact` claim against the EDGE copy's
clean `title-agree` 0.96 → DBMS loses exactly this one slot while winning
every other (hence "one episode used the duplicate source").

**Fix:** an atom may anchor a run only when it CONTAINS (or equals) the
matched title, never when it is merely contained by it.

## RC44 — consolidated phase-1 title claims run before show-name stripping; no explicit-hint rescue (Futurama S09E01)

Reproduced in the previous run only: S12/S13 folders (not yet on TMDB)
forced the WHOLE show through the consolidated scanner (`extra = user_nums
- tmdb_nums` in `_tv_scanner.py`). In `try_title_based_matching` phase 1,
the file "Futurama S09E01 Futurama.mkv" still carries raw title
"Futurama" (show-name stripping happens later, in
`build_consolidated_table`), which token-run-substring-matched 'The
**Futurama** Holiday Spectacular' → reserved (6,13) over its own explicit
S09E01 → lost the table conflict to the real S06E13 file. The rescue
passes skip it: by table time its `raw_title` is None and no rescue falls
back to the explicit S/E hint.

**Fixes:** (a) strip show-name-equal raw titles BEFORE phase-1 title
matching (never title-match a bare show name); (b) add a rescue: a
lost-conflict/unassigned file with an explicit season-relative hint whose
`(hint, episode)` slot exists and is unclaimed re-assigns there at review
confidence.

## RC45 — chained title-no-match squatters block cross-season rescues (Rugrats S7/S8)

'The Big Showdown & Doctor Susie' = TMDB S07E12 + S07E14 (non-contiguous;
E13 'Runaway Reptar' is a standalone file) — correctly stays unassigned,
and per the user it must NOT be forced onto (12,14). The cascade is
elsewhere: 'Back To School & Sweet Dreams' (really S09E21-22, both
unclaimed at scan end) squats on S08E19-20 with
`number+title-no-match+title-multi-segment`; that blocks 'Cat Got Your
Tongue & The War Room & Attention Please' (an EXACT contiguous run at
S08E19-21) from leaving S07E14-16 — which is the wrong file the user sees
on E14. `rescue_cross_season_segmented` runs once, before conflict
resolution, and its block-guard counts other movable squatters as claims;
there is no post-conflict segmented pass.

**Fix:** iterate run-moves to a fixpoint with the guard excluding all
candidates' own slots (chains unwind: Back To School → S9, then Cat Got →
S8E19-21, then 'And The Winner Is...' → S8E22-24), and run a second
`rescue_cross_season_segmented` after conflict resolution.

## RC46 — near-exact unique fuzzy titles park at 0.70 (Rawhide "apostrophes")

Rawhide S5 is systematically off-by-one; most files re-anchor via
`title-strong` exact matches at 0.92. Three park at 0.70 REVIEW because
the title differs microscopically from TMDB and only the FUZZY tier
catches it (rule 2b → `CONF_TITLE_WINS_INEXACT`): 'Buryin' Man'/'Buryin'
Men', 'Commanchero'/'Comanchero' (edit distance 1), 'Incident At The
Trail's End'/'Incident of the Trail's End' (stopword-only difference).
The apostrophes are coincidental. Related: S06E16 'Incident of Midnight
Cave' vs 'Incident of the Midnight Cave' ("the"-only difference) matches
NO tier at all and survives only via its own number (0.88).

**Fix:** a unique fuzzy hit whose compact edit distance is ≤2 (or whose
token sequences are equal after dropping leading stopwords/articles)
ranks as a near-exact tier that can override a disagreeing number at
auto-accept confidence; stopword-insensitive equality also joins the
match ladder so "the"-only differences agree with their number.

## RC47 — duplicate-group merge force-checks shows (Squidbillies, Archer)

`merge_duplicate_episode_claims` sets
`primary.checked = any(item.is_actionable ...)` unconditionally. The only
two checked=True states in the run are exactly the two merged
duplicate-group shows (Squidbillies, Archer); every other show defaults
to unchecked. Review gating (`has_episode_problems`) is bypassed, so a
show sitting in Review Episodes arrives pre-checked.

**Fix:** merged primaries follow the same default as everyone else:
checked only when actionable AND free of conflicts/review rows/unmapped
primaries.

## RC48 — acronym vs expansion defeats every title tier (ST:TNG specials)

'Stardate Revisited The Origin of Star Trek **TNG** Part 1 Inception' vs
TMDB 'Stardate Revisited: The Origin of Star Trek: **The Next
Generation** - Part 1: Inception'. The acronym breaks exact
(different compacts), substring (neither contains the other), part-number
(bases differ), and fuzzy (edit distance ≫2, token walk fails at
"tng"/"the"). Affects 'Energized!' and all three Stardate parts; the
"Season N Extra" files are genuinely absent from TMDB and correctly stay
unmatched.

**Fix:** token-level acronym equivalence — a single token equal to the
initials of a consecutive token run on the other side (tng ↔ the next
generation) counts as equal during title comparison; when all other
tokens match exactly, the match ranks as strong (notation-blind, like
'&' ↔ 'and').
