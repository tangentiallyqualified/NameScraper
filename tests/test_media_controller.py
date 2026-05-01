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
from plex_renamer.constants import JobStatus, MediaType
from plex_renamer.engine import BatchTVOrchestrator, PreviewItem, RenameResult, ScanCancelledError, ScanState, set_auto_accept_threshold
from plex_renamer.job_store import JobStore, RenameJob, RenameOp


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

    def get_season_map(self, show_id):
        return {}, 0

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


def _wait_until(
    predicate,
    *,
    timeout_s: float = 2.0,
    interval_s: float = 0.01,
    description: str,
) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval_s)
    raise AssertionError(f"Timed out waiting for {description}")


class _ControllerTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory(ignore_cleanup_errors=True)
        self.tmp = Path(self._tmp.name)
        self.ctrl, self.store = _make_controller(self.tmp)

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def set_tv_session(
        self,
        states,
        *,
        active_scan=None,
        batch_mode=True,
        tv_root_folder=None,
        batch_orchestrator=None,
        selected_index=None,
    ) -> None:
        self.ctrl._batch_mode = batch_mode
        self.ctrl._batch_states = list(states)
        self.ctrl._active_content_mode = MediaType.TV
        self.ctrl._active_library_mode = MediaType.TV
        self.ctrl._active_scan = active_scan
        self.ctrl._batch_orchestrator = batch_orchestrator
        self.ctrl._tv_root_folder = tv_root_folder
        self.ctrl.library_selected_index = selected_index

    def set_movie_session(
        self,
        states,
        *,
        preview_items=None,
        movie_folder=None,
        movie_scanner=None,
        movie_media_info=None,
        selected_index=None,
    ) -> None:
        self.ctrl._movie_library_states = list(states)
        self.ctrl._movie_preview_items = list(preview_items or [])
        self.ctrl._movie_folder = movie_folder
        self.ctrl._movie_scanner = movie_scanner
        self.ctrl._movie_media_info = movie_media_info
        self.ctrl._active_content_mode = MediaType.MOVIE
        self.ctrl._active_library_mode = MediaType.MOVIE
        self.ctrl.library_selected_index = selected_index


# ── Tests ─────────────────────────────────────────────────────────────

class MediaControllerInitTests(_ControllerTestCase):

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
        self.set_tv_session([state], batch_mode=False)
        self.assertEqual(self.ctrl.library_states, [state])

    def test_library_states_routes_to_movie_states_for_movie(self):
        state = ScanState(
            folder=self.tmp / "Movie",
            media_info={"id": 2, "title": "Movie"},
        )
        self.set_movie_session([state])
        self.assertEqual(self.ctrl.library_states, [state])

    def test_accept_tv_show_preserves_detected_season_assignment(self):
        folder = self.tmp / "Yuru Camp Specials"
        folder.mkdir()

        state = self.ctrl.accept_tv_show(
            folder,
            _FakeTMDB(),
            {"id": 101, "name": "Yuru Camp", "year": "2018"},
        )

        self.assertEqual(state.season_assignment, 0)


class AcceptTVShowTests(_ControllerTestCase):

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
        self.assertEqual(len(mode_events), 1)
        self.assertEqual(len(lib_events), 1)
        self.assertEqual(mode_events[0], ("mode", MediaType.TV, MediaType.TV))
        self.assertEqual(lib_events[0], ("library", 1))


class SelectShowTests(_ControllerTestCase):

    def test_select_show_sets_active_scan(self):
        states = [
            ScanState(folder=self.tmp / "A", media_info={"id": 1, "name": "A"}),
            ScanState(folder=self.tmp / "B", media_info={"id": 2, "name": "B"}),
        ]
        self.set_tv_session(states, batch_mode=False)

        result = self.ctrl.select_show(1)
        self.assertIs(result, states[1])
        self.assertIs(self.ctrl.active_scan, states[1])
        self.assertEqual(self.ctrl.library_selected_index, 1)

    def test_select_show_out_of_range_returns_none(self):
        self.set_tv_session([], batch_mode=False)
        result = self.ctrl.select_show(5)
        self.assertIsNone(result)


