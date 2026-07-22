"""Tests for _resolve_into_table in the normal TV scanner."""

from pathlib import Path

from plex_renamer.engine._tv_scanner import TVScanner
from plex_renamer.engine._tv_scanner_normal import _resolve_into_table
from plex_renamer.engine.episode_assignments import (
    ORIGIN_MANUAL,
    EpisodeAssignmentTable,
    EpisodeSlot,
)
from plex_renamer.parsing import extract_episode


def make_season1_table() -> EpisodeAssignmentTable:
    table = EpisodeAssignmentTable()
    for ep in range(1, 6):
        table.add_slot(EpisodeSlot(season=1, episode=ep, title=f"Ep {ep}"))
    return table


SEASON_TITLES = {1: "Ep 1", 2: "Ep 2", 3: "Ep 3", 4: "Ep 4", 5: "Ep 5"}


def test_extract_episode_noncontiguous_yields_3_and_5():
    """Verify the parse that triggers the bug produces [3, 5]."""
    episodes, _, is_season_relative = extract_episode("Show S01E03E05.mkv")
    assert episodes == [3, 5]
    assert is_season_relative is True


def test_resolve_into_table_contiguous_file_is_assigned():
    table = make_season1_table()
    _resolve_into_table(
        table,
        file_path=Path("Show S01E01.mkv"),
        season_num=1,
        season_titles=SEASON_TITLES,
    )
    assigned = [fid for fid in table.files if table.assignment_for(fid) is not None]
    assert len(assigned) == 1


def test_resolve_into_table_noncontiguous_file_does_not_raise():
    """A non-contiguous multi-episode file must not raise — it must be marked unassigned."""
    table = make_season1_table()
    # Assign a good file first so we can confirm it is not disturbed.
    _resolve_into_table(
        table,
        file_path=Path("Show S01E01.mkv"),
        season_num=1,
        season_titles=SEASON_TITLES,
    )
    # This should NOT raise ValueError even though [3, 5] is non-contiguous.
    _resolve_into_table(
        table,
        file_path=Path("Show S01E03E05.mkv"),
        season_num=1,
        season_titles=SEASON_TITLES,
    )

    # E01 file must still be assigned.
    e01_entry = next(e for e in table.files.values() if e.path.name == "Show S01E01.mkv")
    assert table.assignment_for(e01_entry.file_id) is not None

    # E03E05 file must be unassigned (in unassigned_files).
    bad_entry = next(e for e in table.files.values() if e.path.name == "Show S01E03E05.mkv")
    assert table.assignment_for(bad_entry.file_id) is None
    unassigned_ids = {entry.file_id for entry, _ in table.unassigned_files()}
    assert bad_entry.file_id in unassigned_ids


def test_cross_season_pulls_pilot_to_specials():
    table = make_season1_table()  # S1 slots 1-5
    _resolve_into_table(
        table,
        file_path=Path("Tigtone S01E01 - Tigtone and the Pilot.mkv"),
        season_num=1,
        season_titles={1: "Tigtone and His Fellowship Of", 2: "Tigtone and the Beautiful War"},
        specials_titles={1: "Tigtone and the Pilot"},
    )
    entry = next(e for e in table.files.values() if "Pilot" in e.path.name)
    assignment = table.assignment_for(entry.file_id)
    assert assignment is not None
    assert assignment.season == 0
    assert assignment.episodes == (1,)
    assert "cross-season-special" in assignment.evidence


def test_cross_season_does_not_pull_normal_episode():
    table = make_season1_table()
    _resolve_into_table(
        table,
        file_path=Path("Show S01E02 - Ep 2.mkv"),
        season_num=1,
        season_titles=SEASON_TITLES,  # {1:"Ep 1", ... 5:"Ep 5"}
        specials_titles={1: "Ep 2 Behind the Scenes"},
    )
    entry = next(iter(table.files.values()))
    assignment = table.assignment_for(entry.file_id)
    assert assignment is not None
    assert assignment.season == 1  # own-season title agreement wins
    assert assignment.episodes == (2,)


