# Episode Mapping Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users map, unmap, and correct any TV episode row without creating duplicate hidden mappings.

**Architecture:** Move episode reassignment rules into `EpisodeMappingService` so all UI entry points use one conflict-safe operation. The UI should present mapped, review, missing, and unmapped rows as editable states of the same episode map instead of separate one-off lists.

**Tech Stack:** Python, PySide6 dialogs, existing `PreviewItem`/`EpisodeGuide` models, pytest Qt smoke tests.

---

## File Structure

- Modify `plex_renamer/app/services/episode_mapping_service.py`: add conflict-safe mapping operations.
- Modify `plex_renamer/app/models/state_models.py`: add row metadata needed by the UI for action visibility.
- Modify `plex_renamer/gui_qt/widgets/_workspace_widgets.py`: add row action buttons for mapped, missing, review, and unmapped rows.
- Modify `plex_renamer/gui_qt/widgets/_media_workspace_preview.py`: wire row actions to workspace callbacks and move unmapped primary files directly under Folder.
- Modify `plex_renamer/gui_qt/widgets/_media_workspace_actions.py`: add dialog-backed mapping handlers.
- Modify `plex_renamer/gui_qt/widgets/media_workspace.py`: expose preview-panel callbacks through the workspace facade.
- Modify `plex_renamer/gui_qt/widgets/_media_workspace_ui.py`: pass mapping callbacks into `MediaWorkspacePreviewPanel`.
- Modify `tests/test_episode_mapping_projection.py`: cover pure mapping invariants.
- Modify `tests/test_qt_media_workspace.py`: cover UI actions and row grouping.

### Task 1: Conflict-Safe Mapping Service

**Files:**
- Modify: `tests/test_episode_mapping_projection.py`
- Modify: `plex_renamer/app/services/episode_mapping_service.py`

- [ ] **Step 1: Write failing owner-swap test**

Add:

```python
def test_remap_preview_to_episode_unmaps_previous_owner():
    service = EpisodeMappingService()
    first = PreviewItem(Path("C:/tv/Show/S01E01.mkv"), "Show - S01E01 - Pilot.mkv", Path("C:/tv/Show/Season 01"), 1, [1], "OK")
    second = PreviewItem(Path("C:/tv/Show/S01E02.mkv"), "Show - S01E02 - Second.mkv", Path("C:/tv/Show/Season 01"), 1, [2], "OK")
    state = ScanState(
        folder=Path("C:/tv/Show"),
        media_info={"id": 1, "name": "Show", "year": "2024"},
        preview_items=[first, second],
        scanner=type("Scanner", (), {"episode_meta": {(1, 1): {"name": "Pilot"}, (1, 2): {"name": "Second"}}})(),
    )

    service.remap_preview_to_episode(state, second, season=1, episode=1)

    assert second.season == 1
    assert second.episodes == [1]
    assert second.status == "OK"
    assert first.season is None
    assert first.episodes == []
    assert first.status == "SKIP: remapped to another episode"
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
python -m pytest tests/test_episode_mapping_projection.py::test_remap_preview_to_episode_unmaps_previous_owner -q
```

Expected: fails because the previous owner remains mapped.

- [ ] **Step 3: Implement unmap-before-map**

Add to `EpisodeMappingService`:

```python
    def _unmap_existing_episode_owner(
        self,
        state: ScanState,
        *,
        season: int,
        episode: int,
        except_preview: PreviewItem,
    ) -> None:
        for candidate in state.preview_items:
            if candidate is except_preview:
                continue
            if candidate.season != season or episode not in candidate.episodes:
                continue
            candidate.season = None
            candidate.episodes = []
            candidate.new_name = None
            candidate.target_dir = None
            candidate.status = "SKIP: remapped to another episode"
            candidate.episode_confidence = 0.0
            for companion in candidate.companions:
                companion.new_name = ""
```

Call it at the start of `remap_preview_to_episode()` before assigning the new key.

