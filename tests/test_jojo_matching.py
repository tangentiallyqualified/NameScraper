"""Tests for JoJo-style matching edge cases.

Covers:
  Bug 1 — bare-number OVA filenames detected as TV episodes
  Bug 2 — episode count tiebreaker in batch discovery
  Bug 3 — episode_confidence field on PreviewItem
"""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from plex_renamer.app.services import (
    MovieLibraryDiscoveryService,
    TVLibraryDiscoveryService,
)
from plex_renamer.engine import BatchTVOrchestrator
from plex_renamer.parsing import looks_like_tv_episode


# ── Bare-number OVA filenames (Bug 1) ──────────────────────────────────────

class BareNumberPatternTests(unittest.TestCase):
    """The ``01. Title Here.mkv`` naming convention should be recognized as TV."""

    OVA_FILENAMES = [
        "01. The Evil Spirit (2000).mkv",
        "02. Hierophant Green (2000).mkv",
        "08. Iggi The Fool and N'Dool The Geb (1993).mkv",
        "13. Dio's -The World- - Farewell, My Friends (1994).mkv",
    ]

    def test_bare_number_filenames_detected_as_tv(self):
        for name in self.OVA_FILENAMES:
            with self.subTest(name=name):
                self.assertTrue(
                    looks_like_tv_episode(Path(f"/tmp/OVA/{name}")),
                    f"Expected TV detection for: {name}",
                )

    def test_normal_movie_filenames_not_detected_as_tv(self):
        """Ensure the pattern doesn't false-positive on regular movie files."""
        movie_names = [
            "Inception (2010).mkv",
            "Die Hard (1988).mkv",
            "2001 A Space Odyssey.mkv",
            "Blade Runner (1982) - Final Cut.mkv",
        ]
        for name in movie_names:
            with self.subTest(name=name):
                self.assertFalse(
                    looks_like_tv_episode(Path(f"/tmp/Movies/{name}")),
                    f"False positive TV detection for movie: {name}",
                )


