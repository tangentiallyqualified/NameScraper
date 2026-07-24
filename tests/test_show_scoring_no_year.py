"""RC16: year-less folders must reach auto-accept on exact titles."""

from _provider_fakes import RecordingProvider

from plex_renamer.engine._season_map_validation import SeasonMap
from plex_renamer.engine.matching import _tv_episode_evidence_adjustment, score_results
from plex_renamer.engine.models import DirectEpisodeEvidence


def test_exact_title_without_year_scores_full():
    results = [{"id": 1, "title": "Jujutsu Kaisen", "year": "2020"}]
    scored = score_results(results, "Jujutsu Kaisen", None)
    assert scored[0][1] >= 1.0  # 1.0 title + 0.15 exact bonus, no year forfeit


def test_year_weighting_unchanged_when_hint_present():
    results = [{"id": 1, "title": "Jujutsu Kaisen", "year": "2020"}]
    scored = score_results(results, "Jujutsu Kaisen", "2020")
    assert scored[0][1] >= 1.0


class _FakeTMDB(RecordingProvider):
    def __init__(self, seasons: SeasonMap) -> None:
        super().__init__("tmdb")
        self._seasons: SeasonMap = seasons

    def get_season_map(self, show_id: int) -> tuple[SeasonMap, int]:
        return self._seasons, 0


def test_missing_season_titles_match_across_all_seasons():
    seasons = {1: {"count": 2, "titles": {1: "Execution", 2: "Sendai Colony"}}}
    tmdb = _FakeTMDB(seasons)
    evidence = [
        DirectEpisodeEvidence(3, 1, "Execution"),
        DirectEpisodeEvidence(3, 2, "Sendai Colony"),
    ]
    adjustment = _tv_episode_evidence_adjustment(tmdb, 1, evidence)
    # coverage penalty (-0.12) must be outweighed by the title boost (+0.24)
    assert adjustment > 0.0
