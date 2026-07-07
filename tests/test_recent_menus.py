"""Recent-folder submenus are gated to the active tab (G3)."""
from __future__ import annotations

from unittest.mock import PropertyMock, patch

from conftest_qt import QtSmokeBase

from plex_renamer.app.services.settings_service import SettingsService


class RecentMenuGatingTests(QtSmokeBase):
    def setUp(self):
        super().setUp()
        self._main_window_stack.enter_context(
            patch.object(
                SettingsService,
                "recent_tv_folders",
                new_callable=PropertyMock,
                return_value=["/tv/a", "/tv/b"],
            )
        )
        self._main_window_stack.enter_context(
            patch.object(
                SettingsService,
                "recent_movie_folders",
                new_callable=PropertyMock,
                return_value=["/mv/a", "/mv/b"],
            )
        )

    def _window(self, tmp_path):
        from plex_renamer.gui_qt.main_window import MainWindow

        window = MainWindow()
        window._state_coordinator.rebuild_recent_menus()
        self.addCleanup(window.close)
        return window

    def test_tv_tab_enables_only_tv_recent_menu(self, tmp_path=None):
        window = self._window(tmp_path)
        window._tabs.setCurrentIndex(window._state_coordinator._tv_index)
        window._state_coordinator.sync_recent_menu_enabled()
        self.assertTrue(window._recent_tv_menu.isEnabled())
        self.assertFalse(window._recent_movie_menu.isEnabled())

    def test_movie_tab_enables_only_movie_recent_menu(self, tmp_path=None):
        window = self._window(tmp_path)
        window._tabs.setCurrentIndex(window._state_coordinator._movies_index)
        window._state_coordinator.sync_recent_menu_enabled()
        self.assertFalse(window._recent_tv_menu.isEnabled())
        self.assertTrue(window._recent_movie_menu.isEnabled())
