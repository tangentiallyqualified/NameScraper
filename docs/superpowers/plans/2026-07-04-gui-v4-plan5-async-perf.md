# GUI V4 Plan 5: Async Guide Build + BusyOverlay + Perf Guards — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Episode-guide builds move off the GUI thread (skeleton rows shown until the guide arrives, generation-token staleness protection), a reusable BusyOverlay + `busy_scope()` covers the remaining GUI-thread blockers (bulk apply, unassign-all, queue, tab-restore), the season strip stops rebuilding its buttons on every action-bar sync (Plan 3's deferred M2), and permanent perf guards pin all of it.

**Architecture:** The existing `EpisodeProjectionCacheService` stays the single guide authority and gains Qt-free peek/build/store primitives. `EpisodeTableModel` (already the only render surface) gains an async path copied from the work panel's proven overview pattern: a bridge `QObject` + signal, workers on `plex_renamer.thread_pool.submit`, a per-model generation token that drops stale results. `BusyOverlay` is a new self-contained widget with a context manager; wiring sites wrap existing synchronous blocks without changing their behavior.

**Tech Stack:** PySide6 (QWidget painting, Signals, QTimer), `plex_renamer.thread_pool` (`ThreadPoolExecutor`, thread prefix "PlexWorker"), pytest + `QtSmokeBase` (`tests/conftest_qt.py`).

## Global Constraints

- Spec is `docs/superpowers/specs/2026-07-03-gui-v4-design.md` §7. Budget (reference machine): switching to a 300-episode show renders < 100ms; no interaction may block the event loop > 200ms without the overlay visible. Offscreen CI guards use documented margins (Task 6), not the raw budget.
- No hex color literals outside `gui_qt/theme.py` (existing guard test). Painted colors come from `theme.color(<token>)`; verified token names used in this plan: `"bg"`, `"surface"`, `"accent"`, `"text_dim"`. Inline `setStyleSheet(f"color: {theme.color(...)};")` is the established idiom for one-off label colors (see `job_detail_panel.py:408`).
- No "Plex" string literals in `gui_qt` (existing AST guard). User-facing name is "NameScraper".
- No `QApplication.processEvents()` and no `time.sleep()` anywhere under `plex_renamer/gui_qt/` — currently true; Task 6 adds the permanent guard. Tests may use `processEvents` freely.
- All background work in `gui_qt` goes through `from ...thread_pool import submit as _submit_bg` (never raw `threading.Thread`).
- All pixel sizing through `gui_qt/_scale.py` (`_scale.px(...)`).
- Reusable tests use `tmp_path`/synthetic fixtures — never `P:\` media paths.
- New Qt test files must be registered in BOTH runner lists: added to the smoke include list in `scripts/test_smoke_runner.py` (near line 84) and to the fast-suite `--ignore=` list in `scripts/test_fast_runner.py` (near line 84).
- Suites must pass with zero skips: `scripts\test-fast.cmd` and `scripts\test-smoke.cmd` (use `.venv\Scripts\python.exe` for direct pytest runs).
- Commit after every task with the repo's conventional style (`feat(gui): …` / `fix(gui): …` / `test: …`).

## Context (verified against the landed code, 2026-07-04)

- Guide pipeline today: `EpisodeTableModel.show_state` (TV branch, `_episode_table_model.py:154`) synchronously pulls `self._guide_for_state(state)` inside a model reset; `_guide_for_state` (`:300-305`) uses the injected `guide_provider` (production: `media_controller.episode_guide_for_state` → `EpisodeProjectionCacheService.guide_for_state`, which **builds on miss**) or falls back to a raw `EpisodeMappingService().build_episode_guide(state)`. `_rebuild` (`:296`) re-pulls the same way when `self._guide is None`.
- Async precedent to copy: `_work_panel.py` overview fetch (`_request_overview` → worker via `_submit_bg` → `self._bridge.overview_ready.emit(text, token)` guarded by `try/except RuntimeError` → GUI slot checks token, drops stale). `_roster_model.py` does the same for posters.
- `EpisodeProjectionCacheService` (`app/services/episode_projection_cache.py`): dict cache keyed `folder|show_id|source`, deep tuple `signature_for_state(state)` for staleness. `prepare_episode_guides([state])` is called per state post-scan (`_tv_batch_helpers.py:324`) — the only warm path; spec §7's `warm_preview_cache`/`processEvents` deletions already landed in Plan 3 (repo-wide grep is clean).
- Season strip churn (Plan 3's deferred M2): `update_action_bar` (`_media_workspace_action_bar.py:31`) calls `panel.refresh_header(state)` on every action-bar sync; `refresh_header` (`_work_panel.py:419`) unconditionally calls `_refresh_strip` (`:519`), which `_clear_strip()`s and rebuilds every `QPushButton` from `season_strip_specs(state.completeness)`.
- Overlay wiring sites that exist today: bulk apply (`MediaWorkspaceActionCoordinator.apply_bulk_assignments`, `_media_workspace_actions.py`), unassign-all (`unassign_all_episode_mappings`, same file — it is the sibling bulk apply), queueing (`queue_states`, `_media_workspace_queue_actions.py:97` — shared by inline queue and Queue-N-Checked), tab-restore (`window.media_ctrl.restore_tv_from_tab_switch` / `restore_movie_from_tab_switch`, `_main_window_state.py:129/136`). **Spec deviation, recorded:** spec §7 also names "force rescan" — no such surface exists in today's code (scans run behind the scanning page with their own progress UI); wire it if/when a rescan command appears.
- Bulk-assign boundary (Plan 4, review-pinned): bulk mode pins `_bulk_state`; populate-with-different-state discards. Nothing in this plan may change that seam — the async guide delivery happens **below** it (model-internal) and never populates the work panel.
- Entry system: `_Entry(kind, section_key, text, preview_index, guide_row, row_data, collapsible=False)` + frozen `EpisodeRowData(kind, title, …)` (`_episode_table_model.py:44-68`). Non-selectable kinds set at `:104`. Delegate (`_episode_table_delegate.py`) branches on `row_data.kind`, unit constants `_ROW_SINGLE_U = 34` etc., tones via `_TONE_COLOR`.
- Model ctor (`:72-79`) takes keyword-only `media_type, settings_service, guide_provider, parent`. `MediaWorkPanel` ctor (`_work_panel.py:72`) mirrors and forwards to the model (`:295`); the workspace wires providers in `_media_workspace_ui.py:_build_work_panel` (`:89-101`) with `hasattr` guards.
- Post-mutation refresh paths (`_refresh_episode_projection` in `_media_workspace_actions.py:47-48`, match actions) call `media_ctrl.refresh_episode_guide(state)` **synchronously and stay synchronous in this plan**: the mutating interaction is exactly what the BusyOverlay covers, the reprojection that dominates the cost already ran, and a skeleton flash after every approve would be a regression. The async path applies to guide builds triggered by *displaying* a state whose guide is not cached.

## File Structure

- Create: `plex_renamer/gui_qt/widgets/busy_overlay.py` — `Spinner`, `BusyOverlay`, `busy_scope()` (Plan 6's loading screen will reuse `Spinner`).
- Modify: `plex_renamer/app/services/episode_projection_cache.py` — `cached_guide_for_state`, `build_guide_with_signature`, `store_guide`.
- Modify: `plex_renamer/app/controllers/media_controller.py` — three passthroughs.
- Modify: `plex_renamer/gui_qt/widgets/_episode_table_model.py` — skeleton entries, `_GuideBridge`, token scheduling, `guide_loaded` signal.
- Modify: `plex_renamer/gui_qt/widgets/_episode_table_delegate.py` — skeleton paint + size.
- Modify: `plex_renamer/gui_qt/widgets/_work_panel.py` — provider passthrough, `guide_loaded` → footer/toolbar refresh, strip no-churn key.
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_ui.py` — wire the three provider callables.
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_actions.py`, `_media_workspace_queue_actions.py`, `plex_renamer/gui_qt/_main_window_state.py` — `busy_scope` wiring.
- Create tests: `tests/test_qt_busy_overlay.py`, `tests/test_qt_async_guide.py`, `tests/test_qt_perf_guards.py` (smoke; register in both runner lists), `tests/test_gui_perf_guards.py` (fast source sweep). Extend: `tests/test_episode_projection_cache.py`, `tests/test_work_panel.py`.

---

### Task 1: BusyOverlay widget + `busy_scope()`

**Files:**
- Create: `plex_renamer/gui_qt/widgets/busy_overlay.py`
- Create: `tests/test_qt_busy_overlay.py`
- Modify: `scripts/test_smoke_runner.py` (include list, near line 84), `scripts/test_fast_runner.py` (`--ignore=` list, near line 84)

**Interfaces:**
- Consumes: `gui_qt/theme.py` `theme.color(name)`; `gui_qt/_scale.py` `_scale.px(units)`.
- Produces: `Spinner(parent=None)` (fixed-size rotating accent arc); `BusyOverlay(target: QWidget, text: str)` with `show_now()`, `show_after(delay_ms: int)`, `dismiss()`; `busy_scope(target, text="Working…", *, delay_ms=120, immediate=False)` context manager yielding the overlay. Task 5 imports `busy_scope`; tests find overlays via `findChild(BusyOverlay)` (so `dismiss()` must `setParent(None)`, not just hide).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_qt_busy_overlay.py
"""BusyOverlay + busy_scope behavior (GUI V4 Plan 5, spec §7)."""
from conftest_qt import QtSmokeBase


class BusyOverlayTests(QtSmokeBase):
    def _host(self):
        from PySide6.QtWidgets import QWidget

        host = QWidget()
        host.resize(400, 300)
        host.show()
        self.addCleanup(host.close)
        return host

    def test_immediate_scope_shows_covering_host_and_removes(self):
        from plex_renamer.gui_qt.widgets.busy_overlay import BusyOverlay, busy_scope

        host = self._host()
        with busy_scope(host, "Applying…", immediate=True) as overlay:
            self.assertTrue(overlay.isVisible())
            self.assertEqual(overlay.geometry(), host.rect())
            self.assertEqual(overlay._label.text(), "Applying…")
        self.assertIsNone(host.findChild(BusyOverlay))

    def test_deferred_scope_stays_hidden_before_delay(self):
        from plex_renamer.gui_qt.widgets.busy_overlay import BusyOverlay, busy_scope

        host = self._host()
        with busy_scope(host, delay_ms=60_000) as overlay:
            self._app.processEvents()
            self.assertFalse(overlay.isVisible())
        self.assertIsNone(host.findChild(BusyOverlay))

    def test_deferred_scope_shows_once_delay_elapses(self):
        from PySide6.QtTest import QTest

        from plex_renamer.gui_qt.widgets.busy_overlay import busy_scope

        host = self._host()
        with busy_scope(host, delay_ms=1) as overlay:
            QTest.qWait(50)
            self.assertTrue(overlay.isVisible())

    def test_exception_inside_scope_still_removes_overlay(self):
        from plex_renamer.gui_qt.widgets.busy_overlay import BusyOverlay, busy_scope

        host = self._host()
        with self.assertRaises(RuntimeError):
            with busy_scope(host, immediate=True):
                raise RuntimeError("boom")
        self.assertIsNone(host.findChild(BusyOverlay))

    def test_overlay_tracks_host_resize(self):
        from plex_renamer.gui_qt.widgets.busy_overlay import busy_scope

        host = self._host()
        with busy_scope(host, immediate=True) as overlay:
            host.resize(620, 480)
            self._app.processEvents()
            self.assertEqual(overlay.geometry(), host.rect())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests\test_qt_busy_overlay.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'plex_renamer.gui_qt.widgets.busy_overlay'`

