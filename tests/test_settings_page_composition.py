"""Settings page composition and persistence characterizations."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from conftest_qt import QtSmokeBase
from PySide6.QtWidgets import QCheckBox, QComboBox, QStackedWidget, QWidget

if TYPE_CHECKING:
    from plex_renamer.app.services.settings_service import SettingsService


class SettingsPageCompositionTests(QtSmokeBase):
    def tearDown(self) -> None:
        # Each test builds a full SettingsTab inline with no disposal;
        # dispose per test to keep GC cycle counts small (see
        # QtSmokeBase._dispose_top_level_widgets for the crash this avoids).
        from plex_renamer.gui_qt.widgets.settings_tab import SettingsTab

        self._dispose_top_level_widgets(SettingsTab)
        super().tearDown()

    def _settings(self) -> tuple[SettingsService, Path]:
        from plex_renamer.app.services.settings_service import SettingsService

        path = Path(self._main_window_tmp.name) / "settings-pages.json"
        return SettingsService(path), path

    @staticmethod
    def _checkbox(page: QWidget, text: str) -> QCheckBox:
        for checkbox in page.findChildren(QCheckBox):
            if checkbox.text() == text:
                return checkbox
        raise AssertionError(f"checkbox not found: {text}")

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
        metadata_page = tab.findChild(MetadataSettingsPage)
        automux_page = tab.findChild(AutoMuxSettingsPage)
        settings_stack = tab.findChild(QStackedWidget)
        assert metadata_page is not None
        assert automux_page is not None
        assert settings_stack is not None

        self.assertEqual(metadata_page.property("sectionRole"), "page")
        self.assertEqual(automux_page.property("sectionRole"), "page")
        self.assertGreaterEqual(settings_stack.indexOf(metadata_page), 0)
        self.assertGreaterEqual(settings_stack.indexOf(automux_page), 0)

    def test_api_keys_section_prefills_stored_key(self):
        # Patch the keyring lookup so the stored-key prefill branch runs on
        # every machine; unpatched, its coverage depends on whether the dev
        # keyring holds a real TMDB key.
        from unittest.mock import patch

        from plex_renamer.gui_qt.widgets.settings_tab import SettingsTab

        settings, _path = self._settings()
        with patch("plex_renamer.keys.get_api_key", return_value="stored-key"):
            tab = SettingsTab(settings_service=settings)
        self.assertEqual(tab._api_key_input.text(), "stored-key")

    def test_page_edits_persist_when_settings_are_reloaded(self):
        from plex_renamer.app.services.settings_service import SettingsService
        from plex_renamer.gui_qt.widgets._settings_automux_page import AutoMuxSettingsPage
        from plex_renamer.gui_qt.widgets._settings_metadata_page import MetadataSettingsPage
        from plex_renamer.gui_qt.widgets.settings_tab import SettingsTab

        settings, path = self._settings()
        fake_mkvmerge = Path(self._main_window_tmp.name) / "mkvmerge.exe"
        fake_mkvmerge.write_bytes(b"")
        settings.mkvmerge_path = str(fake_mkvmerge)
        tab = SettingsTab(settings_service=settings)
        metadata_page = tab.findChild(MetadataSettingsPage)
        automux_page = tab.findChild(AutoMuxSettingsPage)
        assert metadata_page is not None
        assert automux_page is not None
        source_combo = metadata_page.findChild(QComboBox)
        assert source_combo is not None

        self._checkbox(metadata_page, "Export local metadata with rename/AutoMux jobs").setChecked(
            True
        )
        source_combo.setCurrentIndex(1)
        self._checkbox(automux_page, "No Fear mode").setChecked(True)

        reloaded = SettingsService(path)
        self.assertTrue(reloaded.get("metadata_enabled"))
        self.assertTrue(reloaded.get("metadata_prefer_local"))
        self.assertTrue(reloaded.get("automux_no_fear"))
