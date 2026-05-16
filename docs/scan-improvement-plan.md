# Scan Improvement Plan

## Purpose

This document turns the nested batch-TV scan discussion into a concrete implementation plan.

## March 29 2026 status update

The core discovery hardening work described in this plan is now implemented on `dev/GUI3`.

Completed from this plan:

1. Recursive TV-library discovery now lives below the GUI layer in `plex_renamer/app/services/tv_library_discovery_service.py`.
2. Batch TV discovery no longer stops at one directory level and can discover show roots under container folders conservatively.
3. Release-style show folders whose names contain tokens like `S01` are no longer misclassified as season folders when they contain real nested season directories.
4. Duplicate handling and controller flows now preserve enough context for the Qt and tkinter shells to present nested discoveries consistently.

Recent validation tied to this work:

1. `tests/test_scan_improvements.py`
2. `tests/test_media_controller.py`
3. `tests/test_haikyuu_matching.py`
4. `tests/test_jojo_matching.py`

Follow-up hardening since the original rollout:

1. fansub multi-episode ranges like `[GHOST] Inuyasha - 166-167 [...]` are now treated as TV episodes instead of movie candidates
2. flat-folder absolute episode mapping now skips TMDB Season 0 specials when distributing regular episodes across main seasons
3. movie jobs for files that live directly in the selected library root now create `Title (Year)` subfolders inside that root instead of renaming the root itself

What remains useful in this document:

1. The discovery constraints and traversal rules still describe the intended long-term behavior.
2. The remaining task list should now be read as follow-up cleanup and audit guidance, not as a statement that the discovery service is still missing.

The immediate problem is that batch TV mode only discovers show folders one level deep, so it misses valid TV show roots inside organizational subdirectories. The fix needs to:

1. support nested show discovery in batch TV mode
2. avoid mistaking season folders or umbrella folders for separate shows
3. preserve duplicate detection behavior when multiple copies of the same show exist in the same nested area
4. keep rename and undo behavior safe for nested folder layouts
5. live below the GUI layer so it survives the PySide6 transition without rework

## Goals

1. Discover TV show roots recursively under container folders in batch TV mode.
2. Keep show-root detection conservative and based on direct-child evidence only.
3. Preserve existing TMDB match and duplicate handling while making duplicate tie-breaking deterministic.
4. Carry enough path metadata forward for both the current tkinter shell and the future PySide6 shell.
5. Bound undo cleanup so nested organizational folders are restored safely.

## Non-Goals

1. Do not redesign the queue model in this pass.
2. Do not change movie batch scan behavior in this pass.
3. Do not make duplicate copies of the same TMDB show independently queueable in this pass.
4. Do not move roster rendering or batch orchestration into PySide6 yet.

## Current Problem Summary

Current batch TV discovery in `BatchTVOrchestrator.discover_shows()` only inspects direct children of the selected library root. That means folders like these are missed:

```text
TV Root/
    Anime/
        Naruto/
            Season 01/
    Sci-Fi/
        Battlestar Galactica (2004)/
            Season 01/
```

The existing logic is correct to avoid treating season folders as separate shows, but it is too shallow to support nested organizational containers.

## Design Constraints

1. A folder is a show root only when its direct children provide evidence.
2. Descendant evidence alone must never classify the current folder as a show.
3. Discovery must stop descending once a folder is confirmed as a show root.
4. Directory traversal must be symlink-safe and deterministic.
5. Discovery must be efficient enough for NAS and network-mounted libraries.
6. GUI code must consume discovery results, not implement traversal rules.

## Proposed Architecture

## New Service

Add a new toolkit-neutral service:

- `plex_renamer/app/services/tv_library_discovery_service.py`

This service will own recursive TV-library discovery and directory classification.

## Suggested Model Additions

Add a small discovery result model under `plex_renamer/app/models/state_models.py` or a new dedicated model file if the existing state model file becomes crowded.

Suggested fields:

