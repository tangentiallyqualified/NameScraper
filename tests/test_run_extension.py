"""RC20(3): a one-segment title match extends to the whole segment run."""
from plex_renamer.engine._episode_resolution import (
    CONF_TITLE_WINS_INEXACT,
    resolve_file,
)

CATDOG_S3 = {
    36: "Full Moon Fever",
    37: "Neferkitty",
    38: "Curiosity Almost Killed The Cat",  # file typo: 'Curiousity' + extra words
}


def test_two_number_file_extends_from_matched_first_segment():
    resolution = resolve_file(
        parsed_episodes=(37, 38),
        raw_title="Neferkitty and Curiousity Almost Killed The Big Weird Cat",
        is_season_relative=True,
        season_titles=CATDOG_S3,
        season=3,
    )
    assert resolution.episodes == (37, 38)
    assert "run-extended" in resolution.evidence or "title-agree" in resolution.evidence


RUGRATS_S4 = {
    19: "Chuckie Is Rich",
    20: "The Unfair Pair",       # file says 'The Mattress'
    21: "Looking for Jack",
}


def test_single_number_two_atoms_extends_backwards():
    resolution = resolve_file(
        parsed_episodes=(21,),
        raw_title="The Mattress & Looking for Jack",
        is_season_relative=True,
        season_titles=RUGRATS_S4,
        season=4,
    )
    assert resolution.episodes == (20, 21)
    assert resolution.confidence == CONF_TITLE_WINS_INEXACT
    assert "run-extended" in resolution.evidence


def test_no_extension_when_atom_counts_disagree():
    resolution = resolve_file(
        parsed_episodes=(21,),
        raw_title="Looking for Jack",
        is_season_relative=True,
        season_titles=RUGRATS_S4,
        season=4,
    )
    assert resolution.episodes == (21,)
