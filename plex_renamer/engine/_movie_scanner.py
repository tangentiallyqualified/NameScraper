"""Movie scanning helpers and scanner implementation."""

from __future__ import annotations

import re
import threading
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

from ..constants import VIDEO_EXTENSIONS, YEAR_MIN, YEAR_MAX, MediaType
from ..parsing import (
    build_movie_name,
    clean_folder_name,
    extract_year,
    find_companion_subtitles,
    is_sample_file,
    looks_like_tv_episode,
)
from ..tmdb import TMDBClient
from ._scan_runtime import CANCEL_SCAN, _raise_if_cancelled
from ._state import get_auto_accept_threshold
from .matching import (
    _country_from_language,
    boost_scores_with_alt_titles,
    score_results,
)
from .models import CompanionFile, PreviewItem


def _build_subtitle_companions(
    video_path: Path,
    video_new_name: str,
) -> list[CompanionFile]:
    """
    Discover subtitle files paired with *video_path* and return fully-computed
    ``CompanionFile`` objects ready for GUI display and job building.

    The target filename is computed here so no downstream code needs to
    reconstruct it. Adding support for a new companion file type means
    writing a similar helper and appending its results to
    ``PreviewItem.companions``.
    """
    video_stem = Path(video_new_name).stem
    return [
        CompanionFile(
            original=sub_path,
            new_name=video_stem + lang_tag + sub_path.suffix,
            file_type="subtitle",
        )
        for sub_path, lang_tag in find_companion_subtitles(video_path)
    ]


def _prepare_movie_query(stem: str) -> tuple[str, str | None, str]:
    """Clean a filename stem into a TMDB search query and year hint."""
    raw_name = clean_folder_name(stem)
    search_query = clean_folder_name(stem, include_year=False)
    year_hint = extract_year(stem)
    return search_query, year_hint, raw_name


def _build_movie_preview_item(
    file_path: Path,
    chosen: dict,
    root_folder: Path,
) -> PreviewItem:
    """Build a PreviewItem from a chosen TMDB movie match."""
    new_name = build_movie_name(chosen["title"], chosen["year"], file_path.suffix)
    folder_name = build_movie_name(chosen["title"], chosen["year"], "")

    target_dir = root_folder / folder_name
    if file_path.parent == target_dir:
        target_dir = file_path.parent

    return PreviewItem(
        original=file_path,
        new_name=new_name,
        target_dir=target_dir,
        season=None,
        episodes=[],
        status="OK",
        media_type=MediaType.MOVIE,
        media_id=chosen.get("id"),
        media_name=chosen.get("title"),
    )


