"""
Rename engine — media-type-aware scanning, preview building, and execution.

This module contains the core logic that was previously embedded inside the
GUI class.  It operates on plain data structures (dicts, lists, Paths) and
has no tkinter dependency, making it testable and reusable.
"""

from __future__ import annotations

import logging
import re
import threading
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

from ..constants import SCORE_TIE_MARGIN, VIDEO_EXTENSIONS, YEAR_MIN, YEAR_MAX, MediaType
from ..parsing import (
    EXTRAS_FOLDER_PATTERN,
    best_tv_match_title,
    is_extras_folder,
    build_movie_name,
    build_show_folder_name,
    build_tv_name,
    clean_folder_name,
    clean_name,
    extract_episode,
    extract_season_number,
    extract_year,
    get_season,
    find_companion_subtitles,
    is_already_complete,
    is_sample_file,
    looks_like_tv_episode,
    normalize_for_match,
    normalize_for_specials,
)
from ..tmdb import TMDBClient
from ._batch_orchestrators import BatchMovieOrchestrator, BatchTVOrchestrator
from ._movie_scanner import (
    MovieScanner,
    _build_movie_preview_item,
    _build_subtitle_companions,
    _prepare_movie_query,
)
from ._scan_runtime import CANCEL_SCAN, ScanCancelledError, _raise_if_cancelled
from ._state import get_auto_accept_threshold
from .matching import (
    _ALT_TITLE_CANDIDATES,
    _country_from_language,
    boost_scores_with_alt_titles,
    boost_tv_scores_with_episode_evidence,
    pick_alternate_matches,
    score_results,
    score_tv_results,
    title_similarity,
)
from .models import (
    CompanionFile,
    CompletenessReport,
    DirectEpisodeEvidence,
    PreviewItem,
    RenameResult,
    ScanState,
    SeasonCompleteness,
    collect_direct_episode_evidence,
    infer_explicit_season_assignment,
)
from ._rename_execution import check_duplicates


_log = logging.getLogger(__name__)


# ─── Batch TV orchestration ─────────────────────────────────────────────────

