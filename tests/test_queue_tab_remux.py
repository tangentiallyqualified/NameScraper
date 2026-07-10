"""Queue-tab remux presentation: progress text/bar and irreversible
history handling."""
from __future__ import annotations

from conftest_qt import QtSmokeBase


def _job(*, kind=None, status=None, undo=None, mux=None):
    from plex_renamer.constants import JobKind, JobStatus
    from plex_renamer.job_store import RenameJob, RenameOp

    return RenameJob(
        media_type="tv", tmdb_id=3, media_name="Show",
        library_root="C:/lib", output_root="C:/out", source_folder="Show",
        job_kind=kind or JobKind.REMUX,
        status=status or JobStatus.RUNNING,
        undo_data=undo,
        rename_ops=[RenameOp(
            original_relative="Show/a.mkv", new_name="X.mkv",
            target_dir_relative="Show (2020)", status="OK", mux=mux)],
    )


class JobTableProgressTests(QtSmokeBase):
    def test_running_row_shows_progress_text(self):
        from plex_renamer.gui_qt.models.job_table_model import JobTableModel

        model = JobTableModel()
        job = _job()
        model.set_jobs([job])
        model.set_progress(job.job_id, 1, 3, 42)
        text = model.index(0, 1).data()
        self.assertEqual(text, "Running · file 2/3 · 42%")

    def test_progress_pruned_when_job_not_running(self):
        from plex_renamer.constants import JobStatus
        from plex_renamer.gui_qt.models.job_table_model import JobTableModel

        model = JobTableModel()
        job = _job()
        model.set_jobs([job])
        model.set_progress(job.job_id, 0, 1, 50)
        job.status = JobStatus.COMPLETED
        model.set_jobs([job])
        self.assertEqual(model.index(0, 1).data(), "Completed")

    def test_irreversible_history_job_not_checkable(self):
        from plex_renamer.constants import JobStatus
        from plex_renamer.gui_qt.models.job_table_model import JobTableModel

        model = JobTableModel(history=True)
        revertible = _job(status=JobStatus.COMPLETED,
                          undo={"renames": [], "remux_outputs": ["x"]})
        no_fear = _job(status=JobStatus.COMPLETED,
                       undo={"renames": [], "irreversible": True})
        self.assertTrue(model.is_checkable_job(revertible))
        self.assertFalse(model.is_checkable_job(no_fear))


class JobDetailProgressTests(QtSmokeBase):
    def test_progress_bar_shows_for_current_job(self):
        from plex_renamer.gui_qt.widgets.job_detail_panel import JobDetailPanel

        panel = JobDetailPanel()
        job = _job()
        panel.set_job(job)
        self.assertTrue(panel._progress_bar.isHidden())
        panel.set_progress(job.job_id, 0, 4, 25)
        self.assertFalse(panel._progress_bar.isHidden())
        self.assertEqual(panel._progress_bar.value(), 25)
        panel.set_progress("someone-else", 0, 4, 99)   # ignored
        self.assertEqual(panel._progress_bar.value(), 25)
        panel.clear()
        self.assertTrue(panel._progress_bar.isHidden())

    def test_irreversible_note_visible(self):
        from plex_renamer.constants import JobStatus
        from plex_renamer.gui_qt.widgets.job_detail_panel import JobDetailPanel

        panel = JobDetailPanel()
        panel.set_job(_job(status=JobStatus.COMPLETED,
                           undo={"renames": [], "irreversible": True}))
        self.assertFalse(panel._irreversible_note.isHidden())
        panel.set_job(_job())
        self.assertTrue(panel._irreversible_note.isHidden())
