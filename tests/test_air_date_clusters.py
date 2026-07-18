"""RC19: folder-season N maps onto the Nth air-date cluster."""

from pathlib import Path

from plex_renamer.engine._episode_resolution import CONF_TITLE_WINS_INEXACT
from plex_renamer.engine._tv_scanner_consolidated import (
    _air_date_clusters,
    apply_air_date_cluster_mapping,
)
from plex_renamer.engine.episode_assignments import (
    REASON_NOT_IN_SEASON,
    EpisodeAssignmentTable,
    EpisodeSlot,
)


def _season_data():
    titles, episodes = {}, {}
    # three cours: eps 1-11 (2023), 12-24 (2024), 25-35 (2026)
    for episode in range(1, 12):
        titles[episode] = f"A{episode}"
        episodes[episode] = {"air_date": f"2023-04-{episode:02d}"}
    for episode in range(12, 25):
        titles[episode] = f"B{episode}"
        episodes[episode] = {"air_date": f"2024-07-{episode - 11:02d}"}
    for episode in range(25, 36):
        titles[episode] = f"C{episode}"
        episodes[episode] = {"air_date": f"2026-01-{episode - 24:02d}"}
    return {"count": 35, "titles": titles, "episodes": episodes, "posters": {}}


def test_air_date_clusters_split_on_gaps():
    clusters = _air_date_clusters(_season_data())
    assert [len(c) for c in clusters] == [11, 13, 11]
    assert clusters[2][0] == 25


def test_folder_season_maps_to_nth_cluster():
    tmdb_seasons = {1: _season_data()}
    table = EpisodeAssignmentTable()
    data = _season_data()
    for episode, title in data["titles"].items():
        table.add_slot(
            EpisodeSlot(
                season=1,
                episode=episode,
                title=title,
                air_date=data["episodes"][episode]["air_date"],
            )
        )
    entries = []
    for episode in range(1, 12):
        entry = table.add_file(
            Path(f"Oshi no Ko (2023) S03E{episode:02d}.mkv"),
            parsed_episodes=(episode,),
            raw_title=None,
            is_season_relative=True,
            season_hint=3,
            folder_season=3,
        )
        table.mark_unassigned(entry.file_id, REASON_NOT_IN_SEASON)
        entries.append(entry)
    apply_air_date_cluster_mapping(table, tmdb_seasons)
    first = table.assignment_for(entries[0].file_id)
    assert first is not None
    assert first.season == 1 and first.episodes == (25,)
    assert first.confidence == CONF_TITLE_WINS_INEXACT
    assert "air-date-cluster" in first.evidence
    last = table.assignment_for(entries[10].file_id)
    assert last.episodes == (35,)