class _LegacyBatchTVOrchestrator:
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

    @staticmethod
    def _normalized_relative_folder(relative_folder: str, fallback: Path) -> str:
        text = relative_folder or fallback.as_posix()
        return text.replace("\\", "/").casefold()

    @staticmethod
    def _preview_single_season(state: ScanState) -> int | None:
        """Return the one season covered by ``preview_items``, or ``None``.

        Used as a fallback for states whose folder carries no explicit
        season hint but whose scanned preview unambiguously resolves to a
        single TMDB season.  Multi-season previews are deliberately
        rejected so we never merge a show-root folder into a sibling on
        partial evidence.
        """
        if not state.preview_items:
            return None
        detected = {
            item.season for item in state.preview_items
            if item.season is not None
        }
        if len(detected) != 1:
            return None
        return next(iter(detected))

    @classmethod
    def _represented_seasons(cls, state: ScanState) -> set[int]:
        seasons = set(state.season_folders.keys())
        if state.season_assignment is not None:
            seasons.add(state.season_assignment)
        if not seasons:
            inferred = cls._preview_single_season(state)
            if inferred is not None:
                seasons.add(inferred)
        return seasons

    @classmethod
    def _expanded_season_folders(cls, state: ScanState) -> dict[int, Path]:
        if state.season_folders:
            return dict(state.season_folders)
        if state.season_assignment is not None:
            return {
                state.season_assignment: cls._resolve_season_folder(
                    state.folder,
                    state.season_assignment,
                )
            }
        inferred = cls._preview_single_season(state)
        if inferred is not None:
            return {
                inferred: cls._resolve_season_folder(state.folder, inferred),
            }
        return {}

    @classmethod
    def _season_merge_priority(cls, state: ScanState) -> tuple[int, float, int, str]:
        represented = cls._represented_seasons(state)
        normalized_relative = cls._normalized_relative_folder(
            state.relative_folder,
            state.folder,
        )
        manual_rank = 0 if state.match_origin == "manual" else 1
        return (
            len(represented),
            state.confidence,
            -manual_rank,
            normalized_relative,
        )

    @classmethod
    def _duplicate_priority(cls, state: ScanState) -> tuple[float, int, int, str]:
        normalized_relative = cls._normalized_relative_folder(
            state.relative_folder,
            state.folder,
        )
        depth = len(PurePosixPath(normalized_relative).parts)
        evidence_rank = 0 if state.has_direct_season_subdirs else 1
        return (-state.confidence, depth, evidence_rank, normalized_relative)

    def _apply_duplicate_labels(self) -> None:
        """Mark lower-priority TMDB matches as duplicates deterministically.

        Two states with the same TMDB ID are considered duplicates UNLESS
        both have an explicit (non-None) season_assignment that differs —
        in that case they represent distinct seasons discovered as separate
        folders and should coexist.
        """
        for state in self.states:
            state.duplicate_of = None
            state.duplicate_of_relative_folder = None

        # Group by TMDB ID, then within each group find a primary for each
        # "slot".  A slot is identified by season_assignment when set, but
        # a state with season_assignment=None competes with every slot.
        groups: dict[int, list[ScanState]] = {}
        for state in self.states:
            sid = state.show_id
            if sid is None:
                continue
            groups.setdefault(sid, []).append(state)

        for group in groups.values():
            if len(group) < 2:
                continue
            # Sort by priority so the best candidate is first
            group.sort(key=self._duplicate_priority)
            primaries: dict[int | None, ScanState] = {}
            for state in group:
                sa = state.season_assignment
                if sa is not None:
                    existing = primaries.get(sa)
                    if existing is None:
                        primaries[sa] = state
                        continue
                else:
                    # No season assignment — duplicate of the best primary
                    existing = next(iter(primaries.values()), None) if primaries else None
                    if existing is None:
                        primaries[None] = state
                        continue
                # This state is a duplicate of `existing`
                state.duplicate_of = existing.display_name
                state.duplicate_of_relative_folder = existing.relative_folder or None
                state.checked = False

    @staticmethod
    def _count_season_subdirs(folder: Path) -> int:
        """Count Season NN subdirectories to estimate episode volume."""
        count = 0
        try:
            for child in folder.iterdir():
                if child.is_dir() and get_season(child) is not None:
                    count += 1
        except OSError:
            pass
        return count

    def _episode_count_tiebreak(
        self,
        scored: list[tuple[dict, float]],
        file_count: int,
        threshold: float = 0.10,
        compare_seasons: bool = False,
    ) -> tuple[dict, float]:
        """Re-rank near-tied TMDB candidates by episode/season count proximity.

        For each candidate within *threshold* of the top score, fetch
        TMDB details to get ``number_of_episodes`` (or ``number_of_seasons``
        when *compare_seasons* is True).  The candidate whose count is
        closest to *file_count* wins.  Falls back to the original best
        if details aren't available.
        """
        detail_key = "number_of_seasons" if compare_seasons else "number_of_episodes"
        top_score = scored[0][1]
        contenders: list[tuple[dict, float, int, bool]] = []

        _unaired_statuses = {"Planned", "In Production"}

        for result, score in scored:
            if top_score - score > threshold:
                break
            show_id = result.get("id")
            if show_id is None:
                continue
            details = self.tmdb.get_tv_details(show_id)
            count = (details or {}).get(detail_key) or 0
            # Shows that haven't aired yet are unlikely to be correct
            # matches — deprioritize them so they don't win tiebreaks
            # against shows that have actually aired.
            unaired = (
                not (details or {}).get("first_air_date")
                or (details or {}).get("status") in _unaired_statuses
            )
            contenders.append((result, score, count, unaired))

        if not contenders:
            return scored[0]

        # Pick the contender whose count is closest to file_count.
        # Unaired/planned shows sort last; on ties prefer higher score.
        best = min(
            contenders,
            key=lambda c: (c[3], abs(c[2] - file_count), -c[1]),
        )
        return best[0], best[1]

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

    def discover_shows(
        self,
        progress_callback: Callable | None = None,
        cancel_event: threading.Event | None = None,
    ) -> list[ScanState]:
        """
        Phase 1: Find show folders and match to TMDB.

        Recursively discovers TV show folders below the library root,
        descending through container folders but classifying show roots
        only from direct-child evidence. Uses search_tv_batch for
        parallel TMDB lookups.

        Returns ScanState instances with media_info populated but
        scanner/preview_items empty (Phase 2 hasn't run yet).
        """
        discovery_service = self._get_discovery_service()
        discovered = discovery_service.discover_show_roots(self.root)
        candidates: list[tuple[object, str, str, str, str | None, list[DirectEpisodeEvidence]]] = []
        for candidate in discovered:
            _raise_if_cancelled(cancel_event)
            cleaned = best_tv_match_title(candidate.folder, include_year=False)
            score_name = best_tv_match_title(candidate.folder)
            # Keep the folder-derived name as a fallback for scoring.
            # File-inferred titles are better for TMDB search but may be
            # shorter than the full show name (e.g. "Evangelion" from episode
            # filenames vs "Neon Genesis Evangelion" from the folder).
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

        if not candidates:
            return []

        _log.info("Discovered %d candidate show folders", len(candidates))

        # Parallel TMDB search
        queries = [(name, year) for _, name, _, _, year, _ in candidates]
        all_results = self.tmdb.search_tv_batch(
            queries,
            progress_callback=progress_callback,
        )

        # Build ScanState for each candidate
        states: list[ScanState] = []
        for (candidate, cleaned_name, score_name, folder_score_name, year_hint, episode_evidence), results in zip(candidates, all_results):
            _raise_if_cancelled(cancel_event)
            folder = candidate.folder
            if not results:
                # No TMDB results — create state with folder name as placeholder
                state = ScanState(
                    folder=folder,
                    media_info={
                        "id": None, "name": folder.name,
                        "year": year_hint or "", "poster_path": None,
                        "overview": "",
                    },
                    confidence=0.0,
                    search_results=results,
                    alternate_matches=[],
                    checked=False,      # No match — don't auto-check
                    relative_folder=candidate.relative_folder,
                    parent_relative_folder=candidate.parent_relative_folder,
                    discovery_reason=candidate.discovery_reason,
                    has_direct_season_subdirs=candidate.has_direct_season_subdirs,
                    direct_episode_file_count=candidate.direct_episode_file_count,
                    direct_video_file_count=candidate.direct_video_file_count,
                    discovered_via_symlink=candidate.discovered_via_symlink,
                    season_assignment=infer_explicit_season_assignment(folder, episode_evidence),
                )
                states.append(state)
                continue

            # Score results using the file-inferred title, then also try
            # the folder-derived title and keep whichever scores higher
            # per result.  File-inferred titles are better TMDB search
            # queries but may be abbreviated (e.g. "Evangelion" from
            # episode filenames vs "Neon Genesis Evangelion" from the
            # folder name).
            raw_name = score_name
            scored = score_tv_results(
                results,
                raw_name,
                year_hint,
                self.tmdb,
                folder=folder,
                folder_score_name=folder_score_name,
                episode_evidence=episode_evidence,
            )

            best, best_score = scored[0]

            # Episode count tiebreaker: when top candidates score within 0.10
            # of each other, prefer the show whose total episode count is
            # closest to the number of video files on disk.  This resolves
            # ambiguity for franchises that share a name (e.g. JoJo 1993 OVA
            # vs JoJo 2012 series when the folder has 13 files).
            #
            # When the folder has season subdirs but no direct video files
            # (typical layout: Show/Season 01/eps...), count season subdirs
            # and use that as a proxy — a folder with 4 season dirs is far
            # more likely to be a 75-episode series than a 2-episode miniseries.
            file_count = candidate.direct_video_file_count
            use_seasons = False
            if file_count == 0 and candidate.has_direct_season_subdirs:
                _raise_if_cancelled(cancel_event)
                file_count = self._count_season_subdirs(candidate.folder)
                use_seasons = True
            if file_count > 0 and len(scored) >= 2:
                runner_up, runner_up_score = scored[1]
                if best_score - runner_up_score <= 0.10:
                    best, best_score = self._episode_count_tiebreak(
                        scored, file_count, threshold=0.10,
                        compare_seasons=use_seasons,
                    )

            # Episode count confidence bonus: when the file count
            # (excluding specials) matches the TMDB total, boost
            # confidence.  Specials (S00E##) would throw off the count,
            # so we use direct_episode_file_count which only counts
            # files with identified season/episode patterns.
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

            # Detect tied top matches — if the runner-up is within 0.02
            # of the winner, flag for user review even if above threshold.
            tie_detected = False
            if len(scored) >= 2:
                for r, s in scored:
                    if r.get("id") != best.get("id"):
                        if best_score - s <= SCORE_TIE_MARGIN and best_score >= get_auto_accept_threshold():
                            tie_detected = True
                        break

            # Only auto-check shows with confident matches (and no ties)
            auto_check = best_score >= get_auto_accept_threshold() and not tie_detected

            # Populate season names from TMDB details (may already be cached
            # from tiebreak or episode count bonus).
            season_names: dict[int, str] = {}
            if best.get("id") is not None:
                details = self.tmdb.get_tv_details(best["id"])
                if details:
                    for si in details.get("seasons", []):
                        sn = si.get("season_number")
                        name = si.get("name", "")
                        if sn is not None and sn > 0 and name:
                            generic = f"Season {sn}"
                            if name != generic:
                                season_names[sn] = name

            state = ScanState(
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
            states.append(state)

        # Sort by match quality group, then alphabetically within each group.
        # Groups: 0 = confident match, 1 = needs review, 2 = no match, 3 = duplicate
        def _sort_key(s: ScanState) -> tuple:
            if s.duplicate_of is not None:
                group = 3
            elif s.show_id is None:
                group = 2
            elif s.needs_review:
                group = 1
            else:
                group = 0
            return (
                group,
                s.display_name.lower(),
                self._normalized_relative_folder(s.relative_folder, s.folder),
            )

        states = self._merge_season_siblings(states)
        states.sort(key=_sort_key)

        self.states = states
        self._apply_duplicate_labels()
        self.states.sort(key=_sort_key)
        return states

    def merge_rematched_state(self, state: ScanState) -> ScanState:
        """Merge a rematched season/special state into existing show siblings."""
        show_id = state.show_id
        state_seasons = self._represented_seasons(state)
        if show_id is None or not state_seasons:
            self._apply_duplicate_labels()
            return state

        merge_group: list[ScanState] = [state]
        covered_seasons = set(state_seasons)
        for other in self.states:
            if other is state or other.show_id != show_id:
                continue
            other_seasons = self._represented_seasons(other)
            if not other_seasons or covered_seasons & other_seasons:
                continue
            merge_group.append(other)
            covered_seasons.update(other_seasons)

        if len(merge_group) == 1:
            self._apply_duplicate_labels()
            return state

        target = max(merge_group, key=self._season_merge_priority)
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
            for season_num, folder in self._expanded_season_folders(member).items():
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

    @staticmethod
    def _merge_season_siblings(states: list[ScanState]) -> list[ScanState]:
        """Merge states that share a TMDB ID and have distinct season_assignments.

        When multiple folders match the same show but each represents a
        different season (e.g. "Show S01", "Show S02"), combine them into
        a single ScanState whose ``season_folders`` map tells TVScanner
        where each season lives on disk.
        """
        # Group matched states by TMDB ID
        groups: dict[int, list[ScanState]] = {}
        rest: list[ScanState] = []
        for state in states:
            sid = state.show_id
            if sid is None or state.season_assignment is None:
                rest.append(state)
                continue
            groups.setdefault(sid, []).append(state)

        merged: list[ScanState] = list(rest)
        for sid, group in groups.items():
            if len(group) < 2:
                merged.extend(group)
                continue

            # Check all have distinct season assignments
            assignments = {s.season_assignment for s in group}
            if len(assignments) < len(group):
                # Some share the same season — can't fully merge, keep as-is
                merged.extend(group)
                continue

            # Pick the best state as primary (highest confidence, then name)
            group.sort(key=lambda s: (-s.confidence, s.display_name.lower()))
            primary = group[0]

            # Build season_folders map from all states in the group.
            # If the folder itself has no video files but contains a season
            # subdir matching the same season number, resolve to that subdir
            # (e.g. "Show.S03.release/" containing an "S03/" subfolder).
            season_map: dict[int, Path] = {}
            total_files = primary.direct_video_file_count
            total_ep_files = primary.direct_episode_file_count
            for s in group:
                if s.season_assignment is not None:
                    season_map[s.season_assignment] = _LegacyBatchTVOrchestrator._resolve_season_folder(
                        s.folder, s.season_assignment,
                    )
                if s is not primary:
                    total_files += s.direct_video_file_count
                    total_ep_files += s.direct_episode_file_count
                    # Merge season names
                    for sn, name in s.season_names.items():
                        primary.season_names.setdefault(sn, name)

            primary.season_folders = season_map
            primary.season_assignment = None  # no longer a single-season state
            primary.direct_video_file_count = total_files
            primary.direct_episode_file_count = total_ep_files
            merged.append(primary)

        return merged

    @staticmethod
    def _resolve_season_folder(folder: Path, season_num: int) -> Path:
        """Return the actual directory containing episode files.

        If *folder* has no video files but contains a single subdir whose
        ``get_season()`` matches *season_num*, return that subdir instead.
        This handles release layouts like ``Show.S03.release/S03/E01.mkv``.
        """
        has_video = any(
            f.suffix.lower() in VIDEO_EXTENSIONS
            for f in folder.iterdir() if f.is_file()
        )
        if has_video:
            return folder
        for child in folder.iterdir():
            if child.is_dir() and get_season(child) == season_num:
                return child
        return folder

    def scan_show(
        self,
        state: ScanState,
        progress_callback: Callable | None = None,
        cancel_event: threading.Event | None = None,
    ) -> None:
        """
        Phase 2: Run TVScanner for a single show and populate its ScanState.

        Creates the TVScanner, runs scan(), computes completeness,
        and stores everything in the ScanState.  Skips if already scanned.
        """
        if state.scanned or state.scanning:
            return
        if state.show_id is None:
            _log.warning("Cannot scan %s — no TMDB match", state.folder.name)
            return

        _raise_if_cancelled(cancel_event)

        state.scanning = True
        _log.info("Scanning episodes for: %s", state.display_name)

        try:
            scanner = TVScanner(self.tmdb, state.media_info, state.folder,
                                season_hint=state.season_assignment,
                                season_folders=state.season_folders or None)
            items, has_mismatch = scanner.scan()
            _raise_if_cancelled(cancel_event)

            _log.info("Folder '%s' produced %d items (mismatch=%s), seasons: %s",
                      state.folder.name, len(items), has_mismatch,
                      sorted({it.season for it in items if it.season is not None}))

            # For batch mode, auto-fix mismatches without prompting
            if has_mismatch:
                _log.info("Season mismatch detected for %s, using consolidated scan",
                           state.display_name)
                items = scanner.scan_consolidated()
                _raise_if_cancelled(cancel_event)

            check_duplicates(items)

            # Compute initial completeness (all OK items checked)
            initial_checked = {i for i, it in enumerate(items) if it.status == "OK"}
            completeness = scanner.get_completeness(items, checked_indices=initial_checked)

            # Assign results atomically
            state.scanner = scanner
            state.preview_items = items
            state.completeness = completeness
            state.scanned = True

            # Auto-uncheck shows where every file was skipped —
            # nothing actionable means nothing to rename.
            has_actionable = any(it.is_actionable for it in items)
            if not has_actionable:
                state.checked = False
        finally:
            state.scanning = False

        # Summary log
        by_season: dict[int | None, int] = defaultdict(int)
        for it in items:
            by_season[it.season] += 1
        _log.info("Scan complete for '%s': %d total items, seasons: %s",
                  state.display_name, len(items),
                  dict(sorted(by_season.items())))

    def scan_all(
        self,
        progress_callback: Callable | None = None,
        cancel_event: threading.Event | None = None,
    ) -> None:
        """
        Phase 2 bulk: Scan all shows that have a TMDB match.

        Runs sequentially because each show's scan does multiple TMDB API
        calls (one per season) and the rate limiter handles throughput.
        """
        to_scan = [
            s for s in self.states
            if not s.scanned and s.show_id is not None
        ]
        total = len(to_scan)

        for i, state in enumerate(to_scan):
            _raise_if_cancelled(cancel_event)
            try:
                self.scan_show(state, cancel_event=cancel_event)
            except Exception as e:
                if isinstance(e, ScanCancelledError):
                    raise
                _log.error("Failed to scan %s: %s", state.display_name, e)
            if progress_callback:
                progress_callback(i + 1, total)

    def reconcile_scanned_state(self, state: ScanState) -> ScanState:
        """Try to merge a freshly-scanned state into a same-show sibling.

        Used after a show-root rematch when ``season_assignment`` was empty
        at rematch time: TVScanner has now resolved episodes against the new
        TMDB show, so the folder's real season(s) are visible in
        ``preview_items``.  If those seasons don't overlap with a sibling
        holding the same ``show_id``, fold this folder into that sibling's
        ``season_folders`` map so the user sees a single consolidated card
        instead of a duplicate stub that still needs a manual assign-season.
        Only acts when we can unambiguously attribute the folder to one
        season — multi-season show-roots stay as-is.
        """
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
            season_num: self._resolve_season_folder(state.folder, season_num),
        }
        return self.merge_rematched_state(state)

    def rematch_show(self, state: ScanState, new_match: dict) -> ScanState:
        """Swap a show's TMDB match and invalidate its scan data."""
        state.media_info = new_match
        # Rescore confidence against the original search results
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
        """
        Heuristic check: does this folder look like a TV library root
        (contains show subdirectories) rather than a single show folder?

        Returns True if at least 2 child directories look like show
        folders — meaning they themselves contain season subdirectories
        or multiple video files (or TV-patterned filenames), AND they
        don't look like season folders themselves.

        Single-file folders without TV episode patterns are treated as
        movie folders and don't count toward the threshold.
        """
        show_like_children = 0
        try:
            for d in folder.iterdir():
                if not d.is_dir() or d.name.startswith("."):
                    continue
                # Skip if this child IS a season folder — season folders
                # are part of a single show, not separate shows.
                if get_season(d) is not None:
                    continue
                # Skip known non-show directories
                if d.name.lower() in (
                    "extras", "featurettes", "@eadir", "#recycle",
                    ".debris", "lost+found",
                ):
                    continue
                # Check if this child looks like a show folder
                has_season_subdir = False
                video_files: list[Path] = []
                for child in d.iterdir():
                    if child.is_dir() and get_season(child) is not None:
                        has_season_subdir = True
                        break
                    if child.is_file() and child.suffix.lower() in VIDEO_EXTENSIONS:
                        video_files.append(child)

                if has_season_subdir:
                    # Has season subdirs — definitely a TV show folder
                    show_like_children += 1
                elif len(video_files) > 2:
                    # Many video files without season dirs — likely a TV show
                    show_like_children += 1
                elif video_files and any(
                    looks_like_tv_episode(f) for f in video_files
                ):
                    # Few files but at least one has TV episode patterns
                    show_like_children += 1
                # else: 1-2 video files with no TV patterns → likely a movie, skip

                if show_like_children >= 2:
                    return True
        except OSError:
            pass
        return False