class TVBatchTests(_ControllerTestCase):

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

        _wait_until(
            lambda: bool(self.ctrl.batch_states),
            description="TV batch states to populate",
        )

        self.assertEqual(len(self.ctrl.batch_states), 1)
        naruto = [s for s in self.ctrl.batch_states if "Naruto" in s.display_name]
        self.assertEqual(len(naruto), 1)

    def test_start_tv_batch_empty_folder(self):
        root = self.tmp / "empty_root"
        root.mkdir()

        self.ctrl.start_tv_batch(root, _FakeTMDB())

        _wait_until(
            lambda: self.ctrl.scan_progress.lifecycle in {
                ScanLifecycle.WARNING,
                ScanLifecycle.READY,
            },
            description="empty TV batch scan to finish",
        )

        self.assertEqual(self.ctrl.batch_states, [])

    def test_cancel_tv_batch_sets_cancelled_progress(self):
        root = self.tmp / "tv_root"
        for name in ("Naruto", "Bleach", "One Piece"):
            (root / name / "Season 01").mkdir(parents=True)
            (root / name / "Season 01" / f"{name} - S01E01.mkv").write_text("x")

        self.ctrl.start_tv_batch(root, _SlowTMDB())

        _wait_until(
            lambda: self.ctrl.scan_progress.lifecycle == ScanLifecycle.MATCHING,
            description="TV batch scan to enter MATCHING",
        )

        self.assertTrue(self.ctrl.cancel_scan())

        _wait_until(
            lambda: self.ctrl.scan_progress.lifecycle == ScanLifecycle.CANCELLED,
            description="TV batch scan cancellation",
        )

        self.assertEqual(self.ctrl.scan_progress.lifecycle, ScanLifecycle.CANCELLED)
        self.assertEqual(self.ctrl.batch_states, [])

    def test_cancel_tv_bulk_scan_preserves_partial_results(self):
        states = [
            ScanState(folder=self.tmp / "ShowA", media_info={"id": 1, "name": "ShowA"}),
            ScanState(folder=self.tmp / "ShowB", media_info={"id": 2, "name": "ShowB"}),
        ]
        for state in states:
            state.folder.mkdir()

        self.set_tv_session(
            states,
            batch_orchestrator=_CancelableBatchOrchestrator(states),
        )

        self.ctrl.scan_all_shows()

        _wait_until(
            lambda: self.ctrl.scan_progress.done >= 1,
            description="TV bulk scan to produce partial progress",
        )

        self.assertTrue(self.ctrl.cancel_scan())

        _wait_until(
            lambda: self.ctrl.scan_progress.lifecycle == ScanLifecycle.CANCELLED,
            description="TV bulk scan cancellation",
        )

        self.assertEqual(self.ctrl.scan_progress.lifecycle, ScanLifecycle.CANCELLED)
        self.assertTrue(self.ctrl.batch_states[0].scanned)
        self.assertFalse(self.ctrl.batch_states[1].scanned)

    def test_scan_all_shows_includes_queued_unscanned_states(self):
        state = ScanState(
            folder=self.tmp / "QueuedShow",
            media_info={"id": 11, "name": "Queued Show", "year": "2024"},
            scanned=False,
            queued=True,
        )

        class _QueuedPreviewOrchestrator:
            def scan_all(self, progress_callback=None, cancel_event=None):
                state.preview_items = [
                    PreviewItem(
                        original=Path("C:/library/tv/QueuedShow/Season 01/QueuedShow.S01E01.mkv"),
                        new_name="Queued Show (2024) - S01E01 - Pilot.mkv",
                        target_dir=Path("C:/library/tv/Queued Show (2024)/Season 01"),
                        season=1,
                        episodes=[1],
                        status="OK",
                    )
                ]
                state.scanned = True
                if progress_callback:
                    progress_callback(1, 1)

        self.set_tv_session([state], batch_orchestrator=_QueuedPreviewOrchestrator())

        self.ctrl.scan_all_shows()

        _wait_until(
            lambda: state.scanned and self.ctrl.scan_progress.lifecycle == ScanLifecycle.READY,
            description="queued TV batch state to finish scanning",
        )

        self.assertEqual(len(state.preview_items), 1)

    def test_scan_all_shows_reports_current_show_before_and_after_scan(self):
        states = [
            ScanState(folder=self.tmp / "ShowA", media_info={"id": 1, "name": "Show A"}),
            ScanState(folder=self.tmp / "ShowB", media_info={"id": 2, "name": "Show B"}),
        ]
        for state in states:
            state.folder.mkdir()

        class _ProgressOrchestrator:
            def __init__(self, scan_states):
                self.states = scan_states

            def scan_all(self, progress_callback=None, cancel_event=None):
                total = len(self.states)
                for index, state in enumerate(self.states):
                    if progress_callback:
                        progress_callback(index, total, state.display_name)
                    state.preview_items = [
                        PreviewItem(
                            original=state.folder / "Episode.mkv",
                            new_name="Episode.mkv",
                            target_dir=state.folder,
                            season=1,
                            episodes=[1],
                            status="OK",
                        )
                    ]
                    state.scanned = True
                    if progress_callback:
                        progress_callback(index + 1, total, state.display_name)

        events: list[ScanProgress] = []
        self.ctrl.add_listener(on_progress=events.append)
        self.set_tv_session(states, batch_orchestrator=_ProgressOrchestrator(states))

        self.ctrl.scan_all_shows()

        _wait_until(
            lambda: self.ctrl.scan_progress.lifecycle == ScanLifecycle.READY,
            description="TV bulk scan to finish",
        )

        scanning_events = [event for event in events if event.lifecycle == ScanLifecycle.SCANNING]
        self.assertTrue(any(event.current_item == "Show A" and event.done == 0 for event in scanning_events))
        self.assertTrue(any(event.current_item == "Show B" and event.done == 1 for event in scanning_events))
        self.assertTrue(any(event.current_item == "Show B" and event.done == 2 for event in scanning_events))

    def test_start_movie_batch_forwards_scanner_progress_to_scan_progress(self):
        root = self.tmp / "movies"
        root.mkdir()
        events: list[ScanProgress] = []
        self.ctrl.add_listener(on_progress=events.append)

        self.ctrl.start_movie_batch(root, _FakeTMDB(), scanner_factory=_SlowMovieBatchScanner)

        _wait_until(
            lambda: any(event.lifecycle == ScanLifecycle.SCANNING and event.done >= 2 for event in events),
            description="movie batch progress events",
        )
        self.ctrl.cancel_scan()

        movie_events = [event for event in events if event.lifecycle == ScanLifecycle.SCANNING]
        self.assertTrue(any(event.phase == "Searching TMDB..." for event in movie_events))
        self.assertTrue(any(event.done == 2 and event.total == 5 for event in movie_events))


