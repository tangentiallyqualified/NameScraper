# Multi-Episode Filename Formatting — Design

**Date:** 2026-06-29
**Status:** Approved for planning

## Problem

Multi-episode files produce overlong, redundant filenames. The 4-part Avatar
finale is the motivating case:

```
Avatar - The Last Airbender (2005) - S03E18-E19-E20-E21 - Sozin's Comet - The Phoenix King-Sozin's Comet - The Old Masters-Sozin's Comet - Into the Inferno-Sozin's Comet - Avatar Aang.mkv
```

(187 characters.) Two defects:

1. **Episode marker not collapsed** — `S03E18-E19-E20-E21` should be the range
   `S03E18-E21` for a contiguous run.
2. **Titles concatenated raw** — four episode titles joined verbatim, with no
   length bound. Risks exceeding filesystem path limits and is unreadable.

## Scope

All changes are confined to the pure function `build_tv_name` in
[plex_renamer/_parsing_names.py](../../../plex_renamer/_parsing_names.py),
plus one private helper. No GUI, no scanner, no resolution-policy changes.
`build_tv_name` is already the single chokepoint for TV filename construction
(used by both the resolution confidence pass and preview projection), so fixing
it here covers every code path.

## Out of Scope

- Combined two-show folder splitting (separate spec/cycle).
- Making the length cap a user setting (a module constant for now; can be
  promoted later).
- Changing single-episode naming, except where a name exceeds the global
  length cap (rare safety-net truncation).

## Current behavior (reference)

```python
if len(episodes) == 1:
    ep_part = f"E{episodes[0]:02d}"
else:
    ep_part = "-".join(f"E{ep:02d}" for ep in episodes)   # E18-E19-E20-E21
...
unique = list(dict.fromkeys(titles))
title_part = "-".join(unique)                              # raw concatenation
```

Non-contiguous episode runs (e.g. `[3, 5]`) never reach `build_tv_name`: the
scanner marks them `REASON_AMBIGUOUS_RUN` upstream. The contiguity check below
is still written to be correct for any input.

## Design

### Part 1 — Episode-range collapse

Render a contiguous ascending run as a first–last range; otherwise join each
episode explicitly.

- `[1]` → `E01` (unchanged)
- `[1, 2]` → `E01-E02` (unchanged; a 2-run is already first–last)
- `[1, 2, 3]` → `E01-E03`
- `[18, 19, 20, 21]` → `E18-E21`
- `[3, 5]` (non-contiguous) → each rendered explicitly via join; this case is
  guarded upstream (`REASON_AMBIGUOUS_RUN`) and never actually reaches
  `build_tv_name`, so the behavior is academic.

Precise rule: a run is contiguous when `episodes == list(range(first, last+1))`
and `len > 1`. Contiguous → `E{first:02d}-E{last:02d}`. Single → `E{n:02d}`.
Otherwise (non-contiguous) → `"-".join(f"E{n:02d}")` over the actual numbers.

### Part 2 — Title common-base collapse

New private helper `_common_title_base(titles) -> str | None`:

1. Operate on the de-duplicated titles (existing `dict.fromkeys`).
2. Require ≥ 2 titles.
3. Compute the longest common **word-prefix** across the titles
   (case-insensitive comparison; original casing preserved from the first
   title).
4. Trim trailing noise from that prefix: separators (`-`, `–`, `,`), dangling
   part-words (`Part`, `Pt`, `Vol`, `Volume`, `Chapter`), and dangling articles
   (`the`, `a`, `an`).
5. Return the base only if it is non-trivial (≥ 3 characters) and strictly
   shorter than the raw join; otherwise `None`.

Worked examples:

| Titles | Common base |
|---|---|
| `Sozin's Comet - The Phoenix King (1)` ×4 (filename form) | `Sozin's Comet` |
| `Sozin's Comet, Part 1: The Phoenix King` ×4 (TMDB form) | `Sozin's Comet` |
| `Dog Gone` + `All You Can't Eat` (CatDog) | `None` → raw join unchanged |

When the helper returns a base, `title_part = base`. Otherwise
`title_part = "-".join(unique)` (current behavior).

### Part 3 — Global length cap (safety net)

`MAX_FILENAME = 150` (characters, including the extension). After the name is
assembled and sanitized, if it exceeds the cap, shorten the **title segment**
(the text between the last ` - ` and the extension) at a word boundary, append
a single-character ellipsis `…` (U+2026, filesystem-safe and not stripped by
`sanitize_filename`, which only trims trailing dots/spaces after the
extension), and re-check. The show/season/episode portion and the extension are
never truncated. 150 leaves comfortable headroom under the 255-char path-
component limit for the output directory + show + season folders.

This cap applies to all names but, after Part 2, essentially only fires for
many genuinely-distinct titles; single-episode names are affected only in
pathological cases.

## Data flow

`build_tv_name(show, year, season, episodes, titles, ext)`:
1. `year_part` (unchanged).
2. `ep_part` ← Part 1 (range collapse).
3. `title_part` ← Part 2 (`_common_title_base` or raw join).
4. `raw = f"{show}{year_part} - S{season:02d}{ep_part} - {title_part}{ext}"`.
5. `name = sanitize_filename(raw)` (unchanged).
6. Part 3 — if `len(name) > MAX_FILENAME`, truncate title segment + `…`,
   re-assemble, re-sanitize.
7. Return `name`.

## Testing (offline, deterministic)

New tests alongside the existing parsing tests:

- **Range:** `[18,19,20,21]`→`E18-E21`; `[1,2]`→`E01-E02`; `[1]`→`E01`;
  non-contiguous `[3,5]`→`E03-E05` (explicit, not a range — assert exact
  string); `[1,2,3]`→`E01-E03`.
- **Common base:** Avatar filename form and TMDB `, Part N:` form both →
  `Sozin's Comet`; `Dog Gone` + `All You Can't Eat` → join unchanged; two
  unrelated titles (`Alpha` + `Beta`) → no spurious base.
- **Cap:** a constructed many-distinct-title case yields a name ≤ 150 ending
  in `…` before the extension; a short name is returned unchanged; the
  extension and `SxxEyy` marker survive truncation.
- **Regression:** existing `build_tv_name` tests and the full suite stay green.

## Success criteria

- Avatar finale → `Avatar - The Last Airbender (2005) - S03E18-E21 - Sozin's Comet.mkv`.
- Contiguous multi-episode markers always render as first–last ranges.
- No TV filename exceeds 150 characters.
- Two-episode and single-episode naming is unchanged for existing cases.
- Full test suite remains green.
