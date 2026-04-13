"""Consolidated-preview helpers for TVScanner."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from ..constants import VIDEO_EXTENSIONS
from ..parsing import build_tv_name, extract_episode, extract_season_number, normalize_for_specials
from .models import PreviewItem

AbsoluteFileEntry = tuple[Path, int, str | None, list[int], bool, int | None]

_RE_LEADING_ABS_NUM = re.compile("^(\\d{1,4})\\s*[-–]\\s*")


def collect_absolute_files(
    season_dirs: list[tuple[Path, int]],
) -> list[AbsoluteFileEntry]:
    """Collect all video files sorted by absolute episode number."""
    all_files: list[AbsoluteFileEntry] = []
    for season_dir, _season_num in season_dirs:
        for file_path in sorted(season_dir.iterdir()):
            if not file_path.is_file() or file_path.suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            episode_numbers, raw_title, is_season_relative = extract_episode(file_path.name)
            season_hint = extract_season_number(file_path.name) if is_season_relative else None
            abs_num = episode_numbers[0] if episode_numbers else 9999
            all_files.append((file_path, abs_num, raw_title, episode_numbers, is_season_relative, season_hint))
    all_files.sort(key=lambda item: item[1])
    return all_files


def match_file_title_to_tmdb(
    raw_title: str | None,
    title_lookup: dict[str, tuple[int, int, str]],
    number_lookup: dict[int, tuple[int, int, str]],
    used: set[tuple[int, int]],
) -> tuple[int, int, str] | None:
    """Match a file's title against the cross-season TMDB title lookup."""
    if not raw_title:
        return None

    cleaned_title = raw_title
    abs_match = _RE_LEADING_ABS_NUM.match(raw_title)
    if abs_match:
        abs_ep = int(abs_match.group(1))
        cleaned_title = raw_title[abs_match.end():]
        if abs_ep in number_lookup:
            result = number_lookup[abs_ep]
            if (result[0], result[1]) not in used:
                return result

    normalized = normalize_for_specials(cleaned_title)
    if not normalized:
        return None

    if normalized in title_lookup:
        result = title_lookup[normalized]
        if (result[0], result[1]) not in used:
            return result

    minimum_substring_len = 8
    if len(normalized) < minimum_substring_len:
        return None

    best: tuple[int, int, str] | None = None
    best_len = 0
    for key, value in title_lookup.items():
        if len(key) < minimum_substring_len:
            continue
        if (value[0], value[1]) in used:
            continue
        if normalized in key or key in normalized:
            if len(key) > best_len:
                best = value
                best_len = len(key)

    return best


def try_title_based_matching(
    all_files: list[AbsoluteFileEntry],
    tmdb_seasons: dict,
) -> list[tuple[int, int, str] | None] | None:
    """Try to match files to TMDB episodes by title or absolute number."""
    title_lookup: dict[str, tuple[int, int, str]] = {}
    file_count = len(all_files)
    qualifying_seasons = [
        season_num for season_num, season_data in tmdb_seasons.items()
        if season_num != 0 and season_data["count"] >= file_count
    ]
    number_lookup: dict[int, tuple[int, int, str]] = {}
    for season_num in sorted(tmdb_seasons.keys()):
        if season_num == 0:
            continue
        for episode_num, title in tmdb_seasons[season_num]["titles"].items():
            normalized = normalize_for_specials(title)
            if normalized and normalized not in title_lookup:
                title_lookup[normalized] = (season_num, episode_num, title)
            if (
                len(qualifying_seasons) == 1
                and season_num == qualifying_seasons[0]
                and episode_num not in number_lookup
            ):
                number_lookup[episode_num] = (season_num, episode_num, title)

    if not title_lookup:
        return None

    matches: list[tuple[int, int, str] | None] = []
    used: set[tuple[int, int]] = set()

    for _file_path, _abs_num, raw_title, episode_numbers, is_season_relative, season_hint in all_files:
        if is_season_relative and season_hint is not None and episode_numbers:
            season_data = tmdb_seasons.get(season_hint)
            if season_data:
                episode_num = episode_numbers[0]
                title = season_data["titles"].get(episode_num)
                if title and (season_hint, episode_num) not in used:
                    match = (season_hint, episode_num, title)
                    used.add((match[0], match[1]))
                    matches.append(match)
                    continue

        match = match_file_title_to_tmdb(raw_title, title_lookup, number_lookup, used)
        if match is not None:
            used.add((match[0], match[1]))
        matches.append(match)

    matched_count = sum(1 for match in matches if match is not None)
    if matched_count < len(all_files) * 0.5:
        return None

    return matches


