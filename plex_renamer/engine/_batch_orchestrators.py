"""Batch orchestration for TV and movie library discovery/scanning."""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from ..constants import SCORE_TIE_MARGIN, VIDEO_EXTENSIONS
from ..parsing import (
    best_tv_match_title,
    clean_folder_name,
    extract_year,
    get_season,
    is_sample_file,
    looks_like_tv_episode,
)
from ..tmdb import TMDBClient
from ._batch_tv_duplicates import (
    apply_duplicate_labels as _apply_tv_duplicate_labels,
    normalized_relative_folder as _normalized_tv_relative_folder,
)
from ._batch_tv_match_policy import (
    count_season_subdirs as _count_tv_season_subdirs,
    episode_count_tiebreak as _episode_count_tiebreak,
)
from ._batch_tv_season_merge import (
    expanded_season_folders as _expanded_tv_season_folders,
    merge_season_siblings as _merge_tv_season_siblings,
    represented_seasons as _represented_tv_seasons,
    resolve_season_folder as _resolve_tv_season_folder,
    season_merge_priority as _season_merge_priority,
)
from ._rename_execution import check_duplicates
from ._scan_runtime import ScanCancelledError, _raise_if_cancelled
from ._state import get_auto_accept_threshold
from .matching import (
    _best_episode_title_similarity,
    _country_from_language,
    _tv_episode_evidence_adjustment,
    boost_scores_with_alt_titles,
    boost_tv_scores_with_episode_evidence,
    pick_alternate_matches,
    score_results,
    score_tv_results,
)
from .models import (
    DirectEpisodeEvidence,
    PreviewItem,
    ScanState,
    collect_direct_episode_evidence,
    infer_explicit_season_assignment,
)

_log = logging.getLogger(__name__)


