"""UI-neutral orchestration of TV and movie scanning sessions.

Owns session state (batch_states, active_scan, movie_library_states),
mode routing, scanning lifecycle, and TMDB cache persistence.  The widget
layer reads state through properties and receives change notifications
via the listener pattern (same as ``QueueExecutor``).

Threading model: scanning methods spawn background threads internally.
Callbacks fire from **any** thread — the widget layer is responsible for
marshaling to the main thread (``root.after`` in tkinter, signals in
PySide6).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

from ...constants import MediaType
from ...engine import (
    BatchMovieOrchestrator,
    BatchTVOrchestrator,
    MovieScanner,
    pick_alternate_matches,
    PreviewItem,
    ScanState,
    ScanCancelledError,
    set_auto_accept_threshold,
    score_results,
    TVScanner,
)
from ...parsing import clean_folder_name, extract_year
from ...job_store import JobStore
from ..models import ScanLifecycle, ScanProgress
from ..services.cache_service import PersistentCacheService
from ..services.command_gating_service import CommandGatingService
from ..services.refresh_policy_service import RefreshPolicyService
from ..services.settings_service import SettingsService
from ..services.tv_library_discovery_service import TVLibraryDiscoveryService
from ..services.movie_library_discovery_service import MovieLibraryDiscoveryService

_log = logging.getLogger(__name__)


class MediaController:
    """UI-neutral orchestration of TV and movie scanning sessions.

    State ownership:
      - TV session: ``batch_states``, ``active_scan``, ``batch_orchestrator``
      - Movie session: ``movie_library_states``, ``movie_preview_items``,
        ``movie_scanner``
      - Mode flags: ``active_content_mode``, ``active_library_mode``
      - Progress: ``scan_progress``
    """

    def __init__(
        self,
        job_store: JobStore,
        command_gating: CommandGatingService,
        settings: SettingsService,
        cache_service: PersistentCacheService,
        refresh_policy: RefreshPolicyService,
        tv_discovery: TVLibraryDiscoveryService | None = None,
        movie_discovery: MovieLibraryDiscoveryService | None = None,
    ) -> None:
        self._job_store = job_store
        self._command_gating = command_gating
        self._settings = settings
        self._cache_service = cache_service
        self._refresh_policy = refresh_policy
        self._tv_discovery = tv_discovery or TVLibraryDiscoveryService()
        self._movie_discovery = movie_discovery or MovieLibraryDiscoveryService()
        set_auto_accept_threshold(self._settings.auto_accept_threshold)

        # ── Mode flags ──────────────────────────────────────────────
        self._active_content_mode: MediaType = MediaType.TV
        self._active_library_mode: MediaType | None = None

        # ── TV session state ────────────────────────────────────────
        self._batch_mode: bool = False
        self._batch_states: list[ScanState] = []
        self._active_scan: ScanState | None = None
        self._batch_orchestrator: BatchTVOrchestrator | None = None
        self._tv_root_folder: Path | None = None

        # ── Movie session state ─────────────────────────────────────
        self._movie_library_states: list[ScanState] = []
        self._movie_preview_items: list[PreviewItem] = []
        self._movie_scanner: MovieScanner | None = None
        self._movie_folder: Path | None = None
        self._movie_media_info: dict | None = None

        # ── Progress ────────────────────────────────────────────────
        self._scan_progress = ScanProgress(lifecycle=ScanLifecycle.IDLE)
        self._scan_operation_lock = threading.Lock()
        self._scan_cancel_event: threading.Event | None = None

        # ── Selection ───────────────────────────────────────────────
        self._library_selected_index: int | None = None

        # ── Listeners ───────────────────────────────────────────────
        self._listeners: list[dict[str, Callable | None]] = []

    # ── Listener management ─────────────────────────────────────────

    def add_listener(
        self,
        on_library_changed: Callable[[list[ScanState]], None] | None = None,
        on_progress: Callable[[ScanProgress], None] | None = None,
        on_scan_complete: Callable[[ScanState | None], None] | None = None,
        on_mode_changed: Callable[[MediaType, MediaType | None], None] | None = None,
    ) -> int:
        """Register a listener.  Returns listener index."""
        self._listeners.append({
            "library_changed": on_library_changed,
            "progress": on_progress,
            "scan_complete": on_scan_complete,
            "mode_changed": on_mode_changed,
        })
        return len(self._listeners) - 1

    def clear_listeners(self) -> None:
        self._listeners.clear()

    def _notify(self, event: str, *args: Any) -> None:
        for listener in self._listeners:
            cb = listener.get(event)
            if cb is not None:
                try:
                    cb(*args)
                except Exception:
                    _log.exception("Listener callback error for %s", event)

    # ── Properties ──────────────────────────────────────────────────

    @property
    def active_content_mode(self) -> MediaType:
        return self._active_content_mode

    @property
    def active_library_mode(self) -> MediaType | None:
        return self._active_library_mode

    @property
    def library_states(self) -> list[ScanState]:
        """Routed roster: returns TV batch_states or movie_library_states."""
        if self._active_library_mode == MediaType.MOVIE:
            return self._movie_library_states
        return self._batch_states

    @property
    def active_scan(self) -> ScanState | None:
        return self._active_scan

    @active_scan.setter
    def active_scan(self, value: ScanState | None) -> None:
        self._active_scan = value

    @property
    def scan_progress(self) -> ScanProgress:
        return self._scan_progress

    @property
    def batch_mode(self) -> bool:
        return self._batch_mode

    @property
    def batch_states(self) -> list[ScanState]:
        return self._batch_states

    @property
    def batch_orchestrator(self) -> BatchTVOrchestrator | None:
        return self._batch_orchestrator

    @property
    def tv_root_folder(self) -> Path | None:
        return self._tv_root_folder

    @property
    def movie_folder(self) -> Path | None:
        return self._movie_folder

    @property
    def movie_library_states(self) -> list[ScanState]:
        return self._movie_library_states

    @property
    def movie_preview_items(self) -> list[PreviewItem]:
        return self._movie_preview_items

    @property
    def movie_scanner(self) -> MovieScanner | None:
        return self._movie_scanner

    @property
    def movie_media_info(self) -> dict | None:
        return self._movie_media_info

    @property
    def library_selected_index(self) -> int | None:
        return self._library_selected_index

    @library_selected_index.setter
    def library_selected_index(self, value: int | None) -> None:
        self._library_selected_index = value

    @property
    def command_gating(self) -> CommandGatingService:
        return self._command_gating

    @property
    def settings(self) -> SettingsService:
        return self._settings

    def apply_runtime_settings(self) -> None:
        """Apply settings that directly affect scan/review semantics."""
        set_auto_accept_threshold(self._settings.auto_accept_threshold)
        for state in (*self._batch_states, *self._movie_library_states):
            if state.match_origin == "manual":
                continue
            if state.needs_review:
                state.checked = False
        self._notify("library_changed", self.library_states)

    # ── Progress helpers ────────────────────────────────────────────

    def _set_progress(
        self,
        lifecycle: ScanLifecycle,
        *,
        phase: str = "",
        done: int = 0,
        total: int = 0,
        current_item: str | None = None,
        message: str = "",
    ) -> None:
        self._scan_progress = ScanProgress(
            lifecycle=lifecycle,
            phase=phase,
            done=done,
            total=total,
            current_item=current_item,
            message=message,
        )
        self._notify("progress", self._scan_progress)

    def _begin_scan_operation(self) -> threading.Event:
        event = threading.Event()
        with self._scan_operation_lock:
            self._scan_cancel_event = event
        return event

    def _is_current_scan_operation(self, event: threading.Event) -> bool:
        with self._scan_operation_lock:
            return self._scan_cancel_event is event

    def _finish_scan_operation(self, event: threading.Event) -> None:
        with self._scan_operation_lock:
            if self._scan_cancel_event is event:
                self._scan_cancel_event = None

    def cancel_scan(self) -> bool:
        with self._scan_operation_lock:
            event = self._scan_cancel_event
        if event is None:
            return False
        event.set()
        return True

    # ── TV session methods ──────────────────────────────────────────

    def accept_tv_show(
        self,
        folder: Path,
        tmdb: Any,
        show_info: dict,
    ) -> ScanState:
        """Set up a single-show TV session.

        Creates a ``ScanState``, sets mode flags, and returns the state.
        Does NOT start scanning — the widget calls ``scan_show()`` next.
        """
        self._batch_mode = False
        self._batch_orchestrator = None
        self._active_content_mode = MediaType.TV
        self._active_library_mode = MediaType.TV
        self._tv_root_folder = folder

        from ...parsing import get_season
        scanner = TVScanner(tmdb, show_info, folder, season_hint=get_season(folder))
        state = ScanState(
            folder=folder,
            media_info=show_info,
            scanner=scanner,
            confidence=1.0,
            scanned=False,
        )
        self._active_scan = state
        self._batch_states = [state]
        self._library_selected_index = 0

        self._set_progress(
            ScanLifecycle.SCANNING,
            phase="Scanning TV files...",
            message="Scanning TV files...",
        )
        self._notify("mode_changed", self._active_content_mode, self._active_library_mode)
        self._notify("library_changed", self._batch_states)
        return state

    def start_tv_batch(
        self,
        folder: Path,
        tmdb: Any,
    ) -> None:
        """Discover TV shows and match to TMDB (Phase 1).

        Spawns a background thread.  Fires ``on_progress`` during
        discovery/matching and ``on_library_changed`` when shows are
        populated.  Fires ``on_scan_complete(None)`` when discovery
        finishes (before episode scanning starts).
        """
        self._batch_mode = True
        self._active_content_mode = MediaType.TV
        self._active_library_mode = MediaType.TV
        self._tv_root_folder = folder
        self._batch_orchestrator = BatchTVOrchestrator(
            tmdb, folder, discovery_service=self._tv_discovery,
        )
        self._batch_states = []
        self._active_scan = None
        self._library_selected_index = None

        self._set_progress(
            ScanLifecycle.DISCOVERING,
            phase="Discovering shows...",
            message="Discovering shows...",
        )
        self._notify("mode_changed", self._active_content_mode, self._active_library_mode)

        orchestrator = self._batch_orchestrator
        cancel_event = self._begin_scan_operation()

        def _progress(done: int, total: int) -> None:
            if cancel_event.is_set():
                raise ScanCancelledError("Scan cancelled")
            self._set_progress(
                ScanLifecycle.MATCHING,
                phase="Matching shows...",
                done=done,
                total=total,
                message=f"Matching shows... {done}/{total}",
            )

        def _worker() -> None:
            try:
                states = orchestrator.discover_shows(
                    progress_callback=_progress,
                    cancel_event=cancel_event,
                )
            except ScanCancelledError:
                if not self._is_current_scan_operation(cancel_event):
                    return
                self._batch_states = []
                self._active_scan = None
                self._library_selected_index = None
                self._set_progress(
                    ScanLifecycle.CANCELLED,
                    phase="TV discovery cancelled",
                    message="TV discovery cancelled.",
                )
                self._notify("library_changed", self._batch_states)
                self._finish_scan_operation(cancel_event)
                return
            except Exception as e:
                if not self._is_current_scan_operation(cancel_event):
                    return
                _log.exception("TV batch discovery failed: %s", e)
                self._set_progress(
                    ScanLifecycle.FAILED,
                    phase="Discovery failed.",
                    message=f"Discovery failed: {e}",
                )
                self._finish_scan_operation(cancel_event)
                return

            if not self._is_current_scan_operation(cancel_event):
                return

            self._batch_states = states or []
            if not self._batch_states:
                self._set_progress(
                    ScanLifecycle.WARNING,
                    phase="No TV shows found in this folder.",
                    message="No TV shows found in this folder.",
                )
                self._notify("library_changed", self._batch_states)
                self._finish_scan_operation(cancel_event)
                return

            self.sync_queued_states()

            needs_review = sum(1 for s in self._batch_states if s.needs_review)
            self._set_progress(
                ScanLifecycle.READY,
                phase="Discovery complete",
                message=(
                    f"Found {len(self._batch_states)} shows"
                    + (f" — {needs_review} need review" if needs_review else "")
                    + " — scanning episodes..."
                ),
            )
            self._notify("library_changed", self._batch_states)
            self._notify("scan_complete", None)
            self._finish_scan_operation(cancel_event)

        threading.Thread(target=_worker, daemon=True, name="TVBatchDiscovery").start()

    def scan_all_shows(self) -> None:
        """Phase 2: scan episodes for all unscanned shows in batch mode.

        Spawns a background thread.  Fires ``on_progress`` per show and
        ``on_library_changed`` on completion.
        """
        orchestrator = self._batch_orchestrator
        if orchestrator is None:
            return

        unscanned = [
            s for s in self._batch_states
            if not s.scanned and not s.queued and s.show_id is not None
        ]
        if not unscanned:
            return

        self._set_progress(
            ScanLifecycle.SCANNING,
            phase="Scanning episodes...",
            message="Scanning episodes...",
        )
        cancel_event = self._begin_scan_operation()

        def _progress(done: int, total: int) -> None:
            if cancel_event.is_set():
                raise ScanCancelledError("Scan cancelled")
            current_name = ""
            to_scan = [
                s for s in self._batch_states
                if not s.scanned and not s.queued and s.show_id is not None
            ]
            if 0 < done <= len(to_scan):
                current_name = to_scan[done - 1].display_name
            self._set_progress(
                ScanLifecycle.SCANNING,
                phase="Scanning episodes...",
                done=done,
                total=total,
                current_item=current_name or None,
                message=f"Scanning episodes... {done}/{total}"
                        + (f" — {current_name}" if current_name else ""),
            )

        def _worker() -> None:
            try:
                orchestrator.scan_all(
                    progress_callback=_progress,
                    cancel_event=cancel_event,
                )
            except ScanCancelledError:
                if not self._is_current_scan_operation(cancel_event):
                    return
                for state in self._batch_states:
                    if self._command_gating.is_plex_ready_state(state):
                        state.checked = False

                scanned = sum(1 for s in self._batch_states if s.scanned)
                total_files = sum(s.file_count for s in self._batch_states if s.scanned)
                self._set_progress(
                    ScanLifecycle.CANCELLED,
                    phase="Batch scan cancelled",
                    message=f"Cancelled after scanning {scanned} show(s) — {total_files} total files",
                )
                self._notify("library_changed", self._batch_states)
                self._finish_scan_operation(cancel_event)
                return
            except Exception as e:
                if not self._is_current_scan_operation(cancel_event):
                    return
                _log.exception("Batch scan failed: %s", e)
                self._finish_scan_operation(cancel_event)
                return

            if not self._is_current_scan_operation(cancel_event):
                return

            # Mark Plex-ready shows as unchecked
            for state in self._batch_states:
                if self._command_gating.is_plex_ready_state(state):
                    state.checked = False

            scanned = sum(1 for s in self._batch_states if s.scanned)
            total_files = sum(s.file_count for s in self._batch_states if s.scanned)
            self._set_progress(
                ScanLifecycle.READY,
                phase="Batch scan complete",
                message=f"Scanned {scanned} shows — {total_files} total files",
            )
            self._notify("library_changed", self._batch_states)
            self._finish_scan_operation(cancel_event)

        threading.Thread(target=_worker, daemon=True, name="TVBatchScan").start()

    def scan_show(self, state: ScanState, tmdb: Any) -> None:
        """Scan a single show's episodes in a background thread."""
        if state.scanner is None:
            state.scanner = TVScanner(tmdb, state.media_info, state.folder,
                                      season_hint=state.season_assignment)

        self._set_progress(
            ScanLifecycle.SCANNING,
            phase="Scanning TV files...",
            message=f"Scanning {state.display_name}...",
        )

        def _worker() -> None:
            try:
                state.scanning = True
                self._notify("library_changed", self.library_states)
                items, _need_review = state.scanner.scan()
                state.preview_items = items
                state.scanned = True
            except Exception as e:
                _log.exception("Single-show scan failed: %s", e)
            finally:
                state.scanning = False

            self._set_progress(
                ScanLifecycle.READY,
                phase="TV scan complete",
                message=f"Preview ready — {len(state.preview_items)} file(s)",
            )
            self._notify("library_changed", self.library_states)
            self._notify("scan_complete", state)

        threading.Thread(target=_worker, daemon=True, name="TVShowScan").start()

    def select_show(self, index: int) -> ScanState | None:
        """Change the selected show in the roster.  Returns the state."""
        states = self.library_states
        if index < 0 or index >= len(states):
            return None
        self._library_selected_index = index
        if self._active_content_mode == MediaType.TV:
            self._active_scan = states[index]
        return states[index]

    # ── Movie session methods ───────────────────────────────────────

    def start_movie_batch(
        self,
        folder: Path,
        tmdb: Any,
    ) -> None:
        """Discover and scan movies.  Spawns a background thread.

        Fires ``on_progress`` during scanning and ``on_library_changed``
        when items are populated.
        """
        self._active_content_mode = MediaType.MOVIE
        self._active_library_mode = MediaType.MOVIE
        self._movie_folder = folder
        self._movie_scanner = MovieScanner(tmdb, folder)
        self._movie_preview_items = []
        self._movie_library_states = []
        self._movie_media_info = {"_type": "movie_batch", "_media_type": MediaType.MOVIE}
        self._library_selected_index = None

        self._set_progress(
            ScanLifecycle.SCANNING,
            phase="Scanning movies...",
            message="Scanning movies...",
        )
        self._notify("mode_changed", self._active_content_mode, self._active_library_mode)

        scanner = self._movie_scanner
        cancel_event = self._begin_scan_operation()

        def _worker() -> None:
            try:
                items = scanner.scan(cancel_event=cancel_event)
            except ScanCancelledError:
                if not self._is_current_scan_operation(cancel_event):
                    return
                self._movie_preview_items = []
                self._movie_library_states = []
                self._library_selected_index = None
                self._set_progress(
                    ScanLifecycle.CANCELLED,
                    phase="Movie scan cancelled",
                    message="Movie scan cancelled.",
                )
                self._notify("library_changed", self._movie_library_states)
                self._finish_scan_operation(cancel_event)
                return
            except Exception as e:
                if not self._is_current_scan_operation(cancel_event):
                    return
                _log.exception("Movie batch scan failed: %s", e)
                self._set_progress(
                    ScanLifecycle.FAILED,
                    phase="Scan failed.",
                    message=f"Movie scan failed: {e}",
                )
                self._finish_scan_operation(cancel_event)
                return

            if not self._is_current_scan_operation(cancel_event):
                return

            self._movie_preview_items = items
            self._build_movie_library_states(items, scanner)
            self.sync_queued_states()

            if not items:
                self._set_progress(
                    ScanLifecycle.WARNING,
                    phase="No movie files found",
                    message="No movie files found",
                )
            else:
                self._set_progress(
                    ScanLifecycle.READY,
                    phase="Movie scan complete",
                    message=f"Found {len(items)} movie file(s)",
                )

            self._notify("library_changed", self._movie_library_states)
            self._notify("scan_complete", None)
            self._finish_scan_operation(cancel_event)

        threading.Thread(target=_worker, daemon=True, name="MovieBatchScan").start()

    def _build_movie_library_states(self, items: list[PreviewItem], scanner: MovieScanner) -> None:
        """Build per-movie ScanState entries from a flat list of PreviewItems."""
        states: list[ScanState] = []
        for item in items:
            if item.media_type != MediaType.MOVIE:
                continue

            chosen = scanner.movie_info.get(item.original, {})
            media_id = chosen.get("id", item.media_id)
            media_info = {
                "id": media_id,
                "title": chosen.get("title") or item.media_name or item.original.stem,
                "year": chosen.get("year", ""),
                "poster_path": chosen.get("poster_path"),
                "overview": chosen.get("overview", ""),
                "_media_type": MediaType.MOVIE,
            }
            confidence = 1.0 if media_id else 0.0
            if item.status.startswith("REVIEW"):
                confidence = 0.5 if media_id else 0.0
            state = ScanState(
                folder=item.original.parent,
                media_info=media_info,
                preview_items=[item],
                confidence=confidence,
                search_results=scanner.get_search_results(item.original),
                alternate_matches=scanner.get_search_results(item.original)[1:4],
                scanned=True,
                checked=item.is_actionable,
                scanner=scanner,
            )
            states.append(state)
        self._apply_movie_duplicate_labels(states)
        self._movie_library_states = states

    def _apply_movie_duplicate_labels(self, states: list[ScanState]) -> None:
        for state in states:
            state.duplicate_of = None
            state.duplicate_of_relative_folder = None

        groups: dict[int, list[ScanState]] = {}
        for state in states:
            media_id = state.show_id
            if media_id is None:
                continue
            groups.setdefault(media_id, []).append(state)

        for group in groups.values():
            if len(group) < 2:
                continue
            group.sort(key=self._movie_duplicate_priority)
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
                state.duplicate_of_relative_folder = self._movie_state_relative_folder(existing)
                state.checked = False

    def _movie_duplicate_priority(self, state: ScanState) -> tuple[int, float, int, str, str]:
        item = state.preview_items[0] if state.preview_items else None
        ready_rank = 0 if item is not None and not item.is_actionable else 1
        relative_folder = self._movie_state_relative_folder(state)
        depth = len(PurePosixPath(relative_folder.replace("\\", "/")).parts)
        original_name = item.original.name.casefold() if item is not None else state.folder.name.casefold()
        return (
            ready_rank,
            -state.confidence,
            depth,
            relative_folder.replace("\\", "/").casefold(),
            original_name,
        )

    def _movie_state_relative_folder(self, state: ScanState) -> str:
        try:
            return state.folder.relative_to(self._movie_folder).as_posix() if self._movie_folder is not None else state.folder.as_posix()
        except ValueError:
            return state.folder.as_posix()

    def approve_match(self, state: ScanState) -> None:
        """Accept the current TMDB match as manually approved, clearing needs-review."""
        if state.show_id is None:
            return
        state.match_origin = "manual"
        state.checked = True
        self._notify("library_changed", self.library_states)

    def assign_season(self, state: ScanState, season_num: int | None) -> None:
        """Assign (or clear) a season number on a state and recompute duplicates."""
        state.season_assignment = season_num
        if self._batch_orchestrator is not None:
            self._batch_orchestrator._apply_duplicate_labels()
        elif self._movie_library_states:
            self._apply_movie_duplicate_labels(self._movie_library_states)
        self._notify("library_changed", self.library_states)

    def rematch_tv_state(self, state: ScanState, new_match: dict) -> None:
        """Apply a new TMDB match to a TV scan state and clear stale scan data."""
        state.match_origin = "manual"
        orchestrator = self._batch_orchestrator
        if orchestrator is not None:
            orchestrator.rematch_show(state, new_match)
        else:
            state.media_info = new_match
            raw_name = clean_folder_name(state.folder.name)
            year_hint = extract_year(state.folder.name)
            scored = score_results([new_match], raw_name, year_hint, title_key="name")
            state.confidence = scored[0][1] if scored else 0.0
            state.reset_scan()

        raw_name = clean_folder_name(state.folder.name)
        year_hint = extract_year(state.folder.name)
        scored = score_results(state.search_results, raw_name, year_hint, title_key="name")
        state.alternate_matches = pick_alternate_matches(
            scored,
            selected_id=state.media_info.get("id"),
            limit=3,
        )
        state.checked = state.show_id is not None and not state.needs_review
        self._notify("library_changed", self.library_states)

    def rematch_movie_state(self, state: ScanState, new_match: dict) -> None:
        """Apply a new TMDB match to a movie scan state and rebuild its preview."""
        preview = state.preview_items[0] if state.preview_items else None
        scanner = state.scanner or self._movie_scanner
        if (
            preview is None
            or scanner is None
            or not hasattr(scanner, "rematch_file")
            or not hasattr(scanner, "get_search_results")
        ):
            raise ValueError("Movie rematch requires an existing preview item and scanner")

        new_item = scanner.rematch_file(preview, new_match)
        raw_name = clean_folder_name(preview.original.stem)
        year_hint = extract_year(preview.original.stem)
        scored = score_results(scanner.get_search_results(preview.original), raw_name, year_hint, title_key="title")

        state.media_info = {
            "id": new_match.get("id"),
            "title": new_match.get("title") or preview.media_name or preview.original.stem,
            "year": new_match.get("year", ""),
            "poster_path": new_match.get("poster_path"),
            "overview": new_match.get("overview", ""),
            "_media_type": MediaType.MOVIE,
        }
        state.match_origin = "manual"
        state.preview_items = [new_item]
        state.search_results = scanner.get_search_results(preview.original)
        state.alternate_matches = [
            result
            for result, score in scored
            if result.get("id") != state.media_info.get("id") and score > 0.3
        ][:3]
        state.confidence = scored[0][1] if scored and scored[0][0].get("id") == state.media_info.get("id") else 1.0
        state.scanned = True
        state.checked = new_item.is_actionable
        state.selected_index = 0 if state.preview_items else None

        for index, item in enumerate(self._movie_preview_items):
            if item.original == preview.original:
                self._movie_preview_items[index] = new_item
                break

        self._notify("library_changed", self.library_states)

    # ── Session save/restore ────────────────────────────────────────

    def snapshot_tv_for_tab_switch(self) -> dict:
        """Snapshot current TV session state for tab switching (in-memory only)."""
        return {
            "batch_mode": self._batch_mode,
            "batch_states": self._batch_states,
            "active_scan": self._active_scan,
            "batch_orchestrator": self._batch_orchestrator,
            "tv_root_folder": self._tv_root_folder,
            "library_selected_index": self._library_selected_index,
        }

    def restore_tv_from_tab_switch(self, snapshot: dict) -> None:
        """Restore TV session from an in-memory tab-switch snapshot."""
        self._batch_mode = snapshot.get("batch_mode", False)
        self._batch_states = snapshot.get("batch_states", [])
        self._active_scan = snapshot.get("active_scan")
        self._batch_orchestrator = snapshot.get("batch_orchestrator")
        self._tv_root_folder = snapshot.get("tv_root_folder")
        self._library_selected_index = snapshot.get("library_selected_index")
        self._active_content_mode = MediaType.TV
        self._active_library_mode = MediaType.TV
        self.sync_queued_states()
        self._notify("mode_changed", self._active_content_mode, self._active_library_mode)
        self._notify("library_changed", self._batch_states)

    def snapshot_movie_for_tab_switch(self) -> dict:
        """Snapshot current movie session state for tab switching (in-memory only)."""
        return {
            "movie_library_states": self._movie_library_states,
            "movie_preview_items": self._movie_preview_items,
            "movie_scanner": self._movie_scanner,
            "movie_folder": self._movie_folder,
            "movie_media_info": self._movie_media_info,
            "library_selected_index": self._library_selected_index,
        }

    def restore_movie_from_tab_switch(self, snapshot: dict) -> None:
        """Restore movie session from an in-memory tab-switch snapshot."""
        self._movie_library_states = snapshot.get("movie_library_states", [])
        self._movie_preview_items = snapshot.get("movie_preview_items", [])
        self._movie_scanner = snapshot.get("movie_scanner")
        self._movie_folder = snapshot.get("movie_folder")
        self._movie_media_info = snapshot.get("movie_media_info")
        self._library_selected_index = snapshot.get("library_selected_index")
        self._active_content_mode = MediaType.MOVIE
        self._active_library_mode = MediaType.MOVIE
        self.sync_queued_states()
        self._notify("mode_changed", self._active_content_mode, self._active_library_mode)
        self._notify("library_changed", self._movie_library_states)

    # ── Query methods ───────────────────────────────────────────────

    def sync_queued_states(self) -> None:
        """Refresh queued flags for TV and movie rosters from the job store."""
        queued_keys = {
            (job.media_type, job.tmdb_id)
            for job in self._job_store.get_queue()
            if job.tmdb_id
        }

        for state in self._batch_states:
            if state.duplicate_of is not None:
                state.queued = False
                continue
            state.queued = (MediaType.TV, state.show_id or 0) in queued_keys

        for state in self._movie_library_states:
            if state.duplicate_of is not None:
                state.queued = False
                continue
            state.queued = (MediaType.MOVIE, state.show_id or 0) in queued_keys
