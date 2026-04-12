"""Tab and startup wiring helpers for the main window."""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtWidgets import QTabBar, QTabWidget

from .widgets.history_tab import HistoryTab
from .widgets.media_workspace import MediaWorkspace
from .widgets.queue_tab import QueueTab
from .widgets.settings_tab import SettingsTab
from .widgets.tab_badge import TabBadge


class MainWindowTabsCoordinator:
    def __init__(
        self,
        window: Any,
        *,
        tv_index: int,
        movies_index: int,
        queue_index: int,
        history_index: int,
    ) -> None:
        self._window = window
        self._tv_index = tv_index
        self._movies_index = movies_index
        self._queue_index = queue_index
        self._history_index = history_index

    def build_tab_widget(self) -> None:
        window = self._window
        window._tabs = QTabWidget()
        window._tabs.setDocumentMode(True)
        window.setCentralWidget(window._tabs)

    def build_tab_content(self) -> None:
        window = self._window
        window._tv_workspace = MediaWorkspace(
            media_type="tv",
            media_controller=window.media_ctrl,
            queue_controller=window.queue_ctrl,
            tmdb_provider=window._ensure_tmdb,
            settings_service=window.settings_service,
        )
        window._movie_workspace = MediaWorkspace(
            media_type="movie",
            media_controller=window.media_ctrl,
            queue_controller=window.queue_ctrl,
            tmdb_provider=window._ensure_tmdb,
            settings_service=window.settings_service,
        )
        window._queue_tab = QueueTab(
            window.queue_ctrl,
            tmdb_provider=window._ensure_tmdb,
            navigate_to_media=window._switch_to_tab,
        )
        window._history_tab = HistoryTab(
            window.queue_ctrl,
            tmdb_provider=window._ensure_tmdb,
        )
        window._settings_tab = SettingsTab(
            settings_service=window.settings_service,
            cache_service=window._cache_service,
            clear_tmdb_callback=window._drop_tmdb_client,
            clear_history_callback=window._clear_history_from_settings,
        )

        window._tabs.addTab(window._tv_workspace, "TV Shows")
        window._tabs.addTab(window._movie_workspace, "Movies")
        window._tabs.addTab(window._queue_tab, "Queue")
        window._tabs.addTab(window._history_tab, "History")
        window._tabs.addTab(window._settings_tab, "Settings")

        self._build_badges()

    def connect_signals(self) -> None:
        window = self._window
        window._tabs.currentChanged.connect(window._on_tab_changed)
        window._tv_workspace.folder_selected.connect(window._on_tv_folder_selected)
        window._movie_workspace.folder_selected.connect(window._on_movie_folder_selected)
        window._tv_workspace.queue_changed.connect(window._on_queue_changed)
        window._movie_workspace.queue_changed.connect(window._on_queue_changed)
        window._queue_tab.queue_changed.connect(window._on_queue_changed)
        window._tv_workspace.status_message.connect(window.statusBar().showMessage)
        window._movie_workspace.status_message.connect(window.statusBar().showMessage)
        window._history_tab.history_changed.connect(window._on_queue_changed)
        window._settings_tab.view_mode_changed.connect(window._apply_view_mode)
        window._settings_tab.companion_visibility_changed.connect(window._apply_companion_visibility)
        window._settings_tab.discovery_visibility_changed.connect(window._apply_discovery_visibility)
        window._settings_tab.language_changed.connect(window._on_language_changed)
        window._settings_tab.threshold_changed.connect(window._on_threshold_changed)
        window._settings_tab.api_key_saved.connect(window._invalidate_tmdb)
        window._settings_tab.history_cleared.connect(window._on_queue_changed)

    def apply_initial_state(self, *, schedule_single_shot: Callable[..., None]) -> None:
        window = self._window
        window._restore_window_state()
        window._refresh_job_views()
        window._apply_view_mode(window.settings_service.view_mode)
        window._apply_companion_visibility(window.settings_service.show_companion_files)
        window._apply_discovery_visibility(window.settings_service.show_discovery_info)
        schedule_single_shot(0, window._start_job_poster_backfill)

    def _build_badges(self) -> None:
        window = self._window
        window._tv_badge = TabBadge(show_failure_pip=True, parent=window._tabs)
        window._movie_badge = TabBadge(show_failure_pip=True, parent=window._tabs)
        window._queue_badge = TabBadge(show_failure_pip=True, parent=window._tabs)
        window._history_badge = TabBadge(parent=window._tabs)
        tab_bar = window._tabs.tabBar()
        tab_bar.setTabButton(self._tv_index, QTabBar.ButtonPosition.RightSide, window._tv_badge)
        tab_bar.setTabButton(self._movies_index, QTabBar.ButtonPosition.RightSide, window._movie_badge)
        tab_bar.setTabButton(self._queue_index, QTabBar.ButtonPosition.RightSide, window._queue_badge)
        tab_bar.setTabButton(self._history_index, QTabBar.ButtonPosition.RightSide, window._history_badge)
