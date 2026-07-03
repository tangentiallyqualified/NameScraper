"""RC43: an atom that is a FRAGMENT of the matched title must not anchor.

'Danger Island Comparative Wickedness of Civilized and Unenlightened
Peoples' splits at its interior 'and'; the trailing atom 'Unenlightened
Peoples' is merely a fragment of E07's title, yet it anchored a run and
invented E06 from the branding prefix — episodes (6,7) at 0.70, which then
lost the E07 conflict to the clean duplicate copy.
"""
from plex_renamer.engine._episode_resolution import resolve_file

ARCHER_S9 = {
    5: "Strange Doings in the Taboo Groves",
    6: "Some Remarks on Cannibalism",
    7: "Comparative Wickedness of Civilized and Unenlightened Peoples",
    8: "A Discovery",
}


def test_branded_title_with_interior_and_agrees_with_number():
    resolution = resolve_file(
        parsed_episodes=(7,),
        raw_title=(
            "Danger Island Comparative Wickedness of Civilized"
            " and Unenlightened Peoples"
        ),
        is_season_relative=True,
        season_titles=ARCHER_S9,
        season=9,
        season_hint=9,
    )
    assert resolution.episodes == (7,)
    assert "title-agree" in resolution.evidence
    assert resolution.confidence >= 0.85