- [ ] **Step 3: Implement the widget**

```python
# plex_renamer/gui_qt/widgets/busy_overlay.py
"""BusyOverlay: translucent scrim + spinner + label over any panel (spec §7).

``busy_scope()`` guarantees removal via ``finally`` — a stuck overlay is
impossible by construction.  ``immediate=True`` is for GUI-thread operations
that block the event loop: the overlay is shown and painted synchronously up
front (a deferred QTimer show can never fire while the loop is blocked).  The
default deferred mode is for waits where the loop stays alive (off-thread
work): the overlay appears only if the wait exceeds ``delay_ms``.
"""
from __future__ import annotations

from contextlib import contextmanager

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from .. import _scale, theme

_DEFAULT_SHOW_DELAY_MS = 120
_SPINNER_DIAMETER_U = 32
_SPINNER_STEP_DEGREES = 8
_SPINNER_INTERVAL_MS = 16
_SPINNER_SPAN_DEGREES = 100
_SCRIM_ALPHA = 170


class Spinner(QWidget):
    """Rotating accent arc.  Plan 6's loading screen reuses this widget."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._angle = 0
        size = _scale.px(_SPINNER_DIAMETER_U)
        self.setFixedSize(size, size)
        self._timer = QTimer(self)
        self._timer.setInterval(_SPINNER_INTERVAL_MS)
        self._timer.timeout.connect(self._advance)

    def showEvent(self, event) -> None:
        self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def _advance(self) -> None:
        self._angle = (self._angle + _SPINNER_STEP_DEGREES) % 360
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = painter.pen()
        pen_width = max(2, _scale.px(3))
        pen.setWidth(pen_width)
        pen.setColor(QColor(theme.color("accent")))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        inset = pen_width // 2 + 1
        arc_rect = self.rect().adjusted(inset, inset, -inset, -inset)
        # drawArc takes 1/16th-degree units.
        painter.drawArc(arc_rect, -self._angle * 16, -_SPINNER_SPAN_DEGREES * 16)


class BusyOverlay(QWidget):
    def __init__(self, target: QWidget, text: str) -> None:
        super().__init__(target)
        self._target = target
        self._show_timer: QTimer | None = None
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(_scale.px(8))
        self._spinner = Spinner(self)
        layout.addWidget(self._spinner, alignment=Qt.AlignmentFlag.AlignHCenter)
        self._label = QLabel(text, self)
        self._label.setStyleSheet(f"color: {theme.color('text_dim')};")
        layout.addWidget(self._label, alignment=Qt.AlignmentFlag.AlignHCenter)
        target.installEventFilter(self)
        self.hide()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._target and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self.setGeometry(self._target.rect())
        return False

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        scrim = QColor(theme.color("bg"))
        scrim.setAlpha(_SCRIM_ALPHA)
        painter.fillRect(self.rect(), scrim)

    def show_now(self) -> None:
        self._cancel_timer()
        self.setGeometry(self._target.rect())
        self.show()
        self.raise_()
        # One synchronous paint so work that blocks the event loop right
        # after this call still gets a visible overlay.
        self.repaint()

    def show_after(self, delay_ms: int) -> None:
        self._cancel_timer()
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(max(0, delay_ms))
        timer.timeout.connect(self.show_now)
        self._show_timer = timer
        timer.start()

    def dismiss(self) -> None:
        self._cancel_timer()
        self._target.removeEventFilter(self)
        self.hide()
        self.setParent(None)
        self.deleteLater()

    def _cancel_timer(self) -> None:
        if self._show_timer is not None:
            self._show_timer.stop()
            self._show_timer = None


@contextmanager
def busy_scope(
    target: QWidget,
    text: str = "Working…",
    *,
    delay_ms: int = _DEFAULT_SHOW_DELAY_MS,
    immediate: bool = False,
):
    overlay = BusyOverlay(target, text)
    try:
        if immediate:
            overlay.show_now()
        else:
            overlay.show_after(delay_ms)
        yield overlay
    finally:
        overlay.dismiss()
```

