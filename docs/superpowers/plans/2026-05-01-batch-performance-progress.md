# Batch Performance And Progress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make TV batch show switching, season toggling, and scan progress feel responsive and trustworthy.

**Architecture:** Keep the first pass inside the existing Qt widget structure, but reduce avoidable work: reuse projected episode-guide data, prevent header toggles from causing detail refresh work, standardize compact row sizing, and emit richer structured scan progress from the controller layer. Deeper model/delegate migration is reserved for a follow-up task after these measured fixes establish the baseline.

**Tech Stack:** Python, PySide6 `QListWidget`, existing controller `ScanProgress`, pytest Qt smoke tests.

---

## File Structure

- Modify `plex_renamer/app/controllers/_tv_batch_helpers.py`: accept richer bulk-scan progress callbacks and pass current show names into `ScanProgress`.
- Modify `plex_renamer/app/controllers/_movie_batch_helpers.py`: pass movie scanner progress into the controller progress model.
- Modify `plex_renamer/app/controllers/media_controller.py`: expose optional movie scanner injection for controller-level progress tests.
- Modify `plex_renamer/engine/_batch_orchestrators.py`: emit before/after progress events around each TV show scan while remaining compatible with two-argument callbacks.
- Modify `plex_renamer/gui_qt/widgets/_media_workspace_preview.py`: cache episode guide projections per state signature and reuse them on collapse/expand/filter repaint.
- Modify `plex_renamer/gui_qt/widgets/_workspace_widgets.py`: make episode guide rows compact, stable-height, and horizontally safe.
- Modify `plex_renamer/gui_qt/widgets/_workspace_widget_primitives.py`: keep `ElidedLabel.text()` semantic while rendering elided display text.
- Modify `tests/test_media_controller.py`: cover TV and movie scan progress.
- Modify `tests/test_qt_media_workspace.py`: cover episode-guide projection reuse, header detail guardrails, and stable compact row behavior.

### Task 1: TV And Movie Progress Payloads

**Files:**
- Modify: `tests/test_media_controller.py`
- Modify: `plex_renamer/engine/_batch_orchestrators.py`
- Modify: `plex_renamer/app/controllers/_tv_batch_helpers.py`
- Modify: `plex_renamer/app/controllers/_movie_batch_helpers.py`
- Modify: `plex_renamer/app/controllers/media_controller.py`

- [ ] **Step 1: Write failing TV progress test**

Add this test to `TVBatchTests` in `tests/test_media_controller.py`:

```python
    def test_scan_all_shows_reports_current_show_before_and_after_scan(self):
        states = [
            ScanState(folder=self.tmp / "ShowA", media_info={"id": 1, "name": "Show A"}),
            ScanState(folder=self.tmp / "ShowB", media_info={"id": 2, "name": "Show B"}),
        ]
        for state in states:
            state.folder.mkdir()

        class _ProgressOrchestrator:
            def __init__(self, scan_states):
                self.states = scan_states

            def scan_all(self, progress_callback=None, cancel_event=None):
                total = len(self.states)
                for index, state in enumerate(self.states):
                    if progress_callback:
                        progress_callback(index, total, state.display_name)
                    state.preview_items = [
                        PreviewItem(
                            original=state.folder / "Episode.mkv",
                            new_name="Episode.mkv",
                            target_dir=state.folder,
                            season=1,
                            episodes=[1],
                            status="OK",
                        )
                    ]
                    state.scanned = True
                    if progress_callback:
                        progress_callback(index + 1, total, state.display_name)

        events: list[ScanProgress] = []
        self.ctrl.add_listener(on_progress=events.append)
        self.set_tv_session(states, batch_orchestrator=_ProgressOrchestrator(states))

        self.ctrl.scan_all_shows()

        _wait_until(
            lambda: self.ctrl.scan_progress.lifecycle == ScanLifecycle.READY,
            description="TV bulk scan to finish",
        )

        scanning_events = [event for event in events if event.lifecycle == ScanLifecycle.SCANNING]
        self.assertTrue(any(event.current_item == "Show A" and event.done == 0 for event in scanning_events))
        self.assertTrue(any(event.current_item == "Show B" and event.done == 1 for event in scanning_events))
        self.assertTrue(any(event.current_item == "Show B" and event.done == 2 for event in scanning_events))
```