class BatchTVOrchestrator:
    """
    Discovers TV show folders in a library root, matches each to TMDB,
    and creates ScanState instances for the GUI.

    Two-phase workflow:
      Phase 1 (match): Scan filesystem, identify show folders, parallel
          TMDB search. Fast — no season data fetched yet.
      Phase 2 (scan): For each matched show, run TVScanner to build
          episode previews. Can be triggered per-show or in bulk.
    """

    def __init__(
        self,
        tmdb: TMDBClient,
        library_root: Path,
        discovery_service=None,
    ):
        self.tmdb = tmdb
        self.root = library_root
        self.states: list[ScanState] = []
        self.discovery_service = discovery_service

    def _apply_duplicate_labels(self) -> None:
        _apply_tv_duplicate_labels(self.states)

    def _episode_count_tiebreak(
        self,
        scored: list[tuple[dict, float]],
        file_count: int,
        threshold: float = 0.10,
        compare_seasons: bool = False,
    ) -> tuple[dict, float]:
        return _episode_count_tiebreak(
            self.tmdb,
            scored,
            file_count,
            threshold=threshold,
            compare_seasons=compare_seasons,
        )

    @staticmethod
    def _collect_direct_episode_evidence(folder: Path) -> list[DirectEpisodeEvidence]:
        """Collect explicit ``S##E##`` evidence from direct child video files."""
        return collect_direct_episode_evidence(folder)

    @staticmethod
    def _best_episode_title_similarity(
        raw_title: str | None,
        season_titles: dict[int, str],
    ) -> float:
        return _best_episode_title_similarity(raw_title, season_titles)

    def _tv_episode_evidence_adjustment(
        self,
        show_id: int,
        evidence: list[DirectEpisodeEvidence],
    ) -> float:
        return _tv_episode_evidence_adjustment(self.tmdb, show_id, evidence)

    def _boost_tv_scores_with_episode_evidence(
        self,
        scored: list[tuple[dict, float]],
        evidence: list[DirectEpisodeEvidence],
    ) -> list[tuple[dict, float]]:
        return boost_tv_scores_with_episode_evidence(self.tmdb, scored, evidence)

    def _get_discovery_service(self):
        if self.discovery_service is None:
            from ..app.services import TVLibraryDiscoveryService

            self.discovery_service = TVLibraryDiscoveryService()
        return self.discovery_service

    def _build_show_candidates(
        self,
        discovered: list[object],
        cancel_event: threading.Event | None = None,
    ) -> list[tuple[object, str, str, str, str | None, list[DirectEpisodeEvidence]]]:
        candidates: list[tuple[object, str, str, str, str | None, list[DirectEpisodeEvidence]]] = []
        for candidate in discovered:
            _raise_if_cancelled(cancel_event)
            cleaned = best_tv_match_title(candidate.folder, include_year=False)
            score_name = best_tv_match_title(candidate.folder)
            folder_score_name = clean_folder_name(candidate.folder.name)
            year_hint = extract_year(candidate.folder.name)
            episode_evidence = self._collect_direct_episode_evidence(candidate.folder)
            candidates.append((
                candidate,
                cleaned,
                score_name,
                folder_score_name,
                year_hint,
                episode_evidence,
            ))
        return candidates

    @staticmethod
    def _build_unmatched_show_state(
        candidate,
        folder: Path,
        year_hint: str | None,
        results: list[dict],
        episode_evidence: list[DirectEpisodeEvidence],
    ) -> ScanState:
        return ScanState(
            folder=folder,
            media_info={
                "id": None, "name": folder.name,
                "year": year_hint or "", "poster_path": None,
                "overview": "",
            },
            confidence=0.0,
            search_results=results,
            alternate_matches=[],
            checked=False,
            relative_folder=candidate.relative_folder,
            parent_relative_folder=candidate.parent_relative_folder,
            discovery_reason=candidate.discovery_reason,
            has_direct_season_subdirs=candidate.has_direct_season_subdirs,
            direct_episode_file_count=candidate.direct_episode_file_count,
            direct_video_file_count=candidate.direct_video_file_count,
            discovered_via_symlink=candidate.discovered_via_symlink,
            season_assignment=infer_explicit_season_assignment(folder, episode_evidence),
        )

    def _season_names_for_match(self, best: dict) -> dict[int, str]:
        season_names: dict[int, str] = {}
        show_id = best.get("id")
        if show_id is None:
            return season_names
        details = self.tmdb.get_tv_details(show_id)
        if not details:
            return season_names
        for season_info in details.get("seasons", []):
            season_number = season_info.get("season_number")
            name = season_info.get("name", "")
            if season_number is None or season_number <= 0 or not name:
                continue
            generic = f"Season {season_number}"
            if name != generic:
                season_names[season_number] = name
        return season_names

    def _select_best_show_match(
        self,
        candidate,
        folder: Path,
        score_name: str,
        folder_score_name: str,
        year_hint: str | None,
        episode_evidence: list[DirectEpisodeEvidence],
        results: list[dict],
        cancel_event: threading.Event | None = None,
    ) -> tuple[dict, float, list[dict], bool, dict[int, str]]:
        scored = score_tv_results(
            results,
            score_name,
            year_hint,
            self.tmdb,
            folder=folder,
            folder_score_name=folder_score_name,
            episode_evidence=episode_evidence,
        )

        best, best_score = scored[0]

        file_count = candidate.direct_video_file_count
        use_seasons = False
        if file_count == 0 and candidate.has_direct_season_subdirs:
            _raise_if_cancelled(cancel_event)
            file_count = _count_tv_season_subdirs(candidate.folder)
            use_seasons = True
        if file_count > 0 and len(scored) >= 2:
            runner_up, runner_up_score = scored[1]
            if best_score - runner_up_score <= 0.10:
                best, best_score = self._episode_count_tiebreak(
                    scored,
                    file_count,
                    threshold=0.10,
                    compare_seasons=use_seasons,
                )

        ep_file_count = file_count if not use_seasons else candidate.direct_episode_file_count
        if ep_file_count > 0 and best.get("id") is not None:
            details = self.tmdb.get_tv_details(best["id"])
            tmdb_ep_count = (details or {}).get("number_of_episodes") or 0
            if tmdb_ep_count > 0:
                if ep_file_count == tmdb_ep_count:
                    best_score = min(best_score + 0.10, 1.0)
                elif abs(ep_file_count - tmdb_ep_count) <= 2:
                    best_score = min(best_score + 0.05, 1.0)

        alternates = pick_alternate_matches(
            scored,
            selected_id=best.get("id"),
            limit=3,
        )

        tie_detected = False
        if len(scored) >= 2:
            for result, score in scored:
                if result.get("id") != best.get("id"):
                    if best_score - score <= SCORE_TIE_MARGIN and best_score >= get_auto_accept_threshold():
                        tie_detected = True
                    break

        season_names = self._season_names_for_match(best)
        return best, best_score, alternates, tie_detected, season_names

    def _build_discovered_show_state(
        self,
        candidate,
        score_name: str,
        folder_score_name: str,
        year_hint: str | None,
        episode_evidence: list[DirectEpisodeEvidence],
        results: list[dict],
        cancel_event: threading.Event | None = None,
    ) -> ScanState:
        folder = candidate.folder
        if not results:
            return self._build_unmatched_show_state(
                candidate,
                folder,
                year_hint,
                results,
                episode_evidence,
            )

        best, best_score, alternates, tie_detected, season_names = self._select_best_show_match(
            candidate,
            folder,
            score_name,
            folder_score_name,
            year_hint,
            episode_evidence,
            results,
            cancel_event=cancel_event,
        )
        auto_check = best_score >= get_auto_accept_threshold() and not tie_detected

        return ScanState(
            folder=folder,
            media_info=best,
            confidence=best_score,
            search_results=results,
            alternate_matches=alternates,
            checked=auto_check,
            relative_folder=candidate.relative_folder,
            parent_relative_folder=candidate.parent_relative_folder,
            discovery_reason=candidate.discovery_reason,
            has_direct_season_subdirs=candidate.has_direct_season_subdirs,
            direct_episode_file_count=candidate.direct_episode_file_count,
            direct_video_file_count=candidate.direct_video_file_count,
            discovered_via_symlink=candidate.discovered_via_symlink,
            tie_detected=tie_detected,
            season_names=season_names,
            season_assignment=infer_explicit_season_assignment(folder, episode_evidence),
        )

    @staticmethod
    def _sort_discovered_show_state(state: ScanState) -> tuple[int, str, str]:
        if state.duplicate_of is not None:
            group = 3
        elif state.show_id is None:
            group = 2
        elif state.needs_review:
            group = 1
        else:
            group = 0
        return (
            group,
            state.display_name.lower(),
            _normalized_tv_relative_folder(state.relative_folder, state.folder),
        )

    def discover_shows(
        self,
        progress_callback: Callable | None = None,
        cancel_event: threading.Event | None = None,
    ) -> list[ScanState]:
        """Phase 1: Find show folders and match to TMDB."""
        discovery_service = self._get_discovery_service()
        discovered = discovery_service.discover_show_roots(self.root)
        candidates = self._build_show_candidates(discovered, cancel_event=cancel_event)

        if not candidates:
            return []

        _log.info("Discovered %d candidate show folders", len(candidates))

        queries = [(name, year) for _, name, _, _, year, _ in candidates]
        all_results = self.tmdb.search_tv_batch(
            queries,
            progress_callback=progress_callback,
        )

        states: list[ScanState] = []
        for (candidate, _cleaned_name, score_name, folder_score_name, year_hint, episode_evidence), results in zip(candidates, all_results):
            _raise_if_cancelled(cancel_event)
            states.append(
                self._build_discovered_show_state(
                    candidate,
                    score_name,
                    folder_score_name,
                    year_hint,
                    episode_evidence,
                    results,
                    cancel_event=cancel_event,
                )
            )

        states = _merge_tv_season_siblings(states)
        states.sort(key=self._sort_discovered_show_state)

        self.states = states
        self._apply_duplicate_labels()
        self.states.sort(key=self._sort_discovered_show_state)
        return states

    def merge_rematched_state(self, state: ScanState) -> ScanState:
        """Merge a rematched season/special state into existing show siblings."""
        show_id = state.show_id
        state_seasons = _represented_tv_seasons(state)
        if show_id is None or not state_seasons:
            self._apply_duplicate_labels()
            return state

        merge_group: list[ScanState] = [state]
        covered_seasons = set(state_seasons)
        for other in self.states:
            if other is state or other.show_id != show_id:
                continue
            other_seasons = _represented_tv_seasons(other)
            if not other_seasons or covered_seasons & other_seasons:
                continue
            merge_group.append(other)
            covered_seasons.update(other_seasons)

        if len(merge_group) == 1:
            self._apply_duplicate_labels()
            return state

        target = max(merge_group, key=_season_merge_priority)
        season_map: dict[int, Path] = {}
        total_files = 0
        total_episode_files = 0
        merged_search_results = target.search_results
        merged_alternates = target.alternate_matches
        merged_tie_detected = target.tie_detected
        merged_checked = False

        for member in merge_group:
            total_files += member.direct_video_file_count
            total_episode_files += member.direct_episode_file_count
            for season_num, folder in _expanded_tv_season_folders(member).items():
                season_map[season_num] = folder
            for season_num, name in member.season_names.items():
                target.season_names.setdefault(season_num, name)
            if member is state:
                merged_search_results = member.search_results
                merged_alternates = member.alternate_matches
                merged_tie_detected = member.tie_detected
            merged_checked = merged_checked or member.checked

        target.media_info = state.media_info
        target.confidence = max(member.confidence for member in merge_group)
        target.match_origin = state.match_origin
        target.search_results = merged_search_results
        target.alternate_matches = merged_alternates
        target.tie_detected = merged_tie_detected
        target.checked = merged_checked
        target.season_folders = season_map
        target.season_assignment = None
        target.direct_video_file_count = total_files
        target.direct_episode_file_count = total_episode_files
        target.duplicate_of = None
        target.duplicate_of_relative_folder = None
        target.reset_scan()

        self.states[:] = [member for member in self.states if member not in merge_group or member is target]
        self._apply_duplicate_labels()
        return target

    def scan_show(
        self,
        state: ScanState,
        progress_callback: Callable | None = None,
        cancel_event: threading.Event | None = None,
    ) -> None:
        """Phase 2: Run TVScanner for a single show and populate its ScanState."""
        if state.scanned or state.scanning:
            return
        if state.show_id is None:
            _log.warning("Cannot scan %s — no TMDB match", state.folder.name)
            return

        from ._tv_scanner import TVScanner

        _raise_if_cancelled(cancel_event)

        state.scanning = True
        _log.info("Scanning episodes for: %s", state.display_name)

        try:
            scanner = TVScanner(
                self.tmdb,
                state.media_info,
                state.folder,
                season_hint=state.season_assignment,
                season_folders=state.season_folders or None,
            )
            items, has_mismatch = scanner.scan()
            _raise_if_cancelled(cancel_event)

            _log.info(
                "Folder '%s' produced %d items (mismatch=%s), seasons: %s",
                state.folder.name,
                len(items),
                has_mismatch,
                sorted({item.season for item in items if item.season is not None}),
            )

            if has_mismatch:
                _log.info(
                    "Season mismatch detected for %s, using consolidated scan",
                    state.display_name,
                )
                items = scanner.scan_consolidated()
                _raise_if_cancelled(cancel_event)

            check_duplicates(items)

            initial_checked = {index for index, item in enumerate(items) if item.status == "OK"}
            completeness = scanner.get_completeness(items, checked_indices=initial_checked)

            state.scanner = scanner
            state.preview_items = items
            state.completeness = completeness
            state.scanned = True

            has_actionable = any(item.is_actionable for item in items)
            if not has_actionable:
                state.checked = False
        finally:
            state.scanning = False

        by_season: dict[int | None, int] = defaultdict(int)
        for item in items:
            by_season[item.season] += 1
        _log.info(
            "Scan complete for '%s': %d total items, seasons: %s",
            state.display_name,
            len(items),
            dict(sorted(by_season.items())),
        )

    def scan_all(
        self,
        progress_callback: Callable | None = None,
        cancel_event: threading.Event | None = None,
    ) -> None:
        """Phase 2 bulk: Scan all shows that have a TMDB match."""
        to_scan = [
            state for state in self.states
            if not state.scanned and state.show_id is not None
        ]
        total = len(to_scan)

        for index, state in enumerate(to_scan):
            _raise_if_cancelled(cancel_event)
            try:
                self.scan_show(state, cancel_event=cancel_event)
            except Exception as error:
                if isinstance(error, ScanCancelledError):
                    raise
                _log.error("Failed to scan %s: %s", state.display_name, error)
            if progress_callback:
                progress_callback(index + 1, total)

    def reconcile_scanned_state(self, state: ScanState) -> ScanState:
        """Try to merge a freshly-scanned state into a same-show sibling."""
        if state.show_id is None or not state.preview_items:
            return state
        if state.season_folders or state.season_assignment is not None:
            return state
        detected = {
            item.season for item in state.preview_items
            if item.season is not None
        }
        if len(detected) != 1:
            return state
        season_num = next(iter(detected))
        has_sibling = any(
            other is not state and other.show_id == state.show_id
            for other in self.states
        )
        if not has_sibling:
            return state
        state.season_folders = {
            season_num: _resolve_tv_season_folder(state.folder, season_num),
        }
        return self.merge_rematched_state(state)

    def rematch_show(self, state: ScanState, new_match: dict) -> ScanState:
        """Swap a show's TMDB match and invalidate its scan data."""
        state.media_info = new_match
        raw_name = best_tv_match_title(state.folder)
        year_hint = extract_year(state.folder.name)
        scored = score_tv_results([new_match], raw_name, year_hint, self.tmdb, folder=state.folder)
        state.confidence = scored[0][1] if scored else 0.0
        state.reset_scan()
        merged_state = self.merge_rematched_state(state)
        self._apply_duplicate_labels()
        return merged_state

    @staticmethod
    def is_tv_library(folder: Path) -> bool:
        """Heuristic check: does this folder look like a TV library root."""
        show_like_children = 0
        try:
            for directory in folder.iterdir():
                if not directory.is_dir() or directory.name.startswith("."):
                    continue
                if get_season(directory) is not None:
                    continue
                if directory.name.lower() in (
                    "extras", "featurettes", "@eadir", "#recycle",
                    ".debris", "lost+found",
                ):
                    continue
                has_season_subdir = False
                video_files: list[Path] = []
                for child in directory.iterdir():
                    if child.is_dir() and get_season(child) is not None:
                        has_season_subdir = True
                        break
                    if child.is_file() and child.suffix.lower() in VIDEO_EXTENSIONS:
                        video_files.append(child)

                if has_season_subdir:
                    show_like_children += 1
                elif len(video_files) > 2:
                    show_like_children += 1
                elif video_files and any(looks_like_tv_episode(file) for file in video_files):
                    show_like_children += 1

                if show_like_children >= 2:
                    return True
        except OSError:
            pass
        return False


