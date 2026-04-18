"""TV scanning implementation for episode preview and completeness logic."""

from __future__ import annotations

import logging
from pathlib import Path

from ..constants import VIDEO_EXTENSIONS
from ..parsing import (
    clean_folder_name,
    get_season,
)
from ..tmdb import TMDBClient
from ._tv_scanner_consolidated import (
    build_consolidated_preview as _build_consolidated_preview,
    collect_absolute_files as _collect_absolute_files,
    match_file_title_to_tmdb as _match_file_title_to_tmdb,
    try_title_based_matching as _try_title_based_matching,
)
from ._tv_scanner_normal import build_normal_preview as _build_normal_preview
from ._tv_scanner_postprocess import (
    build_completeness_report,
    resolve_duplicate_episodes,
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

_HINT_OVERFLOW_MARGIN = 4


def _count_video_files(folder: Path) -> int:
    try:
        return sum(
            1
            for entry in folder.iterdir()
            if entry.is_file() and entry.suffix.lower() in VIDEO_EXTENSIONS
        )
    except OSError:
        return 0


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
        if is_flat_folder and len(non_special_tmdb_seasons) > 1:
            use_consolidated = self._season_hint is None
            if not use_consolidated:
                # Absolute-numbering sources (common for anime) often label every
                # file with a single S## that TMDB has split across seasons. If
                # the video count overflows the hinted season's capacity by more
                # than the margin, treat the hint as unreliable and fall back to
                # consolidated mapping.
                hinted_season = tmdb_seasons.get(self._season_hint)
                if hinted_season:
                    hinted_count = hinted_season.get("count", 0)
                    video_count = _count_video_files(season_dirs[0][0])
                    if hinted_count > 0 and video_count > hinted_count + _HINT_OVERFLOW_MARGIN:
                        use_consolidated = True
            if use_consolidated:
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
        return _build_normal_preview(
            season_dirs=season_dirs,
            tmdb_seasons=tmdb_seasons,
            tmdb=self.tmdb,
            show_info=self.show_info,
            root=self.root,
            media_fields=self._media_fields,
            season_folders=self._season_folders,
            store_tmdb_data=self._store_tmdb_data,
            resolve_duplicate_episodes=self._resolve_duplicate_episodes,
        )

    def _resolve_duplicate_episodes(self, items: list[PreviewItem]) -> None:
        resolve_duplicate_episodes(
            items,
            show_name=self.show_info.get("name", ""),
        )

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
        return build_completeness_report(
            self._get_tmdb_seasons(),
            items,
            checked_indices=checked_indices,
        )