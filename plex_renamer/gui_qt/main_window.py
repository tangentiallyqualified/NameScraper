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
import threading
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow,
    QMenuBar,
    QMessageBox,
    QTabBar,
    QTabWidget,
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

from .widgets.media_workspace import MediaWorkspace
from .widgets.queue_tab import QueueTab
from .widgets.history_tab import HistoryTab
from .widgets.settings_tab import SettingsTab
from .widgets.tab_badge import TabBadge
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


class _ControllerBridge(QObject):
    """Thread-safe bridge from MediaController callbacks to Qt signals.

    MediaController fires callbacks from background threads.  This bridge
    converts them into Qt signals that are dispatched on the main thread.
    """

    progress_received = Signal(object)   # ScanProgress
    scan_complete = Signal()
    library_changed = Signal()

    def on_progress(self, progress: ScanProgress) -> None:
        self.progress_received.emit(progress)

    def on_scan_complete(self, _state) -> None:
        self.scan_complete.emit()

    def on_library_changed(self, _states) -> None:
        self.library_changed.emit()


class _QueueBridge(QObject):
    """Thread-safe bridge from QueueController callbacks to Qt signals."""

    changed = Signal(object)
    job_started = Signal(object)
    job_completed = Signal(object, object)
    job_failed = Signal(object, object)
    queue_finished = Signal()
    poster_backfill_finished = Signal(int)

    def on_job_started(self, job) -> None:
        self.job_started.emit(job)
        self.changed.emit(None)

    def on_job_completed(self, job, result) -> None:
        self.job_completed.emit(job, result)
        self.changed.emit(None)

    def on_job_failed(self, job, error) -> None:
        self.job_failed.emit(job, error)
        self.changed.emit(None)

    def on_queue_finished(self) -> None:
        self.queue_finished.emit()
        self.changed.emit(None)

    def on_poster_backfill_finished(self, updated: int) -> None:
        try:
            self.poster_backfill_finished.emit(updated)
        except RuntimeError:
            pass  # Window closed before backfill thread finished


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

        # ── Services and controllers ─────────────────────────────
        self.settings_service = SettingsService()
        self._job_store = JobStore()
        self._command_gating = CommandGatingService()
        self._cache_service = PersistentCacheService()
        self._refresh_policy = RefreshPolicyService()

        self.queue_ctrl = QueueController(self._job_store)
        self.media_ctrl = MediaController(
            job_store=self._job_store,
            command_gating=self._command_gating,
            settings=self.settings_service,
            cache_service=self._cache_service,
            refresh_policy=self._refresh_policy,
        )

        # ── Controller → Qt bridge ───────────────────────────────
        self._bridge = _ControllerBridge(self)
        self.media_ctrl.add_listener(
            on_progress=self._bridge.on_progress,
            on_scan_complete=self._bridge.on_scan_complete,
            on_library_changed=self._bridge.on_library_changed,
        )
        self._bridge.progress_received.connect(self._on_scan_progress)
        self._bridge.scan_complete.connect(self._on_scan_complete)
        self._bridge.library_changed.connect(self._on_library_changed)

        self._queue_bridge = _QueueBridge(self)
        self.queue_ctrl.add_listener(
            on_job_started=self._queue_bridge.on_job_started,
            on_job_completed=self._queue_bridge.on_job_completed,
            on_job_failed=self._queue_bridge.on_job_failed,
            on_queue_finished=self._queue_bridge.on_queue_finished,
        )
        self._queue_bridge.changed.connect(self._on_queue_changed)
        self._queue_bridge.job_started.connect(self._on_job_started)
        self._queue_bridge.job_completed.connect(self._on_job_completed)
        self._queue_bridge.job_failed.connect(self._on_job_failed)
        self._queue_bridge.queue_finished.connect(self._on_queue_finished)
        self._queue_bridge.poster_backfill_finished.connect(self._on_poster_backfill_finished)

        # ── Tab widget ───────────────────────────────────────────
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self.setCentralWidget(self._tabs)
        self._toast_manager = ToastManager(self)
        self._queue_run_started = False
        self._queue_completed_count = 0
        self._queue_failed_count = 0
        self._job_poster_backfill_started = False
        self._tv_needs_queue_refresh = False
        self._movie_needs_queue_refresh = False
        self._scan_feedback_token: tuple[str, str] | None = None

        # ── Tab content ──────────────────────────────────────────
        self._tv_workspace = MediaWorkspace(
            media_type="tv",
            media_controller=self.media_ctrl,
            queue_controller=self.queue_ctrl,
            tmdb_provider=self._ensure_tmdb,
            settings_service=self.settings_service,
        )
        self._movie_workspace = MediaWorkspace(
            media_type="movie",
            media_controller=self.media_ctrl,
            queue_controller=self.queue_ctrl,
            tmdb_provider=self._ensure_tmdb,
            settings_service=self.settings_service,
        )
        self._queue_tab = QueueTab(
            self.queue_ctrl,
            tmdb_provider=self._ensure_tmdb,
            navigate_to_media=self._switch_to_tab,
        )
        self._history_tab = HistoryTab(
            self.queue_ctrl,
            tmdb_provider=self._ensure_tmdb,
        )
        self._settings_tab = SettingsTab(
            settings_service=self.settings_service,
            cache_service=self._cache_service,
            clear_tmdb_callback=self._drop_tmdb_client,
        )

        self._tabs.addTab(self._tv_workspace, "TV Shows")
        self._tabs.addTab(self._movie_workspace, "Movies")
        self._tabs.addTab(self._queue_tab, "Queue")
        self._tabs.addTab(self._history_tab, "History")
        self._tabs.addTab(self._settings_tab, "Settings")
        self._queue_badge = TabBadge(show_failure_pip=True, parent=self._tabs)
        self._history_badge = TabBadge(parent=self._tabs)
        self._tabs.tabBar().setTabButton(_QUEUE, QTabBar.ButtonPosition.RightSide, self._queue_badge)
        self._tabs.tabBar().setTabButton(_HISTORY, QTabBar.ButtonPosition.RightSide, self._history_badge)

        # ── Menu bar ─────────────────────────────────────────────
        self._build_menu_bar()

        # ── Keyboard shortcuts ───────────────────────────────────
        self._build_shortcuts()

        # ── Signals ──────────────────────────────────────────────
        self._tabs.currentChanged.connect(self._on_tab_changed)
        self._tv_workspace.folder_selected.connect(self._on_tv_folder_selected)
        self._movie_workspace.folder_selected.connect(self._on_movie_folder_selected)
        self._tv_workspace.queue_changed.connect(self._on_queue_changed)
        self._movie_workspace.queue_changed.connect(self._on_queue_changed)
        self._queue_tab.queue_changed.connect(self._on_queue_changed)
        self._tv_workspace.status_message.connect(self.statusBar().showMessage)
        self._movie_workspace.status_message.connect(self.statusBar().showMessage)
        self._history_tab.history_changed.connect(self._on_queue_changed)
        self._settings_tab.view_mode_changed.connect(self._apply_view_mode)
        self._settings_tab.companion_visibility_changed.connect(self._apply_companion_visibility)
        self._settings_tab.discovery_visibility_changed.connect(self._apply_discovery_visibility)
        self._settings_tab.language_changed.connect(self._on_language_changed)
        self._settings_tab.api_key_saved.connect(self._invalidate_tmdb)

        # ── Restore geometry ─────────────────────────────────────
        self._restore_window_state()
        self._refresh_job_views()
        self._apply_view_mode(self.settings_service.view_mode)
        self._apply_companion_visibility(self.settings_service.show_companion_files)
        self._apply_discovery_visibility(self.settings_service.show_discovery_info)
        QTimer.singleShot(0, self._start_job_poster_backfill)

    # ── TMDB client ──────────────────────────────────────────────

    def _ensure_tmdb(self) -> TMDBClient | None:
        """Get or lazily create the shared TMDB client."""
        if self._tmdb is not None:
            return self._tmdb
        api_key = get_api_key("TMDB")
        if not api_key:
            self.statusBar().showMessage(
                "No TMDB API key — set one in Settings first.", 5000,
            )
            return None
        self._tmdb = TMDBClient(
            api_key,
            language=self.settings_service.match_language,
            cache_service=self._cache_service,
        )
        self._restore_tmdb_cache_snapshot()
        return self._tmdb

    def _restore_tmdb_cache_snapshot(self) -> None:
        if self._tmdb is None:
            return
        cached_snapshot = self._cache_service.get(
            TMDB_CACHE_NAMESPACE,
            TMDB_CACHE_SNAPSHOT_KEY,
        )
        if not cached_snapshot.is_hit or not cached_snapshot.value:
            return
        try:
            self._tmdb.import_cache_snapshot(
                cached_snapshot.value,
                clear_existing=True,
            )
        except Exception:
            self._cache_service.invalidate(
                TMDB_CACHE_NAMESPACE,
                TMDB_CACHE_SNAPSHOT_KEY,
            )

    def _persist_tmdb_cache_snapshot(self) -> None:
        if self._tmdb is None:
            return
        snapshot = self._tmdb.export_cache_snapshot()
        self._cache_service.put(
            TMDB_CACHE_NAMESPACE,
            TMDB_CACHE_SNAPSHOT_KEY,
            snapshot,
            metadata={"kind": "tmdb_cache_snapshot"},
        )

    def _invalidate_tmdb(self) -> None:
        self._persist_tmdb_cache_snapshot()
        self._tmdb = None

    def _drop_tmdb_client(self) -> None:
        self._tmdb = None

    def _start_job_poster_backfill(self) -> None:
        if self._job_poster_backfill_started:
            return
        if not get_api_key("TMDB"):
            return
        tmdb = self._ensure_tmdb()
        if tmdb is None:
            return
        self._job_poster_backfill_started = True

        def _worker() -> None:
            updated = self.queue_ctrl.backfill_missing_job_poster_paths(tmdb)
            self._queue_bridge.on_poster_backfill_finished(updated)

        threading.Thread(target=_worker, daemon=True, name="QtJobPosterBackfill").start()

    def _on_poster_backfill_finished(self, updated: int) -> None:
        if updated <= 0:
            return
        self._refresh_job_views()

    def _refresh_media_workspaces(self) -> None:
        self._tv_workspace.apply_settings()
        self._movie_workspace.apply_settings()

    def _apply_view_mode(self, mode: str) -> None:
        checked = mode == "compact"
        self.settings_service.view_mode = mode
        self._compact_action.blockSignals(True)
        self._compact_action.setChecked(checked)
        self._compact_action.blockSignals(False)
        self._settings_tab.sync_view_mode(mode)
        self._refresh_media_workspaces()

    def _apply_companion_visibility(self, checked: bool) -> None:
        self.settings_service.show_companion_files = checked
        self._companion_action.blockSignals(True)
        self._companion_action.setChecked(checked)
        self._companion_action.blockSignals(False)
        self._settings_tab.sync_companion_visibility(checked)
        self._refresh_media_workspaces()

    def _apply_discovery_visibility(self, checked: bool) -> None:
        self.settings_service.show_discovery_info = checked
        self._settings_tab.sync_discovery_visibility(checked)
        self._refresh_media_workspaces()

    def _on_language_changed(self, tag: str) -> None:
        self.settings_service.match_language = tag
        self._settings_tab.sync_language(tag)
        self._invalidate_tmdb()
        self._refresh_media_workspaces()
        self.statusBar().showMessage(f"TMDB language updated to {tag}.", 3000)

    # ── Menu bar ─────────────────────────────────────────────────

    def _build_menu_bar(self) -> None:
        mb = self.menuBar()

        # File
        file_menu = mb.addMenu("&File")

        open_tv = file_menu.addAction("Open TV Folder...")
        open_tv.setShortcut(QKeySequence("Ctrl+O"))
        open_tv.triggered.connect(lambda: self._open_folder("tv"))

        open_movie = file_menu.addAction("Open Movie Folder...")
        open_movie.triggered.connect(lambda: self._open_folder("movie"))

        file_menu.addSeparator()

        # Recent TV folders submenu
        self._recent_tv_menu = file_menu.addMenu("Recent TV Folders")
        self._recent_movie_menu = file_menu.addMenu("Recent Movie Folders")
        self._rebuild_recent_menus()

        file_menu.addSeparator()

        exit_action = file_menu.addAction("E&xit")
        exit_action.setShortcut(QKeySequence("Alt+F4"))
        exit_action.triggered.connect(self.close)

        # Edit
        edit_menu = mb.addMenu("&Edit")

        undo_action = edit_menu.addAction("&Undo Last Rename")
        undo_action.setShortcut(QKeySequence("Ctrl+Z"))
        undo_action.triggered.connect(self._on_undo)

        edit_menu.addSeparator()

        settings_action = edit_menu.addAction("&Settings")
        settings_action.setShortcut(QKeySequence("Ctrl+,"))
        settings_action.triggered.connect(
            lambda: self._tabs.setCurrentIndex(_SETTINGS)
        )

        # View
        view_menu = mb.addMenu("&View")

        self._compact_action = view_menu.addAction("Compact Mode")
        self._compact_action.setCheckable(True)
        self._compact_action.setChecked(
            self.settings_service.view_mode == "compact"
        )
        self._compact_action.toggled.connect(self._on_compact_toggled)

        self._companion_action = view_menu.addAction("Show Companion Files")
        self._companion_action.setCheckable(True)
        self._companion_action.setChecked(
            self.settings_service.show_companion_files
        )
        self._companion_action.toggled.connect(self._on_companion_toggled)

        # Help
        help_menu = mb.addMenu("&Help")
        about_action = help_menu.addAction("&About")
        about_action.triggered.connect(self._on_about)

    def _build_shortcuts(self) -> None:
        """Register keyboard shortcuts that aren't menu-bound."""
        for i in range(5):
            action = QAction(self)
            action.setShortcut(QKeySequence(f"Ctrl+{i + 1}"))
            idx = i
            action.triggered.connect(lambda _=False, n=idx: self._tabs.setCurrentIndex(n))
            self.addAction(action)

        queue_selected = QAction(self)
        queue_selected.setShortcut(QKeySequence("Ctrl+Q"))
        queue_selected.triggered.connect(self._queue_selected_from_shortcut)
        self.addAction(queue_selected)

        queue_checked = QAction(self)
        queue_checked.setShortcut(QKeySequence("Ctrl+Shift+Q"))
        queue_checked.triggered.connect(self._queue_checked_from_shortcut)
        self.addAction(queue_checked)

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
                not state.scanned and not state.queued and state.show_id is not None
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
        needs_tv_bulk_scan = (
            self.media_ctrl.active_content_mode == "tv"
            and self.media_ctrl.batch_mode
            and any(
                not state.scanned and not state.queued and state.show_id is not None
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
        token = (title, message)
        if self._scan_feedback_token == token:
            return
        self._scan_feedback_token = token
        self._toast_manager.show_toast(
            title=title,
            message=message,
            tone=tone,
            duration_ms=4000,
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

    def _refresh_job_views(self) -> None:
        self._queue_tab.refresh()
        self._history_tab.refresh()
        counts = self.queue_ctrl.count_by_status()
        pending = counts.get("pending", 0) + counts.get("running", 0)
        history = sum(counts.get(status, 0) for status in ("completed", "failed", "cancelled", "reverted"))
        self._tabs.setTabText(_QUEUE, "Queue")
        self._tabs.setTabText(_HISTORY, "History")
        self._queue_badge.set_count(pending)
        self._queue_badge.set_failure_visible(bool(counts.get("failed", 0)))
        self._history_badge.set_count(history)

    def _on_job_started(self, _job: RenameJob) -> None:
        if not self._queue_run_started:
            self._queue_run_started = True
            self._queue_completed_count = 0
            self._queue_failed_count = 0

    def _on_job_completed(self, job: RenameJob, result: RenameResult) -> None:
        self._queue_completed_count += 1
        renamed = result.renamed_count
        noun = "file" if renamed == 1 else "files"
        self._toast_manager.show_toast(
            title=f"Job completed: {job.media_name}",
            message=f"{renamed} {noun} renamed.",
            tone="success",
            duration_ms=3000,
        )

    def _show_history_job(self, job_id: str) -> None:
        self._switch_to_tab(_HISTORY)
        self._history_tab.select_job(job_id)

    def _on_job_failed(self, job: RenameJob, error: str) -> None:
        self._queue_failed_count += 1
        detail = error or job.error_message or "Unknown error"
        self._toast_manager.show_toast(
            title=f"Job failed: {job.media_name}",
            message=detail,
            tone="error",
            duration_ms=0,
            action_text="Show in History",
            action_callback=lambda job_id=job.job_id: self._show_history_job(job_id),
        )

    def _on_queue_finished(self) -> None:
        if not self._queue_run_started:
            return
        summary = f"{self._queue_completed_count} completed"
        if self._queue_failed_count:
            summary += f", {self._queue_failed_count} failed"
        self._toast_manager.show_toast(
            title="Queue finished",
            message=summary,
            tone="accent",
            duration_ms=5000,
        )
        self._queue_run_started = False
        self._queue_completed_count = 0
        self._queue_failed_count = 0

    # ── Other actions ────────────────────────────────────────────

    def _open_folder(self, media_type: str) -> None:
        """Switch to the appropriate tab and trigger its folder picker."""
        if media_type == "tv":
            self._switch_to_tab(_TV)
            self._tv_workspace.open_folder_dialog()
        else:
            self._switch_to_tab(_MOVIES)
            self._movie_workspace.open_folder_dialog()

    def _switch_to_tab(self, index: int) -> None:
        self._tabs.setCurrentIndex(index)

    def _rebuild_recent_menus(self) -> None:
        self._recent_tv_menu.clear()
        for folder in self.settings_service.recent_tv_folders:
            p = Path(folder)
            action = self._recent_tv_menu.addAction(f"{p.name}  ({p})")
            action.triggered.connect(
                lambda _=False, f=folder: self._tv_workspace.load_folder(f)
            )
        self._recent_tv_menu.setEnabled(bool(self.settings_service.recent_tv_folders))

        self._recent_movie_menu.clear()
        for folder in self.settings_service.recent_movie_folders:
            p = Path(folder)
            action = self._recent_movie_menu.addAction(f"{p.name}  ({p})")
            action.triggered.connect(
                lambda _=False, f=folder: self._movie_workspace.load_folder(f)
            )
        self._recent_movie_menu.setEnabled(bool(self.settings_service.recent_movie_folders))

    def _on_tab_changed(self, index: int) -> None:
        self._capture_active_snapshot()

        if index == _TV:
            if self._tv_snapshot is not None:
                self.media_ctrl.restore_tv_from_tab_switch(self._tv_snapshot)
                self._tv_workspace.refresh_from_controller()
            elif self._tv_needs_queue_refresh and self._tv_workspace.is_showing_ready():
                self._tv_workspace.refresh_from_controller()
            self._tv_needs_queue_refresh = False
        elif index == _MOVIES:
            if self._movie_snapshot is not None:
                self.media_ctrl.restore_movie_from_tab_switch(self._movie_snapshot)
                self._movie_workspace.refresh_from_controller()
            elif self._movie_needs_queue_refresh and self._movie_workspace.is_showing_ready():
                self._movie_workspace.refresh_from_controller()
            self._movie_needs_queue_refresh = False

        _log.debug("Tab switched to %d", index)

    def _capture_active_snapshot(self) -> None:
        if self.media_ctrl.active_content_mode == "tv":
            self._tv_snapshot = self.media_ctrl.snapshot_tv_for_tab_switch()
        elif self.media_ctrl.active_content_mode == "movie":
            self._movie_snapshot = self.media_ctrl.snapshot_movie_for_tab_switch()

    def _on_undo(self) -> None:
        job = self.queue_ctrl.get_latest_revertible_job()
        if job is None:
            self.statusBar().showMessage("Nothing to undo", 3000)
            return

        undo_data = job.undo_data or {}
        rename_count = len(undo_data.get("renames", []))
        desc = f"Undo {rename_count} rename(s) for '{job.media_name}'?"
        removed_dirs = undo_data.get("removed_dirs") or []
        if removed_dirs:
            desc += "\n\nRemoved folders will also be restored where possible."

        if QMessageBox.question(
            self,
            "Undo Last Rename",
            desc,
        ) != QMessageBox.StandardButton.Yes:
            return

        success, errors = self.queue_ctrl.revert_job(job.job_id)
        self._on_queue_changed()
        self._history_tab.select_job(job.job_id)
        self._switch_to_tab(_HISTORY)

        if errors:
            QMessageBox.warning(self, "Partial Undo", "\n".join(errors[:8]))
        elif success:
            self.statusBar().showMessage(f"Reverted '{job.media_name}'", 4000)
        else:
            QMessageBox.warning(self, "Undo Failed", "Unable to revert the selected rename job.")

    def _on_compact_toggled(self, checked: bool) -> None:
        self._apply_view_mode("compact" if checked else "normal")

    def _on_companion_toggled(self, checked: bool) -> None:
        self._apply_companion_visibility(checked)

    def _on_about(self) -> None:
        QMessageBox.about(
            self,
            "About Plex Renamer",
            "Plex Renamer — GUI3 (PySide6)\n\n"
            "Automatically rename and organize media files\n"
            "into Plex-compatible naming conventions.\n\n"
            "Metadata provided by TMDB.",
        )

    # ── Window state persistence ─────────────────────────────────

    def _restore_window_state(self) -> None:
        geo = self.settings_service.window_geometry
        if geo and len(geo) == 4:
            self.setGeometry(*geo)
        else:
            self.resize(1440, 900)

    def _save_window_state(self) -> None:
        g = self.geometry()
        self.settings_service.window_geometry = [g.x(), g.y(), g.width(), g.height()]

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._toast_manager._reposition()

    # ── Close ────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:
        self._save_window_state()
        self._persist_tmdb_cache_snapshot()
        self.media_ctrl.clear_listeners()
        self.queue_ctrl.clear_listeners()
        self.queue_ctrl.close()
        super().closeEvent(event)
