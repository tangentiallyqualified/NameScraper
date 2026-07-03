"""RC33: substring title matching must respect token boundaries.

'blues' is a compact substring of 'bluesubmarine…' but crosses a token
boundary — every Blue Submarine No. 6 file piled onto S01E01 'Blues' and
died as ambiguous. Conversely 3-char titles ('Sex') could never match at
all because of the key-length floor, even at a clean token boundary.
"""
from plex_renamer.engine._episode_resolution import (
    _has_ambiguous_title_evidence,
    match_title_in_titles,
)

BLUE_SUB = {1: "Blues", 2: "Pilots", 3: "Hearts", 4: "Minasoko"}


def test_show_name_does_not_substring_match_across_tokens():
    assert (
        match_title_in_titles("Blue Submarine No 6 (Toonami Version)", BLUE_SUB)
        is None
    )


def test_promo_files_do_not_match_blues():
    assert (
        match_title_in_titles(
            "Blue Submarine No 6 Toonami Promo (15 seconds)", BLUE_SUB
        )
        is None
    )
    assert not _has_ambiguous_title_evidence(
        "Blue Submarine No 6 Toonami Promo (15 seconds)", BLUE_SUB
    )


OTA_S13 = {1: "Sex", 2: "Drugs", 3: "Music", 4: "Farts"}


def test_short_title_matches_at_token_boundary():
    match = match_title_in_titles("Sex ｜ Off the Air ｜ Adult Swim", OTA_S13)
    assert match is not None
    assert match.episode == 1


def test_longer_sibling_still_matches():
    match = match_title_in_titles("Drugs ｜ Off The Air ｜ Adult Swim", OTA_S13)
    assert match is not None
    assert match.episode == 2


def test_token_aligned_substring_still_matches():
    titles = {10: "Show & Tell - Blossom", 11: "Show & Tell - Buttercup"}
    match = match_title_in_titles("Tell - Blossom", titles)
    assert match is not None
    assert match.episode == 10


def test_key_inside_input_still_matches_when_aligned():
    titles = {37: "Neferkitty", 38: "Curiosity Almost Killed The Cat"}
    match = match_title_in_titles(
        "Neferkitty and Curiousity Almost Killed The Big Weird Cat", titles
    )
    assert match is not None
    assert match.episode == 37
