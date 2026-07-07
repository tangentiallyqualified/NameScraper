# tests/test_workspace_poster_warmup.py
"""SCANNING→READY waits for poster warmup, with a timeout (LD3)."""
from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QStackedWidget, QWidget

from conftest_qt import QtSmokeBase


class _StubScanProgress:
    def __init__(self) -> None:
        self.finish_calls = 0
        self.posters_seen: list[list] = []

    def set_posters(self, pixmaps) -> None:
        self.posters_seen.append(list(pixmaps))

    def finish(self) -> None:
        self.finish_calls += 1

    def stop(self) -> None:
        pass


class _FakeWorkspace(QWidget):
    """Minimal QWidget-based stand-in for MediaWorkspace's lifecycle needs."""

    def __init__(self, model) -> None:
        super().__init__()
        self._roster_panel = SimpleNamespace(model=model)
        self._scan_progress = _StubScanProgress()
        self._stack = QStackedWidget()
        for _ in range(3):
            self._stack.addWidget(QLabel())
        self.refresh_calls = 0

    def refresh_from_controller(self) -> None:
        self.refresh_calls += 1


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
