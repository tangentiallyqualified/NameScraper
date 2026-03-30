# Plex Renamer

Plex Renamer is a desktop application for renaming and reorganizing TV and movie files into Plex-compatible structures using TMDB metadata.

The project currently ships with two GUI shells built on the same backend:

- `python -m plex_renamer`: tkinter shell, still the default entry point
- `python -m plex_renamer --qt`: PySide6 shell (`GUI3`), now suitable for active dogfooding across TV, movies, queue, history, and settings

The long-term direction is the PySide6 shell. The current migration work lives on `dev/GUI3`.

![Python](https://img.shields.io/badge/python-3.11+-blue)
![TMDB](https://img.shields.io/badge/metadata-TMDB-01d277)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)

---

## Current Status

The backend migration and most Qt parity work are complete.

- Phases 0 through 8 in the migration plan are effectively complete on `dev/GUI3`
- The PySide6 shell now includes TV, movies, queue, history, settings, detail surfaces, poster loading, queue badges, toasts, and the three-panel roster/preview/detail workflow
- The tkinter shell remains the default launch path while a few operational/default-switch blockers are still being closed

The most accurate implementation notes live in:

- [docs/gui3-pyside6-migration-plan revised.md](docs/gui3-pyside6-migration-plan%20revised.md)
- [docs/gui3-pyside6-ui-design.md](docs/gui3-pyside6-ui-design.md)

---

## Quick Start

### Install

Create and activate a virtual environment, then install the project.

For the Qt shell, install the `qt` extra:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[qt]"
```

If you only want the current default tkinter shell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
```

### Launch

```powershell
.\.venv\Scripts\python.exe -m plex_renamer
.\.venv\Scripts\python.exe -m plex_renamer --qt
```

### First Run

1. Open `Settings`
2. Enter a TMDB API key
3. Start with either a TV root folder or a movie root folder

API keys are stored via OS keyring when available. If `keyring` is unavailable, the app falls back to local app-data storage.

---

## What It Does

### TV Workflows

- Single-show TV scanning
- Batch TV library discovery from a root folder
- Season and episode parsing across common release naming styles
- Specials / Season 0 handling
- Alternate-match review flows for low-confidence results
- Completeness reporting against TMDB episode data
- Plex-style rename plans for files and show folders

### Movie Workflows

- Bulk movie folder scanning
- Automatic filtering of likely TV episodes mixed into movie folders
- Confidence-based TMDB matching with manual re-match support
- Plex-ready detection for already-correct files/folders
- Queue-driven rename execution through the shared job pipeline

### Shared Qt Workflow

The PySide6 shell uses a consistent three-panel layout:

- left: roster grouped by queue/review/readiness state
- center: preview of rename operations
- right: metadata and selection details

That same model is used for:

- single-show TV
- batch TV
- movie folder scans

### Queue, History, and Undo

- Persistent queue and history stored in SQLite
- Controller-backed queue execution and revert flows
- Queue and history detail panels with cached poster reuse
- Undo/revert data recorded per completed job

---

## Shells

### tkinter Shell

- Still the default launch target
- Uses the shared controllers/services introduced during the migration
- Remains the safer operational path while the final Qt default-switch blockers are closed

### PySide6 Shell (`--qt`)

- Main shell in active development on `dev/GUI3`
- Includes tabs for TV, Movies, Queue, History, and Settings
- Uses the controller layer rather than duplicating orchestration logic in widgets
- Has received recent stabilization work for:
  - transient popup flicker on Windows
  - row/widget styling churn
  - poster request deduplication
  - bounded detail metadata caching
  - thread-safe async settings callbacks

---

## Configuration and Debugging

### Logging

You can override the startup log level with:

```powershell
$env:PLEX_RENAMER_LOG_LEVEL="DEBUG"
```

Supported practical values are `INFO` and `DEBUG`.

### Qt Transient Window Diagnostics

There is a targeted diagnostic flag for transient popup debugging in the Qt shell:

```powershell
$env:PLEX_RENAMER_DEBUG_TRANSIENT_WINDOWS="1"
.\.venv\Scripts\python.exe -m plex_renamer --qt
```

That flag is intended only for debugging popup/window issues.

---

## Testing

Install dev dependencies if needed:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,qt]"
```

Run the full test suite:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Run the Qt smoke suite only:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_gui_qt_smoke.py
```

---

## Architecture

The project is intentionally split into three layers.

### Core Domain Layer

Toolkit-independent logic for parsing, TMDB access, scanning, rename planning, and job persistence.

- `parsing.py`
- `tmdb.py`
- `engine.py`
- `job_store.py`
- `job_executor.py`
- `keys.py`

### Application Layer

UI-neutral controllers, models, and services used by both shells.

- `app/controllers/media_controller.py`
- `app/controllers/queue_controller.py`
- `app/models/`
- `app/services/cache_service.py`
- `app/services/command_gating_service.py`
- `app/services/refresh_policy_service.py`
- `app/services/settings_service.py`
- discovery services for TV and movies

### GUI Layers

- `gui/`: tkinter shell
- `gui_qt/`: PySide6 shell

Both consume the same backend services and controllers.

---

## Repository Layout

```text
plex_renamer/
├── __main__.py
├── constants.py
├── engine.py
├── job_executor.py
├── job_store.py
├── keys.py
├── parsing.py
├── tmdb.py
├── app/
│   ├── controllers/
│   ├── models/
│   └── services/
├── gui/
└── gui_qt/
    ├── app.py
    ├── main_window.py
    ├── resources/
    └── widgets/
tests/
docs/
```

---

## Near-Term Focus

The migration plan’s current recommended follow-up work is now beyond the Phase 8 stabilization pass.

The next likely areas are:

- remaining operational/default-switch blockers for the Qt shell
- queue/history polish and trust-gap cleanup
- deciding when `--qt` becomes the default launch path

For the detailed running status, use the migration plan in `docs/` rather than this README.