- `folder: Path`
- `relative_folder: str`
- `parent_relative_folder: str | None`
- `depth: int`
- `discovery_reason: str`
- `has_direct_season_subdirs: bool`
- `direct_episode_file_count: int`
- `direct_video_file_count: int`
- `discovered_via_symlink: bool`

The key point is that the discovery layer should emit enough evidence for later duplicate tie-breaking and UI display without forcing downstream code to rescan the filesystem.

## Directory Roles

Each visited directory should be classified into one of these roles:

1. `show_root`
2. `container`
3. `season_folder`
4. `ignored_system`
5. `non_tv_leaf`

## Classification Rules

### `season_folder`

Classify as `season_folder` and stop descending when the directory itself looks like a season folder.

Examples:

- `Season 01`
- `S01`
- `Staffel 1`

### `show_root`

Classify as `show_root` when direct-child evidence indicates the root of a single show.

Valid evidence:

1. at least one direct child season folder
2. direct video files with enough TV-episode evidence
3. direct extras or specials structure consistent with one show, if needed by the existing scanner rules

Important rule:

Only direct children count. A folder is not a `show_root` because a grandchild contains `Season 01`.

### `container`

Classify as `container` when:

1. the folder is not a season folder
2. the folder is not a show root
3. the folder has child directories worth exploring

Examples:

- `Anime`
- `Sci-Fi`
- `Documentaries/BBC`

### `ignored_system`

Skip known junk or system folders early.

Initial ignore list:

- `@eaDir`
- `.DS_Store`
- `.metadata`
- `.plexmatch`
- `$RECYCLE.BIN`
- `System Volume Information`
- `lost+found`
- `.debris`
- `#recycle`

Existing media-specific exclusions like `extras` and `featurettes` should be evaluated separately from generic junk folders.

### `non_tv_leaf`

Use this for folders that do not appear to be show roots and do not justify further descent.

Examples:

- likely movie folders
- empty folders
- folders containing only non-video files

## Traversal Rules

The discovery walk should be implemented as an explicit iterator using `Path.iterdir()` or `os.scandir()` semantics, not `os.walk()`.

Rules:

1. inspect each directory once
2. classify using direct children only
3. emit a candidate when the role is `show_root`
4. recurse only when the role is `container`
5. never recurse into `season_folder`
6. never recurse below a confirmed `show_root`

This keeps discovery conservative and prevents a single show hierarchy from being split into fake child shows.

## Symlink Policy

Directory symlinks should be followed, but recursion must be loop-safe.

Rules:

1. resolve each visited directory to a canonical path
2. track a `visited_paths` set of canonical normalized paths
3. skip directories whose canonical path has already been visited
4. record whether a candidate was discovered through a symlink path for diagnostics only

This prevents infinite recursion in Sonarr or manually linked media trees.

## Duplicate Detection Rules

Duplicate grouping should remain keyed by TMDB ID, but primary-selection tie-breaking should become deterministic.

Tie-break order:

1. higher TMDB confidence
2. shallower relative path depth
3. stronger direct evidence of a show root:
   - direct season subdirectories beat loose episode-file evidence
4. lexically smaller normalized relative path using POSIX separators

## Duplicate Metadata

Current duplicate labeling stores only a display-name string. That is ambiguous when multiple copies of the same show live in one nested area.

Extend `ScanState` to retain path-aware duplicate context.

Suggested additions:

- `relative_folder: str = ""`
- `parent_relative_folder: str | None = None`
- `duplicate_of_relative_folder: str | None = None`

Keep `duplicate_of` for the human-readable label, but preserve the primary candidate path for deterministic UI and future controller logic.

## Rename and Undo Requirements

Nested show roots should continue to use the existing relative-path job model.

Required checks:

1. `build_rename_job_from_state()` must continue to store `source_folder` relative to `library_root`
2. rename ops must remain relative to `library_root`
3. nested show folder renames must not break pending job path propagation

### Revert Safety

The upward empty-directory cleanup in `revert_job()` must stop at `Path(job.library_root)`.