- [ ] **Step 4: Register the new Qt test file in both runners**

In `scripts/test_smoke_runner.py`, add `"tests/test_qt_busy_overlay.py",` to the include list (alphabetical position within the existing entries near line 84). In `scripts/test_fast_runner.py`, add `"--ignore=tests/test_qt_busy_overlay.py",` beside the existing ignores.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests\test_qt_busy_overlay.py -q`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add plex_renamer/gui_qt/widgets/busy_overlay.py tests/test_qt_busy_overlay.py scripts/test_smoke_runner.py scripts/test_fast_runner.py
git commit -m "feat(gui): BusyOverlay + busy_scope - deferred/immediate scrim with guaranteed removal"
```

---

### Task 2: Cache peek/build/store primitives + controller passthroughs

**Files:**
- Modify: `plex_renamer/app/services/episode_projection_cache.py`
- Modify: `plex_renamer/app/controllers/media_controller.py` (after `episode_guide_for_state`, line ~519)
- Test: `tests/test_episode_projection_cache.py` (extend; fast suite)

**Interfaces:**
- Consumes: existing `signature_for_state(state)`, `_key_for_state(state)`, `EpisodeMappingService.build_episode_guide(state)`.
- Produces (service): `cached_guide_for_state(state) -> EpisodeGuide | None` (never builds), `build_guide_with_signature(state) -> tuple[EpisodeGuide, tuple]` (signature computed **before** the build so a concurrent mutation degrades to a stale-miss, never a wrong-hit), `store_guide(state, guide, signature) -> None`.
- Produces (controller): `cached_episode_guide_for_state(state)`, `build_episode_guide_snapshot(state)`, `store_episode_guide(state, guide, signature)` — Task 3's workspace wiring consumes these exact names.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_episode_projection_cache.py`, following its existing import style)

```python
class CachedPeekAndStoreTests(unittest.TestCase):
    """Plan 5: Qt-free primitives backing the async guide pipeline."""

    def _state(self, name: str = "Show") -> "ScanState":
        from pathlib import Path

        from plex_renamer.engine import ScanState

        state = ScanState(
            folder=Path(f"C:/library/tv/{name}"),
            media_info={"id": 5, "name": name, "year": "2024"},
        )
        state.scanned = True
        return state

    def test_cached_guide_for_state_returns_none_when_unbuilt(self):
        from plex_renamer.app.services.episode_projection_cache import (
            EpisodeProjectionCacheService,
        )

        service = EpisodeProjectionCacheService()
        self.assertIsNone(service.cached_guide_for_state(self._state()))

    def test_cached_guide_for_state_hits_after_prepare_and_misses_after_mutation(self):
        from plex_renamer.app.services.episode_projection_cache import (
            EpisodeProjectionCacheService,
        )

        service = EpisodeProjectionCacheService()
        state = self._state()
        built = service.prepare_state(state)
        self.assertIs(service.cached_guide_for_state(state), built)
        state.media_info["name"] = "Renamed Show"   # signature-relevant mutation
        self.assertIsNone(service.cached_guide_for_state(state))

    def test_build_guide_with_signature_matches_prebuild_signature(self):
        from plex_renamer.app.services.episode_projection_cache import (
            EpisodeProjectionCacheService,
        )

        service = EpisodeProjectionCacheService()
        state = self._state()
        expected_signature = service.signature_for_state(state)
        guide, signature = service.build_guide_with_signature(state)
        self.assertEqual(signature, expected_signature)
        self.assertIsNotNone(guide)

    def test_store_guide_roundtrips_through_cached_peek(self):
        from plex_renamer.app.services.episode_projection_cache import (
            EpisodeProjectionCacheService,
        )

        service = EpisodeProjectionCacheService()
        state = self._state()
        guide, signature = service.build_guide_with_signature(state)
        service.store_guide(state, guide, signature)
        self.assertIs(service.cached_guide_for_state(state), guide)
        self.assertEqual(service.cache_size, 1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests\test_episode_projection_cache.py -q -k CachedPeekAndStore`
Expected: FAIL — `AttributeError: ... has no attribute 'cached_guide_for_state'`

- [ ] **Step 3: Implement the service primitives** (insert between `guide_for_state` and `refresh_state`)

```python
    def cached_guide_for_state(self, state: ScanState) -> EpisodeGuide | None:
        """Signature-checked peek: return the cached guide or None. Never builds."""
        cached = self._cache.get(self._key_for_state(state))
        if cached is not None and cached.signature == self.signature_for_state(state):
            return cached.guide
        return None

    def build_guide_with_signature(self, state: ScanState) -> tuple[EpisodeGuide, tuple]:
        """Build a guide plus the signature captured BEFORE the build.

        Safe to call off the GUI thread: pure reads over the state. If the
        state mutates mid-build, the pre-build signature no longer matches on
        the next peek, so the stored result degrades to a cache miss instead
        of a wrong hit.
        """
        signature = self.signature_for_state(state)
        return self._episode_mapping.build_episode_guide(state), signature

    def store_guide(self, state: ScanState, guide: EpisodeGuide, signature: tuple) -> None:
        self._cache[self._key_for_state(state)] = _CachedEpisodeGuide(signature, guide)
```

- [ ] **Step 4: Implement the controller passthroughs** (in `media_controller.py`, directly after `episode_guide_for_state`)

```python
    def cached_episode_guide_for_state(self, state: ScanState) -> EpisodeGuide | None:
        return self._episode_projection_cache.cached_guide_for_state(state)

    def build_episode_guide_snapshot(self, state: ScanState) -> tuple[EpisodeGuide, tuple]:
        return self._episode_projection_cache.build_guide_with_signature(state)

    def store_episode_guide(
        self, state: ScanState, guide: EpisodeGuide, signature: tuple
    ) -> None:
        self._episode_projection_cache.store_guide(state, guide, signature)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests\test_episode_projection_cache.py -q`
