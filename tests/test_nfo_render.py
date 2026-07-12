"""Golden tests for the Kodi-convention NFO renderer (pure)."""

import xml.etree.ElementTree as ET

from plex_renamer._nfo_render import (
    render_episode_nfo,
    render_movie_nfo,
    render_tvshow_nfo,
)

TV_DETAILS = {
    "id": 1396,
    "name": "Breaking Bad & Sons <deluxe>",
    "overview": "A chemistry teacher turns to crime.",
    "first_air_date": "2008-01-20",
    "genres": [{"id": 18, "name": "Drama"}],
    "networks": [{"name": "AMC"}],
    "status": "Ended",
    "episode_run_time": [47],
    "vote_average": 8.917,
    "vote_count": 12345,
    "credits": {"cast": [
        {"name": "Bryan Cranston", "character": "Walter White", "order": 0},
    ]},
}

EPISODE_META = {
    "name": "Pilot",
    "overview": "Walt learns he has cancer.",
    "air_date": "2008-01-20",
    "vote_average": 8.2,
    "vote_count": 500,
    "runtime": 58,
    "still_path": "/still.jpg",
    "directors": ["Vince Gilligan"],
    "writers": ["Vince Gilligan"],
    "guest_stars": [{"name": "Guest One", "character": "DEA Agent"}],
}

MOVIE_DETAILS = {
    "id": 438631,
    "title": "Dune",
    "original_title": "Dune",
    "overview": "Paul Atreides journeys to Arrakis.",
    "tagline": "Beyond fear, destiny awaits.",
    "release_date": "2021-09-15",
    "runtime": 155,
    "genres": [{"name": "Science Fiction"}],
    "production_companies": [{"name": "Legendary Pictures"}],
    "vote_average": 7.786,
    "vote_count": 9999,
    "credits": {"cast": [{"name": "Timothee Chalamet",
                          "character": "Paul Atreides", "order": 0}]},
}


def test_tvshow_nfo_structure_and_escaping():
    text = render_tvshow_nfo(TV_DETAILS)
    assert text.startswith('<?xml version="1.0" encoding="UTF-8"')
    root = ET.fromstring(text.split("?>", 1)[1])
    assert root.tag == "tvshow"
    assert root.findtext("title") == "Breaking Bad & Sons <deluxe>"
    assert root.findtext("plot") == "A chemistry teacher turns to crime."
    assert root.findtext("premiered") == "2008-01-20"
    assert root.findtext("year") == "2008"
    assert root.findtext("genre") == "Drama"
    assert root.findtext("studio") == "AMC"
    assert root.findtext("status") == "Ended"
    assert root.findtext("runtime") == "47"
    uid = root.find("uniqueid")
    assert uid.attrib == {"type": "tmdb", "default": "true"}
    assert uid.text == "1396"
    rating = root.find("ratings/rating")
    assert rating.findtext("value") == "8.9"
    assert rating.findtext("votes") == "12345"
    actor = root.find("actor")
    assert actor.findtext("name") == "Bryan Cranston"
    assert actor.findtext("role") == "Walter White"


def test_tvshow_nfo_omits_missing_fields():
    text = render_tvshow_nfo({"id": 7, "name": "Bare"})
    root = ET.fromstring(text.split("?>", 1)[1])
    assert root.findtext("title") == "Bare"
    assert root.find("plot") is None
    assert root.find("year") is None
    assert root.find("ratings") is None
    assert root.find("actor") is None       # pre-widening cache: no credits key


def test_episode_nfo_single_block():
    text = render_episode_nfo(
        [{"season": 1, "episode": 1, "meta": EPISODE_META}])
    root = ET.fromstring(text.split("?>", 1)[1])
    assert root.tag == "episodedetails"
    assert root.findtext("title") == "Pilot"
    assert root.findtext("season") == "1"
    assert root.findtext("episode") == "1"
    assert root.findtext("aired") == "2008-01-20"
    assert root.findtext("runtime") == "58"
    assert root.findtext("director") == "Vince Gilligan"
    assert root.findtext("credits") == "Vince Gilligan"
    actor = root.find("actor")
    assert actor.findtext("name") == "Guest One"
    assert actor.findtext("role") == "DEA Agent"


def test_episode_nfo_multi_episode_emits_consecutive_roots():
    text = render_episode_nfo([
        {"season": 1, "episode": 1, "meta": EPISODE_META},
        {"season": 1, "episode": 2, "meta": {"name": "Second"}},
    ])
    assert text.count("<episodedetails>") == 2
    assert text.index("Pilot") < text.index("Second")


def test_movie_nfo_fields():
    text = render_movie_nfo(MOVIE_DETAILS)
    root = ET.fromstring(text.split("?>", 1)[1])
    assert root.tag == "movie"
    assert root.findtext("title") == "Dune"
    assert root.findtext("originaltitle") == "Dune"
    assert root.findtext("year") == "2021"
    assert root.findtext("tagline") == "Beyond fear, destiny awaits."
    assert root.findtext("premiered") == "2021-09-15"
    assert root.findtext("runtime") == "155"
    assert root.findtext("studio") == "Legendary Pictures"
    assert root.find("uniqueid").text == "438631"


def test_unicode_survives():
    text = render_tvshow_nfo({"id": 1, "name": "Yuru Camp△ \U0001f3d5"})
    root = ET.fromstring(text.split("?>", 1)[1])
    assert root.findtext("title") == "Yuru Camp△ \U0001f3d5"
