"""RC38: an episode-count tiebreak that clearly discriminates breaks the tie.

Three TMDB shows are literally named 'Limitless'; the CBS one has exactly
the folder's episode count, yet the show was still flagged tie -> review.
"""

from plex_renamer.engine._batch_tv_match_policy import episode_count_tiebreak


class _FakeTMDB:
    def __init__(self, details: dict):
        self._details = details

    def get_tv_details(self, show_id: int) -> dict | None:
        return self._details.get(show_id)


LIMITLESS_RESULTS = [
    ({"id": 62687, "name": "Limitless", "year": "2015"}, 1.0),
    ({"id": 215021, "name": "Limitless", "year": "2019"}, 1.0),
    ({"id": 313103, "name": "Limitless", "year": "2026"}, 1.0),
]


def test_unique_episode_count_discriminates():
    tmdb = _FakeTMDB(
        {
            62687: {"number_of_episodes": 22, "first_air_date": "2015-09-22"},
            215021: {"number_of_episodes": 8, "first_air_date": "2019-01-01"},
            313103: {"number_of_episodes": 6, "first_air_date": "2026-01-01"},
        }
    )
    best, _score, discriminated = episode_count_tiebreak(
        tmdb,
        LIMITLESS_RESULTS,
        file_count=22,
    )
    assert best["id"] == 62687
    assert discriminated is True


def test_equal_counts_do_not_discriminate():
    tmdb = _FakeTMDB(
        {
            62687: {"number_of_episodes": 22, "first_air_date": "2015-09-22"},
            215021: {"number_of_episodes": 22, "first_air_date": "2019-01-01"},
            313103: {"number_of_episodes": 6, "first_air_date": "2026-01-01"},
        }
    )
    _best, _score, discriminated = episode_count_tiebreak(
        tmdb,
        LIMITLESS_RESULTS,
        file_count=22,
    )
    assert discriminated is False


def test_single_contender_does_not_discriminate():
    tmdb = _FakeTMDB(
        {
            62687: {"number_of_episodes": 22, "first_air_date": "2015-09-22"},
        }
    )
    best, _score, discriminated = episode_count_tiebreak(
        tmdb,
        LIMITLESS_RESULTS[:1],
        file_count=22,
    )
    assert best["id"] == 62687
    assert discriminated is False
