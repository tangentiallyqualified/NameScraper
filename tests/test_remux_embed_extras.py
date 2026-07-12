"""Mux-time embedding: tags/cover flags through execute_remux_op and
temp-file materialization in _execute_remux."""

from pathlib import Path

import plex_renamer.job_executor as job_executor
from plex_renamer._job_execution_remux import execute_remux_op
from plex_renamer.constants import MediaType
from plex_renamer.engine.models import RenameResult
from plex_renamer.job_store import RenameJob, RenameOp


def _result() -> RenameResult:
    result = RenameResult()
    result.log_entry = {}
    return result


def _mux_plan(tmp_path) -> dict:
    fake_mkvmerge = tmp_path / "mkvmerge.exe"
    fake_mkvmerge.write_bytes(b"")
    return {
        "mkvmerge_path": str(fake_mkvmerge),
        "track_decisions": [], "subtitle_merges": [],
        "strip_track_names": False, "no_fear": False,
        "output_name": "Show (2019) - S01E01 - Pilot.mkv",
    }


def _op(tmp_path) -> RenameOp:
    src_dir = tmp_path / "src" / "Show"
    src_dir.mkdir(parents=True, exist_ok=True)
    (src_dir / "a.mkv").write_bytes(b"mkv")
    return RenameOp(
        original_relative="Show/a.mkv",
        new_name="Show (2019) - S01E01 - Pilot.mkv",
        target_dir_relative="Show (2019)/Season 01",
        status="OK", season=1, episodes=[1],
        mux=_mux_plan(tmp_path))


def _touch_output_runner(record):
    def runner(args, on_percent=None):
        record.append(list(args))
        Path(args[args.index("--output") + 1]).write_bytes(b"out")
        return 0, ""
    return runner


def test_execute_remux_op_passes_embed_flags(tmp_path):
    op = _op(tmp_path)
    calls = []
    result = _result()
    ok = execute_remux_op(
        op,
        source_root=tmp_path / "src",
        output_root=tmp_path / "out",
        result=result,
        runner=_touch_output_runner(calls),
        title="T",
        tags_path=tmp_path / "tags.xml",
        cover_path=tmp_path / "c.jpg",
    )
    assert ok
    args = calls[0]
    assert args[args.index("--global-tags") + 1] == str(tmp_path / "tags.xml")
    assert args[args.index("--attach-file") + 1] == str(tmp_path / "c.jpg")


def test_execute_remux_op_no_flags_by_default(tmp_path):
    op = _op(tmp_path)
    calls = []
    ok = execute_remux_op(
        op,
        source_root=tmp_path / "src",
        output_root=tmp_path / "out",
        result=_result(),
        runner=_touch_output_runner(calls),
    )
    assert ok
    assert "--global-tags" not in calls[0]
    assert "--attach-file" not in calls[0]


def _remux_job(tmp_path, plan_extras) -> RenameJob:
    (tmp_path / "out").mkdir(exist_ok=True)
    return RenameJob(
        media_type=MediaType.TV, tmdb_id=42, media_name="Show",
        library_root=str(tmp_path / "src"),
        output_root=str(tmp_path / "out"),
        source_folder="Show", job_kind="remux",
        rename_ops=[_op(tmp_path)],
        metadata_plan={
            "nfo_files": [], "artwork": [], "embed_title": True,
            "prefer_local": False, "plex_naming": False,
            "mkvpropedit_path": "", "embed_extras": plan_extras,
        },
    )


def test_execute_remux_materializes_and_cleans_temp_files(tmp_path, monkeypatch):
    job = _remux_job(tmp_path, [{
        "op": "Show/a.mkv", "tags_xml": "<Tags/>",
        "cover_tmdb_path": "/p.jpg"}])
    seen = {}

    def fake_remux_op(op, **kwargs):
        seen["tags_path"] = kwargs.get("tags_path")
        seen["cover_path"] = kwargs.get("cover_path")
        seen["tags_exists"] = (kwargs.get("tags_path") is not None
                               and kwargs["tags_path"].exists())
        seen["cover_exists"] = (kwargs.get("cover_path") is not None
                                and kwargs["cover_path"].exists())
        seen["title"] = kwargs.get("title")
        return True

    monkeypatch.setattr(job_executor, "execute_remux_op", fake_remux_op)
    job_executor._execute_remux(
        job, fetch_image_bytes=lambda p: b"jpgbytes")

    assert seen["title"] == "Show (2019) - S01E01 - Pilot"
    assert seen["tags_exists"] is True
    assert seen["cover_exists"] is True
    assert not seen["tags_path"].exists()     # cleaned after the op
    assert not seen["cover_path"].exists()


def test_execute_remux_cover_fetch_failure_warns(tmp_path, monkeypatch):
    job = _remux_job(tmp_path, [{
        "op": "Show/a.mkv", "tags_xml": None,
        "cover_tmdb_path": "/p.jpg"}])
    seen = {}

    def fake_remux_op(op, **kwargs):
        seen["cover_path"] = kwargs.get("cover_path")
        return True

    monkeypatch.setattr(job_executor, "execute_remux_op", fake_remux_op)
    result = job_executor._execute_remux(job, fetch_image_bytes=lambda p: None)

    assert seen["cover_path"] is None
    assert any("Cover art unavailable" in e for e in result.errors)
