"""RC16: year-less folders must reach auto-accept on exact titles."""
from plex_renamer.engine.matching import _tv_episode_evidence_adjustment, score_results


def test_exact_title_without_year_scores_full():
    results = [{"id": 1, "title": "Jujutsu Kaisen", "year": "2020"}]
    scored = score_results(results, "Jujutsu Kaisen", None)
    assert scored[0][1] >= 1.0  # 1.0 title + 0.15 exact bonus, no year forfeit


def test_year_weighting_unchanged_when_hint_present():
    results = [{"id": 1, "title": "Jujutsu Kaisen", "year": "2020"}]
    scored = score_results(results, "Jujutsu Kaisen", "2020")
    assert scored[0][1] >= 1.0


class _FakeTMDB:
    def __init__(self, seasons):
        self._seasons = seasons

    def get_season_map(self, show_id):
        return self._seasons, {}


class _Evidence:
    def __init__(self, season_num, episode_num, raw_title):
        self.season_num = season_num
        self.episode_num = episode_num
        self.raw_title = raw_title


def test_missing_season_titles_match_across_all_seasons():
    seasons = {1: {"count": 2, "titles": {1: "Execution", 2: "Sendai Colony"}}}
    tmdb = _FakeTMDB(seasons)
    evidence = [
        _Evidence(3, 1, "Execution"),
        _Evidence(3, 2, "Sendai Colony"),
    ]
    adjustment = _tv_episode_evidence_adjustment(tmdb, 1, evidence)
    # coverage penalty (-0.12) must be outweighed by the title boost (+0.24)
    assert adjustment > 0.0
