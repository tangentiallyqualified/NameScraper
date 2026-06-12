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

    # --- keep-working: spaced dash WITH E prefix is still a range ---
    def test_sxx_exx_spaced_dash_e_range(self):
        eps, _, rel = extract_episode("Show S01E01 - E04.mkv")
        assert eps == [1, 2, 3, 4]
        assert rel is True


class TestRangeFalsePositives:
    """Regression tests: digit-leading titles must NOT be parsed as range ends."""

    def test_digit_leading_title_12_angry_men(self):
        eps, title, rel = extract_episode("Show S01E01 - 12 Angry Men.mkv")
        assert eps == [1]
        assert title == "12 Angry Men"
        assert rel is True

    def test_digit_leading_title_2_broke_girls(self):
        eps, title, rel = extract_episode("Show S01E01 - 2 Broke Girls.mkv")
        assert eps == [1]
        assert title == "2 Broke Girls"
        assert rel is True

    def test_digit_leading_title_7_minutes(self):
        eps, title, rel = extract_episode("Breaking Bad S01E01 - 7 Minutes.mkv")
        assert eps == [1]
        assert title == "7 Minutes"
        assert rel is True

    def test_digit_leading_title_23rd_psalm(self):
        eps, title, rel = extract_episode("Lost S02E03 - 23rd Psalm.mkv")
        assert eps == [3]
        assert title == "23rd Psalm"
        assert rel is True

    def test_resolution_720p_not_range(self):
        eps, _, _ = extract_episode("Show S01E01-720p.mkv")
        assert eps == [1]

    def test_nxnn_digit_leading_title_9_lives(self):
        eps, title, rel = extract_episode("Show 3x07 - 9 Lives.mkv")
        assert eps == [7]
        assert title == "9 Lives"
        assert rel is True

    # --- keep-working: ranges that must still parse correctly ---
    def test_sxx_exx_no_space_e_range_still_works(self):
        eps, _, _ = extract_episode("Show S01E01-E04.mkv")
        assert eps == [1, 2, 3, 4]

    def test_sxx_exx_no_space_bare_range_still_works(self):
        eps, _, _ = extract_episode("Show S01E01-04.mkv")
        assert eps == [1, 2, 3, 4]

    def test_sxx_exx_spaced_e_range_still_works(self):
        eps, _, _ = extract_episode("Show S01E01 - E04.mkv")
        assert eps == [1, 2, 3, 4]

    def test_xx_format_range_still_works(self):
        eps, _, _ = extract_episode("Show 1x01-1x04.mkv")
        assert eps == [1, 2, 3, 4]

    def test_range_span_cap_still_works(self):
        eps, _, _ = extract_episode("Show S01E01-E80.mkv")
        assert eps == [1, 80]
