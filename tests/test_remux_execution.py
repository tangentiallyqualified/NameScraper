"""Remux op execution: atomicity, No Fear, failure cleanup, progress."""

import sys
from pathlib import Path

from plex_renamer import _job_execution_remux as rex
from plex_renamer.engine.models import RenameResult
from plex_renamer.job_store import RenameOp

PLAN = {
    "output_name": "Show - S01E01 - Pilot.mkv",
    "track_decisions": [],
    "subtitle_merges": [
        {
            "source_relative": "Show/a.eng.srt",
            "action": "merge",
            "language": "eng",
            "set_default": False,
        }
    ],
    "strip_track_names": False,
    "no_fear": False,
    "mkvmerge_path": "mkvmerge",
    "warnings": [],
    "user_modified": False,
}


def _setup(tmp_path, *, no_fear=False):
    lib = tmp_path / "lib"
    out = tmp_path / "out"
    (lib / "Show").mkdir(parents=True)
    out.mkdir()
    (lib / "Show" / "a.mkv").write_bytes(b"video")
    (lib / "Show" / "a.eng.srt").write_text("1\n", encoding="utf-8")
    # A concrete (fake) binary path keeps the test independent of whether
    # mkvmerge is actually installed on this machine — the runner is faked.
    fake_mkvmerge = tmp_path / "mkvmerge.exe"
    fake_mkvmerge.write_bytes(b"")
    plan = dict(PLAN)
    plan["no_fear"] = no_fear
    plan["mkvmerge_path"] = str(fake_mkvmerge)
    op = RenameOp(
        original_relative="Show/a.mkv",
        new_name="Show - S01E01 - Pilot.mkv",
        target_dir_relative="Show (2020)/Season 01",
        status="OK",
        mux=plan,
    )
    return lib, out, op


def _ok_runner(args, on_percent=None):
    # Fake mkvmerge: writes the --output target, reports progress.
    output = Path(args[args.index("--output") + 1])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"muxed")
    if on_percent:
        on_percent(100)
    return 0, "ok"


def _fail_runner(args, on_percent=None):
    output = Path(args[args.index("--output") + 1])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"partial")
    return 2, "boom"


def test_success_writes_final_and_keeps_sources(tmp_path):
    lib, out, op = _setup(tmp_path)
    result = RenameResult()
    result.log_entry = {"renames": [], "remux_outputs": []}
    percents = []
    ok = rex.execute_remux_op(
        op,
        source_root=lib,
        output_root=out,
        result=result,
        on_percent=percents.append,
        runner=_ok_runner,
    )
    final = out / "Show (2020)" / "Season 01" / "Show - S01E01 - Pilot.mkv"
    assert ok and final.read_bytes() == b"muxed"
    assert (lib / "Show" / "a.mkv").exists()  # non-No-Fear keeps source
    assert (lib / "Show" / "a.eng.srt").exists()
    assert result.log_entry["remux_outputs"] == [str(final)]
    assert not result.log_entry.get("irreversible")
    assert percents == [100]
    assert not list(final.parent.glob("*.tmp-*"))  # temp gone


def test_no_fear_deletes_source_and_merged_subs(tmp_path):
    lib, out, op = _setup(tmp_path, no_fear=True)
    result = RenameResult()
    result.log_entry = {"renames": [], "remux_outputs": []}
    ok = rex.execute_remux_op(
        op, source_root=lib, output_root=out, result=result, runner=_ok_runner
    )
    assert ok
    assert not (lib / "Show" / "a.mkv").exists()
    assert not (lib / "Show" / "a.eng.srt").exists()
    assert result.log_entry["irreversible"] is True


def test_failure_removes_temp_and_keeps_source(tmp_path):
    lib, out, op = _setup(tmp_path, no_fear=True)
    result = RenameResult()
    result.log_entry = {"renames": [], "remux_outputs": []}
    ok = rex.execute_remux_op(
        op, source_root=lib, output_root=out, result=result, runner=_fail_runner
    )
    assert not ok
    assert result.errors
    assert (lib / "Show" / "a.mkv").exists()  # No Fear must NOT delete on failure
    season = out / "Show (2020)" / "Season 01"
    assert not season.exists() or not list(season.glob("*"))


def test_existing_target_is_an_error(tmp_path):
    lib, out, op = _setup(tmp_path)
    final = out / "Show (2020)" / "Season 01" / "Show - S01E01 - Pilot.mkv"
    final.parent.mkdir(parents=True)
    final.write_bytes(b"already here")
    result = RenameResult()
    result.log_entry = {"renames": [], "remux_outputs": []}
    ok = rex.execute_remux_op(
        op, source_root=lib, output_root=out, result=result, runner=_ok_runner
    )
    assert not ok
    assert final.read_bytes() == b"already here"


def test_run_mkvmerge_parses_progress():
    script = "import sys;print('Progress: 25%');print('Progress: 100%');print('done')"
    percents = []
    code, _tail = rex.run_mkvmerge([sys.executable, "-c", script], on_percent=percents.append)
    assert code == 0
    assert percents == [25, 100]
