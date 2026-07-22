"""QueueExecutor progress and lifecycle behavior."""

import logging
import threading
from pathlib import Path

import pytest

from plex_renamer import _job_execution_remux as rex
from plex_renamer.constants import JobKind, JobStatus
from plex_renamer.job_executor import QueueExecutor
from plex_renamer.job_store import JobStore, RenameJob, RenameOp

PLAN = {
    "output_name": "X.mkv",
    "track_decisions": [],
    "subtitle_merges": [],
    "strip_track_names": False,
    "no_fear": False,
    "mkvmerge_path": "mkvmerge",
    "warnings": [],
    "user_modified": False,
}


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
    job = store.add_job(
        RenameJob(
            media_type="tv",
            tmdb_id=1,
            media_name="Show",
            library_root=str(lib),
            output_root=str(out),
            source_folder="Show",
            job_kind=JobKind.REMUX,
            rename_ops=[
                RenameOp(
                    original_relative="Show/a.mkv",
                    new_name="X.mkv",
                    target_dir_relative="Show (2020)",
                    status="OK",
                    mux=plan,
                )
            ],
        )
    )

    executor = QueueExecutor(store)
    events = []
    executor.add_listener(on_progress=lambda j, i, n, pct: events.append((j.job_id, i, n, pct)))
    assert executor.execute_single_job(job.job_id)

    assert events == [(job.job_id, 0, 1, 50), (job.job_id, 0, 1, 100)]
    stored_job = store.get_job(job.job_id)
    assert stored_job is not None
    assert stored_job.status == JobStatus.COMPLETED
    assert (out / "Show (2020)" / "X.mkv").exists()


def test_queue_controller_forwards_progress_listener(tmp_path):
    from plex_renamer.app.controllers.queue_controller import QueueController

    store = JobStore(db_path=tmp_path / "ctrl_jobs.db")
    controller = QueueController(store)
    events = []
    controller.add_listener(on_job_progress=lambda job, i, n, pct: events.append((i, n, pct)))
    job = RenameJob(
        media_type="tv",
        tmdb_id=5,
        media_name="S",
        library_root="C:/lib",
        output_root="C:/out",
        source_folder="S",
    )
    controller.executor._notify("progress", job, 0, 2, 40)
    assert events == [(0, 2, 40)]
    controller.close()


def test_background_worker_finishes_empty_queue_and_isolates_listener_errors(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = JobStore(db_path=tmp_path / "worker_jobs.db")
    executor = QueueExecutor(store)
    finished = threading.Event()

    def fail_finished_listener() -> None:
        raise RuntimeError("listener failed")

    executor.add_listener(on_finished=fail_finished_listener)
    executor.add_listener(on_finished=finished.set)

    with caplog.at_level(logging.ERROR, logger="plex_renamer.job_executor"):
        executor.start()
        assert finished.wait(timeout=2.0)

    assert not executor.is_running
    assert "Listener callback error for finished" in caplog.text
    executor.stop()
    store.close()


def test_execute_single_job_rejects_unknown_job_id(tmp_path: Path) -> None:
    store = JobStore(db_path=tmp_path / "single_jobs.db")
    executor = QueueExecutor(store)

    assert executor.execute_single_job("missing") is False

    store.close()
