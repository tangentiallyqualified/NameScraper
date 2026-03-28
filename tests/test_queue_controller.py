"""Tests for QueueController — UI-neutral job queue management."""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

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

    # ── Listener ──────────────────────────────────────────────────────

    def test_add_listener_returns_id(self):
        lid = self.ctrl.add_listener(on_queue_finished=lambda: None)
        self.assertIsInstance(lid, int)


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
