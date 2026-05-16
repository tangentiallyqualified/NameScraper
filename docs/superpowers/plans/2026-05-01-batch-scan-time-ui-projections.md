# Batch Scan-Time UI Projection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move expensive TV episode-guide display preparation out of show-click and season-toggle interactions so batch mode feels instant after scanning.

**Architecture:** Build pure Python episode-guide projections during scan completion and store them in an app-layer cache owned by `MediaController`. The Qt preview panel consumes already-prepared projections, and season header toggles only hide/show existing rows instead of clearing and rebuilding the whole `QListWidget`. Any operation that changes show match, episode match, review status, missing/unmapped ownership, or source metadata must invalidate and rebuild the cached projection for that state before the UI refreshes.

**Tech Stack:** Python, PySide6 `QListWidget`, existing `EpisodeMappingService`, existing `EpisodeGuide` models, `MediaController` scan lifecycle, pytest Qt smoke tests.

---

## Why The Previous Optimization Was Not Enough

The first pass cached `EpisodeGuide` objects inside `MediaWorkspacePreviewPanel`. That only helped after a show had already been rendered once. It did not help the first show click after scanning, and season header toggles still called `populate_preview()`, which cleared the list, recreated every `QListWidgetItem`, recreated every row widget, and reattached them with `setItemWidget()`.

The revised approach optimizes the correct layer:

- scan-time/controller layer prepares row projection data before the user can click the batch screen;
- UI show switching reads prepared data instead of recalculating episode mapping;
- season headers update visibility in-place instead of rebuilding rows;
- match fixes and episode mapping fixes invalidate and rebuild the specific affected state's projection.

Do not pre-create Qt widgets during scan. Qt widgets belong on the GUI thread, and pre-creating hundreds of hidden row widgets would trade CPU flicker for memory and thread-safety problems. The scan-time artifact is a pure data projection.

---

## File Structure

- Create `plex_renamer/app/services/episode_projection_cache.py`: app-layer cache for prepared `EpisodeGuide` projections and signatures.
- Modify `plex_renamer/app/controllers/media_controller.py`: own the projection cache and expose `episode_guide_for_state()`, `prepare_episode_guides()`, `refresh_episode_guide()`, and `invalidate_episode_guide()`.
- Modify `plex_renamer/app/controllers/_tv_batch_helpers.py`: prepare projections after bulk TV episode scanning and emit progress while preparing them.
- Modify `plex_renamer/app/controllers/_controller_tv_workflows.py`: invalidate before single-show scans and prepare after single-show scan completion.
- Modify `plex_renamer/gui_qt/widgets/_media_workspace_ui.py`: pass an episode-guide provider into the preview panel.
- Modify `plex_renamer/gui_qt/widgets/_media_workspace_preview.py`: consume controller-prepared guides and toggle season rows in-place.
- Modify `plex_renamer/gui_qt/widgets/_media_workspace_state.py`: route header clicks through the preview panel's in-place toggle method.
- Modify `plex_renamer/gui_qt/widgets/_media_workspace_actions.py`: refresh projections after show rematches, episode approvals, approve-all, and episode fix/remap actions.
- Modify `plex_renamer/gui_qt/widgets/_media_workspace_match_actions.py`: invalidate projections when switching a show match and rebuild after follow-up scan.
- Modify `plex_renamer/gui_qt/_main_window_scan.py`: ensure the structured scan screen is shown and updated during discovery, episode scanning, and projection preparation.
- Modify `plex_renamer/gui_qt/widgets/_workspace_widgets.py`: restore visible spacing between episode cards after fixed-height row changes.
- Create `tests/test_episode_projection_cache.py`: pure cache and signature tests.
- Modify `tests/test_media_controller.py`: controller preparation, invalidation, and scan progress tests.
- Modify `tests/test_qt_media_workspace.py`: prepared-projection consumption, incremental header toggles, stale-state invalidation, and row spacing tests.
- Modify `tests/test_qt_main_window.py`: scan loading screen progress wiring tests.

---

### Task 1: App-Layer Episode Projection Cache

**Files:**
- Create: `tests/test_episode_projection_cache.py`
- Create: `plex_renamer/app/services/episode_projection_cache.py`

- [ ] **Step 1: Write failing cache reuse and invalidation tests**

Create `tests/test_episode_projection_cache.py`:

```python
from __future__ import annotations

from pathlib import Path

from plex_renamer.app.services.episode_mapping_service import EpisodeMappingService
from plex_renamer.app.services.episode_projection_cache import EpisodeProjectionCacheService
from plex_renamer.engine import PreviewItem, ScanState


def _state_with_preview(status: str = "OK") -> ScanState:
    return ScanState(
        folder=Path("C:/library/tv/Example"),
        media_info={"id": 101, "name": "Example Show", "year": "2024"},
        preview_items=[
            PreviewItem(
                original=Path("C:/library/tv/Example/Season 01/Example.S01E01.mkv"),
                new_name="Example Show (2024) - S01E01 - Pilot.mkv",
                target_dir=Path("C:/library/tv/Example Show (2024)/Season 01"),
                season=1,
                episodes=[1],
                status=status,
            )
        ],
        scanned=True,
        confidence=1.0,
    )


def test_episode_projection_cache_reuses_prepared_guide_until_state_changes():
    service = EpisodeProjectionCacheService(EpisodeMappingService())
    state = _state_with_preview()

    prepared = service.prepare_state(state)
    reused = service.guide_for_state(state)

    assert reused is prepared
    assert service.cache_size == 1

    state.preview_items[0].status = "REVIEW: episode confidence below threshold"
    state.preview_items[0].episode_confidence = 0.42
    rebuilt = service.guide_for_state(state)

    assert rebuilt is not prepared
    assert rebuilt.rows[0].status == "Review"


def test_episode_projection_cache_invalidate_state_forces_rebuild():
    service = EpisodeProjectionCacheService(EpisodeMappingService())
    state = _state_with_preview()

    prepared = service.prepare_state(state)
    service.invalidate_state(state)
    rebuilt = service.guide_for_state(state)

    assert rebuilt is not prepared
    assert service.cache_size == 1


def test_episode_projection_cache_signature_tracks_match_and_episode_mapping_state():
    service = EpisodeProjectionCacheService(EpisodeMappingService())
    state = _state_with_preview()

    first_signature = service.signature_for_state(state)
    state.media_info = {"id": 202, "name": "Replacement Show", "year": "2024"}
    match_signature = service.signature_for_state(state)
    state.preview_items[0].season = 2
    state.preview_items[0].episodes = [3]
    mapping_signature = service.signature_for_state(state)

    assert match_signature != first_signature
    assert mapping_signature != match_signature
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
python -m pytest tests/test_episode_projection_cache.py -q
```

Expected: fails with `ModuleNotFoundError: No module named 'plex_renamer.app.services.episode_projection_cache'`.

- [ ] **Step 3: Implement the projection cache service**

Create `plex_renamer/app/services/episode_projection_cache.py`:

```python
"""Cache scan-time TV episode-guide projections for batch UI rendering."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ...engine import ScanState
from ..models import EpisodeGuide
from .episode_mapping_service import EpisodeMappingService


@dataclass(slots=True)
class _CachedEpisodeGuide:
    signature: tuple
    guide: EpisodeGuide


class EpisodeProjectionCacheService:
    def __init__(self, episode_mapping: EpisodeMappingService | None = None) -> None:
        self._episode_mapping = episode_mapping or EpisodeMappingService()
        self._cache: dict[str, _CachedEpisodeGuide] = {}

    @property
    def cache_size(self) -> int:
        return len(self._cache)

    def prepare_states(self, states: Iterable[ScanState]) -> None:
        for state in states:
            if state.preview_items:
                self.prepare_state(state)

    def prepare_state(self, state: ScanState) -> EpisodeGuide:
        signature = self.signature_for_state(state)
        guide = self._episode_mapping.build_episode_guide(state)
        self._cache[self._key_for_state(state)] = _CachedEpisodeGuide(signature, guide)
        return guide

    def guide_for_state(self, state: ScanState) -> EpisodeGuide:
        key = self._key_for_state(state)
        signature = self.signature_for_state(state)
        cached = self._cache.get(key)
        if cached is not None and cached.signature == signature:
            return cached.guide
        return self.prepare_state(state)

    def refresh_state(self, state: ScanState) -> EpisodeGuide:
        self.invalidate_state(state)
        return self.prepare_state(state)

    def invalidate_state(self, state: ScanState) -> None:
        self._cache.pop(self._key_for_state(state), None)

    def invalidate_all(self) -> None:
        self._cache.clear()

    def signature_for_state(self, state: ScanState) -> tuple:
        preview_signature = tuple(
            (
                str(preview.original),
                preview.new_name,
                str(preview.target_dir) if preview.target_dir is not None else "",
                preview.season,
                tuple(preview.episodes),
                preview.status,
                round(preview.episode_confidence, 4),
                tuple(
                    (str(companion.original), companion.new_name, companion.file_type)
                    for companion in preview.companions
                ),
            )
            for preview in state.preview_items
        )
        completeness = state.completeness
        completeness_signature = None
        if completeness is not None:
            completeness_signature = (
                tuple(
                    (
                        season_num,
                        season.expected,
                        season.matched,
                        tuple(season.missing),
                        tuple(season.matched_episodes),
                    )
                    for season_num, season in sorted(completeness.seasons.items())
                ),
                None
                if completeness.specials is None
                else (
                    completeness.specials.expected,
                    completeness.specials.matched,
                    tuple(completeness.specials.missing),
                    tuple(completeness.specials.matched_episodes),
                ),
                completeness.total_expected,
                completeness.total_matched,
                tuple(completeness.total_missing),
            )
        scanner_meta = ()
        if state.scanner is not None:
            scanner_meta = tuple(
                (
                    key,
                    tuple(sorted((str(name), str(value)) for name, value in meta.items())),
                )
                for key, meta in sorted(state.scanner.episode_meta.items())
            )
        orphan_signature = tuple(
            (str(companion.original), companion.new_name, companion.file_type)
            for companion in state.orphan_companion_files
        )
        return (
            state.show_id,
            state.media_info.get("name") or state.media_info.get("title") or "",
            state.media_info.get("year") or "",
            state.active_episode_source,
            tuple(sorted(state.season_names.items())),
            preview_signature,
            completeness_signature,
            scanner_meta,
            orphan_signature,
        )

    @staticmethod
    def _key_for_state(state: ScanState) -> str:
        source = str(state.source_file) if state.source_file is not None else ""
        return f"{state.folder}|{state.show_id}|{source}"
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
python -m pytest tests/test_episode_projection_cache.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_episode_projection_cache.py plex_renamer/app/services/episode_projection_cache.py
git commit -m "Add scan-time episode projection cache"
```

