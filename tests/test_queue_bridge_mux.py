"""Mux plans flow from preview items into REMUX job ops."""
from pathlib import Path

from plex_renamer.constants import JobKind
from plex_renamer.engine import build_rename_job_from_items
from plex_renamer.engine.models import CompanionFile, PreviewItem


def _item(tmp_path, *, companions=()):
    return PreviewItem(
        original=tmp_path / "lib" / "Show" / "a.mkv",
        new_name="Show - S01E01 - Pilot.mkv",
        target_dir=tmp_path / "out" / "Show (2020)" / "Season 01",
        season=1,
        episodes=[1],
        status="OK",
        media_type="tv",
        companions=list(companions),
    )


def _companion(tmp_path, filename, new_name):
    return CompanionFile(
        original=tmp_path / "lib" / "Show" / filename,
        new_name=new_name,
        file_type="subtitle",
    )


def _build(tmp_path, items, mux_plans):
    return build_rename_job_from_items(
        items=items,
        checked_indices={0},
        media_type="tv",
        tmdb_id=7,
        media_name="Show",
        library_root=tmp_path / "lib",
        output_root=tmp_path / "out",
        source_folder=tmp_path / "lib" / "Show",
        mux_plans=mux_plans,
    )


def test_no_plans_yields_rename_job(tmp_path):
    job = _build(tmp_path, [_item(tmp_path)], mux_plans=None)
    assert job.job_kind == JobKind.RENAME
    assert job.rename_ops[0].mux is None


def test_plan_attaches_to_video_op_and_forces_mkv_name(tmp_path):
    plan = {"output_name": "Show - S01E01 - Pilot.mkv",
            "track_decisions": [], "subtitle_merges": [],
            "strip_track_names": False, "no_fear": False,
            "mkvmerge_path": "", "warnings": [], "user_modified": False}
    job = _build(tmp_path, [_item(tmp_path)], mux_plans={0: plan})
    assert job.job_kind == JobKind.REMUX
    op = job.rename_ops[0]
    assert op.mux == plan
    assert op.new_name == "Show - S01E01 - Pilot.mkv"


def test_merged_companions_are_consumed_not_renamed(tmp_path):
    merged = _companion(tmp_path, "a.eng.srt", "Show - S01E01 - Pilot.eng.srt")
    kept = _companion(tmp_path, "a.spa.srt", "Show - S01E01 - Pilot.spa.srt")
    item = _item(tmp_path, companions=[merged, kept])
    plan = {"output_name": "Show - S01E01 - Pilot.mkv",
            "track_decisions": [],
            "subtitle_merges": [
                {"source_relative": "Show/a.eng.srt", "action": "merge",
                 "language": "eng", "set_default": False},
                {"source_relative": "Show/a.spa.srt", "action": "rename",
                 "language": "spa", "set_default": False}],
            "strip_track_names": False, "no_fear": False,
            "mkvmerge_path": "", "warnings": [], "user_modified": False}
    job = _build(tmp_path, [item], mux_plans={0: plan})
    originals = [op.original_relative for op in job.rename_ops]
    assert str(Path("Show/a.eng.srt")) not in originals
    assert str(Path("Show/a.spa.srt")) in originals
