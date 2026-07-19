"""Behavioral tests for engine rename execution (duplicates, moves, cleanup)."""

from __future__ import annotations

from pathlib import Path

from plex_renamer.engine import PreviewItem
from plex_renamer.engine._rename_execution import check_duplicates


def _item(
    original: Path,
    new_name: str | None,
    *,
    target_dir: Path | None = None,
    status: str = "OK",
) -> PreviewItem:
    return PreviewItem(
        original=original,
        new_name=new_name,
        target_dir=target_dir,
        season=1,
        episodes=[1],
        status=status,
    )


def test_check_duplicates_flags_second_item_on_same_target(tmp_path: Path) -> None:
    first = _item(tmp_path / "a.mkv", "Show - S01E01.mkv")
    second = _item(tmp_path / "b.mkv", "Show - S01E01.mkv")

    check_duplicates([first, second])

    assert first.status == "OK"
    assert second.status == "CONFLICT: same target as a.mkv"


def test_check_duplicates_is_case_insensitive_and_skips_unnamed(tmp_path: Path) -> None:
    first = _item(tmp_path / "a.mkv", "Show - S01E01.MKV")
    unnamed = _item(tmp_path / "skip.mkv", None)
    second = _item(tmp_path / "b.mkv", "show - s01e01.mkv")

    check_duplicates([first, unnamed, second])

    assert unnamed.status == "OK"
    assert second.status == "CONFLICT: same target as a.mkv"


def test_check_duplicates_distinct_target_dirs_do_not_conflict(tmp_path: Path) -> None:
    first = _item(tmp_path / "a.mkv", "Show - S01E01.mkv", target_dir=tmp_path / "Season 01")
    second = _item(tmp_path / "b.mkv", "Show - S01E01.mkv", target_dir=tmp_path / "Season 02")

    check_duplicates([first, second])

    assert first.status == "OK"
    assert second.status == "OK"
