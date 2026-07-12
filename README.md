# NameScraper

NameScraper is a desktop app for renaming and reorganizing your TV and movie
files into the clean, media-server-friendly layout that Plex, Jellyfin, and Emby
expect — `Show (Year)/Season 01/Show (Year) - S01E01 - Title.ext` — using TMDB
metadata to identify each release and fill in episode titles.

It is built on PySide6 (Qt) with a toolkit-independent backend that does the
parsing, matching, scan planning, and job execution.

![Python](https://img.shields.io/badge/python-3.11+-blue)
![PySide6](https://img.shields.io/badge/ui-PySide6-41cd52)
![TMDB](https://img.shields.io/badge/metadata-TMDB-01d277)
![Platform](https://img.shields.io/badge/platform-Windows%20(primary)%20%7C%20macOS%20%7C%20Linux-lightgrey)

> **Naming note:** the app's display name is **NameScraper**, but the Python
> package is still `plex_renamer` (and the console script is `plex-renamer`), so
> you launch it with `python -m plex_renamer`.

---

## Status

The PySide6 UI redesign (tracked internally as "GUI V4") is **complete**. The Qt
shell is the only shell — the earlier tkinter interface has been removed. The app
is at version `0.1.0`; it is used and dogfooded, not yet formally packaged for
distribution.

The redesign delivered a two-panel workspace, bulk episode assignment, an
off-thread guide/preview pipeline with a busy overlay, toast notifications, an
animated loading screen, a restyled queue/history with companion-file surfacing,
a restyled settings area, and a dark, token-based theme validated at 100/150/200%
display scaling.

Development is primarily done and tested on Windows (the shell includes a
Windows-specific transient-popup suppressor); PySide6 itself is cross-platform.

---

## Features

### TV

- **Single-show** scanning and **batch discovery** of a whole TV root folder.
- Season/episode parsing across common release naming styles, including
  anime/fansub **absolute numbering and episode ranges** (e.g.
  `[Group] Show - 166-167 [...]`) and **multi-episode files** (`S01E01-E02`).
- **Specials / Season 0** handling, and flat-folder absolute numbering that keeps
  regular episodes aligned even when TMDB also lists specials.
- **Companion files** (subtitles, `.nfo`, etc.) are detected and moved alongside
  their video.
- **Confidence-gated matching:** high-confidence shows/episodes auto-accept;
  lower-confidence results are routed to review with alternate-match pickers.
- **Completeness reporting** against TMDB's episode list (what's matched, what's
  missing per season).

### Movies

- Bulk movie-folder scanning with automatic filtering of TV episodes that are
  mixed into movie folders.
- Confidence-based TMDB matching with manual re-match, and detection of files
  that are already correctly named.
- Root-level movie files are moved into `Title (Year)/Title (Year).ext` rather
  than renaming the selected root folder itself.

### Bulk assign

For shows where automatic mapping needs a hand, **Bulk Assign** mode lets you
check files and map them onto episode slots in order (with auto-map for the
remainder), staged in-place and applied in one action.

### Queue & History

- A rename **queue** and **history**, persisted in SQLite, driven through a
  shared job pipeline.
- Completed jobs can be **reverted** from History; a failed revert stays visible
  as `revert_failed` (only clean completions are marked `reverted`).
- Status pills, poster reuse, and companion files surfaced under their video in
  the job detail view.

### Settings

- TMDB API key entry, destination folders, display options, and matching
  thresholds.
- Destructive actions (clear cache / clear history) live under **Data** behind
  confirm-with-count dialogs.
- API keys are stored via the OS keyring when available, falling back to local
  app-data storage.

---

## The interface

The app opens maximized with five tabs: **Settings**, **TV Shows**, **Movies**,
**Queue**, and **History**.

The TV and Movie tabs share a two-panel **workspace**:

- **Left — roster:** poster-forward rows grouped by state (queued, review,
  matched, and dedicated groups like *Specials & Unmapped Only*), with season
  chips, a status pill, and a confidence bar.
- **Right — work panel:** a show header (with async-loaded overview), a season
  strip, a toolbar, and a virtualized episode table with ghost rows for missing
  episodes and in-place expansion for per-episode detail. A footer shows the file
  breakdown alongside **Fix Match** and **Queue** actions.

Long-running work (building an episode guide/preview for an uncached show) runs
off the UI thread behind a busy overlay, so large libraries don't freeze the
window.

---

## Quick start

### Requirements

- Python **3.11+**
- A **TMDB API key** (free — https://www.themoviedb.org/settings/api)

### Install

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
```

PySide6, Pillow, requests, and keyring install as core dependencies — there is no
separate UI extra.

### Launch

```powershell
.\.venv\Scripts\python.exe -m plex_renamer
```

(Or run the installed `plex-renamer` console script.)

### First run

1. Open the **Settings** tab.
2. Enter your **TMDB API key**.
3. Point the app at a **TV root folder** or a **movie root folder** and scan.

---

## Configuration & debugging

### Logging

Override the startup log level with:

```powershell
$env:PLEX_RENAMER_LOG_LEVEL="DEBUG"
```

Practical values are `INFO` (default) and `DEBUG`.

### Transient-window diagnostics (Windows)

A targeted flag logs candidate transient popup windows, for debugging flicker on
Windows:

```powershell
$env:PLEX_RENAMER_DEBUG_TRANSIENT_WINDOWS="1"
.\.venv\Scripts\python.exe -m plex_renamer
```

---

## Testing

Dev dependencies (just pytest) install with the `dev` extra:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

- **Full suite:** `.\.venv\Scripts\python.exe -m pytest`
- **Fast unit sweep:** `.\scripts\test-fast.cmd`
- **Qt smoke suite:** `.\scripts\test-smoke.cmd`

The smoke wrapper captures full pytest output to `.pytest_cache/smoke/latest.log`
and prints a concise pass/fail summary with the real exit code (more reliable
than reading raw terminal output from offscreen PySide runs).

There is also an opt-in real-library validation harness,
`scripts/scan_real_library.py`, used to exercise the batch TV engine against a
real media drive; it is not part of the automated suite.

---

## Architecture

The project is split into three layers, so the backend has no UI dependencies.

### Core domain layer

Toolkit-independent parsing, TMDB access, scanning/rename planning, and job
persistence — e.g. `parsing.py` (+ `_parsing_*.py`), `tmdb.py`, the `engine/`
package (batch TV orchestration, episode resolution, matching), `job_store.py`,
`job_executor.py`, and `keys.py`.

### Application layer

UI-neutral controllers, models, and services shared by the interface — e.g.
`app/controllers/` (media and queue controllers), `app/models/`, and
`app/services/` (settings, cache, command gating, refresh policy, episode
mapping, projection cache, TV/movie library discovery).

### GUI layer

`gui_qt/` — the PySide6 shell: `app.py` bootstrap, `main_window.py`, the rendered
theme (`theme.py` + `theme.qss.tmpl`), `resources/`, and `widgets/`. It consumes
the controllers and services rather than duplicating orchestration in widgets.

---

## Repository layout

```text
plex_renamer/
├── __main__.py          # entry point → gui_qt.app.run()
├── constants.py
├── parsing.py           # + _parsing_*.py helpers
├── tmdb.py              # + _tmdb_*.py helpers
├── job_store.py         # + _job_store_*.py helpers
├── job_executor.py
├── keys.py
├── thread_pool.py
├── engine/              # batch TV orchestration, episode resolution, matching
├── app/
│   ├── controllers/
│   ├── models/
│   └── services/
└── gui_qt/
    ├── app.py
    ├── main_window.py
    ├── theme.py
    ├── resources/
    └── widgets/
scripts/                 # test-fast / test-smoke wrappers, real-library harness
tests/
docs/
```

Deeper design and implementation notes live under `docs/` (the GUI V4 design spec
and handoff).