Expected: all pass (existing + 4 new)

- [ ] **Step 6: Commit**

```bash
git add plex_renamer/app/services/episode_projection_cache.py plex_renamer/app/controllers/media_controller.py tests/test_episode_projection_cache.py
git commit -m "feat(services): cache peek/build-with-signature/store primitives for async guide builds"
```

---

### Task 3: Async guide pipeline — skeleton rows, generation token, delivery

**Files:**
- Modify: `plex_renamer/gui_qt/widgets/_episode_table_model.py`
- Modify: `plex_renamer/gui_qt/widgets/_episode_table_delegate.py`
- Modify: `plex_renamer/gui_qt/widgets/_work_panel.py` (ctor params ~line 72, model construction ~line 295)
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_ui.py` (`_build_work_panel`, lines 89-101)
- Create: `tests/test_qt_async_guide.py`
- Modify: `scripts/test_smoke_runner.py` + `scripts/test_fast_runner.py` (register the new Qt test file, same as Task 1 Step 4)

**Interfaces:**
- Consumes: Task 2's controller methods `cached_episode_guide_for_state` / `build_episode_guide_snapshot` / `store_episode_guide`; `from ...thread_pool import submit as _submit_bg`.
- Produces (model): ctor kwargs `cached_guide_provider=None, guide_builder=None, guide_store=None`; class signal `guide_loaded = Signal()`; entry kind `"skeleton"`. Async engages ONLY when both `cached_guide_provider` and `guide_builder` are wired; otherwise the existing synchronous `_guide_for_state` path runs unchanged (keeps every existing bare-panel test green).
- Produces (panel): `MediaWorkPanel` ctor kwargs with the same three names, forwarded to the model; on `guide_loaded` the panel refreshes footer + toolbar.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_qt_async_guide.py
"""Async episode-guide pipeline: skeleton rows, token staleness, delivery (Plan 5)."""
from pathlib import Path
from unittest.mock import patch

from conftest_qt import QtSmokeBase


def _table_state(folder_name: str, *, episodes: int = 4, media_id: int = 101):
    from plex_renamer.app.services.episode_mapping_service import EpisodeMappingService
    from plex_renamer.engine import ScanState
    from plex_renamer.engine.episode_assignments import (
        ORIGIN_MANUAL,
        EpisodeAssignmentTable,
        EpisodeSlot,
    )

    table = EpisodeAssignmentTable()
    for episode in range(1, episodes + 1):
        table.add_slot(EpisodeSlot(season=1, episode=episode, title=f"Ep {episode}"))
    for episode in range(1, episodes + 1):
        entry = table.add_file(Path(f"C:/library/tv/{folder_name}/e{episode:02d}.mkv"))
        table.assign(entry.file_id, 1, [episode], origin=ORIGIN_MANUAL)
    state = ScanState(
        folder=Path(f"C:/library/tv/{folder_name}"),
        media_info={"id": media_id, "name": folder_name, "year": "2024"},
    )
    state.scanned = True
    state.confidence = 1.0
    state.assignments = table
    EpisodeMappingService().reproject(state)
    return state


class AsyncGuideModelTests(QtSmokeBase):
    """Deterministic scheduling: _submit_bg patched to capture workers."""

    def setUp(self):
        super().setUp()
        from plex_renamer.app.services.episode_projection_cache import (
            EpisodeProjectionCacheService,
        )
        from plex_renamer.gui_qt.widgets._episode_table_model import EpisodeTableModel

        self.cache = EpisodeProjectionCacheService()
        self.build_calls: list = []
        self.pending: list = []

        def counting_builder(state):
            self.build_calls.append(state)
            return self.cache.build_guide_with_signature(state)

        self._submit_patch = patch(
            "plex_renamer.gui_qt.widgets._episode_table_model._submit_bg",
            side_effect=self.pending.append,
        )
        self._submit_patch.start()
        self.addCleanup(self._submit_patch.stop)
        self.model = EpisodeTableModel(
            media_type="tv",
            cached_guide_provider=self.cache.cached_guide_for_state,
            guide_builder=counting_builder,
            guide_store=self.cache.store_guide,
        )

    def _kinds(self):
        return [entry.kind for entry in self.model._entries]

    def test_uncached_state_shows_skeleton_without_sync_build(self):
        state = _table_state("Show A")
        self.model.show_state(state, collapsed_sections=set())
        self.assertEqual(self.build_calls, [])          # nothing built on the GUI thread
        self.assertEqual(len(self.pending), 1)          # one worker scheduled
        kinds = set(self._kinds())
        self.assertIn("skeleton", kinds)
        self.assertNotIn("episode", kinds)

    def test_delivery_fills_table_stores_guide_and_emits_guide_loaded(self):
        state = _table_state("Show A")
        loaded: list[bool] = []
        self.model.guide_loaded.connect(lambda: loaded.append(True))
        self.model.show_state(state, collapsed_sections=set())
        self.pending.pop()()                            # run the captured worker
        self._app.processEvents()                       # deliver the bridge signal
        self.assertEqual(len(self.build_calls), 1)
        self.assertIn("episode", set(self._kinds()))
        self.assertNotIn("skeleton", set(self._kinds()))
        self.assertEqual(loaded, [True])
        self.assertIsNotNone(self.cache.cached_guide_for_state(state))

    def test_stale_delivery_is_dropped_after_state_switch(self):
        state_a = _table_state("Show A")
        state_b = _table_state("Show B", media_id=102)
        self.model.show_state(state_a, collapsed_sections=set())
        worker_a = self.pending.pop()
        self.model.show_state(state_b, collapsed_sections=set())
        worker_b = self.pending.pop()
        worker_a()                                      # stale: token moved on
        self._app.processEvents()
        self.assertIn("skeleton", set(self._kinds()))   # B still loading, A dropped
        self.assertIsNone(self.cache.cached_guide_for_state(state_a))
        worker_b()
        self._app.processEvents()
        self.assertIs(self.model.state(), state_b)
        self.assertIn("episode", set(self._kinds()))

    def test_cached_state_renders_synchronously_without_scheduling(self):
        state = _table_state("Show A")
        self.cache.prepare_state(state)
        self.model.show_state(state, collapsed_sections=set())
        self.assertEqual(self.pending, [])
        self.assertEqual(self.build_calls, [])
        self.assertIn("episode", set(self._kinds()))


class AsyncGuideRealThreadTest(QtSmokeBase):
    """One unpatched end-to-end pass over the real thread pool."""

    def test_guide_arrives_via_real_pool(self):
        from PySide6.QtTest import QTest

        from plex_renamer.app.services.episode_projection_cache import (
            EpisodeProjectionCacheService,
        )
        from plex_renamer.gui_qt.widgets._episode_table_model import EpisodeTableModel

        cache = EpisodeProjectionCacheService()
        model = EpisodeTableModel(
            media_type="tv",
            cached_guide_provider=cache.cached_guide_for_state,
            guide_builder=cache.build_guide_with_signature,
            guide_store=cache.store_guide,
        )
        loaded: list[bool] = []
        model.guide_loaded.connect(lambda: loaded.append(True))
        model.show_state(_table_state("Real Show"), collapsed_sections=set())
        for _ in range(200):                            # ≤ 10s hard cap
            if loaded:
                break
            QTest.qWait(50)
        self.assertEqual(loaded, [True])
        self.assertIn("episode", {entry.kind for entry in model._entries})
```

