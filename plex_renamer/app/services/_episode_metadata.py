"""Episode metadata lookup helpers for guide projection."""

from __future__ import annotations

from typing import cast

from ...engine import ScanState
from ...engine.models import TVScanStateScanner


def episode_meta_value(state: ScanState, key: tuple[int, int], name: str) -> str:
    if state.scanner is None:
        return ""
    scanner = cast(TVScanStateScanner, state.scanner)
    meta = scanner.episode_meta.get(key, {})
    value = meta.get(name, "")
    return str(value) if value else ""


def episode_title(state: ScanState, key: tuple[int, int]) -> str:
    meta_title = episode_meta_value(state, key, "name")
    if meta_title:
        return meta_title
    completeness = state.completeness
    if completeness is None:
        return ""
    season_num, episode = key
    season = completeness.specials if season_num == 0 else completeness.seasons.get(season_num)
    if season is None:
        return ""
    for candidates in (
        season.matched_episodes,
        season.review_episodes,
        season.missing,
    ):
        for candidate_episode, title in candidates:
            if candidate_episode == episode:
                return title
    return ""
