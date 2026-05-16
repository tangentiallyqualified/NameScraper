"""Match-selection helpers for batch TV discovery."""

from __future__ import annotations

from pathlib import Path

from ..parsing import get_season
from ..tmdb import TMDBClient


def count_season_subdirs(folder: Path) -> int:
    """Count Season NN subdirectories to estimate episode volume."""
    count = 0
    try:
        for child in folder.iterdir():
            if child.is_dir() and get_season(child) is not None:
                count += 1
    except OSError:
        pass
    return count


def episode_count_tiebreak(
    tmdb: TMDBClient,
    scored: list[tuple[dict, float]],
    file_count: int,
    threshold: float = 0.10,
    compare_seasons: bool = False,
) -> tuple[dict, float]:
    """Re-rank near-tied TMDB candidates by episode/season count proximity."""
    detail_key = "number_of_seasons" if compare_seasons else "number_of_episodes"
    top_score = scored[0][1]
    contenders: list[tuple[dict, float, int, bool]] = []

    unaired_statuses = {"Planned", "In Production"}

    for result, score in scored:
        if top_score - score > threshold:
            break
        show_id = result.get("id")
        if show_id is None:
            continue
        details = tmdb.get_tv_details(show_id)
        count = (details or {}).get(detail_key) or 0
        unaired = (
            not (details or {}).get("first_air_date")
            or (details or {}).get("status") in unaired_statuses
        )
        contenders.append((result, score, count, unaired))

    if not contenders:
        return scored[0]

    best = min(
        contenders,
        key=lambda candidate: (candidate[3], abs(candidate[2] - file_count), -candidate[1]),
    )
    return best[0], best[1]