# ─── Batch movie orchestration ───────────────────────────────────────────────

class _LegacyBatchMovieOrchestrator:
    """
    Discovers movie folders in a library root, matches each to TMDB,
    and creates ScanState instances for the GUI.

    Two-phase workflow:
      Phase 1 (discover): Scan filesystem via MovieLibraryDiscoveryService,
          identify movie_root and multi_movie_folder candidates, parallel
          TMDB search.
      Phase 2 (scan): For each matched movie, build PreviewItems with
          rename plans.  Can be triggered per-movie or in bulk.
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
        # "Title (Year)" folder name match beats loose files in a multi-movie folder
        evidence_rank = 0 if state.discovery_reason == "title_year_folder" else 1
        return (ready_rank, -state.confidence, depth, evidence_rank, normalized_relative)

    def _apply_duplicate_labels(self) -> None:
        """Mark lower-priority TMDB matches as duplicates deterministically.

        Same season-aware logic as BatchTVOrchestrator: two states with
        the same TMDB ID are duplicates unless both have explicit, distinct
        season_assignment values.
        """
        for state in self.states:
            state.duplicate_of = None
            state.duplicate_of_relative_folder = None

        groups: dict[int, list[ScanState]] = {}
        for state in self.states:
            mid = state.show_id
            if mid is None:
                continue
            groups.setdefault(mid, []).append(state)

        for group in groups.values():
            if len(group) < 2:
                continue
            group.sort(key=self._duplicate_priority)
            primaries: dict[int | None, ScanState] = {}
            for state in group:
                sa = state.season_assignment
                if sa is not None:
                    existing = primaries.get(sa)
                    if existing is None:
                        primaries[sa] = state
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
        """
        Phase 1: Find movie folders and match to TMDB.

        Recursively discovers movie folders below the library root using
        the MovieLibraryDiscoveryService.  For movie_root candidates the
        folder name is used for TMDB search; for multi_movie_folder
        candidates each video file gets its own search query.

        Returns ScanState instances with media_info populated but
        preview_items empty (Phase 2 hasn't run yet).
        """
        from ..app.models import MovieDirectoryRole

        discovery_service = self._get_discovery_service()
        discovered = discovery_service.discover_movie_roots(self.root)

        # Build (candidate, search_query, year_hint, source_file_or_None) tuples.
        # movie_root  → one entry per folder  (source_file=None)
        # multi_movie → one entry per video file inside the folder
        entries: list[tuple[object, str, str | None, Path | None]] = []
        for candidate in discovered:
            if candidate.discovery_reason == "multiple_direct_video_files":
                # multi_movie_folder — enumerate individual video files
                video_files = sorted(
                    f for f in candidate.folder.iterdir()
                    if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
                    and not looks_like_tv_episode(f) and not is_sample_file(f)
                )
                for vf in video_files:
                    query, year, _raw = _prepare_movie_query(vf.stem)
                    entries.append((candidate, query, year, vf))
            else:
                # movie_root — use folder name
                cleaned = clean_folder_name(candidate.folder.name, include_year=False)
                year_hint = extract_year(candidate.folder.name)
                entries.append((candidate, cleaned, year_hint, None))

        if not entries:
            return []

        _log.info("Discovered %d movie candidate entries", len(entries))

        # Parallel TMDB search
        queries = [(name, year) for _, name, year, _ in entries]
        all_results = self.tmdb.search_movies_batch(
            queries,
            progress_callback=progress_callback,
        )

        # Build ScanState for each entry
        states: list[ScanState] = []
        for (candidate, search_query, year_hint, source_file), results in zip(
            entries, all_results,
        ):
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

            # Score results — use folder name for movie_root, filename for multi
            if source_file:
                raw_name = clean_folder_name(source_file.stem)
            else:
                raw_name = clean_folder_name(folder.name)
            scored = score_results(results, raw_name, year_hint, title_key="title")
            scored = boost_scores_with_alt_titles(
                scored, raw_name, year_hint, self.tmdb,
                title_key="title", media_type="movie",
                preferred_country=_country_from_language(self.tmdb.language),
            )

            best, best_score = scored[0]
            alternates = [r for r, s in scored[1:4] if s > 0.3]

            # Detect tied top matches
            tie_detected = False
            if len(scored) >= 2:
                for r, s in scored:
                    if r.get("id") != best.get("id"):
                        if best_score - s <= SCORE_TIE_MARGIN and best_score >= get_auto_accept_threshold():
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

        # Sort by match quality group, then alphabetically
        def _sort_key(s: ScanState) -> tuple:
            if s.duplicate_of is not None:
                group = 3
            elif s.show_id is None:
                group = 2
            elif s.needs_review:
                group = 1
            else:
                group = 0
            return (
                group,
                s.display_name.lower(),
                self._normalized_relative_folder(s.relative_folder, s.folder),
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
        """
        Phase 2: Build preview items for a single movie ScanState.

        Creates a MovieScanner, finds video files, and builds rename
        previews.  Skips if already scanned.
        """
        if state.scanned or state.scanning:
            return
        if state.show_id is None:
            _log.warning("Cannot scan %s — no TMDB match", state.folder.name)
            return

        state.scanning = True
        _log.info("Scanning movie: %s", state.display_name)

        try:
            chosen = state.media_info
            if state.source_file is not None:
                video_files = [state.source_file] if state.source_file.exists() else []
            else:
                video_files = sorted(
                    f for f in state.folder.iterdir()
                    if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
                    and not is_sample_file(f) and not looks_like_tv_episode(f)
                )

            items: list[PreviewItem] = []
            for f in video_files:
                item = _build_movie_preview_item(f, chosen, self.root)
                item.companions = _build_subtitle_companions(f, item.new_name)
                if state.confidence < get_auto_accept_threshold():
                    item.status = (
                        f"REVIEW: best match \"{chosen.get('title', '')}\" "
                        f"(confidence {state.confidence:.0%}) — click to verify"
                    )
                items.append(item)

            check_duplicates(items)

            scanner = MovieScanner(self.tmdb, state.folder, files=video_files)
            for f in video_files:
                scanner.set_movie_info(f, chosen)
                scanner.set_search_results(f, state.search_results)

            state.scanner = scanner
            state.preview_items = items
            state.scanned = True

            has_actionable = any(it.is_actionable for it in items)
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
            s for s in self.states
            if not s.scanned and not s.queued and s.show_id is not None
        ]
        total = len(to_scan)

        for i, state in enumerate(to_scan):
            try:
                self.scan_movie(state)
            except Exception as e:
                _log.error("Failed to scan %s: %s", state.display_name, e)
            if progress_callback:
                progress_callback(i + 1, total)

    def rematch_movie(self, state: ScanState, new_match: dict) -> None:
        """Swap a movie's TMDB match and invalidate its scan data."""
        state.media_info = new_match
        raw_source = state.source_file.stem if state.source_file is not None else state.folder.name
        raw_name = clean_folder_name(raw_source)
        year_hint = extract_year(raw_source)
        scored = score_results(
            [new_match], raw_name, year_hint, title_key="title")
        state.confidence = scored[0][1] if scored else 0.0
        state.reset_scan()
        self._apply_duplicate_labels()


# ─── TV scanning ─────────────────────────────────────────────────────────────

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

    def __init__(self, tmdb: TMDBClient, show_info: dict, root_folder: Path,
                 *, season_hint: int | None = None,
                 season_folders: dict[int, Path] | None = None):
        self.tmdb = tmdb
        self.show_info = show_info
        self.root = root_folder
        self._season_hint = season_hint  # from ScanState.season_assignment
        self._season_folders = season_folders  # explicit season->folder map from merged siblings
        # Populated during scan — used by the GUI for detail panel
        self.episode_titles: dict[tuple[int, int], str] = {}
        self.episode_posters: dict[tuple[int, int], str | None] = {}
        self.episode_meta: dict[tuple[int, int], dict] = {}  # Rich metadata per episode
        # Cached scan data — computed once, reused across methods
        self._season_dirs: list[tuple[Path, int]] | None = None
        self._tmdb_seasons: dict | None = None

    def _get_season_dirs(self) -> list[tuple[Path, int]]:
        """Find and sort season subdirectories. Cached after first call.

        When ``_season_folders`` is provided (merged sibling folders), those
        are used directly — each entry maps a season number to an external
        folder path.  Otherwise, the standard discovery logic runs:

        First pass uses ``get_season()`` for standard patterns (Season 01,
        S02, ordinals).  Second pass matches remaining subdirectories against
        TMDB season names so that named anime seasons (e.g. "Karasuno High
        School vs. Shiratorizawa Academy") are correctly identified.
        """
        if self._season_dirs is not None:
            return self._season_dirs

        # Explicit season folder map from merged sibling discoveries
        if self._season_folders:
            self._season_dirs = sorted(
                [(folder, sn) for sn, folder in self._season_folders.items()],
                key=lambda x: x[1],
            )
            return self._season_dirs

        # Compute season number once per directory, filter and sort
        dirs_with_season: list[tuple[Path, int]] = []
        unmatched_dirs: list[Path] = []
        for d in self.root.iterdir():
            if not d.is_dir():
                continue
            sn = get_season(d)
            if sn is not None:
                dirs_with_season.append((d, sn))
            else:
                unmatched_dirs.append(d)

        # Second pass: match unrecognized subdirs against TMDB season names.
        # Only attempt this when we already found at least one season dir
        # (signals this really is a multi-season show root) and there are
        # leftover dirs that might be named seasons.
        if dirs_with_season and unmatched_dirs:
            matched_via_tmdb = self._match_dirs_to_tmdb_seasons(
                unmatched_dirs,
                {sn for _, sn in dirs_with_season},
            )
            dirs_with_season.extend(matched_via_tmdb)

        dirs_with_season.sort(key=lambda x: x[1])

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
        """Try to match directories against TMDB season names.

        For shows like Haikyu!! where seasons have distinct names
        (e.g. "Karasuno High School vs. Shiratorizawa Academy" = Season 3),
        this allows folders named after the season to be correctly identified.
        """
        show_id = self.show_info.get("id")
        if not show_id:
            return []

        show_data = self.tmdb.get_tv_details(show_id)
        if not show_data:
            return []

        # Build a map of season_number → cleaned season name
        tmdb_season_names: dict[int, str] = {}
        for season_info in show_data.get("seasons", []):
            sn = season_info.get("season_number", 0)
            name = season_info.get("name", "")
            if sn > 0 and name and sn not in already_matched:
                tmdb_season_names[sn] = name

        if not tmdb_season_names:
            return []

        # Show title prefix to strip from folder names for comparison
        show_title = clean_folder_name(
            self.show_info.get("name", ""), include_year=False,
        ).lower()

        results: list[tuple[Path, int]] = []
        used_seasons: set[int] = set()

        for d in dirs:
            folder_cleaned = clean_folder_name(
                d.name, include_year=False,
            ).lower()

            best_sn: int | None = None
            best_score = 0.0

            for sn, tmdb_name in tmdb_season_names.items():
                if sn in used_seasons:
                    continue
                tmdb_cleaned = tmdb_name.lower()

                # Strategy 1: folder name contains the TMDB season name
                # or the TMDB season name contains the folder's cleaned text
                if tmdb_cleaned in folder_cleaned or folder_cleaned in tmdb_cleaned:
                    score = 1.0
                else:
                    # Strategy 2: strip the common show title prefix and
                    # compare the remaining subtitle text
                    folder_suffix = folder_cleaned
                    tmdb_suffix = tmdb_cleaned
                    if folder_suffix.startswith(show_title):
                        folder_suffix = folder_suffix[len(show_title):].strip()
                    if tmdb_suffix.startswith(show_title):
                        tmdb_suffix = tmdb_suffix[len(show_title):].strip()

                    if not folder_suffix or not tmdb_suffix:
                        continue

                    # Check for substantial overlap
                    if tmdb_suffix in folder_suffix or folder_suffix in tmdb_suffix:
                        score = 0.9
                    else:
                        # Token overlap — count shared meaningful words
                        folder_tokens = set(folder_suffix.split())
                        tmdb_tokens = set(tmdb_suffix.split())
                        # Remove very short words (articles, noise)
                        folder_tokens = {t for t in folder_tokens if len(t) > 2}
                        tmdb_tokens = {t for t in tmdb_tokens if len(t) > 2}
                        if not tmdb_tokens:
                            continue
                        overlap = len(folder_tokens & tmdb_tokens)
                        score = overlap / max(len(tmdb_tokens), 1)

                if score > best_score and score >= 0.5:
                    best_score = score
                    best_sn = sn

            if best_sn is not None:
                _log.info(
                    "Matched folder '%s' to TMDB season %d via name similarity "
                    "(score=%.2f)",
                    d.name, best_sn, best_score,
                )
                results.append((d, best_sn))
                used_seasons.add(best_sn)

        return results

    def _get_tmdb_seasons(self) -> dict:
        """Fetch TMDB season map. Cached after first call (also cached in TMDBClient)."""
        if self._tmdb_seasons is not None:
            return self._tmdb_seasons
        raw_tmdb_seasons, _ = self.tmdb.get_season_map(self.show_info["id"])
        self._tmdb_seasons = {
            int(season_num): season_data
            for season_num, season_data in raw_tmdb_seasons.items()
        }
        return self._tmdb_seasons

    def invalidate_cache(self) -> None:
        """Force re-scan on next call (e.g. after renames)."""
        self._season_dirs = None
        self._tmdb_seasons = None

    @property
    def _media_fields(self) -> dict:
        """Common fields for PreviewItem construction — media_id and media_name."""
        return {
            "media_id": self.show_info["id"],
            "media_name": self.show_info["name"],
        }

    def scan(self) -> tuple[list[PreviewItem], bool]:
        """
        Scan the folder and build preview items.

        Returns:
            (items, has_mismatch) — the preview list and whether a
            season structure mismatch was detected.
        """
        season_dirs = self._get_season_dirs()
        tmdb_seasons = self._get_tmdb_seasons()

        # Flat folder (no season subdirs) mapped to a multi-season TMDB show:
        # use consolidated/absolute preview to distribute files across seasons
        # instead of cramming everything into Season 01.
        # Exception: when a season_hint is set the folder represents a single
        # known season (e.g. "Show S02"), so skip the consolidated path and
        # match files against that one season only.
        is_flat_folder = (
            len(season_dirs) == 1
            and season_dirs[0][0] == self.root
        )
        non_special_tmdb_seasons = {
            sn for sn in tmdb_seasons if sn != 0
        }
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
                sn: tmdb_seasons[sn]["count"]
                for sn in sorted(tmdb_nums)
                if sn in tmdb_seasons
            },
            "extra_user_seasons": extra,
        }

    # ─── Internal ─────────────────────────────────────────────────────

    def _detect_mismatch(
        self,
        season_dirs: list[tuple[Path, int]],
        tmdb_seasons: dict,
    ) -> tuple[bool, set[int], set[int]]:
        user_nums = {sn for _, sn in season_dirs}
        tmdb_nums = set(tmdb_seasons.keys())
        extra = (user_nums - tmdb_nums) - {0}
        return bool(extra), user_nums, tmdb_nums

    def _store_tmdb_data(self, season_num: int, titles: dict, posters: dict,
                         episodes: dict | None = None):
        """Cache TMDB data for the detail panel."""
        self.episode_titles.update({(season_num, k): v for k, v in titles.items()})
        self.episode_posters.update({(season_num, k): v for k, v in posters.items()})
        if episodes:
            self.episode_meta.update({(season_num, k): v for k, v in episodes.items()})

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
                    normalize_for_specials(title): (ep_num, title)
                    for ep_num, title in s0_titles.items()
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

            # Fuzzy title lookup for Season 0
            tmdb_title_lookup = {}
            if season_num == 0 and titles:
                for ep_num, title in titles.items():
                    normalized = normalize_for_specials(title)
                    tmdb_title_lookup[normalized] = (ep_num, title)
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

            # Detect if this is an extras/featurettes folder (vs actual Season 00)
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
                # Process video files
                if entry.is_file() and entry.suffix.lower() in VIDEO_EXTENSIONS:
                    f = entry
                    eps, raw_title, is_season_relative = extract_episode(f.name)
                    file_season = (
                        extract_season_number(f.name) if is_season_relative else None
                    )

                    # Filename explicitly tags this as a special (S00E##) even
                    # though it lives in a main-season folder — route through
                    # specials matching so it doesn't consume a regular
                    # episode slot or inflate the folder's match count.
                    if file_season == 0 and season_num != 0:
                        ensure_specials_data()
                        item = self._match_special(
                            f, eps, raw_title, s0_titles, s0_tmdb_title_lookup,
                            specials_target, from_extras_folder=False,
                        )
                        items.append(item)
                        continue

                    # Season 0 special handling
                    if season_num == 0:
                        item = self._match_special(
                            f, eps, raw_title, titles, tmdb_title_lookup,
                            specials_target, extras_folder,
                        )
                        items.append(item)
                        continue

                    # Normal season handling
                    if not eps:
                        items.append(PreviewItem(
                            original=f, new_name=None, target_dir=None,
                            season=season_num, episodes=[],
                            status="SKIP: could not parse episode number",
                            **self._media_fields,
                        ))
                        continue

                    # Validate episode numbers against TMDB season data.
                    # If the highest extracted ep number far exceeds the known
                    # episode count for this season, it's likely a mis-parse
                    # (e.g. codec tag x264 → episode 264).
                    max_ep = max(eps)
                    season_ep_count = len(titles)
                    if (season_ep_count > 0
                            and max_ep > season_ep_count * 1.5
                            and max_ep > season_ep_count + 10
                            and not is_season_relative):
                        items.append(PreviewItem(
                            original=f, new_name=None, target_dir=None,
                            season=season_num, episodes=eps,
                            status=(
                                f"REVIEW: parsed episode {max_ep} but "
                                f"season only has {season_ep_count} episodes "
                                f"— likely a mis-parsed filename"
                            ),
                            **self._media_fields,
                        ))
                        continue

                    ep_titles = [
                        titles.get(ep, raw_title or f"Episode {ep}")
                        for ep in eps
                    ]

                    target_dir = season_dir
                    if (season_dir == self.root
                            or get_season(season_dir) is None
                            or self._season_folders):
                        # Flat show root, named-season folder, or merged
                        # sibling folder — target the canonical Season NN
                        # directory so files are moved there.
                        target_dir = self.root / f"Season {season_num:02d}"

                    new_name = build_tv_name(
                        self.show_info["name"], self.show_info["year"],
                        season_num, eps, ep_titles, f.suffix,
                    )

                    item = PreviewItem(
                        original=f, new_name=new_name, target_dir=target_dir,
                        season=season_num, episodes=eps, status="OK",
                        episode_confidence=1.0 if is_season_relative else 0.5,
                        **self._media_fields,
                    )
                    item.companions = _build_subtitle_companions(f, new_name)
                    items.append(item)

                # Scan nested extras folders (e.g. Season 02/Featurettes/)
                elif (entry.is_dir()
                      and season_num != 0  # don't recurse inside Season 00 itself
                      and is_extras_folder(entry.name)):
                    ensure_specials_data()
                    items.extend(self._scan_nested_extras(
                        entry, s0_titles, s0_tmdb_title_lookup, specials_target,
                    ))

        self._resolve_duplicate_episodes(items)
        return items

    def _resolve_duplicate_episodes(self, items: list[PreviewItem]) -> None:
        """Skip files that duplicate an episode already claimed by a better match.

        When two files in the same season both parse to the same episode
        number, the file whose cleaned stem is most similar to the show
        title keeps priority.  The other file is marked as SKIP.

        This handles bundled movies (e.g. "End of Evangelion - 25'")
        alongside regular episodes ("Evangelion - 25") in the same folder.
        """
        show_title = clean_folder_name(
            self.show_info.get("name", ""), include_year=False,
        ).casefold()

        # Group OK items by (season, episode) to find duplicates.
        from collections import defaultdict
        ep_map: dict[tuple[int, int], list[int]] = defaultdict(list)
        for idx, item in enumerate(items):
            if item.status != "OK" or not item.episodes:
                continue
            for ep in item.episodes:
                ep_map[(item.season, ep)].append(idx)

        for key, indices in ep_map.items():
            if len(indices) < 2:
                continue
            # Score each candidate by title similarity to the show name
            scored: list[tuple[int, float]] = []
            for idx in indices:
                item = items[idx]
                stem = clean_name(item.original.stem).casefold()
                # Simple overlap: does the stem start with the show title?
                if stem.startswith(show_title):
                    score = len(show_title) / max(len(stem), 1)
                elif show_title in stem:
                    score = len(show_title) / max(len(stem), 1) * 0.5
                else:
                    score = 0.0
                scored.append((idx, score))

            # The item with the highest score wins; ties prefer shorter stems
            # (simpler filenames are more likely to be the actual episode)
            scored.sort(key=lambda x: (-x[1], len(clean_name(items[x[0]].original.stem)), x[0]))
            # Skip all but the winner
            for loser_idx, _ in scored[1:]:
                loser = items[loser_idx]
                loser.status = (
                    f"SKIP: duplicate episode {key[1]} — filename does not "
                    f"match show title"
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
        """
        Scan a nested extras folder (e.g. Season 02/Featurettes/) and
        match its files against TMDB Season 0 specials.

        Unmatched files go to Unmatched/<extras_folder_name>/.
        """
        items: list[PreviewItem] = []
        for f in sorted(extras_dir.iterdir()):
            if not f.is_file() or f.suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            eps, raw_title, _ = extract_episode(f.name)
            item = self._match_special(
                f, eps, raw_title, s0_titles, s0_tmdb_title_lookup,
                specials_target, from_extras_folder=True,
            )
            items.append(item)
        return items

    def _match_special(
        self,
        f: Path,
        eps: list[int],
        raw_title: str | None,
        titles: dict,
        tmdb_title_lookup: dict,
        specials_target: Path,
        from_extras_folder: bool = False,
    ) -> PreviewItem:
        """
        Try to match a specials/extras file to a TMDB Season 0 episode.

        Matching priority:
          1. Episode number from S##E## pattern (season-relative only)
          2. Fuzzy title match using raw_title from extract_episode
          3. Fuzzy title match using the full cleaned filename stem
             (handles files like "Gag Reel.mkv" or "Making of the Pilot.mkv"
             where extract_episode returns no title)

        Unmatched files from extras folders (Featurettes, Extras, etc.)
        are routed to Unmatched/<original_folder_name>/ instead of Season 00.
        """
        matched_ep = None
        matched_title = None

        # In an actual Season 00 / Specials folder, a parsed episode number is
        # strong enough evidence to bind directly to TMDB season 0. Extras
        # folders stay on the title-based path because numbers there are often
        # incidental labels rather than episode identifiers.
        if not from_extras_folder and eps:
            for ep_num in eps:
                if ep_num in titles:
                    matched_ep = ep_num
                    matched_title = titles[ep_num]
                    break

        # Try fuzzy title match using raw_title from extract_episode
        if not matched_ep and raw_title:
            matched_ep, matched_title = self._fuzzy_match_special(
                raw_title, tmdb_title_lookup)

        # Try fuzzy title match using the full cleaned filename stem
        # This catches files where extract_episode returns no title
        # (e.g. "Gag Reel.mkv", "Making of the Pilot.mkv")
        if not matched_ep:
            stem = f.stem
            # Strip common prefixes like "Season 3 - " that aren't part of the title
            cleaned_stem = re.sub(
                r"^(?:Season|S)\s*\d+\s*[-._]\s*", "", stem, flags=re.IGNORECASE,
            ).strip()
            if cleaned_stem:
                matched_ep, matched_title = self._fuzzy_match_special(
                    cleaned_stem, tmdb_title_lookup)

        if matched_ep is not None:
            new_name = build_tv_name(
                self.show_info["name"], self.show_info["year"],
                0, [matched_ep], [matched_title], f.suffix,
            )
            return PreviewItem(
                original=f, new_name=new_name, target_dir=specials_target,
                season=0, episodes=[matched_ep], status="OK",
                **self._media_fields,
            )

        # No match — route depends on folder type
        if from_extras_folder:
            unmatched_target = (
                self.root / "Unmatched" / f.parent.name
            )
            return PreviewItem(
                original=f, new_name=f.name, target_dir=unmatched_target,
                season=0, episodes=eps,
                status="UNMATCHED: no TMDB special found — moving to Unmatched",
                **self._media_fields,
            )
        else:
            # Actual Season 00/Specials folder — keep in Season 00
            return PreviewItem(
                original=f, new_name=f.name, target_dir=specials_target,
                season=0, episodes=eps, status="OK",
                **self._media_fields,
            )

    @staticmethod
    def _fuzzy_match_special(
        text: str,
        tmdb_title_lookup: dict,
    ) -> tuple[int | None, str | None]:
        """
        Try to fuzzy-match a text string against TMDB Season 0 titles.

        Returns (episode_number, title) or (None, None).
        """
        normalized = normalize_for_specials(text)
        if not normalized:
            return None, None

        # Exact normalized match
        if normalized in tmdb_title_lookup:
            ep_num, title = tmdb_title_lookup[normalized]
            return ep_num, title

        # Substring match (either direction)
        for norm_key, (ep_n, orig_t) in tmdb_title_lookup.items():
            if norm_key and (normalized in norm_key or norm_key in normalized):
                return ep_n, orig_t

        return None, None

    def _build_consolidated_preview(
        self,
        season_dirs: list[tuple[Path, int]],
        tmdb_seasons: dict,
    ) -> list[PreviewItem]:
        """Build preview mapping files in absolute order to TMDB structure."""
        all_files = self._collect_absolute_files(season_dirs)

        # Flat TMDB episode list in order.
        # Exclude Season 0 specials here: consolidated absolute mapping is for
        # distributing regular episodic files across the main seasons. If
        # specials are included, absolute episode 001 gets consumed by S00E01
        # and every later episode shifts by one.
        tmdb_list: list[tuple[int, int, str]] = []
        for sn in sorted(tmdb_seasons.keys()):
            if sn == 0:
                continue
            sd = tmdb_seasons[sn]
            for ep_num in sorted(sd["titles"].keys()):
                tmdb_list.append((sn, ep_num, sd["titles"][ep_num]))

        # Cache TMDB data
        for sn, sdata in tmdb_seasons.items():
            self._store_tmdb_data(sn, sdata["titles"], sdata["posters"],
                                  sdata.get("episodes", {}))

        # Try title-based matching first — handles cases where file numbering
        # doesn't match TMDB season order (e.g. JoJo 1993 OVA where files
        # 01-07 are Season 2 and 08-13 are Season 1).
        title_matches = self._try_title_based_matching(all_files, tmdb_seasons)
        if title_matches is not None:
            items: list[PreviewItem] = []
            for i, (f, abs_num, raw_title, eps, is_sr, season_hint) in enumerate(all_files):
                match = title_matches[i]
                if match is None:
                    items.append(PreviewItem(
                        original=f, new_name=None, target_dir=None,
                        season=0, episodes=eps,
                        status="SKIP: could not match episode title to TMDB",
                        **self._media_fields,
                    ))
                    continue
                sn, ep_num, title = match
                target_dir = self.root / f"Season {sn:02d}"
                new_name = build_tv_name(
                    self.show_info["name"], self.show_info["year"],
                    sn, [ep_num], [title], f.suffix,
                )
                items.append(PreviewItem(
                    original=f, new_name=new_name, target_dir=target_dir,
                    season=sn, episodes=[ep_num], status="OK",
                    episode_confidence=0.7,
                    **self._media_fields,
                ))
            self._resolve_duplicate_episodes(items)
            return items

        # Sequential fallback — distribute files across TMDB seasons in order
        items: list[PreviewItem] = []
        tmdb_idx = 0

        for f, abs_num, raw_title, eps, is_sr, season_hint in all_files:
            num_eps = max(1, len(eps))

            if tmdb_idx >= len(tmdb_list):
                items.append(PreviewItem(
                    original=f, new_name=None, target_dir=None,
                    season=0, episodes=eps,
                    status="SKIP: no matching TMDB episode (extra file?)",
                    **self._media_fields,
                ))
                continue

            file_eps = []
            file_titles = []
            target_season = tmdb_list[tmdb_idx][0]
            for j in range(num_eps):
                if tmdb_idx + j < len(tmdb_list):
                    sn, ep, title = tmdb_list[tmdb_idx + j]
                    file_eps.append(ep)
                    file_titles.append(title)
                    target_season = sn
            tmdb_idx += num_eps

            target_dir = self.root / f"Season {target_season:02d}"
            new_name = build_tv_name(
                self.show_info["name"], self.show_info["year"],
                target_season, file_eps, file_titles, f.suffix,
            )

            items.append(PreviewItem(
                original=f, new_name=new_name, target_dir=target_dir,
                season=target_season, episodes=file_eps, status="OK",
                episode_confidence=0.5 if is_sr else 0.3,
                **self._media_fields,
            ))

        self._resolve_duplicate_episodes(items)
        return items

    def _try_title_based_matching(
        self,
        all_files: list[tuple[Path, int, str | None, list[int], bool, int | None]],
        tmdb_seasons: dict,
    ) -> list[tuple[int, int, str] | None] | None:
        """Try to match files to TMDB episodes by title or absolute number.

        Builds a cross-season lookup of all TMDB episode titles and an
        episode-number lookup, then attempts to match each file using:

        1. Absolute episode number embedded in the raw title (e.g.
           ``"001 - The Day I Became a Shinigami"`` → episode 1).
        2. Exact normalized title match.
        3. Substring title match (with minimum length guard).

        Returns a list of (season, episode_number, title) tuples parallel
        to *all_files*, or ``None`` if fewer than half the files matched
        (triggering the sequential fallback).
        """
        # Build cross-season title lookup: normalized → (season, ep, title)
        title_lookup: dict[str, tuple[int, int, str]] = {}
        # Build episode-number lookup: absolute_num → (season, ep, title)
        # Only safe when exactly one TMDB season has enough episodes to
        # contain all files — the embedded number is then unambiguously
        # absolute.  E.g. Bleach has 366 files and TMDB S01 has 366 eps,
        # while S02 (TYBW) has only 40 — so numbers map to S01 only.
        # With multiple qualifying seasons a leading "05" could mean
        # S01E05 or S02E05 — too risky.
        file_count = len(all_files)
        qualifying_seasons = [
            sn for sn, sdata in tmdb_seasons.items()
            if sn != 0 and sdata["count"] >= file_count
        ]
        number_lookup: dict[int, tuple[int, int, str]] = {}
        for sn in sorted(tmdb_seasons.keys()):
            if sn == 0:
                continue
            for ep_num, title in tmdb_seasons[sn]["titles"].items():
                norm = normalize_for_specials(title)
                if norm and norm not in title_lookup:
                    title_lookup[norm] = (sn, ep_num, title)
                if (
                    len(qualifying_seasons) == 1
                    and sn == qualifying_seasons[0]
                    and ep_num not in number_lookup
                ):
                    number_lookup[ep_num] = (sn, ep_num, title)

        if not title_lookup:
            return None

        matches: list[tuple[int, int, str] | None] = []
        used: set[tuple[int, int]] = set()

        for f, abs_num, raw_title, eps, is_sr, season_hint in all_files:
            if is_sr and season_hint is not None and eps:
                season_data = tmdb_seasons.get(season_hint)
                if season_data:
                    episode_num = eps[0]
                    title = season_data["titles"].get(episode_num)
                    if title and (season_hint, episode_num) not in used:
                        match = (season_hint, episode_num, title)
                        used.add((match[0], match[1]))
                        matches.append(match)
                        continue

            match = self._match_file_title_to_tmdb(
                raw_title, title_lookup, number_lookup, used,
            )
            if match is not None:
                used.add((match[0], match[1]))
            matches.append(match)

        matched_count = sum(1 for m in matches if m is not None)
        if matched_count < len(all_files) * 0.5:
            return None

        return matches

    # Leading absolute number in a raw title: "001 - Title..."
    _RE_LEADING_ABS_NUM = re.compile(r"^(\d{1,4})\s*[-–]\s*")

    @classmethod
    def _match_file_title_to_tmdb(
        cls,
        raw_title: str | None,
        title_lookup: dict[str, tuple[int, int, str]],
        number_lookup: dict[int, tuple[int, int, str]],
        used: set[tuple[int, int]],
    ) -> tuple[int, int, str] | None:
        """Match a file's title against the cross-season TMDB title lookup.

        Tries in order:
        1. Absolute episode number (leading digits in raw_title).
        2. Exact normalized title match (with leading number stripped).
        3. Substring title match (with minimum length guard).

        Skips episodes already claimed by an earlier file.
        """
        if not raw_title:
            return None

        # Try absolute number match first (e.g. "001 - Title...")
        cleaned_title = raw_title
        abs_match = cls._RE_LEADING_ABS_NUM.match(raw_title)
        if abs_match:
            abs_ep = int(abs_match.group(1))
            cleaned_title = raw_title[abs_match.end():]
            if abs_ep in number_lookup:
                result = number_lookup[abs_ep]
                if (result[0], result[1]) not in used:
                    return result

        norm = normalize_for_specials(cleaned_title)
        if not norm:
            return None

        # Exact normalized match
        if norm in title_lookup:
            result = title_lookup[norm]
            if (result[0], result[1]) not in used:
                return result

        # Substring match — prefer longer keys (more specific).
        # Guard: both the TMDB key and the file norm must be long enough
        # to avoid false positives from very short TMDB titles (e.g. "A",
        # "BLACK", "THE MASTER") matching as substrings of unrelated norms.
        _MIN_SUBSTRING_LEN = 8
        if len(norm) < _MIN_SUBSTRING_LEN:
            return None

        best: tuple[int, int, str] | None = None
        best_len = 0
        for key, value in title_lookup.items():
            if len(key) < _MIN_SUBSTRING_LEN:
                continue
            if (value[0], value[1]) in used:
                continue
            if norm in key or key in norm:
                if len(key) > best_len:
                    best = value
                    best_len = len(key)

        return best

    def _collect_absolute_files(
        self, season_dirs: list[tuple[Path, int]],
    ) -> list[tuple[Path, int, str | None, list[int], bool, int | None]]:
        """Collect all video files sorted by absolute episode number."""
        all_files = []
        for season_dir, season_num in season_dirs:
            for f in sorted(season_dir.iterdir()):
                if not f.is_file() or f.suffix.lower() not in VIDEO_EXTENSIONS:
                    continue
                eps, raw_title, is_sr = extract_episode(f.name)
                season_hint = extract_season_number(f.name) if is_sr else None
                abs_num = eps[0] if eps else 9999
                all_files.append((f, abs_num, raw_title, eps, is_sr, season_hint))
        all_files.sort(key=lambda x: x[1])
        return all_files

    def get_completeness(
        self,
        items: list[PreviewItem],
        checked_indices: set[int] | None = None,
    ) -> CompletenessReport:
        """
        Compute completeness of matched episodes vs TMDB expectations.

        Compares the episode numbers found in *items* against the full
        TMDB season map.  Season 0 (specials) is tallied separately.

        Args:
            items: Preview items from a scan.
            checked_indices: If provided, only items at these indices
                count as matched.  If None, all items count.

        Must be called after scan() so that episode_titles is populated.
        """
        tmdb_seasons = self._get_tmdb_seasons()

        # Collect matched episode numbers per season from preview items
        matched_by_season: dict[int, set[int]] = defaultdict(set)
        for i, item in enumerate(items):
            if checked_indices is not None and i not in checked_indices:
                continue
            if item.season is not None and item.episodes:
                for ep in item.episodes:
                    matched_by_season[item.season].add(ep)

        seasons: dict[int, SeasonCompleteness] = {}

        for sn, sdata in sorted(tmdb_seasons.items()):
            expected_eps = set(sdata["titles"].keys())
            matched_eps = matched_by_season.get(sn, set())
            # Only count episodes that TMDB knows about as matched
            matched_valid = matched_eps & expected_eps
            missing_eps = expected_eps - matched_valid

            missing_details = []
            for ep_num in sorted(missing_eps):
                title = sdata["titles"].get(ep_num, f"Episode {ep_num}")
                missing_details.append((ep_num, title))

            matched_details = []
            for ep_num in sorted(matched_valid):
                title = sdata["titles"].get(ep_num, f"Episode {ep_num}")
                matched_details.append((ep_num, title))

            seasons[sn] = SeasonCompleteness(
                season=sn,
                expected=len(expected_eps),
                matched=len(matched_valid),
                missing=missing_details,
                matched_episodes=matched_details,
            )

        # Aggregate totals (exclude specials / season 0)
        total_expected = sum(
            sc.expected for sn, sc in seasons.items() if sn > 0)
        total_matched = sum(
            sc.matched for sn, sc in seasons.items() if sn > 0)
        total_missing = []
        for sn, sc in sorted(seasons.items()):
            if sn > 0:
                for ep_num, title in sc.missing:
                    total_missing.append((sn, ep_num, title))

        specials = seasons.get(0)

        return CompletenessReport(
            seasons={sn: sc for sn, sc in seasons.items() if sn > 0},
            specials=specials,
            total_expected=total_expected,
            total_matched=total_matched,
            total_missing=total_missing,
        )


# ─── Movie scanning ──────────────────────────────────────────────────────────

