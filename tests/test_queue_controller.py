"""Tests for QueueController — UI-neutral job queue management."""
from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from plex_renamer.app.controllers.queue_controller import (
    BatchQueueResult,
    QueueController,
)
from plex_renamer.constants import JobStatus, MediaType
from plex_renamer.engine import PreviewItem, ScanState
from plex_renamer.job_store import JobStore, RenameJob, RenameOp, DuplicateJobError


class QueueControllerTests(unittest.TestCase):
    """QueueController with an in-memory job store."""

    def setUp(self):
        self._tmp = TemporaryDirectory(ignore_cleanup_errors=True)
        self.tmp = Path(self._tmp.name)
        db_path = self.tmp / "test_queue.db"
        self.store = JobStore(db_path=db_path)
        self.ctrl = QueueController(self.store)

    def tearDown(self):
        self.ctrl.close()
        self._tmp.cleanup()

    # ── add_single_job ────────────────────────────────────────────────

    def test_add_single_job_creates_pending_job(self):
        lib_root = self.tmp / "library"
        lib_root.mkdir()
        source = lib_root / "Show"
        source.mkdir()

        item = PreviewItem(
            original=source / "ep01.mkv",
            new_name="Show - S01E01.mkv",
            target_dir=source / "Season 01",
            season=1,
            episodes=[1],
            status="OK",
            media_type=MediaType.TV,
            media_id=100,
            media_name="Show",
        )

        job = self.ctrl.add_single_job(
            items=[item],
            checked_indices={0},
            media_type=MediaType.TV,
            tmdb_id=100,
            media_name="Show",
            library_root=lib_root,
            source_folder=source,
            show_folder_rename="Show (2020)",
        )

        self.assertEqual(job.status, JobStatus.PENDING)
        self.assertEqual(job.tmdb_id, 100)
        self.assertEqual(job.media_name, "Show")
        self.assertEqual(len(self.store.get_pending()), 1)

    def test_add_single_job_persists_poster_path(self):
        lib_root = self.tmp / "library"
        lib_root.mkdir()
        source = lib_root / "Show"
        source.mkdir()

        item = PreviewItem(
            original=source / "ep01.mkv",
            new_name="Show - S01E01.mkv",
            target_dir=source / "Season 01",
            season=1,
            episodes=[1],
            status="OK",
            media_type=MediaType.TV,
            media_id=100,
            media_name="Show",
        )

        job = self.ctrl.add_single_job(
            items=[item],
            checked_indices={0},
            media_type=MediaType.TV,
            tmdb_id=100,
            media_name="Show",
            library_root=lib_root,
            source_folder=source,
            poster_path="/poster.jpg",
        )

        stored = self.store.get_job(job.job_id)
        self.assertEqual(stored.poster_path, "/poster.jpg")

    def test_job_store_migrates_existing_db_to_add_poster_path(self):
        db_path = self.tmp / "legacy_jobs.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript(
            """
            CREATE TABLE schema_version (version INTEGER NOT NULL);
            INSERT INTO schema_version (version) VALUES (1);
            CREATE TABLE jobs (
                job_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                media_type TEXT NOT NULL,
                tmdb_id INTEGER NOT NULL,
                media_name TEXT NOT NULL,
                library_root TEXT NOT NULL,
                source_folder TEXT NOT NULL,
                show_folder_rename TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                error_message TEXT,
                position INTEGER NOT NULL DEFAULT 0,
                undo_data TEXT,
                job_kind TEXT NOT NULL DEFAULT 'rename',
                data_source TEXT NOT NULL DEFAULT 'tmdb',
                depends_on TEXT,
                rename_ops TEXT NOT NULL
            );
            """
        )
        conn.commit()
        conn.close()

        migrated = JobStore(db_path=db_path)
        try:
            row = migrated._get_conn().execute("PRAGMA table_info(jobs)").fetchall()
            columns = {entry[1] for entry in row}
            version = migrated._get_conn().execute("SELECT version FROM schema_version").fetchone()[0]
            self.assertIn("poster_path", columns)
            self.assertEqual(version, 2)
        finally:
            migrated.close()

    def test_add_single_job_duplicate_raises(self):
        lib_root = self.tmp / "library"
        lib_root.mkdir()
        source = lib_root / "Show"
        source.mkdir()

        item = PreviewItem(
            original=source / "ep01.mkv",
            new_name="Show - S01E01.mkv",
            target_dir=source / "Season 01",
            season=1,
            episodes=[1],
            status="OK",
            media_type=MediaType.TV,
            media_id=100,
            media_name="Show",
        )

        kwargs = dict(
            items=[item],
            checked_indices={0},
            media_type=MediaType.TV,
            tmdb_id=100,
            media_name="Show",
            library_root=lib_root,
            source_folder=source,
        )

        self.ctrl.add_single_job(**kwargs)
        with self.assertRaises(DuplicateJobError):
            self.ctrl.add_single_job(**kwargs)

    # ── Properties ────────────────────────────────────────────────────

    def test_pending_count_tracks_pending_jobs(self):
        self.assertEqual(self.ctrl.pending_count, 0)

        lib_root = self.tmp / "library"
        lib_root.mkdir()
        source = lib_root / "Show"
        source.mkdir()

        item = PreviewItem(
            original=source / "ep01.mkv",
            new_name="Show - S01E01.mkv",
            target_dir=source / "Season 01",
            season=1,
            episodes=[1],
            status="OK",
            media_type=MediaType.TV,
            media_id=200,
            media_name="Show2",
        )

        self.ctrl.add_single_job(
            items=[item],
            checked_indices={0},
            media_type=MediaType.TV,
            tmdb_id=200,
            media_name="Show2",
            library_root=lib_root,
            source_folder=source,
        )

        self.assertEqual(self.ctrl.pending_count, 1)

    # ── Revert ────────────────────────────────────────────────────────

    def test_revert_nonexistent_job_returns_failure(self):
        ok, errors = self.ctrl.revert_job("nonexistent-id")
        self.assertFalse(ok)
        self.assertTrue(any("not found" in e for e in errors))

    def test_revert_job_without_undo_data_returns_failure(self):
        job = RenameJob(
            library_root=str(self.tmp),
            source_folder="Show",
            undo_data=None,
        )
        self.store.add_job(job)

        ok, errors = self.ctrl.revert_job(job.job_id)
        self.assertFalse(ok)
        self.assertTrue(any("No undo data" in e for e in errors))

    def test_revert_job_with_undo_data_succeeds(self):
        lib_root = self.tmp / "library"
        lib_root.mkdir()
        renamed_dir = lib_root / "Show (2020)" / "Season 01"
        renamed_dir.mkdir(parents=True)
        renamed_file = renamed_dir / "Show - S01E01.mkv"
        renamed_file.write_text("video")

        original_file = lib_root / "Show" / "ep01.mkv"

        job = RenameJob(
            library_root=str(lib_root),
            source_folder="Show",
            status=JobStatus.COMPLETED,
            undo_data={
                "renames": [
                    {"old": str(original_file), "new": str(renamed_file)},
                ],
                "created_dirs": [str(renamed_dir)],
                "removed_dirs": [],
                "renamed_dirs": [],
            },
        )
        self.store.add_job(job)

        ok, errors = self.ctrl.revert_job(job.job_id)
        self.assertTrue(ok, errors)
        self.assertTrue(original_file.exists())

        updated = self.store.get_job(job.job_id)
        self.assertEqual(updated.status, JobStatus.REVERTED)

    def test_revert_job_with_undo_data_failure_sets_revert_failed(self):
        job = RenameJob(
            library_root=str(self.tmp),
            source_folder="Show",
            status=JobStatus.COMPLETED,
            undo_data={"renames": []},
        )
        self.store.add_job(job)

        with patch(
            "plex_renamer.app.controllers.queue_controller.revert_job",
            return_value=(False, ["could not move file back"]),
        ):
            ok, errors = self.ctrl.revert_job(job.job_id)

        self.assertFalse(ok)
        self.assertEqual(errors, ["could not move file back"])

        updated = self.store.get_job(job.job_id)
        self.assertEqual(updated.status, JobStatus.REVERT_FAILED)
        self.assertIn("could not move file back", updated.error_message or "")

    def test_history_includes_revert_failed_jobs(self):
        job = RenameJob(
            library_root=str(self.tmp),
            source_folder="Show",
            status=JobStatus.REVERT_FAILED,
            error_message="revert error",
        )
        self.store.add_job(job)

        history = self.ctrl.get_history()

        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].status, JobStatus.REVERT_FAILED)

    # ── Query ─────────────────────────────────────────────────────────

    def test_get_queue_returns_pending_jobs(self):
        job = RenameJob(
            library_root=str(self.tmp),
            source_folder="Show",
            status=JobStatus.PENDING,
        )
        self.store.add_job(job)

        queue = self.ctrl.get_queue()
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0].job_id, job.job_id)

    def test_get_history_returns_completed_jobs(self):
        job = RenameJob(
            library_root=str(self.tmp),
            source_folder="Show",
            status=JobStatus.PENDING,
        )
        self.store.add_job(job)
        self.store.update_status(job.job_id, JobStatus.COMPLETED)

        history = self.ctrl.get_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].status, JobStatus.COMPLETED)

    def test_count_by_status(self):
        for i in range(3):
            job = RenameJob(
                library_root=str(self.tmp),
                source_folder=f"Show{i}",
                tmdb_id=1000 + i,
                status=JobStatus.PENDING,
            )
            self.store.add_job(job)

        self.store.update_status(
            self.store.get_pending()[0].job_id, JobStatus.COMPLETED,
        )

        counts = self.ctrl.count_by_status()
        self.assertEqual(counts.get(JobStatus.PENDING, 0), 2)
        self.assertEqual(counts.get(JobStatus.COMPLETED, 0), 1)

    def test_set_job_poster_path_updates_existing_job(self):
        job = RenameJob(
            library_root=str(self.tmp),
            source_folder="Show",
            status=JobStatus.PENDING,
        )
        self.store.add_job(job)

        self.ctrl.set_job_poster_path(job.job_id, "/poster.jpg")

        updated = self.store.get_job(job.job_id)
        self.assertEqual(updated.poster_path, "/poster.jpg")

    def test_backfill_missing_job_poster_paths_uses_cached_metadata_only(self):
        movie_job = RenameJob(
            library_root=str(self.tmp),
            source_folder="Movie",
            media_type=MediaType.MOVIE,
            tmdb_id=101,
            media_name="Movie",
        )
        tv_job = RenameJob(
            library_root=str(self.tmp),
            source_folder="Show",
            media_type=MediaType.TV,
            tmdb_id=202,
            media_name="Show",
        )
        self.store.add_job(movie_job)
        self.store.add_job(tv_job)

        class _FakeTMDB:
            def __init__(self):
                self.cached_calls = []

            def get_cached_poster_path(self, tmdb_id, media_type="tv"):
                self.cached_calls.append((media_type, tmdb_id))
                if (media_type, tmdb_id) == (MediaType.MOVIE, 101):
                    return "/movie-poster.jpg"
                return None

        updated = self.ctrl.backfill_missing_job_poster_paths(_FakeTMDB())

        self.assertEqual(updated, 1)
        self.assertEqual(self.store.get_job(movie_job.job_id).poster_path, "/movie-poster.jpg")
        self.assertIsNone(self.store.get_job(tv_job.job_id).poster_path)

    # ── Listener ──────────────────────────────────────────────────────

    def test_add_listener_returns_id(self):
        lid = self.ctrl.add_listener(on_queue_finished=lambda: None)
        self.assertIsInstance(lid, int)