This prevents undo from removing higher-level user organization folders above the selected batch root.

## Concrete Task List

## Phase 1: Discovery Service

### Task 1. Add a TV library discovery service

Files:

- add `plex_renamer/app/services/tv_library_discovery_service.py`

Work:

1. implement directory role classification
2. implement recursive discovery through container folders only
3. implement ignore-list filtering
4. implement symlink-safe visited-path tracking
5. emit structured discovery results with evidence flags

Acceptance criteria:

1. nested show roots are discovered under container folders
2. season folders are never emitted as show roots
3. container folders are never emitted as show roots based only on descendants
4. symlink loops do not recurse infinitely

### Task 2. Add discovery result model

Files:

- update `plex_renamer/app/models/state_models.py`
  or add a new discovery model file under `plex_renamer/app/models/`

Work:

1. add a typed model for discovery results
2. include relative path, depth, parent path, and classification evidence

Acceptance criteria:

1. the model is GUI-neutral
2. the model carries enough information for duplicate tie-breaking and roster display

## Phase 2: Orchestrator Integration

### Task 3. Refactor batch TV discovery to use the service

Files:

- update `plex_renamer/engine.py`

Work:

1. inject or construct the discovery service in `BatchTVOrchestrator`
2. replace direct-child root iteration in `discover_shows()` with discovery results
3. keep TMDB search and ScanState creation inside the orchestrator

Acceptance criteria:

1. `discover_shows()` behaves the same for flat TV libraries
2. `discover_shows()` finds nested shows under containers
3. movie-like subfolders continue to be ignored in TV mode

### Task 4. Extend `ScanState` with nested-path metadata

Files:

- update `plex_renamer/engine.py`

Work:

1. add `relative_folder`
2. add `parent_relative_folder`
3. add `duplicate_of_relative_folder`
4. populate these fields from discovery results during `discover_shows()`

Acceptance criteria:

1. every batch TV state knows its path relative to the selected library root
2. duplicate states retain the primary candidate path

## Phase 3: Duplicate Handling

### Task 5. Make duplicate tie-breaking deterministic

Files:

- update `plex_renamer/engine.py`

Work:

1. replace confidence-only duplicate winner selection with a deterministic comparator
2. use discovery evidence and normalized relative path as tie-breakers
3. preserve current grouped duplicate behavior

Acceptance criteria:

1. two copies of the same show in the same nested folder always resolve the same way across repeated scans
2. duplicate grouping remains keyed by TMDB ID
3. only the primary duplicate candidate remains checked by default

## Phase 4: Undo Safety

### Task 6. Bound revert cleanup at the library root

Files:

- update `plex_renamer/job_executor.py`

Work:

1. stop upward empty-directory cleanup in `revert_job()` at `Path(job.library_root)`
2. preserve current file and directory revert behavior below that boundary

Acceptance criteria:

1. undo restores nested show folders correctly
2. undo does not remove user organizational folders above the selected library root

## Phase 5: UI Surface

### Task 7. Expose relative path context in the current roster

Files:

- update `plex_renamer/gui/library_panel.py`

Work:

1. show the relative folder or parent container path in show cards where useful
2. show duplicate primary-path context when a duplicate is marked
3. keep this presentation thin and derived from `ScanState`

Acceptance criteria:

1. nested shows are distinguishable in the roster
2. duplicate copies of the same show are visually unambiguous

This is intentionally the last phase because it should consume data produced by the underlying discovery and duplicate logic rather than drive it.

## Validation Matrix

The implementation is not complete until these cases pass.

### March 29 2026 follow-up

The original nested-discovery rollout exposed one more real-world edge case during Qt batch-TV dogfooding:

1. A release-style show folder whose own name contains `S01` can be mistaken for a bare season folder even when it actually contains a child `Season 1` directory.
2. This caused batch TV mode to skip valid show roots such as the Akiba Maid War pattern while direct single-folder scans still worked.
3. Discovery has now been tightened so season-like child folders count as season evidence only when their contents actually behave like season folders.
4. A matching regression test now covers this shape directly, alongside a TV review-suggestion test that preserves runner-up alternates for low-confidence matches.

