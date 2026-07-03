"""Tests for slot-conflict resolution policy.

User invariant: an episode must never be listed twice with an unresolved
conflict. Reproduced cases: ATHF S00E01 (inexact title vs bare special
number), Squidbillies S05 (duplicate copies from two source roots), ATHF
S00E20 (nine extras all substring-matching one special), DS9 S01E02
(double-episode premiere vs exact-titled E02), Rugrats S05E07 (segmented
run vs whole-run number claim), Trailer Park Boys S10 / Futurama S09E01
(show name used as episode-title evidence).
"""

from __future__ import annotations

from pathlib import Path

from plex_renamer.engine._episode_resolution import apply_confidence_adjustments
from plex_renamer.engine._tv_scanner_normal import _resolve_into_table
from plex_renamer.engine.episode_assignments import (
    ORIGIN_AUTO,
    EpisodeAssignmentTable,
    EpisodeSlot,
)

ROOT = Path("C:/lib/show")
SHOW_INFO = {"id": 9, "name": "Demo Show", "year": "2001"}


def _add(table, name, parsed, season, episodes, evidence, conf=0.7, title=None,
         season_relative=False, hint=None):
    entry = table.add_file(
        ROOT / name,
        parsed_episodes=tuple(parsed),
        raw_title=title,
        is_season_relative=season_relative,
        season_hint=hint,
        folder_season=hint,
    )
    table.assign(
        entry.file_id, season, list(episodes),
        origin=ORIGIN_AUTO, confidence=conf, evidence=frozenset(evidence),
    )
    return entry


def _slots(table, season, titles):
    for episode, title in titles.items():
        table.add_slot(EpisodeSlot(season=season, episode=episode, title=title))


class TestConflictLadder:
    def test_inexact_title_beats_bare_special_number(self):
        table = EpisodeAssignmentTable()
        _slots(table, 0, {1: "Rabbot", 2: "Other"})
        rabbot = _add(
            table, "S00E10 - Rabbot - The Original Cut.mkv", (10,), 0, [1],
            {"number-disagree", "title-strong-inexact"}, title="Rabbot - The Original Cut",
        )
        baffler = _add(
            table, "S00E01 - Baffler Meal.mkv", (1,), 0, [1],
            {"number", "special-number-only"}, conf=0.5, title="Baffler Meal",
        )
        apply_confidence_adjustments(table, show_info=SHOW_INFO)
        assert table.assignment_for(rabbot.file_id) is not None
        assert table.assignment_for(baffler.file_id) is None
        assert not table.conflicts()

    def test_duplicate_copies_resolve_to_primary(self):
        table = EpisodeAssignmentTable()
        _slots(table, 5, {1: "Need for Weed"})
        first = _add(
            table, "Squidbillies (2004) - S05E01 - Need for Weed.mkv", (1,), 5, [1],
            {"number", "title-agree"}, conf=0.96, title="Need for Weed",
            season_relative=True, hint=5,
        )
        second = _add(
            table, "Squidbillies (2005) S05E01 - Need for Weed.mkv", (1,), 5, [1],
            {"number", "title-agree"}, conf=0.96, title="Need for Weed",
            season_relative=True, hint=5,
        )
        apply_confidence_adjustments(table, show_info=SHOW_INFO)
        assert table.assignment_for(first.file_id) is not None
        assert table.assignment_for(second.file_id) is None
        reason = table.unassigned_reasons[second.file_id]
        assert "duplicate copy" in reason
        assert not table.conflicts()

    def test_many_way_ambiguous_tie_unassigns_all(self):
        table = EpisodeAssignmentTable()
        _slots(table, 0, {20: "Answering Machine Messages"})
        entries = [
            _add(
                table, f"S00E{109 + i} - VOL 3 - Answering Machine Messages - {name}.mkv",
                (109 + i,), 0, [20], {"title-strong"}, conf=0.88,
                title=f"VOL 3 - Answering Machine Messages - {name}",
            )
            for i, name in enumerate(["Carl 1", "Carl 2", "Frylock"])
        ]
        apply_confidence_adjustments(table, show_info=SHOW_INFO)
        for entry in entries:
            assert table.assignment_for(entry.file_id) is None
        assert not table.conflicts()

    def test_exact_title_winner_still_beats_number_claim(self):
        table = EpisodeAssignmentTable()
        _slots(table, 1, {12: "Taming of the Screwy"})
        exact = _add(
            table, "S01E05 - Taming of the Screwy.mkv", (5,), 1, [12],
            {"number-disagree", "title-strong"}, conf=0.9, title="Taming of the Screwy",
        )
        number = _add(
            table, "S01E12 - Garage Sale & West Side Pigeons.mkv", (12,), 1, [12],
            {"number", "title-ambiguous"}, conf=0.88,
            title="Garage Sale of the Century & West Side Pigeons",
            season_relative=True, hint=1,
        )
        apply_confidence_adjustments(table, show_info=SHOW_INFO)
        assert table.assignment_for(exact.file_id) is not None
        assert table.assignment_for(number.file_id) is None


