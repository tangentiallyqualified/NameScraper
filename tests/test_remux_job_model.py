"""REMUX job kind, op payload round-trip, recovery, cross-kind dedup."""
import pytest

from plex_renamer.constants import JobKind, JobStatus
from plex_renamer.job_store import (
    DuplicateJobError,
    JobStore,
    RenameJob,
    RenameOp,
)

MUX = {"output_name": "X.mkv", "track_decisions": [], "subtitle_merges": [],
       "strip_track_names": False, "no_fear": False, "mkvmerge_path": "",
       "warnings": [], "user_modified": False}


def _store(tmp_path):
    return JobStore(db_path=tmp_path / "jobs.db")


def _job(kind=JobKind.REMUX, tmdb_id=42, mux=MUX):
    return RenameJob(
        media_type="tv", tmdb_id=tmdb_id, media_name="Show",
        library_root="C:/lib", output_root="C:/out", source_folder="Show",
        job_kind=kind,
        rename_ops=[RenameOp(
            original_relative="Show/a.mkv", new_name="X.mkv",
            target_dir_relative="Show (2020)/Season 01", status="OK",
            mux=mux)],
    )


def test_mux_payload_round_trips(tmp_path):
    store = _store(tmp_path)
    job = store.add_job(_job())
    loaded = store.get_job(job.job_id)
    assert loaded.job_kind == JobKind.REMUX
    assert loaded.rename_ops[0].mux == MUX
    assert loaded.mux_ops == [loaded.rename_ops[0]]


def test_legacy_op_dict_defaults_mux_none():
    op = RenameOp.from_dict({
        "original_relative": "a.mkv", "new_name": "b.mkv",
        "target_dir_relative": ".", "status": "OK",
        "season": None, "episodes": [], "selected": True,
        "file_type": "video"})
    assert op.mux is None


def test_rename_and_remux_jobs_cannot_coexist(tmp_path):
    store = _store(tmp_path)
    store.add_job(_job(kind=JobKind.RENAME, mux=None))
    with pytest.raises(DuplicateJobError):
        store.add_job(_job(kind=JobKind.REMUX))


def test_recover_interrupted_marks_failed_and_sweeps_temp(tmp_path):
    store = _store(tmp_path)
    job = store.add_job(_job())
    store.update_status(job.job_id, JobStatus.RUNNING)
    temp = tmp_path / "X.mkv.tmp-abc123.mkv"
    temp.write_bytes(b"partial")
    store.set_active_temp(job.job_id, str(temp))
    store.close()

    reopened = JobStore(db_path=tmp_path / "jobs.db")  # recovery runs in init
    loaded = reopened.get_job(job.job_id)
    assert loaded.status == JobStatus.FAILED
    assert "Interrupted" in loaded.error_message
    assert not temp.exists()
