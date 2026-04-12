"""Helpers for approve, season assignment, and rematch state transitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...constants import MediaType
from ...engine import PreviewItem, ScanState


@dataclass(frozen=True, slots=True)
class SeasonAssignmentResult:
    effective_state: ScanState
    batch_states: list[ScanState]


@dataclass(frozen=True, slots=True)
class TVRematchResult:
    effective_state: ScanState
    batch_states: list[ScanState]


@dataclass(frozen=True, slots=True)
class MovieRematchResult:
    movie_preview_items: list[PreviewItem]


def approve_scan_match(
    state: ScanState,
    *,
    resolve_movie_preview_review: Any,
    set_actionable_preview_checks: Any,
) -> bool:
    if (
        state.show_id is None
        or state.queued
        or state.scanning
        or state.duplicate_of is not None
    ):
        return False
    state.match_origin = "manual"
    resolve_movie_preview_review(state)
    set_actionable_preview_checks(state, True)
    return True


def assign_state_season(
    state: ScanState,
    season_num: int | None,
    *,
    batch_states: list[ScanState],
    batch_orchestrator: Any,
    movie_library_states: list[ScanState],
    apply_movie_duplicate_labels: Any,
) -> SeasonAssignmentResult:
    state.season_assignment = season_num
    effective_state = state
    updated_batch_states = batch_states

    if batch_orchestrator is not None:
        if season_num is not None and state.show_id is not None:
            state.match_origin = "manual"
            batch_orchestrator.states = batch_states
            effective_state = batch_orchestrator.merge_rematched_state(state)
            updated_batch_states = batch_orchestrator.states
            if effective_state is state:
                state.reset_scan()
        else:
            batch_orchestrator._apply_duplicate_labels()
    elif movie_library_states:
        apply_movie_duplicate_labels(movie_library_states)

    return SeasonAssignmentResult(effective_state, updated_batch_states)


def rematch_tv_scan_state(
    state: ScanState,
    new_match: dict,
    *,
    batch_states: list[ScanState],
    batch_orchestrator: Any,
    tmdb: Any | None,
    best_tv_match_title: Any,
    extract_year: Any,
    score_tv_results: Any,
    score_results: Any,
    pick_alternate_matches: Any,
) -> TVRematchResult:
    state.match_origin = "manual"
    effective_state = state
    updated_batch_states = batch_states

    if batch_orchestrator is not None:
        batch_orchestrator.states = batch_states
        effective_state = batch_orchestrator.rematch_show(state, new_match)
        updated_batch_states = batch_orchestrator.states
    else:
        state.media_info = new_match
        raw_name = best_tv_match_title(state.folder)
        year_hint = extract_year(state.folder.name)
        if tmdb is not None:
            scored = score_tv_results([new_match], raw_name, year_hint, tmdb, folder=state.folder)
        else:
            scored = score_results([new_match], raw_name, year_hint, title_key="name")
        state.confidence = scored[0][1] if scored else 0.0
        state.reset_scan()

    raw_name = best_tv_match_title(state.folder)
    year_hint = extract_year(state.folder.name)
    if tmdb is not None:
        scored = score_tv_results(
            effective_state.search_results,
            raw_name,
            year_hint,
            tmdb,
            folder=state.folder,
        )
    else:
        scored = score_results(
            effective_state.search_results,
            raw_name,
            year_hint,
            title_key="name",
        )
    effective_state.alternate_matches = pick_alternate_matches(
        scored,
        selected_id=effective_state.media_info.get("id"),
        limit=3,
    )
    effective_state.checked = effective_state.show_id is not None and not effective_state.needs_review
    return TVRematchResult(effective_state, updated_batch_states)


def rematch_movie_scan_state(
    state: ScanState,
    new_match: dict,
    *,
    movie_preview_items: list[PreviewItem],
    movie_scanner: Any,
    clean_folder_name: Any,
    extract_year: Any,
    score_results: Any,
) -> MovieRematchResult:
    preview = state.preview_items[0] if state.preview_items else None
    scanner = state.scanner or movie_scanner
    if (
        preview is None
        or scanner is None
        or not hasattr(scanner, "rematch_file")
        or not hasattr(scanner, "get_search_results")
    ):
        raise ValueError("Movie rematch requires an existing preview item and scanner")

    new_item = scanner.rematch_file(preview, new_match)
    raw_name = clean_folder_name(preview.original.stem)
    year_hint = extract_year(preview.original.stem)
    search_results = scanner.get_search_results(preview.original)
    scored = score_results(search_results, raw_name, year_hint, title_key="title")

    state.media_info = {
        "id": new_match.get("id"),
        "title": new_match.get("title") or preview.media_name or preview.original.stem,
        "year": new_match.get("year", ""),
        "poster_path": new_match.get("poster_path"),
        "overview": new_match.get("overview", ""),
        "_media_type": MediaType.MOVIE,
    }
    state.match_origin = "manual"
    state.reset_gui_state()
    state.source_file = new_item.original
    state.preview_items = [new_item]
    state.search_results = search_results
    state.alternate_matches = [
        result
        for result, score in scored
        if result.get("id") != state.media_info.get("id") and score > 0.3
    ][:3]
    state.confidence = (
        scored[0][1]
        if scored and scored[0][0].get("id") == state.media_info.get("id")
        else 1.0
    )
    state.scanned = True
    state.checked = new_item.is_actionable
    state.selected_index = 0 if state.preview_items else None

    updated_movie_preview_items = list(movie_preview_items)
    for index, item in enumerate(updated_movie_preview_items):
        if item.original == preview.original:
            updated_movie_preview_items[index] = new_item
            break

    return MovieRematchResult(updated_movie_preview_items)