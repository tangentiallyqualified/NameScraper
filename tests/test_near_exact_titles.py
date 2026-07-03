"""RC46: unique near-exact title matches must auto-accept, not park at 0.70.

Rawhide S5 is systematically off-by-one; most files re-anchor via exact
title matches at 0.92 but titles differing by a typo-level edit ("Buryin'
Man"/"Buryin' Men", "Commanchero"/"Comanchero") or by stopwords only
("Incident At The Trail's End"/"Incident of the Trail's End") fell to the
fuzzy tier and parked at CONF_TITLE_WINS_INEXACT=0.70 (below the 0.85
auto-accept). A "the"-only difference ("Incident of Midnight Cave" vs
"Incident of the Midnight Cave") matched no tier at all.
"""
from plex_renamer.engine._episode_resolution import (
    match_title_in_titles,
    resolve_file,
)

RAWHIDE_S5 = {
    13: "Incident of the Buryin' Men",   # file says E12/'Buryin' Man'
    14: "Incident of the Trail's End",   # file says E13/'At The Trail's End'
    15: "Incident at Spider Rock",
    16: "Incident of the Comanchero",    # file says E15/'Commanchero'
}


def test_single_char_typo_title_overrides_number_at_auto_accept():
    resolution = resolve_file(
        parsed_episodes=(12,),
        raw_title="Incident Of The Buryin' Man",
        is_season_relative=True,
        season_titles=RAWHIDE_S5,
        season=5,
        season_hint=5,
    )
    assert resolution.episodes == (13,)
    assert "title-strong" in resolution.evidence
    assert resolution.confidence >= 0.85


def test_stopword_only_difference_overrides_number_at_auto_accept():
    resolution = resolve_file(
        parsed_episodes=(13,),
        raw_title="Incident At The Trail's End",
        is_season_relative=True,
        season_titles=RAWHIDE_S5,
        season=5,
        season_hint=5,
    )
    assert resolution.episodes == (14,)
    assert "title-strong" in resolution.evidence
    assert resolution.confidence >= 0.85


def test_extra_spelling_letter_overrides_number_at_auto_accept():
    resolution = resolve_file(
        parsed_episodes=(15,),
        raw_title="Incident Of The Commanchero",
        is_season_relative=True,
        season_titles=RAWHIDE_S5,
        season=5,
        season_hint=5,
    )
    assert resolution.episodes == (16,)
    assert "title-strong" in resolution.evidence
    assert resolution.confidence >= 0.85


def test_the_only_difference_agrees_with_number():
    titles = {15: "Incident of the Blue Fire", 16: "Incident of the Midnight Cave"}
    resolution = resolve_file(
        parsed_episodes=(16,),
        raw_title="Incident of Midnight Cave",
        is_season_relative=True,
        season_titles=titles,
        season=6,
        season_hint=6,
    )
    assert resolution.episodes == (16,)
    assert "title-agree" in resolution.evidence
    assert resolution.confidence >= 0.85


def test_ambiguous_near_exact_falls_through_to_part_matching():
    # Two titles within edit distance of the input: near-exact must not
    # claim either; the part-number tier still resolves it.
    titles = {7: "Homecoming (1)", 8: "Homecoming (2)"}
    match = match_title_in_titles("Homecoming 2", titles)
    assert match is not None
    assert match.episode == 8


def test_genuinely_different_titles_stay_unmatched():
    titles = {3: "Incident of the Silent Web"}
    # 'Silver' vs 'Silent' is a 3-edit content difference — not near-exact.
    match = match_title_in_titles("Incident of the Silver Web", titles)
    assert match is None or match.episode != 3 or match.strength < 0.9