---

### Task 2: Controller-Owned Projection Preparation During Scan

**Files:**
- Modify: `tests/test_media_controller.py`
- Modify: `plex_renamer/app/controllers/media_controller.py`
- Modify: `plex_renamer/app/controllers/_tv_batch_helpers.py`
- Modify: `plex_renamer/app/controllers/_controller_tv_workflows.py`

- [ ] **Step 1: Write failing controller preparation tests**

Add these tests to `TVBatchTests` in `tests/test_media_controller.py`:

```python
    def test_scan_all_shows_prepares_episode_guides_before_ready(self):
        state = ScanState(
            folder=self.tmp / "PreparedShow",
            media_info={"id": 11, "name": "Prepared Show", "year": "2024"},
            scanned=False,
        )

        class _PreparedOrchestrator:
            def scan_all(self, progress_callback=None, cancel_event=None):
                state.preview_items = [
                    PreviewItem(
                        original=state.folder / "Season 01" / "Prepared.Show.S01E01.mkv",
                        new_name="Prepared Show (2024) - S01E01 - Pilot.mkv",
                        target_dir=state.folder / "Prepared Show (2024)" / "Season 01",
                        season=1,
                        episodes=[1],
                        status="OK",
                    )
                ]
                state.scanned = True
                if progress_callback:
                    progress_callback(1, 1, state.display_name)

        self.set_tv_session([state], batch_orchestrator=_PreparedOrchestrator())

        self.ctrl.scan_all_shows()

        _wait_until(
            lambda: self.ctrl.scan_progress.lifecycle == ScanLifecycle.READY,
            description="TV scan and projection preparation to finish",
        )

        guide = self.ctrl.episode_guide_for_state(state)
        self.assertEqual(len(guide.rows), 1)
        self.assertEqual(guide.rows[0].status, "Mapped")

    def test_episode_guide_for_state_rebuilds_after_invalidation(self):
        state = ScanState(
            folder=self.tmp / "ReviewShow",
            media_info={"id": 12, "name": "Review Show", "year": "2024"},
            preview_items=[
                PreviewItem(
                    original=self.tmp / "ReviewShow" / "Season 01" / "Review.Show.S01E01.mkv",
                    new_name="Review Show (2024) - S01E01 - Pilot.mkv",
                    target_dir=self.tmp / "Review Show (2024)" / "Season 01",
                    season=1,
                    episodes=[1],
                    status="REVIEW: episode confidence below threshold",
                    episode_confidence=0.45,
                )
            ],
            scanned=True,
        )
        first = self.ctrl.episode_guide_for_state(state)

        state.preview_items[0].status = "OK"
        state.preview_items[0].episode_confidence = 1.0
        self.ctrl.invalidate_episode_guide(state)
        second = self.ctrl.episode_guide_for_state(state)

        self.assertIsNot(second, first)
        self.assertEqual(second.rows[0].status, "Mapped")
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
python -m pytest tests/test_media_controller.py::TVBatchTests::test_scan_all_shows_prepares_episode_guides_before_ready tests/test_media_controller.py::TVBatchTests::test_episode_guide_for_state_rebuilds_after_invalidation -q
```

Expected: fails because `MediaController` does not expose projection cache methods.

- [ ] **Step 3: Add controller projection cache methods**

In `plex_renamer/app/controllers/media_controller.py`, import and initialize the service:

```python
from ..services.episode_projection_cache import EpisodeProjectionCacheService
```

Inside `MediaController.__init__`:

```python
        self._episode_projection_cache = EpisodeProjectionCacheService()
```

Add methods near query/session helpers:

```python
    def prepare_episode_guides(self, states: list[ScanState]) -> None:
        self._episode_projection_cache.prepare_states(states)

    def episode_guide_for_state(self, state: ScanState):
        return self._episode_projection_cache.guide_for_state(state)

    def refresh_episode_guide(self, state: ScanState):
        return self._episode_projection_cache.refresh_state(state)

    def invalidate_episode_guide(self, state: ScanState) -> None:
        self._episode_projection_cache.invalidate_state(state)

    def invalidate_episode_guides(self) -> None:
        self._episode_projection_cache.invalidate_all()
```

Add these protocol methods to `_TVBatchController` in `plex_renamer/app/controllers/_tv_batch_helpers.py`:

```python
    def prepare_episode_guides(self, states: list[ScanState]) -> None: ...
    def invalidate_episode_guides(self) -> None: ...
```

- [ ] **Step 4: Prepare projections before READY after bulk scan**

In `_complete_tv_bulk_scan()` in `plex_renamer/app/controllers/_tv_batch_helpers.py`, prepare projections before setting `READY` and before notifying `library_changed`:

```python
    controller._set_progress(
        ScanLifecycle.SCANNING,
        phase="Preparing episode list...",
        done=0,
        total=scanned,
        message=f"Preparing episode list... 0/{scanned}",
    )
    controller.prepare_episode_guides([
        state for state in controller._batch_states
        if state.scanned and state.preview_items
    ])
```

Keep the existing final `READY` payload after this block. This makes the batch screen receive already-prepared projections.

- [ ] **Step 5: Invalidate around single-show scans**

