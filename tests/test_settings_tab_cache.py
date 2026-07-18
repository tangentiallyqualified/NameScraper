# tests/test_settings_tab_cache.py
"""Settings cache-size combo persists + applies live (S2 UI)."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from conftest_qt import QtSmokeBase


class CacheSizeComboTests(QtSmokeBase):
    def _tab(self, tmp_path: Path):
        from plex_renamer.app.services.cache_service import PersistentCacheService
        from plex_renamer.app.services.settings_service import SettingsService
        from plex_renamer.gui_qt.widgets.settings_tab import SettingsTab  # confirm class name

        settings = SettingsService(path=tmp_path / "s.json")
        cache = PersistentCacheService(db_path=tmp_path / "c.db")
        tab = SettingsTab(settings_service=settings, cache_service=cache)  # match real ctor
        return tab, settings, cache

    def test_combo_lists_sizes_and_selects_current(self):
        with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            tab, settings, _ = self._tab(Path(tmp))
            from plex_renamer.gui_qt.widgets._settings_tab_sections import CACHE_SIZE_CHOICES

            self.assertEqual(tab._cache_size_combo.count(), len(CACHE_SIZE_CHOICES))
            # default 1 GiB is selected
            self.assertEqual(tab._cache_size_combo.currentData(), 1024**3)

    def test_selecting_size_persists_and_applies(self):
        with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            tab, settings, cache = self._tab(Path(tmp))
            idx = tab._cache_size_combo.findData(2 * 1024**3)
            tab._cache_size_combo.setCurrentIndex(idx)
            self.assertEqual(settings.cache_max_size_bytes, 2 * 1024**3)
            self.assertEqual(cache.stats()["max_size_bytes"], 2 * 1024**3)
