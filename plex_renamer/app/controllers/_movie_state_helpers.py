"""Helpers for building and updating movie scan-state rows."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from ...constants import MediaType
from ...engine import MovieScanner, PreviewItem, ScanState


def build_movie_library_states(
    items: list[PreviewItem],
    scanner: MovieScanner,
    movie_folder: Path | None,
) -> list[ScanState]:
    states: list[ScanState] = []
    for item in items:
        if item.media_type != MediaType.MOVIE:
            continue

        chosen = scanner.movie_info.get(item.original, {})
        media_id = chosen.get("id", item.media_id)
        search_results = scanner.get_search_results(item.original)
        media_info = {
            "id": media_id,
            "title": chosen.get("title") or item.media_name or item.original.stem,
            "year": chosen.get("year", ""),
            "poster_path": chosen.get("poster_path"),
            "overview": chosen.get("overview", ""),
            "_media_type": MediaType.MOVIE,
        }
        confidence = 1.0 if media_id else 0.0
        if item.status.startswith("REVIEW"):
            confidence = 0.5 if media_id else 0.0

        state = ScanState(
            folder=item.original.parent,
            source_file=item.original,
            media_info=media_info,
            preview_items=[item],
            confidence=confidence,
            search_results=search_results,
            alternate_matches=search_results[1:4],
            scanned=True,
            checked=False,
            scanner=scanner,
        )
        states.append(state)

    apply_movie_duplicate_labels(states, movie_folder)
    return states


def apply_movie_duplicate_labels(
    states: list[ScanState],
    movie_folder: Path | None,
) -> None:
    for state in states:
        state.duplicate_of = None
        state.duplicate_of_relative_folder = None

    groups: dict[int, list[ScanState]] = {}
    for state in states:
        media_id = state.show_id
        if media_id is None:
            continue
        groups.setdefault(media_id, []).append(state)

    for group in groups.values():
        if len(group) < 2:
            continue
        group.sort(key=lambda state: _movie_duplicate_priority(state, movie_folder))
        primaries: dict[int | None, ScanState] = {}
        for state in group:
            season_assignment = state.season_assignment
            if season_assignment is not None:
                existing = primaries.get(season_assignment)
                if existing is None:
                    primaries[season_assignment] = state
                    continue
            else:
                existing = next(iter(primaries.values()), None) if primaries else None
                if existing is None:
                    primaries[None] = state
                    continue
            state.duplicate_of = existing.display_name
            state.duplicate_of_relative_folder = movie_state_relative_folder(existing, movie_folder)
            state.checked = False


def movie_state_relative_folder(state: ScanState, movie_folder: Path | None) -> str:
    try:
        if movie_folder is not None:
            return state.folder.relative_to(movie_folder).as_posix()
        return state.folder.as_posix()
    except ValueError:
        return state.folder.as_posix()


def set_actionable_preview_checks(state: ScanState, checked: bool) -> None:
    state.checked = checked
    for index, item in enumerate(state.preview_items):
        binding = state.check_vars.get(str(index))
        if binding is None or not hasattr(binding, "set"):
            continue
        binding.set(bool(checked and item.is_actionable))


def resolve_movie_preview_review(
    state: ScanState,
    preview_items: list[PreviewItem],
) -> None:
    if len(state.preview_items) != 1:
        return
    item = state.preview_items[0]
    if item.media_type != MediaType.MOVIE or not item.status.startswith("REVIEW"):
        return

    item.status = "OK"
    state.confidence = max(state.confidence, 1.0)

    for candidate in preview_items:
        if candidate.original == item.original:
            candidate.status = "OK"
            break


def _movie_duplicate_priority(
    state: ScanState,
    movie_folder: Path | None,
) -> tuple[int, float, int, str, str]:
    item = state.preview_items[0] if state.preview_items else None
    ready_rank = 0 if item is not None and not item.is_actionable else 1
    relative_folder = movie_state_relative_folder(state, movie_folder)
    depth = len(PurePosixPath(relative_folder.replace("\\", "/")).parts)
    original_name = item.original.name.casefold() if item is not None else state.folder.name.casefold()
    return (
        ready_rank,
        -state.confidence,
        depth,
        relative_folder.replace("\\", "/").casefold(),
        original_name,
    )
