"""Tests for cross-numbering fixes when source seasons don't match TMDB.

Covers:
- Season-relative confidence floors must not apply when the file's explicit
  season hint disagrees with the assigned season (Oshi no Ko S03E06 was
  auto-accepted onto S01E06 at 0.88).
- Uniform anchor-offset rescue: when title-matched siblings in one source
  season all land at the same nonzero offset, number-only and lost-conflict
  files follow that offset at review confidence (JJK "Cog" -> E53; Rawhide
  S5 e14/e23 into the adjacent unclaimed slots).
"""

from __future__ import annotations

from pathlib import Path

from plex_renamer.engine._episode_resolution import (
    apply_confidence_adjustments,
    apply_uniform_offset_rescue,
)
from plex_renamer.engine.episode_assignments import (
    ORIGIN_AUTO,
    REASON_NOT_IN_SEASON,
    EpisodeAssignmentTable,
    EpisodeSlot,
    lost_conflict_reason,
)

ROOT = Path("C:/lib/show")
SHOW_INFO = {"id": 5, "name": "Demo Show", "year": "2020"}


def _slots(table: EpisodeAssignmentTable, season: int, titles: dict[int, str]) -> None:
    for episode, title in titles.items():
        table.add_slot(EpisodeSlot(season=season, episode=episode, title=title))


class TestSeasonHintFloorGuard:
    def test_no_explicit_floor_when_hint_disagrees_with_assigned_season(self):
        table = EpisodeAssignmentTable()
        _slots(table, 1, {i: f"Ep {i}" for i in range(1, 30)})
        entry = table.add_file(
            ROOT / "Demo Show S03E06.mkv",
            parsed_episodes=(6,),
            is_season_relative=True,
            season_hint=3,
            folder_season=3,
        )
        table.assign(
            entry.file_id, 1, [6],
            origin=ORIGIN_AUTO, confidence=0.50, evidence=frozenset({"number"}),
        )
        apply_confidence_adjustments(table, show_info=SHOW_INFO)
        assignment = table.assignment_for(entry.file_id)
        assert assignment.confidence < 0.85

    def test_explicit_floor_still_applies_when_hint_matches(self):
        table = EpisodeAssignmentTable()
        _slots(table, 3, {i: f"Ep {i}" for i in range(1, 10)})
        entry = table.add_file(
            ROOT / "Demo Show S03E06.mkv",
            parsed_episodes=(6,),
            is_season_relative=True,
            season_hint=3,
            folder_season=3,
        )
        table.assign(
            entry.file_id, 3, [6],
            origin=ORIGIN_AUTO, confidence=0.50, evidence=frozenset({"number"}),
        )
        apply_confidence_adjustments(table, show_info=SHOW_INFO)
        assignment = table.assignment_for(entry.file_id)
        assert assignment.confidence >= 0.86


def _anchored_table() -> tuple[EpisodeAssignmentTable, list]:
    """Source season 3 files whose titles anchor at TMDB S1 offset +47."""
    table = EpisodeAssignmentTable()
    _slots(table, 1, {i: f"Ep {i}" for i in range(1, 60)})
    entries = []
    for parsed, target in ((1, 48), (2, 49), (12, 59)):
        entry = table.add_file(
            ROOT / f"Demo S03E{parsed:02d} Title.mkv",
            parsed_episodes=(parsed,),
            is_season_relative=True,
            season_hint=3,
            folder_season=3,
        )
        table.assign(
            entry.file_id, 1, [target],
            origin=ORIGIN_AUTO, confidence=0.70,
            evidence=frozenset({"title-strong-inexact", "number-disagree"}),
        )
        entries.append(entry)
    return table, entries