- [ ] **Step 2: Write failing movie progress test**

Add this test to `TVBatchTests` in `tests/test_media_controller.py`:

```python
    def test_start_movie_batch_forwards_scanner_progress_to_scan_progress(self):
        root = self.tmp / "movies"
        root.mkdir()
        events: list[ScanProgress] = []
        self.ctrl.add_listener(on_progress=events.append)

        self.ctrl.start_movie_batch(root, _FakeTMDB(), scanner_factory=_SlowMovieBatchScanner)

        _wait_until(
            lambda: any(event.lifecycle == ScanLifecycle.SCANNING and event.done >= 2 for event in events),
            description="movie batch progress events",
        )
        self.ctrl.cancel_scan()

        movie_events = [event for event in events if event.lifecycle == ScanLifecycle.SCANNING]
        self.assertTrue(any(event.phase == "Searching TMDB..." for event in movie_events))
        self.assertTrue(any(event.done == 2 and event.total == 5 for event in movie_events))
```

- [ ] **Step 3: Run tests to verify failure**

Run:

```bash
python -m pytest tests/test_media_controller.py::TVBatchTests::test_scan_all_shows_reports_current_show_before_and_after_scan tests/test_media_controller.py::TVBatchTests::test_start_movie_batch_forwards_scanner_progress_to_scan_progress -q
```

Expected: both tests fail because the current TV scan callback does not accept current item names and movie batch scanning does not pass a progress callback.

- [ ] **Step 4: Implement progress callback compatibility**

In `plex_renamer/engine/_batch_orchestrators.py`, add a local helper near the TV `scan_all()` method:

```python
def _emit_scan_progress(progress_callback, done: int, total: int, current_item: str) -> None:
    if progress_callback is None:
        return
    try:
        progress_callback(done, total, current_item)
    except TypeError:
        progress_callback(done, total)
```

Update TV `scan_all()` to call before and after each show scan:

```python
        for index, state in enumerate(to_scan):
            _raise_if_cancelled(cancel_event)
            _emit_scan_progress(progress_callback, index, total, state.display_name)
            try:
                self.scan_show(state, cancel_event=cancel_event)
            except Exception as error:
                if isinstance(error, ScanCancelledError):
                    raise
                _log.error("Failed to scan %s: %s", state.display_name, error)
            _emit_scan_progress(progress_callback, index + 1, total, state.display_name)
```

In `plex_renamer/app/controllers/_tv_batch_helpers.py`, change `_progress` to accept `current_item`:

```python
    def _progress(done: int, total: int, current_item: str | None = None) -> None:
        if cancel_event.is_set():
            raise ScanCancelledError("Scan cancelled")
        current_name = current_item or _current_batch_scan_name(controller._batch_states, done)
        controller._set_progress(
            ScanLifecycle.SCANNING,
            phase="Scanning episodes...",
            done=done,
            total=total,
            current_item=current_name or None,
            message=f"Scanning episodes... {done}/{total}"
            + (f" - {current_name}" if current_name else ""),
        )
```

In `plex_renamer/app/controllers/_movie_batch_helpers.py`, pass scanner progress:

```python
    def _progress(done: int, total: int, phase: str = "Scanning movies...") -> None:
        if cancel_event.is_set():
            raise ScanCancelledError("Scan cancelled")
        controller._set_progress(
            ScanLifecycle.SCANNING,
            phase=phase or "Scanning movies...",
            done=done,
            total=total,
            message=f"{phase or 'Scanning movies...'} {done}/{total}",
        )
```

Then call:

```python
            items = scanner.scan(progress_callback=_progress, cancel_event=cancel_event)
```

In `plex_renamer/app/controllers/media_controller.py`, allow tests and workflow adapters to inject the scanner without bypassing the public controller method:

```python
    def start_movie_batch(
        self,
        folder: Path,
        tmdb: Any,
        *,
        scanner_factory: Any = MovieScanner,
    ) -> None:
        self._movie_workflow.start_batch(folder, tmdb, scanner_factory=scanner_factory)
```

- [ ] **Step 5: Run tests to verify pass**

Run the same pytest command. Expected: both tests pass.

