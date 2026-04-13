"""Duplicate-labeling helpers for batch TV discovery."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from .models import ScanState


def normalized_relative_folder(relative_folder: str, fallback: Path) -> str:
    text = relative_folder or fallback.as_posix()
    return text.replace("\\", "/").casefold()


def duplicate_priority(state: ScanState) -> tuple[float, int, int, str]:
    normalized_relative = normalized_relative_folder(
        state.relative_folder,
        state.folder,
    )
    depth = len(PurePosixPath(normalized_relative).parts)
    evidence_rank = 0 if state.has_direct_season_subdirs else 1
    return (-state.confidence, depth, evidence_rank, normalized_relative)


def apply_duplicate_labels(states: list[ScanState]) -> None:
    """Mark lower-priority TMDB matches as duplicates deterministically.

    Two states with the same TMDB ID are considered duplicates UNLESS
    both have an explicit (non-None) season_assignment that differs —
    in that case they represent distinct seasons discovered as separate
    folders and should coexist.
    """
    for state in states:
        state.duplicate_of = None
        state.duplicate_of_relative_folder = None

    groups: dict[int, list[ScanState]] = {}
    for state in states:
        show_id = state.show_id
        if show_id is None:
            continue
        groups.setdefault(show_id, []).append(state)

    for group in groups.values():
        if len(group) < 2:
            continue
        group.sort(key=duplicate_priority)
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
            state.duplicate_of_relative_folder = existing.relative_folder or None
            state.checked = False