# Episode Parsing & Resolution Edge-Case Hardening — Design

**Date:** 2026-06-29
**Status:** Approved for planning
**Scan corpus used for evidence:** `P:\data\downloads\in progress files` (178 show folders, 7,194 video files)

## Problem

A review of the episode-matching engine against a large real-world download
directory surfaced a small number of genuine parsing gaps. The bulk of the
engine is healthy — specials (S00) detection, multi-episode expansion
(ranges + concatenation), year-folder umbrellas, and anime absolute numbering
all parse correctly at scale. The gaps that remain are concentrated and
reproducible.

This work hardens three of them **without changing the tuned resolution /
confidence policy** unless a real failure is reproduced. All changes are in the
pure engine layer (`plex_renamer/_parsing_*.py`, `plex_renamer/engine/*`); none
touch the GUI.

### Evidence (offline parsing diagnostic over the corpus)

| Cluster | Count | Status |
|---|---|---|
| Specials / S00 (folders + files) | 343 files, 28 folders | ✅ correct |
| Multi-episode (ranges, `E01E02`, `E18E19E20E21`) | 500 files | ✅ correct |
| Year-folder umbrella (`S2009`–`S2020`) | 10 | ✅ correct |
| **Bracketed `[NN]` episodes** | 33 files (Wolf's Rain 0/33) | ❌ invisible |
| **Numeric-in-title false positives** | `No.6`→6, `Se7en`→7, `Catch-22 - 01`→[22,1] | ❌ phantom episodes |
| File `S##` ≠ folder season | 128 files (Animaniacs 2020) | ⚠️ needs live-TMDB repro |

## In Scope

1. **Bracketed `[NN]` episode numbers** (parsing; additive, low risk)
2. **Numeric-in-title guards** (parsing; narrow, moderate risk)
3. **File-vs-TMDB season mismatch** (resolution; investigation-first)

## Out of Scope

- Splitting two-distinct-shows-in-one-folder (`Harvey Birdman + Birdgirl`,
  `Space Ghost + The Brak Show`) — 2 instances, scanner-level, higher risk.
- Any GUI change.
- Re-tuning confidence constants speculatively.

---

## Item 1 — Bracketed `[NN]` episode numbers

### Problem (confirmed)
Fansub names of the form `[Group][Show Title][NN][quality tags…]` are wholly
unrecognized:

```
[DBD-Raws][Wolf's Rain][01][1080P][BDRip][HEVC-10bit][FLACx2].mkv
  extract_episode      -> []        (no episode)
  looks_like_tv_episode -> False    (not even classified as TV)
```

The entire show is invisible to the TV scanner. This is a common convention, so
it likely recurs beyond the one folder in the corpus.

### Change

**`plex_renamer/_parsing_episodes.py::extract_episode`**
Add a **late-fallback** recognizer (runs only after all current S##E##, NxNN,
dash, `Ep##`, and bare-number patterns miss, so nothing currently parsed
changes):

- Match a `[…]` group whose entire content is an episode token: `\d{1,3}`,
  optionally with a `v\d+` version suffix or an `NN-NN` range.
- Reject the bracket if the number is in `RESOLUTION_NUMBERS` or is a 4-digit
  year (`YEAR_MIN..YEAR_MAX`).
- Return `is_season_relative=False` (absolute numbering, consistent with the
  existing anime bare-number path → routes through consolidated/inferred season
  mapping downstream).
- Title = `None` (these names carry no episode title).

**`plex_renamer/_parsing_tv.py::looks_like_tv_episode`**
Add the same fansub bracket-episode shape (a leading `[group]` followed
somewhere by a pure-numeric `[NN]` bracket) so these files are classified as TV
episodes and routed to the scanner.

**`plex_renamer/_parsing_tv.py::extract_source_title_prefix`** (title extraction —
approved)
Recognize the `[Group][Title][NN]` layout and return the **second** bracket
group as the show title (`Wolf's Rain`). The folder name for these releases is
often unusable (`[DBD-Raws][狼雨][01-30TV全集…]`), so the per-file English title
bracket is the only clean show-search signal. This flows through
`best_tv_match_title` to the TMDB search.

### Guards / counter-tests (must NOT match as an episode)
`[1080P]`, `[480]`, `[v2]`, `[HEVC-10bit]`, `[FLACx2]`, `[B36160B7]` (CRC hash),
`[2006]` (year).

### Risk
Low. The episode recognizer is a pure late fallback; the classifier and title
extractor are additive. No existing pattern's behavior changes.

---

## Item 2 — Numeric-in-title guards

### Problem (confirmed)
The bare-number fallback in `extract_episode` is greedy and grabs digits that
are part of a title:

```
Blue Submarine No.6 …      -> [6]     (the 6 in "No.6")
Se7en.mkv                  -> [7]     (digit embedded in letters)
Catch-22 - 01 - Pilot.mkv  -> [22, 1] (22 from the title + the real 01)
Apollo 13.mkv / Babylon 5  -> [13]/[5] (movies, already gated by tv=False)
```

### Change — high precision only
The bare-number fallback is also what legitimately catches anime absolute
numbering (`Bartender 02`). Guards must be specific so that path is untouched:

1. **Digit-embedded-in-letters** (`Se7en`): add a word-boundary lookbehind on
   the *bare-number* fallback so a digit flanked by letters is not an episode.
   (`Bartender 02` has a space before `02` → still matches.)
2. **Volume/number markers**: reject `No.\s*\d`, `#\d`, `Vol\.?\s*\d` as
   episode numbers.
3. **`Apollo 13` / `Babylon 5`**: left to TV-gating (`looks_like_tv_episode` is
   already `False` for these movie names). No parsing change.
4. **`Catch-22 - 01`**: documented as a known ambiguous limitation. Over-fitting
   a "word-hyphen-number is part of the title" rule is fragile and risks the
   dash-delimited anime path; not worth the destabilization.

### Risk
Moderate. Mitigated by (a) keeping guards specific to `No.`/`#`/`Vol.` and
embedded-in-letters, (b) a dedicated regression test asserting `Bartender 02`,
`Show - 02`, and other legit bare numbers still parse.

---

## Item 3 — File-vs-TMDB season mismatch (investigation-first)

### Key finding
In `engine/_tv_scanner_normal.py::build_normal_table`, inside a season folder
the **folder's season wins**; the file's parsed `S##` (`extract_season_number`)
is used *only* to redirect a file into Season 0 when `file_season == 0`.
Therefore:

```
Animaniacs (2020)/Season 1/Animaniacs (1993) - S06E01 - Jurassic Lark.mkv
  folder_season = 1
  extract_episode -> episodes=[1], season_relative=True
  -> resolved against SEASON 1 titles by episode [1] + title "Jurassic Lark"
  -> the bogus S06 is harmlessly ignored
```

This very likely already resolves **correctly**. The engine also already has
`rescue_cross_season_titles` (As-Told-By-Ginger-style cross-season title rescue)
and consolidated/absolute mapping. So #2 is **not assumed to be a bug**.

### Approach
1. Build a **headless, engine-only** reproduction harness (in `scratchpad/`,
   not committed) that uses the configured live TMDB key to scan the
   representative mismatch folders and dump per-file resolution outcomes
   (assigned season/episode, confidence, evidence, REVIEW/SKIP reason):
   - `Animaniacs (2020)…` (S06 files in S01–S03 folders)
   - `As Told By Ginger…` (cross-season titles)
   - `Squidbillies (2004)` vs `Squidbillies (2005)` (year/duplicate folders)
   - `Rick and Morty Season 0X` (Specials subfolders)
2. **Classify** each outcome: correct, deliberately-REVIEW (by design), or
   genuinely wrong.
3. **Only** design code changes for confirmed *wrong* outcomes.
4. If they already resolve correctly (the expected result for Animaniacs):
   **report the evidence and add offline regression tests** that lock in the
   behavior using synthetic season titles — **no policy change** (approved
   outcome, honors "don't destabilize").

### Risk
Low by construction — investigation gates any code change. The default outcome
is "add regression tests, change nothing."

---

## Testing strategy

- **Offline unit tests** (no network, deterministic), following existing
  conventions in `tests/test_episode_resolution.py` and
  `tests/test_tv_scanner_normal.py` (synthetic `season_titles` dicts):
  - Item 1: `[NN]` recognition + the full counter-test set; title extraction
    from `[Group][Title][NN]`; `looks_like_tv_episode` classification.
  - Item 2: guard cases (`No.6`, `Se7en`, `Catch-22 - 01`) reject; legit bare
    numbers (`Bartender 02`, `Show - 02`) still parse.
  - Item 3: regression tests asserting the mismatch folders' expected
    resolution (synthetic titles mirroring the live-TMDB findings).
- **Full suite**: `scripts/test-smoke.cmd` + `pytest` — must stay green
  (no regressions).
- **Corpus re-diagnostic**: re-run the offline directory diagnostic to confirm
  Wolf's Rain et al. now parse and that no previously-parsed file changed.

## Files expected to change

- `plex_renamer/_parsing_episodes.py` (Items 1, 2)
- `plex_renamer/_parsing_tv.py` (Item 1: classification + title extraction)
- `tests/…` (new offline tests for all three items)
- Possibly `plex_renamer/engine/_episode_resolution.py` **only if** Item 2
  investigation confirms a wrong outcome (not expected).

## Success criteria

- Wolf's Rain-style `[NN]` files parse to their episode number and classify as
  TV; the show title is extracted for search.
- `No.6` / `Se7en` no longer yield phantom episode numbers; legit anime absolute
  numbering still parses.
- The file-vs-folder-season mismatch behavior is characterized with evidence
  and locked by regression tests (code changed only if a real bug is found).
- Entire existing test suite remains green.
