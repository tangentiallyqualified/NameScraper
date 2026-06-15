# TV Batch-Mode Cleanup — Remaining Work Handoff

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:systematic-debugging` (these are behavioural bugs — reproduce before fixing) and `superpowers:test-driven-development` (failing test first). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish cleaning up TV batch mode against the real library at `P:\data\downloads\in progress files`. Three issues remain after the 2026-06-15 fixes; each is diagnosed below with reproduced evidence, but deferred because it needs a design decision or a larger feature than a point fix.

**Tech Stack:** Python 3, PyQt6, pytest. Windows + PowerShell. Run Python via `.venv\Scripts\python.exe`.

**Run tests with:** `.venv\Scripts\python.exe -m pytest -q --ignore=tests/test_gui_qt_smoke.py` from repo root. Qt smoke uses `scripts\test-smoke.cmd` (writes `.pytest_cache/smoke/latest.log`). Commits go through chat-approved messages per `CLAUDE.md` (do **not** auto-push).

---

## Context: what already shipped (don't redo)

Two local commits on `dev/GUI3` already landed (not pushed):

- `33fbabd` — episode-matching hardening: parse `S01 E01-E02` (separator between season/episode tokens, CatDog); stop `extract_source_title_prefix` inventing a prefix from episode titles ending in a standalone number (KaBlam "Money Train 2", Rick and Morty "Vindicators 3"); honor multi-episode runs in the consolidated scanner (Rocket Power); name the slot in lost-conflict reasons.
  - **CatDog is only partially fixed:** the parsing fix means multi-episode files now map to *both* episodes instead of one, but CatDog episode matching **still needs review** and **some multi-episode files map to the WRONG episodes** (source vs TMDB ordering drift — same class as Rugrats; see Task 2).
- `3e0d3c1` — show-identification + UI: per-season episode-count tiebreak (Euphoria S01); franchise-prefix compatibility (Andor S02 "Star Wars Andor"); drop dangling trailing article in `clean_folder_name` (Lucy, the Daughter of the Devil); "Unassign All" button; active-filter checked state; stop the stuck poster spinner.

Baseline after these: **776 non-GUI tests + 161 Qt smoke, all green.**

---

## Reproduction methodology (reuse this — it is essential)

These bugs are NOT diagnosable from reading code; reproduce against real files + live TMDB first. Build a throwaway harness under `scripts/` and delete it when done.

- TMDB key is available in-process: `from plex_renamer.keys import get_api_key; key = get_api_key("TMDB")` → `from plex_renamer.tmdb import TMDBClient; tmdb = TMDBClient(key)`. Calls work and are cached.
- Drive the real scan path: `from plex_renamer.engine._tv_scanner import TVScanner`; build `show_info = {"id", "name", "year"}` from `tmdb.get_tv_details(show_id)`; then `items, mismatched = TVScanner(tmdb, show_info, root, show_match_confidence=1.0).scan()`. Each `PreviewItem` has `.status`, `.season`, `.episodes`, `.episode_confidence`, `.new_name`, `.original`.
- Flat multi-season folders route to `scan_consolidated()`; folders with `Season NN` subdirs use the normal path. `scan()` picks automatically.
- Episode auto-accept threshold = **0.85**; show auto-accept threshold = **0.55** (`plex_renamer/engine/_state.py`).
- Core resolution policy + all confidence constants: `plex_renamer/engine/_episode_resolution.py` (`resolve_file`, `apply_confidence_adjustments`). Episode-number/title parsing: `plex_renamer/_parsing_episodes.py`. Cross-season specials rescue lives in `plex_renamer/engine/_tv_scanner_normal.py::_resolve_into_table`.

---

## Task 1: As Told By Ginger — rescue good-title episodes whose number isn't in the folder's TMDB season

**Folder:** `As Told By Ginger (2000) Season 1-3 S01-03 (480p AMZN.WEBDL x265 10bit EAC3 2.0 EDGE2020)` — TMDB id **1760**.

**Reproduced root cause:** The source numbers episodes differently from TMDB. Files like `S01E17 - I Spy a Witch`, `S01E18 - Deja Who`, `S01E19 - An Even Steven Holiday Special`, `S01E20 - Piece of My Heart` have **good single titles that exist in TMDB**, but under a *different regular season*. `S01E17` etc. are not in TMDB's Season 1, so they become `SKIP: episode not in TMDB season`. The normal scanner already rescues by title into **Season 0/specials** (`_resolve_into_table`, the `specials_titles` block) but **never into another regular season**. There are also number-collision conflicts (`S02E10 April's Fools` vs the real S02E10) that stem from the same numbering drift.

**Design decision needed (this is why it was deferred):** Extending title rescue to all regular seasons risks false matches on short/common titles. Recommended conservative approach:
- Only rescue when the file is currently unassigned with reason `REASON_NOT_IN_SEASON` **and** the parsed number is genuinely absent from the folder season.
- Match by **exact** normalized title only (`match_title_in_titles` strength `== _TITLE_EXACT`, i.e. `title-strong`/1.0) against the *other* regular seasons; ignore substring/part-number strengths to avoid drift.
- Require the rescued slot to be otherwise unclaimed; route to **review** confidence (not auto-accept), since the source numbering is known-wrong.
- Decide ordering vs the existing S0 rescue (prefer an exact regular-season title over an inexact special).

