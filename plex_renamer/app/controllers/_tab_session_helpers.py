"""Helpers for in-memory TV and movie tab session snapshots."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol, TypedDict

from ...constants import MediaType
from ...engine import BatchTVOrchestrator, MovieScanner, PreviewItem, ScanState


class TVTabSnapshot(TypedDict):
    batch_mode: bool
    batch_states: list[ScanState]
    active_scan: ScanState | None
    batch_orchestrator: BatchTVOrchestrator | None
    tv_root_folder: Path | None
    library_selected_index: int | None


class MovieTabSnapshot(TypedDict):
    movie_library_states: list[ScanState]
    movie_preview_items: list[PreviewItem]
    movie_scanner: MovieScanner | None
    movie_folder: Path | None
    movie_media_info: dict | None
    library_selected_index: int | None


class _TVSessionController(Protocol):
    _batch_mode: bool
    _batch_states: list[ScanState]
    _active_scan: ScanState | None
    _batch_orchestrator: BatchTVOrchestrator | None
    _tv_root_folder: Path | None
    _library_selected_index: int | None
    _active_content_mode: MediaType
    _active_library_mode: MediaType | None

    def sync_queued_states(self) -> None: ...

    def _notify(self, event: str, *args: Any) -> None: ...


class _MovieSessionController(Protocol):
    _movie_library_states: list[ScanState]
    _movie_preview_items: list[PreviewItem]
    _movie_scanner: MovieScanner | None
    _movie_folder: Path | None
    _movie_media_info: dict | None
    _library_selected_index: int | None
    _active_content_mode: MediaType
    _active_library_mode: MediaType | None

    def sync_queued_states(self) -> None: ...

    def _notify(self, event: str, *args: Any) -> None: ...


def snapshot_tv_session(
    batch_mode: bool,
    batch_states: list[ScanState],
    active_scan: ScanState | None,
    batch_orchestrator: BatchTVOrchestrator | None,
    tv_root_folder: Path | None,
    library_selected_index: int | None,
) -> TVTabSnapshot:
    return {
        "batch_mode": batch_mode,
        "batch_states": batch_states,
        "active_scan": active_scan,
        "batch_orchestrator": batch_orchestrator,
        "tv_root_folder": tv_root_folder,
        "library_selected_index": library_selected_index,
    }


def restore_tv_session(
    controller: _TVSessionController,
    snapshot: Mapping[str, Any],
) -> None:
    controller._batch_mode = snapshot.get("batch_mode", False)
    controller._batch_states = snapshot.get("batch_states", [])
    controller._active_scan = snapshot.get("active_scan")
    controller._batch_orchestrator = snapshot.get("batch_orchestrator")
    controller._tv_root_folder = snapshot.get("tv_root_folder")
    controller._library_selected_index = snapshot.get("library_selected_index")
    controller._active_content_mode = MediaType.TV
    controller._active_library_mode = MediaType.TV
    controller.sync_queued_states()
    controller._notify("mode_changed", controller._active_content_mode, controller._active_library_mode)
    controller._notify("library_changed", controller._batch_states)


def snapshot_movie_session(
    movie_library_states: list[ScanState],
    movie_preview_items: list[PreviewItem],
    movie_scanner: MovieScanner | None,
    movie_folder: Path | None,
    movie_media_info: dict | None,
    library_selected_index: int | None,
) -> MovieTabSnapshot:
    return {
        "movie_library_states": movie_library_states,
        "movie_preview_items": movie_preview_items,
        "movie_scanner": movie_scanner,
        "movie_folder": movie_folder,
        "movie_media_info": movie_media_info,
        "library_selected_index": library_selected_index,
    }


def restore_movie_session(
    controller: _MovieSessionController,
    snapshot: Mapping[str, Any],
) -> None:
    controller._movie_library_states = snapshot.get("movie_library_states", [])
    controller._movie_preview_items = snapshot.get("movie_preview_items", [])
    controller._movie_scanner = snapshot.get("movie_scanner")
    controller._movie_folder = snapshot.get("movie_folder")
    controller._movie_media_info = snapshot.get("movie_media_info")
    controller._library_selected_index = snapshot.get("library_selected_index")
    controller._active_content_mode = MediaType.MOVIE
    controller._active_library_mode = MediaType.MOVIE
    controller.sync_queued_states()
    controller._notify("mode_changed", controller._active_content_mode, controller._active_library_mode)
    controller._notify("library_changed", controller._movie_library_states)