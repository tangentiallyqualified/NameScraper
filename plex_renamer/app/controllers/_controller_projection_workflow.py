"""Completed-job projection and queued-state sync for MediaController."""

from __future__ import annotations

from typing import Any, Protocol

from ...constants import MediaType
from ...engine import PreviewItem, ScanState
from ._job_projection_helpers import apply_completed_job_projection, sync_queued_state_flags


class _ProjectionController(Protocol):
    _job_store: Any
    _batch_states: list[ScanState]
    _movie_library_states: list[ScanState]
    _movie_preview_items: list[PreviewItem]


class MediaControllerProjectionWorkflow:
    def __init__(self, controller: _ProjectionController) -> None:
        self._controller = controller

    def apply_completed_job_to_state(self, job: Any) -> bool:
        states = self._controller._movie_library_states if job.media_type == MediaType.MOVIE else self._controller._batch_states
        projection = apply_completed_job_projection(
            job,
            states,
            self._controller._movie_preview_items,
        )
        if projection.movie_preview_items is not None:
            self._controller._movie_preview_items = projection.movie_preview_items
        return projection.changed

    def sync_queued_states(self) -> None:
        sync_queued_state_flags(
            self._controller._job_store.get_queue(),
            self._controller._batch_states,
            self._controller._movie_library_states,
        )