**Steps:**
- [ ] Reproduce the SKIP set with the harness; capture the exact titles and their true TMDB season/episode.
- [ ] Write a failing test in `tests/test_tv_scanner_normal.py` (or a new file) for a file whose number is not in its folder season but whose exact title is in another regular season → expect it assigned to the correct season at review confidence.
- [ ] Implement cross-regular-season exact-title rescue in `_resolve_into_table` (mirror the `specials_titles` block; add slots if needed) — guarded as above.
- [ ] Verify Ginger end-to-end; confirm no new false matches on other shows; full suite + smoke green.

---

## Task 2: Rugrats & CatDog — wrong episodes matched on combined-title multi-episode files

**Folders:**
- `Rugrats (1991) Season 1-9 S01-09 (480p AMZN.WEBDL x265 10bit EAC3 2.0 EDGE2020)` — TMDB id **3022**.
- `CatDog (1998-2005) - Complete ANIMATED TV Series, S01-S04 - 1080p Web-DL x264` — TMDB id **1567** (scans as `mismatched=True`).

**Reproduced root cause (partial):** Multi-episode files use **combined segment titles** (e.g. Rugrats `S01E02-E03 - Barbeque Story & Waiter, There's A Baby In My Soup`). A combined title substring-matches 2+ episodes → `match_title_in_titles` returns `None` (ambiguous), so `resolve_file` falls to **number-only** (rule 3, ~0.60 then lifted to ~0.88 by floors). Where the source's per-season numbering diverges from TMDB's ordering, the number picks the **wrong** episode and there is **no title safety net** to catch it.

**Confirmed CatDog instance:** `CatDog - S01 E05-E06 - The Island and All You Need is Lube` maps to TMDB S01E05-E06 by number but those slots are titled **"Full Moon Fever" / "War of the CatDog"** — i.e. the file's real episodes ("The Island", "All You Need is Lube") live at different TMDB numbers. The run maps to the wrong episodes, and CatDog still lands in review. This is the same defect as Rugrats and should be fixed together. CatDog is the easiest reproduction (run the harness on id 1567 and diff each file's title segments against the assigned TMDB titles).

**Blocked on input (Rugrats only):** Need the specific Rugrats season that is visibly wrong to pin its exact source↔TMDB ordering mismatch. (Ask the user, or sweep all 9 seasons with the harness and flag every file where the file's combined title segments don't match the TMDB titles at the assigned numbers.) CatDog needs no extra input — the E05-E06 case above is a ready reproduction.

**Likely fix direction (validate after pinning):**
- [ ] Start with CatDog (id 1567) — it reproduces immediately. Sweep all seasons of both shows; for each multi-episode file, split the combined title on `&`/`and`/`,` and check whether each segment matches the TMDB title at the *assigned* number; report mismatches.
- [ ] If the source order is internally consistent but offset from TMDB, consider matching multi-segment titles **segment-by-segment** (each segment is one episode's exact title) and assigning the run by *title* rather than number — falling back to number only when segment titles don't resolve.
- [ ] Failing test first (combined-title file whose number maps wrong but whose segment titles map right → expect the title-derived run). Then implement in `resolve_file` / a new multi-segment helper. Full suite + smoke green.

---

## Task 3: Adult Swim Infomercials — year-as-season folders fan out into many shows

**Folder:** `Adult Swim Infomercials` (TMDB show is "Infomercials", id **115657**, normal Season 1/Season 2).

**Reproduced root cause:** Children are year-named season dirs `S00, S2009, S2012…S2020` with files like `Adult Swim Infomercials S2014E01 Fartcopter.mp4`. `get_season("S2014")` returns `None` because `plex_renamer/_parsing_seasons.py` (the `S(\d{1,2})` rule) deliberately caps season numbers at 2 digits so release years aren't treated as seasons. So the umbrella folder is classified as a **container**, each `S20XX` dir becomes a separate show candidate (11 of them), each searched with a nonsense query equal to its folder name (`"S2016"`, `"S2020"`…) → random unrelated matches. The real show is never searched.

**Design decision needed (largest of the three):** Don't broaden `S\d{4}` to mean "season" globally (it would mis-read the common `Show S2016 1080p` release-year pattern). Recommended layered approach:
- [ ] At discovery/classification: detect a folder whose children are *predominantly* bare `S\d{4}` labels and treat it as a **single show root**, querying the umbrella folder name ("Adult Swim Infomercials" → correctly hits TMDB "Infomercials"). Relevant code: `plex_renamer/app/services/tv_library_discovery_service.py` / `_tv_library_classification.py`.
- [ ] Add a **year-season → TMDB-season** mapping layer in `plex_renamer/engine/_tv_scanner_seasons.py` (map `S2014`/`S2014E01` onto the show's actual seasons, likely by air-year of TMDB episodes).
- [ ] Failing tests for both the classification (umbrella stays one show) and the year→season mapping. Full suite + smoke green.

---

## Definition of done

- [ ] Each task reproduced, fixed test-first, and verified end-to-end against the `P:` folder named above.
- [ ] `776+` non-GUI tests and `161+` Qt smoke still green (counts only grow with new tests).
- [ ] Throwaway harness scripts deleted.
- [ ] Changes committed with a chat-approved message; not pushed unless asked.
