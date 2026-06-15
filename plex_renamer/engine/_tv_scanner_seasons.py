"""Season directory resolution helpers for TVScanner."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from logging import Logger
from pathlib import Path

from ..parsing import get_year_season
from .models import SeasonFolderEntry, iter_season_folder_paths


def resolve_tv_season_dirs(
    root: Path,
    *,
    season_hint: int | None,
    season_folders: dict[int, SeasonFolderEntry] | None,
    get_season: Callable[[Path], int | None],
    match_dirs_to_tmdb_seasons: Callable[[list[Path], set[int]], list[tuple[Path, int]]],
) -> list[tuple[Path, int]]:
    if season_folders:
        flattened: list[tuple[Path, int]] = []
        for season_num, folder_entry in season_folders.items():
            for folder in iter_season_folder_paths(folder_entry):
                flattened.append((folder, season_num))
        return sorted(
            flattened,
            key=lambda item: (item[1], item[0].as_posix().casefold()),
        )

    dirs_with_season: list[tuple[Path, int]] = []
    unmatched_dirs: list[Path] = []
    for directory in root.iterdir():
        if not directory.is_dir():
            continue
        season_num = get_season(directory)
        if season_num is not None:
            dirs_with_season.append((directory, season_num))
        else:
            unmatched_dirs.append(directory)

    if dirs_with_season and unmatched_dirs:
        matched_via_tmdb = match_dirs_to_tmdb_seasons(
            unmatched_dirs,
            {season_num for _, season_num in dirs_with_season},
        )
        dirs_with_season.extend(matched_via_tmdb)

    dirs_with_season.sort(key=lambda item: item[1])
    if dirs_with_season:
        return dirs_with_season
    return [(root, 1 if season_hint is None else season_hint)]


def match_tv_dirs_to_tmdb_seasons(
    dirs: list[Path],
    already_matched: set[int],
    *,
    show_info: dict,
    tmdb,
    clean_folder_name: Callable[..., str],
    logger: Logger,
) -> list[tuple[Path, int]]:
    show_id = show_info.get("id")
    if not show_id:
        return []

    show_data = tmdb.get_tv_details(show_id)
    if not show_data:
        return []

    results: list[tuple[Path, int]] = []

    # Release-year folders (S2014, S2020) map onto the TMDB season whose
    # episodes aired that year — a single show split across air-year folders
    # (Adult Swim Infomercials). Multiple year folders may share one season.
    year_dirs = [d for d in dirs if get_year_season(d.name) is not None]
    if year_dirs:
        results.extend(
            _map_year_folders_to_seasons(year_dirs, show_data, tmdb, show_id, logger)
        )

    name_dirs = [d for d in dirs if get_year_season(d.name) is None]
    tmdb_season_names: dict[int, str] = {}
    for season_info in show_data.get("seasons", []):
        season_num = season_info.get("season_number", 0)
        name = season_info.get("name", "")
        if season_num > 0 and name and season_num not in already_matched:
            tmdb_season_names[season_num] = name

    if not tmdb_season_names:
        return results

    show_title = clean_folder_name(
        show_info.get("name", ""),
        include_year=False,
    ).lower()

    used_seasons: set[int] = set()
    for directory in name_dirs:
        best_season_num, best_score = _best_tmdb_season_name_match(
            directory.name,
            tmdb_season_names,
            used_seasons=used_seasons,
            show_title=show_title,
            clean_folder_name=clean_folder_name,
        )
        if best_season_num is None:
            continue
        logger.info(
            "Matched folder '%s' to TMDB season %d via name similarity (score=%.2f)",
            directory.name,
            best_season_num,
            best_score,
        )
        results.append((directory, best_season_num))
        used_seasons.add(best_season_num)

    return results


def _map_year_folders_to_seasons(
    year_dirs: list[Path],
    show_data: dict,
    tmdb,
    show_id: int,
    logger: Logger,
) -> list[tuple[Path, int]]:
    """Map ``S<YYYY>`` folders to the TMDB season airing that year.

    Falls back to the show's sole regular season when no season has an episode
    in that exact year (covers a year folder with no matching TMDB air date).
    """
    seasons_meta = show_data.get("seasons", []) or []
    regular = [
        int(season["season_number"])
        for season in seasons_meta
        if isinstance(season.get("season_number"), int)
        and season["season_number"] > 0
        and (season.get("episode_count", 0) or 0) > 0
    ]
    if not regular:
        regular = [
            int(season["season_number"])
            for season in seasons_meta
            if isinstance(season.get("season_number"), int)
            and season["season_number"] > 0
        ]
    if not regular:
        return []

    season_year_counts: dict[int, Counter] = {}
    for season_num in regular:
        data = tmdb.get_season(show_id, season_num) or {}
        counts: Counter = Counter()
        for meta in (data.get("episodes") or {}).values():
            air_year = str((meta or {}).get("air_date") or "")[:4]
            if air_year.isdigit():
                counts[int(air_year)] += 1
        season_year_counts[season_num] = counts

    single_season = regular[0] if len(regular) == 1 else None
    results: list[tuple[Path, int]] = []
    for directory in year_dirs:
        year = get_year_season(directory.name)
        candidates = [
            (season_num, counts[year])
            for season_num, counts in season_year_counts.items()
            if counts.get(year, 0) > 0
        ]
        if candidates:
            target = max(candidates, key=lambda item: (item[1], -item[0]))[0]
        elif single_season is not None:
            target = single_season
        else:
            continue
        logger.info(
            "Mapped release-year folder '%s' to TMDB season %d by air year",
            directory.name,
            target,
        )
        results.append((directory, target))
    return results


def _best_tmdb_season_name_match(
    folder_name: str,
    tmdb_season_names: dict[int, str],
    *,
    used_seasons: set[int],
    show_title: str,
    clean_folder_name: Callable[..., str],
) -> tuple[int | None, float]:
    folder_cleaned = clean_folder_name(
        folder_name,
        include_year=False,
    ).lower()
    best_season_num: int | None = None
    best_score = 0.0

    for season_num, tmdb_name in tmdb_season_names.items():
        if season_num in used_seasons:
            continue
        score = _season_name_similarity_score(
            folder_cleaned,
            tmdb_name.lower(),
            show_title=show_title,
        )
        if score > best_score and score >= 0.5:
            best_score = score
            best_season_num = season_num

    return best_season_num, best_score


def _season_name_similarity_score(folder_cleaned: str, tmdb_cleaned: str, *, show_title: str) -> float:
    if tmdb_cleaned in folder_cleaned or folder_cleaned in tmdb_cleaned:
        return 1.0

    folder_suffix = folder_cleaned
    tmdb_suffix = tmdb_cleaned
    if folder_suffix.startswith(show_title):
        folder_suffix = folder_suffix[len(show_title):].strip()
    if tmdb_suffix.startswith(show_title):
        tmdb_suffix = tmdb_suffix[len(show_title):].strip()

    if not folder_suffix or not tmdb_suffix:
        return 0.0
    if tmdb_suffix in folder_suffix or folder_suffix in tmdb_suffix:
        return 0.9

    folder_tokens = {token for token in folder_suffix.split() if len(token) > 2}
    tmdb_tokens = {token for token in tmdb_suffix.split() if len(token) > 2}
    if not tmdb_tokens:
        return 0.0
    overlap = len(folder_tokens & tmdb_tokens)
    return overlap / max(len(tmdb_tokens), 1)