class TestRunEdgeTrim:
    def test_double_episode_premiere_trims_to_titled_slot(self):
        """DS9: file S01E01-E02 'Emissary' + file S01E03 'Past Prologue'."""
        table = EpisodeAssignmentTable()
        _slots(table, 1, {1: "Emissary", 2: "Past Prologue", 3: "A Man Alone"})
        emissary = _add(
            table, "DS9 - S01E01-E02 - Emissary.mkv", (1, 2), 1, [1, 2],
            {"number", "title-agree"}, conf=0.96, title="Emissary",
            season_relative=True, hint=1,
        )
        prologue = _add(
            table, "DS9 - S01E03 - Past Prologue.mkv", (3,), 1, [2],
            {"number-disagree", "title-strong"}, conf=0.9, title="Past Prologue",
        )
        apply_confidence_adjustments(table, show_info=SHOW_INFO)
        assert table.assignment_for(emissary.file_id).episodes == (1,)
        assert table.assignment_for(prologue.file_id).episodes == (2,)
        assert not table.conflicts()


class TestRunShift:
    def test_whole_run_claim_shifts_off_segmented_run(self):
        """Rugrats: seg run E06-E07 vs rule-1 run E07-E08 anchored at E08."""
        table = EpisodeAssignmentTable()
        _slots(table, 5, {
            6: "The Wild Wild West", 7: "Angelica for a Day",
            8: "Word of the Day", 9: "Jonathan Babysits", 10: "Grandpa's Bad Bug",
        })
        segmented = _add(
            table, "Rugrats - S05E05-E06 - The Wild Wild West & Angelica for a Day.mkv",
            (5, 6), 5, [6, 7],
            {"number-disagree", "title-segmented", "title-strong"}, conf=0.9,
            title="The Wild Wild West & Angelica for a Day",
            season_relative=True, hint=5,
        )
        whole = _add(
            table, "Rugrats - S05E07-E08 - Word of the Day & Jonathan Babysits.mkv",
            (7, 8), 5, [7, 8],
            {"number", "title-agree"}, conf=0.96,
            title="Word of the Day & Jonathan Babysits",
            season_relative=True, hint=5,
        )
        apply_confidence_adjustments(table, show_info=SHOW_INFO)
        assert table.assignment_for(segmented.file_id).episodes == (6, 7)
        assert table.assignment_for(whole.file_id).episodes == (8, 9)
        assert not table.conflicts()


class TestShowNameTitleGuard:
    def test_show_name_title_is_not_episode_evidence(self):
        """Trailer Park Boys S10 files titled with the show name must keep
        their explicit S10 numbers instead of piling onto an S0 special."""
        table = EpisodeAssignmentTable()
        for episode in range(1, 4):
            table.add_slot(EpisodeSlot(season=10, episode=episode, title=f"Ep {episode}"))
        table.add_slot(EpisodeSlot(
            season=0, episode=3, title="Trailer Park Boys Live at the North Pole",
        ))
        for episode in range(1, 4):
            _resolve_into_table(
                table,
                file_path=Path(f"Trailer Park Boys - S10E{episode:02d} - Trailer Park Boys.mkv"),
                season_num=10,
                season_titles={1: "Ep 1", 2: "Ep 2", 3: "Ep 3"},
                specials_titles={3: "Trailer Park Boys Live at the North Pole"},
                show_name="Trailer Park Boys",
            )
        for assignment in table.assignments():
            assert assignment.season == 10
        assert not table.conflicts()

    def test_valid_explicit_episode_is_never_cross_season_rescued(self):
        """TPB S00E03 is literally titled "Trailer Park Boys": S11 files whose
        censored titles miss their own-season match must keep their explicit
        S11E## slots instead of piling onto the show-name special."""
        table = EpisodeAssignmentTable()
        s11_titles = {
            4: "Darth Lahey",
            5: "Flight of the Bumblecock",
            9: "Oh, My F**k Boys, We Killed Lahey & Randy",
        }
        for episode, title in s11_titles.items():
            table.add_slot(EpisodeSlot(season=11, episode=episode, title=title))
        table.add_slot(EpisodeSlot(season=0, episode=3, title="Trailer Park Boys"))
        for episode, censored in (
            (5, "Flight Of The Bumbleck Nf Web Dd 1 H 264"),
            (9, "Oh My Fk Boys We Killed Lahey And Randy Nf Web Dd 1 H 264"),
        ):
            _resolve_into_table(
                table,
                file_path=Path(
                    f"Trailer Park Boys - S11E{episode:02d} - Trailer Park Boys {censored}.mkv"
                ),
                season_num=11,
                season_titles=s11_titles,
                specials_titles={3: "Trailer Park Boys"},
                show_name="Trailer Park Boys",
            )
        by_file = {
            table.files[a.file_id].path.name: (a.season, a.episodes)
            for a in table.assignments()
        }
        assert len(by_file) == 2
        for (season, episodes) in by_file.values():
            assert season == 11
        assert not table.conflicts()
