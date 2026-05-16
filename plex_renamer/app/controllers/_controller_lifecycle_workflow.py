"""Scan lifecycle coordination for MediaController."""

from __future__ import annotations

import threading
from typing import Any, Protocol

from ._scan_operation_helpers import ScanOperationTracker, update_scan_progress
from ..models import ScanLifecycle, ScanProgress


class _LifecycleController(Protocol):
    def _notify(self, event: str, *args: Any) -> None: ...


class MediaControllerLifecycleWorkflow:
    def __init__(self, controller: _LifecycleController) -> None:
        self._controller = controller
        self._scan_progress = ScanProgress(lifecycle=ScanLifecycle.IDLE)
        self._scan_operation = ScanOperationTracker()

    @property
    def scan_progress(self) -> ScanProgress:
        return self._scan_progress

    @scan_progress.setter
    def scan_progress(self, value: ScanProgress) -> None:
        self._scan_progress = value

    def set_progress(
        self,
        lifecycle: ScanLifecycle,
        *,
        phase: str = "",
        done: int = 0,
        total: int = 0,
        current_item: str | None = None,
        message: str = "",
    ) -> None:
        self._scan_progress = update_scan_progress(
            self._controller._notify,
            lifecycle,
            phase=phase,
            done=done,
            total=total,
            current_item=current_item,
            message=message,
        )

    def begin_scan_operation(self) -> threading.Event:
        return self._scan_operation.begin()

    def is_current_scan_operation(self, event: threading.Event) -> bool:
        return self._scan_operation.is_current(event)

    def finish_scan_operation(self, event: threading.Event) -> None:
        self._scan_operation.finish(event)

    def cancel_scan(self) -> bool:
        return self._scan_operation.cancel()