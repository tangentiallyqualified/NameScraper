"""Role-based part groups on EpisodeAssignmentTable (Approach B)."""

from __future__ import annotations

from pathlib import Path

import pytest

from plex_renamer.engine.episode_assignments import (
    ORIGIN_AUTO,
    ORIGIN_MANUAL,
    ROLE_PART,
    ROLE_PRIMARY,
    EpisodeAssignmentTable,
    EpisodeSlot,
    merge_tables,
)


def _table_with_slot() -> EpisodeAssignmentTable:
    table = EpisodeAssignmentTable()
    table.add_slot(EpisodeSlot(season=1, episode=5, title="Ep Five"))
    return table


def _add_parts(table: EpisodeAssignmentTable, count: int) -> list[int]:
    ids: list[int] = []
    for index in range(1, count + 1):
        entry = table.add_file(Path(f"Show S01E05 ({index}).mkv"), parsed_episodes=(5,))
        entry.part_marker = index
        ids.append(entry.file_id)
    return ids


def test_group_parts_creates_primary_and_parts_in_order() -> None:
    table = _table_with_slot()
    ids = _add_parts(table, 3)
    table.group_parts(ids, 1, [5], origin=ORIGIN_AUTO, confidence=0.9)
    roles = [(a.role, a.part_order) for a in (table.assignment_for(i) for i in ids)]
    assert roles == [(ROLE_PRIMARY, 1), (ROLE_PART, 2), (ROLE_PART, 3)]
    assert all(table.assignment_for(i).confidence == 0.9 for i in ids)


def test_grouped_claims_are_one_logical_claim_not_a_conflict() -> None:
    table = _table_with_slot()
    ids = _add_parts(table, 3)
    table.group_parts(ids, 1, [5], origin=ORIGIN_AUTO)
    assert table.conflicts() == {}
    assert table.conflicted_file_ids() == set()
    claimant = table.claimant(1, 5)
    assert claimant is not None and claimant.file_id == ids[0]


def test_group_plus_outside_claim_is_a_conflict() -> None:
    table = _table_with_slot()
    ids = _add_parts(table, 2)
    table.group_parts(ids, 1, [5], origin=ORIGIN_AUTO)
    outsider = table.add_file(Path("Other S01E05.mkv"), parsed_episodes=(5,))
    table.assign(outsider.file_id, 1, [5], origin=ORIGIN_AUTO)
    assert (1, 5) in table.conflicts()
    assert table.claimant(1, 5) is None


def test_part_group_members_ordered_and_empty_for_loners() -> None:
    table = _table_with_slot()
    ids = _add_parts(table, 3)
    table.group_parts(ids, 1, [5], origin=ORIGIN_AUTO)
    members = table.part_group_members(ids[1])
    assert [m.file_id for m in members] == ids
    lone = table.add_file(Path("Other S01E01.mkv"))
    assert table.part_group_members(lone.file_id) == []


def test_ungroup_reverts_to_individual_primary_claims() -> None:
    table = _table_with_slot()
    ids = _add_parts(table, 2)
    table.group_parts(ids, 1, [5], origin=ORIGIN_AUTO)
    table.ungroup_parts(ids[1])
    assignments = [table.assignment_for(i) for i in ids]
    assert all(a is not None and a.role == ROLE_PRIMARY and a.part_order == 0 for a in assignments)
    assert (1, 5) in table.conflicts()  # two independent claims now


def test_group_parts_rejects_unknown_and_short_groups() -> None:
    table = _table_with_slot()
    ids = _add_parts(table, 2)
    with pytest.raises(ValueError):
        table.group_parts([ids[0]], 1, [5], origin=ORIGIN_AUTO)
    with pytest.raises(ValueError):
        table.group_parts([ids[0], 999], 1, [5], origin=ORIGIN_AUTO)


def test_merge_tables_preserves_roles_and_part_order() -> None:
    table = _table_with_slot()
    ids = _add_parts(table, 2)
    table.group_parts(ids, 1, [5], origin=ORIGIN_MANUAL)
    target = _table_with_slot()
    id_map = merge_tables(target, table)
    moved = [target.assignment_for(id_map[i]) for i in ids]
    assert [(a.role, a.part_order) for a in moved] == [(ROLE_PRIMARY, 1), (ROLE_PART, 2)]


def test_set_approved_on_any_member_approves_the_group() -> None:
    table = _table_with_slot()
    ids = _add_parts(table, 3)
    table.group_parts(ids, 1, [5], origin=ORIGIN_AUTO)
    table.set_approved(ids[0])
    assert all(table.assignment_for(i).approved for i in ids)
