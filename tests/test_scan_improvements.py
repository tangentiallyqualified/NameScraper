from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from plex_renamer.app.services import TVLibraryDiscoveryService
from plex_renamer.app.models import TVDirectoryRole
from plex_renamer.engine import BatchTVOrchestrator, score_tv_results, TVScanner
from plex_renamer.job_executor import revert_job
from plex_renamer.job_store import RenameJob
from plex_renamer.parsing import best_tv_match_title


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

    def get_season(self, show_id, season_num):
        details = self.get_tv_details(show_id)
        count = details.get("number_of_episodes", 0) if season_num == 1 else 0
        titles = {episode: f"Episode {episode}" for episode in range(1, count + 1)}
        return {"titles": titles, "posters": {}, "episodes": {}, "count": count}

    def get_season_map(self, show_id):
        season = self.get_season(show_id, 1)
        return ({1: season}, season["count"])


class _RecordingTVTMDB(_FakeTMDB):
    def __init__(self):
        self.queries: list[tuple[str, str | None]] = []

    def search_tv_batch(self, queries, progress_callback=None):
        self.queries = list(queries)
        results = []
        total = len(queries)
        for index, (_name, _year) in enumerate(queries, start=1):
            if progress_callback:
                progress_callback(index, total)
            results.append([
                {
                    "id": 87108,
                    "name": "Chernobyl",
                    "year": "2019",
                    "poster_path": None,
                    "overview": "",
                },
                {
                    "id": 85716,
                    "name": "Chernobyl, la serie",
                    "year": "2018",
                    "poster_path": None,
                    "overview": "",
                },
                {
                    "id": 102179,
                    "name": "Chornobyl: Aftermath",
                    "year": "2016",
                    "poster_path": None,
                    "overview": "",
                },
            ])
        return results

    def get_tv_details(self, show_id):
        details = {
            87108: {"number_of_seasons": 1, "number_of_episodes": 5},
            85716: {"number_of_seasons": 1, "number_of_episodes": 5},
            102179: {"number_of_seasons": 1, "number_of_episodes": 4},
        }
        return details.get(show_id, super().get_tv_details(show_id))


class _FakeYuruCampTMDB(_FakeTMDB):
    language = "en-US"

    ANIME = {
        "id": 101,
        "name": "Laid-Back Camp",
        "year": "2018",
        "poster_path": None,
        "overview": "Anime series",
    }
    DRAMA = {
        "id": 202,
        "name": "Yuru Camp△",
        "year": "2020",
        "poster_path": None,
        "overview": "Live-action drama",
    }

    _SEASON_MAPS = {
        101: {
            0: {"titles": {1: "Heya Camp"}, "posters": {}, "episodes": {}, "count": 1},
            1: {"titles": {1: "Mount Fuji and Curry Noodles"}, "posters": {}, "episodes": {}, "count": 1},
            2: {
                "titles": {
                    1: "Curry Noodles Are the Best Travel Companion",
                    2: "New Year's Solo Camper Girl",
                },
                "posters": {},
                "episodes": {},
                "count": 2,
            },
            3: {
                "titles": {1: "Where Should We Go Next"},
                "posters": {},
                "episodes": {},
                "count": 1,
            },
        },
        202: {
            1: {"titles": {1: "First Day Camping", 2: "Club Meeting"}, "posters": {}, "episodes": {}, "count": 2},
            2: {"titles": {1: "A New Semester", 2: "Rainy Camp"}, "posters": {}, "episodes": {}, "count": 2},
        },
        303: {
            1: {"titles": {1: "Episode One", 2: "Episode Two"}, "posters": {}, "episodes": {}, "count": 2},
            2: {"titles": {1: "Episode Three", 2: "Episode Four"}, "posters": {}, "episodes": {}, "count": 2},
            3: {"titles": {1: "Episode Five", 2: "Episode Six"}, "posters": {}, "episodes": {}, "count": 2},
        },
    }

    def search_tv_batch(self, queries, progress_callback=None):
        results = []
        total = len(queries)
        for index, (_name, _year) in enumerate(queries, start=1):
            if progress_callback:
                progress_callback(index, total)
            results.append([self.DRAMA, self.ANIME])
        return results

    def get_alternative_titles(self, media_id, media_type="tv"):
        if media_id == 101:
            return [("Yuru Camp△", "JP")]
        return []

    def get_tv_details(self, show_id):
        seasons = self._SEASON_MAPS.get(show_id, {})
        return {
            "number_of_seasons": len([sn for sn in seasons if sn > 0]),
            "number_of_episodes": sum(data["count"] for sn, data in seasons.items() if sn > 0),
            "seasons": [
                {"season_number": sn, "name": f"Season {sn}", "episode_count": data["count"]}
                for sn, data in sorted(seasons.items())
            ],
        }

    def get_season_map(self, show_id):
        seasons = self._SEASON_MAPS.get(show_id, {})
        total = sum(data["count"] for sn, data in seasons.items() if sn > 0)
        return seasons, total

    def get_season(self, show_id, season_num):
        return self._SEASON_MAPS.get(show_id, {}).get(
            season_num,
            {"titles": {}, "posters": {}, "episodes": {}, "count": 0},
        )


