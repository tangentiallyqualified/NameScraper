"""Helpers for controller scan progress and cancellation state."""

from __future__ import annotations

import threading
from collections.abc import Callable

from ..models import ScanLifecycle, ScanProgress
from ._controller_event_helpers import build_scan_progress


class ScanOperationTracker:
    """Own the active scan cancellation token and its synchronization."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cancel_event: threading.Event | None = None

    def begin(self) -> threading.Event:
        event = threading.Event()
        with self._lock:
            self._cancel_event = event
        return event

    def is_current(self, event: threading.Event) -> bool:
        with self._lock:
            return self._cancel_event is event

    def finish(self, event: threading.Event) -> None:
        with self._lock:
            if self._cancel_event is event:
                self._cancel_event = None

    def cancel(self) -> bool:
        with self._lock:
            event = self._cancel_event
        if event is None:
            return False
        event.set()
        return True


def update_scan_progress(
    notify: Callable[[str, ScanProgress], None],
    lifecycle: ScanLifecycle,
    *,
    phase: str = "",
    done: int = 0,
    total: int = 0,
    current_item: str | None = None,
    message: str = "",
) -> ScanProgress:
    progress = build_scan_progress(
        lifecycle,
        phase=phase,
        done=done,
        total=total,
        current_item=current_item,
        message=message,
    )
    notify("progress", progress)
    return progress