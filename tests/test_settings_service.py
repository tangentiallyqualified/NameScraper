"""Tests for SettingsService — typed accessors and persistence."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from plex_renamer.app.services.settings_service import SettingsService


class TestSettingsServiceDefaults(unittest.TestCase):
    """New instance with no file on disk should return all defaults."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.path = Path(self._tmp.name) / "settings.json"
        self.svc = SettingsService(path=self.path)

    def tearDown(self):
        self._tmp.cleanup()

    def test_existing_defaults_unchanged(self):
        self.assertEqual(self.svc.match_language, "en-US")
        self.assertTrue(self.svc.hide_already_named)

    def test_view_mode_default(self):
        self.assertEqual(self.svc.view_mode, "normal")

    def test_show_companion_files_default(self):
        self.assertTrue(self.svc.show_companion_files)

    def test_show_discovery_info_default(self):
        self.assertFalse(self.svc.show_discovery_info)

    def test_auto_accept_threshold_default(self):
        self.assertAlmostEqual(self.svc.auto_accept_threshold, 0.55)

    def test_show_confidence_bars_default(self):
        self.assertTrue(self.svc.show_confidence_bars)

    def test_window_geometry_default(self):
        self.assertIsNone(self.svc.window_geometry)

    def test_splitter_positions_default(self):
        self.assertIsNone(self.svc.splitter_positions)

    def test_recent_tv_folders_default(self):
        self.assertEqual(self.svc.recent_tv_folders, [])

    def test_recent_movie_folders_default(self):
        self.assertEqual(self.svc.recent_movie_folders, [])


class TestSettingsServiceSetters(unittest.TestCase):
    """Setters persist and round-trip correctly."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.path = Path(self._tmp.name) / "settings.json"
        self.svc = SettingsService(path=self.path)

    def tearDown(self):
        self._tmp.cleanup()

    def test_view_mode_roundtrip(self):
        self.svc.view_mode = "compact"
        self.assertEqual(self.svc.view_mode, "compact")
        # Reload from disk
        svc2 = SettingsService(path=self.path)
        self.assertEqual(svc2.view_mode, "compact")

    def test_view_mode_rejects_invalid(self):
        with self.assertRaises(ValueError):
            self.svc.view_mode = "tiny"

    def test_show_companion_files_roundtrip(self):
        self.svc.show_companion_files = False
        self.assertFalse(self.svc.show_companion_files)

    def test_show_discovery_info_roundtrip(self):
        self.svc.show_discovery_info = True
        self.assertTrue(self.svc.show_discovery_info)

    def test_auto_accept_threshold_roundtrip(self):
        self.svc.auto_accept_threshold = 0.80
        self.assertAlmostEqual(self.svc.auto_accept_threshold, 0.80)

    def test_auto_accept_threshold_clamped_low(self):
        self.svc.auto_accept_threshold = 0.10
        self.assertAlmostEqual(self.svc.auto_accept_threshold, 0.50)

    def test_auto_accept_threshold_clamped_high(self):
        self.svc.auto_accept_threshold = 1.50
        self.assertAlmostEqual(self.svc.auto_accept_threshold, 1.00)

    def test_auto_accept_threshold_handles_corrupt(self):
        self.svc.set("auto_accept_threshold", "garbage")
        self.assertAlmostEqual(self.svc.auto_accept_threshold, 0.55)

    def test_show_confidence_bars_roundtrip(self):
        self.svc.show_confidence_bars = False
        self.assertFalse(self.svc.show_confidence_bars)

    def test_window_geometry_roundtrip(self):
        self.svc.window_geometry = [100, 200, 1280, 720]
        self.assertEqual(self.svc.window_geometry, [100, 200, 1280, 720])
        # Reload
        svc2 = SettingsService(path=self.path)
        self.assertEqual(svc2.window_geometry, [100, 200, 1280, 720])

    def test_window_geometry_rejects_wrong_length(self):
        with self.assertRaises(ValueError):
            self.svc.window_geometry = [100, 200]

    def test_window_geometry_accepts_none(self):
        self.svc.window_geometry = [100, 200, 1280, 720]
        self.svc.window_geometry = None
        self.assertIsNone(self.svc.window_geometry)

    def test_window_geometry_handles_corrupt(self):
        self.svc.set("window_geometry", "not a list")
        self.assertIsNone(self.svc.window_geometry)

    def test_splitter_positions_roundtrip(self):
        self.svc.splitter_positions = [250, 500, 300]
        self.assertEqual(self.svc.splitter_positions, [250, 500, 300])

    def test_splitter_positions_rejects_wrong_length(self):
        with self.assertRaises(ValueError):
            self.svc.splitter_positions = [250, 500]

    def test_splitter_positions_accepts_none(self):
        self.svc.splitter_positions = [250, 500, 300]
        self.svc.splitter_positions = None
        self.assertIsNone(self.svc.splitter_positions)


class TestRecentFolders(unittest.TestCase):
    """Recent folder MRU list behavior."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.path = Path(self._tmp.name) / "settings.json"
        self.svc = SettingsService(path=self.path)

    def tearDown(self):
        self._tmp.cleanup()

    def test_add_tv_folder(self):
        self.svc.add_recent_tv_folder("/media/tv")
        self.assertEqual(self.svc.recent_tv_folders, ["/media/tv"])

    def test_add_movie_folder(self):
        self.svc.add_recent_movie_folder("/media/movies")
        self.assertEqual(self.svc.recent_movie_folders, ["/media/movies"])

    def test_newest_first(self):
        self.svc.add_recent_tv_folder("/first")
        self.svc.add_recent_tv_folder("/second")
        self.assertEqual(self.svc.recent_tv_folders, ["/second", "/first"])

    def test_deduplication(self):
        self.svc.add_recent_tv_folder("/media/tv")
        self.svc.add_recent_tv_folder("/media/other")
        self.svc.add_recent_tv_folder("/media/tv")
        self.assertEqual(self.svc.recent_tv_folders,
                         ["/media/tv", "/media/other"])

    def test_deduplication_case_insensitive_windows_paths(self):
        self.svc.add_recent_tv_folder("C:\\Users\\TV")
        self.svc.add_recent_tv_folder("c:/users/tv")
        # Should have only one entry (the newest form).
        self.assertEqual(len(self.svc.recent_tv_folders), 1)

    def test_max_recent_folders(self):
        for i in range(15):
            self.svc.add_recent_tv_folder(f"/folder/{i}")
        self.assertEqual(len(self.svc.recent_tv_folders), 10)
        # Most recent is first.
        self.assertEqual(self.svc.recent_tv_folders[0], "/folder/14")

    def test_persists_across_reload(self):
        self.svc.add_recent_movie_folder("/media/movies")
        svc2 = SettingsService(path=self.path)
        self.assertEqual(svc2.recent_movie_folders, ["/media/movies"])


if __name__ == "__main__":
    unittest.main()
