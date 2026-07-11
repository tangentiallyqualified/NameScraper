"""mkvpropedit location + title-embedding argv builders."""

from pathlib import Path

from plex_renamer._mkv_command import (
    build_mkvmerge_args,
    build_mkvpropedit_title_args,
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


def test_build_mkvpropedit_title_args():
    args = build_mkvpropedit_title_args(
        "C:/tools/mkvpropedit.exe",
        Path("C:/out/Show (2019) - S01E01 - Pilot.mkv"),
        "Show (2019) - S01E01 - Pilot",
    )
    assert args[0] == "C:/tools/mkvpropedit.exe"
    assert args[2:] == [
        "--edit", "info", "--set", "title=Show (2019) - S01E01 - Pilot"]


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