- [ ] **Step 2: Register the test file + run to verify failure**

Register `tests/test_qt_async_guide.py` in both runner lists (as Task 1 Step 4).
Run: `.venv\Scripts\python.exe -m pytest tests\test_qt_async_guide.py -q`
Expected: FAIL — `TypeError: EpisodeTableModel.__init__() got an unexpected keyword argument 'cached_guide_provider'`

- [ ] **Step 3: Implement the model pipeline** (`_episode_table_model.py`)

Add imports at the top (beside the existing ones):

```python
import logging

from PySide6.QtCore import QAbstractListModel, QModelIndex, QObject, Qt, Signal

from ...thread_pool import submit as _submit_bg
```

(`QAbstractListModel/QModelIndex/Qt` are already imported — extend that line with `QObject, Signal`.) Add module logger and skeleton constants after the role constants:

```python
_log = logging.getLogger(__name__)

_SKELETON_MIN_ROWS, _SKELETON_MAX_ROWS = 6, 20


class _GuideBridge(QObject):
    """Worker → GUI-thread hop for built guides (mirrors the overview bridge)."""

    guide_ready = Signal(object, object, object, int)   # state, guide, signature, token
```

Extend the ctor (keyword-only params after `guide_provider`) and give the model its signal:

```python
class EpisodeTableModel(QAbstractListModel):
    guide_loaded = Signal()

    def __init__(
        self,
        *,
        media_type: str,
        settings_service=None,
        guide_provider=None,
        cached_guide_provider=None,
        guide_builder=None,
        guide_store=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        ...existing assignments...
        self._cached_guide_provider = cached_guide_provider
        self._guide_builder = guide_builder
        self._guide_store = guide_store
        self._guide_token = 0
        self._guide_bridge = _GuideBridge(self)
        self._guide_bridge.guide_ready.connect(self._on_guide_ready)
```

Replace the TV branch of `show_state` (currently lines 153-155, `self._guide = self._guide_for_state(state)` + entries build) with:

```python
        else:
            self._guide = self._resolve_guide_or_schedule(state)
            if self._guide is None:
                self._entries = list(self._build_skeleton_entries(state))
            else:
                self._entries = list(
                    self._build_tv_entries(state, self._guide, folder_preview)
                )
```

In `_rebuild` (line ~296), replace the identical `self._guide = self._guide_for_state(state)` re-acquisition with `self._guide = self._resolve_guide_or_schedule(state)` and, when it returns `None`, build skeleton entries instead of TV entries (mirror the `show_state` conditional — a filter change while loading keeps the skeleton up).

Add the new methods next to `_guide_for_state`:

```python
    def _resolve_guide_or_schedule(self, state: ScanState) -> EpisodeGuide | None:
        """Cached guide, or None after scheduling an off-thread build.

        Without async wiring (bare panels, existing tests) this stays the
        old synchronous pull.
        """
        if self._cached_guide_provider is None or self._guide_builder is None:
            return self._guide_for_state(state)
        guide = self._cached_guide_provider(state)
        if guide is not None:
            return guide
        self._guide_token += 1
        token = self._guide_token
        builder = self._guide_builder
        bridge = self._guide_bridge

        def _worker() -> None:
            try:
                built, signature = builder(state)
            except Exception:
                _log.exception("episode guide build failed for %s", state.folder)
                return
            try:
                bridge.guide_ready.emit(state, built, signature, token)
            except RuntimeError:
                pass    # bridge destroyed during shutdown

        _submit_bg(_worker)
        return None

    def _on_guide_ready(self, state, guide, signature, token: int) -> None:
        if token != self._guide_token or state is not self._state:
            return    # stale build: a newer show_state/_rebuild superseded it
        if self._guide_store is not None:
            self._guide_store(state, guide, signature)
        self.beginResetModel()
        self._guide = guide
        self._entries = list(self._build_tv_entries(state, guide, self._folder_preview))
        self.endResetModel()
        self.guide_loaded.emit()

    def _build_skeleton_entries(self, state: ScanState):
        count = max(
            _SKELETON_MIN_ROWS,
            min(len(state.preview_items) or _SKELETON_MIN_ROWS, _SKELETON_MAX_ROWS),
        )
        header = EpisodeRowData(
            kind="section-label", title="Loading episodes…",
            status_text="", status_tone="muted",
        )
        yield _Entry("section-label", None, "Loading episodes…", None, None, header)
        for _ in range(count):
            yield _Entry(
                "skeleton", None, "", None, None, EpisodeRowData(kind="skeleton", title="")
            )
```

Add `"skeleton"` to the non-selectable kinds set in `flags()` (line 104): `{"section-header", "section-label", "folder", "bulk-hint", "skeleton"}`.

- [ ] **Step 4: Delegate skeleton painting** (`_episode_table_delegate.py`)

Add `QColor` to the existing `PySide6.QtGui` import line. In `paint()`, immediately after `row_data` is fetched from `ROW_DATA_ROLE`, add the early branch:

```python
        if row_data.kind == "skeleton":
            self._paint_skeleton_row(painter, option.rect)
            return
```

In `sizeHint()`, give `"skeleton"` the single-line height alongside the existing kind branches: `QSize(0, _scale.px(_ROW_SINGLE_U))`. Add the painter helper beside the other paint helpers:

```python
    def _paint_skeleton_row(self, painter: QPainter, rect: QRect) -> None:
        margin = _scale.px(_MARGIN_U)
        bar_height = _scale.px(10)
        bar = QRect(
            rect.x() + margin,
            rect.y() + (rect.height() - bar_height) // 2,
            int(rect.width() * 0.55),
            bar_height,
        )
        color = QColor(theme.color("text_dim"))
        color.setAlpha(50)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        radius = bar_height // 2
        painter.drawRoundedRect(bar, radius, radius)
        painter.restore()
```

- [ ] **Step 5: Panel + workspace wiring**

`_work_panel.py` ctor (line ~72): add `cached_guide_provider=None, guide_builder=None, guide_store=None` keyword params, store nothing on self — forward them straight into the `EpisodeTableModel(...)` construction (line ~295) as the same-named kwargs. After the model is constructed, connect:

```python
        self._model.guide_loaded.connect(self._on_guide_loaded)
```

and add the slot beside `update_footer`:

```python
    def _on_guide_loaded(self) -> None:
        """Async guide arrived: summary + toolbar depend on model.guide()."""
        self.update_footer()
        self.update_toolbar(self._state)
```

`_media_workspace_ui.py:_build_work_panel` (lines 91-101): after the existing `guide_provider=` block, add three more kwargs following the identical `hasattr` pattern:

