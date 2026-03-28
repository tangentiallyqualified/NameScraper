"""
Rename engine — media-type-aware scanning, preview building, and execution.

This module contains the core logic that was previously embedded inside the
GUI class.  It operates on plain data structures (dicts, lists, Paths) and
has no tkinter dependency, making it testable and reusable.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from dataclasses import dataclass, field

from .constants import VIDEO_EXTENSIONS, MediaType
from .parsing import (
    EXTRAS_FOLDER_PATTERN,
    is_extras_folder,
    build_movie_name,
    build_show_folder_name,
    build_tv_name,
    clean_folder_name,
    extract_episode,
    extract_year,
    get_season,
    find_companion_subtitles,
    is_already_complete,
    is_sample_file,
    looks_like_tv_episode,
    normalize_for_match,
    normalize_for_specials,
)
from .tmdb import TMDBClient


# ─── Data structures ─────────────────────────────────────────────────────────

@dataclass
class CompanionFile:
    """
    A non-video file renamed alongside its parent media file.

    Carries a fully-computed rename plan so every consumer — the GUI,
    the job builder, the snapshot service — can read it directly without
    reconstructing names from intermediate data.

    ``file_type`` is an open string enum.  Current values:
      ``"subtitle"``  — SRT, ASS, SSA, VTT, SUP, etc.

    Future values (not yet implemented):
      ``"poster"``    — cover art (.jpg/.png) inside the movie folder
      ``"nfo"``       — metadata sidecar files (.nfo)

    Adding a new companion type requires only producing ``CompanionFile``
    objects with the appropriate ``file_type``; no changes to ``PreviewItem``,
    ``_build_rename_ops``, the job executor, or the snapshot service.
    """
    original: Path      # Absolute source path
    new_name: str       # Target filename (already computed — no reconstruction needed)
    file_type: str      # "subtitle" | "poster" | "nfo" | …


@dataclass
class PreviewItem:
    """One file's rename plan.  The GUI reads these to build the preview."""
    original: Path
    new_name: str | None
    target_dir: Path | None
    season: int | None          # None for movies
    episodes: list[int]         # Empty for movies
    status: str                 # "OK", "SKIP: ...", "CONFLICT: ..."
    media_type: str = MediaType.TV
    media_id: int | None = None      # TMDB ID — for grouping in batch mode
    media_name: str | None = None    # Display name — for grouping in batch mode
    # Non-video files renamed alongside this item (subtitles, and future types).
    # Each entry carries a fully-computed (original, new_name, file_type) plan.
    # Persisted in scan snapshots so restored sessions retain pairing.
    companions: list[CompanionFile] = field(default_factory=list)
    # Episode-level match confidence: 1.0 = strong S##E## match, 0.0 = positional
    # guess from an unstructured filename.  Low values flag items for user review.
    episode_confidence: float = 1.0

    def is_move(self) -> bool:
        """True if this rename also moves the file to a different folder."""
        return (
            self.target_dir is not None
            and self.target_dir != self.original.parent
        )

    @property
    def is_conflict(self) -> bool:
        """True when this item collides with another planned target."""
        return self.status.startswith("CONFLICT")

    @property
    def is_skipped(self) -> bool:
        """True when this item is intentionally non-actionable."""
        return self.status.startswith("SKIP")

    @property
    def is_review(self) -> bool:
        """True when this item needs manual attention before trust."""
        return self.status.startswith("REVIEW")

    @property
    def is_unmatched(self) -> bool:
        """True when this item is routed through the unmatched flow."""
        return "UNMATCHED" in self.status

    @property
    def is_actionable(self) -> bool:
        """True when this item can produce a concrete rename operation.

        Items with OK, UNMATCHED, or REVIEW status are actionable
        (REVIEW items have a valid rename plan computed from the
        best-available TMDB match — the user confirms the match by
        checking the item).  SKIP and CONFLICT items are never
        actionable.
        """
        if self.new_name is None:
            return False
        if self.status != "OK" and not self.is_unmatched and "REVIEW" not in self.status:
            return False
        target_dir = self.target_dir or self.original.parent
        return not (
            self.new_name == self.original.name
            and target_dir == self.original.parent
        )


@dataclass
class RenameResult:
    """Outcome of an execute_rename call."""
    renamed_count: int = 0
    errors: list[str] = field(default_factory=list)
    log_entry: dict = field(default_factory=dict)
    new_root: Path | None = None  # Set if the root show folder was renamed


@dataclass
class SeasonCompleteness:
    """Completeness info for a single season."""
    season: int
    expected: int
    matched: int
    missing: list[tuple[int, str]]  # [(ep_num, title), ...]
    matched_episodes: list[tuple[int, str]] = field(default_factory=list)  # [(ep_num, title), ...]

    @property
    def is_complete(self) -> bool:
        return self.expected > 0 and self.matched >= self.expected

    @property
    def pct(self) -> float:
        return (self.matched / self.expected * 100) if self.expected else 0.0


@dataclass
class CompletenessReport:
    """Full completeness report for a TV series."""
    seasons: dict[int, SeasonCompleteness]       # keyed by season num (>0)
    specials: SeasonCompleteness | None           # season 0, or None
    total_expected: int
    total_matched: int
    total_missing: list[tuple[int, int, str]]     # [(season, ep_num, title), ...]

    @property
    def is_complete(self) -> bool:
        return self.total_expected > 0 and self.total_matched >= self.total_expected

    @property
    def pct(self) -> float:
        return (self.total_matched / self.total_expected * 100) if self.total_expected else 0.0


