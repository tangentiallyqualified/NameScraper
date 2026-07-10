"""QueueExecutor emits per-op progress for REMUX jobs."""
from pathlib import Path

from plex_renamer import _job_execution_remux as rex
from plex_renamer.constants import JobKind, JobStatus
from plex_renamer.job_executor import QueueExecutor
from plex_renamer.job_store import JobStore, RenameJob, RenameOp

PLAN = {"output_name": "X.mkv", "track_decisions": [],
        "subtitle_merges": [], "strip_track_names": False, "no_fear": False,
        "mkvmerge_path": "mkvmerge", "warnings": [], "user_modified": False}


def test_progress_listener_fires(tmp_path, monkeypatch):
    lib = tmp_path / "lib"
    out = tmp_path / "out"
    (lib / "Show").mkdir(parents=True)
    out.mkdir()
    (lib / "Show" / "a.mkv").write_bytes(b"v")
    # A concrete (fake) binary path keeps the test independent of whether
    # mkvmerge is actually installed on this machine — the runner is faked.
    fake_mkvmerge = tmp_path / "mkvmerge.exe"
    fake_mkvmerge.write_bytes(b"")
    plan = dict(PLAN)
    plan["mkvmerge_path"] = str(fake_mkvmerge)

    def fake_runner(args, on_percent=None):
        output = Path(args[args.index("--output") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"muxed")
        if on_percent:
            on_percent(50)
            on_percent(100)
        return 0, ""

    monkeypatch.setattr(rex, "run_mkvmerge", fake_runner)

    store = JobStore(db_path=tmp_path / "jobs.db")
    job = store.add_job(RenameJob(
        media_type="tv", tmdb_id=1, media_name="Show",
        library_root=str(lib), output_root=str(out), source_folder="Show",
        job_kind=JobKind.REMUX,
        rename_ops=[RenameOp(
            original_relative="Show/a.mkv", new_name="X.mkv",
            target_dir_relative="Show (2020)", status="OK", mux=plan)],
    ))

    executor = QueueExecutor(store)
    events = []
    executor.add_listener(
        on_progress=lambda j, i, n, pct: events.append((j.job_id, i, n, pct)))
    assert executor.execute_single_job(job.job_id)

    assert events == [(job.job_id, 0, 1, 50), (job.job_id, 0, 1, 100)]
    assert store.get_job(job.job_id).status == JobStatus.COMPLETED
    assert (out / "Show (2020)" / "X.mkv").exists()
