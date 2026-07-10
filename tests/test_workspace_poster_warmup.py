# tests/test_workspace_poster_warmup.py
"""SCANNING→READY waits for poster warmup, with a timeout (LD3)."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QStackedWidget, QWidget

from conftest_qt import QtSmokeBase


class _StubScanProgress:
    def __init__(self) -> None:
        self.finish_calls = 0
        self.start_calls = 0
        self.posters_seen: list[list] = []

    def set_posters(self, pixmaps) -> None:
        self.posters_seen.append(list(pixmaps))

    def start(self) -> None:
        self.start_calls += 1

    def finish(self) -> None:
        self.finish_calls += 1

    def stop(self) -> None:
        pass


class _StubWorkPanel:
    def __init__(self) -> None:
        self.clear_calls = 0

    def clear(self) -> None:
        self.clear_calls += 1


class _FakeWorkspace(QWidget):
    """Minimal QWidget-based stand-in for MediaWorkspace's lifecycle needs."""

    def __init__(self, model) -> None:
        super().__init__()
        self._roster_panel = SimpleNamespace(model=model)
        self._scan_progress = _StubScanProgress()
        self._work_panel = _StubWorkPanel()
        self._stack = QStackedWidget()
        for _ in range(3):
            self._stack.addWidget(QLabel())
        self.refresh_calls = 0
        self._states: list = []

    def refresh_from_controller(self) -> None:
        self.refresh_calls += 1

    def _current_states(self) -> list:
        return self._states


