"""AutoMux settings page: nav visibility, binary gating, persistence."""

from __future__ import annotations

from pathlib import Path

from conftest_qt import QtSmokeBase


class AutoMuxSettingsPageTests(QtSmokeBase):
    def _svc(self, *, mkvmerge_path=""):
        from plex_renamer.app.services.settings_service import SettingsService

        base = Path(self._main_window_tmp.name)
        svc = SettingsService(base / "automux_settings.json")
        svc.mkvmerge_path = mkvmerge_path
        return svc

    def _fake_exe(self) -> str:
        exe = Path(self._main_window_tmp.name) / "mkvmerge.exe"
        exe.write_bytes(b"")
        return str(exe)

    def _page(self, svc):
        from plex_renamer.gui_qt.widgets._settings_automux_page import (
            AutoMuxSettingsPage,
        )

        return AutoMuxSettingsPage(settings_service=svc)

    def test_nav_shows_automux_and_no_tools(self):
        from PySide6.QtCore import Qt

        from plex_renamer.gui_qt.widgets.settings_tab import SettingsTab

        tab = SettingsTab(settings_service=self._svc())
        labels = [tab._settings_nav.item(i).text() for i in range(tab._settings_nav.count())]
        self.assertIn("AutoMux", labels)
        self.assertNotIn("Tools", labels)
        item = tab._settings_nav.item(labels.index("AutoMux"))
        self.assertFalse(item.isHidden())
        self.assertTrue(item.flags() & Qt.ItemFlag.ItemIsEnabled)

    def test_body_disabled_without_mkvmerge(self):
        svc = self._svc(mkvmerge_path=str(Path(self._main_window_tmp.name) / "missing.exe"))
        page = self._page(svc)
        self.assertFalse(page._body.isEnabled())
        self.assertIn("not found", page._binary_status.text().lower())

    def test_body_enabled_with_explicit_binary(self):
        page = self._page(self._svc(mkvmerge_path=self._fake_exe()))
        self.assertTrue(page._body.isEnabled())

    def test_toggle_persists(self):
        svc = self._svc(mkvmerge_path=self._fake_exe())
        page = self._page(svc)
        page._merge_subs_cb.setChecked(True)
        self.assertTrue(svc.automux_merge_subs)
        page._no_fear_cb.setChecked(True)
        self.assertTrue(svc.automux_no_fear)

    def test_convert_containers_toggle_persists(self):
        from PySide6.QtWidgets import QCheckBox

        svc = self._svc(mkvmerge_path=self._fake_exe())
        page = self._page(svc)
        checkbox = None
        for candidate in page.findChildren(QCheckBox):
            if candidate.text() == "Convert non-MKV containers to MKV":
                checkbox = candidate
                break
        assert checkbox is not None
        checkbox.setChecked(False)
        self.assertFalse(svc.automux_convert_containers)

    def test_language_list_normalizes_on_edit(self):
        svc = self._svc(mkvmerge_path=self._fake_exe())
        page = self._page(svc)
        page._merge_langs_edit.setText("en, jpn, nonsense")
        page._merge_langs_edit.editingFinished.emit()
        self.assertEqual(svc.automux_merge_sub_languages, ["eng", "jpn"])
        self.assertEqual(page._merge_langs_edit.text(), "eng, jpn")

    def test_single_language_normalizes(self):
        svc = self._svc(mkvmerge_path=self._fake_exe())
        page = self._page(svc)
        page._default_audio_edit.setText("ja")
        page._default_audio_edit.editingFinished.emit()
        self.assertEqual(svc.automux_default_audio_language, "jpn")
        self.assertEqual(page._default_audio_edit.text(), "jpn")
