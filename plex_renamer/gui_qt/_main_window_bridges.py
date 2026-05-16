"""Qt bridge helpers for main-window controller callbacks."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Signal

from ..app.models import ScanProgress


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
    queue_finished = Signal()
    poster_backfill_finished = Signal(int)

    def on_job_started(self, job) -> None:
        self.job_started.emit(job)
        self.changed.emit(None)

    def on_job_completed(self, job, result) -> None:
        self.job_completed.emit(job, result)
        self.changed.emit(None)

    def on_job_failed(self, job, error) -> None:
        self.job_failed.emit(job, error)
        self.changed.emit(None)

    def on_queue_finished(self) -> None:
        self.queue_finished.emit()
        self.changed.emit(None)

    def on_poster_backfill_finished(self, updated: int) -> None:
        try:
            self.poster_backfill_finished.emit(updated)
        except RuntimeError:
            pass


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
    )
    bridge.changed.connect(window._on_queue_changed)
    bridge.job_started.connect(window._on_job_started)
    bridge.job_completed.connect(window._on_job_completed)
    bridge.job_failed.connect(window._on_job_failed)
    bridge.queue_finished.connect(window._on_queue_finished)
    bridge.poster_backfill_finished.connect(window._on_poster_backfill_finished)
    return bridge
