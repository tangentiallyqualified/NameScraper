"""Normal per-season preview helpers for TVScanner."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from ..constants import VIDEO_EXTENSIONS
from ..parsing import (
    build_tv_name,
    extract_episode,
    extract_season_number,
    get_season,
    is_extras_folder,
)
from ._movie_scanner import _build_subtitle_companions
from ._tv_scanner_specials import (
    load_specials_context,
    match_special,
    scan_nested_extras,
)
from .models import PreviewItem


def build_normal_preview(
    *,
    season_dirs: list[tuple[Path, int]],
    tmdb_seasons: dict,
    tmdb,
    show_info: dict,
    root: Path,
    media_fields: dict,
    season_folders: dict[int, Path] | None,
    store_tmdb_data: Callable[[int, dict, dict, dict | None], None],
    resolve_duplicate_episodes: Callable[[list[PreviewItem]], None],
) -> list[PreviewItem]:
    items: list[PreviewItem] = []

    specials_context = None

    def ensure_specials_data():
        nonlocal specials_context
        if specials_context is None:
            specials_context = load_specials_context(
                tmdb=tmdb,
                show_info=show_info,
                tmdb_seasons=tmdb_seasons,
                store_tmdb_data=store_tmdb_data,
            )
        return specials_context

    specials_target = root / "Season 00"

    for season_dir, season_num in season_dirs:
        if season_num in tmdb_seasons:
            titles = tmdb_seasons[season_num]["titles"]
            posters = tmdb_seasons[season_num]["posters"]
            episodes = tmdb_seasons[season_num].get("episodes", {})
        else:
            season_data = tmdb.get_season(show_info["id"], season_num)
            titles = season_data["titles"]
            posters = season_data["posters"]
            episodes = season_data.get("episodes", {})

        store_tmdb_data(season_num, titles, posters, episodes)

        tmdb_title_lookup = {}
        if season_num == 0:
            context = ensure_specials_data()
            titles = context.titles
            tmdb_title_lookup = context.title_lookup

        explicit_season_folder = (
            season_dir == root
            or any(folder == season_dir for folder in (season_folders or {}).values())
        )
        nested_specials_folder = bool(
            re.search(
                r"(?:^|[\s._\-])specials?$|(?:^|[\s._\-])season[\s._\-]*0+$",
                season_dir.name,
                re.IGNORECASE,
            )
        )

        extras_folder = (
            season_num == 0
            and not explicit_season_folder
            and not nested_specials_folder
            and season_dir.name.lower().strip() not in (
                "specials", "special", "season 00", "season 0",
                "season00", "season0",
            )
        )

        for entry in sorted(season_dir.iterdir()):
            if entry.is_file() and entry.suffix.lower() in VIDEO_EXTENSIONS:
                file_path = entry
                episode_numbers, raw_title, is_season_relative = extract_episode(file_path.name)
                file_season = extract_season_number(file_path.name) if is_season_relative else None

                if file_season == 0 and season_num != 0:
                    context = ensure_specials_data()
                    items.append(
                        match_special(
                            file_path=file_path,
                            episode_numbers=episode_numbers,
                            raw_title=raw_title,
                            titles=context.titles,
                            tmdb_title_lookup=context.title_lookup,
                            specials_target=specials_target,
                            media_fields=media_fields,
                            show_info=show_info,
                            root=root,
                            from_extras_folder=False,
                        )
                    )
                    continue

                if season_num == 0:
                    items.append(
                        match_special(
                            file_path=file_path,
                            episode_numbers=episode_numbers,
                            raw_title=raw_title,
                            titles=titles,
                            tmdb_title_lookup=tmdb_title_lookup,
                            specials_target=specials_target,
                            media_fields=media_fields,
                            show_info=show_info,
                            root=root,
                            from_extras_folder=extras_folder,
                        )
                    )
                    continue

                if not episode_numbers:
                    items.append(PreviewItem(
                        original=file_path,
                        new_name=None,
                        target_dir=None,
                        season=season_num,
                        episodes=[],
                        status="SKIP: could not parse episode number",
                        **media_fields,
                    ))
                    continue

                max_ep = max(episode_numbers)
                season_episode_count = len(titles)
                if (
                    season_episode_count > 0
                    and max_ep > season_episode_count * 1.5
                    and max_ep > season_episode_count + 10
                    and not is_season_relative
                ):
                    items.append(PreviewItem(
                        original=file_path,
                        new_name=None,
                        target_dir=None,
                        season=season_num,
                        episodes=episode_numbers,
                        status=(
                            f"REVIEW: parsed episode {max_ep} but season only has {season_episode_count} episodes "
                            f"- likely a mis-parsed filename"
                        ),
                        **media_fields,
                    ))
                    continue

                episode_titles = [
                    titles.get(episode_num, raw_title or f"Episode {episode_num}")
                    for episode_num in episode_numbers
                ]

                target_dir = season_dir
                if (
                    season_dir == root
                    or get_season(season_dir) is None
                    or season_folders
                ):
                    target_dir = root / f"Season {season_num:02d}"

                new_name = build_tv_name(
                    show_info["name"],
                    show_info["year"],
                    season_num,
                    episode_numbers,
                    episode_titles,
                    file_path.suffix,
                )

                item = PreviewItem(
                    original=file_path,
                    new_name=new_name,
                    target_dir=target_dir,
                    season=season_num,
                    episodes=episode_numbers,
                    status="OK",
                    episode_confidence=1.0 if is_season_relative else 0.5,
                    **media_fields,
                )
                item.companions = _build_subtitle_companions(file_path, new_name)
                items.append(item)

            elif entry.is_dir() and season_num != 0 and is_extras_folder(entry.name):
                context = ensure_specials_data()
                items.extend(
                    scan_nested_extras(
                        extras_dir=entry,
                        titles=context.titles,
                        tmdb_title_lookup=context.title_lookup,
                        specials_target=specials_target,
                        media_fields=media_fields,
                        show_info=show_info,
                        root=root,
                    )
                )

    resolve_duplicate_episodes(items)
    return items