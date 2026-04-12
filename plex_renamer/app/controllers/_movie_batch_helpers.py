"""Helpers for movie batch scanning workflows."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Protocol

from ...constants import MediaType
from ...engine import ScanCancelledError
from ...thread_pool import submit as _submit_bg
from ..models import ScanLifecycle

_log = logging.getLogger(__name__)


class _MovieBatchController(Protocol):
    _active_content_mode: MediaType
    _active_library_mode: MediaType | None
    _movie_folder: Path | None
    _movie_scanner: Any
    _movie_preview_items: list[Any]
    _movie_library_states: list[Any]
    _movie_media_info: dict | None
    _library_selected_index: int | None

    def _set_progress(
        self,
        lifecycle: ScanLifecycle,
        *,
        phase: str = "",
        done: int = 0,
        total: int = 0,
        current_item: str | None = None,
        message: str = "",
    ) -> None: ...

    def _notify(self, event: str, *args: Any) -> None: ...

    def _begin_scan_operation(self) -> threading.Event: ...

    def _is_current_scan_operation(self, event: threading.Event) -> bool: ...

    def _finish_scan_operation(self, event: threading.Event) -> None: ...

    def _build_movie_library_states(self, items: list[Any], scanner: Any) -> None: ...

    def sync_queued_states(self) -> None: ...


def start_movie_batch_session(
    controller: _MovieBatchController,
    folder: Path,
    tmdb: Any,
    scanner_factory: Any,
) -> None:
    controller._active_content_mode = MediaType.MOVIE
    controller._active_library_mode = MediaType.MOVIE
    controller._movie_folder = folder
    controller._movie_scanner = scanner_factory(tmdb, folder)
    controller._movie_preview_items = []
    controller._movie_library_states = []
    controller._movie_media_info = {"_type": "movie_batch", "_media_type": MediaType.MOVIE}
    controller._library_selected_index = None

    controller._set_progress(
        ScanLifecycle.SCANNING,
        phase="Scanning movies...",
        message="Scanning movies...",
    )
    controller._notify("mode_changed", controller._active_content_mode, controller._active_library_mode)

    scanner = controller._movie_scanner
    cancel_event = controller._begin_scan_operation()

    def _worker() -> None:
        try:
            items = scanner.scan(cancel_event=cancel_event)
        except ScanCancelledError:
            _cancel_movie_batch_scan(controller, cancel_event)
            return
        except Exception as exc:
            _fail_movie_batch_scan(controller, cancel_event, exc)
            return

        _complete_movie_batch_scan(controller, cancel_event, items, scanner)

    _submit_bg(_worker)


def _cancel_movie_batch_scan(
    controller: _MovieBatchController,
    cancel_event: threading.Event,
) -> None:
    if not controller._is_current_scan_operation(cancel_event):
        return
    controller._movie_preview_items = []
    controller._movie_library_states = []
    controller._library_selected_index = None
    controller._set_progress(
        ScanLifecycle.CANCELLED,
        phase="Movie scan cancelled",
        message="Movie scan cancelled.",
    )
    controller._notify("library_changed", controller._movie_library_states)
    controller._finish_scan_operation(cancel_event)


def _fail_movie_batch_scan(
    controller: _MovieBatchController,
    cancel_event: threading.Event,
    exc: Exception,
) -> None:
    if not controller._is_current_scan_operation(cancel_event):
        return
    _log.exception("Movie batch scan failed: %s", exc)
    controller._set_progress(
        ScanLifecycle.FAILED,
        phase="Scan failed.",
        message=f"Movie scan failed: {exc}",
    )
    controller._finish_scan_operation(cancel_event)


def _complete_movie_batch_scan(
    controller: _MovieBatchController,
    cancel_event: threading.Event,
    items: list[Any],
    scanner: Any,
) -> None:
    if not controller._is_current_scan_operation(cancel_event):
        return

    controller._movie_preview_items = items
    controller._build_movie_library_states(items, scanner)
    controller.sync_queued_states()

    if not items:
        controller._set_progress(
            ScanLifecycle.WARNING,
            phase="No movie files found",
            message="No movie files found",
        )
    else:
        controller._set_progress(
            ScanLifecycle.READY,
            phase="Movie scan complete",
            message=f"Found {len(items)} movie file(s)",
        )

    controller._notify("library_changed", controller._movie_library_states)
    controller._notify("scan_complete", None)
    controller._finish_scan_operation(cancel_event)