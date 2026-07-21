"""Projection of part groups: one row per group, parts carried on the row."""

from __future__ import annotations

from pathlib import Path

from plex_renamer.engine._episode_projection import project_preview_items
from plex_renamer.engine.episode_assignments import (
    ORIGIN_AUTO,
    ORIGIN_MANUAL,
    EpisodeAssignmentTable,
    EpisodeSlot,
)
from plex_renamer.engine.models import EPISODE_REVIEW_STATUS_PREFIX

_SHOW_INFO = {"name": "Show", "year": "2020"}
_MEDIA_FIELDS: dict[str, object] = {"media_id": 1, "media_name": "Show"}


def _grouped_table(tmp_path: Path, *, origin: str = ORIGIN_AUTO) -> EpisodeAssignmentTable:
    table = EpisodeAssignmentTable()
    table.add_slot(EpisodeSlot(season=1, episode=5, title="Five"))
    ids: list[int] = []
    for index in (1, 2, 3):
        path = tmp_path / f"Show S01E05 ({index}).mkv"
        path.write_bytes(b"0")
        entry = table.add_file(path, parsed_episodes=(5,))
        ids.append(entry.file_id)
    table.group_parts(ids, 1, [5], origin=origin, confidence=0.9)
    return table


def test_group_projects_one_row_with_parts(tmp_path: Path) -> None:
    table = _grouped_table(tmp_path)
    items = project_preview_items(
        table, show_info=_SHOW_INFO, root=tmp_path, media_fields=_MEDIA_FIELDS
    )
    assert len(items) == 1
    item = items[0]
    assert item.original.name == "Show S01E05 (1).mkv"
    assert [p.name for p in item.merge_part_paths] == [
        "Show S01E05 (1).mkv",
        "Show S01E05 (2).mkv",
        "Show S01E05 (3).mkv",
    ]
    assert len(item.merge_part_file_ids) == 3
    assert item.new_name is not None and item.new_name.endswith(".mkv")


def test_unapproved_auto_group_is_review_with_part_count(tmp_path: Path) -> None:
    table = _grouped_table(tmp_path)
    items = project_preview_items(
        table, show_info=_SHOW_INFO, root=tmp_path, media_fields=_MEDIA_FIELDS
    )
    status = items[0].status
    assert status.startswith(EPISODE_REVIEW_STATUS_PREFIX)
    assert "3 parts" in status


def test_approved_group_is_ok(tmp_path: Path) -> None:
    table = _grouped_table(tmp_path)
    primary_id = min(table.files)
    table.set_approved(primary_id)
    items = project_preview_items(
        table, show_info=_SHOW_INFO, root=tmp_path, media_fields=_MEDIA_FIELDS
    )
    assert items[0].status == "OK"


def test_manual_group_is_ok(tmp_path: Path) -> None:
    table = _grouped_table(tmp_path, origin=ORIGIN_MANUAL)
    items = project_preview_items(
        table, show_info=_SHOW_INFO, root=tmp_path, media_fields=_MEDIA_FIELDS
    )
    assert items[0].status == "OK"


def test_normal_rows_have_empty_merge_fields(tmp_path: Path) -> None:
    table = EpisodeAssignmentTable()
    table.add_slot(EpisodeSlot(season=1, episode=1, title="One"))
    path = tmp_path / "Show S01E01.mkv"
    path.write_bytes(b"0")
    entry = table.add_file(path, parsed_episodes=(1,))
    table.assign(entry.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=0.99)
    items = project_preview_items(
        table, show_info=_SHOW_INFO, root=tmp_path, media_fields=_MEDIA_FIELDS
    )
    assert items[0].merge_part_paths == []
    assert items[0].merge_part_file_ids == []
