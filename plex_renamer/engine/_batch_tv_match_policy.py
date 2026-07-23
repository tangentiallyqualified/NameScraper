"""Match-selection helpers for batch TV discovery."""

from __future__ import annotations

from pathlib import Path

from ..metadata_types import MediaInfo, MediaInfoValue, ScoredMediaInfo
from ..parsing import clean_folder_name, get_season, normalize_for_match
from ..providers import MetadataProvider
from .show_details import ShowDetails, show_details_from_tmdb


def _number_value(result: MediaInfo, key: str) -> str | int | float | None:
    value: MediaInfoValue = result.get(key)
    return value if isinstance(value, (str, int, float)) else None


def _season_numbers(explicit_seasons: set[int] | None) -> set[int]:
    return explicit_seasons if explicit_seasons is not None else set()


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


def _season_episode_count(details: ShowDetails, explicit_seasons: set[int]) -> int | None:
    """Sum ``episode_count`` over *explicit_seasons*.

    Returns ``None`` when none of the requested seasons are present in the
    details payload, so the caller can fall back to the whole-show count.
    """
    total = 0
    matched = False
    for season in details.seasons:
        if season.season_number in explicit_seasons:
            total += season.episode_count
            matched = True
    return total if matched else None


def episode_count_tiebreak(
    tmdb: MetadataProvider,
    scored: ScoredMediaInfo,
    file_count: int,
    threshold: float = 0.10,
    compare_seasons: bool = False,
    explicit_seasons: set[int] | None = None,
) -> tuple[MediaInfo, float, bool]:
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
    season_numbers = _season_numbers(explicit_seasons)
    use_season_subset = bool(season_numbers) and not compare_seasons
    top_score = scored[0][1]
    contenders: list[tuple[MediaInfo, float, int, bool]] = []

    for result, score in scored:
        if top_score - score > threshold:
            break
        show_id = result.get("id")
        if type(show_id) is not int:
            continue
        details = show_details_from_tmdb(tmdb.get_tv_details(show_id))
        if details is None:
            # A failed detail fetch would rank this contender as an unaired
            # zero-episode show — fabricated evidence that can hand a
            # near-tie to the wrong show. Abstain from re-ranking entirely.
            return scored[0][0], scored[0][1], False
        count = details.number_of_seasons if compare_seasons else details.number_of_episodes
        if use_season_subset:
            season_count = _season_episode_count(details, season_numbers)
            if season_count is not None:
                count = season_count
        contenders.append((result, score, count, details.unaired))

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
    best: MediaInfo,
    runner_up: MediaInfo,
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
    best_name = best.get("name")
    runner_name = runner_up.get("name")
    best_exact = normalize_for_match(best_name if isinstance(best_name, str) else "") == query_norm
    runner_exact = (
        normalize_for_match(runner_name if isinstance(runner_name, str) else "") == query_norm
    )
    if not best_exact or runner_exact:
        return False
    best_year = _number_value(best, "year")
    runner_year = _number_value(runner_up, "year")
    if year_hint and best_year and runner_year:
        try:
            best_diff = abs(int(best_year) - int(year_hint))
            runner_diff = abs(int(runner_year) - int(year_hint))
        except (ValueError, TypeError):
            return True
        return best_diff <= runner_diff
    return True


def year_hint_breaks_tie(
    best: MediaInfo,
    runner_up: MediaInfo,
    year_hint: str | None,
) -> bool:
    """True when the folder's year hint matches exactly one candidate.

    Same-name remake pairs ("The Powerpuff Girls" 1998 vs 2016) saturate
    every title-based signal; the year in the folder path is then the only —
    and decisive — identity evidence.
    """
    if not year_hint:
        return False
    best_year_value = _number_value(best, "year")
    runner_year_value = _number_value(runner_up, "year")
    try:
        hint = int(year_hint)
        best_year = int(best_year_value or 0)
        runner_year = int(runner_year_value or 0)
    except (ValueError, TypeError):
        return False
    if not best_year or not runner_year:
        return False
    return best_year == hint and runner_year != hint
