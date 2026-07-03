"""Match-selection helpers for batch TV discovery."""

from __future__ import annotations

from pathlib import Path

from ..parsing import clean_folder_name, get_season, normalize_for_match
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


def _season_episode_count(details: dict, explicit_seasons: set[int]) -> int | None:
    """Sum TMDB ``episode_count`` over *explicit_seasons*.

    Returns ``None`` when none of the requested seasons are present in the
    details payload, so the caller can fall back to the whole-show count.
    """
    seasons = details.get("seasons") or []
    total = 0
    matched = False
    for season in seasons:
        number = season.get("season_number")
        if number in explicit_seasons:
            total += season.get("episode_count") or 0
            matched = True
    return total if matched else None


def episode_count_tiebreak(
    tmdb: TMDBClient,
    scored: list[tuple[dict, float]],
    file_count: int,
    threshold: float = 0.10,
    compare_seasons: bool = False,
    explicit_seasons: set[int] | None = None,
) -> tuple[dict, float, bool]:
    """Re-rank near-tied TMDB candidates by episode/season count proximity.

    When *explicit_seasons* is supplied (and we are comparing episode counts,
    not season counts), each candidate's count is taken from just those
    seasons. This avoids comparing a single-season folder's file count against
    a multi-season show's whole-show episode total — the Euphoria S01 bug,
    where the wrong show's total (10) was closer to 8 files than the correct
    show's total (24), even though the correct show's S1 has exactly 8.

    Returns ``(best, score, discriminated)``; *discriminated* is True when
    the winner's count distance is strictly better than every other
    contender's — real identity evidence that should also break a same-name
    tie (RC38), not just reorder it.
    """
    detail_key = "number_of_seasons" if compare_seasons else "number_of_episodes"
    use_season_subset = bool(explicit_seasons) and not compare_seasons
    top_score = scored[0][1]
    contenders: list[tuple[dict, float, int, bool]] = []

    unaired_statuses = {"Planned", "In Production"}

    for result, score in scored:
        if top_score - score > threshold:
            break
        show_id = result.get("id")
        if show_id is None:
            continue
        details = tmdb.get_tv_details(show_id) or {}
        count = details.get(detail_key) or 0
        if use_season_subset:
            season_count = _season_episode_count(details, explicit_seasons)
            if season_count is not None:
                count = season_count
        unaired = (
            not details.get("first_air_date")
            or details.get("status") in unaired_statuses
        )
        contenders.append((result, score, count, unaired))

    if not contenders:
        return scored[0][0], scored[0][1], False

    best = min(
        contenders,
        key=lambda candidate: (candidate[3], abs(candidate[2] - file_count), -candidate[1]),
    )
    best_distance = abs(best[2] - file_count)
    discriminated = len(contenders) >= 2 and all(
        abs(candidate[2] - file_count) > best_distance
        for candidate in contenders
        if candidate[0] is not best[0]
    )
    return best[0], best[1], discriminated


def primary_name_breaks_tie(
    best: dict,
    runner_up: dict,
    query_name: str,
    year_hint: str | None,
) -> bool:
    """True when the winner's identity evidence clearly beats the runner-up's.

    Alt-title and episode-evidence boosts can level a franchise spin-off
    ("Watchmen: Motion Comic", alt-titled just "Watchmen") with the show whose
    PRIMARY name is the query; both saturate near 1.0 and the near-zero margin
    reads as a tie. An exact primary-name match the runner-up lacks resolves
    that tie — unless a year hint argues for the runner-up instead.
    """
    query_norm = normalize_for_match(
        clean_folder_name(query_name, include_year=False),
    )
    if not query_norm:
        return False
    best_exact = normalize_for_match(best.get("name") or "") == query_norm
    runner_exact = normalize_for_match(runner_up.get("name") or "") == query_norm
    if not best_exact or runner_exact:
        return False
    if year_hint and best.get("year") and runner_up.get("year"):
        try:
            best_diff = abs(int(best["year"]) - int(year_hint))
            runner_diff = abs(int(runner_up["year"]) - int(year_hint))
        except (ValueError, TypeError):
            return True
        return best_diff <= runner_diff
    return True