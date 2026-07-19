"""Behavioral tests for engine rename execution (duplicates, moves, cleanup)."""

from __future__ import annotations

from pathlib import Path

from plex_renamer.engine import PreviewItem
from plex_renamer.engine._rename_execution import check_duplicates, execute_rename


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


def test_execute_rename_renames_checked_item_in_place(tmp_path: Path) -> None:
    root = tmp_path / "Show"
    season = root / "Season 01"
    season.mkdir(parents=True)
    src = season / "show.s01e01.720p.mkv"
    src.write_bytes(b"x")
    item = _item(src, "Show - S01E01.mkv")

    result = execute_rename([item], {0}, "Show", root)

    assert result.renamed_count == 1
    assert result.errors == []
    assert (season / "Show - S01E01.mkv").exists()
    assert not src.exists()
    assert result.log_entry["renames"] == [
        {"old": str(src), "new": str(season / "Show - S01E01.mkv")}
    ]


def test_execute_rename_moves_into_created_target_and_removes_empty_source(
    tmp_path: Path,
) -> None:
    root = tmp_path / "Show"
    incoming = root / "incoming"
    incoming.mkdir(parents=True)
    src = incoming / "ep1.mkv"
    src.write_bytes(b"x")
    target = root / "Season 01"
    item = _item(src, "Show - S01E01.mkv", target_dir=target)

    result = execute_rename([item], {0}, "Show", root)

    assert result.renamed_count == 1
    assert (target / "Show - S01E01.mkv").exists()
    assert str(target) in result.log_entry["created_dirs"]
    assert not incoming.exists()
    assert str(incoming) in result.log_entry["removed_dirs"]


def test_execute_rename_normalizes_season_directory_name(tmp_path: Path) -> None:
    root = tmp_path / "Show"
    season = root / "season 1"
    season.mkdir(parents=True)
    src = season / "ep1.mkv"
    src.write_bytes(b"x")
    item = _item(src, "Show - S01E01.mkv")

    result = execute_rename([item], {0}, "Show", root)

    assert (root / "Season 01" / "Show - S01E01.mkv").exists()
    assert result.log_entry["renamed_dirs"] == [
        {"old": str(season), "new": str(root / "Season 01")}
    ]


def test_execute_rename_leaves_unmatched_subtree_directories_alone(
    tmp_path: Path,
) -> None:
    root = tmp_path / "Show"
    unmatched_season = root / "Unmatched" / "season 2"
    unmatched_season.mkdir(parents=True)
    src = unmatched_season / "ep1.mkv"
    src.write_bytes(b"x")
    item = _item(src, "Mystery - S02E01.mkv")

    execute_rename([item], {0}, "Show", root)

    assert (unmatched_season / "Mystery - S02E01.mkv").exists()
    assert unmatched_season.exists()


def test_execute_rename_renames_root_to_show_folder_name(tmp_path: Path) -> None:
    root = tmp_path / "Show"
    season = root / "Season 01"
    season.mkdir(parents=True)
    src = season / "ep1.mkv"
    src.write_bytes(b"x")
    item = _item(src, "Show - S01E01.mkv")

    result = execute_rename([item], {0}, "Show", root, show_folder_name="Show (2020)")

    new_root = tmp_path / "Show (2020)"
    assert result.new_root == new_root
    assert (new_root / "Season 01" / "Show - S01E01.mkv").exists()
    assert {"old": str(root), "new": str(new_root)} in result.log_entry["renamed_dirs"]


def test_execute_rename_skips_when_target_exists(tmp_path: Path) -> None:
    root = tmp_path / "Show"
    season = root / "Season 01"
    season.mkdir(parents=True)
    src = season / "ep1.mkv"
    src.write_bytes(b"x")
    (season / "Show - S01E01.mkv").write_bytes(b"y")
    item = _item(src, "Show - S01E01.mkv")

    result = execute_rename([item], {0}, "Show", root)

    assert result.renamed_count == 0
    assert result.errors == ["Target already exists, skipped: Show - S01E01.mkv"]
    assert src.exists()


def test_execute_rename_filters_status_and_out_of_range_indices(
    tmp_path: Path,
) -> None:
    root = tmp_path / "Show"
    season = root / "Season 01"
    season.mkdir(parents=True)
    skipped = season / "skipped.mkv"
    skipped.write_bytes(b"x")
    unmatched = season / "unmatched.mkv"
    unmatched.write_bytes(b"x")
    items = [
        _item(skipped, "Skipped.mkv", status="SKIP: no match"),
        _item(unmatched, "Unmatched - S01E01.mkv", status="UNMATCHED: review"),
    ]

    result = execute_rename(items, {0, 1, 9}, "Show", root)

    assert result.renamed_count == 1
    assert skipped.exists()
    assert (season / "Unmatched - S01E01.mkv").exists()


def test_execute_rename_keeps_root_when_target_folder_exists(tmp_path: Path) -> None:
    root = tmp_path / "Show"
    (tmp_path / "Show (2020)").mkdir()
    season = root / "Season 01"
    season.mkdir(parents=True)
    src = season / "ep1.mkv"
    src.write_bytes(b"x")
    item = _item(src, "Show - S01E01.mkv")

    result = execute_rename([item], {0}, "Show", root, show_folder_name="Show (2020)")

    assert result.new_root is None
    assert (season / "Show - S01E01.mkv").exists()


def test_execute_rename_records_error_when_source_vanishes(tmp_path: Path) -> None:
    root = tmp_path / "Show"
    season = root / "Season 01"
    season.mkdir(parents=True)
    src = season / "ghost.mkv"  # never created on disk
    item = _item(src, "Show - S01E01.mkv")

    result = execute_rename([item], {0}, "Show", root)

    assert result.renamed_count == 0
    assert len(result.errors) == 1
    assert result.errors[0].startswith("ghost.mkv: ")


def test_execute_rename_skips_season_rename_when_proper_name_exists(
    tmp_path: Path,
) -> None:
    root = tmp_path / "Show"
    improper = root / "season 1"  # single digit; get_season extracts 1
    proper = root / "Season 01"  # proper format with two digits
    improper.mkdir(parents=True)
    proper.mkdir()
    src = improper / "ep1.mkv"
    src.write_bytes(b"x")
    item = _item(src, "Show - S01E01.mkv", target_dir=proper)

    result = execute_rename([item], {0}, "Show", root)

    assert result.renamed_count == 1
    assert not improper.exists()  # improper dir deleted after becoming empty
    assert (proper / "Show - S01E01.mkv").exists()  # file moved to proper dir
    assert "Season 01" not in result.log_entry["renamed_dirs"]  # Season 01 not renamed


def test_execute_rename_skips_unnamed_items(tmp_path: Path) -> None:
    root = tmp_path / "Show"
    season = root / "Season 01"
    season.mkdir(parents=True)
    src = season / "ep1.mkv"
    src.write_bytes(b"x")
    item = _item(src, None)  # unnamed item

    result = execute_rename([item], {0}, "Show", root)

    assert result.renamed_count == 0
    assert src.exists()
    assert result.errors == []
