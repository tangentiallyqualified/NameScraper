"""RC48: acronym <-> expansion equivalence in title matching (ST:TNG).

'Stardate Revisited The Origin of Star Trek TNG Part 1 Inception' must
match TMDB 'Stardate Revisited: The Origin of Star Trek: The Next
Generation - Part 1: Inception' — a token equal to the initials of a
consecutive token run on the other side counts as equal; everything else
must match exactly.
"""
from plex_renamer.engine._episode_resolution import (
    match_title_in_titles,
    resolve_file,
)

TNG_SPECIALS = {
    1: "Energized! Taking Star Trek: The Next Generation to the Next Level",
    2: "Stardate Revisited: The Origin of Star Trek: The Next Generation - Part 1: Inception",
    3: "Stardate Revisited: The Origin of Star Trek: The Next Generation - Part 2: Launch",
    4: "Stardate Revisited: The Origin of Star Trek: The Next Generation - Part 3: The Continuing Mission",
}


def test_acronym_title_matches_expanded_tmdb_title():
    match = match_title_in_titles(
        "Stardate Revisited The Origin of Star Trek TNG Part 1 Inception",
        TNG_SPECIALS,
    )
    assert match is not None
    assert match.episode == 2
    assert match.strength >= 0.85


def test_acronym_title_resolves_special_at_auto_accept():
    resolution = resolve_file(
        parsed_episodes=(),
        raw_title="Energized Taking Star Trek TNG to the Next Level",
        is_season_relative=False,
        season_titles=TNG_SPECIALS,
        season=0,
    )
    assert resolution.episodes == (1,)
    assert resolution.confidence >= 0.85


def test_wrong_acronym_does_not_match():
    match = match_title_in_titles(
        "Stardate Revisited The Origin of Star Trek DSN Part 1 Inception",
        {2: TNG_SPECIALS[2]},
    )
    assert match is None or match.strength < 0.9


def test_each_stardate_part_matches_its_own_slot():
    match = match_title_in_titles(
        "Stardate Revisited The Origin of Star Trek TNG Part 3 The Continuing Mission",
        TNG_SPECIALS,
    )
    assert match is not None
    assert match.episode == 4
