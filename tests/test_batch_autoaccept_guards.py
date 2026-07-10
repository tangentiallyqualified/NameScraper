"""Batch auto-accept guards (M-H1 / M-H2 from the 2026-07-10 review).

M-H1: the TV winner's score must be clamped to the same [0, 1] scale as the
runner-up before tie detection, and the stored confidence must never exceed
1.0 — otherwise two identically-named shows (Ghosts US vs UK) fake a 0.15
margin and silently auto-accept the more popular one.

M-H2: the batch movie path must run the same
``apply_movie_confidence_adjustments`` caps as the interactive scanner, so a
sequel-number mismatch (Iron Man folder -> Iron Man 2 result) stays capped
below auto-accept.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from plex_renamer.engine._batch_orchestrators import (
    BatchMovieOrchestrator,
    BatchTVOrchestrator,
)
from plex_renamer.engine.matching import MOVIE_CAP_SEQUEL_MISMATCH
from plex_renamer.app.services import (
    MovieLibraryDiscoveryService,
    TVLibraryDiscoveryService,
)


class _FakeTMDBSameNameShows:
    """Two shows with the SAME name (US/UK remake pair), no usable details."""

    language = "en-US"

    GHOSTS_US = {
        "id": 111,
        "name": "Ghosts",
        "year": "2021",
        "poster_path": None,
        "overview": "US remake (more popular, ranked first)",
    }
    GHOSTS_UK = {
        "id": 222,
        "name": "Ghosts",
        "year": "2019",
        "poster_path": None,
        "overview": "UK original",
    }

    def search_tv_batch(self, queries, progress_callback=None):
        results = []
        for i, _query in enumerate(queries, 1):
            if progress_callback:
                progress_callback(i, len(queries))
            results.append([self.GHOSTS_US, self.GHOSTS_UK])
        return results

    def get_tv_details(self, show_id):
        return {}

    def get_season_map(self, show_id):
        return {}, 0

    def get_alternative_titles(self, media_id, media_type="tv"):
        return []


class SameNameShowTieDetectionTests(unittest.TestCase):
    def test_same_name_shows_without_year_hint_flag_a_tie(self):
        """A folder named just "Ghosts" (no year) matching two exact-name
        shows must surface tie_detected, not silently auto-accept the more
        popular one at an out-of-scale confidence."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            show = root / "Ghosts"
            show.mkdir()
            for i in range(1, 4):
                (show / f"Ghosts.S01E{i:02d}.mkv").write_text("x")

            orchestrator = BatchTVOrchestrator(
                _FakeTMDBSameNameShows(),
                root,
                discovery_service=TVLibraryDiscoveryService(),
            )
            states = orchestrator.discover_shows()

            self.assertEqual(len(states), 1)
            state = states[0]
            self.assertLessEqual(
                state.confidence, 1.0,
                f"confidence must stay on the [0,1] scale, got {state.confidence}",
            )
            self.assertTrue(
                state.tie_detected,
                "two exact-name candidates with no distinguishing evidence "
                "must be flagged as a tie",
            )


class _FakeTMDBSequelMovie:
    """Search returns the sequel first for an Iron Man (2008) query."""

    language = "en-US"

    IRON_MAN_2 = {
        "id": 333,
        "title": "Iron Man 2",
        "year": "2010",
        "poster_path": None,
        "overview": "the sequel, ranked first",
    }

    def search_movies_batch(self, queries, progress_callback=None):
        results = []
        for i, _query in enumerate(queries, 1):
            if progress_callback:
                progress_callback(i, len(queries))
            results.append([self.IRON_MAN_2])
        return results

    def get_movie_details(self, movie_id):
        return {}

    def get_alternative_titles(self, media_id, media_type="movie"):
        return []


class BatchMovieConfidenceCapTests(unittest.TestCase):
    def test_sequel_mismatch_capped_in_batch_discovery(self):
        """The sequel-number-mismatch cap the interactive MovieScanner
        applies must also run in batch discovery."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            movie = root / "Iron Man (2008)"
            movie.mkdir()
            (movie / "Iron Man (2008).mkv").write_text("x")

            orchestrator = BatchMovieOrchestrator(
                _FakeTMDBSequelMovie(),
                root,
                discovery_service=MovieLibraryDiscoveryService(),
            )
            states = orchestrator.discover_movies()

            self.assertEqual(len(states), 1)
            state = states[0]
            self.assertLessEqual(
                state.confidence, MOVIE_CAP_SEQUEL_MISMATCH,
                "sequel-number mismatch must cap batch confidence to "
                f"{MOVIE_CAP_SEQUEL_MISMATCH}, got {state.confidence}",
            )


if __name__ == "__main__":
    unittest.main()
