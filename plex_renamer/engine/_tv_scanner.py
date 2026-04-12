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
    normalize_for_specials,
)
from ..tmdb import TMDBClient
from ._movie_scanner import _build_subtitle_companions
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

        if self._season_folders:
            self._season_dirs = sorted(
                [(folder, season_num) for season_num, folder in self._season_folders.items()],
                key=lambda item: item[1],
            )
            return self._season_dirs

        dirs_with_season: list[tuple[Path, int]] = []
        unmatched_dirs: list[Path] = []
        for directory in self.root.iterdir():
            if not directory.is_dir():
                continue
            season_num = get_season(directory)
            if season_num is not None:
                dirs_with_season.append((directory, season_num))
            else:
                unmatched_dirs.append(directory)

        if dirs_with_season and unmatched_dirs:
            matched_via_tmdb = self._match_dirs_to_tmdb_seasons(
                unmatched_dirs,
                {season_num for _, season_num in dirs_with_season},
            )
            dirs_with_season.extend(matched_via_tmdb)

        dirs_with_season.sort(key=lambda item: item[1])

        if not dirs_with_season:
            season_num = 1 if self._season_hint is None else self._season_hint
            self._season_dirs = [(self.root, season_num)]
        else:
            self._season_dirs = dirs_with_season
        return self._season_dirs

    def _match_dirs_to_tmdb_seasons(
        self,
        dirs: list[Path],
        already_matched: set[int],
    ) -> list[tuple[Path, int]]:
        """Try to match directories against TMDB season names."""
        show_id = self.show_info.get("id")
        if not show_id:
            return []

        show_data = self.tmdb.get_tv_details(show_id)
        if not show_data:
            return []

        tmdb_season_names: dict[int, str] = {}
        for season_info in show_data.get("seasons", []):
            season_num = season_info.get("season_number", 0)
            name = season_info.get("name", "")
            if season_num > 0 and name and season_num not in already_matched:
                tmdb_season_names[season_num] = name

        if not tmdb_season_names:
            return []

        show_title = clean_folder_name(
            self.show_info.get("name", ""),
            include_year=False,
        ).lower()

        results: list[tuple[Path, int]] = []
        used_seasons: set[int] = set()

        for directory in dirs:
            folder_cleaned = clean_folder_name(
                directory.name,
                include_year=False,
            ).lower()

            best_season_num: int | None = None
            best_score = 0.0

            for season_num, tmdb_name in tmdb_season_names.items():
                if season_num in used_seasons:
                    continue
                tmdb_cleaned = tmdb_name.lower()

                if tmdb_cleaned in folder_cleaned or folder_cleaned in tmdb_cleaned:
                    score = 1.0
                else:
                    folder_suffix = folder_cleaned
                    tmdb_suffix = tmdb_cleaned
                    if folder_suffix.startswith(show_title):
                        folder_suffix = folder_suffix[len(show_title):].strip()
                    if tmdb_suffix.startswith(show_title):
                        tmdb_suffix = tmdb_suffix[len(show_title):].strip()

                    if not folder_suffix or not tmdb_suffix:
                        continue

                    if tmdb_suffix in folder_suffix or folder_suffix in tmdb_suffix:
                        score = 0.9
                    else:
                        folder_tokens = {token for token in folder_suffix.split() if len(token) > 2}
                        tmdb_tokens = {token for token in tmdb_suffix.split() if len(token) > 2}
                        if not tmdb_tokens:
                            continue
                        overlap = len(folder_tokens & tmdb_tokens)
                        score = overlap / max(len(tmdb_tokens), 1)

                if score > best_score and score >= 0.5:
                    best_score = score
                    best_season_num = season_num

            if best_season_num is not None:
                _log.info(
                    "Matched folder '%s' to TMDB season %d via name similarity (score=%.2f)",
                    directory.name,
                    best_season_num,
                    best_score,
                )
                results.append((directory, best_season_num))
                used_seasons.add(best_season_num)

        return results

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

        s0_titles: dict = {}
        s0_posters: dict = {}
        s0_episodes: dict = {}
        s0_tmdb_title_lookup: dict = {}
        s0_loaded = False

        def ensure_specials_data() -> None:
            nonlocal s0_titles, s0_posters, s0_episodes, s0_tmdb_title_lookup, s0_loaded
            if s0_loaded:
                return
            s0_loaded = True

            if 0 in tmdb_seasons:
                s0_titles = tmdb_seasons[0]["titles"]
                s0_posters = tmdb_seasons[0]["posters"]
                s0_episodes = tmdb_seasons[0].get("episodes", {})
            else:
                s0_data = self.tmdb.get_season(self.show_info["id"], 0)
                s0_titles = s0_data["titles"]
                s0_posters = s0_data["posters"]
                s0_episodes = s0_data.get("episodes", {})

            if s0_titles:
                self._store_tmdb_data(0, s0_titles, s0_posters, s0_episodes)
                s0_tmdb_title_lookup = {
                    normalize_for_specials(title): (episode_num, title)
                    for episode_num, title in s0_titles.items()
                }

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
            if season_num == 0 and titles:
                for episode_num, title in titles.items():
                    normalized = normalize_for_specials(title)
                    tmdb_title_lookup[normalized] = (episode_num, title)
                ensure_specials_data()
                titles = s0_titles
                posters = s0_posters
                episodes = s0_episodes
                tmdb_title_lookup = s0_tmdb_title_lookup

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
                        ensure_specials_data()
                        item = self._match_special(
                            file_path,
                            episode_numbers,
                            raw_title,
                            s0_titles,
                            s0_tmdb_title_lookup,
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
                    ensure_specials_data()
                    items.extend(self._scan_nested_extras(
                        entry,
                        s0_titles,
                        s0_tmdb_title_lookup,
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
        """Scan a nested extras folder and match its files against TMDB Season 0 specials."""
        items: list[PreviewItem] = []
        for file_path in sorted(extras_dir.iterdir()):
            if not file_path.is_file() or file_path.suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            episode_numbers, raw_title, _is_season_relative = extract_episode(file_path.name)
            item = self._match_special(
                file_path,
                episode_numbers,
                raw_title,
                s0_titles,
                s0_tmdb_title_lookup,
                specials_target,
                from_extras_folder=True,
            )
            items.append(item)
        return items

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
        """Try to match a specials/extras file to a TMDB Season 0 episode."""
        matched_ep = None
        matched_title = None

        if not from_extras_folder and episode_numbers:
            for episode_num in episode_numbers:
                if episode_num in titles:
                    matched_ep = episode_num
                    matched_title = titles[episode_num]
                    break

        if not matched_ep and raw_title:
            matched_ep, matched_title = self._fuzzy_match_special(raw_title, tmdb_title_lookup)

        if not matched_ep:
            stem = file_path.stem
            cleaned_stem = re.sub(
                r"^(?:Season|S)\s*\d+\s*[-._]\s*",
                "",
                stem,
                flags=re.IGNORECASE,
            ).strip()
            if cleaned_stem:
                matched_ep, matched_title = self._fuzzy_match_special(
                    cleaned_stem,
                    tmdb_title_lookup,
                )

        if matched_ep is not None:
            new_name = build_tv_name(
                self.show_info["name"],
                self.show_info["year"],
                0,
                [matched_ep],
                [matched_title],
                file_path.suffix,
            )
            return PreviewItem(
                original=file_path,
                new_name=new_name,
                target_dir=specials_target,
                season=0,
                episodes=[matched_ep],
                status="OK",
                **self._media_fields,
            )

        if from_extras_folder:
            unmatched_target = self.root / "Unmatched" / file_path.parent.name
            return PreviewItem(
                original=file_path,
                new_name=file_path.name,
                target_dir=unmatched_target,
                season=0,
                episodes=episode_numbers,
                status="UNMATCHED: no TMDB special found - moving to Unmatched",
                **self._media_fields,
            )

        return PreviewItem(
            original=file_path,
            new_name=file_path.name,
            target_dir=specials_target,
            season=0,
            episodes=episode_numbers,
            status="OK",
            **self._media_fields,
        )

    @staticmethod
    def _fuzzy_match_special(
        text: str,
        tmdb_title_lookup: dict,
    ) -> tuple[int | None, str | None]:
        """Try to fuzzy-match a text string against TMDB Season 0 titles."""
        normalized = normalize_for_specials(text)
        if not normalized:
            return None, None

        if normalized in tmdb_title_lookup:
            episode_num, title = tmdb_title_lookup[normalized]
            return episode_num, title

        for norm_key, (episode_num, original_title) in tmdb_title_lookup.items():
            if norm_key and (normalized in norm_key or norm_key in normalized):
                return episode_num, original_title

        return None, None

    def _build_consolidated_preview(
        self,
        season_dirs: list[tuple[Path, int]],
        tmdb_seasons: dict,
    ) -> list[PreviewItem]:
        """Build preview mapping files in absolute order to TMDB structure."""
        all_files = self._collect_absolute_files(season_dirs)

        tmdb_list: list[tuple[int, int, str]] = []
        for season_num in sorted(tmdb_seasons.keys()):
            if season_num == 0:
                continue
            season_data = tmdb_seasons[season_num]
            for episode_num in sorted(season_data["titles"].keys()):
                tmdb_list.append((season_num, episode_num, season_data["titles"][episode_num]))

        for season_num, season_data in tmdb_seasons.items():
            self._store_tmdb_data(
                season_num,
                season_data["titles"],
                season_data["posters"],
                season_data.get("episodes", {}),
            )

        title_matches = self._try_title_based_matching(all_files, tmdb_seasons)
        if title_matches is not None:
            items: list[PreviewItem] = []
            for index, (file_path, _abs_num, _raw_title, episode_numbers, is_season_relative, _season_hint) in enumerate(all_files):
                match = title_matches[index]
                if match is None:
                    items.append(PreviewItem(
                        original=file_path,
                        new_name=None,
                        target_dir=None,
                        season=0,
                        episodes=episode_numbers,
                        status="SKIP: could not match episode title to TMDB",
                        **self._media_fields,
                    ))
                    continue
                season_num, episode_num, title = match
                target_dir = self.root / f"Season {season_num:02d}"
                new_name = build_tv_name(
                    self.show_info["name"],
                    self.show_info["year"],
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
                    **self._media_fields,
                ))
            self._resolve_duplicate_episodes(items)
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
                    **self._media_fields,
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

            target_dir = self.root / f"Season {target_season:02d}"
            new_name = build_tv_name(
                self.show_info["name"],
                self.show_info["year"],
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
                **self._media_fields,
            ))

        self._resolve_duplicate_episodes(items)
        return items

    def _try_title_based_matching(
        self,
        all_files: list[tuple[Path, int, str | None, list[int], bool, int | None]],
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

            match = self._match_file_title_to_tmdb(raw_title, title_lookup, number_lookup, used)
            if match is not None:
                used.add((match[0], match[1]))
            matches.append(match)

        matched_count = sum(1 for match in matches if match is not None)
        if matched_count < len(all_files) * 0.5:
            return None

        return matches

    _RE_LEADING_ABS_NUM = re.compile("^(\\d{1,4})\\s*[-–]\\s*")

    @classmethod
    def _match_file_title_to_tmdb(
        cls,
        raw_title: str | None,
        title_lookup: dict[str, tuple[int, int, str]],
        number_lookup: dict[int, tuple[int, int, str]],
        used: set[tuple[int, int]],
    ) -> tuple[int, int, str] | None:
        """Match a file's title against the cross-season TMDB title lookup."""
        if not raw_title:
            return None

        cleaned_title = raw_title
        abs_match = cls._RE_LEADING_ABS_NUM.match(raw_title)
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

    def _collect_absolute_files(
        self,
        season_dirs: list[tuple[Path, int]],
    ) -> list[tuple[Path, int, str | None, list[int], bool, int | None]]:
        """Collect all video files sorted by absolute episode number."""
        all_files = []
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