### Discovery

1. flat TV library with direct child shows
2. TV library nested one level under containers
3. TV library nested multiple levels under containers
4. mixed root containing both movies and TV subfolders
5. empty folders and junk folders do not become candidates
6. season folders at the root do not become show candidates

### Duplicate Handling

1. two copies of the same show in the same nested container
2. two copies of the same show in different nested containers
3. one confident match and one low-confidence duplicate
4. identical-confidence duplicate candidates resolve deterministically

### Rename and Undo

1. rename a nested show root and confirm relative-path jobs are built correctly
2. undo a nested rename and confirm the original nested path is restored
3. undo when the nested parent becomes empty and confirm cleanup stops at the library root
4. confirm pending job path propagation still works after nested folder rename

### Symlink Safety

1. follow a directory symlink to a valid show root
2. avoid infinite recursion on circular symlink references

## Movie Batch Scanning Extension

### Motivation

The TV scan improvement phases introduced architectural patterns — recursive discovery, directory classification, structured candidates, deterministic duplicate handling — that solve equivalent problems in movie batch scanning. Movie libraries exhibit the same nested-container layouts as TV libraries:

```text
Movies/
    Action/
        Die Hard (1988)/
            Die Hard (1988).mkv
    Sci-Fi/
        Blade Runner (1982)/
            Blade Runner (1982).mkv
    Unsorted/
        movie.file.2023.1080p.mkv
```

The current `MovieScanner` uses `rglob("*")` to collect all video files flat, with no folder-level classification, no container awareness, and no TMDB ID-based duplicate detection. This extension brings movie batch scanning up to architectural parity with TV batch scanning using the same service-layer patterns.

### Movie Extension Goals

1. Discover movie roots recursively under container folders in batch movie mode.
2. Keep movie-root detection conservative and based on direct-child evidence only.
3. Add TMDB ID-based duplicate detection for movies, with deterministic tie-breaking.
4. Carry enough path metadata forward for both the current tkinter shell and the future PySide6 shell.
5. Live below the GUI layer so it survives the PySide6 transition without rework.

### Movie Extension Non-Goals

1. Do not redesign the queue model in this pass.
2. Do not change TV batch scan behavior in this pass.
3. Do not move roster rendering or batch orchestration into PySide6 yet.
4. Do not add movie collection or franchise grouping in this pass.

### Movie Directory Roles

Each visited directory should be classified into one of these roles:

1. `movie_root` — folder containing video files that represent a single movie (with optional companions)
2. `container` — organizational folder with subdirectories but no direct movie evidence
3. `multi_movie_folder` — folder with 3+ video files that are not sequential TV episodes (loose movies without individual folders)
4. `extras_folder` — featurettes, behind-the-scenes, deleted scenes, etc.
5. `ignored_system` — same junk list as TV discovery (reuse `_IGNORED_SYSTEM_NAMES`)
6. `non_movie_leaf` — folders that do not contain movie content (empty, non-video, or TV content)

### Movie Classification Rules

#### `ignored_system`

Same rules as TV discovery. Reuse the shared ignored-names set.

#### `extras_folder`

Classify as `extras_folder` and stop descending when the folder name matches the extras pattern.

Examples: `Featurettes`, `Extras`, `Behind The Scenes`, `Deleted Scenes`

#### `movie_root`

Classify as `movie_root` when direct-child evidence indicates a single movie folder.

Valid evidence:

1. folder name matches the "Title (Year)" pattern commonly used by Plex, Radarr, and manual organization
2. 1-2 direct video files (the movie, possibly with a different edition or quality)
3. no direct season subdirectories (rules out TV show roots)
4. no direct TV episode evidence among the video files

Important rule: Only direct children count. A folder is not a `movie_root` because a grandchild contains a video file.

#### `multi_movie_folder`

