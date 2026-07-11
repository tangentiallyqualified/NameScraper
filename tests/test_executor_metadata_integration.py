"""End-to-end executor integration: decorate after rename, revert
round-trip, remux --title threading."""

from pathlib import Path

import plex_renamer._job_execution_remux as remux_mod
from plex_renamer.constants import JobKind, JobStatus, MediaType
from plex_renamer.job_store import JobStore, RenameJob, RenameOp
from plex_renamer.job_executor import QueueExecutor, revert_job


def _tree_snapshot(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*")}


def make_env(tmp_path):
    src = tmp_path / "src" / "Show"
    src.mkdir(parents=True)
    (src / "Show.S01E01.mkv").write_bytes(b"video")
    out = tmp_path / "out"
    out.mkdir()
    return tmp_path / "src", out


def make_job(library_root, out, plan) -> RenameJob:
    return RenameJob(
        media_type=MediaType.TV, tmdb_id=42, media_name="Show",
        library_root=str(library_root), output_root=str(out),
        source_folder="Show", show_folder_rename="Show (2019)",
        rename_ops=[RenameOp(
            original_relative="Show/Show.S01E01.mkv",
            new_name="Show (2019) - S01E01 - Pilot.mkv",
            target_dir_relative="Show (2019)/Season 01",
            status="OK", season=1, episodes=[1])],
        metadata_plan=plan,
    )


PLAN = {
    "nfo_files": [{"target_relative": "Show (2019)/tvshow.nfo",
                   "content": "<tvshow/>", "slot": "nfo:show"}],
    "artwork": [{"tmdb_path": "/p.jpg",
                 "target_relative": "Show (2019)/poster.jpg",
                 "kind": "poster", "slot": "poster", "plex_extra": False}],
    "embed_title": False, "prefer_local": False, "plex_naming": False,
    "mkvpropedit_path": "",
}


def test_execute_decorates_and_revert_restores_pristine_tree(tmp_path):
    library_root, out = make_env(tmp_path)
    before = _tree_snapshot(out)

    store = JobStore(db_path=tmp_path / "jobs.db")
    job = store.add_job(make_job(library_root, out, dict(PLAN)))
    executor = QueueExecutor(store, image_fetcher=lambda p: b"img")
    assert executor.execute_single_job(job.job_id)

    done = store.get_job(job.job_id)
    assert done.status == JobStatus.COMPLETED
    assert (out / "Show (2019)" / "tvshow.nfo").exists()
    assert (out / "Show (2019)" / "poster.jpg").read_bytes() == b"img"
    assert set(done.undo_data["created_files"]) == {
        str(out / "Show (2019)" / "tvshow.nfo"),
        str(out / "Show (2019)" / "poster.jpg"),
    }

    ok, errors = revert_job(done)
    assert ok, errors
    assert _tree_snapshot(out) == before
    assert (library_root / "Show" / "Show.S01E01.mkv").exists()


def test_offline_artwork_completes_with_warning(tmp_path):
    library_root, out = make_env(tmp_path)
    store = JobStore(db_path=tmp_path / "jobs.db")
    job = store.add_job(make_job(library_root, out, dict(PLAN)))
    executor = QueueExecutor(store, image_fetcher=None)
    executor.execute_single_job(job.job_id)

    done = store.get_job(job.job_id)
    assert done.status == JobStatus.COMPLETED
    assert "poster.jpg" in (done.error_message or "")
    assert (out / "Show (2019)" / "tvshow.nfo").exists()


def test_remux_op_receives_title(tmp_path, monkeypatch):
    library_root, out = make_env(tmp_path)
    captured = {}

    def fake_run(args, on_percent=None):
        captured["args"] = args
        Path(args[args.index("--output") + 1]).write_bytes(b"muxed")
        return 0, ""

    monkeypatch.setattr(remux_mod, "run_mkvmerge", fake_run)

    mkvmerge = tmp_path / "mkvmerge.exe"
    mkvmerge.write_bytes(b"")
    plan = {"nfo_files": [], "artwork": [], "embed_title": True,
            "prefer_local": False, "plex_naming": False,
            "mkvpropedit_path": ""}
    job = make_job(library_root, out, plan)
    job.job_kind = JobKind.REMUX
    job.rename_ops[0].mux = {
        "mkvmerge_path": str(mkvmerge), "track_decisions": [],
        "subtitle_merges": [], "strip_track_names": False,
        "no_fear": False, "output_name": job.rename_ops[0].new_name,
    }

    store = JobStore(db_path=tmp_path / "jobs.db")
    job = store.add_job(job)
    executor = QueueExecutor(store)
    executor.execute_single_job(job.job_id)

    args = captured["args"]
    assert args[args.index("--title") + 1] == "Show (2019) - S01E01 - Pilot"
