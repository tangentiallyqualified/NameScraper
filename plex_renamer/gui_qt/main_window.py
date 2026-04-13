"""Main application window — Phase 3 shell.

Owns the menu bar, tab bar, and status bar.  Tab content widgets are
created here but their internal logic lives in their own modules.

Controller wiring: MainWindow registers a MediaController listener
that marshals progress/completion callbacks from worker threads to
the main thread via Qt signals, then forwards them to the active
workspace widget.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QMainWindow,
    QMessageBox,
)

from ..app.models import ScanProgress
from ..app.services.cache_service import PersistentCacheService
from ..app.services.command_gating_service import CommandGatingService
from ..app.services.refresh_policy_service import RefreshPolicyService
from ..app.services.settings_service import SettingsService
from ..app.controllers.queue_controller import QueueController
from ..app.controllers.media_controller import MediaController
from ..engine import RenameResult
from ..job_store import JobStore
from ..job_store import RenameJob
from ..tmdb import TMDBClient
from ..keys import get_api_key
from ..thread_pool import submit as _submit_bg

from ._main_window_bridges import install_controller_bridge, install_queue_bridge
from ._main_window_chrome import MainWindowChromeCoordinator
from ._main_window_feedback import MainWindowFeedbackCoordinator
from ._main_window_scan import MainWindowScanCoordinator
from ._main_window_shell import MainWindowShellCoordinator
from ._main_window_shortcuts import MainWindowShortcutCoordinator
from ._main_window_state import MainWindowStateCoordinator
from ._main_window_tabs import MainWindowTabsCoordinator
from ._main_window_tmdb import MainWindowTmdbCoordinator
from .widgets.media_workspace import MediaWorkspace
from .widgets.toast_manager import ToastManager

_log = logging.getLogger(__name__)

# Tab indices
_TV = 0
_MOVIES = 1
_QUEUE = 2
_HISTORY = 3
_SETTINGS = 4
TMDB_CACHE_NAMESPACE = "tmdb"
TMDB_CACHE_SNAPSHOT_KEY = "client_snapshot"


class MainWindow(QMainWindow):
    """Top-level window with menu bar, tab bar, and status bar."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Plex Renamer")
        self.setMinimumSize(960, 600)
        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().hide()

        # ── TMDB client (lazily created) ─────────────────────────
        self._tmdb: TMDBClient | None = None
        self._tv_snapshot: dict | None = None
        self._movie_snapshot: dict | None = None
        self._tmdb_coordinator = MainWindowTmdbCoordinator(
            self,
            cache_namespace=TMDB_CACHE_NAMESPACE,
            snapshot_key=TMDB_CACHE_SNAPSHOT_KEY,
        )
        self._chrome_coordinator = MainWindowChromeCoordinator(
            self,
            settings_index=_SETTINGS,
        )
        self._feedback_coordinator = MainWindowFeedbackCoordinator(
            self,
            queue_index=_QUEUE,
            history_index=_HISTORY,
        )
        self._shell_coordinator = MainWindowShellCoordinator(
            self,
            tv_index=_TV,
            movies_index=_MOVIES,
            history_index=_HISTORY,
        )
        self._state_coordinator = MainWindowStateCoordinator(
            self,
            tv_index=_TV,
            movies_index=_MOVIES,
            queue_index=_QUEUE,
            history_index=_HISTORY,
            logger=_log,
        )
        self._scan_coordinator = MainWindowScanCoordinator(
            self,
            tv_index=_TV,
            movies_index=_MOVIES,
        )
        self._shortcut_coordinator = MainWindowShortcutCoordinator(
            self,
            tv_index=_TV,
            movies_index=_MOVIES,
            queue_index=_QUEUE,
        )
        self._tabs_coordinator = MainWindowTabsCoordinator(
            self,
            tv_index=_TV,
            movies_index=_MOVIES,
            queue_index=_QUEUE,
            history_index=_HISTORY,
        )

        # ── Services and controllers ─────────────────────────────
        self.settings_service = SettingsService()
        self._job_store = JobStore()
        self._command_gating = CommandGatingService()
        self._refresh_policy = RefreshPolicyService()
        self._cache_service = PersistentCacheService(refresh_policy=self._refresh_policy)

        self.queue_ctrl = QueueController(self._job_store)
        self.media_ctrl = MediaController(
            job_store=self._job_store,
            command_gating=self._command_gating,
            settings=self.settings_service,
            cache_service=self._cache_service,
            refresh_policy=self._refresh_policy,
        )

        # ── Controller → Qt bridge ───────────────────────────────
        self._bridge = install_controller_bridge(self)
        self._queue_bridge = install_queue_bridge(self)

        # ── Tab widget ───────────────────────────────────────────
        self._tabs_coordinator.build_tab_widget()
        self._toast_manager = ToastManager(self)
        self._queue_run_started = False
        self._queue_completed_count = 0
        self._queue_failed_count = 0
        self._pending_success_jobs = 0
        self._pending_success_files = 0
        self._job_poster_backfill_started = False
        self._job_poster_backfill_future = None
        self._tv_needs_queue_refresh = False
        self._movie_needs_queue_refresh = False
        self._scan_feedback_token: tuple[str, str] | None = None
        self._success_toast_timer = QTimer(self)
        self._success_toast_timer.setSingleShot(True)
        self._success_toast_timer.setInterval(350)
        self._success_toast_timer.timeout.connect(self._flush_success_toast_batch)

        # ── Tab content ──────────────────────────────────────────
        self._tabs_coordinator.build_tab_content()

        # ── Menu bar ─────────────────────────────────────────────
        self._build_menu_bar()

        # ── Keyboard shortcuts ───────────────────────────────────
        self._build_shortcuts()

        # ── Signals ──────────────────────────────────────────────
        self._tabs_coordinator.connect_signals()

        # ── Restore geometry ─────────────────────────────────────
        self._tabs_coordinator.apply_initial_state(schedule_single_shot=QTimer.singleShot)

    # ── TMDB client ──────────────────────────────────────────────

    def _ensure_tmdb(self) -> TMDBClient | None:
        return self._tmdb_coordinator.ensure_tmdb(
            api_key_lookup=get_api_key,
            tmdb_client_factory=TMDBClient,
        )

    def _restore_tmdb_cache_snapshot(self) -> None:
        self._tmdb_coordinator.restore_tmdb_cache_snapshot()

    def _persist_tmdb_cache_snapshot(self) -> None:
        self._tmdb_coordinator.persist_tmdb_cache_snapshot()

    def _invalidate_tmdb(self) -> None:
        self._tmdb_coordinator.invalidate_tmdb()

    def _drop_tmdb_client(self) -> None:
        self._tmdb_coordinator.drop_tmdb_client()

    def _clear_history_from_settings(self) -> tuple[int, int]:
        """Clear job history; returns (total_cleared, revertible_count)."""
        jobs = self.queue_ctrl.get_history()
        revertible = sum(1 for j in jobs if j.status == "completed" and j.undo_data)
        count = self.queue_ctrl.clear_history()
        self._history_tab.refresh()
        return count, revertible

    def _start_job_poster_backfill(self):
        return self._feedback_coordinator.start_job_poster_backfill(
            api_key_lookup=get_api_key,
            submit_bg=_submit_bg,
            logger=_log,
        )

    def _on_poster_backfill_finished(self, updated: int) -> None:
        self._feedback_coordinator.on_poster_backfill_finished(updated)

    def _refresh_media_workspaces(self) -> None:
        self._state_coordinator.refresh_media_workspaces()

    def _apply_view_mode(self, mode: str) -> None:
        self._state_coordinator.apply_view_mode(mode)

    def _apply_companion_visibility(self, checked: bool) -> None:
        self._state_coordinator.apply_companion_visibility(checked)

    def _apply_discovery_visibility(self, checked: bool) -> None:
        self._state_coordinator.apply_discovery_visibility(checked)

    def _on_language_changed(self, tag: str) -> None:
        self._state_coordinator.on_language_changed(tag)

    def _on_threshold_changed(self, value: float) -> None:
        self._state_coordinator.on_threshold_changed(value)

    # ── Menu bar ─────────────────────────────────────────────────

    def _build_menu_bar(self) -> None:
        self._chrome_coordinator.build_menu_bar()

    def _build_shortcuts(self) -> None:
        """Register keyboard shortcuts that aren't menu-bound."""
        self._chrome_coordinator.build_shortcuts()

    # ── Folder selection → controller scan ───────────────────────

    def _on_tv_folder_selected(self, path: str) -> None:
        self.settings_service.add_recent_tv_folder(path)
        self._rebuild_recent_menus()
        self._start_tv_scan(path)

    def _on_movie_folder_selected(self, path: str) -> None:
        self.settings_service.add_recent_movie_folder(path)
        self._rebuild_recent_menus()
        self._start_movie_scan(path)

    def _start_tv_scan(self, path: str) -> None:
        self._scan_coordinator.start_tv_scan(path)

    def _start_movie_scan(self, path: str) -> None:
        self._scan_coordinator.start_movie_scan(path)

    def _active_media_workspace_for_shortcuts(self) -> MediaWorkspace | None:
        return self._shortcut_coordinator.active_media_workspace()

    def _queue_selected_from_shortcut(self) -> None:
        self._shortcut_coordinator.queue_selected()

    def _queue_checked_from_shortcut(self) -> None:
        self._shortcut_coordinator.queue_checked()

    @staticmethod
    def _text_input_focused() -> bool:
        """Return True if a text input widget currently has focus."""
        return MainWindowShortcutCoordinator.text_input_focused()

    def _toggle_focused_check(self) -> None:
        self._shortcut_coordinator.toggle_focused_check()

    def _on_escape(self) -> None:
        self._shortcut_coordinator.on_escape()

    def _force_rematch_from_shortcut(self) -> None:
        self._shortcut_coordinator.force_rematch()

    def _delete_from_shortcut(self) -> None:
        self._shortcut_coordinator.delete_from_shortcut()

    def _enter_from_shortcut(self) -> None:
        self._shortcut_coordinator.enter_from_shortcut()

    # ── Controller callback handlers (main thread via bridge) ────

    def _active_workspace(self) -> MediaWorkspace:
        """Return the workspace matching the controller's active mode."""
        return self._scan_coordinator.active_workspace()

    def _on_scan_progress(self, progress: ScanProgress) -> None:
        self._scan_coordinator.on_scan_progress(progress)

    def _on_scan_complete(self) -> None:
        self._scan_coordinator.on_scan_complete()

    def _on_library_changed(self) -> None:
        self._scan_coordinator.on_library_changed()

    def _show_scan_feedback(self, *, title: str, message: str, tone: str) -> None:
        self._feedback_coordinator.show_scan_feedback(
            title=title,
            message=message,
            tone=tone,
        )

    def _on_queue_changed(self, _unused=None) -> None:
        self._scan_coordinator.on_queue_changed()

    def _update_media_badges(self, states) -> None:
        self._feedback_coordinator.update_media_badges(states)

    def _refresh_job_views(self) -> None:
        self._feedback_coordinator.refresh_job_views()

    def _on_job_started(self, _job: RenameJob) -> None:
        self._feedback_coordinator.on_job_started(_job)

    def _on_job_completed(self, job: RenameJob, result: RenameResult) -> None:
        self._feedback_coordinator.on_job_completed(job, result)

    def _flush_success_toast_batch(self) -> None:
        self._feedback_coordinator.flush_success_toast_batch()

    def _show_history_job(self, job_id: str) -> None:
        self._switch_to_tab(_HISTORY)
        self._history_tab.select_job(job_id)

    def _on_job_failed(self, job: RenameJob, error: str) -> None:
        self._feedback_coordinator.on_job_failed(job, error)

    def _on_queue_finished(self) -> None:
        self._feedback_coordinator.on_queue_finished()

    # ── Other actions ────────────────────────────────────────────

    def _open_folder(self, media_type: str) -> None:
        self._shell_coordinator.open_folder(media_type)

    def _switch_to_tab(self, index: int) -> None:
        self._state_coordinator.switch_to_tab(index)

    def _rebuild_recent_menus(self) -> None:
        self._state_coordinator.rebuild_recent_menus()

    def _on_tab_changed(self, index: int) -> None:
        self._state_coordinator.on_tab_changed(index)

    def _capture_active_snapshot(self) -> None:
        self._state_coordinator.capture_active_snapshot()

    def _on_undo(self) -> None:
        self._shell_coordinator.undo_last_rename(message_box_api=QMessageBox)

    def _on_compact_toggled(self, checked: bool) -> None:
        self._apply_view_mode("compact" if checked else "normal")

    def _on_companion_toggled(self, checked: bool) -> None:
        self._apply_companion_visibility(checked)

    def _on_about(self) -> None:
        self._shell_coordinator.show_about(message_box_api=QMessageBox)

    # ── Window state persistence ─────────────────────────────────

    def _restore_window_state(self) -> None:
        self._shell_coordinator.restore_window_state()

    def _save_window_state(self) -> None:
        self._shell_coordinator.save_window_state()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._shell_coordinator.handle_resize()

    # ── Close ────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:
        self._shell_coordinator.prepare_close()
        super().closeEvent(event)
