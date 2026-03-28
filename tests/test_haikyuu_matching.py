"""Tests for named-season anime matching (Haikyuu!! scenario).

Validates that:
  - Ordinal season names ("Second Season") are recognized by get_season()
  - A show folder with mixed standard/named season subdirs is discovered
    as a single show root (not split into multiple shows)
  - TVScanner matches non-standard season folders against TMDB season names
"""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from plex_renamer.app.services.tv_library_discovery_service import (
    TVLibraryDiscoveryService,
)
from plex_renamer.parsing import get_season


# ── get_season ordinal recognition ─────────────────────────────────────


class OrdinalSeasonTests(unittest.TestCase):
    """get_season() should recognize ordinal words and suffix ordinals."""

    def _season(self, name: str) -> int | None:
        return get_season(Path(name))

    def test_second_season(self):
        self.assertEqual(self._season("[sam] Haikyuu!! Second Season [BD 1080p FLAC]"), 2)

    def test_third_season(self):
        self.assertEqual(self._season("Some Show Third Season"), 3)

    def test_first_season(self):
        self.assertEqual(self._season("First Season"), 1)

    def test_fourth_season(self):
        self.assertEqual(self._season("Show Fourth Season 1080p"), 4)

    def test_fifth_through_tenth(self):
        for word, num in [("Fifth", 5), ("Sixth", 6), ("Seventh", 7),
                          ("Eighth", 8), ("Ninth", 9), ("Tenth", 10)]:
            with self.subTest(word=word):
                self.assertEqual(self._season(f"Show {word} Season"), num)

    def test_ordinal_suffix_2nd_season(self):
        self.assertEqual(self._season("Haikyuu!! 2nd Season"), 2)

    def test_ordinal_suffix_3rd_season(self):
        self.assertEqual(self._season("Show 3rd Season"), 3)

    def test_ordinal_suffix_1st_season(self):
        self.assertEqual(self._season("Show 1st Season"), 1)

    def test_ordinal_suffix_4th_season(self):
        self.assertEqual(self._season("Show 4th Season"), 4)

    def test_case_insensitive(self):
        self.assertEqual(self._season("show SECOND season"), 2)

    def test_standard_patterns_still_work(self):
        """Regression: existing patterns must not break."""
        self.assertEqual(self._season("Season 01"), 1)
        self.assertEqual(self._season("Season 3"), 3)
        self.assertEqual(self._season("S04"), 4)
        self.assertEqual(self._season("Haikyuu!!.S04.1080p.Blu-Ray"), 4)
        self.assertEqual(self._season("Specials"), 0)
        self.assertEqual(self._season("01"), 1)

    def test_no_false_positive_on_word_season(self):
        """Folder names with 'Season' but no ordinal should NOT match."""
        self.assertIsNone(self._season("Haikyuu!! Karasuno High School vs. Shiratorizawa Academy"))

    def test_no_false_positive_on_non_ordinal_word(self):
        """Random words before 'Season' should NOT match."""
        self.assertIsNone(self._season("The Good Season"))


# ── Discovery: show folder as batch root ───────────────────────────────


class HaikyuuDiscoveryTests(unittest.TestCase):
    """When a show folder with season subdirs is selected as the batch root,
    it should be discovered as a single show, not split into multiple shows."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name) / "[sam] Haikyuu!! [BD 1080p FLAC]"
        self.root.mkdir()

        # Season 01 — standard naming
        s1 = self.root / "Season 01"
        s1.mkdir()
        (s1 / "[sam] Haikyuu!! - 01 [BD 1080p FLAC].mkv").write_text("x")
        (s1 / "[sam] Haikyuu!! - 02 [BD 1080p FLAC].mkv").write_text("x")

        # Second Season — ordinal naming
        s2 = self.root / "[sam] Haikyuu!! Second Season [BD 1080p FLAC]"
        s2.mkdir()
        (s2 / "[sam] Haikyuu!! Second Season - 01 [BD 1080p FLAC].mkv").write_text("x")
        (s2 / "[sam] Haikyuu!! Second Season - 02 [BD 1080p FLAC].mkv").write_text("x")

        # Named season — no standard season indicator
        s3 = self.root / "[sam] Haikyuu!! Karasuno High School vs. Shiratorizawa Academy [BD 1080p FLAC]"
        s3.mkdir()
        (s3 / "[sam] Haikyuu!! S3 - 01 [BD 1080p FLAC].mkv").write_text("x")
        (s3 / "[sam] Haikyuu!! S3 - 02 [BD 1080p FLAC].mkv").write_text("x")

        # S04 — standard S## naming
        s4 = self.root / "Haikyuu!!.S04.1080p.Blu-Ray.10-Bit.Dual-Audio.DTS-HD.x265-iAHD"
        s4.mkdir()
        (s4 / "Haikyuu!!.S04E01.1080p.mkv").write_text("x")
        (s4 / "Haikyuu!!.S04E02.1080p.mkv").write_text("x")

    def tearDown(self):
        self._tmp.cleanup()

    def test_single_show_discovered_when_root_has_season_subdirs(self):
        """Selecting the show folder as batch root should yield one candidate."""
        service = TVLibraryDiscoveryService()
        candidates = service.discover_show_roots(self.root)

        self.assertEqual(len(candidates), 1,
                         f"Expected 1 candidate, got {len(candidates)}: "
                         f"{[c.relative_folder for c in candidates]}")
        self.assertEqual(candidates[0].folder, self.root)
        self.assertTrue(candidates[0].has_direct_season_subdirs)

    def test_second_season_detected_by_get_season(self):
        """The 'Second Season' folder should be recognized as season 2."""
        s2 = self.root / "[sam] Haikyuu!! Second Season [BD 1080p FLAC]"
        self.assertEqual(get_season(s2), 2)

    def test_s04_folder_detected_by_get_season(self):
        """The S04 folder should be recognized as season 4."""
        s4 = self.root / "Haikyuu!!.S04.1080p.Blu-Ray.10-Bit.Dual-Audio.DTS-HD.x265-iAHD"
        self.assertEqual(get_season(s4), 4)

    def test_karasuno_folder_not_detected_by_get_season(self):
        """The named-season folder has no season indicator in its name."""
        s3 = self.root / "[sam] Haikyuu!! Karasuno High School vs. Shiratorizawa Academy [BD 1080p FLAC]"
        # This is expected to return None — the TMDB name matching in
        # TVScanner handles this case, not get_season().
        self.assertIsNone(get_season(s3))


# ── Discovery: library root with show subfolder ────────────────────────


class HaikyuuLibraryDiscoveryTests(unittest.TestCase):
    """When the show folder is inside a library, it should still be
    discovered as a single show root (not split)."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.library = Path(self._tmp.name) / "Anime"
        show = self.library / "[sam] Haikyuu!! [BD 1080p FLAC]"
        show.mkdir(parents=True)

        (show / "Season 01").mkdir()
        (show / "Season 01" / "ep01.mkv").write_text("x")
        (show / "[sam] Haikyuu!! Second Season [BD 1080p FLAC]").mkdir()
        (show / "[sam] Haikyuu!! Second Season [BD 1080p FLAC]" / "ep01.mkv").write_text("x")
        (show / "Haikyuu!!.S04.1080p.Blu-Ray.10-Bit").mkdir()
        (show / "Haikyuu!!.S04.1080p.Blu-Ray.10-Bit" / "S04E01.mkv").write_text("x")

    def tearDown(self):
        self._tmp.cleanup()

    def test_library_root_discovers_single_show(self):
        """Library → show folder should yield one candidate."""
        service = TVLibraryDiscoveryService()
        candidates = service.discover_show_roots(self.library)
        self.assertEqual(len(candidates), 1)
        self.assertIn("Haikyuu", candidates[0].folder.name)
        self.assertTrue(candidates[0].has_direct_season_subdirs)


