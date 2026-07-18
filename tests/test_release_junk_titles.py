"""RC17: release junk must not survive in extracted episode titles."""

from plex_renamer._parsing_titles import strip_release_junk_title
from plex_renamer.parsing import extract_episode


def test_strip_helper_truncates_at_first_noise_token():
    assert (
        strip_release_junk_title("Execution 1080p CR WEB-DL DUAL AAC2 0 H 264-VARYG") == "Execution"
    )
    assert (
        strip_release_junk_title("De-Zanitized, The Monkey Song & Nighty-Night Toon REPACK")
        == "De-Zanitized, The Monkey Song & Nighty-Night Toon"
    )
    assert strip_release_junk_title("1080p x265") is None
    assert strip_release_junk_title(None) is None
    assert strip_release_junk_title("Armed and Dangerous") == "Armed and Dangerous"


def test_sxe_title_strips_release_junk():
    eps, title, rel = extract_episode(
        "Jujutsu.Kaisen.S03E01.Execution.1080p.CR.WEB-DL.DUAL.AAC2.0.H.264-VARYG.mkv"
    )
    assert eps == [1]
    assert rel is True
    assert title == "Execution"


def test_repack_title_stripped_for_segmented_run():
    _, title, _ = extract_episode(
        "Animaniacs.1993.S01E01.De-Zanitized,.The.Monkey.Song.&.Nighty-Night.Toon.REPACK.1080p.mkv"
    )
    assert title == "De-Zanitized, The Monkey Song & Nighty-Night Toon"


def test_part_title_survives_junk_strip():
    _, title, _ = extract_episode(
        "Archer.2009.S00E04.Heart.of.Archness.Part.1.1080p.NF.WEB-DL.DDP5.1.AV1-DBMS.mkv"
    )
    assert title == "Heart of Archness Part 1"


def test_clean_title_untouched():
    eps, title, rel = extract_episode("Show - S01E05 - Armed and Dangerous.mkv")
    assert eps == [5] and title == "Armed and Dangerous"