In `plex_renamer/app/controllers/_controller_tv_workflows.py`, before calling `start_single_show_scan(...)`, invalidate the selected state:

```python
        if hasattr(self._controller, "invalidate_episode_guide"):
            self._controller.invalidate_episode_guide(state)
```

Then ensure the single-show scan completion helper calls `controller.refresh_episode_guide(state)` after `state.preview_items` is populated and before `library_changed` or UI refresh. If the completion path lives in `plex_renamer/app/controllers/_tv_scan_helpers.py`, add the call there instead of in `_controller_tv_workflows.py`:

```python
        if hasattr(controller, "refresh_episode_guide") and state.preview_items:
            controller.refresh_episode_guide(state)
```

- [ ] **Step 6: Run tests to verify pass**

Run:

```bash
python -m pytest tests/test_media_controller.py::TVBatchTests::test_scan_all_shows_prepares_episode_guides_before_ready tests/test_media_controller.py::TVBatchTests::test_episode_guide_for_state_rebuilds_after_invalidation -q
```

Expected: both tests pass.

- [ ] **Step 7: Commit**

```bash
git add tests/test_media_controller.py plex_renamer/app/controllers/media_controller.py plex_renamer/app/controllers/_tv_batch_helpers.py plex_renamer/app/controllers/_controller_tv_workflows.py
git commit -m "Prepare TV episode projections during scan"
```

---

### Task 3: Preview Panel Uses Prepared Projections On First Render

**Files:**
- Modify: `tests/test_qt_media_workspace.py`
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_ui.py`
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_preview.py`

- [ ] **Step 1: Write failing first-render provider test**

Add this test near existing episode-guide workspace tests in `tests/test_qt_media_workspace.py`:

```python
    def test_media_workspace_uses_controller_episode_guide_on_first_show_render(self):
        from plex_renamer.app.services.episode_mapping_service import EpisodeMappingService
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = [state]
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")
                self.episode_guide_for_state = MagicMock(
                    return_value=EpisodeMappingService().build_episode_guide(state)
                )

            def select_show(self, index):
                self.library_selected_index = index
                return self.batch_states[index] if 0 <= index < len(self.batch_states) else None

            def sync_queued_states(self):
                return None

        state = ScanState(
            folder=Path("C:/library/tv/Example"),
            media_info={"id": 101, "name": "Example Show", "year": "2024"},
            preview_items=[
                PreviewItem(
                    original=Path("C:/library/tv/Example/Season 01/Example.S01E01.mkv"),
                    new_name="Example Show (2024) - S01E01 - Pilot.mkv",
                    target_dir=Path("C:/library/tv/Example Show (2024)/Season 01"),
                    season=1,
                    episodes=[1],
                    status="OK",
                )
            ],
            scanned=True,
            confidence=1.0,
        )
        media_ctrl = _FakeMediaController(state)
        workspace = MediaWorkspace(media_type="tv", media_controller=media_ctrl)
        workspace._preview_panel._episode_mapping.build_episode_guide = MagicMock(
            side_effect=AssertionError("preview panel should not build TV guide on first render")
        )

        workspace.show_ready()

        media_ctrl.episode_guide_for_state.assert_called_with(state)
        workspace.close()
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
python -m pytest tests/test_qt_media_workspace.py::QtMediaWorkspaceTests::test_media_workspace_uses_controller_episode_guide_on_first_show_render -q
```

Expected: fails because the preview panel still builds its own guide.

- [ ] **Step 3: Pass an episode guide provider into the preview panel**

In `MediaWorkspacePreviewPanel.__init__` in `plex_renamer/gui_qt/widgets/_media_workspace_preview.py`, add a callback parameter:

```python
        episode_guide_provider=None,
```

Store it:

```python
        self._episode_guide_provider = episode_guide_provider
```

In `plex_renamer/gui_qt/widgets/_media_workspace_ui.py`, pass a provider when constructing `MediaWorkspacePreviewPanel`:

```python
            episode_guide_provider=(
                workspace._media_ctrl.episode_guide_for_state
                if workspace._media_ctrl is not None
                and hasattr(workspace._media_ctrl, "episode_guide_for_state")
                else None
            ),
```

- [ ] **Step 4: Use provider before local fallback**

Replace `_episode_guide_for_state()` in `_media_workspace_preview.py` with:

```python
    def _episode_guide_for_state(self, state: ScanState):
        if self._episode_guide_provider is not None:
            return self._episode_guide_provider(state)
        key = _state_key(state)
        signature = self._episode_guide_signature(state)
        cached = self._episode_guide_cache.get(key)
        if cached is not None and cached[0] == signature:
            return cached[1]
        guide = self._episode_mapping.build_episode_guide(state)
        self._episode_guide_cache[key] = (signature, guide)
        return guide
```

Keep the local fallback for tests and lightweight fake controllers that do not implement the provider.

- [ ] **Step 5: Run test to verify pass**

Run:

```bash
python -m pytest tests/test_qt_media_workspace.py::QtMediaWorkspaceTests::test_media_workspace_uses_controller_episode_guide_on_first_show_render -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add tests/test_qt_media_workspace.py plex_renamer/gui_qt/widgets/_media_workspace_ui.py plex_renamer/gui_qt/widgets/_media_workspace_preview.py
git commit -m "Render TV preview from prepared episode guides"
```

---

### Task 4: Incremental Season Header Toggle

