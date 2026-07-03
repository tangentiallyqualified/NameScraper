"""RC22: zero-title-match multi-segment files must not auto-accept."""
from pathlib import Path

from plex_renamer.engine._episode_resolution import (
    CONF_WEAK_TITLE_NUMBER_CAP,
    CONF_TITLE_WINS_INEXACT,
    resolve_file,
    rescue_cross_season_segmented,
)
from plex_renamer.engine.episode_assignments import EpisodeAssignmentTable, EpisodeSlot

S3_TITLES = {1: "New Neighbors", 2: "Dummy Dummy", 3: "Smarter than Smarts"}
S2_TITLES = {34: "Movin On Up", 35: "Sumo Enchanted Evening", 36: "Hotel CatDog"}


def test_zero_match_multisegment_is_review_capped():
    resolution = resolve_file(
        parsed_episodes=(1, 2),
        raw_title="Sumo Enchanted Evening and Hotel CatDog",
        is_season_relative=True,
        season_titles=S3_TITLES,
        season=3,
    )
    assert resolution.episodes == (1, 2)
    assert resolution.confidence == CONF_WEAK_TITLE_NUMBER_CAP
    assert "title-no-match" in resolution.evidence
    assert "title-multi-segment" in resolution.evidence


def _build_table() -> EpisodeAssignmentTable:
    table = EpisodeAssignmentTable()
    for episode, title in S3_TITLES.items():
        table.add_slot(EpisodeSlot(season=3, episode=episode, title=title))
    for episode, title in S2_TITLES.items():
        table.add_slot(EpisodeSlot(season=2, episode=episode, title=title))
    return table


def test_cross_season_segmented_rescue_moves_file():
    table = _build_table()
    entry = table.add_file(
        Path("S03 E01-E02 - Sumo Enchanted Evening and Hotel CatDog.mkv"),
        parsed_episodes=(1, 2),
        raw_title="Sumo Enchanted Evening and Hotel CatDog",
        is_season_relative=True,
        season_hint=3,
        folder_season=3,
    )
    table.assign(
        entry.file_id, 3, [1, 2], origin="auto",
        confidence=CONF_WEAK_TITLE_NUMBER_CAP,
        evidence=frozenset({"number", "title-no-match", "title-multi-segment"}),
    )
    rescue_cross_season_segmented(table)
    assignment = table.assignment_for(entry.file_id)
    assert assignment.season == 2
    assert assignment.episodes == (35, 36)
    assert assignment.confidence == CONF_TITLE_WINS_INEXACT
    assert "cross-season-rescue" in assignment.evidence
