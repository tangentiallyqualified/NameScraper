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

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ...constants import MediaType
from ...engine import (
    BatchTVOrchestrator,
    check_duplicates,
    MovieScanner,
    PreviewItem,
    ScanState,
    set_auto_accept_threshold,
    set_episode_auto_accept_threshold,
    pick_alternate_matches,
    score_results,
    score_tv_results,
    TVScanner,
)
from ...parsing import best_tv_match_title, clean_folder_name, extract_year
from ...job_store import JobStore
from ._controller_lifecycle_workflow import MediaControllerLifecycleWorkflow
from ._controller_match_helpers import (
    approve_controller_match,
)
from ._controller_projection_workflow import MediaControllerProjectionWorkflow
from ._controller_movie_workflows import MediaControllerMovieWorkflow
from ._controller_session_models import (
    ControllerModeState,
    MovieControllerSession,
    TVControllerSession,
)
from ._controller_tv_workflows import MediaControllerTVWorkflow
from ._controller_state_helpers import (
    routed_library_states,
    select_library_show,
)
from ._controller_event_helpers import (
    ListenerEntry,
    add_controller_listener,
    apply_runtime_settings_to_states,
    notify_controller_listeners,
)
from ..models import ScanLifecycle, ScanProgress
from ..services.cache_service import PersistentCacheService
from ..services.command_gating_service import CommandGatingService
from ..services.refresh_policy_service import RefreshPolicyService
from ..services.settings_service import SettingsService
from ..services.tv_library_discovery_service import TVLibraryDiscoveryService
from ..services.movie_library_discovery_service import MovieLibraryDiscoveryService


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
        set_episode_auto_accept_threshold(self._settings.episode_auto_accept_threshold)

        self._mode_state = ControllerModeState()
        self._tv_session = TVControllerSession()
        self._movie_session = MovieControllerSession()
        self._tv_workflow = MediaControllerTVWorkflow(self)
        self._movie_workflow = MediaControllerMovieWorkflow(self)
        self._projection_workflow = MediaControllerProjectionWorkflow(self)

        # ── Listeners ───────────────────────────────────────────────
        self._listeners: list[ListenerEntry] = []
        self._lifecycle_workflow = MediaControllerLifecycleWorkflow(self)

    @property
    def _active_content_mode(self) -> MediaType:
        return self._mode_state.active_content_mode

    @_active_content_mode.setter
    def _active_content_mode(self, value: MediaType) -> None:
        self._mode_state.active_content_mode = value

    @property
    def _active_library_mode(self) -> MediaType | None:
        return self._mode_state.active_library_mode

    @_active_library_mode.setter
    def _active_library_mode(self, value: MediaType | None) -> None:
        self._mode_state.active_library_mode = value

    @property
    def _library_selected_index(self) -> int | None:
        return self._mode_state.library_selected_index

    @_library_selected_index.setter
    def _library_selected_index(self, value: int | None) -> None:
        self._mode_state.library_selected_index = value

    @property
    def _batch_mode(self) -> bool:
        return self._tv_session.batch_mode

    @_batch_mode.setter
    def _batch_mode(self, value: bool) -> None:
        self._tv_session.batch_mode = value

    @property
    def _batch_states(self) -> list[ScanState]:
        return self._tv_session.batch_states

    @_batch_states.setter
    def _batch_states(self, value: list[ScanState]) -> None:
        self._tv_session.batch_states = value

    @property
    def _active_scan(self) -> ScanState | None:
        return self._tv_session.active_scan

    @_active_scan.setter
    def _active_scan(self, value: ScanState | None) -> None:
        self._tv_session.active_scan = value

    @property
    def _batch_orchestrator(self) -> BatchTVOrchestrator | None:
        return self._tv_session.batch_orchestrator

    @_batch_orchestrator.setter
    def _batch_orchestrator(self, value: BatchTVOrchestrator | None) -> None:
        self._tv_session.batch_orchestrator = value

    @property
    def _tv_root_folder(self) -> Path | None:
        return self._tv_session.root_folder

    @_tv_root_folder.setter
    def _tv_root_folder(self, value: Path | None) -> None:
        self._tv_session.root_folder = value

    @property
    def _movie_library_states(self) -> list[ScanState]:
        return self._movie_session.library_states

    @_movie_library_states.setter
    def _movie_library_states(self, value: list[ScanState]) -> None:
        self._movie_session.library_states = value

    @property
    def _movie_preview_items(self) -> list[PreviewItem]:
        return self._movie_session.preview_items

    @_movie_preview_items.setter
    def _movie_preview_items(self, value: list[PreviewItem]) -> None:
        self._movie_session.preview_items = value

    @property
    def _movie_scanner(self) -> MovieScanner | None:
        return self._movie_session.scanner

    @_movie_scanner.setter
    def _movie_scanner(self, value: MovieScanner | None) -> None:
        self._movie_session.scanner = value

    @property
    def _movie_folder(self) -> Path | None:
        return self._movie_session.folder

    @_movie_folder.setter
    def _movie_folder(self, value: Path | None) -> None:
        self._movie_session.folder = value

    @property
    def _movie_media_info(self) -> dict[str, Any] | None:
        return self._movie_session.media_info

    @_movie_media_info.setter
    def _movie_media_info(self, value: dict[str, Any] | None) -> None:
        self._movie_session.media_info = value

    @property
    def _scan_progress(self) -> ScanProgress:
        return self._lifecycle_workflow.scan_progress

    @_scan_progress.setter
    def _scan_progress(self, value: ScanProgress) -> None:
        self._lifecycle_workflow.scan_progress = value

    # ── Listener management ─────────────────────────────────────────

    def add_listener(
        self,
        on_library_changed: Callable[[list[ScanState]], None] | None = None,
        on_progress: Callable[[ScanProgress], None] | None = None,
        on_scan_complete: Callable[[ScanState | None], None] | None = None,
        on_mode_changed: Callable[[MediaType, MediaType | None], None] | None = None,
    ) -> int:
        """Register a listener.  Returns listener index."""
        return add_controller_listener(
            self._listeners,
            on_library_changed=on_library_changed,
            on_progress=on_progress,
            on_scan_complete=on_scan_complete,
            on_mode_changed=on_mode_changed,
        )

    def clear_listeners(self) -> None:
        self._listeners.clear()

    def _notify(self, event: str, *args: Any) -> None:
        notify_controller_listeners(self._listeners, event, *args)

    # ── Properties ──────────────────────────────────────────────────

    @property
    def active_content_mode(self) -> MediaType:
        return self._mode_state.active_content_mode

    @property
    def active_library_mode(self) -> MediaType | None:
        return self._mode_state.active_library_mode

    @property
    def library_states(self) -> list[ScanState]:
        """Routed roster: returns TV batch_states or movie_library_states."""
        return routed_library_states(self)

    @property
    def active_scan(self) -> ScanState | None:
        return self._tv_session.active_scan

    @active_scan.setter
    def active_scan(self, value: ScanState | None) -> None:
        self._tv_session.active_scan = value

    @property
    def scan_progress(self) -> ScanProgress:
        return self._lifecycle_workflow.scan_progress

    @property
    def batch_mode(self) -> bool:
        return self._tv_session.batch_mode

    @property
    def batch_states(self) -> list[ScanState]:
        return self._tv_session.batch_states

    @property
    def batch_orchestrator(self) -> BatchTVOrchestrator | None:
        return self._tv_session.batch_orchestrator

    @property
    def tv_root_folder(self) -> Path | None:
        return self._tv_session.root_folder

    @property
    def movie_folder(self) -> Path | None:
        return self._movie_session.folder

    @property
    def movie_library_states(self) -> list[ScanState]:
        return self._movie_session.library_states

    @property
    def movie_preview_items(self) -> list[PreviewItem]:
        return self._movie_session.preview_items

    @property
    def movie_scanner(self) -> MovieScanner | None:
        return self._movie_session.scanner

    @property
    def movie_media_info(self) -> dict | None:
        return self._movie_session.media_info

    @property
    def library_selected_index(self) -> int | None:
        return self._mode_state.library_selected_index

    @library_selected_index.setter
    def library_selected_index(self, value: int | None) -> None:
        self._mode_state.library_selected_index = value

    @property
    def command_gating(self) -> CommandGatingService:
        return self._command_gating

    @property
    def settings(self) -> SettingsService:
        return self._settings

    def apply_runtime_settings(self) -> None:
        """Apply settings that directly affect scan/review semantics."""
        apply_runtime_settings_to_states(
            self._settings.auto_accept_threshold,
            self._settings.episode_auto_accept_threshold,
            (*self._batch_states, *self._movie_library_states),
        )
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
        self._lifecycle_workflow.set_progress(
            lifecycle,
            phase=phase,
            done=done,
            total=total,
            current_item=current_item,
            message=message,
        )

    def _begin_scan_operation(self) -> threading.Event:
        return self._lifecycle_workflow.begin_scan_operation()

    def _is_current_scan_operation(self, event: threading.Event) -> bool:
        return self._lifecycle_workflow.is_current_scan_operation(event)

    def _finish_scan_operation(self, event: threading.Event) -> None:
        self._lifecycle_workflow.finish_scan_operation(event)

    def cancel_scan(self) -> bool:
        return self._lifecycle_workflow.cancel_scan()

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
        return self._tv_workflow.accept_show(
            folder,
            tmdb,
            show_info,
            scanner_factory=TVScanner,
        )

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
        self._tv_workflow.start_batch(folder, tmdb)

    def scan_all_shows(self) -> None:
        """Phase 2: scan episodes for all unscanned shows in batch mode.

        Spawns a background thread.  Fires ``on_progress`` per show and
        ``on_library_changed`` on completion.
        """
        self._tv_workflow.scan_all_shows()

    def scan_show(self, state: ScanState, tmdb: Any) -> None:
        """Scan a single show's episodes in a background thread."""
        self._tv_workflow.scan_show(
            state,
            tmdb,
            scanner_factory=TVScanner,
            duplicate_checker=check_duplicates,
        )

    def select_show(self, index: int) -> ScanState | None:
        """Change the selected show in the roster.  Returns the state."""
        return select_library_show(self, index)

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
        self._movie_workflow.start_batch(
            folder,
            tmdb,
            scanner_factory=MovieScanner,
        )

    def _build_movie_library_states(self, items: list[PreviewItem], scanner: MovieScanner) -> None:
        """Build per-movie ScanState entries from a flat list of PreviewItems."""
        self._movie_workflow.build_library_states(items, scanner)

    def approve_match(self, state: ScanState) -> None:
        """Accept the current TMDB match as manually approved, clearing needs-review."""
        approve_controller_match(self, state)

    def assign_season(self, state: ScanState, season_num: int | None) -> ScanState:
        """Assign (or clear) a season number on a state and recompute duplicates.

        In batch TV mode, an assignment that gives the state a concrete season
        triggers consolidation into any sibling ScanState matching the same
        show — so a user who rematches a show-root folder and then assigns a
        season sees that folder absorbed into the existing show card rather
        than left as a parallel entry.
        """
        return self._tv_workflow.assign_season(state, season_num)

    def rematch_tv_state(self, state: ScanState, new_match: dict, tmdb: Any | None = None) -> ScanState:
        """Apply a new TMDB match to a TV scan state and clear stale scan data."""
        return self._tv_workflow.rematch_state(
            state,
            new_match,
            tmdb=tmdb,
            best_tv_match_title=best_tv_match_title,
            extract_year=extract_year,
            score_tv_results=score_tv_results,
            score_results=score_results,
            pick_alternate_matches=pick_alternate_matches,
        )

    def rematch_movie_state(self, state: ScanState, new_match: dict) -> None:
        """Apply a new TMDB match to a movie scan state and rebuild its preview."""
        self._movie_workflow.rematch_state(
            state,
            new_match,
            clean_folder_name=clean_folder_name,
            extract_year=extract_year,
            score_results=score_results,
        )

    # ── Session save/restore ────────────────────────────────────────

    def snapshot_tv_for_tab_switch(self) -> dict:
        """Snapshot current TV session state for tab switching (in-memory only)."""
        return self._tv_workflow.snapshot_for_tab_switch()

    def restore_tv_from_tab_switch(self, snapshot: dict) -> None:
        """Restore TV session from an in-memory tab-switch snapshot."""
        self._tv_workflow.restore_from_tab_switch(snapshot)

    def snapshot_movie_for_tab_switch(self) -> dict:
        """Snapshot current movie session state for tab switching (in-memory only)."""
        return self._movie_workflow.snapshot_for_tab_switch()

    def restore_movie_from_tab_switch(self, snapshot: dict) -> None:
        """Restore movie session from an in-memory tab-switch snapshot."""
        self._movie_workflow.restore_from_tab_switch(snapshot)

    def apply_completed_job_to_state(self, job, result) -> bool:
        """Project a completed rename job back into the in-memory scan state."""
        del result
        return self._projection_workflow.apply_completed_job_to_state(job)

    # ── Query methods ───────────────────────────────────────────────

    def sync_queued_states(self) -> None:
        """Refresh queued flags for TV and movie rosters from the job store."""
        self._projection_workflow.sync_queued_states()
