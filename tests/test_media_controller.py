"""Tests for MediaController — UI-neutral session orchestration."""
from __future__ import annotations

import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from plex_renamer.app.controllers.media_controller import MediaController
from plex_renamer.app.models import ScanLifecycle, ScanProgress
from plex_renamer.app.services.command_gating_service import CommandGatingService
from plex_renamer.app.services.settings_service import SettingsService
from plex_renamer.app.services.cache_service import PersistentCacheService
from plex_renamer.app.services.refresh_policy_service import RefreshPolicyService
from plex_renamer.constants import MediaType
from plex_renamer.engine import PreviewItem, ScanCancelledError, ScanState
from plex_renamer.job_store import JobStore, RenameJob


# ── Fake TMDB client ─────────────────────────────────────────────────

class _FakeTMDB:
    language = "en-US"

    def search_tv_batch(self, queries, progress_callback=None):
        results = []
        total = len(queries)
        for index, (name, year) in enumerate(queries, start=1):
            if progress_callback:
                progress_callback(index, total)
            results.append([
                {
                    "id": hash(name) % 10000,
                    "name": name,
                    "year": year or "2020",
                    "poster_path": None,
                    "overview": "",
                    "number_of_seasons": 1,
                    "number_of_episodes": 12,
                }
            ])
        return results

    def get_alternative_titles(self, media_id, media_type="tv"):
        return []

    def get_tv_details(self, show_id):
        return {"number_of_seasons": 1, "number_of_episodes": 12}

    def get_episode_list(self, show_id, season_number):
        return [
            {"episode_number": i, "name": f"Episode {i}"}
            for i in range(1, 13)
        ]


class _FakeMovieScanner:
    def __init__(self, chosen_by_path, search_results):
        self.movie_info = chosen_by_path
        self._search_results = search_results

    def get_search_results(self, path):
        return list(self._search_results.get(path, []))


class _SlowTMDB(_FakeTMDB):
    def search_tv_batch(self, queries, progress_callback=None):
        results = []
        total = len(queries)
        for index, (name, year) in enumerate(queries, start=1):
            time.sleep(0.05)
            if progress_callback:
                progress_callback(index, total)
            results.append([
                {
                    "id": index,
                    "name": name,
                    "year": year or "2020",
                    "poster_path": None,
                    "overview": "",
                    "number_of_seasons": 1,
                    "number_of_episodes": 12,
                }
            ])
        return results


class _CancelableBatchOrchestrator:
    def __init__(self, states):
        self.states = states

    def scan_all(self, progress_callback=None, cancel_event=None):
        total = len(self.states)
        self.states[0].scanned = True
        self.states[0].preview_items = [
            PreviewItem(
                original=self.states[0].folder / "Episode.mkv",
                new_name="Episode.mkv",
                target_dir=self.states[0].folder,
                season=1,
                episodes=[1],
                status="OK",
            )
        ]
        if progress_callback:
            progress_callback(1, total)
        while cancel_event is not None and not cancel_event.is_set():
            time.sleep(0.01)
        raise ScanCancelledError("Scan cancelled")


class _SlowMovieBatchScanner:
    def __init__(self, tmdb, root_folder, files=None):
        self.tmdb = tmdb
        self.root = root_folder
        self._explicit_files = files
        self.movie_info = {}

    def scan(self, pick_movie_callback=None, progress_callback=None, cancel_event=None):
        total = 5
        for index in range(1, total + 1):
            if cancel_event is not None and cancel_event.is_set():
                raise ScanCancelledError("Scan cancelled")
            if progress_callback:
                progress_callback(index, total, "Searching TMDB...")
            time.sleep(0.05)
        return []


# ── Helper to build a controller with temp services ──────────────────

def _make_controller(tmp: Path):
    db_path = tmp / "test.db"
    store = JobStore(db_path=db_path)
    settings_path = tmp / "settings.json"
    cache_path = tmp / "cache.db"
    cache = PersistentCacheService(db_path=cache_path)
    return MediaController(
        job_store=store,
        command_gating=CommandGatingService(),
        settings=SettingsService(path=settings_path),
        cache_service=cache,
        refresh_policy=RefreshPolicyService(),
    ), store


# ── Tests ─────────────────────────────────────────────────────────────

class MediaControllerInitTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory(ignore_cleanup_errors=True)
        self.tmp = Path(self._tmp.name)
        self.ctrl, self.store = _make_controller(self.tmp)

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def test_initial_state(self):
        self.assertEqual(self.ctrl.active_content_mode, MediaType.TV)
        self.assertIsNone(self.ctrl.active_library_mode)
        self.assertFalse(self.ctrl.batch_mode)
        self.assertIsNone(self.ctrl.active_scan)
        self.assertEqual(self.ctrl.library_states, [])
        self.assertEqual(self.ctrl.scan_progress.lifecycle, ScanLifecycle.IDLE)
        self.assertIsNone(self.ctrl.tv_root_folder)
        self.assertIsNone(self.ctrl.movie_folder)
        self.assertIsNone(self.ctrl.library_selected_index)

    def test_library_states_routes_to_batch_states_for_tv(self):
        state = ScanState(
            folder=self.tmp / "Show",
            media_info={"id": 1, "name": "Show"},
        )
        self.ctrl._batch_states = [state]
        self.ctrl._active_library_mode = MediaType.TV
        self.assertEqual(self.ctrl.library_states, [state])

    def test_library_states_routes_to_movie_states_for_movie(self):
        state = ScanState(
            folder=self.tmp / "Movie",
            media_info={"id": 2, "title": "Movie"},
        )
        self.ctrl._movie_library_states = [state]
        self.ctrl._active_library_mode = MediaType.MOVIE
        self.assertEqual(self.ctrl.library_states, [state])


class AcceptTVShowTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory(ignore_cleanup_errors=True)
        self.tmp = Path(self._tmp.name)
        self.ctrl, self.store = _make_controller(self.tmp)

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def test_accept_tv_show_sets_mode_and_state(self):
        folder = self.tmp / "Naruto"
        folder.mkdir()
        show_info = {
            "id": 100,
            "name": "Naruto",
            "year": "2002",
            "number_of_seasons": 1,
        }

        state = self.ctrl.accept_tv_show(folder, _FakeTMDB(), show_info)

        self.assertEqual(self.ctrl.active_content_mode, MediaType.TV)
        self.assertEqual(self.ctrl.active_library_mode, MediaType.TV)
        self.assertFalse(self.ctrl.batch_mode)
        self.assertIs(self.ctrl.active_scan, state)
        self.assertEqual(len(self.ctrl.batch_states), 1)
        self.assertEqual(self.ctrl.tv_root_folder, folder)
        self.assertEqual(state.media_info["id"], 100)
        self.assertFalse(state.scanned)

    def test_accept_tv_show_fires_listeners(self):
        events = []

        self.ctrl.add_listener(
            on_mode_changed=lambda cm, lm: events.append(("mode", cm, lm)),
            on_library_changed=lambda s: events.append(("library", len(s))),
            on_progress=lambda p: events.append(("progress", p.lifecycle)),
        )

        folder = self.tmp / "Show"
        folder.mkdir()
        self.ctrl.accept_tv_show(folder, _FakeTMDB(), {"id": 1, "name": "Show"})

        mode_events = [e for e in events if e[0] == "mode"]
        lib_events = [e for e in events if e[0] == "library"]
        self.assertTrue(len(mode_events) >= 1)
        self.assertTrue(len(lib_events) >= 1)
        self.assertEqual(mode_events[0], ("mode", MediaType.TV, MediaType.TV))
        self.assertEqual(lib_events[0], ("library", 1))


class SelectShowTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory(ignore_cleanup_errors=True)
        self.tmp = Path(self._tmp.name)
        self.ctrl, self.store = _make_controller(self.tmp)

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def test_select_show_sets_active_scan(self):
        states = [
            ScanState(folder=self.tmp / "A", media_info={"id": 1, "name": "A"}),
            ScanState(folder=self.tmp / "B", media_info={"id": 2, "name": "B"}),
        ]
        self.ctrl._batch_states = states
        self.ctrl._active_content_mode = MediaType.TV
        self.ctrl._active_library_mode = MediaType.TV

        result = self.ctrl.select_show(1)
        self.assertIs(result, states[1])
        self.assertIs(self.ctrl.active_scan, states[1])
        self.assertEqual(self.ctrl.library_selected_index, 1)

    def test_select_show_out_of_range_returns_none(self):
        self.ctrl._batch_states = []
        self.ctrl._active_library_mode = MediaType.TV
        result = self.ctrl.select_show(5)
        self.assertIsNone(result)


class TVBatchTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory(ignore_cleanup_errors=True)
        self.tmp = Path(self._tmp.name)
        self.ctrl, self.store = _make_controller(self.tmp)

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def test_start_tv_batch_populates_states(self):
        root = self.tmp / "tv_root"
        (root / "Naruto" / "Season 01").mkdir(parents=True)
        (root / "Naruto" / "Season 01" / "Naruto - S01E01.mkv").write_text("x")

        events = []
        self.ctrl.add_listener(
            on_library_changed=lambda s: events.append(("library", len(s))),
            on_scan_complete=lambda s: events.append(("complete",)),
        )

        self.ctrl.start_tv_batch(root, _FakeTMDB())

        self.assertTrue(self.ctrl.batch_mode)
        self.assertEqual(self.ctrl.active_content_mode, MediaType.TV)
        self.assertEqual(self.ctrl.tv_root_folder, root)

        # Wait for background thread
        for _ in range(50):
            if self.ctrl.batch_states:
                break
            time.sleep(0.1)

        self.assertTrue(len(self.ctrl.batch_states) >= 1)
        naruto = [s for s in self.ctrl.batch_states if "Naruto" in s.display_name]
        self.assertTrue(len(naruto) >= 1)

    def test_start_tv_batch_empty_folder(self):
        root = self.tmp / "empty_root"
        root.mkdir()

        self.ctrl.start_tv_batch(root, _FakeTMDB())

        for _ in range(50):
            if self.ctrl.scan_progress.lifecycle in (
                ScanLifecycle.WARNING,
                ScanLifecycle.READY,
            ):
                break
            time.sleep(0.1)

        self.assertEqual(self.ctrl.batch_states, [])

    def test_cancel_tv_batch_sets_cancelled_progress(self):
        root = self.tmp / "tv_root"
        for name in ("Naruto", "Bleach", "One Piece"):
            (root / name / "Season 01").mkdir(parents=True)
            (root / name / "Season 01" / f"{name} - S01E01.mkv").write_text("x")

        self.ctrl.start_tv_batch(root, _SlowTMDB())

        for _ in range(50):
            if self.ctrl.scan_progress.lifecycle == ScanLifecycle.MATCHING:
                break
            time.sleep(0.02)

        self.assertTrue(self.ctrl.cancel_scan())

        for _ in range(50):
            if self.ctrl.scan_progress.lifecycle == ScanLifecycle.CANCELLED:
                break
            time.sleep(0.02)

        self.assertEqual(self.ctrl.scan_progress.lifecycle, ScanLifecycle.CANCELLED)
        self.assertEqual(self.ctrl.batch_states, [])

    def test_cancel_tv_bulk_scan_preserves_partial_results(self):
        states = [
            ScanState(folder=self.tmp / "ShowA", media_info={"id": 1, "name": "ShowA"}),
            ScanState(folder=self.tmp / "ShowB", media_info={"id": 2, "name": "ShowB"}),
        ]
        for state in states:
            state.folder.mkdir()

        self.ctrl._batch_mode = True
        self.ctrl._active_content_mode = MediaType.TV
        self.ctrl._active_library_mode = MediaType.TV
        self.ctrl._batch_states = states
        self.ctrl._batch_orchestrator = _CancelableBatchOrchestrator(states)

        self.ctrl.scan_all_shows()

        for _ in range(50):
            if self.ctrl.scan_progress.done >= 1:
                break
            time.sleep(0.02)

        self.assertTrue(self.ctrl.cancel_scan())

        for _ in range(50):
            if self.ctrl.scan_progress.lifecycle == ScanLifecycle.CANCELLED:
                break
            time.sleep(0.02)

        self.assertEqual(self.ctrl.scan_progress.lifecycle, ScanLifecycle.CANCELLED)
        self.assertTrue(self.ctrl.batch_states[0].scanned)
        self.assertFalse(self.ctrl.batch_states[1].scanned)


class MovieStateBuildTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory(ignore_cleanup_errors=True)
        self.tmp = Path(self._tmp.name)
        self.ctrl, self.store = _make_controller(self.tmp)

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def test_build_movie_library_states_uses_scanner_metadata_and_skips_non_movies(self):
        movie_file = self.tmp / "Dune.Part.Two.2024.mkv"
        skipped_file = self.tmp / "Show.S01E01.mkv"

        movie_item = PreviewItem(
            original=movie_file,
            new_name="Dune Part Two (2024).mkv",
            target_dir=self.tmp / "Dune Part Two (2024)",
            season=None,
            episodes=[],
            status="OK",
            media_type=MediaType.MOVIE,
            media_id=693134,
            media_name="Dune: Part Two",
        )
        skipped_item = PreviewItem(
            original=skipped_file,
            new_name=None,
            target_dir=None,
            season=None,
            episodes=[],
            status="SKIP: not a movie",
            media_type=MediaType.OTHER,
        )
        scanner = _FakeMovieScanner(
            chosen_by_path={
                movie_file: {
                    "id": 693134,
                    "title": "Dune: Part Two",
                    "year": "2024",
                    "poster_path": "/poster.jpg",
                    "overview": "Paul Atreides unites with the Fremen.",
                }
            },
            search_results={
                movie_file: [
                    {"id": 693134, "title": "Dune: Part Two"},
                    {"id": 1, "title": "Other Match"},
                ]
            },
        )

        self.ctrl._build_movie_library_states([movie_item, skipped_item], scanner)

        self.assertEqual(len(self.ctrl.movie_library_states), 1)
        state = self.ctrl.movie_library_states[0]
        self.assertEqual(state.media_info["id"], 693134)
        self.assertEqual(state.media_info["title"], "Dune: Part Two")
        self.assertEqual(state.media_info["poster_path"], "/poster.jpg")
        self.assertEqual(len(state.search_results), 2)
        self.assertEqual(len(state.alternate_matches), 1)
        self.assertIs(state.scanner, scanner)
        self.assertTrue(state.checked)

    def test_build_movie_library_states_marks_actionable_duplicate_under_ready_primary(self):
        proper_dir = self.tmp / "Alien (1979)"
        proper_dir.mkdir()
        proper_file = proper_dir / "Alien (1979).mkv"

        duplicate_dir = self.tmp / "Alien.Source"
        duplicate_dir.mkdir()
        duplicate_file = duplicate_dir / "Alien.1979.1080p.mkv"

        proper_item = PreviewItem(
            original=proper_file,
            new_name="Alien (1979).mkv",
            target_dir=proper_dir,
            season=None,
            episodes=[],
            status="OK",
            media_type=MediaType.MOVIE,
            media_id=42,
            media_name="Alien",
        )
        duplicate_item = PreviewItem(
            original=duplicate_file,
            new_name="Alien (1979).mkv",
            target_dir=self.tmp / "Alien (1979)",
            season=None,
            episodes=[],
            status="OK",
            media_type=MediaType.MOVIE,
            media_id=42,
            media_name="Alien",
        )
        scanner = _FakeMovieScanner(
            chosen_by_path={
                proper_file: {"id": 42, "title": "Alien", "year": "1979", "poster_path": None, "overview": ""},
                duplicate_file: {"id": 42, "title": "Alien", "year": "1979", "poster_path": None, "overview": ""},
            },
            search_results={proper_file: [{"id": 42, "title": "Alien"}], duplicate_file: [{"id": 42, "title": "Alien"}]},
        )
        self.ctrl._movie_folder = self.tmp

        self.ctrl._build_movie_library_states([duplicate_item, proper_item], scanner)

        by_folder = {state.folder.name: state for state in self.ctrl.movie_library_states}
        proper_state = by_folder["Alien (1979)"]
        duplicate_state = by_folder["Alien.Source"]

        self.assertIsNone(proper_state.duplicate_of)
        self.assertEqual(duplicate_state.duplicate_of, proper_state.display_name)
        self.assertEqual(duplicate_state.duplicate_of_relative_folder, "Alien (1979)")
        self.assertFalse(proper_state.checked)
        self.assertFalse(duplicate_state.checked)


class RematchStateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory(ignore_cleanup_errors=True)
        self.tmp = Path(self._tmp.name)
        self.ctrl, self.store = _make_controller(self.tmp)

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def test_rematch_tv_state_updates_match_and_alternates(self):
        state = ScanState(
            folder=self.tmp / "Andor.2022",
            media_info={"id": 10, "name": "Andor", "year": "2022"},
            confidence=0.4,
            scanned=True,
            search_results=[
                {"id": 10, "name": "Andor", "year": "2022"},
                {"id": 20, "name": "Andor", "year": "2022"},
                {"id": 30, "name": "Random", "year": "1999"},
            ],
            alternate_matches=[
                {"id": 20, "name": "Andor", "year": "2022"},
            ],
        )
        self.ctrl._batch_states = [state]
        self.ctrl._active_library_mode = MediaType.TV

        self.ctrl.rematch_tv_state(state, {"id": 20, "name": "Andor", "year": "2022"})

        self.assertEqual(state.media_info["id"], 20)
        self.assertFalse(state.scanned)
        alternate_ids = [match["id"] for match in state.alternate_matches]
        self.assertIn(10, alternate_ids)
        self.assertNotIn(20, alternate_ids)

    def test_rematch_tv_state_keeps_runner_up_suggestions_without_score_threshold(self):
        state = ScanState(
            folder=self.tmp / "Man.DOk.Ngew.2016",
            media_info={"id": 10, "name": "Man Dok Ngew", "year": "2016"},
            confidence=0.28,
            scanned=True,
            search_results=[
                {"id": 10, "name": "Man Dok Ngew", "year": "2016"},
                {"id": 20, "name": "Marn Dok Ngeo", "year": "2016"},
                {"id": 30, "name": "Dok Ngew", "year": "2017"},
            ],
        )
        self.ctrl._batch_states = [state]
        self.ctrl._active_library_mode = MediaType.TV

        with patch(
            "plex_renamer.app.controllers.media_controller.score_results",
            return_value=[
                ({"id": 20, "name": "Marn Dok Ngeo", "year": "2016"}, 0.22),
                ({"id": 10, "name": "Man Dok Ngew", "year": "2016"}, 0.21),
                ({"id": 30, "name": "Dok Ngew", "year": "2017"}, 0.18),
            ],
        ):
            self.ctrl.rematch_tv_state(state, {"id": 20, "name": "Marn Dok Ngeo", "year": "2016"})

        self.assertEqual(state.media_info["id"], 20)
        self.assertEqual([match["id"] for match in state.alternate_matches], [10, 30])

    def test_rematch_movie_state_rebuilds_preview(self):
        movie_file = self.tmp / "Dune.Part.Two.2024.mkv"
        old_item = PreviewItem(
            original=movie_file,
            new_name="Old Match (2023).mkv",
            target_dir=self.tmp / "Old Match (2023)",
            season=None,
            episodes=[],
            status="REVIEW: verify",
            media_type=MediaType.MOVIE,
            media_id=1,
            media_name="Old Match",
        )

        class _RematchScanner:
            def __init__(self, target_root):
                self._target_root = target_root
                self.movie_info = {movie_file: {"id": 1, "title": "Old Match", "year": "2023"}}
                self._results = {
                    movie_file: [
                        {"id": 99, "title": "Dune: Part Two", "year": "2024", "poster_path": "/poster.jpg", "overview": "Paul Atreides returns."},
                        {"id": 1, "title": "Old Match", "year": "2023", "poster_path": None, "overview": ""},
                    ]
                }

            def rematch_file(self, item, chosen):
                self.movie_info[item.original] = chosen
                return PreviewItem(
                    original=item.original,
                    new_name=f"{chosen['title']} ({chosen['year']}).mkv",
                    target_dir=self._target_root / f"{chosen['title']} ({chosen['year']})",
                    season=None,
                    episodes=[],
                    status="OK",
                    media_type=MediaType.MOVIE,
                    media_id=chosen["id"],
                    media_name=chosen["title"],
                )

            def get_search_results(self, path):
                return list(self._results.get(path, []))

        scanner = _RematchScanner(self.tmp)
        state = ScanState(
            folder=self.tmp,
            media_info={"id": 1, "title": "Old Match", "year": "2023"},
            preview_items=[old_item],
            confidence=0.5,
            scanned=True,
            checked=False,
            scanner=scanner,
            search_results=scanner.get_search_results(movie_file),
            alternate_matches=[scanner.get_search_results(movie_file)[0]],
        )
        self.ctrl._movie_library_states = [state]
        self.ctrl._movie_preview_items = [old_item]
        self.ctrl._active_library_mode = MediaType.MOVIE

        self.ctrl.rematch_movie_state(
            state,
            {"id": 99, "title": "Dune: Part Two", "year": "2024", "poster_path": "/poster.jpg", "overview": "Paul Atreides returns."},
        )

        self.assertEqual(state.media_info["id"], 99)
        self.assertEqual(state.preview_items[0].new_name, "Dune: Part Two (2024).mkv")
        self.assertTrue(state.checked)
        self.assertEqual(self.ctrl.movie_preview_items[0].media_id, 99)


class MovieBatchCancellationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory(ignore_cleanup_errors=True)
        self.tmp = Path(self._tmp.name)
        self.ctrl, self.store = _make_controller(self.tmp)

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def test_cancel_movie_batch_sets_cancelled_progress(self):
        root = self.tmp / "movies"
        root.mkdir()

        with patch(
            "plex_renamer.app.controllers.media_controller.MovieScanner",
            _SlowMovieBatchScanner,
        ):
            self.ctrl.start_movie_batch(root, _FakeTMDB())

            for _ in range(50):
                if self.ctrl.scan_progress.lifecycle == ScanLifecycle.SCANNING:
                    break
                time.sleep(0.02)

            self.assertTrue(self.ctrl.cancel_scan())

            for _ in range(50):
                if self.ctrl.scan_progress.lifecycle == ScanLifecycle.CANCELLED:
                    break
                time.sleep(0.02)

        self.assertEqual(self.ctrl.scan_progress.lifecycle, ScanLifecycle.CANCELLED)
        self.assertEqual(self.ctrl.movie_library_states, [])


class SessionSaveRestoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory(ignore_cleanup_errors=True)
        self.tmp = Path(self._tmp.name)
        self.ctrl, self.store = _make_controller(self.tmp)

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def test_save_restore_tv_from_tab_switch(self):
        state = ScanState(
            folder=self.tmp / "Show",
            media_info={"id": 1, "name": "Show"},
        )
        self.ctrl._batch_mode = True
        self.ctrl._batch_states = [state]
        self.ctrl._active_scan = state
        self.ctrl._tv_root_folder = self.tmp / "tv"
        self.ctrl._library_selected_index = 0

        snapshot = self.ctrl.snapshot_tv_for_tab_switch()

        # Clear state
        self.ctrl._batch_mode = False
        self.ctrl._batch_states = []
        self.ctrl._active_scan = None
        self.ctrl._tv_root_folder = None

        # Restore
        events = []
        self.ctrl.add_listener(
            on_mode_changed=lambda cm, lm: events.append("mode"),
            on_library_changed=lambda s: events.append("library"),
        )
        self.ctrl.restore_tv_from_tab_switch(snapshot)

        self.assertTrue(self.ctrl.batch_mode)
        self.assertEqual(len(self.ctrl.batch_states), 1)
        self.assertIs(self.ctrl.active_scan, state)
        self.assertEqual(self.ctrl.active_content_mode, MediaType.TV)
        self.assertIn("mode", events)
        self.assertIn("library", events)

    def test_save_restore_movie_from_tab_switch(self):
        item = PreviewItem(
            original=self.tmp / "Movie.mkv",
            new_name="Movie (2021).mkv",
            target_dir=self.tmp / "Movie (2021)",
            season=None,
            episodes=[],
            status="OK",
            media_type=MediaType.MOVIE,
            media_id=500,
            media_name="Movie",
        )
        state = ScanState(
            folder=self.tmp,
            media_info={"id": 500, "title": "Movie"},
            preview_items=[item],
            scanned=True,
        )
        self.ctrl._movie_library_states = [state]
        self.ctrl._movie_preview_items = [item]
        self.ctrl._movie_folder = self.tmp
        self.ctrl._active_content_mode = MediaType.MOVIE
        self.ctrl._active_library_mode = MediaType.MOVIE

        snapshot = self.ctrl.snapshot_movie_for_tab_switch()

        # Clear state
        self.ctrl._movie_library_states = []
        self.ctrl._movie_preview_items = []
        self.ctrl._active_content_mode = MediaType.TV

        self.ctrl.restore_movie_from_tab_switch(snapshot)

        self.assertEqual(len(self.ctrl.movie_library_states), 1)
        self.assertEqual(len(self.ctrl.movie_preview_items), 1)
        self.assertEqual(self.ctrl.active_content_mode, MediaType.MOVIE)
        self.assertEqual(self.ctrl.active_library_mode, MediaType.MOVIE)


class SyncQueuedStatesTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory(ignore_cleanup_errors=True)
        self.tmp = Path(self._tmp.name)
        self.ctrl, self.store = _make_controller(self.tmp)

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def test_sync_marks_queued_tv_states(self):
        state = ScanState(
            folder=self.tmp / "Show",
            media_info={"id": 100, "name": "Show"},
        )
        self.ctrl._batch_states = [state]

        # Add a pending job for this show
        job = RenameJob(
            library_root=str(self.tmp),
            source_folder="Show",
            media_type=MediaType.TV,
            tmdb_id=100,
        )
        self.store.add_job(job)

        self.ctrl.sync_queued_states()
        self.assertTrue(state.queued)

    def test_sync_does_not_mark_unmatched_states(self):
        state = ScanState(
            folder=self.tmp / "Other",
            media_info={"id": 999, "name": "Other"},
        )
        self.ctrl._batch_states = [state]

        self.ctrl.sync_queued_states()
        self.assertFalse(state.queued)

    def test_sync_marks_duplicates_as_not_queued(self):
        state = ScanState(
            folder=self.tmp / "Dup",
            media_info={"id": 100, "name": "Dup"},
            duplicate_of="Primary Show",
        )
        self.ctrl._batch_states = [state]

        job = RenameJob(
            library_root=str(self.tmp),
            source_folder="Dup",
            media_type=MediaType.TV,
            tmdb_id=100,
        )
        self.store.add_job(job)

        self.ctrl.sync_queued_states()
        self.assertFalse(state.queued)

    def test_sync_marks_movie_duplicates_as_not_queued(self):
        state = ScanState(
            folder=self.tmp / "DupMovie",
            media_info={"id": 100, "title": "Dup Movie", "_media_type": MediaType.MOVIE},
            duplicate_of="Primary Movie",
        )
        self.ctrl._movie_library_states = [state]

        job = RenameJob(
            library_root=str(self.tmp),
            source_folder="DupMovie",
            media_type=MediaType.MOVIE,
            tmdb_id=100,
        )
        self.store.add_job(job)

        self.ctrl.sync_queued_states()
        self.assertFalse(state.queued)


class ListenerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory(ignore_cleanup_errors=True)
        self.tmp = Path(self._tmp.name)
        self.ctrl, self.store = _make_controller(self.tmp)

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def test_add_and_clear_listeners(self):
        lid = self.ctrl.add_listener(on_progress=lambda p: None)
        self.assertEqual(lid, 0)
        self.assertEqual(len(self.ctrl._listeners), 1)

        self.ctrl.clear_listeners()
        self.assertEqual(len(self.ctrl._listeners), 0)

    def test_listener_error_does_not_propagate(self):
        def bad_callback(states):
            raise RuntimeError("boom")

        self.ctrl.add_listener(on_library_changed=bad_callback)

        # Should not raise
        self.ctrl._notify("library_changed", [])

    def test_progress_notification(self):
        progress_events = []
        self.ctrl.add_listener(
            on_progress=lambda p: progress_events.append(p),
        )

        self.ctrl._set_progress(
            ScanLifecycle.SCANNING,
            phase="Testing",
            done=5,
            total=10,
            message="Testing 5/10",
        )

        self.assertEqual(len(progress_events), 1)
        self.assertEqual(progress_events[0].lifecycle, ScanLifecycle.SCANNING)
        self.assertEqual(progress_events[0].done, 5)
        self.assertEqual(progress_events[0].total, 10)


if __name__ == "__main__":
    unittest.main()
