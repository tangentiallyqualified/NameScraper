"""RC27: E##.Title / ##.Title filenames must keep their title evidence."""
from plex_renamer.parsing import extract_episode


def test_e_prefix_dot_title():
    eps, title, rel = extract_episode("E01.He's Not the Messiah, He's a DJ.mkv")
    assert eps == [1]
    assert title == "He's Not the Messiah, He's a DJ"
    assert rel is False


def test_e_prefix_reno_pilot():
    eps, title, _ = extract_episode("E01.The Pilot.mkv")
    assert eps == [1] and title == "The Pilot"


def test_bare_number_dot_no_space():
    eps, title, _ = extract_episode("01.The Pilot.mkv")
    assert eps == [1] and title == "The Pilot"


def test_episode_word_space_title():
    eps, title, _ = extract_episode("Episode 5 The Great Escape.mkv")
    assert eps == [5] and title == "The Great Escape"


def test_no_title_still_none():
    eps, title, _ = extract_episode("Episode 5.mkv")
    assert eps == [5] and title is None


def test_sxe_still_wins():
    eps, title, rel = extract_episode("Show S02E03 Some Title.mkv")
    assert eps == [3] and rel is True
