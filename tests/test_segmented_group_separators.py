"""RC41: merged segment groups must match titles across their separator.

'Goodfeathers & The Beginning' is one TMDB segment title
('Goodfeathers: The Beginning') — the '&' between the atoms folds to the
word 'and' when the group is matched by raw span, so the group could
never equal the slot title and the whole decomposition failed
(Animaniacs S01E04).
"""
from plex_renamer.engine._episode_resolution import (
    match_segmented_title_run,
    resolve_file,
)

ANIMANIACS_S1 = {
    4: "Yakko's World",
    10: "Hooked On a Ceiling",
    11: "Goodfeathers: The Beginning",
    12: "Taming of the Screwy",
}


def test_group_spanning_separator_matches_colon_title():
    seg = match_segmented_title_run(
        "Hooked on a Ceiling, Goodfeathers & The Beginning",
        ANIMANIACS_S1,
        2,
    )
    assert seg == ((10, 11), True)


def test_disc_grouped_file_decomposes_across_separator():
    resolution = resolve_file(
        parsed_episodes=(4,),
        raw_title="Hooked on a Ceiling, Goodfeathers & The Beginning",
        is_season_relative=True,
        season_titles=ANIMANIACS_S1,
        season=1,
        season_hint=1,
    )
    assert resolution.episodes == (10, 11)
    assert resolution.confidence >= 0.85
    assert "title-segmented" in resolution.evidence


def test_titles_containing_and_still_match_by_raw_span():
    titles = {7: "The Warners and the Beanstalk", 8: "Frontier Slappy"}
    seg = match_segmented_title_run(
        "The Warners and the Beanstalk & Frontier Slappy", titles, 2,
    )
    assert seg == ((7, 8), True)
