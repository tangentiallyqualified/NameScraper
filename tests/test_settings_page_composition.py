"""Settings page composition and persistence characterizations."""

from __future__ import annotations

from pathlib import Path

from conftest_qt import QtSmokeBase


class SettingsPageCompositionTests(QtSmokeBase):
    def _settings(self):
        from plex_renamer.app.services.settings_service import SettingsService

        path = Path(self._main_window_tmp.name) / "settings-pages.json"
        return SettingsService(path), path

    def test_composer_constructs_both_concrete_page_cards(self):
        from plex_renamer.gui_qt.widgets._settings_automux_page import (
            AutoMuxSettingsPage,
        )
        from plex_renamer.gui_qt.widgets._settings_metadata_page import (
            MetadataSettingsPage,
        )
        from plex_renamer.gui_qt.widgets.settings_tab import SettingsTab

        settings, _path = self._settings()
        tab = SettingsTab(settings_service=settings)

        self.assertIsInstance(tab._metadata_page, MetadataSettingsPage)
        self.assertIsInstance(tab._automux_page, AutoMuxSettingsPage)
        self.assertEqual(tab._metadata_page.property("sectionRole"), "page")
        self.assertEqual(tab._automux_page.property("sectionRole"), "page")
        self.assertGreaterEqual(tab._settings_stack.indexOf(tab._metadata_page), 0)
        self.assertGreaterEqual(tab._settings_stack.indexOf(tab._automux_page), 0)

    def test_page_edits_persist_when_settings_are_reloaded(self):
        from plex_renamer.app.services.settings_service import SettingsService
        from plex_renamer.gui_qt.widgets.settings_tab import SettingsTab

        settings, path = self._settings()
        fake_mkvmerge = Path(self._main_window_tmp.name) / "mkvmerge.exe"
        fake_mkvmerge.write_bytes(b"")
        settings.mkvmerge_path = str(fake_mkvmerge)
        tab = SettingsTab(settings_service=settings)

        tab._metadata_page._master_cb.setChecked(True)
        tab._metadata_page._source_combo.setCurrentIndex(1)
        tab._automux_page._no_fear_cb.setChecked(True)

        reloaded = SettingsService(path)
        self.assertTrue(reloaded.get("metadata_enabled"))
        self.assertTrue(reloaded.get("metadata_prefer_local"))
        self.assertTrue(reloaded.get("automux_no_fear"))
