# Settings Restyle And Output Destinations Design

Date: 2026-05-17

## Purpose

Prepare NameScraper for upcoming mkvmerge-based cleanup features by fixing two prerequisites first:

1. Make the Settings tab scalable enough for more configuration.
2. Replace inconsistent source-folder rename behavior with explicit TV and movie output destinations.

The goal is to make file actions predictable. Rename-only jobs move selected media and supported companion files into clean output folders. Original source folders and unmatched files stay where they are.

## Current Context

Relevant existing structure:

- `plex_renamer/gui_qt/widgets/settings_tab.py` owns the Settings tab shell.
- `plex_renamer/gui_qt/widgets/_settings_tab_sections.py` builds current settings sections.
- `plex_renamer/app/services/settings_service.py` persists JSON-backed settings.
- `plex_renamer/app/services/_settings_schema.py` defines settings defaults and validation.
- `plex_renamer/engine/_queue_bridge.py` converts preview items to queue jobs.
- `plex_renamer/app/controllers/_queue_submission_helpers.py` submits TV and movie jobs.
- `plex_renamer/job_executor.py` executes and reverts jobs.
- `plex_renamer/_job_execution_filesystem.py` contains lower-level filesystem helpers.

Current execution still has source-folder-coupled behavior, including folder renames, season directory normalization in source paths, and `Unmatched Files` cleanup for leftovers. That behavior conflicts with the desired output-folder workflow.

## Goals

- Restyle Settings around a category-sidebar layout.
- Add persistent, required output folders for TV Shows and Movies.
- Block scanning when the relevant output folder is not valid.
- Prevent scanning when the output folder is the same as, or nested under, the selected scan source.
- Move selected rename-only files into canonical folders under the configured output root.
- Leave all original directories intact, including empty source folders after files move out.
- Leave unmatched, unsupported, and unactionable files in their original locations.
- Remove empty app-created output directories during revert.
- Preserve a clean future path for mkvmerge strip/copy jobs.

## Non-Goals

- Do not implement mkvmerge integration in this change.
- Do not add a copy mode yet.
- Do not move unsupported sidecar files such as notes, samples, or NFO files unless they are already modeled as supported companion files.
- Do not create any `Unmatched Files` output folder.
- Do not delete or rename source folders.
- Do not redesign TV/movie scanning or matching behavior beyond output-folder gating.

## Chosen Approach

Use a first-class output-destination model.

Settings persist `tv_output_folder` and `movie_output_folder`. Scanning is blocked until the relevant destination exists and passes source/output relationship validation. Queue jobs explicitly carry enough information to resolve original source paths and final output paths without renaming the source folder.

This is preferred over executor-only remapping because the destination should be visible in preview, queue detail, history detail, and future mkvmerge workflows. It is also preferred over a full operation pipeline because copy/strip behavior should wait until mkvmerge requirements are finalized.

## Settings UX

Settings moves to the category-sidebar layout selected during brainstorming.

Initial categories:

- Destinations
- Display
- Matching
- MKV Cleanup, omitted until implemented or shown only as a disabled navigation category with no editable controls
- API Keys
- Data
- Advanced, hidden or retained only if needed

The Destinations category appears first and contains:

- TV Shows output folder
- Movies output folder

Each destination row shows:

- label
- saved path
- Browse button
- validation state
- short explanation of what the folder is used for

The Settings tab should only save an output root when the selected path exists and is a directory. If a previously saved path is later missing or not a directory, Settings shows it as invalid and scan gating treats it as unavailable.

The output root itself must exist ahead of time. The app creates show/movie folders and nested season folders inside that root during job execution.

## Scan Gating

TV scanning requires a valid TV output folder.

Movie scanning requires a valid Movie output folder.

Before discovery starts, the app validates the selected source folder against the relevant output root:

- source and output must not resolve to the same directory
- output must not be nested inside source

If validation fails, the app does not begin scanning. The workspace should show a setup-focused message or dialog that explains the blocked condition and points the user to Settings.

Output roots can be parents of scan sources. For example, scanning an unsorted staging folder into a separate media library folder is valid as long as the output folder is not the same as or inside the scanned folder.

## Job Model

The domain model should distinguish:

- source root: the selected input root used to resolve original files
- output root: the configured TV or movie output folder
- output media folder: the canonical show/movie subdirectory created below output root
- output nested folders: season folders or future nested structures created below output media folder

Implementation may preserve the existing `library_root` name internally as the source root for compatibility, but new behavior should add a clear output-root field rather than overloading `target_dir_relative` with source-relative destinations.

Rename operations should continue to store:

- original relative path from source root
- canonical new filename
- target directory relative to output root
- media type and companion file type
- selected state
- status
- season and episode metadata where relevant

Completed jobs store undo data as absolute old/new paths, plus created output directories, so revert does not depend on current settings values.

Legacy jobs without an output root use this compatibility behavior:

- existing completed history remains viewable and revertible through its stored undo data
- pending legacy jobs are blocked from execution with a clear "legacy job must be recreated" message
- new scans and queue submissions always create destination-aware jobs

## Execution Behavior

Rename-only jobs move selected video files and supported companion files from their original paths to output paths.

Execution creates missing output directories as needed:

- TV: `<tv_output_root>/<Show Name (Year)>/Season NN/...`
- Movie: `<movie_output_root>/<Movie Name (Year)>/...`

