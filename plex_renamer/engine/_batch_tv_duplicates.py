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
    represented_count = len({season for season in _effective_seasons(state) if season is not None})
    evidence_rank = 0 if state.has_direct_season_subdirs or state.season_folders else 1
    return (-represented_count, -state.confidence, depth, evidence_rank, normalized_relative)


def _effective_seasons(state: ScanState) -> set[int | None]:
    """Season keys for duplicate bucketing.

    Prefers the explicit assignment; falls back to the single dominant
    season in scan results so a post-scan None-assignment state that
    resolved cleanly to one season is bucketed against other states for
    the same season rather than colliding with arbitrary explicit ones.
    Multi-season states reserve every season they represent so explicit
    same-season siblings become duplicates instead of independent cards.
    """
    if state.season_assignment is not None:
        return {state.season_assignment}
    if state.season_folders:
        return set(state.season_folders)
    if not state.preview_items:
        return {None}
    detected = {
        item.season
        for item in state.preview_items
        if item.status == "OK" and item.season is not None and item.season > 0
    }
    if len(detected) == 1:
        return {next(iter(detected))}
    return {None}


def apply_duplicate_labels(states: list[ScanState]) -> None:
    """Mark lower-priority TMDB matches as duplicates deterministically.

    Two states with the same TMDB ID are considered duplicates UNLESS
    they resolve to distinct seasons — either via explicit
    ``season_assignment`` or via a post-scan single-dominant season in
    ``preview_items``.  States whose effective season cannot be pinned
    share a single None-keyed slot so a pre-scan None-assignment does
    not collide with an unrelated explicit-season primary.
    """
    for state in states:
        state.duplicate_of = None
        state.duplicate_of_relative_folder = None

    groups: dict[tuple[str, int], list[ScanState]] = {}
    for state in states:
        key = state.provider_show_key
        if key is None:
            continue
        groups.setdefault(key, []).append(state)

    for group in groups.values():
        if len(group) < 2:
            continue
        group.sort(key=duplicate_priority)
        primaries: dict[int | None, ScanState] = {}
        for state in group:
            effective_seasons = _effective_seasons(state)
            existing = next(
                (
                    primaries[season]
                    for season in sorted(
                        effective_seasons, key=lambda value: (value is None, value or 0)
                    )
                    if season in primaries
                ),
                None,
            )
            if existing is None:
                for season in effective_seasons:
                    primaries.setdefault(season, state)
                continue
            state.duplicate_of = existing.display_name
            state.duplicate_of_relative_folder = existing.relative_folder or None
            state.checked = False