**Files:**
- Modify: `tests/test_qt_media_workspace.py`
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_preview.py`
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_state.py`

- [ ] **Step 1: Write failing no-rebuild toggle test**

Add this test to `tests/test_qt_media_workspace.py`:

```python
    def test_media_workspace_episode_header_toggle_hides_rows_without_rebuilding_preview(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace
        from plex_renamer.gui_qt.widgets._media_workspace_preview import _PREVIEW_ENTRY_KIND_ROLE

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = [state]
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                return self.batch_states[index] if 0 <= index < len(self.batch_states) else None

            def sync_queued_states(self):
                return None

        state = ScanState(
            folder=Path("C:/library/tv/Example"),
            media_info={"id": 101, "name": "Example Show", "year": "2024"},
            preview_items=[
                PreviewItem(
                    original=Path(f"C:/library/tv/Example/Season 01/Example.S01E{episode:02d}.mkv"),
                    new_name=f"Example Show (2024) - S01E{episode:02d} - Episode {episode}.mkv",
                    target_dir=Path("C:/library/tv/Example Show (2024)/Season 01"),
                    season=1,
                    episodes=[episode],
                    status="OK",
                )
                for episode in range(1, 6)
            ],
            scanned=True,
            confidence=1.0,
        )
        workspace = MediaWorkspace(media_type="tv", media_controller=_FakeMediaController(state))
        workspace.show_ready()
        original_populate = workspace._state_coordinator.populate_preview
        workspace._state_coordinator.populate_preview = MagicMock(wraps=original_populate)
        header = next(
            workspace._preview_list.item(row)
            for row in range(workspace._preview_list.count())
            if workspace._preview_list.item(row).data(_PREVIEW_ENTRY_KIND_ROLE) == "header"
        )
        first_episode = next(
            workspace._preview_list.item(row)
            for row in range(workspace._preview_list.count())
            if workspace._preview_list.item(row).data(_PREVIEW_ENTRY_KIND_ROLE) == "episode"
        )
        first_widget = workspace._preview_list.itemWidget(first_episode)

        workspace._on_preview_item_clicked(header)

        workspace._state_coordinator.populate_preview.assert_not_called()
        self.assertTrue(first_episode.isHidden())
        self.assertIs(workspace._preview_list.itemWidget(first_episode), first_widget)
        self.assertTrue(header.text().startswith("\u25b8 SEASON 1"))
        workspace.close()
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
python -m pytest tests/test_qt_media_workspace.py::QtMediaWorkspaceTests::test_media_workspace_episode_header_toggle_hides_rows_without_rebuilding_preview -q
```

Expected: fails because header clicks call `populate_preview()`.

- [ ] **Step 3: Store season row membership while populating**

In `MediaWorkspacePreviewPanel.__init__`, add:

```python
        self._episode_section_items: dict[str, list[QListWidgetItem]] = {}
```

At the start of `populate_from_state()`, clear this per-render index:

```python
        self._episode_section_items.clear()
```

When adding each episode item in `_populate_episode_guide()`, append it to the current section:

```python
                self._episode_section_items.setdefault(section_key, []).append(item)
```

- [ ] **Step 4: Add in-place toggle method**

Add this method to `MediaWorkspacePreviewPanel`:

```python
    def toggle_episode_section(
        self,
        *,
        state: ScanState,
        section_key: str,
        preview_group_state: dict[str, set[int | str]],
    ) -> bool:
        collapsed = preview_group_state.setdefault(_state_key(state), set())
        is_collapsing = section_key not in collapsed
        if is_collapsing:
            collapsed.add(section_key)
        else:
            collapsed.remove(section_key)

        for row in range(self._list_widget.count()):
            item = self._list_widget.item(row)
            if item.data(_PREVIEW_SECTION_ROLE) == section_key:
                season_num = str(section_key).removeprefix("episode-guide-season:")
                prefix = "\u25b8 " if is_collapsing else "\u25be "
                text = item.text()
                if text.startswith(("\u25b8 ", "\u25be ")):
                    text = text[2:]
                item.setText(prefix + text)
                break

        for item in self._episode_section_items.get(section_key, []):
            item.setHidden(is_collapsing)
        self.update_sticky_header()
        return True
```

- [ ] **Step 5: Route header clicks through in-place toggle**

In `MediaWorkspaceStateCoordinator.on_preview_item_clicked()` in `plex_renamer/gui_qt/widgets/_media_workspace_state.py`, replace the final collapse mutation plus `self.populate_preview(state)` with:

```python
        if str(section_key).startswith("episode-guide-season:"):
            handled = workspace._preview_panel.toggle_episode_section(
                state=state,
                section_key=section_key,
                preview_group_state=workspace._preview_group_state,
            )
            if handled:
                return
        collapsed = workspace._preview_group_state.setdefault(_state_key(state), set())
        if section_key in collapsed:
            collapsed.remove(section_key)
        else:
            collapsed.add(section_key)
        self.populate_preview(state)
```

Folder headers and other non-episode sections may continue to rebuild if needed; season headers must not.

- [ ] **Step 6: Run test to verify pass**

Run:

```bash
python -m pytest tests/test_qt_media_workspace.py::QtMediaWorkspaceTests::test_media_workspace_episode_header_toggle_hides_rows_without_rebuilding_preview -q
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add tests/test_qt_media_workspace.py plex_renamer/gui_qt/widgets/_media_workspace_preview.py plex_renamer/gui_qt/widgets/_media_workspace_state.py
git commit -m "Toggle TV season rows without rebuilding preview"
```

