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

    def test_episode_auto_accept_threshold_default(self):
        self.assertAlmostEqual(self.svc.episode_auto_accept_threshold, 0.85)

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

    def test_episode_auto_accept_threshold_roundtrip(self):
        self.svc.episode_auto_accept_threshold = 0.90
        self.assertAlmostEqual(self.svc.episode_auto_accept_threshold, 0.90)
        svc2 = SettingsService(path=self.path)
        self.assertAlmostEqual(svc2.episode_auto_accept_threshold, 0.90)

    def test_episode_auto_accept_threshold_clamped(self):
        self.svc.episode_auto_accept_threshold = 0.10
        self.assertAlmostEqual(self.svc.episode_auto_accept_threshold, 0.50)
        self.svc.episode_auto_accept_threshold = 1.50
        self.assertAlmostEqual(self.svc.episode_auto_accept_threshold, 1.00)

    def test_episode_auto_accept_threshold_handles_corrupt(self):
        self.svc.set("episode_auto_accept_threshold", "garbage")
        self.assertAlmostEqual(self.svc.episode_auto_accept_threshold, 0.85)

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
        self.assertEqual(self.svc.recent_tv_folders, ["/media/tv", "/media/other"])

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


class TestSettingsValidation(unittest.TestCase):
    """Schema validation on load — unknown keys, wrong types."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.path = Path(self._tmp.name) / "settings.json"

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, data: dict) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def test_unknown_key_stripped_on_load(self):
        self._write({"match_language": "ja-JP", "typo_key": True})
        svc = SettingsService(path=self.path)
        self.assertEqual(svc.match_language, "ja-JP")
        self.assertIsNone(svc.get("typo_key"))

    def test_wrong_type_reset_to_default(self):
        self._write({"auto_accept_threshold": "not a number"})
        svc = SettingsService(path=self.path)
        self.assertAlmostEqual(svc.auto_accept_threshold, 0.55)

    def test_correct_types_preserved(self):
        self._write(
            {
                "match_language": "fr-FR",
                "hide_already_named": False,
                "auto_accept_threshold": 0.75,
                "episode_auto_accept_threshold": 0.90,
                "window_geometry": [10, 20, 800, 600],
            }
        )
        svc = SettingsService(path=self.path)
        self.assertEqual(svc.match_language, "fr-FR")
        self.assertFalse(svc.hide_already_named)
        self.assertAlmostEqual(svc.auto_accept_threshold, 0.75)
        self.assertAlmostEqual(svc.episode_auto_accept_threshold, 0.90)
        self.assertEqual(svc.window_geometry, [10, 20, 800, 600])

    def test_int_threshold_accepted(self):
        self._write({"auto_accept_threshold": 1})
        svc = SettingsService(path=self.path)
        self.assertAlmostEqual(svc.auto_accept_threshold, 1.00)

    def test_none_geometry_accepted(self):
        self._write({"window_geometry": None})
        svc = SettingsService(path=self.path)
        self.assertIsNone(svc.window_geometry)

    def test_bool_where_string_expected_reset(self):
        self._write({"match_language": True})
        svc = SettingsService(path=self.path)
        self.assertEqual(svc.match_language, "en-US")


class TestCacheMaxSizeBytes(unittest.TestCase):
    """cache_max_size_bytes default and clamping behavior."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.path = Path(self._tmp.name) / "settings.json"
        self.svc = SettingsService(path=self.path)

    def tearDown(self):
        self._tmp.cleanup()

    def test_cache_max_size_default_is_one_gib(self):
        self.assertEqual(self.svc.cache_max_size_bytes, 1024**3)

    def test_cache_max_size_clamps_to_ceiling(self):
        self.svc.cache_max_size_bytes = 99 * 1024**3  # above 8 GiB
        self.assertEqual(self.svc.cache_max_size_bytes, 8 * 1024**3)

    def test_cache_max_size_clamps_to_floor(self):
        self.svc.cache_max_size_bytes = 1  # below floor
        self.assertEqual(self.svc.cache_max_size_bytes, 64 * 1024 * 1024)


class TestOutputDestinations(unittest.TestCase):
    """Persistent TV/movie output folder settings and validation."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.path = self.root / "settings.json"
        self.svc = SettingsService(path=self.path)

    def tearDown(self):
        self._tmp.cleanup()

    def test_output_folders_default_to_empty(self):
        self.assertEqual(self.svc.tv_output_folder, "")
        self.assertEqual(self.svc.movie_output_folder, "")
        self.assertIsNone(self.svc.valid_tv_output_folder)
        self.assertIsNone(self.svc.valid_movie_output_folder)

    def test_output_folders_roundtrip(self):
        tv = self.root / "TV Output"
        movies = self.root / "Movie Output"
        tv.mkdir()
        movies.mkdir()

        self.svc.tv_output_folder = str(tv)
        self.svc.movie_output_folder = str(movies)

        reloaded = SettingsService(path=self.path)
        self.assertEqual(Path(reloaded.tv_output_folder), tv)
        self.assertEqual(Path(reloaded.movie_output_folder), movies)
        self.assertEqual(reloaded.valid_tv_output_folder, tv.resolve())
        self.assertEqual(reloaded.valid_movie_output_folder, movies.resolve())

    def test_output_folder_validation_requires_existing_directory(self):
        missing = self.root / "missing"
        status = self.svc.validate_output_folder(str(missing))

        self.assertFalse(status.valid)
        self.assertIn("does not exist", status.reason)

    def test_scan_output_relationship_rejects_same_directory(self):
        output = self.root / "media"
        output.mkdir()

        status = self.svc.validate_scan_output_relationship(output, output)

        self.assertFalse(status.valid)
        self.assertIn("cannot be the same", status.reason)

    def test_scan_output_relationship_rejects_output_nested_under_source(self):
        source = self.root / "source"
        output = source / "ready"
        output.mkdir(parents=True)

        status = self.svc.validate_scan_output_relationship(source, output)

        self.assertFalse(status.valid)
        self.assertIn("cannot be inside", status.reason)

    def test_scan_output_relationship_allows_source_nested_under_output(self):
        output = self.root / "library"
        source = output / "incoming"
        source.mkdir(parents=True)

        status = self.svc.validate_scan_output_relationship(source, output)

        self.assertTrue(status.valid)


def test_tv_metadata_source_default_and_roundtrip(tmp_path: Path) -> None:
    svc = SettingsService(tmp_path / "settings.json")
    assert svc.tv_metadata_source == "tmdb"
    svc.tv_metadata_source = "tvdb"
    reloaded = SettingsService(tmp_path / "settings.json")
    assert reloaded.tv_metadata_source == "tvdb"


def test_automux_convert_containers_defaults_true_and_round_trips(tmp_path: Path) -> None:
    svc = SettingsService(path=tmp_path / "settings.json")
    assert svc.automux_convert_containers is True
    svc.automux_convert_containers = False
    reloaded = SettingsService(path=tmp_path / "settings.json")
    assert reloaded.automux_convert_containers is False


def test_convert_containers_does_not_count_toward_any_enabled(tmp_path: Path) -> None:
    svc = SettingsService(path=tmp_path / "settings.json")
    # Fresh defaults: merge/strip all off, convert on — AutoMux must stay
    # inactive (piggyback semantics; spec revision).
    assert svc.automux_convert_containers is True
    assert svc.automux_any_enabled is False


if __name__ == "__main__":
    unittest.main()
