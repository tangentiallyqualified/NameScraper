"""Manual merge/ungroup service actions."""

from __future__ import annotations

from pathlib import Path

from plex_renamer.app.services.episode_mapping_service import EpisodeMappingService
from plex_renamer.engine.episode_assignments import (
    ORIGIN_AUTO,
    EpisodeAssignmentTable,
    EpisodeSlot,
)
from plex_renamer.engine.models import ScanState


def _state_with_conflict(tmp_path: Path) -> tuple[ScanState, list[int]]:
    table = EpisodeAssignmentTable()
    table.add_slot(EpisodeSlot(season=1, episode=5, title="Five"))
    ids: list[int] = []
    for index in (1, 2):
        path = tmp_path / f"Show S01E05 ({index}).mkv"
        path.write_bytes(b"0")
        entry = table.add_file(path, parsed_episodes=(5,))
        table.assign(entry.file_id, 1, [5], origin=ORIGIN_AUTO, confidence=0.9)
        ids.append(entry.file_id)
    state = ScanState(folder=tmp_path, media_info={"name": "Show", "year": "2020"})
    state.assignments = table
    service = EpisodeMappingService()
    service.reproject(state)
    return state, ids


def test_merge_files_groups_and_reprojects(tmp_path: Path) -> None:
    state, ids = _state_with_conflict(tmp_path)
    service = EpisodeMappingService()
    service.merge_files(state, ids, season=1, episodes=[5])
    rows = [p for p in state.preview_items if p.file_id is not None]
    assert len(rows) == 1
    assert rows[0].status == "OK"  # manual -> approved-equivalent
    assert len(rows[0].merge_part_paths) == 2


def test_ungroup_restores_conflict(tmp_path: Path) -> None:
    state, ids = _state_with_conflict(tmp_path)
    service = EpisodeMappingService()
    service.merge_files(state, ids, season=1, episodes=[5])
    grouped_row = next(p for p in state.preview_items if p.merge_part_paths)
    service.ungroup_file(state, grouped_row)
    conflict_rows = [p for p in state.preview_items if p.is_conflict]
    assert len(conflict_rows) == 2
