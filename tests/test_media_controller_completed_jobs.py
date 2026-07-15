"""Completed-job state projection tests for MediaController."""

from plex_renamer.constants import JobStatus, MediaType
from plex_renamer.engine import PreviewItem, RenameResult, ScanState
from plex_renamer.job_store import RenameJob, RenameOp
from tests.test_media_controller import ControllerTestCase


class CompletedJobStateProjectionTests(ControllerTestCase):
    def test_apply_completed_tv_job_updates_state_to_plex_ready(self):
        state = ScanState(
            folder=self.tmp / "Example.Show.2024",
            media_info={"id": 101, "name": "Example Show", "year": "2024"},
            preview_items=[
                PreviewItem(
                    original=self.tmp
                    / "Example.Show.2024"
                    / "Season 01"
                    / "Example.Show.S01E01.mkv",
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

        changed = self.ctrl.apply_completed_job_to_state(  # pyright: ignore[reportUnknownMemberType]
            job, RenameResult(renamed_count=1)
        )

        self.assertTrue(changed)
        self.assertEqual(state.folder, self.tmp / "Example Show (2024)")
        self.assertEqual(state.relative_folder, "Example Show (2024)")
        self.assertEqual(
            state.preview_items[0].original,
            self.tmp
            / "Example Show (2024)"
            / "Season 01"
            / "Example Show (2024) - S01E01 - Pilot.mkv",
        )
        self.assertFalse(state.preview_items[0].is_actionable)
        self.assertTrue(self.ctrl.command_gating.is_fully_ready_state(state))

    def test_apply_completed_destination_tv_job_updates_state_to_output_root(self):
        source_root = self.tmp / "Incoming"
        output_root = self.tmp / "TV Output"
        source_root.mkdir()
        output_root.mkdir()
        state = ScanState(
            folder=source_root / "Example.Show.2024",
            relative_folder="Example.Show.2024",
            media_info={"id": 101, "name": "Example Show", "year": "2024"},
            preview_items=[
                PreviewItem(
                    original=source_root
                    / "Example.Show.2024"
                    / "Season 01"
                    / "Example.Show.S01E01.mkv",
                    new_name="Example Show (2024) - S01E01 - Pilot.mkv",
                    target_dir=output_root / "Example Show (2024)" / "Season 01",
                    season=1,
                    episodes=[1],
                    status="OK",
                )
            ],
            output_root=output_root,
            scanned=True,
            checked=True,
            confidence=1.0,
        )
        self.set_tv_session([state], batch_mode=False, tv_root_folder=source_root)

        job = RenameJob(
            library_root=str(source_root),
            output_root=str(output_root),
            source_folder="Example.Show.2024",
            media_type=MediaType.TV,
            tmdb_id=101,
            media_name="Example Show (2024)",
            rename_ops=[
                RenameOp(
                    original_relative="Example.Show.2024/Season 01/Example.Show.S01E01.mkv",
                    new_name="Example Show (2024) - S01E01 - Pilot.mkv",
                    target_dir_relative="Example Show (2024)/Season 01",
                    status="OK",
                    season=1,
                    episodes=[1],
                    selected=True,
                )
            ],
        )

        changed = self.ctrl.apply_completed_job_to_state(  # pyright: ignore[reportUnknownMemberType]
            job, RenameResult(renamed_count=1)
        )

        final_dir = output_root / "Example Show (2024)" / "Season 01"
        self.assertTrue(changed)
        self.assertEqual(state.folder, output_root / "Example Show (2024)")
        self.assertEqual(state.relative_folder, "Example Show (2024)")
        self.assertEqual(
            state.preview_items[0].original, final_dir / "Example Show (2024) - S01E01 - Pilot.mkv"
        )
        self.assertEqual(state.preview_items[0].target_dir, final_dir)
        self.assertEqual(state.season_folders[1], final_dir)
        self.assertFalse(state.preview_items[0].is_actionable)

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