class BatchTVOrchestratorRegressionTests(unittest.TestCase):

    def test_scan_all_includes_queued_unscanned_states(self):
        state = ScanState(
            folder=Path("C:/library/tv/QueuedShow"),
            media_info={"id": 11, "name": "Queued Show", "year": "2024"},
            scanned=False,
            queued=True,
        )
        orchestrator = BatchTVOrchestrator.__new__(BatchTVOrchestrator)
        orchestrator.states = [state]
        scanned: list[ScanState] = []
        orchestrator.scan_show = lambda current_state, cancel_event=None: scanned.append(current_state)

        orchestrator.scan_all()

        self.assertEqual(scanned, [state])


class ScanShowRegressionTests(_ControllerTestCase):

    def test_scan_show_uses_preserved_single_show_season_hint_after_rematch(self):
        folder = self.tmp / "Yuru Camp Specials"
        folder.mkdir()
        state = self.ctrl.accept_tv_show(
            folder,
            _FakeTMDB(),
            {"id": 101, "name": "Yuru Camp", "year": "2018"},
        )
        created: dict[str, object] = {}

        class _FakeScanner:
            def __init__(self, tmdb, show_info, root_folder, *, season_hint=None, season_folders=None):
                created["tmdb"] = tmdb
                created["show_info"] = show_info
                created["root_folder"] = root_folder
                created["season_hint"] = season_hint
                created["season_folders"] = season_folders

            def scan(self):
                created["scan_called"] = True
                return ([], False)

            def get_completeness(self, items, checked_indices):
                created["checked_indices"] = checked_indices
                return None

        self.ctrl.rematch_tv_state(state, {"id": 202, "name": "Yuru Camp", "year": "2018"})

        with patch("plex_renamer.app.controllers.media_controller.TVScanner", _FakeScanner):
            self.ctrl.scan_show(state, _FakeTMDB())

        _wait_until(
            lambda: state.scanned and self.ctrl.scan_progress.lifecycle == ScanLifecycle.READY,
            description="single-show rematch rescan to finish",
        )

        self.assertTrue(created.get("scan_called"))
        self.assertEqual(created.get("season_hint"), 0)
        self.assertIsNone(created.get("season_folders"))
        self.assertEqual(created.get("root_folder"), folder)
        self.assertEqual(created.get("checked_indices"), set())

    def test_scan_show_uses_batch_scan_inputs_for_rematched_tv_state(self):
        state = ScanState(
            folder=self.tmp / "Merged.Show",
            media_info={"id": 11, "name": "Merged Show", "year": "2024"},
            scanned=False,
            season_assignment=2,
            season_folders={2: self.tmp / "Merged.Show" / "Season 02"},
        )
        created: dict[str, object] = {}

        class _FakeScanner:
            def __init__(self, tmdb, show_info, root_folder, *, season_hint=None, season_folders=None):
                created["tmdb"] = tmdb
                created["show_info"] = show_info
                created["root_folder"] = root_folder
                created["season_hint"] = season_hint
                created["season_folders"] = season_folders

            def scan(self):
                created["scan_called"] = True
                return ([], True)

            def scan_consolidated(self):
                created["scan_consolidated_called"] = True
                return [
                    PreviewItem(
                        original=state.folder / "Season 02" / "Merged.Show.S02E01.mkv",
                        new_name="Merged Show (2024) - S02E01 - Pilot.mkv",
                        target_dir=state.folder / "Season 02",
                        season=2,
                        episodes=[1],
                        status="OK",
                    )
                ]

            def get_completeness(self, items, checked_indices):
                created["checked_indices"] = checked_indices
                return None

        self.set_tv_session([state], batch_mode=True)

        with patch("plex_renamer.app.controllers.media_controller.TVScanner", _FakeScanner):
            self.ctrl.scan_show(state, _FakeTMDB())

        _wait_until(
            lambda: state.scanned and self.ctrl.scan_progress.lifecycle == ScanLifecycle.READY,
            description="rematched TV state to finish scanning",
        )

        self.assertTrue(created.get("scan_called"))
        self.assertTrue(created.get("scan_consolidated_called"))
        self.assertEqual(created.get("season_hint"), 2)
        self.assertEqual(created.get("season_folders"), state.season_folders)
        self.assertEqual(created.get("checked_indices"), {0})
        self.assertEqual(len(state.preview_items), 1)
        self.assertEqual(state.preview_items[0].new_name, "Merged Show (2024) - S02E01 - Pilot.mkv")


