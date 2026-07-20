"""ID-tag parsing: {tmdb-123}/{tvdb-123} and bracket/case/`id` variants."""

import pytest

from plex_renamer._parsing_id_tags import (
    extract_provider_id_tag,
    strip_provider_id_tags,
)
from plex_renamer.parsing import clean_folder_name


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Breaking Bad (2008) {tmdb-1396}", ("tmdb", 1396)),
        ("Breaking Bad (2008) {tvdb-81189}", ("tvdb", 81189)),
        ("Breaking Bad [tmdb-1396]", ("tmdb", 1396)),
        ("Breaking Bad [tvdbid-81189]", ("tvdb", 81189)),
        ("Breaking Bad {TMDB-1396}", ("tmdb", 1396)),
        ("Breaking Bad {tvdb=81189}", ("tvdb", 81189)),
        ("Breaking Bad {tvdb 81189}", ("tvdb", 81189)),
        ("Breaking Bad (2008)", None),
        ("Breaking Bad {imdb-tt0903747}", None),
        ("Breaking Bad {tvdb-}", None),
    ],
)
def test_extract_provider_id_tag(name: str, expected: tuple[str, int] | None) -> None:
    assert extract_provider_id_tag(name) == expected


def test_first_tag_wins_when_both_present() -> None:
    assert extract_provider_id_tag("Show {tmdb-1} {tvdb-2}") == ("tmdb", 1)


def test_strip_provider_id_tags() -> None:
    assert strip_provider_id_tags("Breaking Bad {tvdb-81189} (2008)") == "Breaking Bad (2008)"
    assert strip_provider_id_tags("Show [tmdbid-55]") == "Show"
    assert strip_provider_id_tags("No tags here") == "No tags here"


def test_clean_folder_name_strips_id_tags() -> None:
    cleaned = clean_folder_name("Breaking Bad (2008) {tvdb-81189}", include_year=False)
    assert "81189" not in cleaned
    assert "tvdb" not in cleaned.lower()