```python
            cached_guide_provider=(
                workspace._media_ctrl.cached_episode_guide_for_state
                if workspace._media_ctrl is not None
                and hasattr(workspace._media_ctrl, "cached_episode_guide_for_state")
                else None
            ),
            guide_builder=(
                workspace._media_ctrl.build_episode_guide_snapshot
                if workspace._media_ctrl is not None
                and hasattr(workspace._media_ctrl, "build_episode_guide_snapshot")
                else None
            ),
            guide_store=(
                workspace._media_ctrl.store_episode_guide
                if workspace._media_ctrl is not None
                and hasattr(workspace._media_ctrl, "store_episode_guide")
                else None
            ),
```

- [ ] **Step 6: Run the new tests, then the full suites**

Run: `.venv\Scripts\python.exe -m pytest tests\test_qt_async_guide.py -q` → Expected: 6 passed.
Run: `scripts\test-fast.cmd` then `scripts\test-smoke.cmd` → Expected: all pass, zero skips. Workspace tests with fake `_FakeMediaController`s lack the new controller attributes → the `hasattr` guards keep them on the synchronous path; if any existing test asserts entry lists mid-populate and now sees skeletons, that test's fake controller has partial wiring — fix the FAKE (add or remove all three attributes coherently), not the product.

- [ ] **Step 7: Commit**

```bash
git add plex_renamer/gui_qt/widgets/_episode_table_model.py plex_renamer/gui_qt/widgets/_episode_table_delegate.py plex_renamer/gui_qt/widgets/_work_panel.py plex_renamer/gui_qt/widgets/_media_workspace_ui.py tests/test_qt_async_guide.py scripts/test_smoke_runner.py scripts/test_fast_runner.py
git commit -m "feat(gui): async episode-guide build - skeleton rows, generation token, off-thread delivery"
```

---

### Task 4: Season strip stops rebuilding when specs are unchanged (Plan 3's M2)

**Files:**
- Modify: `plex_renamer/gui_qt/widgets/_work_panel.py` (`_refresh_strip` line 519, `_clear_strip` line 513, ctor init)
- Test: `tests/test_work_panel.py` (extend)

**Interfaces:**
- Consumes: `season_strip_specs(state.completeness)` (existing, returns `list[tuple[int, chip]]` with `chip.text/tone/tooltip`).
- Produces: no API change — `_refresh_strip` becomes idempotent for unchanged specs. Internal: `self._strip_key: tuple | None`.

- [ ] **Step 1: Write the failing test** (append to `tests/test_work_panel.py`, reusing its `_guide_state()` fixture and `self._panel(...)` helper idioms)

```python
    def test_refresh_header_reuses_strip_buttons_when_seasons_unchanged(self):
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        before = [id(button) for button in panel._strip_buttons]
        self.assertTrue(before)                       # fixture renders at least one chip
        panel.refresh_header(state)                   # action-bar sync repeats this constantly
        panel.refresh_header(state)
        self.assertEqual([id(button) for button in panel._strip_buttons], before)
        panel.close()

    def test_refresh_strip_rebuilds_after_completeness_change(self):
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        before = [id(button) for button in panel._strip_buttons]
        season = next(iter(state.completeness.seasons.values()))
        season.matched += 1                           # chip text/tone derives from this
        panel.refresh_header(state)
        after = [id(button) for button in panel._strip_buttons]
        self.assertNotEqual(after, before)
        panel.close()

    def test_clear_resets_strip_key_so_next_show_rebuilds(self):
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        panel.clear()
        self.assertEqual(panel._strip_buttons, [])
        panel.refresh_header(state)
        self.assertTrue(panel._strip_buttons)
        panel.close()
```

- [ ] **Step 2: Run tests to verify the first fails**

Run: `.venv\Scripts\python.exe -m pytest tests\test_work_panel.py -q -k strip`
Expected: `test_refresh_header_reuses_strip_buttons_when_seasons_unchanged` FAILS (ids differ — buttons are rebuilt today); the other two pass (pin current behavior).

- [ ] **Step 3: Implement the no-churn key**

Ctor/`_build_ui` (wherever `self._strip_buttons = []` is initialized): add `self._strip_key: tuple | None = None`. In `_clear_strip` (line 513), reset the key so every clearing path (including `clear()`) invalidates:

```python
    def _clear_strip(self) -> None:
        self._strip_key = None
        for button in self._strip_buttons:
            button.setParent(None)
            button.deleteLater()
        self._strip_buttons = []
```

In `_refresh_strip` (line 519), compute the key and skip when unchanged — replace the unconditional `self._clear_strip()` opener:

```python
    def _refresh_strip(self, state: ScanState) -> None:
        if self._media_type == "movie":
            self._clear_strip()
            self._strip_scroll.hide()
            return
        specs = season_strip_specs(state.completeness)
        key = tuple(
            (season_num, chip.text, chip.tone, chip.tooltip) for season_num, chip in specs
        )
        if key == self._strip_key:
            return                                   # same chips: no widget churn
        self._clear_strip()
        self._strip_key = key
        if not specs:
            self._strip_scroll.hide()
            return
        ...existing build loop unchanged...
```