class MovieStateBuildTests(_ControllerTestCase):

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
        self.assertFalse(state.checked)

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


class RematchStateTests(_ControllerTestCase):

    def tearDown(self):
        set_auto_accept_threshold(0.55)
        super().tearDown()

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
        self.set_tv_session([state], batch_mode=False)

        self.ctrl.rematch_tv_state(state, {"id": 20, "name": "Andor", "year": "2022"})

        self.assertEqual(state.media_info["id"], 20)
        self.assertFalse(state.scanned)
        alternate_ids = [match["id"] for match in state.alternate_matches]
        self.assertIn(10, alternate_ids)
        self.assertNotIn(20, alternate_ids)

    def test_rematch_tv_state_marks_manual_match_as_resolved(self):
        state = ScanState(
            folder=self.tmp / "Andor.2022",
            media_info={"id": 10, "name": "Andor", "year": "2022"},
            confidence=0.2,
            scanned=True,
            checked=False,
            search_results=[
                {"id": 10, "name": "Andor", "year": "2022"},
                {"id": 20, "name": "Andor", "year": "2022"},
            ],
        )
        self.set_tv_session([state], batch_mode=False)

        with patch(
            "plex_renamer.app.controllers.media_controller.score_results",
            return_value=[({"id": 20, "name": "Andor", "year": "2022"}, 0.22)],
        ):
            self.ctrl.rematch_tv_state(state, {"id": 20, "name": "Andor", "year": "2022"})

        self.assertEqual(state.match_origin, "manual")
        self.assertFalse(state.needs_review)
        self.assertFalse(state.checked)

    def test_apply_runtime_settings_updates_review_threshold(self):
        state = ScanState(
            folder=self.tmp / "Show.2024",
            media_info={"id": 10, "name": "Show", "year": "2024"},
            confidence=0.7,
            checked=True,
        )
        self.set_tv_session([state], batch_mode=False)

        self.ctrl.settings.auto_accept_threshold = 0.8
        self.ctrl.apply_runtime_settings()
        self.assertTrue(state.needs_review)
        self.assertFalse(state.checked)

        self.ctrl.settings.auto_accept_threshold = 0.6
        self.ctrl.apply_runtime_settings()
        self.assertFalse(state.needs_review)

    def test_apply_runtime_settings_reapplies_episode_review_threshold(self):
        item = PreviewItem(
            original=self.tmp / "Show.2024" / "Show.S01E01.mkv",
            new_name="Show (2024) - S01E01 - Pilot.mkv",
            target_dir=self.tmp / "Show (2024)" / "Season 01",
            season=1,
            episodes=[1],
            status="OK",
            episode_confidence=0.7,
        )
        state = ScanState(
            folder=self.tmp / "Show.2024",
            media_info={"id": 10, "name": "Show", "year": "2024"},
            preview_items=[item],
            confidence=1.0,
            checked=True,
        )
        self.set_tv_session([state], batch_mode=False)

        self.ctrl.settings.episode_auto_accept_threshold = 0.85
        self.ctrl.apply_runtime_settings()
        self.assertTrue(item.is_review)
        self.assertFalse(state.checked)

        self.ctrl.settings.episode_auto_accept_threshold = 0.6
        self.ctrl.apply_runtime_settings()
        self.assertEqual(item.status, "OK")

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
        self.set_tv_session([state], batch_mode=False)

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

    def test_rematch_tv_state_merges_single_season_into_existing_multi_season_card(self):
        (self.tmp / "Yuru Camp S02").mkdir()
        (self.tmp / "Yuru Camp S03").mkdir()
        (self.tmp / "Yuru Camp").mkdir()
        merged_state = ScanState(
            folder=self.tmp / "Yuru Camp S02",
            media_info={"id": 101, "name": "Laid-Back Camp", "year": "2018"},
            confidence=0.88,
            season_folders={
                2: self.tmp / "Yuru Camp S02",
                3: self.tmp / "Yuru Camp S03",
            },
            search_results=[
                {"id": 101, "name": "Laid-Back Camp", "year": "2018"},
                {"id": 202, "name": "Yuru Camp△", "year": "2020"},
            ],
            scanned=True,
            checked=True,
        )
        season_one_state = ScanState(
            folder=self.tmp / "Yuru Camp",
            media_info={"id": 202, "name": "Yuru Camp△", "year": "2020"},
            confidence=0.49,
            season_assignment=1,
            search_results=[
                {"id": 202, "name": "Yuru Camp△", "year": "2020"},
                {"id": 101, "name": "Laid-Back Camp", "year": "2018"},
            ],
            scanned=True,
            checked=False,
        )
        orchestrator = BatchTVOrchestrator.__new__(BatchTVOrchestrator)
        orchestrator.tmdb = _FakeTMDB()
        orchestrator.root = self.tmp

        self.set_tv_session(
            [merged_state, season_one_state],
            batch_mode=True,
            batch_orchestrator=orchestrator,
        )
        orchestrator.states = self.ctrl.batch_states

        effective_state = self.ctrl.rematch_tv_state(
            season_one_state,
            {"id": 101, "name": "Laid-Back Camp", "year": "2018"},
            orchestrator.tmdb,
        )

        self.assertIs(effective_state, merged_state)
        self.assertEqual(self.ctrl.batch_states, [merged_state])
        self.assertEqual(set(merged_state.season_folders.keys()), {1, 2, 3})
        self.assertIsNone(merged_state.duplicate_of)
        self.assertFalse(merged_state.scanned)

    def test_rematch_tv_state_merges_specials_into_existing_multi_season_card(self):
        (self.tmp / "Yuru Camp S01").mkdir()
        (self.tmp / "Yuru Camp S02").mkdir()
        (self.tmp / "Yuru Camp S03").mkdir()
        (self.tmp / "Yuru Camp Specials").mkdir()
        merged_state = ScanState(
            folder=self.tmp / "Yuru Camp S01",
            media_info={"id": 101, "name": "Laid-Back Camp", "year": "2018"},
            confidence=0.93,
            season_folders={
                1: self.tmp / "Yuru Camp S01",
                2: self.tmp / "Yuru Camp S02",
                3: self.tmp / "Yuru Camp S03",
            },
            search_results=[
                {"id": 101, "name": "Laid-Back Camp", "year": "2018"},
                {"id": 202, "name": "Yuru Camp△", "year": "2020"},
            ],
            scanned=True,
            checked=True,
        )
        specials_state = ScanState(
            folder=self.tmp / "Yuru Camp Specials",
            media_info={"id": 202, "name": "Yuru Camp△", "year": "2020"},
            confidence=0.32,
            season_assignment=0,
            search_results=[
                {"id": 202, "name": "Yuru Camp△", "year": "2020"},
                {"id": 101, "name": "Laid-Back Camp", "year": "2018"},
            ],
            scanned=True,
            checked=False,
        )
        orchestrator = BatchTVOrchestrator.__new__(BatchTVOrchestrator)
        orchestrator.tmdb = _FakeTMDB()
        orchestrator.root = self.tmp

        self.set_tv_session(
            [merged_state, specials_state],
            batch_mode=True,
            batch_orchestrator=orchestrator,
        )
        orchestrator.states = self.ctrl.batch_states

        effective_state = self.ctrl.rematch_tv_state(
            specials_state,
            {"id": 101, "name": "Laid-Back Camp", "year": "2018"},
            orchestrator.tmdb,
        )

        self.assertIs(effective_state, merged_state)
        self.assertEqual(self.ctrl.batch_states, [merged_state])
        self.assertEqual(set(merged_state.season_folders.keys()), {0, 1, 2, 3})

    def test_rematch_tv_state_resyncs_controller_batch_states_when_orchestrator_list_drifted(self):
        (self.tmp / "Yuru Camp S02").mkdir()
        (self.tmp / "Yuru Camp S03").mkdir()
        (self.tmp / "Yuru Camp").mkdir()
        merged_state = ScanState(
            folder=self.tmp / "Yuru Camp S02",
            media_info={"id": 101, "name": "Laid-Back Camp", "year": "2018"},
            confidence=0.88,
            season_folders={
                2: self.tmp / "Yuru Camp S02",
                3: self.tmp / "Yuru Camp S03",
            },
            search_results=[
                {"id": 101, "name": "Laid-Back Camp", "year": "2018"},
                {"id": 202, "name": "Yuru Camp△", "year": "2020"},
            ],
            scanned=True,
            checked=True,
        )
        season_one_state = ScanState(
            folder=self.tmp / "Yuru Camp",
            media_info={"id": 202, "name": "Yuru Camp△", "year": "2020"},
            confidence=0.49,
            season_assignment=1,
            search_results=[
                {"id": 202, "name": "Yuru Camp△", "year": "2020"},
                {"id": 101, "name": "Laid-Back Camp", "year": "2018"},
            ],
            scanned=True,
            checked=False,
        )
        orchestrator = BatchTVOrchestrator.__new__(BatchTVOrchestrator)
        orchestrator.tmdb = _FakeTMDB()
        orchestrator.root = self.tmp

        self.set_tv_session(
            [merged_state, season_one_state],
            batch_mode=True,
            batch_orchestrator=orchestrator,
        )
        orchestrator.states = list(self.ctrl.batch_states)

        effective_state = self.ctrl.rematch_tv_state(
            season_one_state,
            {"id": 101, "name": "Laid-Back Camp", "year": "2018"},
            orchestrator.tmdb,
        )

        self.assertIs(effective_state, merged_state)
        self.assertIs(self.ctrl.batch_states, orchestrator.states)
        self.assertEqual(self.ctrl.batch_states, [merged_state])
        self.assertEqual(set(merged_state.season_folders.keys()), {1, 2, 3})
        self.assertEqual(merged_state.match_origin, "manual")
        self.assertFalse(merged_state.scanned)

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
        self.set_movie_session(
            [state],
            preview_items=[old_item],
            movie_scanner=scanner,
        )

        self.ctrl.rematch_movie_state(
            state,
            {"id": 99, "title": "Dune: Part Two", "year": "2024", "poster_path": "/poster.jpg", "overview": "Paul Atreides returns."},
        )

        self.assertEqual(state.media_info["id"], 99)
        self.assertEqual(state.preview_items[0].new_name, "Dune: Part Two (2024).mkv")
        self.assertFalse(state.checked)
        self.assertEqual(state.match_origin, "manual")
        self.assertEqual(self.ctrl.movie_preview_items[0].media_id, 99)

    def test_approve_match_ignores_duplicates(self):
        state = ScanState(
            folder=self.tmp / "Alien.Source",
            media_info={"id": 42, "title": "Alien", "year": "1979"},
            confidence=0.2,
            checked=False,
            duplicate_of="Alien (1979)",
        )
        self.set_movie_session([state])

        self.ctrl.approve_match(state)

        self.assertEqual(state.match_origin, "auto")
        self.assertFalse(state.checked)

    def test_approve_match_resolves_movie_preview_review_status(self):
        movie_file = self.tmp / "Evangelion 3.0.mkv"
        preview = PreviewItem(
            original=movie_file,
            new_name="Evangelion: 3.0 You Can (Not) Redo (2012).mkv",
            target_dir=self.tmp / "Evangelion: 3.0 You Can (Not) Redo (2012)",
            season=None,
            episodes=[],
            status='REVIEW: best match "Evangelion: 3.0 You Can (Not) Redo" scored 0.53',
            media_type=MediaType.MOVIE,
            media_id=75624,
            media_name="Evangelion: 3.0 You Can (Not) Redo",
        )
        state = ScanState(
            folder=self.tmp,
            source_file=movie_file,
            media_info={"id": 75624, "title": "Evangelion: 3.0 You Can (Not) Redo", "year": "2012"},
            preview_items=[preview],
            confidence=0.53,
            scanned=True,
            checked=False,
        )
        self.set_movie_session([state], preview_items=[preview])

        self.ctrl.approve_match(state)

        self.assertEqual(state.match_origin, "manual")
        self.assertEqual(state.preview_items[0].status, "OK")
        self.assertEqual(self.ctrl.movie_preview_items[0].status, "OK")
        self.assertFalse(state.checked)
        self.assertEqual(state.confidence, 1.0)