class PosterWarmupTests(QtSmokeBase):
    def _coordinator_with_fake(self, pending_seq):
        from plex_renamer.gui_qt.widgets._roster_model import RosterModel
        from plex_renamer.gui_qt.widgets._media_workspace_lifecycle import (
            MediaWorkspaceLifecycleCoordinator,
        )

        model = RosterModel(media_type="tv")
        pending = list(pending_seq)
        model.pending_poster_count = lambda: pending[0]

        workspace = _FakeWorkspace(model)
        coordinator = MediaWorkspaceLifecycleCoordinator(
            workspace,
            empty_index=0,
            scanning_index=1,
            ready_index=2,
        )
        return coordinator, workspace, model, pending

    def test_switches_to_ready_when_pending_reaches_zero(self):
        coordinator, workspace, model, pending = self._coordinator_with_fake([2])
        coordinator.show_ready_when_posters_warm()

        self.assertNotEqual(workspace._stack.currentIndex(), 2)
        self.assertEqual(workspace._scan_progress.finish_calls, 0)

        pending[0] = 0
        model.poster_loaded.emit()

        self.assertEqual(workspace._stack.currentIndex(), 2)
        self.assertEqual(workspace._scan_progress.finish_calls, 1)

        # A second emit must not re-finalize (exactly-once / disconnect check).
        model.poster_loaded.emit()
        self.assertEqual(workspace._stack.currentIndex(), 2)
        self.assertEqual(workspace._scan_progress.finish_calls, 1)

    def test_reentrant_warmup_finalizes_once(self):
        coordinator, workspace, model, pending = self._coordinator_with_fake([2])
        coordinator.show_ready_when_posters_warm()

        self.assertNotEqual(workspace._stack.currentIndex(), 2)
        self.assertEqual(workspace._scan_progress.finish_calls, 0)

        # Re-entrant call before warmup #1 finalizes: must cancel warmup #1
        # (stop its poll timer, disconnect its handler) and start warmup #2
        # cleanly, rather than stacking a second handler alongside the first.
        coordinator.show_ready_when_posters_warm()

        self.assertNotEqual(workspace._stack.currentIndex(), 2)
        self.assertEqual(workspace._scan_progress.finish_calls, 0)

        pending[0] = 0
        model.poster_loaded.emit()

        self.assertEqual(workspace._stack.currentIndex(), 2)
        self.assertEqual(workspace._scan_progress.finish_calls, 1)

    def test_switches_to_ready_on_timeout_even_if_posters_never_settle(self):
        import plex_renamer.gui_qt.widgets._media_workspace_lifecycle as life

        original_max_ms = life._POSTER_WARMUP_MAX_MS
        original_poll_ms = life._POSTER_WARMUP_POLL_MS

        def _restore():
            life._POSTER_WARMUP_MAX_MS = original_max_ms
            life._POSTER_WARMUP_POLL_MS = original_poll_ms

        self.addCleanup(_restore)
        life._POSTER_WARMUP_MAX_MS = 30
        life._POSTER_WARMUP_POLL_MS = 5

        coordinator, workspace, model, pending = self._coordinator_with_fake([3])
        coordinator.show_ready_when_posters_warm()

        self.assertNotEqual(workspace._stack.currentIndex(), 2)

        QTest.qWait(300)

        self.assertEqual(workspace._stack.currentIndex(), 2)
        self.assertEqual(workspace._scan_progress.finish_calls, 1)

    def _model_with_counting_tmdb(self):
        from unittest.mock import patch

        from PIL import Image

        from plex_renamer.gui_qt.widgets import _roster_model as rm

        fetches: list[int] = []

        class _Tmdb:
            def fetch_poster(self, show_id, *, media_type="tv", target_width=240):
                fetches.append(show_id)
                return Image.new("RGB", (4, 6), (10, 20, 30))

        model = rm.RosterModel(media_type="tv", tmdb_provider=lambda: _Tmdb())
        self._submit_bg_patch = patch.object(rm, "_submit_bg", side_effect=lambda fn: fn())
        self._submit_bg_patch.start()
        self.addCleanup(self._submit_bg_patch.stop)
        return model, fetches

    def _drain_background(self) -> None:
        # The patched _submit_bg above runs work synchronously, so there is
        # nothing left to drain; this mirrors test_roster_model.py's pattern.
        pass

    def _state(self, *, show_id):
        from plex_renamer.engine.models import ScanState

        media_info = {"name": "Show", "year": "2020"}
        if show_id is not None:
            media_info["id"] = show_id
        return ScanState(folder=Path(f"C:/lib/show-{show_id}"), media_info=media_info)

    def _workspace(self):
        from plex_renamer.gui_qt.widgets._roster_model import RosterModel

        model = RosterModel(media_type="tv")
        return _FakeWorkspace(model)

    def test_warm_posters_requests_for_matched_states_only(self):
        model, fetches = self._model_with_counting_tmdb()
        states = [self._state(show_id=11), self._state(show_id=None), self._state(show_id=12)]
        model.warm_posters(states)
        self._drain_background()
        self.assertEqual(sorted(fetches), [11, 12])

    def test_show_scanning_starts_the_poster_feed_timer(self):
        from plex_renamer.gui_qt.widgets._media_workspace_lifecycle import (
            MediaWorkspaceLifecycleCoordinator,
        )

        workspace = self._workspace()
        coordinator = MediaWorkspaceLifecycleCoordinator(
            workspace,
            empty_index=0,
            scanning_index=1,
            ready_index=2,
        )
        workspace._lifecycle_coordinator = coordinator
        coordinator.show_scanning()
        self.assertTrue(workspace._lifecycle_coordinator._scan_poster_timer.isActive())
        coordinator.show_ready()
        self.assertIsNone(workspace._lifecycle_coordinator._scan_poster_timer)

    def test_scan_feed_pushes_loaded_posters_on_signal(self):
        coordinator, workspace, model, pending = self._coordinator_with_fake([1])
        coordinator.show_scanning()

        before = len(workspace._scan_progress.posters_seen)
        model.poster_loaded.emit()

        self.assertEqual(len(workspace._scan_progress.posters_seen), before + 1)
        self.assertEqual(workspace._scan_progress.posters_seen[-1], model.loaded_posters())

    def test_scan_feed_disconnects_after_show_ready(self):
        coordinator, workspace, model, pending = self._coordinator_with_fake([0])
        coordinator.show_scanning()
        coordinator.show_ready()

        before = len(workspace._scan_progress.posters_seen)
        model.poster_loaded.emit()

        self.assertEqual(len(workspace._scan_progress.posters_seen), before)

    def test_start_scan_poster_feed_reentrant_no_double_delivery(self):
        coordinator, workspace, model, pending = self._coordinator_with_fake([1])
        coordinator.show_scanning()
        # Re-entrant call before any teardown: must not stack a second
        # poster_loaded connection alongside the first.
        coordinator._start_scan_poster_feed()

        before = len(workspace._scan_progress.posters_seen)
        model.poster_loaded.emit()

        self.assertEqual(len(workspace._scan_progress.posters_seen), before + 1)
