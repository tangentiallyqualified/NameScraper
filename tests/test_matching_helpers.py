# pyright: strict, reportPrivateUsage=false, reportUnknownVariableType=false

from plex_renamer.engine._tv_scanner_consolidated import _contiguous_run
from plex_renamer.engine.matching import pick_alternate_matches, score_results
from plex_renamer.metadata_types import MediaInfo


def test_contiguous_run_includes_every_available_consecutive_episode() -> None:
    season_titles = {1: "Pilot", 2: "Second", 3: "Third"}

    assert _contiguous_run([1, 2, 3], season_titles) == [1, 2, 3]
    assert _contiguous_run([1, 3], season_titles) == [1]


def test_pick_alternate_matches_returns_all_results_below_limit() -> None:
    first: MediaInfo = {"id": 1, "title": "First"}
    second: MediaInfo = {"id": 2, "title": "Second"}

    assert pick_alternate_matches([(first, 0.9), (second, 0.8)], selected_id=None, limit=3) == [
        first,
        second,
    ]
    assert pick_alternate_matches([(first, 0.9), (second, 0.8)], selected_id=None, limit=1) == [
        first
    ]


def test_score_results_treats_non_string_title_as_empty() -> None:
    result: MediaInfo = {"id": 1, "title": 404, "year": "2024"}

    assert score_results([result], "Expected Title", "2024") == [(result, 0.3)]
