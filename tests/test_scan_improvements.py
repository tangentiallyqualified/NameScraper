from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from plex_renamer.app.services import TVLibraryDiscoveryService
from plex_renamer.engine import BatchTVOrchestrator
from plex_renamer.job_executor import revert_job
from plex_renamer.job_store import RenameJob


class _FakeTMDB:
    language = "en-US"

    def search_tv_batch(self, queries, progress_callback=None):
        results = []
        total = len(queries)
        for index, (_name, _year) in enumerate(queries, start=1):
            if progress_callback:
                progress_callback(index, total)
            results.append([
                {
                    "id": 100,
                    "name": "Naruto",
                    "year": "2002",
                    "poster_path": None,
                    "overview": "",
                    "number_of_seasons": 1,
                    "number_of_episodes": 220,
                }
            ])
        return results

    def get_alternative_titles(self, media_id, media_type="tv"):
        return []

    def get_tv_details(self, show_id):
        return {"number_of_seasons": 1, "number_of_episodes": 12}


class ScanImprovementTests(unittest.TestCase):
    def test_nested_discovery_finds_show_roots_but_not_containers_or_movies(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Anime" / "Naruto" / "Season 01").mkdir(parents=True)
            (root / "Anime" / "Naruto" / "Season 01" / "Naruto - S01E01.mkv").write_text("x")
            (root / "Sci-Fi" / "Battlestar Galactica (2004)" / "Season 01").mkdir(parents=True)
            (
                root
                / "Sci-Fi"
                / "Battlestar Galactica (2004)"
                / "Season 01"
                / "Battlestar Galactica - S01E01.mkv"
            ).write_text("x")
            (root / "Movies" / "Inception (2010)").mkdir(parents=True)
            (root / "Movies" / "Inception (2010)" / "Inception.2010.1080p.mkv").write_text("x")

            service = TVLibraryDiscoveryService()
            candidates = service.discover_show_roots(root)
            relative_paths = {candidate.relative_folder for candidate in candidates}

            self.assertEqual(
                relative_paths,
                {
                    "Anime/Naruto",
                    "Sci-Fi/Battlestar Galactica (2004)",
                },
            )

    def test_duplicate_resolution_keeps_primary_relative_path(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Anime" / "Naruto" / "Season 01").mkdir(parents=True)
            (root / "Anime" / "Naruto" / "Season 01" / "Naruto - S01E01.mkv").write_text("x")
            (root / "Anime" / "Naruto Alt" / "Season 01").mkdir(parents=True)
            (root / "Anime" / "Naruto Alt" / "Season 01" / "Naruto - S01E01.mkv").write_text("x")

            orchestrator = BatchTVOrchestrator(
                _FakeTMDB(),
                root,
                discovery_service=TVLibraryDiscoveryService(),
            )

            states = orchestrator.discover_shows()
            by_path = {state.relative_folder: state for state in states}

            self.assertIn("Anime/Naruto", by_path)
            self.assertIn("Anime/Naruto Alt", by_path)

            primary = by_path["Anime/Naruto"]
            duplicate = by_path["Anime/Naruto Alt"]

            self.assertIsNone(primary.duplicate_of)
            self.assertTrue(primary.checked)
            self.assertEqual(duplicate.duplicate_of, primary.display_name)
            self.assertEqual(duplicate.duplicate_of_relative_folder, primary.relative_folder)
            self.assertFalse(duplicate.checked)

    def test_folder_named_with_s01_and_nested_season_dir_is_discovered_as_show(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            show = root / "[CW] Akiba Maid War S01 [Dual Audio][BD 1080p][FLAC + AAC][AVC] - Akiba Meido Sensou S01"
            (show / "season 1").mkdir(parents=True)
            (show / "season 1" / "Akiba.Maid.War.S01E01.mkv").write_text("x")
            (show / "extra").mkdir()

            service = TVLibraryDiscoveryService()
            candidates = service.discover_show_roots(root)

            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0].relative_folder, show.name)
            self.assertTrue(candidates[0].has_direct_season_subdirs)

    def test_tv_discovery_keeps_runner_up_suggestions_for_review_items(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            show = root / "Man DOk Ngew (2016)"
            (show / "Season 01").mkdir(parents=True)
            (show / "Season 01" / "Man.DOk.Ngew.S01E01.mkv").write_text("x")

            orchestrator = BatchTVOrchestrator(
                _FakeTMDB(),
                root,
                discovery_service=TVLibraryDiscoveryService(),
            )
            scored = [
                ({"id": 1, "name": "Man Dok Ngew", "year": "2016"}, 0.28),
                ({"id": 2, "name": "Marn Dok Ngeo", "year": "2016"}, 0.22),
                ({"id": 3, "name": "Dok Ngew", "year": "2017"}, 0.18),
            ]

            with patch("plex_renamer.engine.score_results", return_value=scored), patch(
                "plex_renamer.engine.boost_scores_with_alt_titles",
                side_effect=lambda scored, *args, **kwargs: scored,
            ):
                states = orchestrator.discover_shows()

            self.assertEqual(len(states), 1)
            self.assertTrue(states[0].needs_review)
            self.assertEqual([match["id"] for match in states[0].alternate_matches], [2, 3])

    def test_revert_cleanup_preserves_nested_container_boundary(self):
        with TemporaryDirectory() as tmp:
            library_root = Path(tmp) / "TV Root"
            generated_dir = library_root / "Documentaries" / "Generated" / "Season 01"
            generated_dir.mkdir(parents=True)
            restored_file = library_root / "restored.txt"
            generated_file = generated_dir / "restored.txt"
            generated_file.write_text("x")

            job = RenameJob(
                library_root=str(library_root),
                source_folder="Documentaries/Show",
                undo_data={
                    "renames": [
                        {
                            "old": str(restored_file),
                            "new": str(generated_file),
                        }
                    ],
                    "created_dirs": [
                        str(generated_dir),
                    ],
                    "removed_dirs": [],
                    "renamed_dirs": [],
                },
            )

            success, errors = revert_job(job)

            self.assertTrue(success, errors)
            self.assertEqual(errors, [])
            self.assertTrue(restored_file.exists())
            self.assertTrue((library_root / "Documentaries").exists())
            self.assertFalse((library_root / "Documentaries" / "Generated").exists())


    def test_movie_at_library_root_does_not_move_sibling_content(self):
        """Movies in the library root must not cause sibling dirs/files
        to be relocated into an Unmatched Files subfolder."""
        from plex_renamer.job_executor import _execute_rename
        from plex_renamer.job_store import RenameOp

        with TemporaryDirectory() as tmp:
            library_root = Path(tmp)

            # Movie file at the library root
            movie_file = library_root / "Dune.2021.2160p.mkv"
            movie_file.write_text("movie")

            # Sibling TV show directory that should NOT be touched
            tv_dir = library_root / "test_library" / "Breaking Bad" / "Season 01"
            tv_dir.mkdir(parents=True)
            tv_ep = tv_dir / "Breaking.Bad.S01E01.mkv"
            tv_ep.write_text("episode")

            # Another sibling movie file (different movie, not part of this job)
            other_movie = library_root / "Goodfellas.1990.mkv"
            other_movie.write_text("other")

            # Target directory for the renamed movie
            target = library_root / "Dune (2021)"

            job = RenameJob(
                library_root=str(library_root),
                source_folder=".",
                media_name="Dune",
                media_type="movie",
                rename_ops=[
                    RenameOp(
                        original_relative="Dune.2021.2160p.mkv",
                        new_name="Dune (2021).mkv",
                        target_dir_relative="Dune (2021)",
                        status="OK",
                        selected=True,
                    ),
                ],
            )

            result = _execute_rename(job)

            # The movie file should be renamed and moved
            self.assertEqual(result.renamed_count, 1)
            self.assertTrue((target / "Dune (2021).mkv").exists())
            self.assertFalse(movie_file.exists())

            # Sibling content must be untouched
            self.assertTrue(tv_ep.exists(),
                            "TV episode was errantly moved")
            self.assertTrue(other_movie.exists(),
                            "Sibling movie file was errantly moved")
            self.assertFalse((target / "Unmatched Files").exists(),
                             "Unmatched Files dir should not exist for root-level movies")


    def test_score_results_prefers_exact_year_over_adjacent_year(self):
        """When two TMDB results share an identical title, the one whose
        year exactly matches the hint must outscore the ±1 neighbour —
        the exact-title bonus must not clamp away the year signal."""
        from plex_renamer.engine import score_results

        results = [
            {"name": "Battlestar Galactica", "year": "2003", "id": 71365},
            {"name": "Battlestar Galactica", "year": "2004", "id": 73545},
        ]

        scored = score_results(results, "Battlestar Galactica", "2004",
                               title_key="name")
        best, best_score = scored[0]
        runner, runner_score = scored[1]

        self.assertEqual(best["year"], "2004",
                         "Exact year match must rank first")
        self.assertGreater(best_score, runner_score,
                           "Exact year must score strictly higher, not tie")

    def test_score_results_both_bsg_coexist_correctly(self):
        """Two BSG folders with different years must each match correctly."""
        from plex_renamer.engine import score_results

        results = [
            {"name": "Battlestar Galactica", "year": "2003", "id": 71365},
            {"name": "Battlestar Galactica", "year": "2004", "id": 73545},
        ]

        # Folder says 2003 → should match the miniseries
        scored_2003 = score_results(results, "Battlestar Galactica", "2003",
                                    title_key="name")
        self.assertEqual(scored_2003[0][0]["year"], "2003")

        # Folder says 2004 → should match the main series
        scored_2004 = score_results(results, "Battlestar Galactica", "2004",
                                    title_key="name")
        self.assertEqual(scored_2004[0][0]["year"], "2004")

    def test_season_count_tiebreaker_overrides_wrong_year(self):
        """When a folder says 2003 but has 4 season subdirs, the tiebreaker
        must prefer the 4-season series over the miniseries, even though
        the miniseries has a better year match."""
        from plex_renamer.engine import score_results, BatchTVOrchestrator

        results = [
            {"name": "Battlestar Galactica", "year": "2003", "id": 1001},
            {"name": "Battlestar Galactica", "year": "2004", "id": 1002},
        ]

        # Folder says 2003 → miniseries scores higher by year alone
        scored = score_results(results, "Battlestar Galactica", "2003",
                               title_key="name")
        self.assertEqual(scored[0][0]["id"], 1001, "Year scoring should favour 2003")
        self.assertLessEqual(scored[0][1] - scored[1][1], 0.10,
                             "Scores must be close enough for tiebreaker")

        # Now simulate the tiebreaker with 4 season subdirs on disk
        class _FakeTMDB:
            language = "en-US"
            def get_tv_details(self, show_id):
                if show_id == 1001:
                    return {"number_of_seasons": 1, "number_of_episodes": 2}
                if show_id == 1002:
                    return {"number_of_seasons": 4, "number_of_episodes": 75}
                return None

        orch = BatchTVOrchestrator.__new__(BatchTVOrchestrator)
        orch.tmdb = _FakeTMDB()

        best, _ = orch._episode_count_tiebreak(
            scored, file_count=4, threshold=0.10, compare_seasons=True,
        )
        self.assertEqual(best["id"], 1002,
                         "4 season subdirs must pick the 4-season series")


if __name__ == "__main__":
    unittest.main()