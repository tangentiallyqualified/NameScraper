from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from plex_renamer.app.services import TVLibraryDiscoveryService
from plex_renamer.app.models import TVDirectoryRole
from plex_renamer.engine import BatchTVOrchestrator, PreviewItem, score_tv_results, TVScanner
from plex_renamer.job_executor import revert_job
from plex_renamer.job_store import RenameJob
from plex_renamer.parsing import best_tv_match_title, clean_folder_name, extract_episode, extract_season_number


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


class _FakeAlwaysSunnyTMDB(_FakeTMDB):
    _SEASONS = {
        1: {
            "titles": {
                1: "The Gang Gets Racist",
                2: "Charlie Wants an Abortion",
                5: "Gun Fever",
            },
            "posters": {},
            "episodes": {},
            "count": 7,
        },
        2: {
            "titles": {
                1: "Charlie Gets Crippled",
                2: "The Gang Goes Jihad",
            },
            "posters": {},
            "episodes": {},
            "count": 10,
        },
    }

    def get_season_map(self, show_id):
        total = sum(data["count"] for data in self._SEASONS.values())
        return self._SEASONS, total

    def get_season(self, show_id, season_num):
        return self._SEASONS.get(
            season_num,
            {"titles": {}, "posters": {}, "episodes": {}, "count": 0},
        )


class _FakeSuccessionTMDB(_FakeTMDB):
    SUCCESSION = {
        "id": 76331,
        "name": "Succession",
        "year": "2018",
        "poster_path": None,
        "overview": "",
        "number_of_seasons": 4,
        "number_of_episodes": 39,
    }

    _SEASONS = {
        1: {"titles": {episode: f"Season 1 Episode {episode}" for episode in range(1, 11)}, "posters": {}, "episodes": {}, "count": 10},
        2: {"titles": {episode: f"Season 2 Episode {episode}" for episode in range(1, 11)}, "posters": {}, "episodes": {}, "count": 10},
        3: {"titles": {episode: f"Season 3 Episode {episode}" for episode in range(1, 10)}, "posters": {}, "episodes": {}, "count": 9},
        4: {"titles": {episode: f"Season 4 Episode {episode}" for episode in range(1, 10)}, "posters": {}, "episodes": {}, "count": 10},
    }

    def search_tv_batch(self, queries, progress_callback=None):
        results = []
        total = len(queries)
        for index, (_name, _year) in enumerate(queries, start=1):
            if progress_callback:
                progress_callback(index, total)
            results.append([dict(self.SUCCESSION)])
        return results

    def get_tv_details(self, show_id):
        return {
            "number_of_seasons": 4,
            "number_of_episodes": 39,
            "seasons": [
                {"season_number": season, "name": f"Season {season}", "episode_count": data["count"]}
                for season, data in sorted(self._SEASONS.items())
            ],
        }

    def get_season_map(self, show_id):
        total = sum(data["count"] for data in self._SEASONS.values())
        return self._SEASONS, total

    def get_season(self, show_id, season_num):
        return self._SEASONS.get(
            season_num,
            {"titles": {}, "posters": {}, "episodes": {}, "count": 0},
        )


class _FakeITCrowdTMDB(_FakeTMDB):
    _SEASONS = {
        1: {
            "titles": {
                1: "Yesterday's Jam",
                2: "Calamity Jen",
            },
            "posters": {},
            "episodes": {},
            "count": 2,
        },
        2: {
            "titles": {
                1: "The Work Outing",
            },
            "posters": {},
            "episodes": {},
            "count": 1,
        },
    }

    def get_season_map(self, show_id):
        total = sum(data["count"] for data in self._SEASONS.values())
        return self._SEASONS, total

    def get_season(self, show_id, season_num):
        return self._SEASONS.get(
            season_num,
            {"titles": {}, "posters": {}, "episodes": {}, "count": 0},
        )


class _FakeSeasonMapTMDB(_FakeTMDB):
    language = "en-US"

    def __init__(self, seasons):
        self._seasons = seasons

    def get_tv_details(self, show_id):
        return {
            "number_of_seasons": len([season for season in self._seasons if season > 0]),
            "number_of_episodes": sum(
                data["count"] for season, data in self._seasons.items() if season > 0
            ),
            "seasons": [
                {
                    "season_number": season,
                    "name": data.get("name", f"Season {season}"),
                    "episode_count": data["count"],
                }
                for season, data in sorted(self._seasons.items())
            ],
        }

    def get_season_map(self, show_id):
        total = sum(data["count"] for season, data in self._seasons.items() if season > 0)
        return self._seasons, total

    def get_season(self, show_id, season_num):
        return self._seasons.get(
            season_num,
            {"titles": {}, "posters": {}, "episodes": {}, "count": 0},
        )


class _FakeWatchmenTMDB(_FakeTMDB):
    """Real show + a spin-off whose ALT title equals the query.

    The alt-title boost levels their scores and the winner's saturates at
    1.0, so tie detection must fall back to identity evidence.
    """

    REAL = {"id": 79788, "name": "Watchmen", "year": "2019",
            "poster_path": None, "overview": ""}
    SPINOFF = {"id": 18096, "name": "Watchmen: Motion Comic", "year": "2008",
               "poster_path": None, "overview": ""}

    def __init__(self, spinoff_name: str = "Watchmen: Motion Comic"):
        self._spinoff = dict(self.SPINOFF, name=spinoff_name)

    def search_tv_batch(self, queries, progress_callback=None):
        return [[dict(self.REAL), dict(self._spinoff)] for _ in queries]

    def get_alternative_titles(self, media_id, media_type="tv"):
        if media_id == self.SPINOFF["id"]:
            return [("Watchmen", "US")]
        return []

    def _count(self, show_id):
        return 9 if show_id == self.REAL["id"] else 12

    def get_tv_details(self, show_id):
        count = self._count(show_id)
        return {
            "number_of_seasons": 1,
            "number_of_episodes": count,
            "seasons": [
                {"season_number": 1, "name": "Season 1", "episode_count": count},
            ],
        }

    def get_season_map(self, show_id):
        count = self._count(show_id)
        titles = {episode: f"Chapter {episode}" for episode in range(1, count + 1)}
        return {1: {"titles": titles, "posters": {}, "episodes": {}, "count": count}}, count

    def get_season(self, show_id, season_num):
        seasons, _total = self.get_season_map(show_id)
        return seasons.get(
            season_num, {"titles": {}, "posters": {}, "episodes": {}, "count": 0},
        )


class SaturatedTieBreakTests(unittest.TestCase):
    """RC13: alt-title + evidence boosts saturate both candidates above 1.0;
    the exact primary-name match must break the tie instead of flagging it."""

    def _discover(self, tmdb):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            show = root / "Watchmen.S01.2160p.MAX.WEB-DL.x265.10bit.HDR.DTS-HD.MA.5.1-NTb[rartv]"
            show.mkdir()
            for episode in range(1, 10):
                (show / (
                    f"Watchmen.S01E{episode:02d}.2160p.MAX.WEB-DL"
                    ".DTS-HD.MA.5.1.HDR.DV.HEVC-NTb.mkv"
                )).write_text("x")
            orchestrator = BatchTVOrchestrator(
                tmdb, root, discovery_service=TVLibraryDiscoveryService(),
            )
            return orchestrator.discover_shows()

    def test_exact_primary_name_breaks_saturated_tie(self):
        states = self._discover(_FakeWatchmenTMDB())
        self.assertEqual(len(states), 1)
        self.assertEqual(states[0].show_id, 79788)
        self.assertFalse(states[0].tie_detected)

    def test_two_exact_primary_names_keep_the_tie(self):
        # A GENUINE ambiguity — both literally named "Watchmen" AND
        # indistinguishable by episode count — must still surface as a tie.
        class _EqualCounts(_FakeWatchmenTMDB):
            def _count(self, show_id):
                return 9

        states = self._discover(_EqualCounts(spinoff_name="Watchmen"))
        self.assertEqual(len(states), 1)
        self.assertTrue(states[0].tie_detected)

    def test_episode_count_discrimination_breaks_same_name_tie(self):
        # RC38 (Limitless): same primary name, but the folder's 9 files
        # exactly match the real show's episode count (spinoff has 12) —
        # the count evidence identifies the show, so no tie flag.
        states = self._discover(_FakeWatchmenTMDB(spinoff_name="Watchmen"))
        self.assertEqual(len(states), 1)
        self.assertEqual(states[0].show_id, 79788)
        self.assertFalse(states[0].tie_detected)


