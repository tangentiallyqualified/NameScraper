"""RC20(4): fuzzy title -> unique unclaimed same-season slot rescue."""
from pathlib import Path

from plex_renamer.engine._episode_resolution import (
    CONF_TITLE_WINS_INEXACT,
    rescue_same_season_fuzzy_titles,
)
from plex_renamer.engine.episode_assignments import (
    EpisodeAssignmentTable,
    EpisodeSlot,
    lost_conflict_reason,
)


def test_lost_conflict_file_rescued_by_fuzzy_title():
    table = EpisodeAssignmentTable()
    titles = {1: "Zooing Time", 2: "H²-Whoa!", 3: "Fish and Dips"}
    for episode, title in titles.items():
        table.add_slot(EpisodeSlot(season=3, episode=episode, title=title))
    entry = table.add_file(
        Path("The Angry Beavers - S03E05 - H-2 Whoa.mkv"),
        parsed_episodes=(5,),
        raw_title="H-2 Whoa",
        is_season_relative=True,
        season_hint=3,
        folder_season=3,
    )
    table.mark_unassigned(entry.file_id, lost_conflict_reason(3, 5))
    rescue_same_season_fuzzy_titles(table)
    assignment = table.assignment_for(entry.file_id)
    assert assignment is not None
    assert assignment.season == 3 and assignment.episodes == (2,)
    assert assignment.confidence == CONF_TITLE_WINS_INEXACT
    assert "same-season-rescue" in assignment.evidence