- [ ] **Step 6: Commit**

```bash
git add tests/test_media_controller.py plex_renamer/engine/_batch_orchestrators.py plex_renamer/app/controllers/_tv_batch_helpers.py plex_renamer/app/controllers/_movie_batch_helpers.py
git commit -m "Improve batch scan progress updates"
```

### Task 2: Episode Guide Projection Cache

**Files:**
- Modify: `tests/test_qt_media_workspace.py`
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_preview.py`

- [ ] **Step 1: Write failing projection reuse test**

Add this test near the existing episode-guide tests in `tests/test_qt_media_workspace.py`:

```python
    def test_media_workspace_episode_guide_reuses_projection_when_toggling_headers(self):
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
        workspace = MediaWorkspace(media_type="tv", media_controller=_FakeMediaController(state))
        workspace.show_ready()
        original_builder = workspace._preview_panel._episode_mapping.build_episode_guide
        workspace._preview_panel._episode_mapping.build_episode_guide = MagicMock(wraps=original_builder)

        workspace._populate_preview(state)
        header = next(
            workspace._preview_list.item(row)
            for row in range(workspace._preview_list.count())
            if workspace._preview_list.item(row).data(_PREVIEW_ENTRY_KIND_ROLE) == "header"
        )
        workspace._on_preview_item_clicked(header)
        workspace._on_preview_item_clicked(header)

        self.assertEqual(workspace._preview_panel._episode_mapping.build_episode_guide.call_count, 1)
        workspace.close()
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
python -m pytest tests/test_qt_media_workspace.py::QtMediaWorkspaceTests::test_media_workspace_episode_guide_reuses_projection_when_toggling_headers -q
```

Expected: fails because `build_episode_guide()` is called for every repaint.

- [ ] **Step 3: Implement projection cache**

In `MediaWorkspacePreviewPanel.__init__`, add:

```python
        self._episode_guide_cache: dict[str, tuple[tuple, object]] = {}
```

Add helpers:

```python
    def _episode_guide_for_state(self, state: ScanState):
        key = _state_key(state)
        signature = self._episode_guide_signature(state)
        cached = self._episode_guide_cache.get(key)
        if cached is not None and cached[0] == signature:
            return cached[1]
        guide = self._episode_mapping.build_episode_guide(state)
        self._episode_guide_cache[key] = (signature, guide)
        return guide

    @staticmethod
    def _episode_guide_signature(state: ScanState) -> tuple:
        preview_signature = tuple(
            (
                str(preview.original),
                preview.new_name,
                str(preview.target_dir) if preview.target_dir is not None else "",
                preview.season,
                tuple(preview.episodes),
                preview.status,
                round(preview.episode_confidence, 4),
                tuple((str(companion.original), companion.new_name, companion.file_type) for companion in preview.companions),
            )
            for preview in state.preview_items
        )
        completeness = state.completeness
        completeness_signature = None
        if completeness is not None:
            completeness_signature = (
                tuple(
                    (season_num, season.expected, season.matched, tuple(season.missing), tuple(season.matched_episodes))
                    for season_num, season in sorted(completeness.seasons.items())
                ),
                None if completeness.specials is None else (
                    completeness.specials.expected,
                    completeness.specials.matched,
                    tuple(completeness.specials.missing),
                    tuple(completeness.specials.matched_episodes),
                ),
                completeness.total_expected,
                completeness.total_matched,
                tuple(completeness.total_missing),
            )
        return (
            state.active_episode_source,
            tuple(sorted(state.season_names.items())),
            preview_signature,
            completeness_signature,
            tuple((str(companion.original), companion.new_name, companion.file_type) for companion in state.orphan_companion_files),
        )
```

Change `_populate_episode_guide()`:

```python
        guide = self._episode_guide_for_state(state)
```

- [ ] **Step 4: Run test to verify pass**

Run the same pytest command. Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_qt_media_workspace.py plex_renamer/gui_qt/widgets/_media_workspace_preview.py
git commit -m "Cache episode guide projections"
```

### Task 3: Stable Compact Episode Rows

**Files:**
- Modify: `tests/test_qt_media_workspace.py`
- Modify: `plex_renamer/gui_qt/widgets/_workspace_widgets.py`
- Modify: `plex_renamer/gui_qt/widgets/_workspace_widget_primitives.py`

