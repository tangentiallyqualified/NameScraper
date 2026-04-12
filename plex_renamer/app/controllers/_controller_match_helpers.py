"""Helpers for controller-owned match mutation workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from ...constants import MediaType
from ...engine import PreviewItem, ScanState
from ._match_state_helpers import (
    approve_scan_match,
    assign_state_season,
    rematch_movie_scan_state,
    rematch_tv_scan_state,
)
from ._movie_state_helpers import (
    apply_movie_duplicate_labels,
    resolve_movie_preview_review,
    set_actionable_preview_checks,
)


class _MatchStateController(Protocol):
    _active_library_mode: MediaType | None
    _batch_states: list[ScanState]
    _batch_orchestrator: Any
    _movie_library_states: list[ScanState]
    _movie_preview_items: list[PreviewItem]
    _movie_scanner: Any
    _movie_folder: Path | None

    def _notify(self, event: str, *args: Any) -> None: ...


def approve_controller_match(
    controller: _MatchStateController,
    state: ScanState,
) -> None:
    if not approve_scan_match(
        state,
        resolve_movie_preview_review=lambda candidate: resolve_movie_preview_review(
            candidate,
            controller._movie_preview_items,
        ),
        set_actionable_preview_checks=set_actionable_preview_checks,
    ):
        return
    controller._notify("library_changed", routed_library_states(controller))


def assign_controller_season(
    controller: _MatchStateController,
    state: ScanState,
    season_num: int | None,
) -> ScanState:
    result = assign_state_season(
        state,
        season_num,
        batch_states=controller._batch_states,
        batch_orchestrator=controller._batch_orchestrator,
        movie_library_states=controller._movie_library_states,
        apply_movie_duplicate_labels=lambda states: apply_movie_duplicate_labels(
            states,
            controller._movie_folder,
        ),
    )
    controller._batch_states = result.batch_states
    controller._notify("library_changed", routed_library_states(controller))
    return result.effective_state


def rematch_controller_tv_state(
    controller: _MatchStateController,
    state: ScanState,
    new_match: dict,
    *,
    tmdb: Any | None,
    best_tv_match_title: Any,
    extract_year: Any,
    score_tv_results: Any,
    score_results: Any,
    pick_alternate_matches: Any,
) -> ScanState:
    result = rematch_tv_scan_state(
        state,
        new_match,
        batch_states=controller._batch_states,
        batch_orchestrator=controller._batch_orchestrator,
        tmdb=tmdb,
        best_tv_match_title=best_tv_match_title,
        extract_year=extract_year,
        score_tv_results=score_tv_results,
        score_results=score_results,
        pick_alternate_matches=pick_alternate_matches,
    )
    controller._batch_states = result.batch_states
    controller._notify("library_changed", routed_library_states(controller))
    return result.effective_state


def rematch_controller_movie_state(
    controller: _MatchStateController,
    state: ScanState,
    new_match: dict,
    *,
    clean_folder_name: Any,
    extract_year: Any,
    score_results: Any,
) -> None:
    result = rematch_movie_scan_state(
        state,
        new_match,
        movie_preview_items=controller._movie_preview_items,
        movie_scanner=controller._movie_scanner,
        clean_folder_name=clean_folder_name,
        extract_year=extract_year,
        score_results=score_results,
    )
    controller._movie_preview_items = result.movie_preview_items
    controller._notify("library_changed", routed_library_states(controller))


def routed_library_states(controller: _MatchStateController) -> list[ScanState]:
    if controller._active_library_mode == MediaType.MOVIE:
        return controller._movie_library_states
    return controller._batch_states
