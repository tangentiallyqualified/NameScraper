"""Tests for movie confidence postprocessing helpers in engine.matching."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from plex_renamer.engine import MovieScanner, apply_movie_confidence_adjustments
from plex_renamer.engine.matching import (
    _collect_movie_evidence,
    _extract_sequel_number,
)


class ExtractSequelNumberTests(unittest.TestCase):
    def test_no_sequel_marker_returns_none(self):
        self.assertIsNone(_extract_sequel_number("Inception"))
        self.assertIsNone(_extract_sequel_number("The Matrix"))

    def test_arabic_numeral_suffix(self):
        self.assertEqual(_extract_sequel_number("Iron Man 2"), 2)
        self.assertEqual(_extract_sequel_number("Toy Story 3"), 3)
        self.assertEqual(_extract_sequel_number("Saw 7"), 7)

    def test_roman_numeral_suffix(self):
        self.assertEqual(_extract_sequel_number("Rocky II"), 2)
        self.assertEqual(_extract_sequel_number("Halloween III"), 3)
        self.assertEqual(_extract_sequel_number("Star Wars: Episode IV"), 4)

    def test_part_phrasing(self):
        self.assertEqual(_extract_sequel_number("Kill Bill Part 2"), 2)
        self.assertEqual(_extract_sequel_number("Kill Bill: Part II"), 2)
        self.assertEqual(_extract_sequel_number("Dune: Part Two"), 2)

    def test_chapter_phrasing(self):
        self.assertEqual(_extract_sequel_number("John Wick: Chapter 3"), 3)
        self.assertEqual(_extract_sequel_number("It Chapter Two"), 2)

    def test_year_is_not_sequel(self):
        self.assertIsNone(_extract_sequel_number("Blade Runner 2049"))
        self.assertIsNone(_extract_sequel_number("Inception (2010)"))

    def test_case_insensitive(self):
        self.assertEqual(_extract_sequel_number("iron man 2"), 2)
        self.assertEqual(_extract_sequel_number("rocky ii"), 2)


class CollectMovieEvidenceTests(unittest.TestCase):
    def test_exact_title_match_from_filename(self):
        ev = _collect_movie_evidence(
            file_path=Path("/movies/Inception.2010.mkv"),
            tmdb_title="Inception",
            tmdb_year="2010",
        )
        self.assertTrue(ev.exact_title_match)
        self.assertTrue(ev.year_exact_match)
        self.assertFalse(ev.year_severely_off)
        self.assertFalse(ev.folder_corroborates_title)
        self.assertFalse(ev.sequel_mismatch)

    def test_folder_corroborates_title_with_year(self):
        ev = _collect_movie_evidence(
            file_path=Path("/movies/Inception (2010)/movie.mkv"),
            tmdb_title="Inception",
            tmdb_year="2010",
        )
        self.assertTrue(ev.folder_corroborates_title)
        self.assertTrue(ev.year_exact_match)

    def test_folder_corroborates_without_year(self):
        ev = _collect_movie_evidence(
            file_path=Path("/movies/Inception/movie.mkv"),
            tmdb_title="Inception",
            tmdb_year="2010",
        )
        self.assertTrue(ev.folder_corroborates_title)

    def test_year_severely_off_three_or_more(self):
        ev = _collect_movie_evidence(
            file_path=Path("/movies/Inception.2008.mkv"),
            tmdb_title="Inception",
            tmdb_year="2010",
        )
        self.assertFalse(ev.year_exact_match)
        self.assertFalse(ev.year_severely_off)  # diff is 2

        ev = _collect_movie_evidence(
            file_path=Path("/movies/Inception.2007.mkv"),
            tmdb_title="Inception",
            tmdb_year="2010",
        )
        self.assertTrue(ev.year_severely_off)  # diff is 3

    def test_no_filename_year_yields_no_year_evidence(self):
        ev = _collect_movie_evidence(
            file_path=Path("/movies/Inception.mkv"),
            tmdb_title="Inception",
            tmdb_year="2010",
        )
        self.assertFalse(ev.year_exact_match)
        self.assertFalse(ev.year_severely_off)

    def test_sequel_mismatch_filename_has_number(self):
        ev = _collect_movie_evidence(
            file_path=Path("/movies/Iron Man 2.mkv"),
            tmdb_title="Iron Man",
            tmdb_year="2008",
        )
        self.assertTrue(ev.sequel_mismatch)

    def test_sequel_mismatch_tmdb_has_number(self):
        ev = _collect_movie_evidence(
            file_path=Path("/movies/Iron Man.mkv"),
            tmdb_title="Iron Man 2",
            tmdb_year="2010",
        )
        self.assertTrue(ev.sequel_mismatch)

    def test_sequel_numbers_match(self):
        ev = _collect_movie_evidence(
            file_path=Path("/movies/Iron Man 2.mkv"),
            tmdb_title="Iron Man 2",
            tmdb_year="2010",
        )
        self.assertFalse(ev.sequel_mismatch)

    def test_no_sequel_on_either_side(self):
        ev = _collect_movie_evidence(
            file_path=Path("/movies/Inception.mkv"),
            tmdb_title="Inception",
            tmdb_year="2010",
        )
        self.assertFalse(ev.sequel_mismatch)


class ApplyMovieConfidenceAdjustmentsTests(unittest.TestCase):
    def _call(self, raw, **kwargs):
        return apply_movie_confidence_adjustments(
            raw_confidence=raw,
            file_path=kwargs.get("file_path", Path("/movies/Inception.mkv")),
            tmdb_title=kwargs.get("tmdb_title", "Inception"),
            tmdb_year=kwargs.get("tmdb_year", "2010"),
        )

    def test_exact_title_match_floors_to_095(self):
        result = self._call(0.42, file_path=Path("/movies/Inception.mkv"))
        self.assertGreaterEqual(result, 0.95)

    def test_year_exact_match_floors_to_085(self):
        # No exact title (filename differs), but year matches exactly.
        result = self._call(
            0.20,
            file_path=Path("/movies/incept.2010.mkv"),
            tmdb_title="Inception",
            tmdb_year="2010",
        )
        self.assertGreaterEqual(result, 0.85)

    def test_folder_corroborates_floors_to_088(self):
        result = self._call(
            0.30,
            file_path=Path("/movies/Inception/movie.mkv"),
            tmdb_title="Inception",
            tmdb_year="2010",
        )
        self.assertGreaterEqual(result, 0.88)

    def test_year_severely_off_caps_to_045(self):
        result = self._call(
            0.98,
            file_path=Path("/movies/Inception.2007.mkv"),
            tmdb_title="Inception",
            tmdb_year="2010",
        )
        self.assertLessEqual(result, 0.45)

    def test_sequel_mismatch_caps_to_050(self):
        result = self._call(
            0.95,
            file_path=Path("/movies/Iron Man 2.mkv"),
            tmdb_title="Iron Man",
            tmdb_year="2008",
        )
        self.assertLessEqual(result, 0.50)

    def test_cap_wins_over_floor(self):
        # Exact title match (floor 0.95) AND year severely off (cap 0.45) → 0.45.
        result = self._call(
            0.95,
            file_path=Path("/movies/Inception.2007.mkv"),
            tmdb_title="Inception",
            tmdb_year="2010",
        )
        # Exact equality: floor applied (raw 0.95 already at/above floor 0.95),
        # then cap brings it down to exactly MOVIE_CAP_YEAR_SEVERELY_OFF (0.45).
        self.assertAlmostEqual(result, 0.45, places=6)

    def test_no_evidence_leaves_score_unchanged(self):
        result = self._call(
            0.62,
            file_path=Path("/movies/totally_different.mkv"),
            tmdb_title="Inception",
            tmdb_year="2010",
        )
        self.assertAlmostEqual(result, 0.62, places=3)

    def test_never_exceeds_one(self):
        result = self._call(1.0, file_path=Path("/movies/Inception.mkv"))
        self.assertLessEqual(result, 1.0)

    def test_never_below_zero(self):
        # Negative raw input is clamped to 0.0 even with no evidence triggering.
        result = self._call(
            -0.1,
            file_path=Path("/movies/totally_different.mkv"),
            tmdb_title="Unknown",
            tmdb_year="2010",
        )
        self.assertGreaterEqual(result, 0.0)

    def test_year_none_leaves_year_evidence_inactive(self):
        # With tmdb_year=None, neither the year-exact floor nor the year-severely-off
        # cap should fire. Only title evidence remains, so an exact title match still
        # floors to 0.95.
        result = self._call(
            0.42,
            file_path=Path("/movies/Inception.2010.mkv"),  # filename has a year
            tmdb_title="Inception",
            tmdb_year=None,
        )
        self.assertGreaterEqual(result, 0.95)  # title floor applies

        # No title evidence, no year evidence → raw passes through.
        result_neutral = self._call(
            0.55,
            file_path=Path("/movies/totally_different.2010.mkv"),
            tmdb_title="Inception",
            tmdb_year=None,
        )
        self.assertAlmostEqual(result_neutral, 0.55, places=6)


class MovieScannerConfidenceTests(unittest.TestCase):
    def _make_scanner(self, tmp: Path, tmdb_results: list[dict]) -> MovieScanner:
        tmdb = MagicMock()
        tmdb.language = "en-US"
        tmdb.search_movies_batch.return_value = [tmdb_results, tmdb_results, tmdb_results]
        tmdb.search_with_fallback.return_value = tmdb_results
        tmdb.search_movie.return_value = tmdb_results
        tmdb.get_alternative_titles.return_value = []
        return MovieScanner(tmdb, tmp)

    def test_preview_item_carries_real_confidence(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "Inception.2010.mkv").touch()
            (tmp / "filler1.mkv").touch()
            (tmp / "filler2.mkv").touch()
            scanner = self._make_scanner(tmp, [
                {"id": 27205, "title": "Inception", "year": "2010",
                 "poster_path": None, "overview": ""},
            ])
            items = scanner.scan()
            inception = next(i for i in items if "Inception" in i.original.name)
            self.assertGreaterEqual(inception.episode_confidence, 0.95)

    def test_review_status_set_for_low_confidence(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "Iron Man 2.mkv").touch()
            (tmp / "filler1.mkv").touch()
            (tmp / "filler2.mkv").touch()
            # TMDB returns Iron Man (no 2) — sequel-mismatch cap should fire.
            scanner = self._make_scanner(tmp, [
                {"id": 1726, "title": "Iron Man", "year": "2008",
                 "poster_path": None, "overview": ""},
            ])
            items = scanner.scan()
            iron = next(i for i in items if "Iron Man" in i.original.name)
            self.assertLessEqual(iron.episode_confidence, 0.50)
            self.assertTrue(iron.status.startswith("REVIEW"))

    def test_no_tmdb_results_yields_zero_confidence(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "Some Mystery Film.mkv").touch()
            (tmp / "filler1.mkv").touch()
            (tmp / "filler2.mkv").touch()
            scanner = self._make_scanner(tmp, [])  # empty TMDB results
            items = scanner.scan()
            mystery = next(i for i in items if "Some Mystery" in i.original.name)
            self.assertEqual(mystery.episode_confidence, 0.0)
            self.assertTrue(mystery.status.startswith("REVIEW"))


if __name__ == "__main__":
    unittest.main()
