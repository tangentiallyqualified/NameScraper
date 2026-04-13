"""TV scanning implementation for episode preview and completeness logic."""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from pathlib import Path

from ..constants import VIDEO_EXTENSIONS
from ..parsing import (
    build_tv_name,
    clean_folder_name,
    clean_name,
    extract_episode,
    extract_season_number,
    get_season,
    is_extras_folder,
)
from ..tmdb import TMDBClient
from ._movie_scanner import _build_subtitle_companions
from ._tv_scanner_consolidated import (
    build_consolidated_preview as _build_consolidated_preview,
    collect_absolute_files as _collect_absolute_files,
    match_file_title_to_tmdb as _match_file_title_to_tmdb,
    try_title_based_matching as _try_title_based_matching,
)
from ._tv_scanner_seasons import (
    match_tv_dirs_to_tmdb_seasons,
    resolve_tv_season_dirs,
)
from ._tv_scanner_specials import (
    fuzzy_match_special as _fuzzy_match_special,
    load_specials_context,
    match_special as _match_special,
    scan_nested_extras as _scan_nested_extras,
)
from .models import CompletenessReport, PreviewItem, SeasonCompleteness

_log = logging.getLogger(__name__)


class TVScanner:
    """
    Scans a TV series folder and builds PreviewItems using TMDB data.

    Handles:
      - Season folder detection and mapping
      - Season structure mismatch detection (user folders vs TMDB)
      - Consolidated (absolute) and per-folder preview building
      - Specials / Season 0 fuzzy matching

    Caches season_dirs and tmdb_seasons after first computation to avoid
    redundant filesystem walks and API calls across scan/mismatch/consolidated.
    """

    def __init__(
        self,
        tmdb: TMDBClient,
        show_info: dict,
        root_folder: Path,
        *,
        season_hint: int | None = None,
        season_folders: dict[int, Path] | None = None,
    ):
        self.tmdb = tmdb
        self.show_info = show_info
        self.root = root_folder
        self._season_hint = season_hint
        self._season_folders = season_folders
        self.episode_titles: dict[tuple[int, int], str] = {}
        self.episode_posters: dict[tuple[int, int], str | None] = {}
        self.episode_meta: dict[tuple[int, int], dict] = {}
        self._season_dirs: list[tuple[Path, int]] | None = None
        self._tmdb_seasons: dict | None = None

    def _get_season_dirs(self) -> list[tuple[Path, int]]:
        """Find and sort season subdirectories. Cached after first call."""
        if self._season_dirs is not None:
            return self._season_dirs

        self._season_dirs = resolve_tv_season_dirs(
            self.root,
            season_hint=self._season_hint,
            season_folders=self._season_folders,
            get_season=get_season,
            match_dirs_to_tmdb_seasons=self._match_dirs_to_tmdb_seasons,
        )
        return self._season_dirs

    def _match_dirs_to_tmdb_seasons(
        self,
        dirs: list[Path],
        already_matched: set[int],
    ) -> list[tuple[Path, int]]:
        """Try to match directories against TMDB season names."""
        return match_tv_dirs_to_tmdb_seasons(
            dirs,
            already_matched,
            show_info=self.show_info,
            tmdb=self.tmdb,
            clean_folder_name=clean_folder_name,
            logger=_log,
        )

    def _get_tmdb_seasons(self) -> dict:
        """Fetch TMDB season map. Cached after first call."""
        if self._tmdb_seasons is not None:
            return self._tmdb_seasons
        raw_tmdb_seasons, _ = self.tmdb.get_season_map(self.show_info["id"])
        self._tmdb_seasons = {
            int(season_num): season_data
            for season_num, season_data in raw_tmdb_seasons.items()
        }
        return self._tmdb_seasons

    def invalidate_cache(self) -> None:
        """Force re-scan on next call."""
        self._season_dirs = None
        self._tmdb_seasons = None

    @property
    def _media_fields(self) -> dict:
        """Common fields for PreviewItem construction."""
        return {
            "media_id": self.show_info["id"],
            "media_name": self.show_info["name"],
        }

    def scan(self) -> tuple[list[PreviewItem], bool]:
        """Scan the folder and build preview items."""
        season_dirs = self._get_season_dirs()
        tmdb_seasons = self._get_tmdb_seasons()

        is_flat_folder = len(season_dirs) == 1 and season_dirs[0][0] == self.root
        non_special_tmdb_seasons = {season_num for season_num in tmdb_seasons if season_num != 0}
        if is_flat_folder and len(non_special_tmdb_seasons) > 1 and self._season_hint is None:
            return (
                self._build_consolidated_preview(season_dirs, tmdb_seasons),
                False,
            )

        mismatched, _, _ = self._detect_mismatch(season_dirs, tmdb_seasons)

        return (
            self._build_normal_preview(season_dirs, tmdb_seasons),
            mismatched,
        )

    def scan_consolidated(self) -> list[PreviewItem]:
        """Build a consolidated (absolute order) preview for mismatch fixes."""
        season_dirs = self._get_season_dirs()
        tmdb_seasons = self._get_tmdb_seasons()
        return self._build_consolidated_preview(season_dirs, tmdb_seasons)

    def get_mismatch_info(self) -> dict:
        """Return info about the season mismatch for UI display."""
        season_dirs = self._get_season_dirs()
        tmdb_seasons = self._get_tmdb_seasons()
        _, user_nums, tmdb_nums = self._detect_mismatch(season_dirs, tmdb_seasons)
        extra = sorted(user_nums - tmdb_nums)
        return {
            "user_seasons": sorted(user_nums),
            "tmdb_seasons": {
                season_num: tmdb_seasons[season_num]["count"]
                for season_num in sorted(tmdb_nums)
                if season_num in tmdb_seasons
            },
            "extra_user_seasons": extra,
        }

    def _detect_mismatch(
        self,
        season_dirs: list[tuple[Path, int]],
        tmdb_seasons: dict,
    ) -> tuple[bool, set[int], set[int]]:
        user_nums = {season_num for _, season_num in season_dirs}
        tmdb_nums = set(tmdb_seasons.keys())
        extra = (user_nums - tmdb_nums) - {0}
        return bool(extra), user_nums, tmdb_nums

    def _store_tmdb_data(
        self,
        season_num: int,
        titles: dict,
        posters: dict,
        episodes: dict | None = None,
    ) -> None:
        """Cache TMDB data for the detail panel."""
        self.episode_titles.update({(season_num, key): value for key, value in titles.items()})
        self.episode_posters.update({(season_num, key): value for key, value in posters.items()})
        if episodes:
            self.episode_meta.update({(season_num, key): value for key, value in episodes.items()})

    def _build_normal_preview(
        self,
        season_dirs: list[tuple[Path, int]],
        tmdb_seasons: dict,
    ) -> list[PreviewItem]:
        items: list[PreviewItem] = []

        specials_context = None

        def ensure_specials_data():
            nonlocal specials_context
            if specials_context is None:
                specials_context = load_specials_context(
                    tmdb=self.tmdb,
                    show_info=self.show_info,
                    tmdb_seasons=tmdb_seasons,
                    store_tmdb_data=self._store_tmdb_data,
                )
            return specials_context

        specials_target = self.root / "Season 00"

        for season_dir, season_num in season_dirs:
            if season_num in tmdb_seasons:
                titles = tmdb_seasons[season_num]["titles"]
                posters = tmdb_seasons[season_num]["posters"]
                episodes = tmdb_seasons[season_num].get("episodes", {})
            else:
                season_data = self.tmdb.get_season(self.show_info["id"], season_num)
                titles = season_data["titles"]
                posters = season_data["posters"]
                episodes = season_data.get("episodes", {})

            self._store_tmdb_data(season_num, titles, posters, episodes)

            tmdb_title_lookup = {}
            if season_num == 0:
                context = ensure_specials_data()
                titles = context.titles
                posters = context.posters
                episodes = context.episodes
                tmdb_title_lookup = context.title_lookup

            explicit_season_folder = (
                season_dir == self.root
                or any(folder == season_dir for folder in (self._season_folders or {}).values())
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
                        item = self._match_special(
                            file_path,
                            episode_numbers,
                            raw_title,
                            context.titles,
                            context.title_lookup,
                            specials_target,
                            from_extras_folder=False,
                        )
                        items.append(item)
                        continue

                    if season_num == 0:
                        item = self._match_special(
                            file_path,
                            episode_numbers,
                            raw_title,
                            titles,
                            tmdb_title_lookup,
                            specials_target,
                            extras_folder,
                        )
                        items.append(item)
                        continue

                    if not episode_numbers:
                        items.append(PreviewItem(
                            original=file_path,
                            new_name=None,
                            target_dir=None,
                            season=season_num,
                            episodes=[],
                            status="SKIP: could not parse episode number",
                            **self._media_fields,
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
                            **self._media_fields,
                        ))
                        continue

                    episode_titles = [
                        titles.get(episode_num, raw_title or f"Episode {episode_num}")
                        for episode_num in episode_numbers
                    ]

                    target_dir = season_dir
                    if (
                        season_dir == self.root
                        or get_season(season_dir) is None
                        or self._season_folders
                    ):
                        target_dir = self.root / f"Season {season_num:02d}"

                    new_name = build_tv_name(
                        self.show_info["name"],
                        self.show_info["year"],
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
                        **self._media_fields,
                    )
                    item.companions = _build_subtitle_companions(file_path, new_name)
                    items.append(item)

                elif entry.is_dir() and season_num != 0 and is_extras_folder(entry.name):
                    context = ensure_specials_data()
                    items.extend(self._scan_nested_extras(
                        entry,
                        context.titles,
                        context.title_lookup,
                        specials_target,
                    ))

        self._resolve_duplicate_episodes(items)
        return items

    def _resolve_duplicate_episodes(self, items: list[PreviewItem]) -> None:
        """Skip files that duplicate an episode already claimed by a better match."""
        show_title = clean_folder_name(
            self.show_info.get("name", ""),
            include_year=False,
        ).casefold()

        episode_map: dict[tuple[int, int], list[int]] = defaultdict(list)
        for index, item in enumerate(items):
            if item.status != "OK" or not item.episodes:
                continue
            for episode_num in item.episodes:
                episode_map[(item.season, episode_num)].append(index)

        for key, indices in episode_map.items():
            if len(indices) < 2:
                continue
            scored: list[tuple[int, float]] = []
            for index in indices:
                item = items[index]
                stem = clean_name(item.original.stem).casefold()
                if stem.startswith(show_title):
                    score = len(show_title) / max(len(stem), 1)
                elif show_title in stem:
                    score = len(show_title) / max(len(stem), 1) * 0.5
                else:
                    score = 0.0
                scored.append((index, score))

            scored.sort(
                key=lambda item: (-item[1], len(clean_name(items[item[0]].original.stem)), item[0]),
            )
            for loser_index, _score in scored[1:]:
                loser = items[loser_index]
                loser.status = (
                    f"SKIP: duplicate episode {key[1]} - filename does not match show title"
                )
                loser.new_name = None
                loser.target_dir = None

    def _scan_nested_extras(
        self,
        extras_dir: Path,
        s0_titles: dict,
        s0_tmdb_title_lookup: dict,
        specials_target: Path,
    ) -> list[PreviewItem]:
        return _scan_nested_extras(
            extras_dir=extras_dir,
            titles=s0_titles,
            tmdb_title_lookup=s0_tmdb_title_lookup,
            specials_target=specials_target,
            media_fields=self._media_fields,
            show_info=self.show_info,
            root=self.root,
        )

    def _match_special(
        self,
        file_path: Path,
        episode_numbers: list[int],
        raw_title: str | None,
        titles: dict,
        tmdb_title_lookup: dict,
        specials_target: Path,
        from_extras_folder: bool = False,
    ) -> PreviewItem:
        return _match_special(
            file_path=file_path,
            episode_numbers=episode_numbers,
            raw_title=raw_title,
            titles=titles,
            tmdb_title_lookup=tmdb_title_lookup,
            specials_target=specials_target,
            media_fields=self._media_fields,
            show_info=self.show_info,
            root=self.root,
            from_extras_folder=from_extras_folder,
        )

    @staticmethod
    def _fuzzy_match_special(
        text: str,
        tmdb_title_lookup: dict,
    ) -> tuple[int | None, str | None]:
        return _fuzzy_match_special(text, tmdb_title_lookup)

    def _build_consolidated_preview(
        self,
        season_dirs: list[tuple[Path, int]],
        tmdb_seasons: dict,
    ) -> list[PreviewItem]:
        return _build_consolidated_preview(
            season_dirs=season_dirs,
            tmdb_seasons=tmdb_seasons,
            root=self.root,
            show_info=self.show_info,
            media_fields=self._media_fields,
            store_tmdb_data=self._store_tmdb_data,
            resolve_duplicate_episodes=self._resolve_duplicate_episodes,
        )

    def _try_title_based_matching(
        self,
        all_files: list[tuple[Path, int, str | None, list[int], bool, int | None]],
        tmdb_seasons: dict,
    ) -> list[tuple[int, int, str] | None] | None:
        return _try_title_based_matching(all_files, tmdb_seasons)

    @classmethod
    def _match_file_title_to_tmdb(
        cls,
        raw_title: str | None,
        title_lookup: dict[str, tuple[int, int, str]],
        number_lookup: dict[int, tuple[int, int, str]],
        used: set[tuple[int, int]],
    ) -> tuple[int, int, str] | None:
        return _match_file_title_to_tmdb(raw_title, title_lookup, number_lookup, used)

    def _collect_absolute_files(
        self,
        season_dirs: list[tuple[Path, int]],
    ) -> list[tuple[Path, int, str | None, list[int], bool, int | None]]:
        return _collect_absolute_files(season_dirs)

    def get_completeness(
        self,
        items: list[PreviewItem],
        checked_indices: set[int] | None = None,
    ) -> CompletenessReport:
        """Compute completeness of matched episodes vs TMDB expectations."""
        tmdb_seasons = self._get_tmdb_seasons()

        matched_by_season: dict[int, set[int]] = defaultdict(set)
        for index, item in enumerate(items):
            if checked_indices is not None and index not in checked_indices:
                continue
            if item.season is not None and item.episodes:
                for episode_num in item.episodes:
                    matched_by_season[item.season].add(episode_num)

        seasons: dict[int, SeasonCompleteness] = {}

        for season_num, season_data in sorted(tmdb_seasons.items()):
            expected_eps = set(season_data["titles"].keys())
            matched_eps = matched_by_season.get(season_num, set())
            matched_valid = matched_eps & expected_eps
            missing_eps = expected_eps - matched_valid

            missing_details = []
            for episode_num in sorted(missing_eps):
                title = season_data["titles"].get(episode_num, f"Episode {episode_num}")
                missing_details.append((episode_num, title))

            matched_details = []
            for episode_num in sorted(matched_valid):
                title = season_data["titles"].get(episode_num, f"Episode {episode_num}")
                matched_details.append((episode_num, title))

            seasons[season_num] = SeasonCompleteness(
                season=season_num,
                expected=len(expected_eps),
                matched=len(matched_valid),
                missing=missing_details,
                matched_episodes=matched_details,
            )

        total_expected = sum(season.expected for season_num, season in seasons.items() if season_num > 0)
        total_matched = sum(season.matched for season_num, season in seasons.items() if season_num > 0)
        total_missing = []
        for season_num, season in sorted(seasons.items()):
            if season_num > 0:
                for episode_num, title in season.missing:
                    total_missing.append((season_num, episode_num, title))

        specials = seasons.get(0)

        return CompletenessReport(
            seasons={season_num: season for season_num, season in seasons.items() if season_num > 0},
            specials=specials,
            total_expected=total_expected,
            total_matched=total_matched,
            total_missing=total_missing,
        )