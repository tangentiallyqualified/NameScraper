"""execute_remux_op with append sources: validation, argv, No Fear cleanup."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from plex_renamer._job_execution_remux import execute_remux_op
from plex_renamer.engine._mux_planner import MuxPlan, SubtitleMergeDecision
from plex_renamer.engine.models import RenameResult
from plex_renamer.job_store import RenameOp


def _op(plan: MuxPlan) -> RenameOp:
    return RenameOp(
        original_relative="p1.mkv",
        new_name="Show - S01E05.mkv",
        target_dir_relative="Show/Season 01",
        status="OK",
        season=1,
        episodes=[5],
        mux=plan.to_dict(),
    )


def _plan(*, no_fear: bool = False) -> MuxPlan:
    return MuxPlan(
        output_name="Show - S01E05.mkv",
        append_sources=["p2.mkv", "p3.mkv"],
        no_fear=no_fear,
        mkvmerge_path="mkvmerge",
    )


def _fake_runner(created: Path) -> Any:
    def runner(args: list[str], on_percent: Any = None) -> tuple[int, str]:
        created.parent.mkdir(parents=True, exist_ok=True)
        out = Path(args[args.index("--output") + 1])
        out.write_bytes(b"merged")
        return 0, ""

    return runner


def _setup(tmp_path: Path, *, parts: int = 3) -> tuple[Path, Path]:
    source_root = tmp_path / "in"
    output_root = tmp_path / "out"
    source_root.mkdir()
    for index in range(1, parts + 1):
        (source_root / f"p{index}.mkv").write_bytes(b"x")
    return source_root, output_root


def test_missing_append_source_fails_before_running(tmp_path: Path) -> None:
    source_root, output_root = _setup(tmp_path, parts=2)  # p3 missing
    result = RenameResult()
    ran: list[list[str]] = []
    ok = execute_remux_op(
        _op(_plan()),
        source_root=source_root,
        output_root=output_root,
        result=result,
        runner=lambda args, on_percent=None: ran.append(args) or (0, ""),
    )
    assert not ok
    assert ran == []
    assert any("p3.mkv" in e for e in result.errors)


def test_append_paths_reach_the_argv(tmp_path: Path) -> None:
    source_root, output_root = _setup(tmp_path)
    result = RenameResult()
    seen: list[list[str]] = []

    def runner(args: list[str], on_percent: Any = None) -> tuple[int, str]:
        seen.append(args)
        out = Path(args[args.index("--output") + 1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"m")
        return 0, ""

    ok = execute_remux_op(
        _op(_plan()),
        source_root=source_root,
        output_root=output_root,
        result=result,
        runner=runner,
    )
    assert ok, result.errors
    argv = seen[0]
    assert str(source_root / "p2.mkv") in argv and str(source_root / "p3.mkv") in argv
    assert argv.count("+") == 2


def test_no_fear_deletes_all_parts_after_success(tmp_path: Path) -> None:
    source_root, output_root = _setup(tmp_path)
    result = RenameResult()
    final = output_root / "Show/Season 01/Show - S01E05.mkv"
    ok = execute_remux_op(
        _op(_plan(no_fear=True)),
        source_root=source_root,
        output_root=output_root,
        result=result,
        runner=_fake_runner(final),
    )
    assert ok, result.errors
    assert final.exists()
    assert not any((source_root / f"p{i}.mkv").exists() for i in (1, 2, 3))


def test_without_no_fear_sources_survive(tmp_path: Path) -> None:
    source_root, output_root = _setup(tmp_path)
    result = RenameResult()
    final = output_root / "Show/Season 01/Show - S01E05.mkv"
    ok = execute_remux_op(
        _op(_plan(no_fear=False)),
        source_root=source_root,
        output_root=output_root,
        result=result,
        runner=_fake_runner(final),
    )
    assert ok, result.errors
    assert all((source_root / f"p{i}.mkv").exists() for i in (1, 2, 3))


def test_escaping_append_source_fails_before_running(tmp_path: Path) -> None:
    """I2: an absolute/escaping append_sources entry in the serialized plan
    must fail the boundary check before mkvmerge ever runs -- otherwise it
    would replace source_root under the pathlib join, get fed to mkvmerge,
    and (under No Fear) be deleted."""
    source_root, output_root = _setup(tmp_path, parts=1)
    outside = tmp_path / "outside" / "secret.mkv"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_bytes(b"x")
    plan = MuxPlan(
        output_name="Show - S01E05.mkv",
        append_sources=["../outside/secret.mkv"],
        mkvmerge_path="mkvmerge",
    )
    result = RenameResult()
    ran: list[list[str]] = []

    def runner(args: list[str], on_percent: Any = None) -> tuple[int, str]:
        ran.append(args)
        return 0, ""

    ok = execute_remux_op(
        _op(plan),
        source_root=source_root,
        output_root=output_root,
        result=result,
        runner=runner,
    )
    assert not ok
    assert ran == []
    assert any("escape their roots" in e for e in result.errors)
    assert outside.exists()  # never touched, let alone deleted


def test_escaping_merged_sub_source_fails_before_running(tmp_path: Path) -> None:
    """I2 variant: same boundary check applies to merged_sub_paths."""
    source_root, output_root = _setup(tmp_path, parts=1)
    outside = tmp_path / "outside" / "secret.srt"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_bytes(b"x")
    plan = MuxPlan(
        output_name="Show - S01E05.mkv",
        subtitle_merges=[
            SubtitleMergeDecision(
                source_relative="../outside/secret.srt",
                action="merge",
                language="eng",
                set_default=False,
            )
        ],
        mkvmerge_path="mkvmerge",
    )
    result = RenameResult()
    ran: list[list[str]] = []

    def runner(args: list[str], on_percent: Any = None) -> tuple[int, str]:
        ran.append(args)
        return 0, ""

    ok = execute_remux_op(
        _op(plan),
        source_root=source_root,
        output_root=output_root,
        result=result,
        runner=runner,
    )
    assert not ok
    assert ran == []
    assert any("escape their roots" in e for e in result.errors)
    assert outside.exists()
