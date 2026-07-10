"""Language normalization: user input and mkvmerge output → ISO 639-2/B."""
from plex_renamer._lang_normalize import normalize_lang, normalize_lang_list


def test_iso639_1_maps_to_2b():
    assert normalize_lang("en") == "eng"
    assert normalize_lang("ja") == "jpn"
    assert normalize_lang("de") == "ger"


def test_region_subtags_stripped():
    assert normalize_lang("en-US") == "eng"
    assert normalize_lang("pt_BR") == "por"


def test_iso639_2t_maps_to_2b():
    # mkvmerge may report terminology codes; matching must use one canon.
    assert normalize_lang("deu") == "ger"
    assert normalize_lang("fra") == "fre"
    assert normalize_lang("zho") == "chi"


def test_three_letter_codes_pass_through():
    assert normalize_lang("eng") == "eng"
    assert normalize_lang("JPN") == "jpn"


def test_und_and_invalid():
    assert normalize_lang("und") == "und"
    assert normalize_lang("") is None
    assert normalize_lang("nonsense-tag") is None
    assert normalize_lang("q1") is None


def test_list_normalization_preserves_order_dedups_drops_invalid():
    assert normalize_lang_list(["en-US", "eng", "xx!", "ja"]) == ["eng", "jpn"]