(Note `_clear_strip` resets `_strip_key`, so assign `self._strip_key = key` AFTER calling it, as shown.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests\test_work_panel.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add plex_renamer/gui_qt/widgets/_work_panel.py tests/test_work_panel.py
git commit -m "perf(gui): season strip skips rebuild when chip specs unchanged (Plan 3 M2)"
```

---

### Task 5: BusyOverlay wiring — bulk apply, unassign-all, queueing, tab-restore

**Files:**
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_actions.py` (`apply_bulk_assignments`, `unassign_all_episode_mappings`)
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_queue_actions.py` (`queue_states`, line 97)
- Modify: `plex_renamer/gui_qt/_main_window_state.py` (restore calls, lines 129/136)
- Test: `tests/test_qt_media_workspace.py` (workspace sites) and `tests/test_qt_chrome.py` (tab-restore)

**Interfaces:**
- Consumes: Task 1's `busy_scope` (`from .busy_overlay import busy_scope` in widgets; `from .widgets.busy_overlay import busy_scope` in `_main_window_state.py`) and `BusyOverlay` (tests).
- Produces: no API changes. All four sites use `immediate=True` — they run on the GUI thread and block the loop, so the deferred timer could never fire (see the module docstring).

**Scope rules for every site:** the `with busy_scope(...)` block wraps only the mutation + projection-refresh/repopulate work. Confirm dialogs (`QMessageBox`) stay OUTSIDE and BEFORE the scope — never show a scrim under a modal prompt. Status/toast emissions may stay inside or after; keep the diff minimal.

- [ ] **Step 1: Write the failing tests**

Append to `BulkAssignWorkspaceTests` in `tests/test_qt_media_workspace.py` (its `_tv_workspace_with_table_state` helper already exists):

```python
    def test_bulk_apply_shows_busy_overlay_during_service_call(self):
        from unittest.mock import patch

        from plex_renamer.gui_qt.widgets.busy_overlay import BusyOverlay

        workspace = self._tv_workspace_with_table_state()
        workspace._enter_bulk_assign()
        panel = workspace._work_panel.bulk_panel
        panel.auto_map_remaining()
        seen: dict[str, bool] = {}

        def observing_apply(service_self, state, pairs):
            overlay = workspace._work_panel.findChild(BusyOverlay)
            seen["visible"] = overlay is not None and overlay.isVisible()
            return (len(pairs), 0)

        with patch(
            "plex_renamer.gui_qt.widgets._media_workspace_actions."
            "EpisodeMappingService.apply_assignments",
            new=observing_apply,
        ):
            workspace._on_bulk_apply(panel.staged_pairs())
        self.assertTrue(seen.get("visible"))
        self.assertIsNone(workspace._work_panel.findChild(BusyOverlay))
```

Add the queueing test in the same file's queue-focused test class, same observer shape with these exact seams: the workspace fixtures' fake queue controller exposes `add_tv_batch(states, root, output_root, gating)` — replace it on the fixture instance with an observer that records `workspace.findChild(BusyOverlay) is not None and overlay.isVisible()` and returns whatever the fake returned before; drive the real entry point (the roster queue button / `queue_selected_state`, per the class's existing queue tests); assert `seen["visible"]` is True and `workspace.findChild(BusyOverlay)` is `None` afterwards.

For tab-restore, add to `tests/test_qt_chrome.py` (its main-window fixture already exercises tab switches): replace `window.media_ctrl.restore_tv_from_tab_switch` on the window's controller instance with an observer that records `window.findChild(BusyOverlay)` visibility (import `BusyOverlay` the same way), trigger the tab switch that reaches `_main_window_state.py:129` via the real tab bar (`window.tabs.setCurrentIndex(...)` per the file's existing idiom), and assert visible-during / gone-after. In both tests drive the real entry points, not the private helpers, and let the observer preserve the replaced callable's return value.

- [ ] **Step 2: Run to verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests\test_qt_media_workspace.py -q -k busy_overlay`
Expected: FAIL — `seen["visible"]` is falsy (no overlay exists yet).

- [ ] **Step 3: Wire the four sites**

`_media_workspace_actions.py` — add `from .busy_overlay import busy_scope` to the imports. In `apply_bulk_assignments`, after the existing `state is None or not pairs` and `state.assignments is None` guards (do not touch them), wrap the remainder — from the `applied, skipped = EpisodeMappingService().apply_assignments(state, pairs)` call through the projection refresh/repopulate lines that follow — in:

```python
        with busy_scope(workspace._work_panel, "Applying assignments…", immediate=True):
            ...existing apply + refresh block, indented one level...
```

In `unassign_all_episode_mappings`, the confirm `QMessageBox` stays outside; wrap the post-confirm service call + refresh in `busy_scope(workspace._work_panel, "Unassigning all…", immediate=True)` the same way.

`_media_workspace_queue_actions.py` — add the same import. In `queue_states` (line 97), wrap the block that hands the eligible states to the queue controller (the `add_tv_batch`/movie-equivalent call plus the immediate post-queue state sync it performs) in `busy_scope(workspace, "Queueing…", immediate=True)`. Eligibility checks and any message boxes stay outside.

`_main_window_state.py` — add `from .widgets.busy_overlay import busy_scope`. Wrap each of the two restore calls (lines 129 and 136):

```python
                with busy_scope(window, "Restoring…", immediate=True):
                    window.media_ctrl.restore_tv_from_tab_switch(window._tv_snapshot)
```

(and the movie twin at line 136).

**Spec deviation to record in your report:** spec §7 lists "force rescan" as an overlay site; no rescan surface exists in the current code (scans run behind the scanning page). Skipped, not deferred silently.

- [ ] **Step 4: Run the tests, then both suites**

Run: `.venv\Scripts\python.exe -m pytest tests\test_qt_media_workspace.py tests\test_qt_chrome.py -q`
Expected: all pass (new overlay tests + no regressions — the overlay must not swallow events needed by existing tests because every scope closes before assertions run).
Then `scripts\test-fast.cmd` + `scripts\test-smoke.cmd` → green, zero skips.

- [ ] **Step 5: Commit**

```bash
git add plex_renamer/gui_qt/widgets/_media_workspace_actions.py plex_renamer/gui_qt/widgets/_media_workspace_queue_actions.py plex_renamer/gui_qt/_main_window_state.py tests/test_qt_media_workspace.py tests/test_qt_chrome.py
git commit -m "feat(gui): busy_scope wiring - bulk apply, unassign-all, queueing, tab-restore"
```

---

### Task 6: Permanent perf guards

**Files:**
- Create: `tests/test_gui_perf_guards.py` (fast suite — pure source sweep, no Qt)
- Create: `tests/test_qt_perf_guards.py` (smoke — behavioral + wall-clock)
- Modify: `scripts/test_smoke_runner.py` + `scripts/test_fast_runner.py` (register `tests/test_qt_perf_guards.py` only; the non-Qt file runs in fast automatically)

**Interfaces:**
- Consumes: Task 3's async wiring (counting-builder pattern from `tests/test_qt_async_guide.py`), Task 2's cache service.
- Produces: standing guards; no product code.

- [ ] **Step 1: Write the fast source-sweep guard**

```python
# tests/test_gui_perf_guards.py
"""Spec §7 standing guards: the GUI package must never block-and-pump."""
import unittest
from pathlib import Path

_GUI_ROOT = Path(__file__).resolve().parent.parent / "plex_renamer" / "gui_qt"
_FORBIDDEN = ("processEvents(", "time.sleep(")


class GuiEventLoopGuards(unittest.TestCase):
    def test_gui_package_never_pumps_or_sleeps(self):
        offenders: list[str] = []
        for source in sorted(_GUI_ROOT.rglob("*.py")):
            text = source.read_text(encoding="utf-8")
            for needle in _FORBIDDEN:
                if needle in text:
                    offenders.append(f"{source.relative_to(_GUI_ROOT)}: {needle}")
        self.assertEqual(
            offenders, [],
            "processEvents/time.sleep are banned in gui_qt (spec §7); "
            "move the work to plex_renamer.thread_pool.submit or use BusyOverlay.",
        )
```

- [ ] **Step 2: Write the Qt behavioral/wall-clock guards**

```python
# tests/test_qt_perf_guards.py
"""Spec §7 perf guards over a 300-episode show (12 seasons x 25).

Budget on the reference machine: cached switch < 100ms. The wall-clock
assertion below uses a 5x margin (500ms) so offscreen CI variance cannot
flake it; the deterministic guards are the primary protection.
"""
from pathlib import Path
from unittest.mock import patch

from conftest_qt import QtSmokeBase


def _big_state(name: str = "Big Show", *, seasons: int = 12, per_season: int = 25):
    from plex_renamer.app.services.episode_mapping_service import EpisodeMappingService
    from plex_renamer.engine import ScanState
    from plex_renamer.engine.episode_assignments import (
        ORIGIN_MANUAL,
        EpisodeAssignmentTable,
        EpisodeSlot,
    )

    table = EpisodeAssignmentTable()
    for season in range(1, seasons + 1):
        for episode in range(1, per_season + 1):
            table.add_slot(EpisodeSlot(season=season, episode=episode,
                                       title=f"S{season:02d}E{episode:02d}"))
    for season in range(1, seasons + 1):
        for episode in range(1, per_season + 1):
            entry = table.add_file(
                Path(f"C:/library/tv/{name}/s{season:02d}e{episode:02d}.mkv")
            )
            table.assign(entry.file_id, season, [episode], origin=ORIGIN_MANUAL)
    state = ScanState(folder=Path(f"C:/library/tv/{name}"),
                      media_info={"id": 900, "name": name, "year": "2020"})
    state.scanned = True
    state.confidence = 1.0
    state.assignments = table
    EpisodeMappingService().reproject(state)
    return state


class PerfGuardTests(QtSmokeBase):
    def _async_model(self, cache):
        from plex_renamer.gui_qt.widgets._episode_table_model import EpisodeTableModel

        return EpisodeTableModel(
            media_type="tv",
            cached_guide_provider=cache.cached_guide_for_state,
            guide_builder=cache.build_guide_with_signature,
            guide_store=cache.store_guide,
        )

    def test_uncached_300_episode_switch_never_builds_on_gui_thread(self):
        from plex_renamer.app.services.episode_projection_cache import (
            EpisodeProjectionCacheService,
        )

        cache = EpisodeProjectionCacheService()
        pending: list = []
        with patch(
            "plex_renamer.gui_qt.widgets._episode_table_model._submit_bg",
            side_effect=pending.append,
        ):
            model = self._async_model(cache)
            resets: list[bool] = []
            model.modelReset.connect(lambda: resets.append(True))
            model.show_state(_big_state(), collapsed_sections=set())
        self.assertEqual(len(resets), 1)                       # one reset, instant
        self.assertEqual(len(pending), 1)                      # build went to the pool
        self.assertIn("skeleton", {e.kind for e in model._entries})

    def test_cached_300_episode_switch_renders_under_offscreen_budget(self):
        from PySide6.QtCore import QElapsedTimer

        from plex_renamer.app.services.episode_projection_cache import (
            EpisodeProjectionCacheService,
        )

        cache = EpisodeProjectionCacheService()
        state = _big_state()
        cache.prepare_state(state)
        model = self._async_model(cache)
        timer = QElapsedTimer()
        timer.start()
        model.show_state(state, collapsed_sections=set())
        elapsed_ms = timer.elapsed()
        self.assertIn("episode", {e.kind for e in model._entries})
        self.assertLess(
            elapsed_ms, 500,
            f"cached 300-episode switch took {elapsed_ms}ms offscreen "
            "(reference budget 100ms; 5x margin)",
        )
```

- [ ] **Step 3: Register + run**

Register `tests/test_qt_perf_guards.py` in both runner lists (as Task 1 Step 4). Run:
`.venv\Scripts\python.exe -m pytest tests\test_gui_perf_guards.py tests\test_qt_perf_guards.py -q`
Expected: 3 passed.

- [ ] **Step 4: Run both suites**

`scripts\test-fast.cmd` + `scripts\test-smoke.cmd` → green, zero skips.

- [ ] **Step 5: Commit**

```bash
git add tests/test_gui_perf_guards.py tests/test_qt_perf_guards.py scripts/test_smoke_runner.py scripts/test_fast_runner.py
git commit -m "test: spec-7 perf guards - no GUI-thread guide builds, no processEvents, cached-switch budget"
```

---

### Task 7: Verification + bookkeeping (controller)

**Files:**
- Modify: `docs/superpowers/plans/2026-07-03-gui-v4-implementation.md`, `docs/superpowers/plans/2026-07-03-gui-v4-handoff.md`

- [ ] **Step 1: Full suites** — `scripts\test-fast.cmd` + `scripts\test-smoke.cmd` → pass, zero new skips; skim `.pytest_cache/smoke/latest.log`.

- [ ] **Step 2: Visual sanity** — throwaway offscreen grab script (scratchpad, Plan 4 pattern; `QT_QPA_PLATFORM=offscreen`, `QT_QPA_FONTDIR=C:\Windows\Fonts`, theme QSS applied). Grabs: (a) work panel mid-load — construct the async-wired panel with an UNCACHED table-backed state and grab before draining the pool: "Loading episodes…" label + dim skeleton bars visible; (b) same panel after the guide arrives (drain via processEvents until `guide_loaded`): real rows, footer populated; (c) a panel with `busy_scope(..., immediate=True)` held open: scrim + spinner + label legible over the table. Assert parentage while grabbing (overlay `.window() is panel.window()`, no stray visible top-levels — Plan 3's lesson). Delete/keep script in scratchpad only.

- [ ] **Step 3: Update roadmap + handoff, commit** — roadmap row 5 → Landed (commit range); handoff status/current + "next step: write Plan 6 (toasts + loading screen, spec §9-§10)" + session log entry; record the "force rescan" spec deviation and note `Spinner` is the shared primitive Plan 6's loading screen must reuse (spec line 192).

```bash
git add docs/superpowers/plans
git commit -m "docs: mark GUI V4 plan 5 landed; next up plan 6 (toasts + loading)"
```

---

## Self-review notes (kept for the record)

- **Spec §7 coverage:** async guide build on the existing thread pool with a per-state generation token + skeleton-then-fill (Task 3, exactly the overview-bridge pattern already proven in `_work_panel.py`); BusyOverlay + `busy_scope()` with guaranteed finally-removal and the ~120ms deferred show (Task 1), wired to bulk apply/unassign-all/queue/tab-restore (Task 5); `warm_preview_cache`/`processEvents` deletions landed in Plan 3 — pinned permanently by Task 6's sweep rather than re-done; budget guarded deterministically (no GUI-thread builds) plus one margin-documented wall-clock (Task 6); Plan 3's M2 strip churn folded in (Task 4). Spec's "force rescan" overlay site does not exist in the code — recorded as a deviation in Tasks 5/7, not silently dropped. Spec's group collapse/expand <50ms budget has no deterministic proxy that isn't a wall-clock flake risk; consciously left to the cached-switch guard (collapse runs the same `_rebuild`) — reviewer may challenge.
- **Deliberate design choices:** post-mutation `refresh_episode_guide` paths stay synchronous (the reprojection already ran; overlay covers the interaction; skeleton-flash-on-approve would be a UX regression) — the async path triggers only on display of an uncached state. Signature captured BEFORE off-thread build so concurrent mutation degrades to a stale miss, never a wrong hit. Async engages only when all wiring is present (`hasattr` guards + model fallback), keeping every bare-panel test and fake controller on today's synchronous path. `dismiss()` reparents to None so tests can assert removal without deferred-delete pumping. Immediate mode `repaint()`s once because a deferred QTimer cannot fire under a blocked loop — this is why the four wired sites use `immediate=True`.
- **Type-consistency pass:** provider names `cached_guide_provider`/`guide_builder`/`guide_store` identical across model ctor (Task 3), panel ctor (Task 3 Step 5), workspace wiring (Task 3 Step 5), and both test files (Tasks 3/6); controller methods `cached_episode_guide_for_state`/`build_episode_guide_snapshot`/`store_episode_guide` match Task 2's definitions; `busy_scope(target, text, *, delay_ms, immediate)` matches every Task 5 call; `guide_loaded` signal name identical in model, panel connection, and tests; skeleton kind string `"skeleton"` identical in model `flags()`, delegate branches, and test assertions; `_strip_key` reset lives inside `_clear_strip()` so `clear()` (line 351) inherits it.