- [ ] **Step 4: Run test to verify pass**

Run the same pytest command. Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_episode_mapping_projection.py plex_renamer/app/services/episode_mapping_service.py
git commit -m "Make episode remapping conflict-safe"
```

### Task 2: Missing And Unmapped Row Actions

**Files:**
- Modify: `plex_renamer/app/models/state_models.py`
- Modify: `plex_renamer/app/services/episode_mapping_service.py`
- Modify: `plex_renamer/gui_qt/widgets/_workspace_widgets.py`
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_preview.py`
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_actions.py`
- Modify: `plex_renamer/gui_qt/widgets/media_workspace.py`
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_ui.py`
- Modify: `tests/test_qt_media_workspace.py`

- [ ] **Step 1: Write failing missing-file action test**

Add a Qt test that creates a missing episode row and an unmapped primary file, clicks `Map File`, chooses the unmapped file, and asserts the missing row becomes mapped while the unmapped section disappears.

- [ ] **Step 2: Add row metadata**

Add `action_kind: str = ""` to `EpisodeGuideRow` and populate:

```python
action_kind="change"      # mapped and review rows
action_kind="map_file"    # missing file rows
```

Keep `UnmappedFileRow.preview` populated for selectable unmapped files.

Populate `action_kind` in `EpisodeMappingService.build_episode_guide()` so every projection consumer receives the same action contract.

- [ ] **Step 3: Add row actions**

In `EpisodeGuideRowWidget`, show:

```python
Change
```

for mapped and review rows, and:

```python
Map File
```

for missing rows. Keep `Approve` visible only for review rows.

- [ ] **Step 4: Add action handlers**

Add workspace callbacks:

```python
map_file_to_episode(state, season, episode)
change_episode_mapping(state, preview)
```

Use a list dialog for file choice. The dialog item labels should be original file names, with full paths in tooltips.

Wire those callbacks through `media_workspace.py` and `_media_workspace_ui.py` using the existing preview-panel callback pattern, then route them to `_media_workspace_actions.py`.

- [ ] **Step 5: Run focused tests**

Run:

```bash
python -m pytest tests/test_episode_mapping_projection.py tests/test_qt_media_workspace.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add plex_renamer/app/models/state_models.py plex_renamer/app/services/episode_mapping_service.py plex_renamer/gui_qt/widgets/_workspace_widgets.py plex_renamer/gui_qt/widgets/_media_workspace_preview.py plex_renamer/gui_qt/widgets/_media_workspace_actions.py plex_renamer/gui_qt/widgets/media_workspace.py plex_renamer/gui_qt/widgets/_media_workspace_ui.py tests/test_qt_media_workspace.py tests/test_episode_mapping_projection.py
git commit -m "Add editable episode mapping actions"
```

### Task 3: Unmapped Primary Files Placement

**Files:**
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_preview.py`
- Modify: `tests/test_qt_media_workspace.py`

- [ ] **Step 1: Write failing section-order test**

Add a test that builds a TV state with a folder preview, an unmapped primary file, and a season row. Assert preview headers are ordered:

```python
["FOLDER", "UNMAPPED PRIMARY FILES", "SEASON 1"]
```

- [ ] **Step 2: Move unmapped section**

In `_populate_episode_guide()`, render `guide.unmapped_primary_files` immediately after `_add_folder_preview_section()` and before season headers when the filter allows unmapped content.

- [ ] **Step 3: Keep expanded by default**

Do not assign unmapped primary files a collapsible `section_key`; render it as a static header and visible rows.

- [ ] **Step 4: Run test**

Run:

```bash
python -m pytest tests/test_qt_media_workspace.py::QtMediaWorkspaceTests::test_media_workspace_unmapped_primary_files_render_below_folder -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add plex_renamer/gui_qt/widgets/_media_workspace_preview.py tests/test_qt_media_workspace.py
git commit -m "Move unmapped files below folder preview"
```
