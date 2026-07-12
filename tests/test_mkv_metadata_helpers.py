"""mkvpropedit location + title-embedding argv builders."""

from pathlib import Path

from plex_renamer._mkv_command import (
    build_mkvmerge_args,
    build_mkvpropedit_args,
)
from plex_renamer._mkv_locate import find_mkvpropedit
from plex_renamer.engine._mux_planner import MuxPlan


def test_find_mkvpropedit_prefers_sibling_of_mkvmerge(tmp_path):
    import plex_renamer._mkv_locate as locate

    exe = locate._EXE_NAME
    propedit_name = "mkvpropedit.exe" if exe.endswith(".exe") else "mkvpropedit"
    (tmp_path / exe).write_bytes(b"")
    (tmp_path / propedit_name).write_bytes(b"")
    found = find_mkvpropedit(str(tmp_path))
    assert found == tmp_path / propedit_name


def test_find_mkvpropedit_missing_sibling_returns_none(tmp_path, monkeypatch):
    import plex_renamer._mkv_locate as locate

    (tmp_path / locate._EXE_NAME).write_bytes(b"")
    monkeypatch.setattr(locate.shutil, "which", lambda name: None)
    monkeypatch.setattr(locate.os, "environ", {})
    assert find_mkvpropedit(str(tmp_path)) is None


def test_build_mkvpropedit_args_title_only():
    args = build_mkvpropedit_args(
        "C:/tools/mkvpropedit.exe",
        Path("C:/out/Show (2019) - S01E01 - Pilot.mkv"),
        title="Show (2019) - S01E01 - Pilot",
    )
    assert args[0] == "C:/tools/mkvpropedit.exe"
    assert args[2:] == [
        "--edit", "info", "--set", "title=Show (2019) - S01E01 - Pilot"]


def test_build_mkvpropedit_args_tags_and_cover():
    args = build_mkvpropedit_args(
        "mkvpropedit", Path("out.mkv"),
        title="T", tags_path="C:/tmp/tags.xml", cover_path="C:/tmp/c.jpg",
    )
    assert args[2:] == [
        "--edit", "info", "--set", "title=T",
        "--tags", "global:C:/tmp/tags.xml",
        "--attachment-name", "cover.jpg",
        "--attachment-mime-type", "image/jpeg",
        "--add-attachment", "C:/tmp/c.jpg",
    ]


def test_build_mkvpropedit_args_extras_without_title():
    args = build_mkvpropedit_args(
        "mkvpropedit", Path("out.mkv"), tags_path="tags.xml")
    assert "--edit" not in args
    assert args[2:] == ["--tags", "global:tags.xml"]


def _empty_plan() -> MuxPlan:
    return MuxPlan.from_dict({
        "mkvmerge_path": "mkvmerge",
        "track_decisions": [],
        "subtitle_merges": [],
        "strip_track_names": False,
        "no_fear": False,
        "output_name": "out.mkv",
    })


def test_build_mkvmerge_args_title_flag():
    args = build_mkvmerge_args(
        mkvmerge_path="mkvmerge",
        source=Path("in.mkv"),
        output=Path("out.mkv"),
        plan=_empty_plan(),
        resolve_sub=lambda rel: Path(rel),
        title="My Title",
    )
    idx = args.index("--title")
    assert args[idx + 1] == "My Title"
    assert idx > args.index("--output")


def test_build_mkvmerge_args_no_title_by_default():
    args = build_mkvmerge_args(
        mkvmerge_path="mkvmerge",
        source=Path("in.mkv"),
        output=Path("out.mkv"),
        plan=_empty_plan(),
        resolve_sub=lambda rel: Path(rel),
    )
    assert "--title" not in args


def test_build_mkvmerge_args_global_tags_and_cover():
    args = build_mkvmerge_args(
        mkvmerge_path="mkvmerge",
        source=Path("in.mkv"),
        output=Path("out.mkv"),
        plan=_empty_plan(),
        resolve_sub=lambda rel: Path(rel),
        title="My Title",
        global_tags_path="C:/tmp/tags.xml",
        cover_path="C:/tmp/c.jpg",
    )
    tags_idx = args.index("--global-tags")
    assert args[tags_idx + 1] == "C:/tmp/tags.xml"
    attach_idx = args.index("--attach-file")
    assert args[attach_idx + 1] == "C:/tmp/c.jpg"
    assert args[args.index("--attachment-name") + 1] == "cover.jpg"
    assert args[args.index("--attachment-mime-type") + 1] == "image/jpeg"
    # All embed flags come before the source input.
    assert max(tags_idx, attach_idx) < args.index("in.mkv")


def test_build_mkvmerge_args_no_embed_flags_by_default():
    args = build_mkvmerge_args(
        mkvmerge_path="mkvmerge",
        source=Path("in.mkv"),
        output=Path("out.mkv"),
        plan=_empty_plan(),
        resolve_sub=lambda rel: Path(rel),
    )
    assert "--global-tags" not in args
    assert "--attach-file" not in args
