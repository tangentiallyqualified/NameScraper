"""Helpers for controller-owned session routing and selection state."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from ...constants import MediaType
from ...engine import PreviewItem, ScanState
from ._job_projection_helpers import apply_completed_job_projection, sync_queued_state_flags
from ._tv_state_helpers import build_accepted_tv_state
from ..models import ScanLifecycle


class _ControllerSessionState(Protocol):
    _batch_mode: bool
    _batch_states: list[ScanState]
    _active_scan: ScanState | None
    _batch_orchestrator: Any
    _tv_root_folder: Path | None
    _movie_library_states: list[ScanState]
    _movie_preview_items: list[PreviewItem]
    _active_content_mode: MediaType
    _active_library_mode: MediaType | None
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


def routed_library_states(controller: _ControllerSessionState) -> list[ScanState]:
    if controller._active_library_mode == MediaType.MOVIE:
        return controller._movie_library_states
    return controller._batch_states


def accept_tv_show_session(
    controller: _ControllerSessionState,
    folder: Path,
    tmdb: Any,
    show_info: dict,
    *,
    scanner_factory: Callable[..., Any],
) -> ScanState:
    controller._batch_mode = False
    controller._batch_orchestrator = None
    controller._active_content_mode = MediaType.TV
    controller._active_library_mode = MediaType.TV
    controller._tv_root_folder = folder

    state = build_accepted_tv_state(folder, tmdb, show_info, scanner_factory)
    controller._active_scan = state
    controller._batch_states = [state]
    controller._library_selected_index = 0

    controller._set_progress(
        ScanLifecycle.SCANNING,
        phase="Scanning TV files...",
        message="Scanning TV files...",
    )
    controller._notify("mode_changed", controller._active_content_mode, controller._active_library_mode)
    controller._notify("library_changed", controller._batch_states)
    return state


def select_library_show(
    controller: _ControllerSessionState,
    index: int,
) -> ScanState | None:
    states = routed_library_states(controller)
    if index < 0 or index >= len(states):
        return None

    controller._library_selected_index = index
    if controller._active_content_mode == MediaType.TV:
        controller._active_scan = states[index]
    return states[index]


def apply_completed_job_to_session(
    controller: _ControllerSessionState,
    job: Any,
) -> bool:
    states = controller._movie_library_states if job.media_type == MediaType.MOVIE else controller._batch_states
    projection = apply_completed_job_projection(job, states, controller._movie_preview_items)
    if projection.movie_preview_items is not None:
        controller._movie_preview_items = projection.movie_preview_items
    return projection.changed


def sync_controller_queued_states(
    controller: _ControllerSessionState,
    queue_jobs: list[Any],
) -> None:
    sync_queued_state_flags(
        queue_jobs,
        controller._batch_states,
        controller._movie_library_states,
    )
