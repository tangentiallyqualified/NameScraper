# tests/test_settings_longpath.py
"""Non-blocking long-path (MAX_PATH) warning at destination selection (S1)."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from conftest_qt import QtSmokeBase


class LongPathWarningTests(QtSmokeBase):
    def tearDown(self):
        # Each test builds a full SettingsTab inline with no disposal;
        # dispose per test to keep GC cycle counts small (see
        # QtSmokeBase._dispose_top_level_widgets for the crash this avoids).
        from plex_renamer.gui_qt.widgets.settings_tab import SettingsTab

        self._dispose_top_level_widgets(SettingsTab)
        super().tearDown()

    def _tab(self, tmp_path: Path):
        from plex_renamer.app.services.cache_service import PersistentCacheService
        from plex_renamer.app.services.settings_service import SettingsService
        from plex_renamer.gui_qt.widgets.settings_tab import SettingsTab

        settings = SettingsService(path=tmp_path / "s.json")
        cache = PersistentCacheService(db_path=tmp_path / "c.db")
        tab = SettingsTab(settings_service=settings, cache_service=cache)
        return tab

    def test_browse_with_long_path_shows_warning(self):
        with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            tab = self._tab(Path(tmp))
            long_path = (
                r"C:\Users\somebody\Videos\Archive\Television\Complete Collections\By Network"
                + ("\\deep" * 12)
            )
            with patch(
                "plex_renamer.gui_qt.widgets._settings_tab_state.QFileDialog.getExistingDirectory",
                return_value=long_path,
            ):
                tab._state_coordinator.browse_output_folder("tv")

            self.assertNotEqual(tab._destinations_status.text(), "")
            self.assertEqual(tab._destinations_status.property("tone"), "warning")

    def test_browse_with_short_path_clears_warning(self):
        with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            tab = self._tab(Path(tmp))
            short_path = str(Path(tmp) / "TV")
            with patch(
                "plex_renamer.gui_qt.widgets._settings_tab_state.QFileDialog.getExistingDirectory",
                return_value=short_path,
            ):
                tab._state_coordinator.browse_output_folder("tv")

            self.assertEqual(tab._destinations_status.text(), "")