---

### Task 5: Projection Invalidation For Match And Episode Changes

**Files:**
- Modify: `tests/test_qt_media_workspace.py`
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_actions.py`
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_match_actions.py`

- [ ] **Step 1: Write failing episode approval invalidation test**

Add this test to `tests/test_qt_media_workspace.py`:

```python
    def test_media_workspace_episode_approval_refreshes_prepared_projection(self):
        from plex_renamer.gui_qt.widgets._workspace_widgets import EpisodeGuideRowWidget
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = [state]
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")
                self.refresh_episode_guide = MagicMock()
                self.invalidate_episode_guide = MagicMock()

            def select_show(self, index):
                self.library_selected_index = index
                return self.batch_states[index] if 0 <= index < len(self.batch_states) else None

            def sync_queued_states(self):
                return None

        review_item = PreviewItem(
            original=Path("C:/library/tv/Example/Season 01/Example.S01E01.mkv"),
            new_name="Example Show (2024) - S01E01 - Pilot.mkv",
            target_dir=Path("C:/library/tv/Example Show (2024)/Season 01"),
            season=1,
            episodes=[1],
            status="REVIEW: episode confidence below threshold",
            episode_confidence=0.5,
        )
        state = ScanState(
            folder=Path("C:/library/tv/Example"),
            media_info={"id": 101, "name": "Example Show", "year": "2024"},
            preview_items=[review_item],
            scanned=True,
            confidence=1.0,
        )
        media_ctrl = _FakeMediaController(state)
        workspace = MediaWorkspace(media_type="tv", media_controller=media_ctrl)
        workspace.show_ready()
        widget = next(
            workspace._preview_list.itemWidget(workspace._preview_list.item(row))
            for row in range(workspace._preview_list.count())
            if isinstance(workspace._preview_list.itemWidget(workspace._preview_list.item(row)), EpisodeGuideRowWidget)
        )

        widget._approve_button.click()
        self._app.processEvents()

        media_ctrl.refresh_episode_guide.assert_called_with(state)
        self.assertEqual(review_item.status, "OK")
        workspace.close()
```

- [ ] **Step 2: Write failing rematch invalidation test**

Add this test to `tests/test_qt_media_workspace.py`:

```python
    def test_media_workspace_show_rematch_invalidates_projection_before_rescan(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeTMDB:
            def search_tv(self, *_args, **_kwargs):
                return []

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = [state]
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")
                self.invalidate_episode_guide = MagicMock()
                self.refresh_episode_guide = MagicMock()

            def select_show(self, index):
                self.library_selected_index = index
                return self.batch_states[index] if 0 <= index < len(self.batch_states) else None

            def sync_queued_states(self):
                return None

            def rematch_tv_state(self, state, chosen, tmdb=None):
                state.media_info = chosen
                state.preview_items = []
                state.scanned = False
                return state

            def scan_show(self, state, _tmdb):
                state.preview_items = [
                    PreviewItem(
                        original=Path("C:/library/tv/Example/Season 01/Example.S01E01.mkv"),
                        new_name="Replacement Show (2024) - S01E01 - Pilot.mkv",
                        target_dir=Path("C:/library/tv/Replacement Show (2024)/Season 01"),
                        season=1,
                        episodes=[1],
                        status="OK",
                    )
                ]
                state.scanned = True

        state = ScanState(
            folder=Path("C:/library/tv/Example"),
            media_info={"id": 101, "name": "Original Show", "year": "2024"},
            preview_items=[],
            scanned=False,
            confidence=0.5,
        )
        media_ctrl = _FakeMediaController(state)
        workspace = MediaWorkspace(media_type="tv", media_controller=media_ctrl, tmdb_provider=_FakeTMDB)

        workspace._apply_tv_match(state, {"id": 202, "name": "Replacement Show", "year": "2024"})

        media_ctrl.invalidate_episode_guide.assert_called_with(state)
        media_ctrl.refresh_episode_guide.assert_called_with(state)
        workspace.close()
```

- [ ] **Step 3: Run tests to verify failure**

Run:

```bash
python -m pytest tests/test_qt_media_workspace.py::QtMediaWorkspaceTests::test_media_workspace_episode_approval_refreshes_prepared_projection tests/test_qt_media_workspace.py::QtMediaWorkspaceTests::test_media_workspace_show_rematch_invalidates_projection_before_rescan -q
```

Expected: fails because action handlers do not call projection invalidation/refresh.

- [ ] **Step 4: Refresh projection after episode status and mapping changes**

In `plex_renamer/gui_qt/widgets/_media_workspace_actions.py`, add a private helper:

```python
def _refresh_episode_projection(workspace, state: ScanState) -> None:
    media_ctrl = getattr(workspace, "_media_ctrl", None)
    if media_ctrl is not None and hasattr(media_ctrl, "refresh_episode_guide"):
        media_ctrl.refresh_episode_guide(state)
```

Call it after each mutation and before `workspace.refresh_from_controller()` in:

```python
approve_episode_mapping()
approve_all_episode_mappings()
prompt_fix_episode_mapping()
```

For `prompt_fix_episode_mapping()`, call it only after `EpisodeMappingService.remap_preview_to_episode(...)` succeeds.