Classify as `multi_movie_folder` when:

1. the folder has 3+ direct video files
2. the files are not sequential TV episodes (pass through the existing sequential-batch filter)
3. the folder has no direct season subdirectories

This covers the common "dump folder" pattern where movies are collected without individual subfolders.

#### `container`

Classify as `container` when:

1. the folder is not a movie root, multi-movie folder, or extras folder
2. the folder has child directories worth exploring
3. the folder has no or very few direct video files (0-0 — containers should not have movies themselves)

Examples: `Action`, `Sci-Fi`, `2023`, `Criterion Collection`

#### `non_movie_leaf`

Use this for folders that do not contain movie evidence and do not justify further descent.

Examples:

- folders containing only TV episode files
- empty folders
- folders containing only non-video files (subtitles without video, NFO-only, etc.)

### Movie Traversal Rules

Same structural rules as TV discovery, adapted for movie roles:

1. inspect each directory once
2. classify using direct children only
3. emit a candidate when the role is `movie_root` or `multi_movie_folder`
4. recurse only when the role is `container`
5. never recurse below a confirmed `movie_root`
6. never recurse into `extras_folder`

### Movie Symlink Policy

Same as TV discovery. Reuse the canonical-path visited set and loop-safe traversal.

### Movie Duplicate Detection Rules

Duplicate grouping should be keyed by TMDB movie ID, using the same deterministic tie-breaking pattern as TV.

Tie-break order:

1. higher TMDB confidence
2. shallower relative path depth
3. stronger direct evidence of a movie root:
   - "Title (Year)" folder name match beats loose files in a multi-movie folder
4. lexically smaller normalized relative path using POSIX separators

### Movie Discovery Result Model

Add a `MovieDiscoveryCandidate` model under `plex_renamer/app/models/state_models.py`.

Suggested fields:

- `folder: Path`
- `relative_folder: str`
- `parent_relative_folder: str | None`
- `depth: int`
- `discovery_reason: str`
- `direct_video_file_count: int`
- `has_title_year_folder_name: bool`
- `discovered_via_symlink: bool`

### Concrete Task List — Movie Extension

#### Phase M1: Movie Discovery Service

##### Task M1. Add a movie library discovery service

Files:

- add `plex_renamer/app/services/movie_library_discovery_service.py`

Work:

1. implement directory role classification for movie folders
2. implement recursive discovery through container folders only
3. reuse ignore-list filtering from TV discovery
4. reuse symlink-safe visited-path tracking
5. emit structured discovery results with evidence flags

Acceptance criteria:

1. nested movie roots are discovered under container folders
2. extras folders are never emitted as movie roots
3. container folders are never emitted as movie roots based only on descendants
4. multi-movie folders are emitted with their direct video file count
5. TV content is not misclassified as movie content
6. symlink loops do not recurse infinitely

##### Task M2. Add movie discovery result model

Files:

- update `plex_renamer/app/models/state_models.py`

Work:

1. add `MovieDirectoryRole` enum
2. add `MovieDiscoveryCandidate` dataclass

Acceptance criteria:

1. the model is GUI-neutral
2. the model carries enough information for duplicate tie-breaking and roster display

#### Phase M2: Orchestrator Integration

##### Task M3. Add BatchMovieOrchestrator

Files:

- update `plex_renamer/engine.py`

Work:

1. create `BatchMovieOrchestrator` class parallel to `BatchTVOrchestrator`
2. implement two-phase workflow: discover movie roots → parallel TMDB match
3. create `ScanState` objects from discovery results with metadata populated
4. replace the current flat `MovieScanner._get_video_files()` + GUI orchestration pattern
5. handle `multi_movie_folder` candidates by creating per-file ScanState entries

Acceptance criteria:

1. flat movie libraries behave the same as today
2. nested movie libraries discover movies under containers
3. multi-movie folders produce one ScanState per video file
4. TV content in mixed roots is skipped

##### Task M4. Extend `ScanState` with movie discovery metadata

Files:

