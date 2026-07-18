"""End-to-end against a real mkvmerge binary.

Skipped when mkvmerge is not installed (same spirit as the P: drive
harness rule).  A subtitle-only MKV is a valid Matroska file, so the
whole probe → plan → command → execute chain runs without any media
fixtures.
"""

import subprocess

import pytest

from plex_renamer import _job_execution_remux as rex
from plex_renamer._mkv_locate import find_mkvmerge
from plex_renamer._mkv_probe import clear_probe_cache, probe_file
from plex_renamer.engine._mux_planner import MuxSettings, build_mux_plan
from plex_renamer.engine.models import RenameResult
from plex_renamer.job_store import RenameOp

MKVMERGE = find_mkvmerge("")

pytestmark = pytest.mark.skipif(MKVMERGE is None, reason="mkvmerge not installed")

SRT = "1\n00:00:01,000 --> 00:00:02,000\nhello\n"


def _make_source_mkv(tmp_path):
    """Build a real MKV (subtitle-only) using mkvmerge itself."""
    seed = tmp_path / "seed.eng.srt"
    seed.write_text(SRT, encoding="utf-8")
    source = tmp_path / "lib" / "Show" / "a.mkv"
    source.parent.mkdir(parents=True)
    subprocess.run(
        [str(MKVMERGE), "--output", str(source), "--language", "0:eng", str(seed)],
        check=True,
        capture_output=True,
    )
    return source


def test_probe_plan_execute_round_trip(tmp_path):
    clear_probe_cache()
    source = _make_source_mkv(tmp_path)
    lib = tmp_path / "lib"
    out = tmp_path / "out"
    out.mkdir()
    extra = lib / "Show" / "a.jpn.srt"
    extra.write_text(SRT, encoding="utf-8")

    probe = probe_file(MKVMERGE, source)
    assert probe.ok
    assert probe.subtitle_tracks[0].language == "eng"

    plan = build_mux_plan(
        probe=probe,
        companion_subs=[("Show/a.jpn.srt", ".jpn")],
        settings=MuxSettings(merge_subs=True, merge_sub_languages=["jpn"]),
        new_name="Show - S01E01 - Pilot.mkv",
        mkvmerge_path=str(MKVMERGE),
    )
    assert plan is not None

    op = RenameOp(
        original_relative="Show/a.mkv",
        new_name=plan.output_name,
        target_dir_relative="Show (2020)/Season 01",
        status="OK",
        mux=plan.to_dict(),
    )
    result = RenameResult()
    result.log_entry = {"renames": [], "remux_outputs": []}
    assert rex.execute_remux_op(op, source_root=lib, output_root=out, result=result), result.errors

    final = out / "Show (2020)" / "Season 01" / "Show - S01E01 - Pilot.mkv"
    assert final.exists()
    clear_probe_cache()
    merged = probe_file(MKVMERGE, final)
    langs = sorted(t.language for t in merged.subtitle_tracks)
    assert langs == ["eng", "jpn"]