class MovieBatchCancellationTests(_ControllerTestCase):

    def test_cancel_movie_batch_sets_cancelled_progress(self):
        root = self.tmp / "movies"
        root.mkdir()

        with patch(
            "plex_renamer.app.controllers.media_controller.MovieScanner",
            _SlowMovieBatchScanner,
        ):
            self.ctrl.start_movie_batch(root, _FakeTMDB())

            _wait_until(
                lambda: self.ctrl.scan_progress.lifecycle == ScanLifecycle.SCANNING,
                description="movie batch scan to enter SCANNING",
            )

            self.assertTrue(self.ctrl.cancel_scan())

            _wait_until(
                lambda: self.ctrl.scan_progress.lifecycle == ScanLifecycle.CANCELLED,
                description="movie batch scan cancellation",
            )

        self.assertEqual(self.ctrl.scan_progress.lifecycle, ScanLifecycle.CANCELLED)
        self.assertEqual(self.ctrl.movie_library_states, [])


class SessionSaveRestoreTests(_ControllerTestCase):

    def test_save_restore_tv_from_tab_switch(self):
        state = ScanState(
            folder=self.tmp / "Show",
            media_info={"id": 1, "name": "Show"},
        )
        self.set_tv_session(
            [state],
            active_scan=state,
            tv_root_folder=self.tmp / "tv",
            selected_index=0,
        )

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
        self.set_movie_session(
            [state],
            preview_items=[item],
            movie_folder=self.tmp,
        )

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