class MovieScanner:
    """Scan movie files and build PreviewItems using TMDB data."""

    def __init__(
        self,
        tmdb: TMDBClient,
        root_folder: Path,
        files: list[Path] | None = None,
    ):
        self.tmdb = tmdb
        self.root = root_folder
        self._explicit_files = files
        self.movie_info: dict[Path, dict] = {}
        self._search_cache: dict[Path, list[dict]] = {}

    @property
    def explicit_files(self) -> list[Path] | None:
        """The explicit file list passed at construction, or None for folder mode."""
        return self._explicit_files

    def _get_video_files(self) -> list[Path]:
        """Return the files to process, using either the explicit list or a folder scan."""
        if self._explicit_files:
            return sorted(self._explicit_files)
        return sorted(
            file_path for file_path in self.root.rglob("*")
            if file_path.is_file() and file_path.suffix.lower() in VIDEO_EXTENSIONS
        )

    def _filter_tv_show_root_files(
        self,
        files: list[Path],
    ) -> tuple[list[Path], list[PreviewItem]]:
        """Skip files that live under detected TV show roots in folder mode."""
        if self._explicit_files is not None or not files:
            return files, []

        from ..app.services import TVLibraryDiscoveryService

        show_roots = TVLibraryDiscoveryService().discover_show_roots(self.root)
        if not show_roots:
            return files, []

        tv_root_paths = [
            Path(candidate.folder)
            for candidate in show_roots
            if Path(candidate.folder) != self.root
        ]
        if not tv_root_paths:
            return files, []

        remaining: list[Path] = []
        skipped: list[PreviewItem] = []

        for file_path in files:
            if any(
                tv_root == file_path.parent or tv_root in file_path.parents
                for tv_root in tv_root_paths
            ):
                skipped.append(PreviewItem(
                    original=file_path,
                    new_name=None,
                    target_dir=None,
                    season=None,
                    episodes=[],
                    status="SKIP: inside detected TV show folder",
                    media_type=MediaType.OTHER,
                ))
                continue
            remaining.append(file_path)

        return remaining, skipped

    @staticmethod
    def _filter_sequential_batches(
        files: list[Path],
    ) -> tuple[list[Path], list[PreviewItem]]:
        """Detect groups of files that look like sequentially numbered TV episodes."""
        number_pattern = re.compile(
            r"^(.*?)\s*-\s*(\d{1,3})\s*(?:[\s.\-(v]|$)",
        )

        by_folder: dict[Path, list[tuple[Path, str, int]]] = defaultdict(list)

        for file_path in files:
            match = number_pattern.search(file_path.stem)
            if match:
                prefix = match.group(1).strip().lower()
                number = int(match.group(2))
                if YEAR_MIN <= number <= YEAR_MAX:
                    continue
                by_folder[file_path.parent].append((file_path, prefix, number))

        skip_set: set[Path] = set()
        for _folder, entries in by_folder.items():
            prefix_groups: dict[str, list[tuple[Path, int]]] = defaultdict(list)
            for file_path, prefix, number in entries:
                prefix_groups[prefix].append((file_path, number))

            for _prefix, group in prefix_groups.items():
                if len(group) < 3:
                    continue
                numbers = sorted(number for _, number in group)
                number_range = numbers[-1] - numbers[0]
                if number_range < len(group) * 3:
                    for file_path, _number in group:
                        skip_set.add(file_path)

        remaining = []
        skipped = []
        for file_path in files:
            if file_path in skip_set:
                skipped.append(PreviewItem(
                    original=file_path,
                    new_name=None,
                    target_dir=None,
                    season=None,
                    episodes=[],
                    status="SKIP: looks like a TV episode (sequential batch)",
                    media_type=MediaType.OTHER,
                ))
            else:
                remaining.append(file_path)

        return remaining, skipped

    def scan(
        self,
        pick_movie_callback: Callable | None = None,
        progress_callback: Callable | None = None,
        cancel_event: threading.Event | None = None,
    ) -> list[PreviewItem]:
        """Scan files and build preview items with automatic TMDB matching."""
        items: list[PreviewItem] = []
        _raise_if_cancelled(cancel_event)

        all_video_files = self._get_video_files()
        all_video_files, tv_root_skipped = self._filter_tv_show_root_files(all_video_files)
        items.extend(tv_root_skipped)
        video_files: list[Path] = []

        for file_path in all_video_files:
            _raise_if_cancelled(cancel_event)
            if is_sample_file(file_path):
                items.append(PreviewItem(
                    original=file_path,
                    new_name=None,
                    target_dir=None,
                    season=None,
                    episodes=[],
                    status="SKIP: release sample clip",
                    media_type=MediaType.OTHER,
                ))
            elif looks_like_tv_episode(file_path):
                items.append(PreviewItem(
                    original=file_path,
                    new_name=None,
                    target_dir=None,
                    season=None,
                    episodes=[],
                    status="SKIP: looks like a TV episode",
                    media_type=MediaType.OTHER,
                ))
            else:
                video_files.append(file_path)

        if len(video_files) >= 3:
            video_files, batch_skipped = self._filter_sequential_batches(video_files)
            items.extend(batch_skipped)
        _raise_if_cancelled(cancel_event)

        if not video_files:
            return items

        if len(video_files) == 1:
            return items + self._scan_single(video_files[0], pick_movie_callback)

        prepared = [_prepare_movie_query(file_path.stem) for file_path in video_files]

        def _progress(done, total):
            _raise_if_cancelled(cancel_event)
            if progress_callback:
                progress_callback(done, total, "Searching TMDB...")

        search_queries = [(query, year) for query, year, _raw_name in prepared]
        all_results = self.tmdb.search_movies_batch(
            search_queries,
            progress_callback=_progress,
        )

        for file_path, (_search_query, year_hint, raw_name), results in zip(
            video_files,
            prepared,
            all_results,
        ):
            _raise_if_cancelled(cancel_event)
            self._search_cache[file_path] = results

            if not results:
                items.append(PreviewItem(
                    original=file_path,
                    new_name=None,
                    target_dir=None,
                    season=None,
                    episodes=[],
                    status="REVIEW: no TMDB results — click to search manually",
                    media_type=MediaType.MOVIE,
                ))
                continue

            chosen, confidence = self._best_match(results, raw_name, year_hint)
            self.movie_info[file_path] = chosen

            item = _build_movie_preview_item(file_path, chosen, self.root)
            item.companions = _build_subtitle_companions(file_path, item.new_name)
            if confidence < get_auto_accept_threshold():
                item.status = (
                    f"REVIEW: best match \"{chosen['title']}\" "
                    f"(confidence {confidence:.0%}) — click to verify"
                )
            items.append(item)

        return items

    def _scan_single(
        self,
        file_path: Path,
        pick_movie_callback: Callable | None,
    ) -> list[PreviewItem]:
        """Handle single-file scan with confirmation dialog."""
        search_query, year_hint, _raw_name = _prepare_movie_query(file_path.stem)

        results = self.tmdb.search_with_fallback(
            search_query,
            self.tmdb.search_movie,
            year=year_hint,
        )
        if not results:
            results = self.tmdb.search_with_fallback(
                search_query,
                self.tmdb.search_movie,
            )
        self._search_cache[file_path] = results

        if pick_movie_callback:
            chosen = pick_movie_callback(results or [], file_path.name)
            if chosen is CANCEL_SCAN:
                return []
        else:
            chosen = results[0] if results else None

        if not chosen:
            return [PreviewItem(
                original=file_path,
                new_name=None,
                target_dir=None,
                season=None,
                episodes=[],
                status="SKIP: no movie selected" if results else "REVIEW: no TMDB results — click to search manually",
                media_type=MediaType.MOVIE,
            )]

        self.movie_info[file_path] = chosen
        item = _build_movie_preview_item(file_path, chosen, self.root)
        item.companions = _build_subtitle_companions(file_path, item.new_name)
        return [item]

    def rematch_file(
        self,
        item: PreviewItem,
        chosen: dict,
    ) -> PreviewItem:
        """Re-match a single file to a different TMDB movie."""
        self.movie_info[item.original] = chosen
        return _build_movie_preview_item(item.original, chosen, self.root)

    def set_movie_info(self, file_path: Path, info: dict) -> None:
        """Hydrate cached movie metadata for a file during session restore."""
        self.movie_info[file_path] = dict(info)

    def set_search_results(self, file_path: Path, results: list[dict]) -> None:
        """Hydrate cached TMDB search results for a file during session restore."""
        self._search_cache[file_path] = list(results)

    def get_search_results(self, file_path: Path) -> list[dict]:
        """Return cached TMDB search results for a file."""
        return self._search_cache.get(file_path, [])

    def _best_match(
        self,
        results: list[dict],
        raw_name: str,
        year_hint: str | None,
    ) -> tuple[dict, float]:
        """Pick the best TMDB result using title similarity and year matching."""
        scored = score_results(results, raw_name, year_hint, title_key="title")
        if not scored:
            return results[0], 0.0
        scored = boost_scores_with_alt_titles(
            scored,
            raw_name,
            year_hint,
            self.tmdb,
            title_key="title",
            media_type="movie",
            preferred_country=_country_from_language(self.tmdb.language),
        )
        return scored[0]