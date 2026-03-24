# Plex Renamer

A desktop application that automatically renames and reorganizes media files into [Plex-compatible naming conventions](https://support.plex.tv/articles/naming-and-organizing-your-movie-media-files/) using [TMDB](https://www.themoviedb.org/) as the source of truth.

Built with Python and tkinter. Designed around a unified three-panel workflow that handles single-show TV scans, batch TV library scans, and movie folder scans from the same core preview/detail UI.

![Python](https://img.shields.io/badge/python-3.12+-blue)
![TMDB](https://img.shields.io/badge/metadata-TMDB-01d277)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)

---

## Current Capabilities

### TV Series (Single Show)

Point the app at a TV show folder and it handles the rest.

Single-show TV uses the same left-library/preview/detail layout as batch TV, treating one show as a roster of one instead of maintaining a separate UI mode.

<img width="3504" height="1842" alt="tvseries1" src="https://github.com/user-attachments/assets/6357b2d4-68e5-4058-a1b2-39edd12c234b" />


**Automatic TMDB Matching**
- Cleans release-group folder names to extract the show title — strips resolution tags, codec info, source labels, release group names, and other noise while preserving dotted acronyms like `S.H.I.E.L.D.`
- Searches TMDB with progressive query trimming (if the full cleaned name returns no results, trims one word at a time from the end)
- Auto-accepts high-confidence matches; prompts the user with a selection dialog when the match is ambiguous or when multiple results score similarly
- Manual search fallback if automatic matching fails entirely

**Season & Episode Detection**
- Detects season folders in many formats: `Season 02`, `S02`, `Staffel 3`, `Saison 3`, `Temporada`, `Stagione`, bare number folders (`02`), and more
- Extracts episode numbers from multiple naming conventions:
  - `S01E01` with multi-episode support (`S01E01-E02`, `S01E01E02`)
  - Dash-delimited: `Show - 05 - Episode Title`
  - Bare numbers with year/resolution exclusion to avoid false positives
- International season folder naming (German, French, Spanish, Italian)

**Specials & Extras Handling**
- Recognizes Season 0 / Specials folders and maps files to TMDB Season 0 episodes
- Fuzzy title matching against TMDB special episode names — catches files like `Gag Reel.mkv` or `Making of the Pilot.mkv` that don't have episode numbers
- Scans nested extras folders inside regular seasons (e.g. `Season 02/Featurettes/`) and matches them against TMDB specials
- Unmatched extras are routed to an `Unmatched/<original_folder>/` directory instead of being silently dropped
- Recognizes extras folders by name: Specials, Extras, Bonus, Featurettes, Behind the Scenes, Deleted Scenes, Shorts, OVA, OAD, ONA, Special Features

**Season Structure Mismatch Detection**
- Compares user folder structure against TMDB's season structure
- Detects when user folders don't align with TMDB (e.g. a single-season folder containing episodes that TMDB splits across multiple seasons)
- Offers automatic consolidated remapping: assigns files in absolute order to the correct TMDB seasons, builds new season folders, and moves files accordingly

**Completeness Tracking**
- Compares matched episodes against TMDB's full episode list per season
- Per-season progress bars with matched/expected counts and percentages
- Collapsible missing episode lists in the detail panel
- Overall series completion percentage
- Separate tracking for specials (Season 0) vs regular seasons
- Rename button changes to green "Complete" style when the series is fully matched

**Plex-Formatted Output**

<img width="3522" height="1872" alt="tvseries2" src="https://github.com/user-attachments/assets/a1f5c3de-b5d5-45c8-9476-0573911bb8c1" />

- Renames files to: `Show Name (Year) - S01E01 - Episode Title.ext`
- Multi-episode files: `Show Name (Year) - S01E01-E02 - Title 1-Title 2.ext`
- Normalizes season folder names to `Season 01` format
- Renames the root show folder to match Plex/TMDB naming
- Sanitizes filenames for cross-platform compatibility (strips illegal characters, replaces colons)

<img width="3510" height="1866" alt="tvseries3" src="https://github.com/user-attachments/assets/27291f01-8aca-443e-8d1e-34baa673d901" />
  
---

### Movies (Folder Scan)

Point the app at a movie folder for bulk processing through the same shared three-panel layout used elsewhere in the app.

Movie scans now use the unified roster flow as well: the left panel shows the current movie scan as a roster entry, the center panel shows the proposed file operations, and the right panel shows metadata for the selected item.

<img width="3534" height="1905" alt="batchmovie1" src="https://github.com/user-attachments/assets/9defe4d5-a43a-4ac5-8543-c0ade6000c54" />

<img width="3513" height="1821" alt="batchmovie2" src="https://github.com/user-attachments/assets/7e49de99-01bd-44bc-9d28-fd27c59fd9da" />

**Smart Filtering**
- Automatically identifies and skips TV episodes mixed into movie folders using multiple heuristic signals:
  - `S01E01` / `1x05` / `Episode 5` filename patterns
  - Anime fansub naming: `[Group] Title - 05`
  - Parent folder named `Season XX` or equivalent
  - Parent folder is an extras/featurettes folder
  - Sequential batch detection: 3+ files in the same folder with the same name prefix and sequential dash-delimited numbers are flagged as likely TV content
- Skipped files are tagged as `OTHER` (not `MOVIE`) so they're visually distinct in the preview

**Parallel TMDB Search**
- Searches movie files concurrently using a thread pool (default 8 workers)
- Rate-limited to stay within TMDB's API limits
- Progress bar shows search completion in real-time

**Confidence-Based Auto-Matching**
- Each TMDB result is scored using title similarity (longest common subsequence) weighted at 70% plus year match weighted at 30%, with a bonus for exact normalized title matches
- Results above the confidence threshold are auto-accepted
- Low-confidence matches are flagged as `NEEDS REVIEW` with the best guess pre-filled — user can verify or re-match
- Files with no TMDB results are flagged for manual search

**Re-Matching**
- Any movie can be re-matched from the detail panel with a single click
- Opens a search dialog pre-populated with cached results
- Supports manual search queries to find the correct match
- Updates the preview immediately after re-matching

**Batch Output**
- Each movie is placed in its own `Title (Year)/` folder under the batch root
- Files already in the correct location are detected and no unnecessary move is flagged
- Files already properly named are filtered out of the preview with a count shown in the status bar

---

### Preview & Interaction

**Unified Three-Panel Workflow**
- The left panel is always the media roster for the active TV or Movie session
- Single-show TV is represented as a one-item roster entry
- Movie folder scans are represented as a one-item roster entry for the active folder scan
- Batch TV keeps grouped roster headers such as `matched`, `needs review`, `duplicates`, and `queued`

**Card-Based Preview**
- Every file gets a preview card showing the original filename and the proposed new name with target folder
- Cards are color-coded by status: green for ready, amber for needs review, red for conflicts, muted for skipped
- Badge pills indicate file type and status: `MOVIE`, `SPECIAL`, `MULTI-PART`, `NEEDS REVIEW`, `UNMATCHED`, `OTHER`
- Colored accent bars on the left edge of each card for quick visual scanning
- Checkbox per file — only checked files are included in the rename operation
- Season header bars (TV mode) with per-season checkboxes to select/deselect entire seasons at once
- Collapsible seasons — click a season header to hide/show its episodes
- Search/filter bar to find specific files by name
- Select All toggle
- Selected/total tally display

**Poster Thumbnails**
- Movie preview mode shows TMDB poster thumbnails on preview cards when multiple movie files are present
- Placeholder poster for files without a TMDB poster
- The left roster panel caches poster thumbnails for both TV and Movie sessions
- Season poster thumbnails in result view headers

**Detail Panel**
- Right-side panel shows rich metadata for the selected item
- TV episodes: episode title, rating (star display), runtime, air date, synopsis, directors, writers, guest stars (top 4 with character names)
- Movies: title, tagline, rating, runtime, release date, synopsis, genres, production companies
- Episode/movie still images scaled to panel width
- Rename preview card showing `FROM → TO` with folder move indication
- Status indicator with color coding
- Re-match button (movies only) for correcting auto-matches
- Show-level info beside poster: overall rating, genres, network, status, season/episode counts, creators

---

### Rename Execution

**Safe Rename Operations**
- Confirmation dialog showing file count, move count, and undo availability
- Creates target directories as needed
- Cross-folder moves using `shutil.move` for cross-device compatibility
- Same-folder renames using `Path.rename` for efficiency
- Normalizes season folder names to `Season XX` format after rename
- Optionally renames the root show folder to match TMDB naming
- Cleans up empty source directories after moves
- Skips conflicting files and continues processing the rest (does not abort the entire batch)

**Result View**
- Completion badge with stats (files renamed, moved, folders renamed, empty folders removed)
- Error section for any failed operations
- Folder changes section showing directory renames and removals
- Collapsible per-season file lists showing old → new for every renamed file
- Clickable result cards that populate the detail panel with metadata
- Undo and Scan Again buttons

---

### Undo System

- Full undo of the most recent rename batch via `Ctrl+Z` or the Undo button
- Atomic JSON log stored at `~/.plex_renamer/rename_log.json`
- Write-safe: uses temp file + rename to prevent corruption on crash
- Reverts file renames, directory renames, and recreates removed directories
- Properly handles cascading directory renames using `Path.relative_to()` for safe path rewriting
- Cleans up directories created during the original rename if they're empty after undo

---

### TMDB API Client

**Connection Management**
- HTTP connection pooling via `requests.Session` (reuses TCP+TLS connections across requests)
- Token-bucket rate limiter at 35 requests/second (below TMDB's 40/s limit), thread-safe
- Automatic retry with exponential backoff for rate limits (429) and server errors (5xx) — 2 retries with 1s/3s delays
- Typed exception hierarchy: `TMDBError` → `TMDBNetworkError`, `TMDBRateLimitError`, `TMDBAPIError`
- Safe wrapper (`_get_safe`) for non-critical paths that returns `None` on failure instead of raising

**Caching**
- In-memory caching for show details, season data, season maps, and movie details — eliminates redundant API calls across scan/mismatch/rescan cycles
- LRU-bounded image cache (200 entries) prevents unbounded memory growth during batch operations
- Cache clearing when switching between shows

**Batch Operations**
- `search_movies_batch()`: parallel movie search across a thread pool
- `search_tv_batch()`: parallel TV show search across a thread pool
- Progressive query trimming (`search_with_fallback`): if a search returns no results, trims words from the end and retries

**Image Handling**
- Poster/still fetching with priority chain: episode still → season poster → show/movie poster
- Automatic scaling to target width
- Rate-limited image downloads

---

### Filename Parsing Engine

**Title Extraction**
- Strips release-group noise from folder/filenames: resolution (480p–2160p, 4K, UHD), source (BluRay, WEB-DL, HDTV, streaming service tags), video codec (x264, x265, HEVC, AV1), audio (AAC, DTS-HD MA, TrueHD, Atmos), release tags (REMUX, REPACK, PROPER, HDR, DoVi), and more
- Protects dotted acronyms (e.g. `S.H.I.E.L.D.`) from being split during dot-to-space conversion
- Strips bracketed tags `[group]` and parenthesized tags `(tags)` while preserving parenthesized years `(2023)`
- Removes trailing release group names (e.g. `-iAHD`)
- Year extraction from filenames with range validation (1920–2099)

**Fuzzy Matching**
- Unified normalization: strips years, punctuation, articles (`the`, `a`, `an`), and extra whitespace
- Title similarity scoring using longest common subsequence (Dice-like coefficient)
- Specials-specific normalization that reduces to pure alphanumeric for substring matching

---

### GUI & UX

- Dark theme with a gold accent color palette
- DPI-aware on Windows (High DPI scaling support)
- Custom-drawn checkbox images (checked/unchecked with rounded rectangles and checkmark)
- Responsive layout with resizable panes
- Canvas-based rendering for the preview list (handles dynamic card heights, text wrapping, badge pills)
- Debounced completeness recalculation on checkbox changes (50ms delay)
- Debounced canvas redraw on window resize (100ms delay)
- Mousewheel scrolling with enter/leave routing between preview and detail canvases
- Keyboard shortcuts: `Ctrl+Z` for undo, `F5` for refresh
- Progress bar in the status bar for async operations
- Threaded scanning for batch movie mode (keeps UI responsive)

---

### Security & Storage

- API keys stored securely via the OS keyring (not in plaintext config files)
- API key management dialog with masked input
- Undo log written atomically to prevent corruption

---

## Architecture

```
plex_renamer/
├── __main__.py          # Entry point
├── constants.py         # Shared constants, regex patterns, MediaType enum
├── parsing.py           # Pure filename parsing, name building, normalization
├── tmdb.py              # TMDB API client with rate limiting and caching
├── engine.py            # TVScanner, MovieScanner, rename execution, undo
├── keys.py              # OS keyring API key storage
├── undo_log.py          # Atomic JSON undo log
├── styles.py            # Dark theme, ttk styles, color palette
└── gui/
    ├── app.py           # Main window, state management, orchestration
    ├── preview_canvas.py # Card rendering, checkboxes, search, completeness
    ├── detail_panel.py  # Right-side metadata panel
    ├── result_views.py  # Post-rename result display
    ├── dialogs.py       # Media picker, API key manager, mismatch prompt
    └── helpers.py       # Platform init, scaling, mousewheel, canvas buttons
```

The backend (`parsing.py`, `tmdb.py`, `engine.py`) has zero GUI dependencies and operates on plain data structures, making it testable and reusable independently of the frontend.

---

## Roadmap

- **Queue-First Rename Workflow**: Continue expanding the queue/history flow so more rename operations run through the persistent job pipeline by default
- **Full Library Automation**: Scan an entire Plex library (movies + TV) and automatically reformat everything with minimal manual intervention