- update `plex_renamer/engine.py`

Work:

1. populate `relative_folder` for movies
2. populate `parent_relative_folder` for movies
3. populate `discovery_reason` for movies
4. populate `discovered_via_symlink` for movies

Acceptance criteria:

1. every batch movie state knows its path relative to the selected library root
2. movie states carry the same path metadata that TV states carry

#### Phase M3: Movie Duplicate Handling

##### Task M5. Add TMDB ID-based duplicate detection for movies

Files:

- update `plex_renamer/engine.py`

Work:

1. add duplicate labeling for movies keyed by TMDB movie ID
2. use deterministic tie-breaking with discovery evidence
3. mark secondary duplicates as non-checked by default

Acceptance criteria:

1. two copies of the same movie resolve deterministically across repeated scans
2. duplicate grouping is keyed by TMDB movie ID
3. only the primary duplicate candidate remains checked by default

#### Phase M4: UI Surface

##### Task M6. Expose movie discovery context in the current roster

Files:

- update `plex_renamer/gui/library_panel.py`

Work:

1. show relative folder path for nested movies
2. show duplicate primary-path context when a movie duplicate is marked
3. keep presentation derived from `ScanState`

Acceptance criteria:

1. nested movies are distinguishable in the roster
2. duplicate copies of the same movie are visually unambiguous

This is intentionally the last phase because it should consume data produced by the underlying discovery and duplicate logic.

### Movie Extension Validation Matrix

#### Discovery

1. flat movie library with direct child movie folders
2. movie library nested one level under genre containers
3. movie library nested multiple levels under containers
4. mixed root containing both TV and movie subfolders
5. multi-movie dump folder with loose files
6. empty folders and junk folders do not become candidates
7. extras folders at any level do not become candidates

#### Duplicate Handling

1. two copies of the same movie in the same nested container
2. two copies of the same movie in different nested containers
3. one confident match and one low-confidence duplicate
4. identical-confidence duplicate candidates resolve deterministically

#### Symlink Safety

1. follow a directory symlink to a valid movie root
2. avoid infinite recursion on circular symlink references

### Movie Extension Recommended Execution Order

Implement in this order:

1. movie discovery result model
2. movie discovery service
3. BatchMovieOrchestrator
4. `ScanState` movie metadata population
5. movie TMDB ID duplicate detection
6. roster display improvements

---

## Risks and Follow-Ups

### Known Risk

Current queue uniqueness is keyed by `job_kind + media_type + tmdb_id + library_root`.

That means multiple copies of the same TMDB show or movie within one library root still share one queue identity. This is acceptable if duplicate copies remain non-queueable except for the primary candidate.

If product requirements later change to allow queueing multiple copies independently, `source_folder` will need to be included in the queue uniqueness key.

### Follow-Up Opportunities

1. expose discovery evidence in the future PySide6 roster model for richer explanations
2. move the duplicate comparator into a dedicated helper or service if it grows beyond a small function
3. add targeted tests for network-share and symlink-heavy libraries
4. unify shared discovery infrastructure (ignored names, symlink tracking, traversal) into a base class or shared module if TV and movie services accumulate significant duplication

## Recommended Execution Order

### TV Phases (Goals 1-5 — Complete)

Implemented in this order:

1. ~~discovery service~~
2. ~~discovery result model~~
3. ~~orchestrator integration~~
4. ~~`ScanState` path metadata~~
5. ~~deterministic duplicate comparator~~
6. ~~revert cleanup boundary~~
7. roster display improvements (remaining — deferred to PySide6 roster)

### Movie Phases

Implement in this order:

1. ~~movie discovery result model~~
2. ~~movie discovery service~~
3. ~~BatchMovieOrchestrator~~
4. ~~`ScanState` movie metadata population~~
5. ~~movie TMDB ID duplicate detection~~
6. roster display improvements (remaining — deferred to PySide6 roster)

This keeps filesystem behavior, duplicate semantics, and undo safety stable before any presentation changes are made.