class MovieBatchCheckboxTests(unittest.TestCase):
    """Regression test: movie batch queueing must respect state.checked."""

    def setUp(self):
        self._tmp = TemporaryDirectory(ignore_cleanup_errors=True)
        self.tmp = Path(self._tmp.name)
        db_path = self.tmp / "test_queue.db"
        self.store = JobStore(db_path=db_path)
        self.ctrl = QueueController(self.store)

    def tearDown(self):
        self.ctrl.close()
        self._tmp.cleanup()

    def _make_movie_state(self, title, tmdb_id, checked=True):
        lib_root = self.tmp / "library"
        lib_root.mkdir(exist_ok=True)
        item = PreviewItem(
            original=lib_root / f"{title}.mkv",
            new_name=f"{title} (2021).mkv",
            target_dir=lib_root / f"{title} (2021)",
            season=None,
            episodes=[],
            status="OK",
            media_type=MediaType.MOVIE,
            media_id=tmdb_id,
            media_name=title,
        )
        state = ScanState(
            folder=lib_root,
            media_info={"id": tmdb_id, "title": title, "year": "2021"},
            preview_items=[item],
            confidence=1.0,
            scanned=True,
            checked=checked,
        )
        return state

    def test_unchecked_movies_are_not_queued(self):
        from plex_renamer.app.services.command_gating_service import CommandGatingService

        checked_state = self._make_movie_state("Dune", 100, checked=True)
        unchecked_state = self._make_movie_state("Tenet", 200, checked=False)

        lib_root = self.tmp / "library"
        result = self.ctrl.add_movie_batch(
            states=[checked_state, unchecked_state],
            library_root=lib_root,
            command_gating=CommandGatingService(),
        )

        self.assertEqual(result.added, 1)
        self.assertTrue(checked_state.queued)
        self.assertFalse(unchecked_state.queued)

    def test_all_checked_movies_are_queued(self):
        from plex_renamer.app.services.command_gating_service import CommandGatingService

        states = [
            self._make_movie_state("Dune", 300, checked=True),
            self._make_movie_state("Tenet", 400, checked=True),
        ]

        lib_root = self.tmp / "library"
        result = self.ctrl.add_movie_batch(
            states=states,
            library_root=lib_root,
            command_gating=CommandGatingService(),
        )

        self.assertEqual(result.added, 2)
        self.assertTrue(all(s.queued for s in states))

    def test_checked_movie_with_no_selected_files_is_not_queued(self):
        from plex_renamer.app.services.command_gating_service import CommandGatingService

        class _Binding:
            def __init__(self, value):
                self._value = value

            def get(self):
                return self._value

            def set(self, value):
                self._value = value

        state = self._make_movie_state("Dune", 301, checked=True)
        state.check_vars = {"0": _Binding(False)}

        lib_root = self.tmp / "library"
        result = self.ctrl.add_movie_batch(
            states=[state],
            library_root=lib_root,
            command_gating=CommandGatingService(),
        )

        self.assertEqual(result.added, 0)
        self.assertFalse(state.queued)
        self.assertTrue(result.blocked)

    def test_manual_approved_movie_job_snapshots_ok_status(self):
        from plex_renamer.app.services.command_gating_service import CommandGatingService

        lib_root = self.tmp / "library"
        lib_root.mkdir(exist_ok=True)
        movie_file = lib_root / "Evangelion.3.0.mkv"
        movie_file.write_text("video")

        item = PreviewItem(
            original=movie_file,
            new_name="Evangelion: 3.0 You Can (Not) Redo (2012).mkv",
            target_dir=lib_root / "Evangelion: 3.0 You Can (Not) Redo (2012)",
            season=None,
            episodes=[],
            status="OK",
            media_type=MediaType.MOVIE,
            media_id=75624,
            media_name="Evangelion: 3.0 You Can (Not) Redo",
        )
        state = ScanState(
            folder=lib_root,
            media_info={"id": 75624, "title": "Evangelion: 3.0 You Can (Not) Redo", "year": "2012"},
            preview_items=[item],
            confidence=1.0,
            match_origin="manual",
            scanned=True,
            checked=True,
        )

        result = self.ctrl.add_movie_batch(
            states=[state],
            library_root=lib_root,
            command_gating=CommandGatingService(),
        )

        self.assertEqual(result.added, 1)
        jobs = self.store.get_pending()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].rename_ops[0].status, "OK")

    def test_root_level_movie_job_does_not_request_library_root_rename(self):
        from plex_renamer.app.services.command_gating_service import CommandGatingService

        lib_root = self.tmp / "library"
        lib_root.mkdir()
        movie_file = lib_root / "Spaceballs.1987.2160p.mkv"
        movie_file.write_text("x")

        item = PreviewItem(
            original=movie_file,
            new_name="Spaceballs (1987).mkv",
            target_dir=lib_root / "Spaceballs (1987)",
            season=None,
            episodes=[],
            status="OK",
            media_type=MediaType.MOVIE,
            media_id=222,
            media_name="Spaceballs",
        )
        state = ScanState(
            folder=lib_root,
            media_info={"id": 222, "title": "Spaceballs", "year": "1987"},
            preview_items=[item],
            confidence=1.0,
            scanned=True,
            checked=True,
        )

        result = self.ctrl.add_movie_batch(
            states=[state],
            library_root=lib_root,
            command_gating=CommandGatingService(),
        )

        self.assertEqual(result.added, 1)
        jobs = self.store.get_pending()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].source_folder, ".")
        self.assertIsNone(jobs[0].show_folder_rename)
        self.assertEqual(jobs[0].rename_ops[0].target_dir_relative, "Spaceballs (1987)")


class BatchQueueResultTests(unittest.TestCase):
    def test_total_skipped(self):
        r = BatchQueueResult(skipped_duplicate=2, skipped_queued=3)
        self.assertEqual(r.total_skipped, 5)

    def test_defaults(self):
        r = BatchQueueResult()
        self.assertEqual(r.added, 0)
        self.assertEqual(r.total_skipped, 0)
        self.assertEqual(r.blocked, [])
        self.assertEqual(r.errors, [])


if __name__ == "__main__":
    unittest.main()