- [ ] **Step 1: Write failing row stability test**

Add this test near `test_media_workspace_episode_review_actions_are_inline_with_confidence_meter`:

```python
    def test_media_workspace_episode_guide_rows_have_stable_compact_height(self):
        from plex_renamer.gui_qt.widgets._workspace_widgets import EpisodeGuideRowWidget

        short_row = EpisodeGuideRowWidget(title="S01E01 - Pilot", status="Mapped", original="Pilot.mkv")
        missing_row = EpisodeGuideRowWidget(title="S01E02 - Missing", status="Missing File")
        long_row = EpisodeGuideRowWidget(
            title="S01E03 - This Is A Very Long Episode Title That Should Not Expand The Row Horizontally",
            status="Review",
            original="Example.Show.S01E03.With.A.Long.Release.Name.mkv",
            target="Example Show (2024) - S01E03 - This Is A Very Long Episode Title That Should Not Expand The Row Horizontally.mkv",
            confidence="52%",
        )

        heights = {short_row.sizeHint().height(), missing_row.sizeHint().height(), long_row.sizeHint().height()}
        self.assertEqual(len(heights), 1)
        self.assertLessEqual(next(iter(heights)), 76)

        short_row.close()
        missing_row.close()
        long_row.close()
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
python -m pytest tests/test_qt_media_workspace.py::QtMediaWorkspaceTests::test_media_workspace_episode_guide_rows_have_stable_compact_height -q
```

Expected: fails because long and missing rows size differently.

- [ ] **Step 3: Implement stable row sizing**

In `EpisodeGuideRowWidget`, replace long wrapped title/original/target labels with `ElidedLabel` where horizontal content can grow. Set a fixed row height:

```python
        self.setFixedHeight(68)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
```

Use `ElidedLabel` for title, original, target, and companions:

```python
        self._title = ElidedLabel(title, elide_mode=Qt.TextElideMode.ElideRight, parent=self)
        self._original = ElidedLabel(original, elide_mode=Qt.TextElideMode.ElideMiddle, parent=self)
        self._target = ElidedLabel(f"-> {target}" if target else "", elide_mode=Qt.TextElideMode.ElideMiddle, parent=self)
```

Keep the status pill visible and uncompressed:

```python
        self._status.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
```

Keep compatibility with tests and callers that inspect label text by making `ElidedLabel.text()` return its full source text while the QLabel display text remains elided internally.

- [ ] **Step 4: Run test to verify pass**

Run the same pytest command. Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_qt_media_workspace.py plex_renamer/gui_qt/widgets/_workspace_widgets.py
git commit -m "Stabilize episode guide row height"
```

### Task 4: Performance Verification Guardrail

**Files:**
- Modify: `tests/test_qt_media_workspace.py`

- [ ] **Step 1: Add regression test for header toggle preserving detail selection**

Add this test:

```python
    def test_media_workspace_episode_header_toggle_does_not_reload_detail_selection(self):
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
        workspace = MediaWorkspace(media_type="tv", media_controller=_FakeMediaController(state))
        workspace.show_ready()
        workspace._detail_panel.set_selection = MagicMock(wraps=workspace._detail_panel.set_selection)
        header = next(
            workspace._preview_list.item(row)
            for row in range(workspace._preview_list.count())
            if workspace._preview_list.item(row).data(_PREVIEW_ENTRY_KIND_ROLE) == "header"
        )

        workspace._on_preview_item_clicked(header)

        workspace._detail_panel.set_selection.assert_not_called()
        workspace.close()
```

- [ ] **Step 2: Run test**

Run:

```bash
python -m pytest tests/test_qt_media_workspace.py::QtMediaWorkspaceTests::test_media_workspace_episode_header_toggle_does_not_reload_detail_selection -q
```

Expected: pass once header toggles stay inside preview repaint logic only.

- [ ] **Step 3: Run focused suite**

Run:

```bash
python -m pytest tests/test_media_controller.py tests/test_qt_media_workspace.py -q
```

Expected: pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_qt_media_workspace.py
git commit -m "Guard episode header repaint behavior"
```