@dataclass
class ScanState:
    """
    Per-show scan state — decouples show-level data from the GUI.

    In single-show mode, one ScanState is created and assigned to
    app.active_scan.  In batch TV mode, each detected show gets
    its own ScanState stored in app.batch_states.

    GUI-side fields (check_vars, selected_index, etc.) use ``Any``
    type hints because they hold tkinter objects that the engine
    module deliberately doesn't import.
    """
    folder: Path
    media_info: dict                                    # TMDB show/movie dict
    scanner: TVScanner | None = None
    preview_items: list[PreviewItem] = field(default_factory=list)
    completeness: CompletenessReport | None = None

    # Match metadata
    confidence: float = 0.0
    alternate_matches: list[dict] = field(default_factory=list)
    search_results: list[dict] = field(default_factory=list)
    relative_folder: str = ""
    parent_relative_folder: str | None = None
    duplicate_of_relative_folder: str | None = None
    discovery_reason: str = ""
    has_direct_season_subdirs: bool = False
    direct_episode_file_count: int = 0
    direct_video_file_count: int = 0
    discovered_via_symlink: bool = False

    # GUI-side state (populated by preview_canvas, not by engine)
    check_vars: dict = field(default_factory=dict)
    selected_index: int | None = None
    card_positions: list[tuple[int, int, int]] = field(default_factory=list)
    season_header_positions: list[tuple[int, int, int]] = field(default_factory=list)
    display_order: list[int] = field(default_factory=list)
    collapsed_seasons: set[int] = field(default_factory=set)

    # Flags
    scanned: bool = False                               # True after Phase 2 scan
    scanning: bool = False                              # True while Phase 2 scan is in progress
    checked: bool = True                                # Master show-level checkbox
    duplicate_of: str | None = None                     # Display name of the primary match (if this is a dup)
    queued: bool = False                                # True after added to job queue

    @property
    def show_id(self) -> int | None:
        return self.media_info.get("id")

    @property
    def display_name(self) -> str:
        name = (self.media_info.get("name")
                or self.media_info.get("title")
                or self.folder.name)
        year = self.media_info.get("year", "")
        return f"{name} ({year})" if year else name

    @property
    def needs_review(self) -> bool:
        return self.confidence < AUTO_ACCEPT_THRESHOLD

    @property
    def file_count(self) -> int:
        return len(self.preview_items)

    @property
    def total_expected(self) -> int:
        if self.completeness:
            return self.completeness.total_expected
        return 0

    @property
    def total_matched(self) -> int:
        if self.completeness:
            return self.completeness.total_matched
        return 0

    @property
    def match_pct(self) -> float:
        if self.completeness:
            return self.completeness.pct
        return 0.0

    @property
    def all_skipped(self) -> bool:
        """True if scanned but every file was SKIP (nothing actionable)."""
        if not self.scanned or not self.preview_items:
            return False
        return all(it.status.startswith("SKIP") for it in self.preview_items)

    @property
    def actionable_indices(self) -> set[int]:
        """Return indices of preview items that can produce rename ops."""
        return {
            index for index, item in enumerate(self.preview_items)
            if item.is_actionable
        }

    @property
    def actionable_file_count(self) -> int:
        """Return the number of actionable files in the current preview."""
        return len(self.actionable_indices)

    def reset_gui_state(self) -> None:
        """Clear GUI-side state (e.g. when switching shows)."""
        self.check_vars.clear()
        self.selected_index = None
        self.card_positions.clear()
        self.season_header_positions.clear()
        self.display_order.clear()
        self.collapsed_seasons.clear()

    def reset_scan(self) -> None:
        """Clear scan data to force a rescan."""
        self.scanner = None
        self.preview_items.clear()
        self.completeness = None
        self.scanned = False
        self.reset_gui_state()


def get_checked_indices_from_state(state: ScanState) -> set[int]:
    """
    Return indices of checked, actionable items from a ScanState.

    Centralises the checked-item collection logic used by both
    single-show and batch rename paths.
    """
    return {
        i for i, item in enumerate(state.preview_items)
        if state.check_vars.get(str(i)) is not None
        and state.check_vars[str(i)].get()
        and item.is_actionable
    }


_log = logging.getLogger(__name__)