class SyncQueuedStatesTests(_ControllerTestCase):

    def test_sync_marks_queued_tv_states(self):
        state = ScanState(
            folder=self.tmp / "Show",
            media_info={"id": 100, "name": "Show"},
        )
        self.set_tv_session([state], batch_mode=False)

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
        self.set_tv_session([state], batch_mode=False)

        self.ctrl.sync_queued_states()
        self.assertFalse(state.queued)


class CompletedJobStateProjectionTests(_ControllerTestCase):

    def test_apply_completed_tv_job_updates_state_to_plex_ready(self):
        state = ScanState(
            folder=self.tmp / "Example.Show.2024",
            media_info={"id": 101, "name": "Example Show", "year": "2024"},
            preview_items=[
                PreviewItem(
                    original=self.tmp / "Example.Show.2024" / "Season 01" / "Example.Show.S01E01.mkv",
                    new_name="Example Show (2024) - S01E01 - Pilot.mkv",
                    target_dir=self.tmp / "Example Show (2024)" / "Season 01",
                    season=1,
                    episodes=[1],
                    status="OK",
                )
            ],
            scanned=True,
            checked=True,
            confidence=1.0,
        )
        self.set_tv_session([state], batch_mode=False, tv_root_folder=self.tmp)

        job = RenameJob(
            library_root=str(self.tmp),
            source_folder="Example.Show.2024",
            media_type=MediaType.TV,
            tmdb_id=101,
            media_name="Example Show (2024)",
            show_folder_rename="Example Show (2024)",
            rename_ops=[
                RenameOp(
                    original_relative="Example.Show.2024/Season 01/Example.Show.S01E01.mkv",
                    new_name="Example Show (2024) - S01E01 - Pilot.mkv",
                    target_dir_relative="Example.Show.2024/Season 01",
                    status="OK",
                    season=1,
                    episodes=[1],
                    selected=True,
                )
            ],
        )

        changed = self.ctrl.apply_completed_job_to_state(job, RenameResult(renamed_count=1))

        self.assertTrue(changed)
        self.assertEqual(state.folder, self.tmp / "Example Show (2024)")
        self.assertEqual(state.relative_folder, "Example Show (2024)")
        self.assertEqual(state.preview_items[0].original, self.tmp / "Example Show (2024)" / "Season 01" / "Example Show (2024) - S01E01 - Pilot.mkv")
        self.assertFalse(state.preview_items[0].is_actionable)
        self.assertTrue(self.ctrl.command_gating.is_plex_ready_state(state))

    def test_sync_marks_duplicates_as_not_queued(self):
        state = ScanState(
            folder=self.tmp / "Dup",
            media_info={"id": 100, "name": "Dup"},
            duplicate_of="Primary Show",
        )
        self.set_tv_session([state], batch_mode=False)

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
        self.set_movie_session([state])

        job = RenameJob(
            library_root=str(self.tmp),
            source_folder="DupMovie",
            media_type=MediaType.MOVIE,
            tmdb_id=100,
        )
        self.store.add_job(job)

        self.ctrl.sync_queued_states()
        self.assertFalse(state.queued)

    def test_sync_clears_completed_tv_states_from_queued(self):
        state = ScanState(
            folder=self.tmp / "DoneShow",
            media_info={"id": 444, "name": "Done Show"},
        )
        self.set_tv_session([state], batch_mode=False)

        job = RenameJob(
            library_root=str(self.tmp),
            source_folder="DoneShow",
            media_type=MediaType.TV,
            tmdb_id=444,
            status=JobStatus.COMPLETED,
        )
        self.store.add_job(job)

        self.ctrl.sync_queued_states()
        self.assertFalse(state.queued)


class ListenerTests(_ControllerTestCase):

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
