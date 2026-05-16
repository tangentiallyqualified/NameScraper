"""Tests for movie confidence postprocessing helpers in engine.matching."""
from __future__ import annotations

import unittest
from pathlib import Path

from plex_renamer.engine import apply_movie_confidence_adjustments
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


if __name__ == "__main__":
    unittest.main()


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
        self.assertLessEqual(result, 0.45)

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
        result = self._call(
            0.10,
            file_path=Path("/movies/Iron Man 2.mkv"),
            tmdb_title="Iron Man",
            tmdb_year="2008",
        )
        self.assertGreaterEqual(result, 0.0)