def test_cross_season_substring_pull_tagged_inexact():
    table = make_season1_table()  # S1 slots 1-5
    # E07 is NOT a valid own-season episode, so the substring S0 pull is
    # allowed (RC24b only protects VALID explicit own-season numbers).
    _resolve_into_table(
        table,
        file_path=Path("Show S01E07 - The Lost Pilot Episode.mkv"),
        season_num=1,
        season_titles={1: "Completely Different", 2: "Also Different"},
        specials_titles={1: "The Lost Pilot"},
    )
    entry = next(iter(table.files.values()))
    assignment = table.assignment_for(entry.file_id)
    assert assignment is not None
    assert assignment.season == 0
    assert "cross-season-special" in assignment.evidence
    assert "title-strong-inexact" in assignment.evidence
    assert "title-strong" not in assignment.evidence


def test_inexact_s0_pull_blocked_for_valid_own_number():
    table = make_season1_table()  # S1 slots 1-5
    # Same substring hit, but E01 IS valid in the own season -> no pull (RC24b).
    _resolve_into_table(
        table,
        file_path=Path("Show S01E01 - The Lost Pilot Episode.mkv"),
        season_num=1,
        season_titles={1: "Completely Different", 2: "Also Different"},
        specials_titles={1: "The Lost Pilot"},
    )
    entry = next(iter(table.files.values()))
    assignment = table.assignment_for(entry.file_id)
    assert assignment is not None
    assert assignment.season == 1
    assert assignment.episodes == (1,)


def test_specials_title_evidence_strips_quality_tags():
    table = EpisodeAssignmentTable()
    table.add_slot(
        EpisodeSlot(season=0, episode=2, title="The Writers Flipped, They Have No Script")
    )
    _resolve_into_table(
        table,
        file_path=Path(
            "The Writers Flipped, They Have No Script (480p DVD x265 HEVC 10bit AAC 2.0 Ghost).mkv"
        ),
        season_num=0,
        season_titles={2: "The Writers Flipped, They Have No Script"},
    )
    entry = next(iter(table.files.values()))
    # raw_title must be set (not None) and must not contain quality noise
    assert entry.raw_title is not None, "raw_title should be the cleaned stem, not None"
    assert "480p" not in entry.raw_title
    assignment = table.assignment_for(entry.file_id)
    assert assignment is not None
    assert assignment.episodes == (2,)
    assert assignment.confidence >= 0.85


class _SeasonMapTMDB:
    """Minimal TMDB stand-in exposing a fixed, pre-fetched season map."""

    language = "en-US"

    def __init__(self, seasons: dict):
        self._seasons = seasons

    def get_season_map(self, show_id):
        total = sum(
            payload["count"] for season_num, payload in self._seasons.items() if season_num > 0
        )
        return self._seasons, total

    def get_season(self, show_id, season_num):
        return self._seasons.get(
            season_num,
            {"titles": {}, "posters": {}, "episodes": {}, "count": 0},
        )

    def get_tv_details(self, show_id):
        return {"seasons": []}

    def get_alternative_titles(
        self, media_id: int, media_type: str = "movie"
    ) -> list[tuple[str, str]]:
        return []


def _season(titles: dict[int, str]) -> dict:
    return {"titles": titles, "posters": {}, "episodes": {}, "count": len(titles)}


SHOW_INFO = {"id": 5, "name": "Demo Show", "year": "2020"}


def test_all_tmdb_seasons_get_slots_even_without_local_folders(tmp_path):
    """Shaun the Sheep S6 bug: TMDB knows about a season with no matched
    local season directory. Its slots must still be registered so bulk
    assign can offer it and manual table.assign can target it."""
    season_dir = tmp_path / "Season 01"
    season_dir.mkdir()
    (season_dir / "Demo Show S01E01.mkv").touch()
    seasons = {
        1: _season({1: "Ep 1", 2: "Ep 2", 3: "Ep 3"}),
        6: _season({1: "S6 Ep 1", 2: "S6 Ep 2", 3: "S6 Ep 3", 4: "S6 Ep 4", 5: "S6 Ep 5"}),
    }
    scanner = TVScanner(_SeasonMapTMDB(seasons), SHOW_INFO, tmp_path)
    scanner.scan()
    table = scanner.assignment_table
    assert (6, 1) in table.slots
    assert (6, 5) in table.slots

    # And assigning into the unscanned season must not raise.
    entry = next(iter(table.files.values()))
    table.assign(entry.file_id, 6, [1], origin=ORIGIN_MANUAL, displace=True)
