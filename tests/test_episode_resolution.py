"""Tests for episode parsing extensions and the resolution policy."""

from plex_renamer.parsing import extract_episode


class TestMultiEpisodeRuns:
    def test_three_episode_e_run(self):
        eps, title, rel = extract_episode("Show S01E01E02E03.mkv")
        assert eps == [1, 2, 3]
        assert rel is True

    def test_five_episode_e_run(self):
        eps, _, rel = extract_episode("Show S01E01E02E03E04E05.mkv")
        assert eps == [1, 2, 3, 4, 5]
        assert rel is True

    def test_sxx_exx_dash_range(self):
        eps, _, rel = extract_episode("Show S01E01-E04.mkv")
        assert eps == [1, 2, 3, 4]
        assert rel is True

    def test_sxx_exx_dash_range_bare_end(self):
        eps, _, rel = extract_episode("Show S01E01-04.mkv")
        assert eps == [1, 2, 3, 4]
        assert rel is True

    def test_xx_format_range(self):
        eps, _, rel = extract_episode("Show 1x01-1x04.mkv")
        assert eps == [1, 2, 3, 4]
        assert rel is True

    def test_range_span_cap_rejected(self):
        # Span > 12 is a parse artifact, not a real run: keep endpoints only.
        eps, _, _ = extract_episode("Show S01E01-E80.mkv")
        assert eps == [1, 80]

    def test_two_episode_format_unchanged(self):
        eps, title, rel = extract_episode("Show S01E01E02 - Pilot.mkv")
        assert eps == [1, 2]
        assert rel is True

    def test_single_episode_with_title_unchanged(self):
        eps, title, rel = extract_episode("Show S02E05 - The One.mkv")
        assert eps == [5]
        assert title == "The One"
        assert rel is True

    def test_resolution_number_not_an_episode(self):
        eps, _, _ = extract_episode("Show S01E01 1080p.mkv")
        assert eps == [1]
