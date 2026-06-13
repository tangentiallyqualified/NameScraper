"""Normal per-season table building for TVScanner."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from ..constants import VIDEO_EXTENSIONS
from ..parsing import extract_episode, extract_season_number, is_extras_folder
from ._episode_resolution import resolve_file
from .episode_assignments import REASON_AMBIGUOUS_RUN, EpisodeAssignmentTable, EpisodeSlot
from .models import SeasonFolderEntry, iter_season_folder_paths

_SPECIAL_STEM_PREFIX_RE = re.compile(
    r"^(?:Season|S)\s*\d+\s*[-._]\s*", re.IGNORECASE,
)


def _register_season_slots(
    table: EpisodeAssignmentTable,
    season_num: int,
    titles: dict,
    episodes_meta: dict,
) -> None:
    for episode_num, title in titles.items():
        meta = (episodes_meta or {}).get(episode_num, {}) or {}
        table.add_slot(EpisodeSlot(
            season=season_num,
            episode=episode_num,
            title=title,
            air_date=str(meta.get("air_date", "") or ""),
            overview=str(meta.get("overview", "") or ""),
        ))


def _resolve_into_table(
    table: EpisodeAssignmentTable,
    *,
    file_path: Path,
    season_num: int,
    season_titles: dict[int, str],
    from_extras_folder: bool = False,
) -> None:
    episode_numbers, raw_title, is_season_relative = extract_episode(file_path.name)
    season_hint = extract_season_number(file_path.name) if is_season_relative else None
    entry = table.add_file(
        file_path,
        parsed_episodes=tuple(episode_numbers),
        raw_title=raw_title,
        is_season_relative=is_season_relative,
        season_hint=season_hint,
        folder_season=season_num,
        from_extras_folder=from_extras_folder,
    )
    title_evidence = raw_title
    if season_num == 0 and not title_evidence:
        # Specials numbering varies across sources; the filename itself is
        # often the only title evidence (mirrors the retired match_special
        # stem fallback).
        cleaned_stem = _SPECIAL_STEM_PREFIX_RE.sub("", file_path.stem).strip()
        title_evidence = cleaned_stem or None
    resolution = resolve_file(
        parsed_episodes=tuple(episode_numbers),
        raw_title=title_evidence,
        is_season_relative=is_season_relative,
        season_titles=season_titles,
        season=season_num,
    )
    if resolution.episodes:
        try:
            table.assign(
                entry.file_id,
                season_num,
                list(resolution.episodes),
                origin="auto",
                confidence=resolution.confidence,
                evidence=resolution.evidence,
            )
        except ValueError:
            table.mark_unassigned(entry.file_id, REASON_AMBIGUOUS_RUN)
    else:
        table.mark_unassigned(entry.file_id, resolution.reason or "")


def build_normal_table(
    *,
    season_dirs: list[tuple[Path, int]],
    tmdb_seasons: dict,
    tmdb,
    show_info: dict,
    root: Path,
    season_folders: dict[int, SeasonFolderEntry] | None,
    store_tmdb_data: Callable[[int, dict, dict, dict | None], None],
) -> EpisodeAssignmentTable:
    table = EpisodeAssignmentTable()
    s0_titles: dict[int, str] | None = None

    def ensure_s0_titles() -> dict[int, str]:
        nonlocal s0_titles
        if s0_titles is None:
            if 0 in tmdb_seasons:
                data = tmdb_seasons[0]
            else:
                data = tmdb.get_season(show_info["id"], 0)
            s0_titles = data.get("titles", {})
            if s0_titles:
                store_tmdb_data(0, s0_titles, data.get("posters", {}), data.get("episodes", {}))
                _register_season_slots(table, 0, s0_titles, data.get("episodes", {}))
        return s0_titles

    registered_seasons: set[int] = set()
    for season_dir, season_num in season_dirs:
        if season_num in tmdb_seasons:
            season_data = tmdb_seasons[season_num]
        else:
            season_data = tmdb.get_season(show_info["id"], season_num)
        titles = season_data.get("titles", {})
        store_tmdb_data(
            season_num, titles,
            season_data.get("posters", {}), season_data.get("episodes", {}),
        )
        if season_num == 0:
            ensure_s0_titles()
            titles = s0_titles or titles
        else:
            # TMDB's episode count can run ahead of its listed titles
            # (newly airing seasons). Untitled placeholder slots keep
            # those episode numbers assignable instead of SKIPped.
            count = int(season_data.get("count", 0) or 0)
            titles = dict(titles)
            for episode_num in range(1, count + 1):
                titles.setdefault(episode_num, "")
            if season_num not in registered_seasons:
                _register_season_slots(table, season_num, titles, season_data.get("episodes", {}))
                registered_seasons.add(season_num)

        explicit_season_folder = season_dir == root
        if not explicit_season_folder and season_folders:
            explicit_season_folder = any(
                folder == season_dir
                for folder_entry in season_folders.values()
                for folder in iter_season_folder_paths(folder_entry)
            )
        nested_specials_folder = bool(re.search(
            r"(?:^|[\s._\-])specials?$|(?:^|[\s._\-])season[\s._\-]*0+$",
            season_dir.name, re.IGNORECASE,
        ))
        extras_folder = (
            season_num == 0
            and not explicit_season_folder
            and not nested_specials_folder
            and season_dir.name.lower().strip() not in (
                "specials", "special", "season 00", "season 0",
                "season00", "season0",
            )
        )

        for entry_path in sorted(season_dir.iterdir()):
            if entry_path.is_file() and entry_path.suffix.lower() in VIDEO_EXTENSIONS:
                _, _, is_season_relative = extract_episode(entry_path.name)
                file_season = (
                    extract_season_number(entry_path.name)
                    if is_season_relative else None
                )
                if season_num == 0 or file_season == 0:
                    _resolve_into_table(
                        table,
                        file_path=entry_path,
                        season_num=0,
                        season_titles=ensure_s0_titles(),
                        from_extras_folder=extras_folder and season_num == 0,
                    )
                else:
                    _resolve_into_table(
                        table,
                        file_path=entry_path,
                        season_num=season_num,
                        season_titles=titles,
                    )
            elif entry_path.is_dir() and season_num != 0 and is_extras_folder(entry_path.name):
                for extras_file in sorted(entry_path.iterdir()):
                    if (
                        extras_file.is_file()
                        and extras_file.suffix.lower() in VIDEO_EXTENSIONS
                    ):
                        _resolve_into_table(
                            table,
                            file_path=extras_file,
                            season_num=0,
                            season_titles=ensure_s0_titles(),
                            from_extras_folder=True,
                        )

    return table