def build_consolidated_preview(
    *,
    season_dirs: list[tuple[Path, int]],
    tmdb_seasons: dict,
    root: Path,
    show_info: dict,
    media_fields: dict,
    store_tmdb_data: Callable[[int, dict, dict, dict | None], None],
    resolve_duplicate_episodes: Callable[[list[PreviewItem]], None],
) -> list[PreviewItem]:
    """Build preview mapping files in absolute order to TMDB structure."""
    all_files = collect_absolute_files(season_dirs)

    tmdb_list: list[tuple[int, int, str]] = []
    for season_num in sorted(tmdb_seasons.keys()):
        if season_num == 0:
            continue
        season_data = tmdb_seasons[season_num]
        for episode_num in sorted(season_data["titles"].keys()):
            tmdb_list.append((season_num, episode_num, season_data["titles"][episode_num]))

    for season_num, season_data in tmdb_seasons.items():
        store_tmdb_data(
            season_num,
            season_data["titles"],
            season_data["posters"],
            season_data.get("episodes", {}),
        )

    title_matches = try_title_based_matching(all_files, tmdb_seasons)
    if title_matches is not None:
        items: list[PreviewItem] = []
        for index, (file_path, _abs_num, _raw_title, episode_numbers, _is_season_relative, _season_hint) in enumerate(all_files):
            match = title_matches[index]
            if match is None:
                items.append(PreviewItem(
                    original=file_path,
                    new_name=None,
                    target_dir=None,
                    season=0,
                    episodes=episode_numbers,
                    status="SKIP: could not match episode title to TMDB",
                    **media_fields,
                ))
                continue
            season_num, episode_num, title = match
            target_dir = root / f"Season {season_num:02d}"
            new_name = build_tv_name(
                show_info["name"],
                show_info["year"],
                season_num,
                [episode_num],
                [title],
                file_path.suffix,
            )
            items.append(PreviewItem(
                original=file_path,
                new_name=new_name,
                target_dir=target_dir,
                season=season_num,
                episodes=[episode_num],
                status="OK",
                episode_confidence=0.7,
                **media_fields,
            ))
        resolve_duplicate_episodes(items)
        return items

    items: list[PreviewItem] = []
    tmdb_index = 0

    for file_path, _abs_num, _raw_title, episode_numbers, is_season_relative, _season_hint in all_files:
        num_eps = max(1, len(episode_numbers))

        if tmdb_index >= len(tmdb_list):
            items.append(PreviewItem(
                original=file_path,
                new_name=None,
                target_dir=None,
                season=0,
                episodes=episode_numbers,
                status="SKIP: no matching TMDB episode (extra file?)",
                **media_fields,
            ))
            continue

        file_eps = []
        file_titles = []
        target_season = tmdb_list[tmdb_index][0]
        for offset in range(num_eps):
            if tmdb_index + offset < len(tmdb_list):
                season_num, episode_num, title = tmdb_list[tmdb_index + offset]
                file_eps.append(episode_num)
                file_titles.append(title)
                target_season = season_num
        tmdb_index += num_eps

        target_dir = root / f"Season {target_season:02d}"
        new_name = build_tv_name(
            show_info["name"],
            show_info["year"],
            target_season,
            file_eps,
            file_titles,
            file_path.suffix,
        )

        items.append(PreviewItem(
            original=file_path,
            new_name=new_name,
            target_dir=target_dir,
            season=target_season,
            episodes=file_eps,
            status="OK",
            episode_confidence=0.5 if is_season_relative else 0.3,
            **media_fields,
        ))

    resolve_duplicate_episodes(items)
    return items