Execution must not:

- rename source folders
- delete source folders
- normalize source season folder names
- move leftovers into `Unmatched Files`
- move unmatched/unactionable files

Only selected actionable items produce filesystem operations. Supported companion files follow their parent video file as they do today.

## Collision Behavior

If the canonical show/movie output folder already exists, jobs merge into it by default.

Before moving any file, execution checks all selected destination file paths. If no selected file would collide, the job uses the canonical output folder.

If any selected destination filename would collide, the whole job reroutes to the next available numbered sibling folder:

- `Toy Story (1998)`
- `Toy Story (1998) (1)`
- `Toy Story (1998) (2)`

Only the top-level show/movie folder receives the parenthesized number. Nested folders and filenames stay canonical. This keeps the duplicate folder easy for the user to rename later without having to repair season folders or file names.

The duplicate folder decision should be made once per job before moves begin. All selected operations in that job use the same duplicate root.

## Revert Behavior

Revert moves files from their output paths back to their exact original paths and names.

Revert recreates original parent directories only if needed to place a file back, but it does not delete original directories afterward.

Revert removes empty output directories created or vacated by that job. Cleanup walks upward only within the job output root and stops before removing the configured output root itself.

If a reverted output directory contains unrelated files, it is left in place.

## Preview, Queue, And History

Preview should show the actual destination under the configured output root.

TV example:

```text
D:\TV Output\Show Name (2024)\Season 01\Show Name (2024) - S01E01 - Pilot.mkv
```

Movie example:

```text
D:\Movie Output\Movie Name (2024)\Movie Name (2024).mkv
```

Queue and history detail should distinguish:

- Source: original source folder/path
- Output: configured output folder and generated media subfolder
- Action: Move and rename

`Open Source` opens the original source location when available.

`Open Target` opens the output folder or generated subfolder after execution. While a job is pending, `Open Target` should be disabled if the target folder has not been created yet.

Job detail and projection helpers should stop inferring folder renames from `show_folder_rename` for new destination-aware jobs. The displayed operation is an output move/rename, not a source folder rename.

## Future MKV Cleanup Path

The future mkvmerge feature should build on the destination model:

- rename-only jobs move originals into output
- strip/clean jobs create a processed output copy and leave the original source file untouched
- future copy mode can share the same output-root and collision behavior

Mkvmerge jobs should be marked as partially revertible:

- output files produced by the job can be deleted or moved during revert
- removed tracks, cleaned track titles, and removed attachments are not "renamed back" because the original source file was not modified

This design intentionally does not define detailed mkvmerge settings yet. The Settings category can reserve space for the future feature without exposing unfinished controls.

## Error Handling

Settings validation errors:

- missing path
- path exists but is not a directory
- browse/save failure

Scan gating errors:

- output root missing or invalid
- output root equals source folder
- output root is nested inside source folder

Execution errors:

- source file missing at execution time
- destination collision could not be resolved
- output directory creation failure
- move failure

Execution should fail before moving files if preflight detects an unresolvable destination conflict. Partial failures after some moves should preserve undo data for completed moves so revert can still recover.

## Testing Strategy

Settings service tests:

- defaults include empty output folders
- valid output folder persists and round-trips
- invalid type resets to default
- missing/deleted saved folder reports invalid through validation helper

Settings UI tests:

- category sidebar builds expected categories
- Destinations category shows both path controls
- invalid path cannot be saved
- valid path updates settings service
- checkbox styling uses custom painted controls or consistent QSS styling

Scan gating tests:

- TV scan blocked without TV output folder
- movie scan blocked without movie output folder
- scan blocked when source equals output
- scan blocked when output is nested under source
- scan allowed when output exists outside source

Queue/job creation tests:

- TV batch job stores source root and output root
- movie batch job stores source root and output root
- target directories are output-root-relative
- unmatched/unactionable preview items do not produce ops

Executor tests:

- TV job moves selected files into output show/season folders
- movie job moves selected file into output movie folder
- original source folders remain intact even when empty
- unsupported leftover files remain in source
- existing output folder merges when filenames do not collide
- filename collision reroutes whole job to numbered sibling folder
- numbered duplicate folder does not modify nested season folder names or filenames

Revert tests:

- moved files return to exact original paths and names
- empty output media folders are removed
- cleanup does not remove configured output root
- cleanup does not remove original source folders
- output folders with unrelated files are preserved

Queue/history UI tests:

- detail panel distinguishes Source and Output
- pending `Open Target` is disabled when target folder does not exist
- completed `Open Target` points to output location
- legacy jobs remain displayable

## Implementation Notes

The implementation plan should be staged:

1. Add settings schema/accessors and validation helpers.
2. Restyle Settings around the category sidebar and destination controls.
3. Add scan gating before TV/movie discovery starts.
4. Extend job creation and storage for output roots.
5. Replace source-coupled execution with output-root execution for new jobs.
6. Update preview, queue detail, history detail, and projection helpers.
7. Remove or bypass `Unmatched Files` cleanup for destination-aware jobs.
8. Add revert cleanup constrained to output roots.
9. Add compatibility handling for existing legacy jobs.

The destination-aware path should be introduced behind explicit fields rather than trying to infer behavior from existing `show_folder_rename` state. This keeps future copy and mkvmerge jobs from inheriting source-folder rename assumptions.