# ─── Batch TV orchestration ─────────────────────────────────────────────────

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

    @staticmethod
    def _normalized_relative_folder(relative_folder: str, fallback: Path) -> str:
        text = relative_folder or fallback.as_posix()
        return text.replace("\\", "/").casefold()

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
        """Mark lower-priority TMDB matches as duplicates deterministically."""
        for state in self.states:
            state.duplicate_of = None
            state.duplicate_of_relative_folder = None

        seen_ids: dict[int, ScanState] = {}
        for state in self.states:
            sid = state.show_id
            if sid is None:
                continue
            primary = seen_ids.get(sid)
            if primary is None:
                seen_ids[sid] = state
                continue

            if self._duplicate_priority(state) < self._duplicate_priority(primary):
                primary.duplicate_of = state.display_name
                primary.duplicate_of_relative_folder = state.relative_folder or None
                primary.checked = False
                state.duplicate_of = None
                state.duplicate_of_relative_folder = None
                seen_ids[sid] = state
            else:
                state.duplicate_of = primary.display_name
                state.duplicate_of_relative_folder = primary.relative_folder or None
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
        contenders: list[tuple[dict, float, int]] = []

        for result, score in scored:
            if top_score - score > threshold:
                break
            show_id = result.get("id")
            if show_id is None:
                continue
            details = self.tmdb.get_tv_details(show_id)
            count = (details or {}).get(detail_key) or 0
            contenders.append((result, score, count))

        if not contenders:
            return scored[0]

        # Pick the contender whose count is closest to file_count.
        # On ties, prefer the one with the higher original score.
        best = min(
            contenders,
            key=lambda c: (abs(c[2] - file_count), -c[1]),
        )
        return best[0], best[1]

    def _get_discovery_service(self):
        if self.discovery_service is None:
            from .app.services import TVLibraryDiscoveryService

            self.discovery_service = TVLibraryDiscoveryService()
        return self.discovery_service

    def discover_shows(
        self,
        progress_callback: Callable | None = None,
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
        candidates: list[tuple[object, str, str | None]] = []
        for candidate in discovered:
            cleaned = clean_folder_name(candidate.folder.name, include_year=False)
            year_hint = extract_year(candidate.folder.name)
            candidates.append((candidate, cleaned, year_hint))

        if not candidates:
            return []

        _log.info("Discovered %d candidate show folders", len(candidates))

        # Parallel TMDB search
        queries = [(name, year) for _, name, year in candidates]
        all_results = self.tmdb.search_tv_batch(
            queries,
            progress_callback=progress_callback,
        )

        # Build ScanState for each candidate
        states: list[ScanState] = []
        for (candidate, cleaned_name, year_hint), results in zip(candidates, all_results):
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
                )
                states.append(state)
                continue

            # Score results
            raw_name = clean_folder_name(folder.name)
            scored = score_results(results, raw_name, year_hint, title_key="name")
            scored = boost_scores_with_alt_titles(
                scored, raw_name, year_hint, self.tmdb,
                title_key="name", media_type="tv",
                preferred_country=_country_from_language(self.tmdb.language),
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
                file_count = self._count_season_subdirs(candidate.folder)
                use_seasons = True
            if file_count > 0 and len(scored) >= 2:
                runner_up, runner_up_score = scored[1]
                if best_score - runner_up_score <= 0.10:
                    best, best_score = self._episode_count_tiebreak(
                        scored, file_count, threshold=0.10,
                        compare_seasons=use_seasons,
                    )

            alternates = [r for r, s in scored[1:4] if s > 0.3]  # Top 3 alternates above threshold

            # Only auto-check shows with confident matches
            auto_check = best_score >= AUTO_ACCEPT_THRESHOLD

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

        states.sort(key=_sort_key)

        self.states = states
        self._apply_duplicate_labels()
        self.states.sort(key=_sort_key)
        return states

    def scan_show(
        self,
        state: ScanState,
        progress_callback: Callable | None = None,
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

        state.scanning = True
        _log.info("Scanning episodes for: %s", state.display_name)

        try:
            scanner = TVScanner(self.tmdb, state.media_info, state.folder)
            items, has_mismatch = scanner.scan()

            _log.info("Folder '%s' produced %d items (mismatch=%s), seasons: %s",
                      state.folder.name, len(items), has_mismatch,
                      sorted({it.season for it in items if it.season is not None}))

            # For batch mode, auto-fix mismatches without prompting
            if has_mismatch:
                _log.info("Season mismatch detected for %s, using consolidated scan",
                           state.display_name)
                items = scanner.scan_consolidated()

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
    ) -> None:
        """
        Phase 2 bulk: Scan all shows that have a TMDB match.

        Runs sequentially because each show's scan does multiple TMDB API
        calls (one per season) and the rate limiter handles throughput.
        """
        to_scan = [
            s for s in self.states
            if not s.scanned and not s.queued and s.show_id is not None
        ]
        total = len(to_scan)

        for i, state in enumerate(to_scan):
            try:
                self.scan_show(state)
            except Exception as e:
                _log.error("Failed to scan %s: %s", state.display_name, e)
            if progress_callback:
                progress_callback(i + 1, total)

    def rematch_show(self, state: ScanState, new_match: dict) -> None:
        """Swap a show's TMDB match and invalidate its scan data."""
        state.media_info = new_match
        # Rescore confidence against the original search results
        raw_name = clean_folder_name(state.folder.name)
        year_hint = extract_year(state.folder.name)
        scored = score_results(
            [new_match], raw_name, year_hint, title_key="name")
        state.confidence = scored[0][1] if scored else 0.0
        state.reset_scan()
        self._apply_duplicate_labels()

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

class BatchMovieOrchestrator:
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
    def _duplicate_priority(cls, state: ScanState) -> tuple[float, int, int, str]:
        normalized_relative = cls._normalized_relative_folder(
            state.relative_folder,
            state.folder,
        )
        depth = len(PurePosixPath(normalized_relative).parts)
        # "Title (Year)" folder name match beats loose files in a multi-movie folder
        evidence_rank = 0 if state.discovery_reason == "title_year_folder" else 1
        return (-state.confidence, depth, evidence_rank, normalized_relative)

    def _apply_duplicate_labels(self) -> None:
        """Mark lower-priority TMDB matches as duplicates deterministically."""
        for state in self.states:
            state.duplicate_of = None
            state.duplicate_of_relative_folder = None

        seen_ids: dict[int, ScanState] = {}
        for state in self.states:
            mid = state.show_id  # works for movies too — reads media_info["id"]
            if mid is None:
                continue
            primary = seen_ids.get(mid)
            if primary is None:
                seen_ids[mid] = state
                continue

            if self._duplicate_priority(state) < self._duplicate_priority(primary):
                primary.duplicate_of = state.display_name
                primary.duplicate_of_relative_folder = state.relative_folder or None
                primary.checked = False
                state.duplicate_of = None
                state.duplicate_of_relative_folder = None
                seen_ids[mid] = state
            else:
                state.duplicate_of = primary.display_name
                state.duplicate_of_relative_folder = primary.relative_folder or None
                state.checked = False

    def _get_discovery_service(self):
        if self.discovery_service is None:
            from .app.services import MovieLibraryDiscoveryService

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
        from .app.models import MovieDirectoryRole

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
            auto_check = best_score >= AUTO_ACCEPT_THRESHOLD

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
                direct_video_file_count=candidate.direct_video_file_count,
                discovered_via_symlink=candidate.discovered_via_symlink,
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
            video_files = sorted(
                f for f in state.folder.iterdir()
                if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
                and not is_sample_file(f) and not looks_like_tv_episode(f)
            )

            items: list[PreviewItem] = []
            for f in video_files:
                item = _build_movie_preview_item(f, chosen, self.root)
                item.companions = _build_subtitle_companions(f, item.new_name)
                if state.confidence < AUTO_ACCEPT_THRESHOLD:
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
        raw_name = clean_folder_name(state.folder.name)
        year_hint = extract_year(state.folder.name)
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

    def __init__(self, tmdb: TMDBClient, show_info: dict, root_folder: Path):
        self.tmdb = tmdb
        self.show_info = show_info
        self.root = root_folder
        # Populated during scan — used by the GUI for detail panel
        self.episode_titles: dict[tuple[int, int], str] = {}
        self.episode_posters: dict[tuple[int, int], str | None] = {}
        self.episode_meta: dict[tuple[int, int], dict] = {}  # Rich metadata per episode
        # Cached scan data — computed once, reused across methods
        self._season_dirs: list[tuple[Path, int]] | None = None
        self._tmdb_seasons: dict | None = None

    def _get_season_dirs(self) -> list[tuple[Path, int]]:
        """Find and sort season subdirectories. Cached after first call.

        First pass uses ``get_season()`` for standard patterns (Season 01,
        S02, ordinals).  Second pass matches remaining subdirectories against
        TMDB season names so that named anime seasons (e.g. "Karasuno High
        School vs. Shiratorizawa Academy") are correctly identified.
        """
        if self._season_dirs is not None:
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
            self._season_dirs = [(self.root, 1)]
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
        is_flat_folder = (
            len(season_dirs) == 1
            and season_dirs[0][0] == self.root
        )
        non_special_tmdb_seasons = {
            sn for sn in tmdb_seasons if sn != 0
        }
        if is_flat_folder and len(non_special_tmdb_seasons) > 1:
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

            # Detect if this is an extras/featurettes folder (vs actual Season 00)
            extras_folder = (
                season_num == 0
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
                    if season_dir == self.root:
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

        return items

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

        # Try by episode number (only if from S##E## pattern, not bare numbers
        # which could be "Season 3 - Bloopers" where 3 is the season not episode)
        if eps and raw_title:
            # If extract_episode found a number, check if it's a valid S0 episode
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

        # Flat TMDB episode list in order
        tmdb_list: list[tuple[int, int, str]] = []
        for sn in sorted(tmdb_seasons.keys()):
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
            for i, (f, abs_num, raw_title, eps, is_sr) in enumerate(all_files):
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
            return items

        # Sequential fallback — distribute files across TMDB seasons in order
        items: list[PreviewItem] = []
        tmdb_idx = 0

        for f, abs_num, raw_title, eps, is_sr in all_files:
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

        return items

    def _try_title_based_matching(
        self,
        all_files: list[tuple[Path, int, str | None, list[int], bool]],
        tmdb_seasons: dict,
    ) -> list[tuple[int, int, str] | None] | None:
        """Try to match files to TMDB episodes by title.

        Builds a cross-season lookup of all TMDB episode titles and attempts
        to fuzzy-match each file's embedded title.  Returns a list of
        (season, episode_number, title) tuples parallel to *all_files*,
        or ``None`` if fewer than half the files matched (triggering the
        sequential fallback).
        """
        # Build cross-season title lookup: normalized → (season, ep, title)
        title_lookup: dict[str, tuple[int, int, str]] = {}
        for sn in sorted(tmdb_seasons.keys()):
            if sn == 0:
                continue
            for ep_num, title in tmdb_seasons[sn]["titles"].items():
                norm = normalize_for_specials(title)
                if norm and norm not in title_lookup:
                    title_lookup[norm] = (sn, ep_num, title)

        if not title_lookup:
            return None

        matches: list[tuple[int, int, str] | None] = []
        used: set[tuple[int, int]] = set()

        for f, abs_num, raw_title, eps, is_sr in all_files:
            match = self._match_file_title_to_tmdb(raw_title, title_lookup, used)
            if match is not None:
                used.add((match[0], match[1]))
            matches.append(match)

        matched_count = sum(1 for m in matches if m is not None)
        if matched_count < len(all_files) * 0.5:
            return None

        return matches

    @staticmethod
    def _match_file_title_to_tmdb(
        raw_title: str | None,
        title_lookup: dict[str, tuple[int, int, str]],
        used: set[tuple[int, int]],
    ) -> tuple[int, int, str] | None:
        """Match a file's title against the cross-season TMDB title lookup.

        Uses exact normalized match first, then substring match as a
        fallback (preferring longer keys for specificity).  Skips episodes
        already claimed by an earlier file.
        """
        if not raw_title:
            return None

        norm = normalize_for_specials(raw_title)
        if not norm:
            return None

        # Exact normalized match
        if norm in title_lookup:
            result = title_lookup[norm]
            if (result[0], result[1]) not in used:
                return result

        # Substring match — prefer longer keys (more specific)
        best: tuple[int, int, str] | None = None
        best_len = 0
        for key, value in title_lookup.items():
            if (value[0], value[1]) in used:
                continue
            if key and (norm in key or key in norm):
                if len(key) > best_len:
                    best = value
                    best_len = len(key)

        return best

    def _collect_absolute_files(
        self, season_dirs: list[tuple[Path, int]],
    ) -> list[tuple[Path, int, str | None, list[int], bool]]:
        """Collect all video files sorted by absolute episode number."""
        all_files = []
        for season_dir, season_num in season_dirs:
            for f in sorted(season_dir.iterdir()):
                if not f.is_file() or f.suffix.lower() not in VIDEO_EXTENSIONS:
                    continue
                eps, raw_title, is_sr = extract_episode(f.name)
                abs_num = eps[0] if eps else 9999
                all_files.append((f, abs_num, raw_title, eps, is_sr))
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

def _build_subtitle_companions(
    video_path: Path,
    video_new_name: str,
) -> list[CompanionFile]:
    """
    Discover subtitle files paired with *video_path* and return fully-computed
    ``CompanionFile`` objects ready for GUI display and job building.

    The target filename is computed here so no downstream code needs to
    reconstruct it.  Adding support for a new companion file type (posters,
    NFOs, etc.) means writing a similar helper and appending its results to
    ``PreviewItem.companions`` — nothing else changes.
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
    """
    Shared helper: clean a filename stem into a TMDB search query and year hint.

    Returns:
        (search_query, year_hint, raw_name) — raw_name is the cleaned folder
        name with year (for scoring), search_query is the bare title without
        year (for TMDB search).
    """
    raw_name = clean_folder_name(stem)
    search_query = clean_folder_name(stem, include_year=False)
    year_hint = extract_year(stem)
    return search_query, year_hint, raw_name


def _build_movie_preview_item(
    f: Path, chosen: dict, root_folder: Path,
) -> PreviewItem:
    """
    Shared helper: build a PreviewItem from a chosen TMDB movie match.

    Target folder is always ``root_folder / Title (Year)``, so all movies
    end up as direct children of the batch root regardless of where the
    source file lives in the folder hierarchy.

    If the file is already in the correct location, no move is flagged.
    """
    new_name = build_movie_name(chosen["title"], chosen["year"], f.suffix)
    folder_name = build_movie_name(chosen["title"], chosen["year"], "")

    target_dir = root_folder / folder_name

    # If the file is already exactly where it should be, use its parent
    # so is_move() returns False and no unnecessary move is attempted
    if f.parent == target_dir:
        target_dir = f.parent

    return PreviewItem(
        original=f, new_name=new_name, target_dir=target_dir,
        season=None, episodes=[], status="OK",
        media_type=MediaType.MOVIE,
    )


class MovieScanner:
    """
    Scans movie files and builds PreviewItems using TMDB data.

    Supports two modes:
      - Batch folder: pass a root_folder, all video files inside are scanned
      - Explicit files: pass a list of file paths directly

    Each file is independently matched against TMDB by cleaning the
    *filename* (not the folder name).  A new folder "Title (Year)" is
    created next to each file, and the file is moved inside.

    This matches Plex's expected structure:
      Movies/Title (Year)/Title (Year).mkv
    """

    def __init__(
        self,
        tmdb: TMDBClient,
        root_folder: Path,
        files: list[Path] | None = None,
    ):
        self.tmdb = tmdb
        self.root = root_folder
        self._explicit_files = files
        # Populated during scan for the detail panel
        self.movie_info: dict[Path, dict] = {}
        # Cached TMDB search results per file for re-matching
        self._search_cache: dict[Path, list[dict]] = {}

    @property
    def explicit_files(self) -> list[Path] | None:
        """The explicit file list passed at construction, or None for folder mode."""
        return self._explicit_files

    def _get_video_files(self) -> list[Path]:
        """Return the files to process — explicit list or folder scan."""
        if self._explicit_files:
            return sorted(self._explicit_files)
        return sorted(
            f for f in self.root.rglob("*")
            if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
        )

    @staticmethod
    def _filter_sequential_batches(
        files: list[Path],
    ) -> tuple[list[Path], list[PreviewItem]]:
        """
        Detect groups of files that look like sequentially numbered TV episodes.

        Groups files by parent folder, extracts a dash-delimited number from
        each filename (e.g. "Title - 03"), and if 3+ files in the same folder
        share a common prefix with sequential-ish numbers, marks them as TV skips.

        Returns (remaining_files, skipped_items).
        """
        # Pattern: anything, then " - ##" before tags/extension
        _NUM_PATTERN = re.compile(
            r"^(.*?)\s*-\s*(\d{1,3})\s*(?:[\s.\-(v]|$)",
        )

        # Group by parent folder
        by_folder: dict[Path, list[tuple[Path, str, int]]] = defaultdict(list)

        for f in files:
            m = _NUM_PATTERN.search(f.stem)
            if m:
                prefix = m.group(1).strip().lower()
                num = int(m.group(2))
                # Skip numbers that look like years
                if 1900 <= num <= 2099:
                    continue
                by_folder[f.parent].append((f, prefix, num))

        # Find sequential batches (3+ files with same prefix)
        skip_set: set[Path] = set()
        for folder, entries in by_folder.items():
            # Group by prefix
            prefix_groups: dict[str, list[tuple[Path, int]]] = defaultdict(list)
            for f, prefix, num in entries:
                prefix_groups[prefix].append((f, num))

            for prefix, group in prefix_groups.items():
                if len(group) < 3:
                    continue
                # Check if numbers are roughly sequential (allow gaps)
                nums = sorted(n for _, n in group)
                # If the range of numbers is reasonable for a TV series
                # (not like 1, 500, 999) and there are enough of them
                num_range = nums[-1] - nums[0]
                if num_range < len(group) * 3:  # Allow some gaps
                    for f, _ in group:
                        skip_set.add(f)

        remaining = []
        skipped = []
        for f in files:
            if f in skip_set:
                skipped.append(PreviewItem(
                    original=f, new_name=None, target_dir=None,
                    season=None, episodes=[],
                    status="SKIP: looks like a TV episode (sequential batch)",
                    media_type=MediaType.OTHER,
                ))
            else:
                remaining.append(f)

        return remaining, skipped

    def scan(
        self,
        pick_movie_callback: Callable | None = None,
        progress_callback: Callable | None = None,
    ) -> list[PreviewItem]:
        """
        Scan files and build preview items with automatic TMDB matching.

        Performance optimizations for large folders:
          - Files that look like TV episodes (S01E01 patterns, season
            folders) are filtered out automatically with a SKIP status.
          - TMDB searches run in parallel using a thread pool.
          - Connection pooling (HTTP keep-alive) via the TMDBClient session.

        For single-file mode (1 file), the pick callback is invoked for
        immediate confirmation.
        """
        items: list[PreviewItem] = []

        # Phase 1: Collect and filter files
        all_video_files = self._get_video_files()
        video_files: list[Path] = []

        for f in all_video_files:
            if is_sample_file(f):
                items.append(PreviewItem(
                    original=f, new_name=None, target_dir=None,
                    season=None, episodes=[],
                    status="SKIP: release sample clip",
                    media_type=MediaType.OTHER,
                ))
            elif looks_like_tv_episode(f):
                items.append(PreviewItem(
                    original=f, new_name=None, target_dir=None,
                    season=None, episodes=[],
                    status="SKIP: looks like a TV episode",
                    media_type=MediaType.OTHER,
                ))
            else:
                video_files.append(f)

        # Phase 1b: Batch detection — if 3+ remaining files in the same
        # folder share a common name prefix with sequential dash-delimited
        # numbers (e.g. "Title - 01", "Title - 02", "Title - 03"), they're
        # almost certainly TV episodes even without S##E## markers.
        if len(video_files) >= 3:
            video_files, batch_skipped = self._filter_sequential_batches(video_files)
            items.extend(batch_skipped)

        if not video_files:
            return items

        # Single-file mode: serial search with confirmation dialog
        if len(video_files) == 1:
            return items + self._scan_single(
                video_files[0], pick_movie_callback,
            )

        # Phase 2: Build search queries (shared helper eliminates duplication)
        prepared = [_prepare_movie_query(f.stem) for f in video_files]

        # Phase 3: Parallel TMDB search
        def _progress(done, total):
            if progress_callback:
                progress_callback(done, total, "Searching TMDB...")

        # search_movies_batch expects (query, year) tuples
        search_queries = [(q, y) for q, y, _ in prepared]
        all_results = self.tmdb.search_movies_batch(
            search_queries, progress_callback=_progress,
        )

        # Phase 4: Build preview items from results
        for f, (search_query, year_hint, raw_name), results in zip(
            video_files, prepared, all_results,
        ):
            self._search_cache[f] = results

            if not results:
                items.append(PreviewItem(
                    original=f, new_name=None, target_dir=None,
                    season=None, episodes=[],
                    status="REVIEW: no TMDB results — click to search manually",
                    media_type=MediaType.MOVIE,
                ))
                continue

            chosen, confidence = self._best_match(results, raw_name, year_hint)
            self.movie_info[f] = chosen

            item = _build_movie_preview_item(f, chosen, self.root)
            item.companions = _build_subtitle_companions(f, item.new_name)
            if confidence < AUTO_ACCEPT_THRESHOLD:
                # Low confidence — flag for user review instead of auto-accepting
                item.status = (
                    f"REVIEW: best match \"{chosen['title']}\" "
                    f"(confidence {confidence:.0%}) — click to verify"
                )
            items.append(item)

        return items

    def _scan_single(
        self,
        f: Path,
        pick_movie_callback: Callable | None,
    ) -> list[PreviewItem]:
        """Handle single-file scan with confirmation dialog."""
        search_query, year_hint, _raw_name = _prepare_movie_query(f.stem)

        results = self.tmdb.search_with_fallback(
            search_query, self.tmdb.search_movie, year=year_hint)
        if not results:
            results = self.tmdb.search_with_fallback(
                search_query, self.tmdb.search_movie)
        self._search_cache[f] = results

        if pick_movie_callback:
            chosen = pick_movie_callback(results or [], f.name)
            if chosen is CANCEL_SCAN:
                return []
        else:
            chosen = results[0] if results else None

        if not chosen:
            return [PreviewItem(
                original=f, new_name=None, target_dir=None,
                season=None, episodes=[],
                status="SKIP: no movie selected" if results else
                       "REVIEW: no TMDB results — click to search manually",
                media_type=MediaType.MOVIE,
            )]

        self.movie_info[f] = chosen
        item = _build_movie_preview_item(f, chosen, self.root)
        item.companions = _build_subtitle_companions(f, item.new_name)
        return [item]

    def rematch_file(
        self, item: PreviewItem, chosen: dict,
    ) -> PreviewItem:
        """
        Re-match a single file to a different TMDB movie.

        Called from the GUI when the user corrects an auto-match or
        resolves a REVIEW item from the preview.
        """
        self.movie_info[item.original] = chosen
        return _build_movie_preview_item(item.original, chosen, self.root)

    def set_movie_info(self, f: Path, info: dict) -> None:
        """Hydrate cached movie metadata for a file during session restore."""
        self.movie_info[f] = dict(info)

    def set_search_results(self, f: Path, results: list[dict]) -> None:
        """Hydrate cached TMDB search results for a file during session restore."""
        self._search_cache[f] = list(results)

    def get_search_results(self, f: Path) -> list[dict]:
        """Return cached TMDB search results for a file."""
        return self._search_cache.get(f, [])

    def _best_match(
        self, results: list[dict], raw_name: str, year_hint: str | None,
    ) -> tuple[dict, float]:
        """
        Pick the best TMDB result using title similarity + year matching.

        Returns (best_result, confidence) where confidence is 0.0–1.0.
        Delegates scoring to the shared ``score_results`` function,
        then boosts low-confidence matches via alternative titles.
        """
        scored = score_results(results, raw_name, year_hint, title_key="title")
        if not scored:
            return results[0], 0.0
        scored = boost_scores_with_alt_titles(
            scored, raw_name, year_hint, self.tmdb,
            title_key="title", media_type="movie",
            preferred_country=_country_from_language(self.tmdb.language),
        )
        return scored[0]


def title_similarity(a: str, b: str) -> float:
    """
    Compute a simple title similarity score between 0.0 and 1.0.

    Uses the longest common subsequence ratio, which handles:
      - Exact matches → 1.0
      - Substring matches (Daybreakers vs Daybreak) → high but < 1.0
      - Partial overlaps → proportional score
      - Completely different → near 0.0

    This is lightweight and doesn't need external libraries.
    """
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0

    # Quick check: one is substring of the other
    # "daybreak" in "daybreakers" → high but penalized for length diff
    if a in b or b in a:
        shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
        return len(shorter) / len(longer)

    # LCS length ratio
    m, n = len(a), len(b)
    # Optimize: only keep two rows for O(min(m,n)) space
    if m < n:
        a, b = b, a
        m, n = n, m

    prev = [0] * (n + 1)
    for i in range(1, m + 1):
        curr = [0] * (n + 1)
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                curr[j] = prev[j - 1] + 1
            else:
                curr[j] = max(curr[j - 1], prev[j])
        prev = curr

    lcs_len = prev[n]
    return (2.0 * lcs_len) / (m + n)  # Dice-like coefficient


# Minimum confidence for auto-accepting a match without review
AUTO_ACCEPT_THRESHOLD = 0.55


# Sentinel value returned by the pick callback to cancel the entire scan.
CANCEL_SCAN = object()


def score_results(
    results: list[dict],
    raw_name: str,
    year_hint: str | None,
    title_key: str = "title",
) -> list[tuple[dict, float]]:
    """
    Score a list of TMDB search results against a cleaned name.

    Shared by both TV and movie matching paths.  Each result gets a
    confidence score based on:
      - Title similarity (normalized, case-insensitive) weighted at 70%
      - Year match weighted at 30%  (exact=1.0, ±1=0.8, ±2=0.5, ±3=0.2)
      - Exact normalized title match gets a +0.15 bonus

    Args:
        results:    List of TMDB result dicts.
        raw_name:   Cleaned folder/filename to match against.
        year_hint:  4-digit year string extracted from the source, or None.
        title_key:  Key in each result dict holding the title
                    ("title" for movies, "name" for TV).

    Returns:
        List of (result, score) tuples sorted by score descending.
    """
    query_norm = normalize_for_match(raw_name)
    scored: list[tuple[dict, float]] = []

    for r in results:
        title = r.get(title_key, "")
        title_norm = normalize_for_match(title)

        t_score = title_similarity(query_norm, title_norm)

        year_score = 0.0
        if year_hint and r.get("year"):
            try:
                diff = abs(int(year_hint) - int(r["year"]))
                if diff == 0:
                    year_score = 1.0
                elif diff == 1:
                    # Very common: premiere year vs first full season year
                    year_score = 0.8
                elif diff == 2:
                    year_score = 0.5
                elif diff == 3:
                    year_score = 0.2
            except (ValueError, TypeError):
                pass

        score = (t_score * 0.7) + (year_score * 0.3)

        if query_norm == title_norm:
            score += 0.15

        scored.append((r, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


# Number of top candidates to fetch alternative titles for
_ALT_TITLE_CANDIDATES = 5


def _country_from_language(language_tag: str) -> str | None:
    """Extract the ISO 3166-1 country code from a TMDB language tag.

    ``"fr-FR"`` → ``"FR"``, ``"en-US"`` → ``"US"``, ``"ja"`` → ``"JP"``.
    Returns None for empty/unrecognised input.
    """
    if not language_tag:
        return None
    if "-" in language_tag:
        return language_tag.split("-", 1)[1].upper()
    # Bare language code — map common ones to their primary country
    _LANG_TO_COUNTRY = {
        "en": "US", "fr": "FR", "es": "ES", "de": "DE", "it": "IT",
        "pt": "BR", "ja": "JP", "ko": "KR", "zh": "CN", "ru": "RU",
        "nl": "NL", "sv": "SE", "da": "DK", "no": "NO", "fi": "FI",
        "pl": "PL", "tr": "TR", "ar": "SA", "hi": "IN", "th": "TH",
    }
    return _LANG_TO_COUNTRY.get(language_tag.lower())


def boost_scores_with_alt_titles(
    scored: list[tuple[dict, float]],
    raw_name: str,
    year_hint: str | None,
    tmdb: TMDBClient,
    title_key: str = "title",
    media_type: str = "movie",
    preferred_country: str | None = None,
) -> list[tuple[dict, float]]:
    """
    Re-score top candidates using TMDB alternative titles.

    When the best match scores below the auto-accept threshold, fetches
    alternative titles for the top candidates and re-scores each using the
    best-matching alternative.  Returns the full list re-sorted by the
    (potentially boosted) scores.

    Matching priority (fallback chain):

    1. Primary title from the TMDB search result (already scored).
    2. Alternative titles in the user's preferred language/country.
    3. English alternative titles (US / GB) as a universal fallback.
    4. All remaining alternative titles from other languages.

    If no alternative title pushes the score above the auto-accept
    threshold, the original (low) score is preserved and the item will
    be flagged for manual review.

    This is a no-op when the top result already exceeds the threshold or
    when there are no results.
    """
    if not scored:
        return scored

    best_score = scored[0][1]
    if best_score >= AUTO_ACCEPT_THRESHOLD:
        _log.debug(
            "Alt title boost skipped — top result already at %.2f "
            "(threshold %.2f) for %r",
            best_score, AUTO_ACCEPT_THRESHOLD, raw_name,
        )
        return scored

    _log.info(
        "Alt title boost: top score %.2f < %.2f for %r — "
        "checking alt titles (preferred_country=%s)",
        best_score, AUTO_ACCEPT_THRESHOLD, raw_name, preferred_country,
    )

    query_norm = normalize_for_match(raw_name)
    english_countries = {"US", "GB"}
    updated: list[tuple[dict, float]] = []

    for i, (result, original_score) in enumerate(scored):
        # Only fetch alt titles for the top N candidates
        if i < _ALT_TITLE_CANDIDATES and result.get("id") is not None:
            raw_alts = tmdb.get_alternative_titles(
                result["id"], media_type,
            )
            _log.debug(
                "  [%s] id=%s %r: %d alt titles fetched",
                media_type, result["id"],
                result.get(title_key, "?"), len(raw_alts),
            )

            # Sort by priority: preferred country → English → rest
            preferred: list[str] = []
            english: list[str] = []
            rest: list[str] = []
            for title, cc in raw_alts:
                if preferred_country and cc == preferred_country:
                    preferred.append(title)
                elif cc in english_countries:
                    english.append(title)
                else:
                    rest.append(title)
            ordered_alts = preferred + english + rest

            best_alt_score = original_score
            best_alt_title = None
            for alt in ordered_alts:
                alt_norm = normalize_for_match(alt)
                t_score = title_similarity(query_norm, alt_norm)

                year_score = 0.0
                if year_hint and result.get("year"):
                    try:
                        diff = abs(int(year_hint) - int(result["year"]))
                        if diff == 0:
                            year_score = 1.0
                        elif diff == 1:
                            year_score = 0.3
                    except (ValueError, TypeError):
                        pass

                score = (t_score * 0.7) + (year_score * 0.3)
                if query_norm == alt_norm:
                    score += 0.15

                if score > best_alt_score:
                    best_alt_score = score
                    best_alt_title = alt

            if best_alt_title:
                _log.info(
                    "  Boosted id=%s from %.2f → %.2f via alt title %r",
                    result["id"], original_score, best_alt_score,
                    best_alt_title,
                )
            updated.append((result, best_alt_score))
        else:
            updated.append((result, original_score))

    updated.sort(key=lambda x: x[1], reverse=True)
    return updated


# ─── Shared utilities ─────────────────────────────────────────────────────────

def check_duplicates(items: list[PreviewItem]) -> None:
    """Flag items that would collide on the same target path."""
    seen: dict[tuple[str, str], str] = {}
    for item in items:
        if item.new_name is None:
            continue
        target_dir = item.target_dir or item.original.parent
        key = (str(target_dir).lower(), item.new_name.lower())
        if key in seen:
            item.status = f"CONFLICT: same target as {seen[key]}"
        else:
            seen[key] = item.original.name


def execute_rename(
    items: list[PreviewItem],
    checked_indices: set[int],
    show_name: str,
    root_folder: Path,
    show_folder_name: str | None = None,
) -> RenameResult:
    """
    Perform the actual file renames/moves for checked items.

    Supports cross-folder moves, creates target directories as needed,
    normalizes season folder names, optionally renames the root show
    folder to match Plex conventions, and cleans up empty source dirs.

    Args:
        show_folder_name: If provided and the root folder's current name
            doesn't match, rename it.  The new root path is stored in
            result.new_root so the caller can update its state.
    Returns a RenameResult with the log entry for undo support.
    """
    result = RenameResult()
    result.log_entry = {
        "show": show_name,
        "renames": [],
        "created_dirs": [],
        "removed_dirs": [],
        "renamed_dirs": [],
    }

    renames: list[tuple[Path, Path, Path]] = []
    source_dirs: set[Path] = set()

    for i in checked_indices:
        if i >= len(items):
            continue
        item = items[i]
        # Process OK items and UNMATCHED items (which get moved to Unmatched/)
        if item.new_name is None:
            continue
        if item.status != "OK" and "UNMATCHED" not in item.status:
            continue

        src = item.original
        source_dirs.add(src.parent)
        target_dir = item.target_dir or src.parent
        dst = target_dir / item.new_name

        if dst.exists() and src != dst:
            result.errors.append(f"Target already exists, skipped: {dst.name}")
            continue

        renames.append((src, dst, target_dir))

    if not renames:
        return result

    for src, dst, target_dir in renames:
        try:
            if not target_dir.exists():
                target_dir.mkdir(parents=True, exist_ok=True)
                if str(target_dir) not in result.log_entry["created_dirs"]:
                    result.log_entry["created_dirs"].append(str(target_dir))

            if src.parent != target_dir:
                shutil.move(str(src), str(dst))
            else:
                src.rename(dst)

            result.log_entry["renames"].append({
                "old": str(src), "new": str(dst),
            })
            result.renamed_count += 1
        except (OSError, shutil.Error) as e:
            result.errors.append(f"{src.name}: {e}")

    # Normalize season folder names (TV only)
    # Skip directories inside the Unmatched/ folder — they preserve their
    # original names intentionally and shouldn't be treated as seasons.
    unmatched_dir = root_folder / "Unmatched"
    all_dirs = source_dirs.copy()
    for _, dst, td in renames:
        all_dirs.add(td)

    for season_dir in all_dirs:
        if not season_dir.exists() or season_dir == root_folder:
            continue
        # Don't normalize anything under Unmatched/
        try:
            season_dir.relative_to(unmatched_dir)
            continue  # inside Unmatched — skip
        except ValueError:
            pass  # not inside Unmatched — proceed
        season_num = get_season(season_dir)
        if season_num is None:
            continue
        proper_name = f"Season {season_num:02d}"
        if season_dir.name == proper_name:
            continue
        proper_path = season_dir.parent / proper_name
        if proper_path.exists():
            continue
        try:
            season_dir.rename(proper_path)
            result.log_entry["renamed_dirs"].append({
                "old": str(season_dir), "new": str(proper_path),
            })
        except OSError:
            pass

    # Clean up empty source directories
    for src_dir in source_dirs:
        try:
            if src_dir != root_folder and src_dir.exists():
                if not list(src_dir.iterdir()):
                    src_dir.rmdir()
                    result.log_entry["removed_dirs"].append(str(src_dir))
        except OSError:
            pass

    # Rename root show/movie folder to match Plex/TMDB naming
    if show_folder_name and root_folder.exists():
        if root_folder.name != show_folder_name:
            new_root = root_folder.parent / show_folder_name
            same_dir = (
                os.path.normcase(str(root_folder)) ==
                os.path.normcase(str(new_root))
            )
            if same_dir or not new_root.exists():
                try:
                    root_folder.rename(new_root)
                    result.log_entry["renamed_dirs"].append({
                        "old": str(root_folder), "new": str(new_root),
                    })
                    result.new_root = new_root
                except OSError:
                    pass  # Not fatal — files are already renamed

    return result


# ─── Job queue bridge ────────────────────────────────────────────────────────

def _build_rename_ops(
    items: list[PreviewItem],
    checked_indices: set[int],
    library_root: Path,
) -> list:
    """
    Shared helper: convert PreviewItems → RenameOp list.

    Skips items that are already properly named (same name, same
    directory) since queuing those would be a no-op.
    """
    from .job_store import RenameOp

    ops = []
    for i, item in enumerate(items):
        if not item.is_actionable:
            continue

        target_dir = item.target_dir or item.original.parent

        try:
            original_rel = str(item.original.relative_to(library_root))
        except ValueError:
            original_rel = str(item.original)

        try:
            target_rel = str(target_dir.relative_to(library_root))
        except ValueError:
            target_rel = str(target_dir)

        is_selected = i in checked_indices
        ops.append(RenameOp(
            original_relative=original_rel,
            new_name=item.new_name,
            target_dir_relative=target_rel,
            status=item.status,
            season=item.season,
            episodes=list(item.episodes),
            selected=is_selected,
            file_type="video",
        ))

        # Companion ops (subtitles, future: posters, NFOs…) — each carries a
        # fully-computed new_name, so no name reconstruction is needed here.
        # Selection state mirrors the parent video op.
        for companion in item.companions:
            try:
                companion_rel = str(companion.original.relative_to(library_root))
            except ValueError:
                companion_rel = str(companion.original)

            ops.append(RenameOp(
                original_relative=companion_rel,
                new_name=companion.new_name,
                target_dir_relative=target_rel,
                status="OK",
                season=item.season,
                episodes=list(item.episodes),
                selected=is_selected,
                file_type=companion.file_type,
            ))

    return ops


def build_rename_job_from_state(
    state: ScanState,
    library_root: Path,
    show_folder_rename: str | None = None,
    checked_indices: set[int] | None = None,
) -> 'RenameJob':
    """
    Create a RenameJob from a ScanState (TV batch mode).

    Snapshots the checked PreviewItems as RenameOp instances with
    paths relative to library_root.
    """
    from .job_store import RenameJob

    checked_indices = checked_indices or get_checked_indices_from_state(state)
    ops = _build_rename_ops(state.preview_items, checked_indices, library_root)

    # Prefer the pre-computed relative_folder from discovery; fall back to
    # computing it from the absolute paths (which can fail if the state was
    # restored against a different library_root).
    if state.relative_folder:
        source_folder = state.relative_folder
    else:
        try:
            source_folder = str(state.folder.relative_to(library_root))
        except ValueError:
            source_folder = state.folder.name

    return RenameJob(
        media_type=MediaType.TV,
        tmdb_id=state.show_id or 0,
        media_name=state.display_name,
        library_root=str(library_root),
        source_folder=source_folder,
        rename_ops=ops,
        show_folder_rename=show_folder_rename,
    )


def build_rename_job_from_items(
    items: list[PreviewItem],
    checked_indices: set[int],
    media_type: str,
    tmdb_id: int,
    media_name: str,
    library_root: Path,
    source_folder: Path,
    show_folder_rename: str | None = None,
) -> 'RenameJob':
    """
    Create a RenameJob from raw PreviewItems (single-show TV or movie mode).
    """
    from .job_store import RenameJob

    ops = _build_rename_ops(items, checked_indices, library_root)

    try:
        source_rel = str(source_folder.relative_to(library_root))
    except ValueError:
        source_rel = str(source_folder)

    return RenameJob(
        media_type=media_type,
        tmdb_id=tmdb_id,
        media_name=media_name,
        library_root=str(library_root),
        source_folder=source_rel,
        rename_ops=ops,
        show_folder_rename=show_folder_rename,
    )

