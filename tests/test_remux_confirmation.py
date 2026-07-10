"""Confirmation copy for queues containing REMUX jobs (spec §7.5)."""
from plex_renamer.constants import JobKind, JobStatus
from plex_renamer.gui_qt.widgets._queue_tab_actions import (
    remux_confirmation_message,
)
from plex_renamer.job_store import RenameJob, RenameOp

MUX = {"output_name": "X.mkv", "track_decisions": [], "subtitle_merges": [],
       "strip_track_names": False, "no_fear": False, "mkvmerge_path": "",
       "warnings": [], "user_modified": False}


def _job(kind=JobKind.REMUX, *, no_fear=False):
    mux = dict(MUX)
    mux["no_fear"] = no_fear
    return RenameJob(
        media_type="tv", tmdb_id=1, media_name="Show",
        library_root="C:/lib", output_root="C:/out", source_folder="Show",
        job_kind=kind,
        rename_ops=[RenameOp(
            original_relative="Show/a.mkv", new_name="X.mkv",
            target_dir_relative="Show (2020)", status="OK",
            mux=mux if kind == JobKind.REMUX else None)],
    )


def test_no_remux_jobs_no_message():
    assert remux_confirmation_message([_job(JobKind.RENAME)]) == ""


def test_remux_message_mentions_output_and_duration():
    message = remux_confirmation_message([_job()])
    assert "remux" in message.lower()
    assert "output folder" in message.lower()
    assert "DELETED" not in message


def test_no_fear_escalates_copy():
    message = remux_confirmation_message([_job(no_fear=True)])
    assert "DELETED" in message


def test_non_pending_jobs_ignored():
    job = _job()
    job.status = JobStatus.COMPLETED
    assert remux_confirmation_message([job]) == ""