class TestUniformOffsetRescue:
    def test_number_only_file_follows_anchor_offset(self):
        table, _ = _anchored_table()
        cog = table.add_file(
            ROOT / "Demo S03E06 Cog.mkv",
            parsed_episodes=(6,),
            is_season_relative=True,
            season_hint=3,
            folder_season=3,
        )
        table.assign(
            cog.file_id, 1, [6],
            origin=ORIGIN_AUTO, confidence=0.88,
            evidence=frozenset({"number", "season-relative"}),
        )
        apply_uniform_offset_rescue(table)
        assignment = table.assignment_for(cog.file_id)
        assert assignment.episodes == (53,)
        assert "offset-inferred" in assignment.evidence
        assert assignment.confidence < 0.85

    def test_not_in_season_file_is_rescued_with_offset(self):
        table, _ = _anchored_table()
        stray = table.add_file(
            ROOT / "Demo S03E07 Unknown.mkv",
            parsed_episodes=(7,),
            is_season_relative=True,
            season_hint=3,
            folder_season=3,
        )
        table.mark_unassigned(stray.file_id, REASON_NOT_IN_SEASON)
        apply_uniform_offset_rescue(table)
        assignment = table.assignment_for(stray.file_id)
        assert assignment is not None
        assert assignment.episodes == (54,)

    def test_lost_conflict_file_moves_into_freed_slot(self):
        """Rawhide-style: e15 number-claims E15; e14's title anchor freed it."""
        table = EpisodeAssignmentTable()
        _slots(table, 5, {i: f"Incident {i}" for i in range(1, 31)})
        anchors = []
        for parsed in (1, 2, 13):
            entry = table.add_file(
                ROOT / f"Rawhide S05e{parsed:02d} Title.mkv",
                parsed_episodes=(parsed,),
                is_season_relative=True,
                season_hint=5,
                folder_season=5,
            )
            table.assign(
                entry.file_id, 5, [parsed + 1],
                origin=ORIGIN_AUTO, confidence=0.92,
                evidence=frozenset({"title-strong", "number-disagree"}),
            )
            anchors.append(entry)
        # e15 claimed E15 by bare number (its real slot is E16).
        e15 = table.add_file(
            ROOT / "Rawhide S05e15 Trails End.mkv",
            parsed_episodes=(15,),
            is_season_relative=True,
            season_hint=5,
            folder_season=5,
        )
        table.assign(
            e15.file_id, 5, [15],
            origin=ORIGIN_AUTO, confidence=0.88,
            evidence=frozenset({"number", "season-relative"}),
        )
        # e14 lost the conflict for E15 against a title anchor... simulate as
        # a lost-conflict unassigned file whose true slot (15) frees up when
        # e15 moves to 16.
        e14 = table.add_file(
            ROOT / "Rawhide S05e14 Buryin Man.mkv",
            parsed_episodes=(14,),
            is_season_relative=True,
            season_hint=5,
            folder_season=5,
        )
        table.mark_unassigned(e14.file_id, lost_conflict_reason(5, 14))

        apply_uniform_offset_rescue(table)

        assert table.assignment_for(e15.file_id).episodes == (16,)
        moved = table.assignment_for(e14.file_id)
        assert moved is not None
        assert moved.episodes == (15,)

    def test_no_rescue_when_offsets_disagree(self):
        table, entries = _anchored_table()
        # Add a conflicting anchor at a different offset.
        odd = table.add_file(
            ROOT / "Demo S03E03 Odd.mkv",
            parsed_episodes=(3,),
            is_season_relative=True,
            season_hint=3,
            folder_season=3,
        )
        table.assign(
            odd.file_id, 1, [20],
            origin=ORIGIN_AUTO, confidence=0.70,
            evidence=frozenset({"title-strong", "number-disagree"}),
        )
        mover = table.add_file(
            ROOT / "Demo S03E06 Cog.mkv",
            parsed_episodes=(6,),
            is_season_relative=True,
            season_hint=3,
            folder_season=3,
        )
        table.assign(
            mover.file_id, 1, [6],
            origin=ORIGIN_AUTO, confidence=0.88,
            evidence=frozenset({"number", "season-relative"}),
        )
        apply_uniform_offset_rescue(table)
        assert table.assignment_for(mover.file_id).episodes == (6,)

    def test_no_rescue_with_single_anchor(self):
        table = EpisodeAssignmentTable()
        _slots(table, 1, {i: f"Ep {i}" for i in range(1, 20)})
        anchor = table.add_file(
            ROOT / "Demo S02E01 A.mkv",
            parsed_episodes=(1,), is_season_relative=True,
            season_hint=2, folder_season=2,
        )
        table.assign(
            anchor.file_id, 1, [11],
            origin=ORIGIN_AUTO, confidence=0.9,
            evidence=frozenset({"title-strong", "number-disagree"}),
        )
        mover = table.add_file(
            ROOT / "Demo S02E02 B.mkv",
            parsed_episodes=(2,), is_season_relative=True,
            season_hint=2, folder_season=2,
        )
        table.assign(
            mover.file_id, 1, [2],
            origin=ORIGIN_AUTO, confidence=0.88,
            evidence=frozenset({"number", "season-relative"}),
        )
        apply_uniform_offset_rescue(table)
        assert table.assignment_for(mover.file_id).episodes == (2,)
