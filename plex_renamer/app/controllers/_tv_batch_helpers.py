"""Helpers for TV batch discovery and bulk episode scans."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Protocol

from ...constants import MediaType
from ...engine import BatchTVOrchestrator, ScanCancelledError, ScanState
from ...thread_pool import submit as _submit_bg
from ..models import ScanLifecycle
from ..services.tv_library_discovery_service import TVLibraryDiscoveryService

_log = logging.getLogger(__name__)


class _TVBatchController(Protocol):
    _batch_mode: bool
    _active_content_mode: MediaType
    _active_library_mode: MediaType | None
    _tv_root_folder: Path | None
    _batch_orchestrator: BatchTVOrchestrator | None
    _batch_states: list[ScanState]
    _active_scan: ScanState | None
    _library_selected_index: int | None

    @property
    def command_gating(self) -> Any: ...

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

    def sync_queued_states(self) -> None: ...


def start_tv_batch_session(
    controller: _TVBatchController,
    folder: Path,
    tmdb: Any,
    discovery_service: TVLibraryDiscoveryService,
) -> None:
    controller._batch_mode = True
    controller._active_content_mode = MediaType.TV
    controller._active_library_mode = MediaType.TV
    controller._tv_root_folder = folder
    controller._batch_orchestrator = BatchTVOrchestrator(
        tmdb,
        folder,
        discovery_service=discovery_service,
    )
    controller._batch_states = []
    controller._active_scan = None
    controller._library_selected_index = None

    controller._set_progress(
        ScanLifecycle.DISCOVERING,
        phase="Discovering shows...",
        message="Discovering shows...",
    )
    controller._notify("mode_changed", controller._active_content_mode, controller._active_library_mode)

    orchestrator = controller._batch_orchestrator
    cancel_event = controller._begin_scan_operation()

    def _progress(done: int, total: int) -> None:
        if cancel_event.is_set():
            raise ScanCancelledError("Scan cancelled")
        controller._set_progress(
            ScanLifecycle.MATCHING,
            phase="Matching shows...",
            done=done,
            total=total,
            message=f"Matching shows... {done}/{total}",
        )

    def _worker() -> None:
        try:
            states = orchestrator.discover_shows(
                progress_callback=_progress,
                cancel_event=cancel_event,
            )
        except ScanCancelledError:
            _cancel_tv_batch_discovery(controller, cancel_event)
            return
        except Exception as exc:
            _fail_tv_batch_discovery(controller, cancel_event, exc)
            return

        _complete_tv_batch_discovery(controller, cancel_event, states)

    _submit_bg(_worker)


def scan_all_tv_batch_shows(controller: _TVBatchController) -> None:
    orchestrator = controller._batch_orchestrator
    if orchestrator is None:
        return

    unscanned = _collect_unscanned_batch_states(controller._batch_states)
    if not unscanned:
        return

    controller._set_progress(
        ScanLifecycle.SCANNING,
        phase="Scanning episodes...",
        message="Scanning episodes...",
    )
    cancel_event = controller._begin_scan_operation()

    def _progress(done: int, total: int) -> None:
        if cancel_event.is_set():
            raise ScanCancelledError("Scan cancelled")
        current_name = _current_batch_scan_name(controller._batch_states, done)
        controller._set_progress(
            ScanLifecycle.SCANNING,
            phase="Scanning episodes...",
            done=done,
            total=total,
            current_item=current_name or None,
            message=f"Scanning episodes... {done}/{total}"
            + (f" — {current_name}" if current_name else ""),
        )

    def _worker() -> None:
        try:
            orchestrator.scan_all(
                progress_callback=_progress,
                cancel_event=cancel_event,
            )
        except ScanCancelledError:
            _cancel_tv_bulk_scan(controller, cancel_event)
            return
        except Exception as exc:
            if not controller._is_current_scan_operation(cancel_event):
                return
            _log.exception("Batch scan failed: %s", exc)
            controller._finish_scan_operation(cancel_event)
            return

        _complete_tv_bulk_scan(controller, cancel_event)

    _submit_bg(_worker)


def _cancel_tv_batch_discovery(
    controller: _TVBatchController,
    cancel_event: threading.Event,
) -> None:
    if not controller._is_current_scan_operation(cancel_event):
        return
    controller._batch_states = []
    controller._active_scan = None
    controller._library_selected_index = None
    controller._set_progress(
        ScanLifecycle.CANCELLED,
        phase="TV discovery cancelled",
        message="TV discovery cancelled.",
    )
    controller._notify("library_changed", controller._batch_states)
    controller._finish_scan_operation(cancel_event)


def _fail_tv_batch_discovery(
    controller: _TVBatchController,
    cancel_event: threading.Event,
    exc: Exception,
) -> None:
    if not controller._is_current_scan_operation(cancel_event):
        return
    _log.exception("TV batch discovery failed: %s", exc)
    controller._set_progress(
        ScanLifecycle.FAILED,
        phase="Discovery failed.",
        message=f"Discovery failed: {exc}",
    )
    controller._finish_scan_operation(cancel_event)


def _complete_tv_batch_discovery(
    controller: _TVBatchController,
    cancel_event: threading.Event,
    states: list[ScanState] | None,
) -> None:
    if not controller._is_current_scan_operation(cancel_event):
        return

    controller._batch_states = states or []
    if not controller._batch_states:
        controller._set_progress(
            ScanLifecycle.WARNING,
            phase="No TV shows found in this folder.",
            message="No TV shows found in this folder.",
        )
        controller._notify("library_changed", controller._batch_states)
        controller._finish_scan_operation(cancel_event)
        return

    controller.sync_queued_states()

    needs_review = sum(1 for state in controller._batch_states if state.needs_review)
    controller._set_progress(
        ScanLifecycle.READY,
        phase="Discovery complete",
        message=(
            f"Found {len(controller._batch_states)} shows"
            + (f" — {needs_review} need review" if needs_review else "")
            + " — scanning episodes..."
        ),
    )
    controller._notify("library_changed", controller._batch_states)
    controller._notify("scan_complete", None)
    controller._finish_scan_operation(cancel_event)


def _cancel_tv_bulk_scan(
    controller: _TVBatchController,
    cancel_event: threading.Event,
) -> None:
    if not controller._is_current_scan_operation(cancel_event):
        return

    _clear_plex_ready_checks(controller)
    scanned, total_files = _summarize_scanned_batch_states(controller._batch_states)
    controller._set_progress(
        ScanLifecycle.CANCELLED,
        phase="Batch scan cancelled",
        message=f"Cancelled after scanning {scanned} show(s) — {total_files} total files",
    )
    controller._notify("library_changed", controller._batch_states)
    controller._finish_scan_operation(cancel_event)


def _complete_tv_bulk_scan(
    controller: _TVBatchController,
    cancel_event: threading.Event,
) -> None:
    if not controller._is_current_scan_operation(cancel_event):
        return

    _clear_plex_ready_checks(controller)
    scanned, total_files = _summarize_scanned_batch_states(controller._batch_states)
    controller._set_progress(
        ScanLifecycle.READY,
        phase="Batch scan complete",
        message=f"Scanned {scanned} shows — {total_files} total files",
    )
    controller._notify("library_changed", controller._batch_states)
    controller._finish_scan_operation(cancel_event)


def _clear_plex_ready_checks(controller: _TVBatchController) -> None:
    for state in controller._batch_states:
        if controller.command_gating.is_plex_ready_state(state):
            state.checked = False


def _collect_unscanned_batch_states(states: list[ScanState]) -> list[ScanState]:
    return [
        state for state in states
        if not state.scanned and state.show_id is not None
    ]


def _current_batch_scan_name(states: list[ScanState], done: int) -> str:
    current_name = ""
    to_scan = _collect_unscanned_batch_states(states)
    if 0 < done <= len(to_scan):
        current_name = to_scan[done - 1].display_name
    return current_name


def _summarize_scanned_batch_states(states: list[ScanState]) -> tuple[int, int]:
    scanned = sum(1 for state in states if state.scanned)
    total_files = sum(state.file_count for state in states if state.scanned)
    return scanned, total_files