class SpecialsLeafDiscoveryTests(unittest.TestCase):
    """A bare "Specials" folder holding explicit S00E## episode files must be
    discoverable even though its name matches the extras-folder pattern (The
    Brak Show: empty Season 1-3 + Specials/ with one S00E01 file produced NO
    candidate). Extras folders with only bonus junk stay undiscovered.
    """

    def test_specials_folder_with_explicit_s00_files_is_discovered(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            show = root / "The Brak Show (2000)"
            for season in (1, 2, 3):
                (show / f"Season {season}").mkdir(parents=True)
            specials = show / "Specials"
            specials.mkdir()
            (specials / "The Brak Show (2000) S00E01 - Brak Presents.mkv").write_text("x")

            service = TVLibraryDiscoveryService()
            candidates = service.discover_show_roots(root)

            relative = {candidate.relative_folder for candidate in candidates}
            self.assertIn("The Brak Show (2000)/Specials", relative)

    def test_extras_folder_without_explicit_specials_stays_leaf(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            extras = root / "Some Show (2001)" / "Extras"
            extras.mkdir(parents=True)
            (extras / "Behind the Scenes.mkv").write_text("x")
            (extras / "Bloopers.mkv").write_text("x")

            service = TVLibraryDiscoveryService()
            candidates = service.discover_show_roots(root)

            self.assertEqual(candidates, [])


class GenericCandidateTitleInheritanceTests(unittest.TestCase):
    """A discovered candidate named only with a season/collection label
    ("Specials (1998-2003)", "Series") carries no show identity: searching
    TMDB with it matches shows literally called "Specials". Such candidates
    must search with the PARENT folder's title instead.
    """

    def _discover(self, root: Path):
        tmdb = _RecordingTVTMDB()
        orchestrator = BatchTVOrchestrator(
            tmdb, root, discovery_service=TVLibraryDiscoveryService(),
        )
        states = orchestrator.discover_shows()
        return tmdb, states

    def test_specials_child_of_empty_umbrella_inherits_parent_search_title(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            show = root / "The Wild Thornberries (1998)"
            for season in range(1, 6):
                (show / f"Season {season}").mkdir(parents=True)
            specials = show / "Specials (1998-2003)"
            specials.mkdir()
            for name in ("The Origin of Donnie.avi", "Sir Nigel.avi", "Gold Fever.avi"):
                (specials / name).write_text("x")

            tmdb, states = self._discover(root)

            queries = [name for name, _year in tmdb.queries]
            self.assertEqual(len(states), 1)
            self.assertIn("The Wild Thornberries", queries)
            self.assertNotIn("Specials", queries)
            self.assertEqual(states[0].season_assignment, 0)

    def test_generic_series_child_inherits_parent_search_title(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            series = root / "Bobs Burgers (2011) Complete" / "Series"
            series.mkdir(parents=True)
            for name in ("Human Flesh.mp4", "Crawl Space.mp4", "Sacred Cow.mp4"):
                (series / name).write_text("x")

            tmdb, states = self._discover(root)

            queries = [name for name, _year in tmdb.queries]
            self.assertEqual(len(states), 1)
            self.assertIn("Bobs Burgers", queries)
            self.assertNotIn("Series", queries)

    def test_top_level_specials_folder_keeps_own_name(self):
        # Directly under the library root there is no parent show folder to
        # inherit from; the candidate keeps its own (odd) name.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            specials = root / "Specials (1998-2003)"
            specials.mkdir()
            for name in ("A.avi", "B.avi", "C.avi"):
                (specials / name).write_text("x")

            tmdb, states = self._discover(root)

            queries = [name for name, _year in tmdb.queries]
            self.assertEqual(queries, ["Specials"])

    def test_show_named_specials_child_keeps_own_name(self):
        # "Yuru Camp Specials" carries the show title; it must NOT be
        # replaced by the (junk-laden) parent bundle name.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = root / "[UDF] Camp Bundle (BDRip 1080p x264 FLAC)"
            specials = bundle / "Yuru Camp Specials"
            specials.mkdir(parents=True)
            for name in ("01.mkv", "02.mkv", "03.mkv"):
                (specials / name).write_text("x")

            tmdb, states = self._discover(root)

            queries = [name for name, _year in tmdb.queries]
            self.assertEqual(queries, ["Yuru Camp Specials"])


class ScanImprovementTests(unittest.TestCase):
    def test_extract_episode_parses_nxnn_filenames_as_season_relative(self):
        name = "It's Always Sunny in Philadelphia - 1x05 - Gun Fever.mkv"

        self.assertEqual(extract_episode(name), ([5], "Gun Fever", True))
        self.assertEqual(extract_season_number(name), 1)

    def test_extract_episode_handles_space_between_season_and_episode(self):
        # CatDog source uses "S01 E01-E02" (space between season and episode).
        name = "CatDog - S01 E01-E02 - Dog Gone and All You Can't Eat (1080p - Web-DL).mp4"

        self.assertEqual(
            extract_episode(name),
            ([1, 2], "Dog Gone and All You Can't Eat", True),
        )
        self.assertEqual(extract_season_number(name), 1)

    def test_tv_scanner_maps_nxnn_files_to_their_episode_numbers(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "It's Always Sunny in Philadelphia S01-02"
            season_one = root / "S01"
            season_two = root / "S02"
            season_one.mkdir(parents=True)
            season_two.mkdir()

            filenames = [
                season_one / "It's Always Sunny in Philadelphia - 1x01 - The Gang Gets Racist.mkv",
                season_one / "It's Always Sunny in Philadelphia - 1x02 - Charlie Wants an Abortion.mkv",
                season_one / "It's Always Sunny in Philadelphia - 1x05 - Gun Fever.mkv",
                season_two / "It's Always Sunny in Philadelphia - 2x01 - Charlie Gets Crippled.mkv",
                season_two / "It's Always Sunny in Philadelphia - 2x02 - The Gang Goes Jihad.mkv",
            ]
            for filename in filenames:
                filename.write_text("x")

            scanner = TVScanner(
                _FakeAlwaysSunnyTMDB(),
                {"id": 2710, "name": "It's Always Sunny in Philadelphia", "year": "2005"},
                root,
            )

            items, has_mismatch = scanner.scan()

            self.assertFalse(has_mismatch)
            by_name = {item.original.name: item for item in items}
            self.assertEqual(len(by_name), len(filenames))
            self.assertEqual(by_name[filenames[0].name].episodes, [1])
            self.assertEqual(by_name[filenames[1].name].episodes, [2])
            self.assertEqual(by_name[filenames[2].name].episodes, [5])
            self.assertEqual(by_name[filenames[3].name].season, 2)
            self.assertEqual(by_name[filenames[3].name].episodes, [1])
            self.assertEqual(by_name[filenames[4].name].episodes, [2])
            self.assertTrue(all(item.status == "OK" for item in items))

    def test_get_year_season_recognizes_year_folders(self):
        from plex_renamer.parsing import get_year_season
        self.assertEqual(get_year_season("S2014"), 2014)
        self.assertEqual(get_year_season("s2020"), 2020)
        self.assertIsNone(get_year_season("S01"))
        self.assertIsNone(get_year_season("S123"))
        self.assertIsNone(get_year_season("Season 1"))

    def test_year_season_umbrella_classified_as_single_show_root(self):
        # Adult Swim Infomercials: children are release-year folders (S2014,
        # S2020). The umbrella is ONE show, not a multi-show container.
        with TemporaryDirectory() as tmp:
            umbrella = Path(tmp) / "Adult Swim Infomercials"
            for year in ("S2014", "S2016", "S2020"):
                year_dir = umbrella / year
                year_dir.mkdir(parents=True)
                (year_dir / f"Adult Swim Infomercials {year}E01 Thing.mkv").write_text("x")
            specials = umbrella / "S00"
            specials.mkdir()
            (specials / "Adult Swim Infomercials SPECIAL 0x1 Yule Log.mkv").write_text("x")

            service = TVLibraryDiscoveryService()
            self.assertEqual(
                service.classify_directory(umbrella), TVDirectoryRole.SHOW_ROOT,
            )

    def test_year_season_umbrella_discovered_as_one_candidate(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            umbrella = root / "Adult Swim Infomercials"
            for year in ("S2014", "S2016", "S2020"):
                year_dir = umbrella / year
                year_dir.mkdir(parents=True)
                (year_dir / f"Adult Swim Infomercials {year}E01 Thing.mkv").write_text("x")

            service = TVLibraryDiscoveryService()
            candidates = service.discover_show_roots(root)
            relative_paths = {candidate.relative_folder for candidate in candidates}

            self.assertIn("Adult Swim Infomercials", relative_paths)
            self.assertNotIn("Adult Swim Infomercials/S2014", relative_paths)
            self.assertNotIn("Adult Swim Infomercials/S2020", relative_paths)

    def test_year_season_umbrella_selected_directly_is_single_show(self):
        # User points the scan directly at the umbrella folder.
        with TemporaryDirectory() as tmp:
            umbrella = Path(tmp) / "Adult Swim Infomercials"
            for year in ("S2014", "S2016", "S2020"):
                year_dir = umbrella / year
                year_dir.mkdir(parents=True)
                (year_dir / f"Adult Swim Infomercials {year}E01 Thing.mkv").write_text("x")

            service = TVLibraryDiscoveryService()
            candidates = service.discover_show_roots(umbrella)
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0].relative_folder, ".")

    def test_year_folders_resolve_to_tmdb_season_by_air_year(self):
        seasons = {
            0: {
                "titles": {1: "Yule Log"}, "posters": {},
                "episodes": {1: {"air_date": "2014-12-25"}},
                "count": 1, "name": "Specials",
            },
            1: {
                "titles": {1: "Fartcopter", 2: "Too Many Cooks"}, "posters": {},
                "episodes": {
                    1: {"air_date": "2014-05-01"},
                    2: {"air_date": "2016-06-01"},
                },
                "count": 2, "name": "Season 1",
            },
        }
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "Adult Swim Infomercials"
            d2014 = root / "S2014"
            d2014.mkdir(parents=True)
            (d2014 / "Adult Swim Infomercials S2014E01 Fartcopter.mkv").write_text("x")
            d2016 = root / "S2016"
            d2016.mkdir()
            (d2016 / "Adult Swim Infomercials S2016E01 Too Many Cooks.mkv").write_text("x")
            specials = root / "S00"
            specials.mkdir()
            (specials / "Adult Swim Infomercials SPECIAL 0x1 Yule Log.mkv").write_text("x")

            scanner = TVScanner(
                _FakeSeasonMapTMDB(seasons),
                {"id": 115657, "name": "Infomercials", "year": "2013"},
                root,
            )
            items, has_mismatch = scanner.scan()

            self.assertFalse(has_mismatch)
            by_name = {item.original.name: item for item in items}
            fartcopter = by_name["Adult Swim Infomercials S2014E01 Fartcopter.mkv"]
            self.assertEqual(fartcopter.season, 1)
            self.assertEqual(fartcopter.episodes, [1])
            cooks = by_name["Adult Swim Infomercials S2016E01 Too Many Cooks.mkv"]
            self.assertEqual(cooks.season, 1)
            self.assertEqual(cooks.episodes, [2])

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

    def test_consolidated_preview_auto_accepts_explicit_sxxeyy_title_matches(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "The IT Crowd"
            root.mkdir()
            filenames = [
                "The.IT.Crowd.S01E01.Yesterdays.Jam.mkv",
                "The.IT.Crowd.S01E02.Calamity.Jen.mkv",
                "The.IT.Crowd.S02E01.The.Work.Outing.mkv",
            ]
            for name in filenames:
                (root / name).write_text("x")

            scanner = TVScanner(
                _FakeITCrowdTMDB(),
                {"id": 2490, "name": "The IT Crowd", "year": "2006"},
                root,
            )

            items, has_mismatch = scanner.scan()
            by_name = {item.original.name: item for item in items}

            self.assertFalse(has_mismatch)
            self.assertEqual(by_name[filenames[0]].season, 1)
            self.assertEqual(by_name[filenames[0]].episodes, [1])
            self.assertEqual(by_name[filenames[2]].season, 2)
            self.assertEqual(by_name[filenames[2]].episodes, [1])
            self.assertTrue(all(item.status == "OK" for item in items))
            # The consolidated path now reconciles each file through the shared
            # resolution policy: an explicit S##E## number agreeing with the
            # TMDB episode title yields CONF_AGREE (0.96), same as the normal
            # path, rather than the old bare-number title-match floor (0.92).
            self.assertTrue(all(item.episode_confidence == 0.96 for item in items))

    def test_title_prefix_mismatch_caps_explicit_episode_confidence(self):
        seasons = {
            1: {
                "name": "Season 1",
                "titles": {1: "Pilot", 2: "Square Peg"},
                "posters": {},
                "episodes": {},
                "count": 2,
            },
        }
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "King of the Hill"
            season_one = root / "Season 01"
            season_one.mkdir(parents=True)
            (season_one / "SpongeBob - S01E01.mkv").write_text("x")
            (season_one / "SpongeBob - S01E02.mkv").write_text("x")

            scanner = TVScanner(
                _FakeSeasonMapTMDB(seasons),
                {"id": 1000, "name": "King of the Hill", "year": "1997"},
                root,
            )

            items, _has_mismatch = scanner.scan()

            self.assertTrue(all(item.episode_confidence == 0.45 for item in items))
            self.assertTrue(all(item.status.startswith("REVIEW") for item in items))

    def test_title_and_episode_title_evidence_raise_explicit_episode_confidence(self):
        seasons = {
            1: {
                "name": "Season 1",
                "titles": {1: "Pilot"},
                "posters": {},
                "episodes": {},
                "count": 1,
            },
        }
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "King of the Hill"
            root.mkdir()
            (root / "King.of.the.Hill.S01E01.Pilot.mkv").write_text("x")

            scanner = TVScanner(
                _FakeSeasonMapTMDB(seasons),
                {"id": 1000, "name": "King of the Hill", "year": "1997"},
                root,
            )

            items, _has_mismatch = scanner.scan()

            # Number and TMDB title agree -> CONF_AGREE from the shared
            # resolution policy (was a 0.92 title-match floor pre-table).
            self.assertEqual(items[0].episode_confidence, 0.96)
            self.assertEqual(items[0].status, "OK")

    def test_already_plex_ready_episode_gets_perfect_confidence(self):
        seasons = {
            1: {
                "name": "Season 1",
                "titles": {1: "Bartender"},
                "posters": {},
                "episodes": {},
                "count": 1,
            },
        }
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "Bartender (2006)"
            season_one = root / "Season 01"
            season_one.mkdir(parents=True)
            (season_one / "Bartender (2006) - S01E01 - Bartender.mkv").write_text("x")

            scanner = TVScanner(
                _FakeSeasonMapTMDB(seasons),
                {"id": 3000, "name": "Bartender", "year": "2006"},
                root,
                show_match_confidence=1.0,
            )

            items, _has_mismatch = scanner.scan()

            self.assertEqual(items[0].new_name, items[0].original.name)
            self.assertEqual(items[0].target_dir, items[0].original.parent)
            self.assertFalse(items[0].is_actionable)
            self.assertEqual(items[0].episode_confidence, 1.0)
            self.assertEqual(items[0].status, "OK")

    def test_plex_ready_episode_gets_perfect_confidence_in_mixed_directory(self):
        seasons = {
            1: {
                "name": "Season 1",
                "titles": {1: "Bartender", 2: "Menu of the Heart"},
                "posters": {},
                "episodes": {},
                "count": 2,
            },
        }
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "Bartender (2006)"
            season_one = root / "Season 01"
            season_one.mkdir(parents=True)
            (season_one / "Bartender (2006) - S01E01 - Bartender.mkv").write_text("x")
            (season_one / "[Kawaiika-Raws] Bartender 02 [BDRip].mkv").write_text("x")

            scanner = TVScanner(
                _FakeSeasonMapTMDB(seasons),
                {"id": 3000, "name": "Bartender", "year": "2006"},
                root,
                show_match_confidence=1.0,
            )

            items, _has_mismatch = scanner.scan()

            by_episode = {item.episodes[0]: item for item in items}
            self.assertFalse(by_episode[1].is_actionable)
            self.assertTrue(by_episode[2].is_actionable)
            self.assertEqual(by_episode[1].episode_confidence, 1.0)
            self.assertEqual(by_episode[2].episode_confidence, 0.85)

    def test_season_name_satisfies_source_title_prefix_compatibility(self):
        seasons = {
            2: {
                "name": "K: Return of Kings",
                "titles": {1: "Knave", 2: "Kindness"},
                "posters": {},
                "episodes": {},
                "count": 2,
            },
        }
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "K"
            season_two = root / "Season 02"
            season_two.mkdir(parents=True)
            (season_two / "K.Return.of.Kings.01.Releasegroup.mkv").write_text("x")
            (season_two / "K.Return.of.Kings.02.Releasegroup.mkv").write_text("x")

            scanner = TVScanner(
                _FakeSeasonMapTMDB(seasons),
                {"id": 2000, "name": "K", "year": "2012"},
                root,
            )

            items, _has_mismatch = scanner.scan()

            self.assertTrue(all(item.episode_confidence == 0.80 for item in items))
            self.assertTrue(all(item.status.startswith("REVIEW") for item in items))

    def test_exact_bare_number_season_coverage_gets_below_default_floor(self):
        seasons = {
            1: {
                "name": "Season 1",
                "titles": {episode: f"Episode {episode}" for episode in range(1, 12)},
                "posters": {},
                "episodes": {},
                "count": 11,
            },
        }
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "Bartender"
            root.mkdir()
            for episode in range(1, 12):
                (root / f"[Kawaiika-Raws] Bartender {episode:02d} [BDRip].mkv").write_text("x")

            scanner = TVScanner(
                _FakeSeasonMapTMDB(seasons),
                {"id": 3000, "name": "Bartender", "year": "2006"},
                root,
            )

            items, _has_mismatch = scanner.scan()

            self.assertTrue(all(item.episode_confidence == 0.80 for item in items))
            self.assertTrue(all(item.status.startswith("REVIEW") for item in items))

    def test_single_season_exact_coverage_with_perfect_show_match_reaches_default_threshold(self):
        seasons = {
            1: {
                "name": "Season 1",
                "titles": {episode: f"Episode {episode}" for episode in range(1, 12)},
                "posters": {},
                "episodes": {},
                "count": 11,
            },
        }
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "Bartender"
            root.mkdir()
            for episode in range(1, 12):
                (root / f"[Kawaiika-Raws] Bartender {episode:02d} [BDRip].mkv").write_text("x")

            scanner = TVScanner(
                _FakeSeasonMapTMDB(seasons),
                {"id": 3000, "name": "Bartender", "year": "2006"},
                root,
                show_match_confidence=1.0,
            )

            items, _has_mismatch = scanner.scan()

            self.assertTrue(all(item.episode_confidence == 0.85 for item in items))
            self.assertTrue(all(item.status == "OK" for item in items))

    def test_exact_bare_number_floor_clears_when_user_threshold_allows_it(self):
        from plex_renamer.engine import set_episode_auto_accept_threshold

        seasons = {
            1: {
                "name": "Season 1",
                "titles": {episode: f"Episode {episode}" for episode in range(1, 4)},
                "posters": {},
                "episodes": {},
                "count": 3,
            },
        }
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "Bartender"
            root.mkdir()
            for episode in range(1, 4):
                (root / f"Bartender {episode:02d}.mkv").write_text("x")

            try:
                set_episode_auto_accept_threshold(0.80)
                scanner = TVScanner(
                    _FakeSeasonMapTMDB(seasons),
                    {"id": 3000, "name": "Bartender", "year": "2006"},
                    root,
                )

                items, _has_mismatch = scanner.scan()
            finally:
                set_episode_auto_accept_threshold(0.85)

            self.assertTrue(all(item.episode_confidence == 0.80 for item in items))
            self.assertTrue(all(item.status == "OK" for item in items))

    def test_multi_season_exact_coverage_gets_per_season_floor(self):
        seasons = {
            1: {
                "name": "Season 1",
                "titles": {1: "One", 2: "Two"},
                "posters": {},
                "episodes": {},
                "count": 2,
            },
            2: {
                "name": "Season 2",
                "titles": {1: "Three", 2: "Four"},
                "posters": {},
                "episodes": {},
                "count": 2,
            },
        }
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "Example Show"
            for season in (1, 2):
                season_dir = root / f"Season {season:02d}"
                season_dir.mkdir(parents=True)
                (season_dir / "Example Show 01.mkv").write_text("x")
                (season_dir / "Example Show 02.mkv").write_text("x")

            scanner = TVScanner(
                _FakeSeasonMapTMDB(seasons),
                {"id": 4000, "name": "Example Show", "year": "2020"},
                root,
            )

            items, _has_mismatch = scanner.scan()

            self.assertEqual({item.season for item in items}, {1, 2})
            self.assertTrue(all(item.episode_confidence == 0.80 for item in items))

    def test_companion_videos_do_not_block_exact_coverage_floor(self):
        seasons = {
            1: {
                "name": "Season 1",
                "titles": {1: "One", 2: "Two"},
                "posters": {},
                "episodes": {},
                "count": 2,
            },
        }
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "Example Show"
            season_dir = root / "Season 01"
            season_dir.mkdir(parents=True)
            (season_dir / "Example Show 01.mkv").write_text("x")
            (season_dir / "Example Show 02.mkv").write_text("x")
            (season_dir / "Example Show NCOP.mkv").write_text("x")
            (season_dir / "Example Show NCED.mkv").write_text("x")

            scanner = TVScanner(
                _FakeSeasonMapTMDB(seasons),
                {"id": 4000, "name": "Example Show", "year": "2020"},
                root,
            )

            items, _has_mismatch = scanner.scan()
            episode_items = [item for item in items if item.episodes]

            self.assertEqual(len(episode_items), 2)
            self.assertTrue(all(item.episode_confidence == 0.80 for item in episode_items))

    def test_nested_extras_do_not_block_regular_season_coverage_floor(self):
        seasons = {
            0: {
                "name": "Specials",
                "titles": {},
                "posters": {},
                "episodes": {},
                "count": 0,
            },
            1: {
                "name": "Season 1",
                "titles": {1: "One", 2: "Two"},
                "posters": {},
                "episodes": {},
                "count": 2,
            },
        }
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "Example Show"
            season_dir = root / "Season 01"
            extras_dir = season_dir / "Extras"
            extras_dir.mkdir(parents=True)
            (season_dir / "Example Show 01.mkv").write_text("x")
            (season_dir / "Example Show 02.mkv").write_text("x")
            (extras_dir / "Interview.mkv").write_text("x")

            scanner = TVScanner(
                _FakeSeasonMapTMDB(seasons),
                {"id": 4000, "name": "Example Show", "year": "2020"},
                root,
            )

            items, _has_mismatch = scanner.scan()
            episode_items = [item for item in items if item.season == 1 and item.episodes]

            self.assertEqual(len(episode_items), 2)
            self.assertTrue(all(item.episode_confidence == 0.80 for item in episode_items))

    def test_duplicate_regular_episode_claims_prevent_coverage_floor(self):
        seasons = {
            1: {
                "name": "Season 1",
                "titles": {1: "One"},
                "posters": {},
                "episodes": {},
                "count": 1,
            },
        }
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "Example Show"
            root.mkdir()
            (root / "Example Show 01.mkv").write_text("x")
            (root / "Alt Show 01.mkv").write_text("x")

            scanner = TVScanner(
                _FakeSeasonMapTMDB(seasons),
                {"id": 4000, "name": "Example Show", "year": "2020"},
                root,
            )

            items, _has_mismatch = scanner.scan()

            self.assertTrue(any("duplicate episode" in item.status for item in items))
            self.assertTrue(all(item.episode_confidence < 0.80 for item in items))

    # test_conflict_regular_episode_claims_prevent_coverage_floor moved to
    # tests/test_episode_resolution.py::TestConfidenceAdjustments::
    # test_conflicted_season_gets_no_coverage_floor (table-based).

    def test_currently_airing_season_uses_aired_episode_count_for_coverage(self):
        seasons = {
            1: {
                "name": "Season 1",
                "titles": {episode: f"Episode {episode}" for episode in range(1, 14)},
                "posters": {},
                "episodes": {
                    episode: {
                        "name": f"Episode {episode}",
                        "air_date": f"2026-01-{episode:02d}" if episode <= 4 else f"2026-12-{episode:02d}",
                    }
                    for episode in range(1, 14)
                },
                "count": 13,
            },
        }
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "Airing Show"
            root.mkdir()
            for episode in range(1, 5):
                (root / f"Airing Show {episode:02d}.mkv").write_text("x")

            scanner = TVScanner(
                _FakeSeasonMapTMDB(seasons),
                {"id": 5000, "name": "Airing Show", "year": "2026"},
                root,
            )

            with patch("plex_renamer.engine._episode_resolution.date") as fake_date:
                fake_date.today.return_value = date(2026, 5, 15)
                fake_date.fromisoformat.side_effect = date.fromisoformat
                items, _has_mismatch = scanner.scan()

            self.assertEqual(len(items), 4)
            self.assertTrue(all(item.episode_confidence == 0.80 for item in items))

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

    def test_tv_discovery_strips_leading_website_release_prefix_from_query(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            show = (
                root
                / "www.UIndex.org    -    The Pitt S02E03 900 A M 2160p HMAX WEB-DL DDP5 1 DV H 265-NTb"
            )
            show.mkdir()
            (show / "The Pitt (2025) - S02E03 - 9 -00 A.M..mkv").write_text("x")

            tmdb = _RecordingTVTMDB()
            orchestrator = BatchTVOrchestrator(
                tmdb,
                root,
                discovery_service=TVLibraryDiscoveryService(),
            )

            orchestrator.discover_shows()

            self.assertEqual(tmdb.queries, [("The Pitt", None)])

    def test_tv_discovery_preserves_it_in_show_title_when_cleaning_release_noise(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            show = root / "The IT Crowd 2006 S01-S05 Complete 1080p WEB-DL HEVC x265 BONE"
            season_one = show / "S01"
            season_one.mkdir(parents=True)
            (season_one / "The.IT.Crowd.S01E01.mkv").write_text("x")

            tmdb = _RecordingTVTMDB()
            orchestrator = BatchTVOrchestrator(
                tmdb,
                root,
                discovery_service=TVLibraryDiscoveryService(),
            )

            orchestrator.discover_shows()

            self.assertEqual(clean_folder_name(show.name, include_year=False), "The IT Crowd")
            self.assertEqual(tmdb.queries, [("The IT Crowd", "2006")])

    def test_clean_folder_name_drops_dangling_trailing_article(self):
        """A trailing article left when 'The Complete Series' is stripped at the
        'Complete' noise token must not pollute the search/score title.

        Real case: "Lucy, The Daughter of The Devil The Complete Series[...]"
        previously cleaned to "Lucy, The Daughter of The Devil The".
        """
        name = (
            "Lucy, The Daughter of The Devil The Complete Series"
            "[DVDRip 480p AC3][AtaraxiaPrime]"
        )
        self.assertEqual(
            clean_folder_name(name, include_year=False),
            "Lucy, The Daughter of The Devil",
        )

    def test_clean_folder_name_preserves_leading_article(self):
        """The dangling-article cleanup must never strip a legitimate leading
        article like 'The' in 'The Office'."""
        self.assertEqual(clean_folder_name("The Office", include_year=False), "The Office")
        self.assertEqual(clean_folder_name("The", include_year=False), "The")

    def test_disjoint_same_season_sibling_is_consolidated_into_multi_season_card(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            season_folders = {
                1: root / "Succession.S01.2160p.MAX.WEB-DL.x265.10bit.HDR.DDP5.1.Atmos-SPAMKiNGS[rartv]",
                2: root / "Succession.S02.2160p.MAX.WEB-DL.x265.10bit.HDR.DDP5.1.Atmos-SPAMKiNGS[rartv]",
                3: root / "Succession.S03.2160p.MAX.WEB-DL.x265.10bit.HDR.DDP5.1.Atmos-SPAMKiNGS[rartv]",
                4: root / "succession season 04",
            }
            for season, folder in season_folders.items():
                folder.mkdir()
                for episode in range(1, 3):
                    (folder / f"Succession.S{season:02d}E{episode:02d}.mkv").write_text("x")

            duplicate_season = (
                root
                / "www.Torrenting.com - Succession S04E09 Church and State 2160p MAX WEB-DL DD 5 1 Atmos DoVi HDR H 265-playWEB"
            )
            duplicate_season.mkdir()
            (duplicate_season / "Succession S04E09 Church and State.mkv").write_text("x")

            orchestrator = BatchTVOrchestrator(
                _FakeSuccessionTMDB(),
                root,
                discovery_service=TVLibraryDiscoveryService(),
            )

            states = orchestrator.discover_shows()
            succession_states = [state for state in states if state.show_id == _FakeSuccessionTMDB.SUCCESSION["id"]]
            merged = [state for state in succession_states if state.season_folders]

            self.assertEqual(len(merged), 1)
            self.assertEqual(set(merged[0].season_folders), {1, 2, 3, 4})
            self.assertIsNone(merged[0].season_assignment)

            duplicates = [state for state in succession_states if state is not merged[0]]
            self.assertEqual(duplicates, [])

            orchestrator.scan_show(merged[0])

            season_four_items = [
                item
                for item in merged[0].preview_items
                if item.season == 4 and item.status == "OK"
            ]
            self.assertEqual(
                sorted(item.episodes[0] for item in season_four_items),
                [1, 2, 9],
            )

    def test_overlapping_same_season_sibling_remains_duplicate(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            season_folder = root / "succession season 04"
            season_folder.mkdir()
            (season_folder / "Succession.S04E01.mkv").write_text("x")
            (season_folder / "Succession.S04E09.mkv").write_text("x")

            overlapping_folder = root / "Succession S04E09 Church and State"
            overlapping_folder.mkdir()
            (overlapping_folder / "Succession S04E09 Church and State.mkv").write_text("x")

            orchestrator = BatchTVOrchestrator(
                _FakeSuccessionTMDB(),
                root,
                discovery_service=TVLibraryDiscoveryService(),
            )

            states = orchestrator.discover_shows()
            succession_states = [state for state in states if state.show_id == _FakeSuccessionTMDB.SUCCESSION["id"]]
            primaries = [state for state in succession_states if state.duplicate_of is None]
            duplicates = [state for state in succession_states if state.duplicate_of is not None]

            self.assertEqual(len(primaries), 1)
            self.assertEqual(len(duplicates), 1)
            self.assertEqual(duplicates[0].season_assignment, 4)
            self.assertEqual(duplicates[0].duplicate_of, primaries[0].display_name)
            self.assertEqual(
                duplicates[0].duplicate_of_relative_folder,
                primaries[0].relative_folder,
            )

    def test_partial_overlap_same_season_sibling_merges_unique_claims_and_marks_conflicts(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            season_folder = root / "succession season 04"
            season_folder.mkdir()
            (season_folder / "Succession.S04E01.mkv").write_text("x")
            (season_folder / "Succession.S04E09.mkv").write_text("x")

            overlapping_folder = root / "Succession S04E09 S04E10 pack"
            overlapping_folder.mkdir()
            (overlapping_folder / "Succession S04E09 Church and State.mkv").write_text("x")
            (overlapping_folder / "Succession S04E10 With Open Eyes.mkv").write_text("x")

            orchestrator = BatchTVOrchestrator(
                _FakeSuccessionTMDB(),
                root,
                discovery_service=TVLibraryDiscoveryService(),
            )

            orchestrator.discover_shows()
            orchestrator.scan_all()

            succession_states = [
                state
                for state in orchestrator.states
                if state.show_id == _FakeSuccessionTMDB.SUCCESSION["id"]
            ]
            self.assertEqual(len(succession_states), 1)
            merged = succession_states[0]
            ok_items = [item for item in merged.preview_items if item.status == "OK"]
            conflict_items = [item for item in merged.preview_items if item.is_conflict]

            self.assertEqual(
                sorted(item.episodes[0] for item in ok_items if item.season == 4),
                [1, 10],
            )
            # Spec: 2+ claims on a slot are a conflict record — both
            # claimants surfaced, neither wins silently.
            self.assertEqual(len(conflict_items), 2)
            self.assertTrue(all(item.episodes == [9] for item in conflict_items))
            self.assertTrue(all(
                "duplicate episode claim S04E09" in item.status
                for item in conflict_items
            ))
            self.assertEqual(
                sorted(item.source_relative_folder for item in conflict_items),
                sorted([
                    season_folder.relative_to(root).as_posix(),
                    overlapping_folder.relative_to(root).as_posix(),
                ]),
            )

    def test_fully_redundant_same_show_sibling_becomes_conflict_evidence(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            season_folder = root / "succession season 04"
            season_folder.mkdir()
            (season_folder / "Succession.S04E01.mkv").write_text("x")
            (season_folder / "Succession.S04E02.mkv").write_text("x")

            redundant_folder = root / "Succession S04 duplicate pack"
            redundant_folder.mkdir()
            (redundant_folder / "Succession S04E01 The Munsters.mkv").write_text("x")
            (redundant_folder / "Succession S04E02 Rehearsal.mkv").write_text("x")

            orchestrator = BatchTVOrchestrator(
                _FakeSuccessionTMDB(),
                root,
                discovery_service=TVLibraryDiscoveryService(),
            )

            orchestrator.discover_shows()
            orchestrator.scan_all()

            succession_states = [
                state
                for state in orchestrator.states
                if state.show_id == _FakeSuccessionTMDB.SUCCESSION["id"]
            ]
            self.assertEqual(len(succession_states), 1)
            conflict_items = [
                item for item in succession_states[0].preview_items if item.is_conflict
            ]

            # Spec: both claimants of each duplicated slot are conflicts —
            # neither folder's copy wins silently.
            self.assertEqual(len(conflict_items), 4)
            conflict_sources = {item.source_relative_folder for item in conflict_items}
            self.assertEqual(
                conflict_sources,
                {
                    season_folder.relative_to(root).as_posix(),
                    redundant_folder.relative_to(root).as_posix(),
                },
            )

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

    def test_nested_discovery_ignores_season_like_trees_without_video_files(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            show = root / "Anime" / "Naruto" / "Season 01"
            show.mkdir(parents=True)
            (show / "Naruto - S01E01.mkv").write_text("x")

            objects = root / "TrackStripper" / ".git" / "objects"
            for folder_name in ("01", "02", "03"):
                object_dir = objects / folder_name
                object_dir.mkdir(parents=True)
                (object_dir / "0123456789abcdef0123456789abcdef012345").write_text("git object")

            non_media_objects = root / "Not Media" / "objects"
            for folder_name in ("01", "02", "03"):
                object_dir = non_media_objects / folder_name
                object_dir.mkdir(parents=True)
                (object_dir / "opaque-data-file").write_text("not video")

            service = TVLibraryDiscoveryService()
            candidates = service.discover_show_roots(root)
            relative_paths = {candidate.relative_folder for candidate in candidates}

            self.assertEqual(relative_paths, {"Anime/Naruto"})
            self.assertNotIn("TrackStripper/.git/objects", relative_paths)
            self.assertNotIn("Not Media/objects", relative_paths)
            self.assertEqual(service.discover_show_roots(root / "TrackStripper" / ".git"), [])

    def test_nested_discovery_keeps_lowercase_s_seasons_under_single_letter_show(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            show = root / "K"
            season_one = show / "s01"
            season_two = show / "s02"
            season_one.mkdir(parents=True)
            season_two.mkdir()
            (season_one / "k - s01e01.mkv").write_text("x")
            (season_two / "k - s02e01.mkv").write_text("x")

            service = TVLibraryDiscoveryService()
            candidates = service.discover_show_roots(root)
            relative_paths = {candidate.relative_folder for candidate in candidates}

            self.assertEqual(relative_paths, {"K"})
            self.assertTrue(candidates[0].has_direct_season_subdirs)

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

    def test_destination_aware_tv_job_moves_files_to_output_and_preserves_source_dirs(self):
        from plex_renamer.constants import MediaType
        from plex_renamer.job_executor import _execute_rename
        from plex_renamer.job_store import RenameOp

        with TemporaryDirectory() as tmp:
            source_root = Path(tmp) / "Incoming"
            output_root = Path(tmp) / "TV Output"
            source_dir = source_root / "Bleach" / "Disc 01"
            source_dir.mkdir(parents=True)
            output_root.mkdir()
            episode = source_dir / "Bleach - 001.mkv"
            note = source_dir / "notes.txt"
            episode.write_text("ep1")
            note.write_text("keep")

            job = RenameJob(
                library_root=str(source_root),
                output_root=str(output_root),
                source_folder="Bleach",
                media_name="Bleach",
                media_type=MediaType.TV,
                rename_ops=[
                    RenameOp(
                        original_relative="Bleach/Disc 01/Bleach - 001.mkv",
                        new_name="Bleach (2004) - S01E01.mkv",
                        target_dir_relative="Bleach (2004)/Season 01",
                        status="OK",
                        selected=True,
                    ),
                    RenameOp(
                        original_relative="Bleach/Disc 01/notes.txt",
                        new_name="notes.txt",
                        target_dir_relative="Bleach (2004)/Season 01/Unmatched Files",
                        status="UNMATCHED",
                        selected=True,
                    ),
                ],
            )

            result = _execute_rename(job)

            self.assertEqual(result.errors, [])
            self.assertEqual(result.renamed_count, 1)
            self.assertTrue((output_root / "Bleach (2004)" / "Season 01" / "Bleach (2004) - S01E01.mkv").exists())
            self.assertFalse(episode.exists())
            self.assertTrue(source_dir.exists())
            self.assertTrue(note.exists())
            self.assertFalse((output_root / "Bleach (2004)" / "Season 01" / "Unmatched Files").exists())

    def test_revert_destination_job_restores_files_and_removes_empty_output_dirs_only(self):
        from plex_renamer.job_executor import _execute_rename, revert_job
        from plex_renamer.job_store import RenameOp

        with TemporaryDirectory() as tmp:
            source_root = Path(tmp) / "Incoming"
            output_root = Path(tmp) / "TV Output"
            source_dir = source_root / "Show" / "Disc 01"
            source_dir.mkdir(parents=True)
            output_root.mkdir()
            original = source_dir / "Show.001.mkv"
            original.write_text("x")

            job = RenameJob(
                library_root=str(source_root),
                output_root=str(output_root),
                source_folder="Show",
                media_name="Show",
                rename_ops=[
                    RenameOp(
                        original_relative="Show/Disc 01/Show.001.mkv",
                        new_name="Show (2024) - S01E01.mkv",
                        target_dir_relative="Show (2024)/Season 01",
                        status="OK",
                        selected=True,
                    )
                ],
            )

            result = _execute_rename(job)
            job.undo_data = result.log_entry

            ok, errors = revert_job(job)

            self.assertTrue(ok, errors)
            self.assertTrue(original.exists())
            self.assertTrue(source_dir.exists())
            self.assertTrue(output_root.exists())
            self.assertFalse((output_root / "Show (2024)").exists())

    def test_revert_destination_job_preserves_output_folder_with_unrelated_files(self):
        from plex_renamer.job_executor import _execute_rename, revert_job
        from plex_renamer.job_store import RenameOp

        with TemporaryDirectory() as tmp:
            source_root = Path(tmp) / "Incoming"
            output_root = Path(tmp) / "Movies"
            source_root.mkdir()
            output_root.mkdir()
            original = source_root / "Alien.1979.mkv"
            original.write_text("x")

            job = RenameJob(
                library_root=str(source_root),
                output_root=str(output_root),
                source_folder=".",
                media_name="Alien",
                rename_ops=[
                    RenameOp(
                        original_relative="Alien.1979.mkv",
                        new_name="Alien (1979).mkv",
                        target_dir_relative="Alien (1979)",
                        status="OK",
                        selected=True,
                    )
                ],
            )

            result = _execute_rename(job)
            unrelated = output_root / "Alien (1979)" / "poster.jpg"
            unrelated.write_text("keep")
            job.undo_data = result.log_entry

            ok, errors = revert_job(job)

            self.assertTrue(ok, errors)
            self.assertTrue(original.exists())
            self.assertTrue(unrelated.exists())

    def test_revert_destination_job_rejects_undo_paths_outside_roots(self):
        from plex_renamer.job_executor import revert_job

        with TemporaryDirectory() as tmp:
            source_root = Path(tmp) / "Incoming"
            output_root = Path(tmp) / "TV Output"
            source_root.mkdir()
            output_root.mkdir()
            outside_output = Path(tmp) / "outside-output.mkv"
            outside_output.write_text("outside")
            outside_source = Path(tmp) / "outside-source" / "restored.mkv"

            job = RenameJob(
                library_root=str(source_root),
                output_root=str(output_root),
                source_folder="Show",
                media_name="Show",
                undo_data={
                    "renames": [
                        {
                            "old": str(outside_source),
                            "new": str(outside_output),
                        }
                    ],
                    "created_dirs": [],
                    "removed_dirs": [],
                    "renamed_dirs": [],
                },
            )

            ok, errors = revert_job(job)

            self.assertFalse(ok)
            self.assertTrue(any("outside the output root" in error for error in errors))
            self.assertTrue(any("outside the source root" in error for error in errors))
            self.assertTrue(outside_output.exists())
            self.assertEqual(outside_output.read_text(), "outside")
            self.assertFalse(outside_source.exists())

    def test_revert_destination_job_rejects_folder_undo_paths_outside_roots(self):
        from plex_renamer.job_executor import revert_job

        with TemporaryDirectory() as tmp:
            source_root = Path(tmp) / "Incoming"
            output_root = Path(tmp) / "TV Output"
            source_root.mkdir()
            output_root.mkdir()
            outside_renamed_dir = Path(tmp) / "outside-renamed"
            outside_renamed_dir.mkdir()
            outside_restore_dir = Path(tmp) / "outside-restored"
            outside_removed_dir = Path(tmp) / "outside-removed"

            job = RenameJob(
                library_root=str(source_root),
                output_root=str(output_root),
                source_folder="Show",
                media_name="Show",
                undo_data={
                    "renames": [],
                    "created_dirs": [],
                    "removed_dirs": [str(outside_removed_dir)],
                    "renamed_dirs": [
                        {
                            "old": str(outside_restore_dir),
                            "new": str(outside_renamed_dir),
                        }
                    ],
                },
            )

            ok, errors = revert_job(job)

            self.assertFalse(ok)
            self.assertTrue(any("outside the output root" in error for error in errors))
            self.assertTrue(any("outside the source root" in error for error in errors))
            self.assertTrue(outside_renamed_dir.exists())
            self.assertFalse(outside_restore_dir.exists())
            self.assertFalse(outside_removed_dir.exists())

    def test_destination_collision_routes_whole_job_to_numbered_top_folder(self):
        from plex_renamer.constants import MediaType
        from plex_renamer.job_executor import _execute_rename
        from plex_renamer.job_store import RenameOp

        with TemporaryDirectory() as tmp:
            source_root = Path(tmp) / "Incoming"
            output_root = Path(tmp) / "Movies"
            source_root.mkdir()
            existing_dir = output_root / "Toy Story (1995)"
            existing_dir.mkdir(parents=True)
            existing_file = existing_dir / "Toy Story (1995).mkv"
            existing_file.write_text("existing")
            movie_file = source_root / "Toy.Story.1995.mkv"
            movie_file.write_text("movie")
            subtitle = source_root / "Toy.Story.1995.srt"
            subtitle.write_text("subtitle")

            job = RenameJob(
                library_root=str(source_root),
                output_root=str(output_root),
                source_folder=".",
                media_name="Toy Story",
                media_type=MediaType.MOVIE,
                rename_ops=[
                    RenameOp(
                        original_relative="Toy.Story.1995.mkv",
                        new_name="Toy Story (1995).mkv",
                        target_dir_relative="Toy Story (1995)",
                        status="OK",
                        selected=True,
                    ),
                    RenameOp(
                        original_relative="Toy.Story.1995.srt",
                        new_name="Toy Story (1995).srt",
                        target_dir_relative="Toy Story (1995)",
                        status="REVIEW_SUBTITLE",
                        selected=True,
                        file_type="subtitle",
                    ),
                ],
            )

            result = _execute_rename(job)

            numbered_dir = output_root / "Toy Story (1995) (1)"
            self.assertEqual(result.errors, [])
            self.assertEqual(result.renamed_count, 2)
            self.assertTrue(existing_file.exists())
            self.assertEqual(existing_file.read_text(), "existing")
            self.assertTrue((numbered_dir / "Toy Story (1995).mkv").exists())
            self.assertTrue((numbered_dir / "Toy Story (1995).srt").exists())
            self.assertFalse(movie_file.exists())
            self.assertFalse(subtitle.exists())

    def test_destination_existing_top_folder_routes_whole_job_to_numbered_folder(self):
        from plex_renamer.constants import MediaType
        from plex_renamer.job_executor import _execute_rename
        from plex_renamer.job_store import RenameOp

        with TemporaryDirectory() as tmp:
            source_root = Path(tmp) / "Incoming"
            output_root = Path(tmp) / "Movies"
            source_root.mkdir()
            existing_dir = output_root / "Toy Story (1995)"
            existing_dir.mkdir(parents=True)
            unrelated = existing_dir / "poster.jpg"
            unrelated.write_text("existing")
            movie_file = source_root / "Toy.Story.1995.mkv"
            movie_file.write_text("movie")
            subtitle = source_root / "Toy.Story.1995.srt"
            subtitle.write_text("subtitle")

            job = RenameJob(
                library_root=str(source_root),
                output_root=str(output_root),
                source_folder=".",
                media_name="Toy Story",
                media_type=MediaType.MOVIE,
                rename_ops=[
                    RenameOp(
                        original_relative="Toy.Story.1995.mkv",
                        new_name="Toy Story (1995).mkv",
                        target_dir_relative="Toy Story (1995)",
                        status="OK",
                        selected=True,
                    ),
                    RenameOp(
                        original_relative="Toy.Story.1995.srt",
                        new_name="Toy Story (1995).srt",
                        target_dir_relative="Toy Story (1995)",
                        status="REVIEW_SUBTITLE",
                        selected=True,
                        file_type="subtitle",
                    ),
                ],
            )

            result = _execute_rename(job)

            numbered_dir = output_root / "Toy Story (1995) (1)"
            self.assertEqual(result.errors, [])
            self.assertEqual(result.renamed_count, 2)
            self.assertTrue(unrelated.exists())
            self.assertTrue((numbered_dir / "Toy Story (1995).mkv").exists())
            self.assertTrue((numbered_dir / "Toy Story (1995).srt").exists())
            self.assertFalse((existing_dir / "Toy Story (1995).mkv").exists())

    def test_destination_job_rejects_paths_outside_source_or_output_roots(self):
        from plex_renamer.constants import MediaType
        from plex_renamer.job_executor import _execute_rename
        from plex_renamer.job_store import RenameOp

        with TemporaryDirectory() as tmp:
            source_root = Path(tmp) / "Incoming"
            output_root = Path(tmp) / "TV Output"
            source_root.mkdir()
            output_root.mkdir()
            outside_source = Path(tmp) / "outside.mkv"
            outside_source.write_text("outside")
            inside_source = source_root / "episode.mkv"
            inside_source.write_text("inside")

            job = RenameJob(
                library_root=str(source_root),
                output_root=str(output_root),
                source_folder=".",
                media_name="Escapes",
                media_type=MediaType.TV,
                rename_ops=[
                    RenameOp(
                        original_relative="../outside.mkv",
                        new_name="Outside.mkv",
                        target_dir_relative="Escapes/Season 01",
                        status="OK",
                        selected=True,
                    ),
                    RenameOp(
                        original_relative="episode.mkv",
                        new_name="Inside.mkv",
                        target_dir_relative="../Escaped",
                        status="OK",
                        selected=True,
                    ),
                ],
            )

            result = _execute_rename(job)

            self.assertEqual(result.renamed_count, 0)
            self.assertTrue(any("outside the source root" in error for error in result.errors))
            self.assertTrue(any("outside the output root" in error for error in result.errors))
            self.assertTrue(outside_source.exists())
            self.assertTrue(inside_source.exists())
            self.assertFalse((Path(tmp) / "Escaped").exists())

    def test_destination_job_rejects_duplicate_selected_targets_before_moving(self):
        from plex_renamer.constants import MediaType
        from plex_renamer.job_executor import _execute_rename
        from plex_renamer.job_store import RenameOp

        with TemporaryDirectory() as tmp:
            source_root = Path(tmp) / "Incoming"
            output_root = Path(tmp) / "TV Output"
            source_root.mkdir()
            output_root.mkdir()
            first = source_root / "first.mkv"
            second = source_root / "second.mkv"
            first.write_text("first")
            second.write_text("second")

            job = RenameJob(
                library_root=str(source_root),
                output_root=str(output_root),
                source_folder=".",
                media_name="Duplicate",
                media_type=MediaType.TV,
                rename_ops=[
                    RenameOp(
                        original_relative="first.mkv",
                        new_name="Duplicate.mkv",
                        target_dir_relative="Duplicate/Season 01",
                        status="OK",
                        selected=True,
                    ),
                    RenameOp(
                        original_relative="second.mkv",
                        new_name="Duplicate.mkv",
                        target_dir_relative="Duplicate/Season 01",
                        status="OK",
                        selected=True,
                    ),
                ],
            )

            result = _execute_rename(job)

            self.assertEqual(result.renamed_count, 0)
            self.assertTrue(any("Duplicate target" in error for error in result.errors))
            self.assertTrue(first.exists())
            self.assertTrue(second.exists())
            self.assertFalse((output_root / "Duplicate").exists())

    def test_destination_job_rejects_new_name_that_escapes_output_root(self):
        from plex_renamer.constants import MediaType
        from plex_renamer.job_executor import _execute_rename
        from plex_renamer.job_store import RenameOp

        with TemporaryDirectory() as tmp:
            source_root = Path(tmp) / "Incoming"
            output_root = Path(tmp) / "TV Output"
            source_root.mkdir()
            output_root.mkdir()
            episode = source_root / "episode.mkv"
            episode.write_text("inside")
            outside_collision = Path(tmp) / "escaped.mkv"
            outside_collision.write_text("outside")

            job = RenameJob(
                library_root=str(source_root),
                output_root=str(output_root),
                source_folder=".",
                media_name="Escaped Name",
                media_type=MediaType.TV,
                rename_ops=[
                    RenameOp(
                        original_relative="episode.mkv",
                        new_name="../../../escaped.mkv",
                        target_dir_relative="Escaped Name/Season 01",
                        status="OK",
                        selected=True,
                    ),
                ],
            )

            result = _execute_rename(job)

            self.assertEqual(result.renamed_count, 0)
            self.assertTrue(any("outside the output root" in error for error in result.errors))
            self.assertTrue(episode.exists())
            self.assertEqual(outside_collision.read_text(), "outside")

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

        best, _, _ = orch._episode_count_tiebreak(
            scored, file_count=4, threshold=0.10, compare_seasons=True,
        )
        self.assertEqual(best["id"], 1002,
                         "4 season subdirs must pick the 4-season series")

    def test_episode_tiebreak_uses_per_season_count_for_single_season_evidence(self):
        """Euphoria S01 regression: a single-season folder (8 files, all S01)
        must compare against each candidate's SEASON 1 episode count, not the
        whole-show total.

        The wrong show (2012, 10 total eps, S1=10) is closer to 8 by total
        count than the correct HBO show (24 total eps, S1=8). Comparing the
        right season makes HBO (|8-8|=0) win over 2012 (|10-8|=2).
        """
        from plex_renamer.engine import score_results, BatchTVOrchestrator

        results = [
            {"name": "Euphoria", "year": "2019", "id": 85552},
            {"name": "Euphoria", "year": "2012", "id": 90417},
        ]
        # No year hint → pure title tie, both score equal (within threshold).
        scored = score_results(results, "Euphoria", None, title_key="name")
        self.assertLessEqual(abs(scored[0][1] - scored[1][1]), 0.10)

        class _FakeTMDB:
            language = "en-US"
            def get_tv_details(self, show_id):
                if show_id == 85552:  # HBO 2019
                    return {
                        "number_of_seasons": 3,
                        "number_of_episodes": 24,
                        "first_air_date": "2019-06-16",
                        "status": "Ended",
                        "seasons": [
                            {"season_number": 1, "episode_count": 8},
                            {"season_number": 2, "episode_count": 8},
                            {"season_number": 3, "episode_count": 8},
                        ],
                    }
                if show_id == 90417:  # 2012 Israeli
                    return {
                        "number_of_seasons": 1,
                        "number_of_episodes": 10,
                        "first_air_date": "2012-01-01",
                        "status": "Ended",
                        "seasons": [
                            {"season_number": 1, "episode_count": 10},
                        ],
                    }
                return None

        orch = BatchTVOrchestrator.__new__(BatchTVOrchestrator)
        orch.tmdb = _FakeTMDB()

        # Without season context the old behaviour picks the wrong show.
        best, _, _ = orch._episode_count_tiebreak(
            scored, file_count=8, threshold=0.10, explicit_seasons={1},
        )
        self.assertEqual(
            best["id"], 85552,
            "Single-season evidence must compare against S1 ep count, picking HBO",
        )


if __name__ == "__main__":
    unittest.main()


class FakeTMDB:
    """Minimal TMDB stand-in for table-driven scanner tests."""

    def __init__(self, seasons: dict):
        # seasons: {num: {"titles": {ep: title}, "posters": {}, "episodes": {}, "count": n}}
        self._seasons = seasons
        self.language = "en-US"

    def get_season_map(self, show_id):
        return self._seasons, None

    def get_season(self, show_id, season_num):
        return self._seasons.get(
            season_num, {"titles": {}, "posters": {}, "episodes": {}},
        )

    def get_tv_details(self, show_id):
        return {"seasons": []}


SHOW_INFO = {"id": 5, "name": "Demo Show", "year": "2020"}


def _seasons(spec: dict[int, dict[int, str]]) -> dict:
    return {
        num: {
            "titles": titles,
            "posters": {},
            "episodes": {},
            "count": len(titles),
        }
        for num, titles in spec.items()
    }


def make_scanner(root, seasons):
    from plex_renamer.engine._tv_scanner import TVScanner

    return TVScanner(FakeTMDB(_seasons(seasons)), SHOW_INFO, root)


class TestTableDrivenScan:
    def test_scan_produces_assignment_table(self, tmp_path):
        season_dir = tmp_path / "Season 01"
        season_dir.mkdir()
        (season_dir / "Demo Show S01E01.mkv").touch()
        scanner = make_scanner(tmp_path, {1: {1: "Pilot", 2: "Two"}})
        items, _ = scanner.scan()
        assert scanner.assignment_table is not None
        assert len(scanner.assignment_table.files) == 1
        assert items[0].file_id is not None
        assert items[0].status == "OK"

    def test_special_title_beats_wrong_number(self, tmp_path):
        # The headline bug: local S00E03 named "Special A" while TMDB
        # says e02 is "Special A" -> must map to e02, not e03.
        specials = tmp_path / "Specials"
        specials.mkdir()
        (specials / "S00E03 - Special A.mkv").touch()
        scanner = make_scanner(
            tmp_path,
            {0: {1: "Opening", 2: "Special A", 3: "Special C"},
             1: {1: "Pilot"}},
        )
        items, _ = scanner.scan()
        special = next(item for item in items if item.season == 0)
        assert special.episodes == [2]
        assert special.episode_confidence < 1.0

    def test_unmatched_special_is_not_silent_ok(self, tmp_path):
        specials = tmp_path / "Specials"
        specials.mkdir()
        (specials / "random home video.mkv").touch()
        scanner = make_scanner(
            tmp_path, {0: {1: "Opening"}, 1: {1: "Pilot"}},
        )
        items, _ = scanner.scan()
        special = next(item for item in items if item.season == 0)
        assert special.is_unmatched

    def test_same_named_specials_in_two_seasons_resolve_as_duplicate_copies(self, tmp_path):
        """Identical special files stored in two season folders are duplicate
        copies: one keeps the slot, the other is flagged, never a conflict."""
        for season_name in ("Season 01", "Season 02"):
            directory = tmp_path / season_name
            directory.mkdir()
            (directory / "S00E01 - Opening.mkv").touch()
        scanner = make_scanner(
            tmp_path, {0: {1: "Opening"}, 1: {1: "Pilot"}, 2: {1: "Reboot"}},
        )
        items, _ = scanner.scan()
        table = scanner.assignment_table
        assert not table.conflicts()
        assigned = [
            entry for entry in table.files.values()
            if table.assignment_for(entry.file_id) is not None
        ]
        assert len(assigned) == 1
        duplicate_reasons = [
            reason for reason in table.unassigned_reasons.values()
            if "duplicate copy" in reason
        ]
        assert len(duplicate_reasons) == 1

    def test_episode_confidence_set_on_specials(self, tmp_path):
        specials = tmp_path / "Specials"
        specials.mkdir()
        (specials / "S00E01.mkv").touch()  # number only, no title
        scanner = make_scanner(
            tmp_path, {0: {1: "Opening"}, 1: {1: "Pilot"}},
        )
        items, _ = scanner.scan()
        special = next(item for item in items if item.season == 0)
        assert special.episode_confidence < 1.0


class TestSpecialsOnlyShow:
    def test_specials_only_folder_scans_season_zero(self, tmp_path):
        specials = tmp_path / "Specials"
        specials.mkdir()
        (specials / "S00E01 - Opening.mkv").touch()
        scanner = make_scanner(
            tmp_path, {0: {1: "Opening"}, 1: {1: "Pilot"}},
        )
        items, _ = scanner.scan()
        assert all(item.season == 0 for item in items)

    def test_infer_season_assignment_returns_zero_for_all_s00_evidence(self):
        from plex_renamer.engine.models import (
            DirectEpisodeEvidence,
            infer_explicit_season_assignment,
        )
        evidence = [
            DirectEpisodeEvidence(0, 1, "Opening"),
            DirectEpisodeEvidence(0, 2, "Recap"),
        ]
        assert infer_explicit_season_assignment(
            Path("Some Show"), evidence,
        ) == 0

    def test_collect_evidence_descends_specials_folder(self, tmp_path):
        from plex_renamer.engine.models import collect_direct_episode_evidence
        specials = tmp_path / "Specials"
        specials.mkdir()
        (specials / "S00E01 - Opening.mkv").touch()
        evidence = collect_direct_episode_evidence(tmp_path)
        assert any(item.season_num == 0 for item in evidence)
