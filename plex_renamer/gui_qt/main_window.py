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
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QTextEdit,
)

from ..app.models import ScanLifecycle, ScanProgress
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
from ._main_window_shell import MainWindowShellCoordinator
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

    def _start_job_poster_backfill(self) -> None:
        self._feedback_coordinator.start_job_poster_backfill(
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
        self._scan_feedback_token = None
        tmdb = self._ensure_tmdb()
        if tmdb is None:
            self._tv_workspace.show_empty()
            return
        self.media_ctrl.start_tv_batch(Path(path), tmdb)

    def _start_movie_scan(self, path: str) -> None:
        self._scan_feedback_token = None
        tmdb = self._ensure_tmdb()
        if tmdb is None:
            self._movie_workspace.show_empty()
            return
        self.media_ctrl.start_movie_batch(Path(path), tmdb)

    def _active_media_workspace_for_shortcuts(self) -> MediaWorkspace | None:
        current = self._tabs.currentIndex()
        if current == _TV:
            return self._tv_workspace
        if current == _MOVIES:
            return self._movie_workspace
        return None

    def _queue_selected_from_shortcut(self) -> None:
        workspace = self._active_media_workspace_for_shortcuts()
        if workspace is not None:
            workspace.queue_selected()

    def _queue_checked_from_shortcut(self) -> None:
        workspace = self._active_media_workspace_for_shortcuts()
        if workspace is not None:
            workspace.queue_checked()

    @staticmethod
    def _text_input_focused() -> bool:
        """Return True if a text input widget currently has focus."""
        focused = QApplication.focusWidget()
        return isinstance(focused, (QLineEdit, QTextEdit))

    def _toggle_focused_check(self) -> None:
        if self._text_input_focused():
            return
        workspace = self._active_media_workspace_for_shortcuts()
        if workspace is not None:
            workspace.toggle_focused_check()

    def _on_escape(self) -> None:
        # First try to cancel a running scan on the active workspace
        workspace = self._active_media_workspace_for_shortcuts()
        if workspace is not None and workspace.cancel_scan():
            return
        # Otherwise dismiss the topmost toast
        self._toast_manager.dismiss_topmost()

    def _force_rematch_from_shortcut(self) -> None:
        if self._text_input_focused():
            return
        workspace = self._active_media_workspace_for_shortcuts()
        if workspace is not None:
            workspace.force_rematch()

    def _delete_from_shortcut(self) -> None:
        if self._text_input_focused():
            return
        if self._tabs.currentIndex() == _QUEUE:
            self._queue_tab.remove_focused_checked()

    def _enter_from_shortcut(self) -> None:
        if self._text_input_focused():
            return
        if self._tabs.currentIndex() == _QUEUE:
            self._queue_tab.execute_focused()

    # ── Controller callback handlers (main thread via bridge) ────

    def _active_workspace(self) -> MediaWorkspace:
        """Return the workspace matching the controller's active mode."""
        mode = self.media_ctrl.active_content_mode
        if mode == "movie":
            return self._movie_workspace
        return self._tv_workspace

    def _on_scan_progress(self, progress: ScanProgress) -> None:
        ws = self._active_workspace()
        ws.scan_progress_widget.update_progress(
            lifecycle=progress.lifecycle,
            phase=progress.phase,
            done=progress.done,
            total=progress.total,
            current_item=progress.current_item or "",
            message=progress.message,
        )
        self.statusBar().showMessage(progress.message, 2000)

    def _on_scan_complete(self) -> None:
        ws = self._active_workspace()
        if self.media_ctrl.scan_progress.lifecycle == ScanLifecycle.CANCELLED:
            ws.scan_progress_widget.stop()
            if self.media_ctrl.library_states:
                ws.show_ready()
            else:
                ws.show_empty()
                self._show_scan_feedback(
                    title="Scan cancelled",
                    message="The scan was cancelled before any results were produced.",
                    tone="accent",
                )
            self.statusBar().showMessage("Scan cancelled", 3000)
            return
        if (
            self.media_ctrl.active_content_mode == "tv"
            and self.media_ctrl.batch_mode
            and any(
                not state.scanned and state.show_id is not None
                for state in self.media_ctrl.batch_states
            )
        ):
            self.media_ctrl.scan_all_shows()
            return

        ws.scan_progress_widget.finish()
        if not ws.is_showing_ready():
            ws.show_ready()
        self._scan_feedback_token = None
        self.statusBar().showMessage("Scan complete", 3000)

    def _on_library_changed(self) -> None:
        ws = self._active_workspace()

        states = self.media_ctrl.library_states
        self._update_media_badges(states)
        needs_tv_bulk_scan = (
            self.media_ctrl.active_content_mode == "tv"
            and self.media_ctrl.batch_mode
            and any(
                not state.scanned and state.show_id is not None
                for state in states
            )
        )

        if self.media_ctrl.scan_progress.lifecycle == ScanLifecycle.READY and states and not needs_tv_bulk_scan:
            ws.scan_progress_widget.finish()
            ws.show_ready()
        elif self.media_ctrl.scan_progress.lifecycle == ScanLifecycle.CANCELLED:
            ws.scan_progress_widget.stop()
            if states:
                ws.show_ready()
            else:
                ws.show_empty()
        elif self.media_ctrl.scan_progress.lifecycle in {
            ScanLifecycle.WARNING,
            ScanLifecycle.FAILED,
        } and not states:
            ws.show_empty()
            message = self.media_ctrl.scan_progress.message or "The scan ended before any results were produced."
            self._show_scan_feedback(
                title="Scan did not finish cleanly",
                message=message,
                tone="error",
            )
        elif ws.is_showing_ready():
            ws.refresh_from_controller()

    def _show_scan_feedback(self, *, title: str, message: str, tone: str) -> None:
        self._feedback_coordinator.show_scan_feedback(
            title=title,
            message=message,
            tone=tone,
        )

    def _on_queue_changed(self, _unused=None) -> None:
        self._refresh_job_views()
        # Only refresh media workspaces that are in the READY state and
        # currently visible.  Full roster rebuilds are expensive — avoid
        # doing them on both workspaces for every queue event.  The
        # non-visible workspace will refresh via _on_tab_changed when the
        # user switches back to it.
        active = self._tabs.currentIndex()
        if active == _TV and self._tv_workspace.is_showing_ready():
            self._tv_workspace.refresh_from_controller()
        elif active == _MOVIES and self._movie_workspace.is_showing_ready():
            self._movie_workspace.refresh_from_controller()
        # Mark the other workspace as needing a refresh on next tab switch.
        self._tv_needs_queue_refresh = active != _TV
        self._movie_needs_queue_refresh = active != _MOVIES

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