class ScanImprovementTests(unittest.TestCase):
    def test_tv_classify_directory_marks_explicit_episode_folder_as_show_root(self):
        with TemporaryDirectory() as tmp:
            show = Path(tmp) / "Yuru Camp△"
            show.mkdir()
            (show / "Yuru Camp△ - S01E01 - Pilot.mkv").write_text("x")
            (show / "Yuru Camp△ - S01E02 - Second.mkv").write_text("x")

            service = TVLibraryDiscoveryService()

            self.assertEqual(service.classify_directory(show), TVDirectoryRole.SHOW_ROOT)

    def test_specials_only_bundle_is_treated_as_container_and_discovers_nested_children(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = root / "[UDF] Yuru Camp△ + Heya Camp△ (BDRip 1080p x264 FLAC)"
            season_one = bundle / "Yuru Camp△"
            specials = bundle / "Yuru Camp△ Specials"
            season_one.mkdir(parents=True)
            specials.mkdir()
            (season_one / "Yuru Camp△ - S01E01 - Pilot.mkv").write_text("x")
            (specials / "01.mkv").write_text("x")

            service = TVLibraryDiscoveryService()

            self.assertEqual(service.classify_directory(bundle), TVDirectoryRole.CONTAINER)

            candidates = service.discover_show_roots(root)
            relative_paths = {candidate.relative_folder for candidate in candidates}

            self.assertNotIn(bundle.name, relative_paths)
            self.assertIn(f"{bundle.name}/Yuru Camp△", relative_paths)
            self.assertIn(f"{bundle.name}/Yuru Camp△ Specials", relative_paths)

    def test_tv_discovery_infers_season_assignment_from_explicit_episode_files(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            season_one = root / "Yuru Camp△"
            season_one.mkdir()
            (season_one / "Yuru Camp△ - S01E01 - Pilot.mkv").write_text("x")
            (season_one / "Yuru Camp△ - S01E02 - Second.mkv").write_text("x")

            orchestrator = BatchTVOrchestrator(
                _FakeYuruCampTMDB(),
                root,
                discovery_service=TVLibraryDiscoveryService(),
            )

            states = orchestrator.discover_shows()

            self.assertEqual(len(states), 1)
            self.assertEqual(states[0].season_assignment, 1)

    def test_score_tv_results_matches_episode_evidence_ranking(self):
        with TemporaryDirectory() as tmp:
            folder = Path(tmp) / "[UDF] Yuru Camp△ + Heya Camp△ (BDRip 1080p x264 FLAC)"
            folder.mkdir()
            for name in [
                "Yuru Camp△ - S02E01 - Curry Noodles Are the Best Travel Companion.mkv",
                "Yuru Camp△ - S03E01 - Where Should We Go Next.mkv",
                "Yuru Camp△ - S02E02 - New Year's Solo Camper Girl.mkv",
            ]:
                (folder / name).write_text("x")

            tmdb = _FakeYuruCampTMDB()
            scored = score_tv_results(
                [tmdb.DRAMA, tmdb.ANIME],
                "Yuru Camp△",
                None,
                tmdb,
                folder=folder,
            )

            self.assertEqual(scored[0][0]["id"], tmdb.ANIME["id"])
            self.assertGreater(scored[0][1], scored[1][1])

    def test_tv_discovery_prefers_episode_evidence_over_exact_wrong_primary_title(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            show = root / "[UDF] Yuru Camp△ + Heya Camp△ (BDRip 1080p x264 FLAC)"
            show.mkdir()
            (show / "Yuru Camp△ Specials").mkdir()
            for name in [
                "Yuru Camp△ - S02E01 - Curry Noodles Are the Best Travel Companion.mkv",
                "Yuru Camp△ - S03E01 - Where Should We Go Next.mkv",
                "Yuru Camp△ - S02E02 - New Year's Solo Camper Girl.mkv",
            ]:
                (show / name).write_text("x")

            orchestrator = BatchTVOrchestrator(
                _FakeYuruCampTMDB(),
                root,
                discovery_service=TVLibraryDiscoveryService(),
            )

            states = orchestrator.discover_shows()

            self.assertEqual(len(states), 1)
            self.assertEqual(states[0].show_id, 101)
            self.assertEqual(states[0].media_info["name"], "Laid-Back Camp")

    def test_consolidated_preview_keeps_explicit_season_numbers_when_titles_do_not_match(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "[UDF] Yuru Camp△ + Heya Camp△ (BDRip 1080p x264 FLAC)"
            root.mkdir()
            filenames = [
                "Yuru Camp△ - S02E01 - Curry Noodles Are the Best Travel Companion.mkv",
                "Yuru Camp△ - S03E01 - Where Should We Go Next.mkv",
                "Yuru Camp△ - S02E02 - New Year's Solo Camper Girl.mkv",
            ]
            for name in filenames:
                (root / name).write_text("x")

            scanner = TVScanner(
                _FakeYuruCampTMDB(),
                {"id": 303, "name": "Other Camp", "year": "2020"},
                root,
            )

            items, has_mismatch = scanner.scan()
            by_name = {item.original.name: item for item in items}

            self.assertFalse(has_mismatch)
            self.assertEqual(by_name[filenames[0]].season, 2)
            self.assertEqual(by_name[filenames[0]].episodes, [1])
            self.assertEqual(by_name[filenames[1]].season, 3)
            self.assertEqual(by_name[filenames[1]].episodes, [1])
            self.assertEqual(by_name[filenames[2]].season, 2)
            self.assertEqual(by_name[filenames[2]].episodes, [2])

    def test_tv_scanner_marks_low_episode_confidence_for_review_using_episode_threshold(self):
        from plex_renamer.engine import set_episode_auto_accept_threshold

        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "Bartender"
            root.mkdir()
            (root / "Bartender 03.mkv").write_text("x")

            try:
                set_episode_auto_accept_threshold(0.85)
                scanner = TVScanner(
                    _FakeTMDB(),
                    {"id": 100, "name": "Bartender", "year": "2006"},
                    root,
                )

                items, _has_mismatch = scanner.scan()
            finally:
                set_episode_auto_accept_threshold(0.85)

            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].episode_confidence, 0.5)
            self.assertTrue(items[0].status.startswith("REVIEW"))

    def test_tv_scanner_attaches_sup_mks_subtitle_companions(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "Bartender"
            root.mkdir()
            video = root / "[Kawaiika-Raws] Bartender 03 [BDRip 1920x1080 HEVC FLAC].mkv"
            sidecar = root / "[Kawaiika-Raws] Bartender 03 [BDRip 1920x1080 HEVC FLAC].eng.[BD].sup.mks"
            video.write_text("video")
            sidecar.write_text("subtitle")

            scanner = TVScanner(
                _FakeTMDB(),
                {"id": 100, "name": "Bartender", "year": "2006"},
                root,
            )

            items, _has_mismatch = scanner.scan()

            self.assertEqual(len(items), 1)
            self.assertEqual(len(items[0].companions), 1)
            self.assertEqual(items[0].companions[0].original, sidecar)
            self.assertEqual(
                items[0].companions[0].new_name,
                "Bartender (2006) - S01E03 - Episode 3.eng.[BD].sup.mks",
            )

    def test_tv_discovery_uses_consistent_episode_title_over_noisy_folder_suffix(self):
        with TemporaryDirectory() as tmp:
            show = Path(tmp) / "chernobyl framestor"
            show.mkdir()
            for episode in range(1, 6):
                (
                    show
                    / f"Chernobyl.S01E0{episode}.2160p.DTS-HD.MA.5.1.DV.HEVC.REMUX-FraMeSToR.mkv"
                ).write_text("x")

            tmdb = _RecordingTVTMDB()
            orchestrator = BatchTVOrchestrator(
                tmdb,
                show,
                discovery_service=TVLibraryDiscoveryService(),
            )

            states = orchestrator.discover_shows()

            self.assertEqual(tmdb.queries, [("Chernobyl", None)])
            self.assertEqual(len(states), 1)
            self.assertEqual(states[0].show_id, 87108)
            self.assertEqual(states[0].media_info["name"], "Chernobyl")
            self.assertEqual(states[0].display_name, "Chernobyl (2019)")

    def test_best_tv_match_title_falls_back_when_episode_titles_disagree(self):
        with TemporaryDirectory() as tmp:
            show = Path(tmp) / "anthology framestor"
            show.mkdir()
            (show / "Show.One.S01E01.mkv").write_text("x")
            (show / "Show.Two.S01E02.mkv").write_text("x")

            self.assertEqual(
                best_tv_match_title(show, include_year=False),
                "anthology framestor",
            )

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
            self.assertFalse(primary.checked)
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

            with patch("plex_renamer.engine.matching.score_results", return_value=scored), patch(
                "plex_renamer.engine.matching.boost_scores_with_alt_titles",
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

    def test_queue_execute_keeps_final_tv_folder_clean_when_show_folder_is_renamed(self):
        from plex_renamer.constants import MediaType
        from plex_renamer.job_executor import _execute_rename
        from plex_renamer.job_store import RenameOp

        with TemporaryDirectory() as tmp:
            library_root = Path(tmp) / "TV Root"
            source_root = library_root / "Bleach"
            season_one = source_root / "Disc 01"
            season_two = source_root / "Disc 02"
            season_one.mkdir(parents=True)
            season_two.mkdir(parents=True)

            episode_one = season_one / "Bleach - 001.mkv"
            episode_two = season_two / "Bleach - 002.mkv"
            leftover = season_two / "notes.txt"
            episode_one.write_text("ep1")
            episode_two.write_text("ep2")
            leftover.write_text("keep")

            job = RenameJob(
                library_root=str(library_root),
                source_folder="Bleach",
                media_name="Bleach",
                media_type=MediaType.TV,
                show_folder_rename="Bleach (2004)",
                rename_ops=[
                    RenameOp(
                        original_relative="Bleach/Disc 01/Bleach - 001.mkv",
                        new_name="Bleach (2004) - S01E01.mkv",
                        target_dir_relative="Bleach/Season 01",
                        status="OK",
                        selected=True,
                    ),
                    RenameOp(
                        original_relative="Bleach/Disc 02/Bleach - 002.mkv",
                        new_name="Bleach (2004) - S01E02.mkv",
                        target_dir_relative="Bleach/Season 01",
                        status="OK",
                        selected=True,
                    ),
                ],
            )

            result = _execute_rename(job)

            final_root = library_root / "Bleach (2004)"
            self.assertEqual(result.errors, [])
            self.assertTrue((final_root / "Season 01" / "Bleach (2004) - S01E01.mkv").exists())
            self.assertTrue((final_root / "Season 01" / "Bleach (2004) - S01E02.mkv").exists())
            self.assertFalse((final_root / "Disc 01").exists())
            self.assertFalse((final_root / "Disc 02").exists())
            self.assertTrue(
                (
                    final_root
                    / "Season 01"
                    / "Unmatched Files"
                    / "notes.txt"
                ).exists()
            )
            self.assertNotIn(
                {"old": str(source_root), "new": str(final_root)},
                result.log_entry["renamed_dirs"],
            )

    def test_revert_job_succeeds_for_queue_execute_with_final_tv_folder(self):
        from plex_renamer.constants import MediaType
        from plex_renamer.job_executor import _execute_rename
        from plex_renamer.job_store import RenameOp

        with TemporaryDirectory() as tmp:
            library_root = Path(tmp) / "TV Root"
            source_root = library_root / "Bleach"
            season_one = source_root / "Disc 01"
            season_two = source_root / "Disc 02"
            season_one.mkdir(parents=True)
            season_two.mkdir(parents=True)

            episode_one = season_one / "Bleach - 001.mkv"
            episode_two = season_two / "Bleach - 002.mkv"
            episode_one.write_text("ep1")
            episode_two.write_text("ep2")

            job = RenameJob(
                library_root=str(library_root),
                source_folder="Bleach",
                media_name="Bleach",
                media_type=MediaType.TV,
                show_folder_rename="Bleach (2004)",
                rename_ops=[
                    RenameOp(
                        original_relative="Bleach/Disc 01/Bleach - 001.mkv",
                        new_name="Bleach (2004) - S01E01.mkv",
                        target_dir_relative="Bleach/Season 01",
                        status="OK",
                        selected=True,
                    ),
                    RenameOp(
                        original_relative="Bleach/Disc 02/Bleach - 002.mkv",
                        new_name="Bleach (2004) - S01E02.mkv",
                        target_dir_relative="Bleach/Season 01",
                        status="OK",
                        selected=True,
                    ),
                ],
            )

            result = _execute_rename(job)
            job.status = "completed"
            job.undo_data = result.log_entry

            ok, errors = revert_job(job)

            self.assertTrue(ok, errors)
            self.assertEqual(errors, [])
            self.assertTrue((source_root / "Disc 01" / "Bleach - 001.mkv").exists())
            self.assertTrue((source_root / "Disc 02" / "Bleach - 002.mkv").exists())
            self.assertFalse((library_root / "Bleach (2004)").exists())


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

    def test_movie_at_library_root_ignores_folder_rename_and_stays_inside_root(self):
        """Malformed or legacy root-level movie jobs must not rename the library root
        to a sibling folder outside the selected directory."""
        from plex_renamer.job_executor import _execute_rename
        from plex_renamer.job_store import RenameOp, RenameJob

        with TemporaryDirectory() as tmp:
            library_root = Path(tmp) / "Quarantine"
            library_root.mkdir()

            movie_file = library_root / "Spaceballs.1987.2160p.UHD.BluRay.HEVC.REMUX.mkv"
            movie_file.write_text("movie")

            job = RenameJob(
                library_root=str(library_root),
                source_folder=".",
                media_name="Spaceballs",
                media_type="movie",
                show_folder_rename="Spaceballs (1987)",
                rename_ops=[
                    RenameOp(
                        original_relative=movie_file.name,
                        new_name="Spaceballs (1987).mkv",
                        target_dir_relative="Spaceballs (1987)",
                        status="OK",
                        selected=True,
                    ),
                ],
            )

            result = _execute_rename(job)

            self.assertEqual(result.renamed_count, 1)
            self.assertTrue((library_root / "Spaceballs (1987)" / "Spaceballs (1987).mkv").exists())
            self.assertFalse((library_root.parent / "Spaceballs (1987)" / "Spaceballs (1987).mkv").exists())
            self.assertTrue(library_root.exists(), "Library root should not be renamed")

    def test_queue_execute_normalizes_season_folder_case_only_names(self):
        from plex_renamer.constants import MediaType
        from plex_renamer.job_executor import _execute_rename
        from plex_renamer.job_store import RenameJob, RenameOp

        with TemporaryDirectory() as tmp:
            library_root = Path(tmp) / "TV Root"
            source_root = library_root / "Show"
            season_dir = source_root / "season 01"
            season_dir.mkdir(parents=True)
            episode = season_dir / "Show.S01E01.mkv"
            episode.write_text("ep1")

            job = RenameJob(
                library_root=str(library_root),
                source_folder="Show",
                media_name="Show",
                media_type=MediaType.TV,
                rename_ops=[
                    RenameOp(
                        original_relative="Show/season 01/Show.S01E01.mkv",
                        new_name="Show - S01E01.mkv",
                        target_dir_relative="Show/season 01",
                        status="OK",
                        selected=True,
                    ),
                ],
            )

            result = _execute_rename(job)

            self.assertEqual(result.errors, [])
            self.assertTrue((source_root / "Season 01" / "Show - S01E01.mkv").exists())
            self.assertEqual(sorted(child.name for child in source_root.iterdir()), ["Season 01"])


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
