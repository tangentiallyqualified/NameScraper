"""Normal per-season table building for TVScanner."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from ..constants import VIDEO_EXTENSIONS
from ..parsing import (
    extract_episode,
    extract_season_number,
    is_companion_video_file,
    is_extras_folder,
    normalize_for_specials,
)
from .._parsing_titles import clean_title_evidence
from ._episode_resolution import (
    CONF_TITLE_WINS_INEXACT,
    STRONG_TITLE_STRENGTH,
    _TITLE_EXACT,
    Resolution,
    match_title_in_titles,
    resolve_file,
)
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
    specials_titles: dict[int, str] | None = None,
    from_extras_folder: bool = False,
    show_name: str | None = None,
) -> None:
    episode_numbers, raw_title, is_season_relative = extract_episode(file_path.name)
    season_hint = extract_season_number(file_path.name) if is_season_relative else None
    if from_extras_folder and not is_season_relative:
        # A bare number in an extras filename ("Season 2 Extra 1", "NCED2")
        # is not an episode number; claiming numbered S0 slots from it
        # produced mass conflicts. Only explicit S00E## numbering counts.
        episode_numbers = []
    elif from_extras_folder and season_hint not in (None, 0):
        # "Prequel - S07E13 - …": the S##E## names the PARENT episode the
        # extra belongs to, not an S0 slot (RC25).
        episode_numbers = []
    if is_companion_video_file(file_path):
        entry = table.add_file(
            file_path,
            parsed_episodes=(),
            raw_title=raw_title,
            is_season_relative=is_season_relative,
            season_hint=season_hint,
            folder_season=season_num,
            from_extras_folder=True,
        )
        table.mark_unassigned(entry.file_id, "companion extra (NCOP/NCED)")
        return
    title_evidence = raw_title
    if (
        title_evidence
        and show_name
        and normalize_for_specials(title_evidence) == normalize_for_specials(show_name)
    ):
        # A "title" that is just the show name ("Trailer Park Boys -
        # S10E01 - Trailer Park Boys") carries no episode information and
        # must not match episodes/specials whose titles contain the show
        # name.
        title_evidence = None
    if not title_evidence and (season_num == 0 or not episode_numbers):
        # No parsed episode and no extracted title: the filename itself is
        # the only evidence (root specials like "The Henry & June Show
        # (1999).mp4"). Clean it so quality tags don't pollute the match.
        cleaned_stem = clean_title_evidence(file_path.stem)
        cleaned_stem = _SPECIAL_STEM_PREFIX_RE.sub("", cleaned_stem).strip()
        title_evidence = cleaned_stem or None
    entry = table.add_file(
        file_path,
        parsed_episodes=tuple(episode_numbers),
        raw_title=title_evidence,
        is_season_relative=is_season_relative,
        season_hint=season_hint,
        folder_season=season_num,
        from_extras_folder=from_extras_folder,
    )
    resolution = resolve_file(
        parsed_episodes=tuple(episode_numbers),
        raw_title=title_evidence,
        is_season_relative=is_season_relative,
        season_titles=season_titles,
        season=season_num,
    )
    if (
        season_num == 0
        and not resolution.episodes
        and title_evidence
        and " - " in title_evidence
    ):
        # Extras often name themselves "Parent Title - Extra Title" while
        # TMDB lists "Extra Title (Parent Title Prequel)"; per-segment
        # matching bridges the recombination (RC25).
        for segment in reversed(title_evidence.split(" - ")):
            segment = segment.strip()
            if len(segment) < 4:
                continue
            segment_match = match_title_in_titles(segment, season_titles)
            if (
                segment_match is not None
                and segment_match.strength >= STRONG_TITLE_STRENGTH
            ):
                resolution = Resolution(
                    episodes=(segment_match.episode,),
                    confidence=CONF_TITLE_WINS_INEXACT,
                    evidence=frozenset({"title-strong-inexact", "segment-title"}),
                )
                break
    season_for_assign = season_num
    if (
        season_num != 0
        and specials_titles
        and title_evidence
        and "title-agree" not in resolution.evidence
    ):
        own_match = match_title_in_titles(title_evidence, season_titles)
        s0_match = match_title_in_titles(title_evidence, specials_titles)
        if (
            s0_match is not None
            and show_name
            and normalize_for_specials(specials_titles[s0_match.episode])
            == normalize_for_specials(show_name)
        ):
            # A special titled exactly like the show ("Trailer Park Boys"
            # S00E03) matches any show-name-prefixed file title; that carries
            # no episode information and must not ride over valid own-season
            # numbers.
            s0_match = None
        own_explicit_valid = (
            is_season_relative
            and season_hint == season_num
            and bool(episode_numbers)
            and all(episode in season_titles for episode in episode_numbers)
        )
        if (
            s0_match is not None
            and s0_match.strength >= STRONG_TITLE_STRENGTH
            and (own_match is None or s0_match.strength > own_match.strength)
            and (
                not own_explicit_valid
                or (s0_match.strength >= _TITLE_EXACT and own_match is None)
            )
        ):
            if (0, s0_match.episode) not in table.slots:
                table.add_slot(EpisodeSlot(
                    season=0, episode=s0_match.episode,
                    title=specials_titles[s0_match.episode],
                ))
            exact_title = "title-strong" if s0_match.strength >= _TITLE_EXACT else "title-strong-inexact"
            resolution = Resolution(
                episodes=(s0_match.episode,),
                confidence=CONF_TITLE_WINS_INEXACT,
                evidence=frozenset({exact_title, "cross-season-special"}),
            )
            season_for_assign = 0
    if resolution.episodes:
        try:
            table.assign(
                entry.file_id,
                season_for_assign,
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
    season_dir_paths = {season_dir for season_dir, _ in season_dirs}
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
                        show_name=show_info.get('name'),
                    )
                else:
                    _resolve_into_table(
                        table,
                        file_path=entry_path,
                        season_num=season_num,
                        season_titles=titles,
                        specials_titles=ensure_s0_titles(),
                        show_name=show_info.get('name'),
                    )
            elif (
                entry_path.is_dir()
                and season_num != 0
                and is_extras_folder(entry_path.name)
                and entry_path not in season_dir_paths
            ):
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
                            show_name=show_info.get('name'),
                        )
            elif entry_path.is_dir() and season_num == 0 and extras_folder:
                # An extras folder may group its bonus videos one level
                # deeper ("Extras/The Mayfly of Space/…"); scan those files
                # as specials too so titled OVAs aren't silently dropped.
                for nested_file in sorted(entry_path.iterdir()):
                    if (
                        nested_file.is_file()
                        and nested_file.suffix.lower() in VIDEO_EXTENSIONS
                    ):
                        _resolve_into_table(
                            table,
                            file_path=nested_file,
                            season_num=0,
                            season_titles=ensure_s0_titles(),
                            from_extras_folder=True,
                            show_name=show_info.get('name'),
                        )

    return table
