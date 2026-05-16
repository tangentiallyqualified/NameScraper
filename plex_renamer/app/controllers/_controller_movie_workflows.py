"""Movie-specific workflow routing for MediaController."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...engine import MovieScanner, PreviewItem, ScanState
from ._controller_match_helpers import rematch_controller_movie_state
from ._movie_batch_helpers import start_movie_batch_session
from ._movie_state_helpers import build_movie_library_states
from ._tab_session_helpers import restore_movie_session, snapshot_movie_session


class MediaControllerMovieWorkflow:
    def __init__(self, controller: Any) -> None:
        self._controller = controller

    def start_batch(
        self,
        folder: Path,
        tmdb: Any,
        *,
        scanner_factory: Any,
    ) -> None:
        start_movie_batch_session(self._controller, folder, tmdb, scanner_factory)

    def build_library_states(
        self,
        items: list[PreviewItem],
        scanner: MovieScanner,
    ) -> None:
        self._controller._movie_library_states = build_movie_library_states(
            items,
            scanner,
            self._controller._movie_folder,
        )

    def rematch_state(
        self,
        state: ScanState,
        new_match: dict,
        *,
        clean_folder_name: Any,
        extract_year: Any,
        score_results: Any,
    ) -> None:
        rematch_controller_movie_state(
            self._controller,
            state,
            new_match,
            clean_folder_name=clean_folder_name,
            extract_year=extract_year,
            score_results=score_results,
        )

    def snapshot_for_tab_switch(self) -> dict:
        controller = self._controller
        return snapshot_movie_session(
            controller._movie_library_states,
            controller._movie_preview_items,
            controller._movie_scanner,
            controller._movie_folder,
            controller._movie_media_info,
            controller._library_selected_index,
        )

    def restore_from_tab_switch(self, snapshot: dict) -> None:
        restore_movie_session(self._controller, snapshot)