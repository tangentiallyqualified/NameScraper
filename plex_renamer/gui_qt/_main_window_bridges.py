"""Qt bridge helpers for main-window controller callbacks."""

from __future__ import annotations

import contextlib
from typing import Any

from PySide6.QtCore import QObject, Qt, QTimer, Signal

from ..app.models import ScanProgress

_QUEUE_REFRESH_DEBOUNCE_MS = 75


class ControllerBridge(QObject):
    """Marshal MediaController callbacks onto the Qt main thread."""

    progress_received = Signal(object)
    scan_complete = Signal()
    library_changed = Signal()

    def on_progress(self, progress: ScanProgress) -> None:
        self.progress_received.emit(progress)

    def on_scan_complete(self, _state) -> None:
        self.scan_complete.emit()

    def on_library_changed(self, _states) -> None:
        self.library_changed.emit()


class QueueBridge(QObject):
    """Marshal QueueController callbacks onto the Qt main thread."""

    changed = Signal(object)
    job_started = Signal(object)
    job_completed = Signal(object, object)
    job_failed = Signal(object, object)
    job_progress = Signal(object, int, int, int)
    queue_finished = Signal()
    poster_backfill_finished = Signal(int)
    _change_requested = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._change_timer = QTimer(self)
        self._change_timer.setSingleShot(True)
        self._change_timer.setInterval(_QUEUE_REFRESH_DEBOUNCE_MS)
        self._change_timer.timeout.connect(self._emit_changed)
        self._change_requested.connect(
            self._schedule_changed,
            Qt.ConnectionType.QueuedConnection,
        )

    def on_job_started(self, job) -> None:
        self.job_started.emit(job)
        self._request_changed()

    def on_job_completed(self, job, result) -> None:
        self.job_completed.emit(job, result)
        self._request_changed()

    def on_job_failed(self, job, error) -> None:
        self.job_failed.emit(job, error)
        self._request_changed()

    def on_job_progress(self, job, op_index: int, op_count: int, percent: int) -> None:
        # Cross-thread signal emission queues to the GUI thread; progress
        # is high-frequency, so it bypasses the debounced changed() path.
        self.job_progress.emit(job, op_index, op_count, percent)

    def on_queue_finished(self) -> None:
        self.queue_finished.emit()
        self._request_changed(force=True)

    def _request_changed(self, *, force: bool = False) -> None:
        self._change_requested.emit(force)

    def _schedule_changed(self, force: bool) -> None:
        if force:
            self._change_timer.stop()
            self._emit_changed()
            return
        if not self._change_timer.isActive():
            self._change_timer.start()

    def _emit_changed(self) -> None:
        self.changed.emit(None)

    def on_poster_backfill_finished(self, updated: int) -> None:
        with contextlib.suppress(RuntimeError):
            self.poster_backfill_finished.emit(updated)


def install_controller_bridge(window: Any) -> ControllerBridge:
    bridge = ControllerBridge(window)
    window.media_ctrl.add_listener(
        on_progress=bridge.on_progress,
        on_scan_complete=bridge.on_scan_complete,
        on_library_changed=bridge.on_library_changed,
    )
    bridge.progress_received.connect(window._on_scan_progress)
    bridge.scan_complete.connect(window._on_scan_complete)
    bridge.library_changed.connect(window._on_library_changed)
    return bridge


def install_queue_bridge(window: Any) -> QueueBridge:
    bridge = QueueBridge(window)
    window.queue_ctrl.add_listener(
        on_job_started=bridge.on_job_started,
        on_job_completed=bridge.on_job_completed,
        on_job_failed=bridge.on_job_failed,
        on_queue_finished=bridge.on_queue_finished,
        on_job_progress=bridge.on_job_progress,
    )
    bridge.changed.connect(window._on_queue_changed)
    bridge.job_started.connect(window._on_job_started)
    bridge.job_completed.connect(window._on_job_completed)
    bridge.job_failed.connect(window._on_job_failed)
    bridge.job_progress.connect(window._on_job_progress)
    bridge.queue_finished.connect(window._on_queue_finished)
    bridge.poster_backfill_finished.connect(window._on_poster_backfill_finished)
    return bridge