- [ ] **Step 5: Invalidate and refresh around show match switches**

In `plex_renamer/gui_qt/widgets/_media_workspace_match_actions.py`, add:

```python
def _invalidate_episode_projection(workspace, state: ScanState) -> None:
    media_ctrl = getattr(workspace, "_media_ctrl", None)
    if media_ctrl is not None and hasattr(media_ctrl, "invalidate_episode_guide"):
        media_ctrl.invalidate_episode_guide(state)


def _refresh_episode_projection(workspace, state: ScanState) -> None:
    media_ctrl = getattr(workspace, "_media_ctrl", None)
    if media_ctrl is not None and hasattr(media_ctrl, "refresh_episode_guide"):
        media_ctrl.refresh_episode_guide(state)
```

Call `_invalidate_episode_projection(workspace, state)` before `rematch_tv_state(...)` mutates match identity or clears preview data.

After follow-up `scan_show(...)` succeeds and `state.preview_items` is repopulated, call:

```python
_refresh_episode_projection(workspace, updated_state)
```

- [ ] **Step 6: Run tests to verify pass**

Run:

```bash
python -m pytest tests/test_qt_media_workspace.py::QtMediaWorkspaceTests::test_media_workspace_episode_approval_refreshes_prepared_projection tests/test_qt_media_workspace.py::QtMediaWorkspaceTests::test_media_workspace_show_rematch_invalidates_projection_before_rescan -q
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add tests/test_qt_media_workspace.py plex_renamer/gui_qt/widgets/_media_workspace_actions.py plex_renamer/gui_qt/widgets/_media_workspace_match_actions.py
git commit -m "Refresh episode projections after match changes"
```

---

### Task 6: Restore Episode Card Gaps And Guard Against Transient Popups

**Files:**
- Modify: `tests/test_qt_media_workspace.py`
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_preview.py`
- Modify: `plex_renamer/gui_qt/widgets/_workspace_widgets.py`

- [ ] **Step 1: Write failing row spacing test**

Add this test to `tests/test_qt_media_workspace.py`:

```python
    def test_media_workspace_episode_guide_items_preserve_card_gap(self):
        from plex_renamer.gui_qt.widgets._workspace_widgets import EpisodeGuideRowWidget
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = [state]
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                return self.batch_states[index] if 0 <= index < len(self.batch_states) else None

            def sync_queued_states(self):
                return None

        state = ScanState(
            folder=Path("C:/library/tv/Example"),
            media_info={"id": 101, "name": "Example Show", "year": "2024"},
            preview_items=[
                PreviewItem(
                    original=Path(f"C:/library/tv/Example/Season 01/Example.S01E{episode:02d}.mkv"),
                    new_name=f"Example Show (2024) - S01E{episode:02d} - Episode {episode}.mkv",
                    target_dir=Path("C:/library/tv/Example Show (2024)/Season 01"),
                    season=1,
                    episodes=[episode],
                    status="OK",
                )
                for episode in range(1, 3)
            ],
            scanned=True,
            confidence=1.0,
        )
        workspace = MediaWorkspace(media_type="tv", media_controller=_FakeMediaController(state))
        workspace.show_ready()
        for row in range(workspace._preview_list.count()):
            item = workspace._preview_list.item(row)
            widget = workspace._preview_list.itemWidget(item)
            if isinstance(widget, EpisodeGuideRowWidget):
                self.assertGreaterEqual(item.sizeHint().height(), widget.sizeHint().height() + 6)
                break
        else:
            self.fail("No episode guide row widget found")
        workspace.close()
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
python -m pytest tests/test_qt_media_workspace.py::QtMediaWorkspaceTests::test_media_workspace_episode_guide_items_preserve_card_gap -q
```

Expected: fails because `_sync_item_height()` sets item height equal to widget height.

- [ ] **Step 3: Add item height gap for embedded preview widgets**

In `MediaWorkspacePreviewPanel._sync_item_height()`:

```python
    def _sync_item_height(self, item: QListWidgetItem, widget: QWidget) -> None:
        item.setSizeHint(QSize(0, widget.sizeHint().height() + 6))