class BatchMovieOrchestrator:
    """
    Discovers movie folders in a library root, matches each to TMDB,
    and creates ScanState instances for the GUI.

    Two-phase workflow:
      Phase 1 (discover): Scan filesystem via MovieLibraryDiscoveryService,
          identify movie_root and multi_movie_folder candidates, parallel
          TMDB search.
      Phase 2 (scan): For each matched movie, build PreviewItems with
          rename plans. Can be triggered per-movie or in bulk.
    """

    def __init__(
        self,
        tmdb: TMDBClient,
        library_root: Path,
        discovery_service=None,
    ):
        self.tmdb = tmdb
        self.root = library_root
        self.states: list[ScanState] = []
        self.discovery_service = discovery_service

    @staticmethod
    def _normalized_relative_folder(relative_folder: str, fallback: Path) -> str:
        text = relative_folder or fallback.as_posix()
        return text.replace("\\", "/").casefold()

    @classmethod
    def _is_ready_movie_candidate(cls, state: ScanState) -> bool:
        return bool(
            state.scanned
            and state.preview_items
            and not any(item.is_actionable for item in state.preview_items)
        )

    @classmethod
    def _duplicate_priority(cls, state: ScanState) -> tuple[float, int, int, str]:
        normalized_relative = cls._normalized_relative_folder(
            state.relative_folder,
            state.folder,
        )
        depth = len(PurePosixPath(normalized_relative).parts)
        ready_rank = 0 if cls._is_ready_movie_candidate(state) else 1
        evidence_rank = 0 if state.discovery_reason == "title_year_folder" else 1
        return (ready_rank, -state.confidence, depth, evidence_rank, normalized_relative)

    def _apply_duplicate_labels(self) -> None:
        """Mark lower-priority TMDB matches as duplicates deterministically."""
        for state in self.states:
            state.duplicate_of = None
            state.duplicate_of_relative_folder = None

        groups: dict[int, list[ScanState]] = {}
        for state in self.states:
            movie_id = state.show_id
            if movie_id is None:
                continue
            groups.setdefault(movie_id, []).append(state)

        for group in groups.values():
            if len(group) < 2:
                continue
            group.sort(key=self._duplicate_priority)
            primaries: dict[int | None, ScanState] = {}
            for state in group:
                season_assignment = state.season_assignment
                if season_assignment is not None:
                    existing = primaries.get(season_assignment)
                    if existing is None:
                        primaries[season_assignment] = state
                        continue
                else:
                    existing = next(iter(primaries.values()), None) if primaries else None
                    if existing is None:
                        primaries[None] = state
                        continue
                state.duplicate_of = existing.display_name
                state.duplicate_of_relative_folder = existing.relative_folder or None
                state.checked = False

    def _get_discovery_service(self):
        if self.discovery_service is None:
            from ..app.services import MovieLibraryDiscoveryService

            self.discovery_service = MovieLibraryDiscoveryService()
        return self.discovery_service

    def discover_movies(
        self,
        progress_callback: Callable | None = None,
    ) -> list[ScanState]:
        """Phase 1: Find movie folders and match to TMDB."""
        from ._movie_scanner import _prepare_movie_query

        discovery_service = self._get_discovery_service()
        discovered = discovery_service.discover_movie_roots(self.root)

        entries: list[tuple[object, str, str | None, Path | None]] = []
        for candidate in discovered:
            if candidate.discovery_reason == "multiple_direct_video_files":
                video_files = sorted(
                    file for file in candidate.folder.iterdir()
                    if file.is_file() and file.suffix.lower() in VIDEO_EXTENSIONS
                    and not looks_like_tv_episode(file) and not is_sample_file(file)
                )
                for video_file in video_files:
                    query, year, _raw = _prepare_movie_query(video_file.stem)
                    entries.append((candidate, query, year, video_file))
            else:
                cleaned = clean_folder_name(candidate.folder.name, include_year=False)
                year_hint = extract_year(candidate.folder.name)
                entries.append((candidate, cleaned, year_hint, None))

        if not entries:
            return []

        _log.info("Discovered %d movie candidate entries", len(entries))

        queries = [(name, year) for _, name, year, _ in entries]
        all_results = self.tmdb.search_movies_batch(
            queries,
            progress_callback=progress_callback,
        )

        states: list[ScanState] = []
        for (candidate, _search_query, year_hint, source_file), results in zip(entries, all_results):
            folder = candidate.folder

            if not results:
                display = source_file.stem if source_file else folder.name
                state = ScanState(
                    folder=folder,
                    media_info={
                        "id": None, "title": display,
                        "year": year_hint or "", "poster_path": None,
                        "overview": "",
                    },
                    confidence=0.0,
                    search_results=results,
                    alternate_matches=[],
                    checked=False,
                    source_file=source_file,
                    relative_folder=candidate.relative_folder,
                    parent_relative_folder=candidate.parent_relative_folder,
                    discovery_reason=candidate.discovery_reason,
                    direct_video_file_count=candidate.direct_video_file_count,
                    discovered_via_symlink=candidate.discovered_via_symlink,
                )
                states.append(state)
                continue

            raw_name = clean_folder_name(source_file.stem) if source_file else clean_folder_name(folder.name)
            scored = score_results(results, raw_name, year_hint, title_key="title")
            scored = boost_scores_with_alt_titles(
                scored,
                raw_name,
                year_hint,
                self.tmdb,
                title_key="title",
                media_type="movie",
                preferred_country=_country_from_language(self.tmdb.language),
            )

            best, best_score = scored[0]
            alternates = [result for result, score in scored[1:4] if score > 0.3]

            tie_detected = False
            if len(scored) >= 2:
                for result, score in scored:
                    if result.get("id") != best.get("id"):
                        if best_score - score <= SCORE_TIE_MARGIN and best_score >= get_auto_accept_threshold():
                            tie_detected = True
                        break

            auto_check = best_score >= get_auto_accept_threshold() and not tie_detected

            state = ScanState(
                folder=folder,
                media_info=best,
                confidence=best_score,
                search_results=results,
                alternate_matches=alternates,
                checked=auto_check,
                source_file=source_file,
                relative_folder=candidate.relative_folder,
                parent_relative_folder=candidate.parent_relative_folder,
                discovery_reason=candidate.discovery_reason,
                direct_video_file_count=candidate.direct_video_file_count,
                discovered_via_symlink=candidate.discovered_via_symlink,
                tie_detected=tie_detected,
            )
            states.append(state)

        def _sort_key(state: ScanState) -> tuple:
            if state.duplicate_of is not None:
                group = 3
            elif state.show_id is None:
                group = 2
            elif state.needs_review:
                group = 1
            else:
                group = 0
            return (
                group,
                state.display_name.lower(),
                self._normalized_relative_folder(state.relative_folder, state.folder),
            )

        states.sort(key=_sort_key)

        self.states = states
        self._apply_duplicate_labels()
        self.states.sort(key=_sort_key)
        return states

    def scan_movie(
        self,
        state: ScanState,
        progress_callback: Callable | None = None,
    ) -> None:
        """Phase 2: Build preview items for a single movie ScanState."""
        if state.scanned or state.scanning:
            return
        if state.show_id is None:
            _log.warning("Cannot scan %s — no TMDB match", state.folder.name)
            return

        from ._movie_scanner import MovieScanner, _build_movie_preview_item, _build_subtitle_companions

        state.scanning = True
        _log.info("Scanning movie: %s", state.display_name)

        try:
            chosen = state.media_info
            if state.source_file is not None:
                video_files = [state.source_file] if state.source_file.exists() else []
            else:
                video_files = sorted(
                    file for file in state.folder.iterdir()
                    if file.is_file() and file.suffix.lower() in VIDEO_EXTENSIONS
                    and not is_sample_file(file) and not looks_like_tv_episode(file)
                )

            items: list[PreviewItem] = []
            for file in video_files:
                item = _build_movie_preview_item(file, chosen, self.root)
                item.companions = _build_subtitle_companions(file, item.new_name)
                if state.confidence < get_auto_accept_threshold():
                    item.status = (
                        f"REVIEW: best match \"{chosen.get('title', '')}\" "
                        f"(confidence {state.confidence:.0%}) — click to verify"
                    )
                items.append(item)

            check_duplicates(items)

            scanner = MovieScanner(self.tmdb, state.folder, files=video_files)
            for file in video_files:
                scanner.set_movie_info(file, chosen)
                scanner.set_search_results(file, state.search_results)

            state.scanner = scanner
            state.preview_items = items
            state.scanned = True

            has_actionable = any(item.is_actionable for item in items)
            if not has_actionable:
                state.checked = False
        finally:
            state.scanning = False

        self._apply_duplicate_labels()

    def scan_all(
        self,
        progress_callback: Callable | None = None,
    ) -> None:
        """Phase 2 bulk: Scan all movies that have a TMDB match."""
        to_scan = [
            state for state in self.states
            if not state.scanned and not state.queued and state.show_id is not None
        ]
        total = len(to_scan)

        for index, state in enumerate(to_scan):
            try:
                self.scan_movie(state)
            except Exception as error:
                _log.error("Failed to scan %s: %s", state.display_name, error)
            if progress_callback:
                progress_callback(index + 1, total)

    def rematch_movie(self, state: ScanState, new_match: dict) -> None:
        """Swap a movie's TMDB match and invalidate its scan data."""
        state.media_info = new_match
        raw_source = state.source_file.stem if state.source_file is not None else state.folder.name
        raw_name = clean_folder_name(raw_source)
        year_hint = extract_year(raw_source)
        scored = score_results([new_match], raw_name, year_hint, title_key="title")
        state.confidence = scored[0][1] if scored else 0.0
        state.reset_scan()
        self._apply_duplicate_labels()