class MovieDiscoveryOVATests(unittest.TestCase):
    """OVA folders with bare-number files should NOT become movie candidates."""

    def test_ova_folder_excluded_from_movie_discovery(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            ova = root / "Jojos bizarre adventure"
            ova.mkdir()
            for name in [
                "01. The Evil Spirit (2000).mkv",
                "02. Hierophant Green (2000).mkv",
                "03. Silver Chariot and Strength (2000).mkv",
            ]:
                (ova / name).write_text("x")

            service = MovieLibraryDiscoveryService()
            candidates = service.discover_movie_roots(root)
            self.assertEqual(len(candidates), 0, "OVA folder should not be a movie candidate")

    def test_mixed_library_ova_excluded_movie_kept(self):
        """OVA folder excluded, proper movie folder kept."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)

            ova = root / "Jojos bizarre adventure"
            ova.mkdir()
            for i in range(1, 14):
                (ova / f"{i:02d}. Episode Title.mkv").write_text("x")

            movie = root / "Inception (2010)"
            movie.mkdir()
            (movie / "Inception.mkv").write_text("x")

            service = MovieLibraryDiscoveryService()
            candidates = service.discover_movie_roots(root)
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0].relative_folder, "Inception (2010)")


class TVDiscoveryOVATests(unittest.TestCase):
    """OVA folders with bare-number files SHOULD be found by TV discovery."""

    def test_ova_folder_included_in_tv_discovery(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            ova = root / "Jojos bizarre adventure"
            ova.mkdir()
            for name in [
                "01. The Evil Spirit (2000).mkv",
                "02. Hierophant Green (2000).mkv",
                "03. Silver Chariot and Strength (2000).mkv",
            ]:
                (ova / name).write_text("x")

            service = TVLibraryDiscoveryService()
            candidates = service.discover_show_roots(root)
            relative_paths = {c.relative_folder for c in candidates}
            self.assertIn("Jojos bizarre adventure", relative_paths)


# ── Episode count tiebreaker (Bug 2) ───────────────────────────────────────

class _FakeTMDBWithEpisodeCounts:
    """TMDB stub that returns two JoJo series with different episode counts."""

    JOJO_2012 = {
        "id": 31911,
        "name": "JoJo's Bizarre Adventure",
        "year": "2012",
        "poster_path": None,
        "overview": "2012 TV series",
    }
    JOJO_1993 = {
        "id": 29955,
        "name": "JoJo's Bizarre Adventure",
        "year": "1993",
        "poster_path": None,
        "overview": "1993 OVA",
    }

    DETAILS = {
        31911: {"number_of_episodes": 190, "number_of_seasons": 5},
        29955: {"number_of_episodes": 13, "number_of_seasons": 1},
    }

    def search_tv_batch(self, queries, progress_callback=None):
        results = []
        for i, (_name, _year) in enumerate(queries, 1):
            if progress_callback:
                progress_callback(i, len(queries))
            # Both series returned for every query, 2012 first (higher popularity)
            results.append([self.JOJO_2012, self.JOJO_1993])
        return results

    def get_tv_details(self, show_id):
        return self.DETAILS.get(show_id)


class EpisodeCountTiebreakerTests(unittest.TestCase):
    """When title scores are tied, prefer the TMDB match whose episode count
    is closest to the number of video files on disk."""

    def test_ova_folder_matches_ova_series_not_2012(self):
        """13-file OVA folder should match the 13-episode 1993 OVA, not the
        190-episode 2012 series."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            ova = root / "Jojos bizarre adventure"
            ova.mkdir()
            for i in range(1, 14):
                (ova / f"{i:02d}. Episode Title.mkv").write_text("x")

            orchestrator = BatchTVOrchestrator(
                _FakeTMDBWithEpisodeCounts(),
                root,
                discovery_service=TVLibraryDiscoveryService(),
            )
            states = orchestrator.discover_shows()

            self.assertEqual(len(states), 1)
            state = states[0]
            # Should pick the 1993 OVA (13 eps) over 2012 (190 eps)
            self.assertEqual(state.show_id, 29955,
                             f"Expected 1993 OVA (29955), got {state.show_id}")

    def test_large_folder_matches_large_series(self):
        """A folder with 48+ S##E## files should prefer the 190-episode 2012
        series over the 13-episode OVA."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            show = root / "JoJo's Bizarre Adventure (2012)"
            (show / "Season 01").mkdir(parents=True)
            for i in range(1, 49):
                (show / "Season 01" / f"S01E{i:02d}.mkv").write_text("x")

            orchestrator = BatchTVOrchestrator(
                _FakeTMDBWithEpisodeCounts(),
                root,
                discovery_service=TVLibraryDiscoveryService(),
            )
            states = orchestrator.discover_shows()

            self.assertEqual(len(states), 1)
            state = states[0]
            # Should pick the 2012 series (190 eps) over 1993 OVA (13 eps)
            self.assertEqual(state.show_id, 31911,
                             f"Expected 2012 series (31911), got {state.show_id}")


# ── Episode confidence field (Bug 3) ───────────────────────────────────────

class EpisodeConfidenceTests(unittest.TestCase):
    """PreviewItem.episode_confidence should reflect match quality."""

    def test_default_confidence_is_1(self):
        from plex_renamer.engine import PreviewItem
        item = PreviewItem(
            original=Path("/tmp/test.mkv"),
            new_name="test.mkv",
            target_dir=None,
            season=1,
            episodes=[1],
            status="OK",
        )
        self.assertEqual(item.episode_confidence, 1.0)

    def test_confidence_field_accepts_low_values(self):
        from plex_renamer.engine import PreviewItem
        item = PreviewItem(
            original=Path("/tmp/test.mkv"),
            new_name="test.mkv",
            target_dir=None,
            season=1,
            episodes=[1],
            status="OK",
            episode_confidence=0.3,
        )
        self.assertEqual(item.episode_confidence, 0.3)


if __name__ == "__main__":
    unittest.main()