```

Keep `EpisodeGuideRowWidget` fixed-height internally; the gap belongs to the list item, not the row card.

- [ ] **Step 4: Run test to verify pass**

Run:

```bash
python -m pytest tests/test_qt_media_workspace.py::QtMediaWorkspaceTests::test_media_workspace_episode_guide_items_preserve_card_gap -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_qt_media_workspace.py plex_renamer/gui_qt/widgets/_media_workspace_preview.py plex_renamer/gui_qt/widgets/_workspace_widgets.py
git commit -m "Restore episode card spacing"
```

---

### Task 7: Scan Loading Screen Shows Real Work

**Files:**
- Modify: `tests/test_qt_main_window.py`
- Modify: `plex_renamer/gui_qt/_main_window_scan.py`
- Modify: `plex_renamer/gui_qt/widgets/scan_progress.py`
- Modify: `plex_renamer/app/controllers/_tv_batch_helpers.py`

- [ ] **Step 1: Write failing loading-screen routing test**

Add this test to `tests/test_qt_main_window.py`:

```python
    def test_main_window_scan_progress_updates_active_progress_widget(self):
        from plex_renamer.app.models import ScanLifecycle, ScanProgress
        from plex_renamer.gui_qt._main_window_scan import MainWindowScanCoordinator

        class _FakeStatusBar:
            def __init__(self):
                self.messages = []

            def showMessage(self, message, timeout=0):
                self.messages.append((message, timeout))

        class _FakeProgressWidget:
            def __init__(self):
                self.updates = []

            def update_progress(self, **payload):
                self.updates.append(payload)

        class _FakeWorkspace:
            def __init__(self):
                self.scan_progress_widget = _FakeProgressWidget()
                self.show_scanning_calls = 0

            def show_scanning(self):
                self.show_scanning_calls += 1

        class _FakeMediaController:
            active_content_mode = "tv"

            def start_tv_batch(self, folder, tmdb):
                return None

        class _FakeWindow:
            def __init__(self):
                self.media_ctrl = _FakeMediaController()
                self._tv_workspace = _FakeWorkspace()
                self._movie_workspace = _FakeWorkspace()
                self._status = _FakeStatusBar()

            def statusBar(self):
                return self._status

            def _ensure_tmdb(self):
                return object()

        window = _FakeWindow()
        coordinator = MainWindowScanCoordinator(window, tv_index=0, movies_index=1)

        coordinator.start_tv_scan("C:/library/tv")
        coordinator.on_scan_progress(
            ScanProgress(
                lifecycle=ScanLifecycle.SCANNING,
                phase="Preparing episode list...",
                done=3,
                total=10,
                current_item="Example Show",
                message="Preparing episode list... 3/10 - Example Show",
            )
        )

        self.assertEqual(window._tv_workspace.show_scanning_calls, 1)
        self.assertEqual(window._tv_workspace.scan_progress_widget.updates[-1]["phase"], "Preparing episode list...")
        self.assertEqual(window._tv_workspace.scan_progress_widget.updates[-1]["current_item"], "Example Show")
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
python -m pytest tests/test_qt_main_window.py::QtMainWindowTests::test_main_window_scan_progress_updates_active_progress_widget -q
```

Expected: fails if `start_tv_scan()` does not explicitly show the scanning state or if progress does not reach the active widget.

- [ ] **Step 3: Show scanning state when scan starts**

In `plex_renamer/gui_qt/_main_window_scan.py`, update `_start_scan()` before starting controller work:

```python
        workspace = self._workspace_for_media_type(media_type)
        workspace.show_scanning()
```

Then keep the existing controller start calls.

- [ ] **Step 4: Emit projection preparation progress**

In `_complete_tv_bulk_scan()` in `plex_renamer/app/controllers/_tv_batch_helpers.py`, replace the single preparation progress event from Task 2 with per-state progress:

```python
    prepared_states = [
        state for state in controller._batch_states
        if state.scanned and state.preview_items
    ]
    total_prepared = len(prepared_states)
    for index, state in enumerate(prepared_states, start=1):
        controller._set_progress(
            ScanLifecycle.SCANNING,
            phase="Preparing episode list...",
            done=index,
            total=total_prepared,
            current_item=state.display_name,
            message=f"Preparing episode list... {index}/{total_prepared} - {state.display_name}",
        )
        controller.prepare_episode_guides([state])
```

This is the user-facing "we are preparing the batch screen" step. It should not mention projection caches, orchestrators, or match math.

- [ ] **Step 5: Run loading-screen tests**

Run:

```bash
python -m pytest tests/test_qt_main_window.py::QtMainWindowTests::test_main_window_scan_progress_updates_active_progress_widget tests/test_media_controller.py::TVBatchTests::test_scan_all_shows_prepares_episode_guides_before_ready -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add tests/test_qt_main_window.py plex_renamer/gui_qt/_main_window_scan.py plex_renamer/gui_qt/widgets/scan_progress.py plex_renamer/app/controllers/_tv_batch_helpers.py
git commit -m "Show projection preparation in scan progress"
```

---

### Task 8: Focused Verification

**Files:**
- Modify: no production files in this task.

- [ ] **Step 1: Run focused regression suite**

Run:

```bash
python -m pytest tests/test_episode_projection_cache.py tests/test_media_controller.py tests/test_qt_media_workspace.py tests/test_qt_main_window.py -q
```

Expected: pass.

- [ ] **Step 2: Run diff hygiene check**

Run:

```bash
git diff --check
```

Expected: no output.

- [ ] **Step 3: Commit any final test-only guardrails**

If Task 8 added any test-only guardrails, commit them:

```bash
git add tests/test_episode_projection_cache.py tests/test_media_controller.py tests/test_qt_media_workspace.py tests/test_qt_main_window.py
git commit -m "Add batch projection performance guardrails"
```

If Task 8 did not modify files, skip this commit.

---

## Self-Review Notes

- This plan intentionally does not pre-create Qt widgets during scan. Only pure `EpisodeGuide` projection data is prepared off the interaction path.
- First-click show delay is addressed by having `MediaController.episode_guide_for_state(state)` return a prepared guide before the preview panel renders.
- Season collapse delay and flicker are addressed by hiding/showing existing list items and preserving their attached widgets.
- Switching show matches invalidates old projections because the `show_id`, title/year, preview items, completeness, and scanner metadata can all change.
- Fixing an individual episode match or approving a review episode refreshes the selected state's projection before UI refresh so row status, action buttons, missing rows, unmapped rows, and queue preflight cannot go stale.
- Future missing-file and unmapped-file mapping actions must call the same `refresh_episode_guide(state)` helper after they change ownership.
