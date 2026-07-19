"""RC20(1)/RC24(a)/RC16(c): notation variants must normalize identically."""

from plex_renamer._parsing_names import normalize_for_specials_spaced
from plex_renamer.parsing import normalize_for_match, normalize_for_specials


def test_ampersand_folds_to_and():
    assert normalize_for_specials("Love & Monsters") == normalize_for_specials("Love and Monsters")
    assert normalize_for_specials("Dagski & Norb") == normalize_for_specials("Dagski and Norb")


def test_superscript_digits_fold():
    assert normalize_for_specials("H²-Whoa!") == normalize_for_specials("H-2 Whoa")


def test_contraction_and_number_sign_fold():
    assert normalize_for_specials("I Am Not an Animal, I'm Scientist #1") == normalize_for_specials(
        "I'm Not an Animal... I'm Scientist No. 1"
    )


def test_apostrophe_folds_in_match_normalization():
    assert normalize_for_match("Hell's Paradise") == "hells paradise"
    assert normalize_for_match("Hells Paradise") == "hells paradise"


def test_spaced_form_keeps_tokens():
    assert normalize_for_specials_spaced("Tokyo Colony No. 1 (3)") == "tokyo colony number 1 3"