# ── TVScanner TMDB season name matching ────────────────────────────────


class TMDBSeasonNameMatchingTests(unittest.TestCase):
    """TVScanner._match_dirs_to_tmdb_seasons() should match folders like
    'Karasuno High School vs. Shiratorizawa Academy' to the correct TMDB
    season when the TMDB season name contains the same text."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name) / "[sam] Haikyuu!! [BD 1080p FLAC]"
        self.root.mkdir()

        # Create the non-standard season folder
        self.karasuno = self.root / "[sam] Haikyuu!! Karasuno High School vs. Shiratorizawa Academy [BD 1080p FLAC]"
        self.karasuno.mkdir()
        (self.karasuno / "[sam] Haikyuu!! S3 - 01.mkv").write_text("x")

        # Also create a "TO THE TOP" folder (season 4 name from TMDB)
        self.top = self.root / "Haikyuu!! TO THE TOP"
        self.top.mkdir()
        (self.top / "S04E01.mkv").write_text("x")

    def tearDown(self):
        self._tmp.cleanup()

    def test_match_karasuno_to_season_3(self):
        from plex_renamer.engine import TVScanner

        fake_tmdb = _FakeTMDB()
        show_info = {"id": 46260, "name": "Haikyu!!"}
        scanner = TVScanner(fake_tmdb, show_info, self.root)

        matched = scanner._match_dirs_to_tmdb_seasons(
            [self.karasuno],
            already_matched={1, 2, 4},
        )
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0][0], self.karasuno)
        self.assertEqual(matched[0][1], 3)

    def test_match_to_the_top_to_season_4(self):
        from plex_renamer.engine import TVScanner

        fake_tmdb = _FakeTMDB()
        show_info = {"id": 46260, "name": "Haikyu!!"}
        scanner = TVScanner(fake_tmdb, show_info, self.root)

        matched = scanner._match_dirs_to_tmdb_seasons(
            [self.top],
            already_matched={1, 2, 3},
        )
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0][1], 4)


class _FakeTMDB:
    """Minimal TMDB client stub with Haikyuu!! season data."""
    language = "en-US"

    _SHOW_DATA = {
        "id": 46260,
        "name": "Haikyu!!",
        "seasons": [
            {"season_number": 0, "name": "Specials", "episode_count": 9},
            {"season_number": 1, "name": "Haikyu!!", "episode_count": 25},
            {"season_number": 2, "name": "Haikyu!! 2nd Season", "episode_count": 25},
            {"season_number": 3, "name": "Haikyu!! Karasuno High School vs. Shiratorizawa Academy", "episode_count": 10},
            {"season_number": 4, "name": "Haikyu!! TO THE TOP", "episode_count": 25},
        ],
    }

    def get_tv_details(self, show_id):
        if show_id == 46260:
            return self._SHOW_DATA
        return None

    def get_season_map(self, show_id):
        if show_id != 46260:
            return {}, 0
        tmdb_seasons = {}
        total = 0
        for s in self._SHOW_DATA["seasons"]:
            sn = s["season_number"]
            count = s["episode_count"]
            tmdb_seasons[sn] = {
                "titles": {i: f"Episode {i}" for i in range(1, count + 1)},
                "posters": {},
                "episodes": {},
                "count": count,
            }
            if sn > 0:
                total += count
        return tmdb_seasons, total


if __name__ == "__main__":
    unittest.main()
