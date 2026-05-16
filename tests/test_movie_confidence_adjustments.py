"""Tests for movie confidence postprocessing helpers in engine.matching."""
from __future__ import annotations

import unittest

from plex_renamer.engine.matching import _extract_sequel_number


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
