"""Settings page composition and persistence characterizations."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

from conftest_qt import QtSmokeBase
from PySide6.QtWidgets import QCheckBox, QComboBox, QLabel, QStackedWidget, QWidget

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

        from PySide6.QtWidgets import QLineEdit

        from plex_renamer.gui_qt.widgets.settings_tab import SettingsTab

        settings, _path = self._settings()
        with patch("plex_renamer.keys.get_api_key", return_value="stored-key"):
            tab = SettingsTab(settings_service=settings)
        key_inputs = [
            line_edit
            for line_edit in tab.findChildren(QLineEdit)
            if line_edit.placeholderText() == "Enter TMDB API key..."
        ]
        assert len(key_inputs) == 1
        self.assertEqual(key_inputs[0].text(), "stored-key")

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

    def test_api_keys_section_has_source_combo_and_tvdb_key(self):
        from PySide6.QtWidgets import QLineEdit

        from plex_renamer.gui_qt.widgets.settings_tab import SettingsTab

        settings, _path = self._settings()
        tab = SettingsTab(settings_service=settings)
        combo = cast(
            QComboBox,
            tab._tv_source_combo,  # pyright: ignore[reportPrivateUsage, reportAttributeAccessIssue, reportUnknownMemberType]
        )
        self.assertEqual([combo.itemData(i) for i in range(combo.count())], ["tmdb", "tvdb"])
        self.assertEqual(combo.currentData(), "tmdb")
        api_key_input = cast(
            QLineEdit,
            tab._api_key_input,  # pyright: ignore[reportPrivateUsage, reportAttributeAccessIssue, reportUnknownMemberType]
        )
        tvdb_key_input = cast(
            QLineEdit,
            tab._tvdb_key_input,  # pyright: ignore[reportPrivateUsage, reportAttributeAccessIssue, reportUnknownMemberType]
        )
        self.assertEqual(tvdb_key_input.echoMode(), api_key_input.echoMode())

    def test_changing_source_persists_setting(self):
        from plex_renamer.gui_qt.widgets.settings_tab import SettingsTab

        settings, _path = self._settings()
        tab = SettingsTab(settings_service=settings)
        combo = cast(
            QComboBox,
            tab._tv_source_combo,  # pyright: ignore[reportPrivateUsage, reportAttributeAccessIssue, reportUnknownMemberType]
        )
        idx = combo.findData("tvdb")
        combo.setCurrentIndex(idx)
        assert tab._settings is not None  # pyright: ignore[reportPrivateUsage]
        self.assertEqual(tab._settings.tv_metadata_source, "tvdb")  # pyright: ignore[reportPrivateUsage]

    def test_save_key_persists_tvdb_only_key_when_tmdb_field_empty(self):
        # Regression: save_key() used to early-return with "Please enter an
        # API key" whenever the TMDB field was empty, even if a TVDB key was
        # entered, discarding it. The two saves must be independent.
        from unittest.mock import patch

        from PySide6.QtWidgets import QLineEdit

        from plex_renamer.gui_qt.widgets.settings_tab import SettingsTab

        settings, _path = self._settings()
        tab = SettingsTab(settings_service=settings)
        api_key_input = cast(
            QLineEdit,
            tab._api_key_input,  # pyright: ignore[reportPrivateUsage, reportAttributeAccessIssue, reportUnknownMemberType]
        )
        tvdb_key_input = cast(
            QLineEdit,
            tab._tvdb_key_input,  # pyright: ignore[reportPrivateUsage, reportAttributeAccessIssue, reportUnknownMemberType]
        )
        api_key_input.setText("")
        tvdb_key_input.setText("tvdb-only-key")

        saved_calls: list[tuple[str, str]] = []

        def _record_save(service: str, key: str) -> None:
            saved_calls.append((service, key))

        with patch("plex_renamer.keys.save_api_key", side_effect=_record_save):
            tab._on_save_key()  # pyright: ignore[reportPrivateUsage, reportAttributeAccessIssue]

        self.assertEqual(saved_calls, [("TVDB", "tvdb-only-key")])
        key_status = cast(
            QLabel,
            tab._key_status,  # pyright: ignore[reportPrivateUsage, reportAttributeAccessIssue, reportUnknownMemberType]
        )
        self.assertEqual(key_status.property("tone"), "success")
        self.assertNotEqual(key_status.text(), "Please enter an API key.")
