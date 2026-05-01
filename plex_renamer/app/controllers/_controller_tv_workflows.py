"""TV-specific workflow routing for MediaController."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...engine import (
    ScanState,
)
from ._controller_match_helpers import assign_controller_season, rematch_controller_tv_state
from ._controller_state_helpers import accept_tv_show_session
from ._single_show_scan_helpers import start_single_show_scan
from ._tab_session_helpers import restore_tv_session, snapshot_tv_session
from ._tv_batch_helpers import scan_all_tv_batch_shows, start_tv_batch_session


class MediaControllerTVWorkflow:
    def __init__(self, controller: Any) -> None:
        self._controller = controller

    def accept_show(
        self,
        folder: Path,
        tmdb: Any,
        show_info: dict,
        *,
        scanner_factory: Any,
    ) -> ScanState:
        return accept_tv_show_session(
            self._controller,
            folder,
            tmdb,
            show_info,
            scanner_factory=scanner_factory,
        )

    def start_batch(
        self,
        folder: Path,
        tmdb: Any,
    ) -> None:
        start_tv_batch_session(
            self._controller,
            folder,
            tmdb,
            self._controller._tv_discovery,
        )

    def scan_all_shows(self) -> None:
        scan_all_tv_batch_shows(self._controller)

    def scan_show(
        self,
        state: ScanState,
        tmdb: Any,
        *,
        scanner_factory: Any,
        duplicate_checker: Any,
    ) -> None:
        if hasattr(self._controller, "invalidate_episode_guide"):
            self._controller.invalidate_episode_guide(state)
        start_single_show_scan(
            self._controller,
            state,
            tmdb,
            scanner_factory=scanner_factory,
            duplicate_checker=duplicate_checker,
        )

    def assign_season(self, state: ScanState, season_num: int | None) -> ScanState:
        return assign_controller_season(self._controller, state, season_num)

    def rematch_state(
        self,
        state: ScanState,
        new_match: dict,
        *,
        tmdb: Any | None = None,
        best_tv_match_title: Any,
        extract_year: Any,
        score_tv_results: Any,
        score_results: Any,
        pick_alternate_matches: Any,
    ) -> ScanState:
        return rematch_controller_tv_state(
            self._controller,
            state,
            new_match,
            tmdb=tmdb,
            best_tv_match_title=best_tv_match_title,
            extract_year=extract_year,
            score_tv_results=score_tv_results,
            score_results=score_results,
            pick_alternate_matches=pick_alternate_matches,
        )

    def snapshot_for_tab_switch(self) -> dict:
        controller = self._controller
        return snapshot_tv_session(
            controller._batch_mode,
            controller._batch_states,
            controller._active_scan,
            controller._batch_orchestrator,
            controller._tv_root_folder,
            controller._library_selected_index,
        )

    def restore_from_tab_switch(self, snapshot: dict) -> None:
        restore_tv_session(self._controller, snapshot)
