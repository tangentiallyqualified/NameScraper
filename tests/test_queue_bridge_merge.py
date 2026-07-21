"""A part group queues as exactly one REMUX op carrying append sources."""

from __future__ import annotations

from pathlib import Path

from plex_renamer.constants import JobKind
from plex_renamer.engine._queue_bridge import build_rename_job_from_items
from plex_renamer.engine.models import PreviewItem


def test_group_row_yields_single_remux_op(tmp_path: Path) -> None:
    parts = [tmp_path / f"Show S01E05 ({i}).mkv" for i in (1, 2, 3)]
    for part in parts:
        part.write_bytes(b"0")
    item = PreviewItem(
        original=parts[0],
        new_name="Show - S01E05 - Five.mkv",
        target_dir=tmp_path / "Show" / "Season 01",
        season=1,
        episodes=[5],
        status="OK",
        merge_part_paths=list(parts),
        merge_part_file_ids=[0, 1, 2],
    )
    plan = {
        "output_name": "Show - S01E05 - Five.mkv",
        "track_decisions": [],
        "subtitle_merges": [],
        "append_sources": ["Show S01E05 (2).mkv", "Show S01E05 (3).mkv"],
        "strip_track_names": False,
        "no_fear": False,
        "mkvmerge_path": "",
        "warnings": [],
        "container_conversion": False,
        "user_modified": False,
    }
    job = build_rename_job_from_items(
        items=[item],
        checked_indices={0},
        media_type="tv",
        tmdb_id=1,
        media_name="Show",
        library_root=tmp_path,
        output_root=tmp_path / "lib",
        source_folder=tmp_path,
        mux_plans={0: plan},
    )
    video_ops = [op for op in job.rename_ops if op.file_type == "video"]
    assert len(video_ops) == 1
    assert job.job_kind == JobKind.REMUX
    assert video_ops[0].mux is not None
    assert video_ops[0].mux["append_sources"] == [
        "Show S01E05 (2).mkv",
        "Show S01E05 (3).mkv",
    ]
    assert video_ops[0].original_relative == "Show S01E05 (1).mkv"
