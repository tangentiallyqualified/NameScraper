"""Golden tests for the Matroska global-tags renderer (pure)."""

import xml.etree.ElementTree as ET

from plex_renamer._mkv_tags_render import (
    render_episode_tags,
    render_movie_tags,
)

MOVIE_DETAILS = {
    "id": 438631,
    "title": "Dune & Sons <deluxe>",
    "overview": "Paul Atreides journeys to Arrakis.",
    "release_date": "2021-09-15",
    "genres": [{"name": "Science Fiction"}, {"name": "Adventure"}],
}

SHOW_DETAILS = {
    "id": 42,
    "name": "Show",
    "genres": [{"name": "Drama"}],
}

BLOCKS = [
    {"season": 1, "episode": 1,
     "meta": {"name": "Pilot", "overview": "Walt learns things.",
              "air_date": "2008-01-20"}},
    {"season": 1, "episode": 2, "meta": {"name": "Second"}},
]


def _root(text: str) -> ET.Element:
    assert text.startswith('<?xml version="1.0" encoding="UTF-8"')
    return ET.fromstring(text.split("?>", 1)[1])


def _simples(tag: ET.Element) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for simple in tag.findall("Simple"):
        out.setdefault(simple.findtext("Name"), []).append(
            simple.findtext("String"))
    return out


def _tags_by_target(root: ET.Element) -> dict[str, list[ET.Element]]:
    out: dict[str, list[ET.Element]] = {}
    for tag in root.findall("Tag"):
        ttv = tag.findtext("Targets/TargetTypeValue")
        out.setdefault(ttv, []).append(tag)
    return out


def test_movie_tags_fields_and_escaping():
    root = _root(render_movie_tags(MOVIE_DETAILS))
    assert root.tag == "Tags"
    by_target = _tags_by_target(root)
    assert set(by_target) == {"50"}
    simples = _simples(by_target["50"][0])
    assert simples["TITLE"] == ["Dune & Sons <deluxe>"]
    assert simples["DATE_RELEASED"] == ["2021"]
    assert simples["SYNOPSIS"] == ["Paul Atreides journeys to Arrakis."]
    assert simples["GENRE"] == ["Science Fiction", "Adventure"]


def test_movie_tags_omit_missing_fields():
    root = _root(render_movie_tags({"title": "Bare"}))
    simples = _simples(root.find("Tag"))
    assert simples == {"TITLE": ["Bare"]}


def test_episode_tags_layered_targets():
    root = _root(render_episode_tags(SHOW_DETAILS, BLOCKS[:1]))
    by_target = _tags_by_target(root)
    assert set(by_target) == {"70", "60", "50"}

    show = _simples(by_target["70"][0])
    assert show["TITLE"] == ["Show"]
    assert show["GENRE"] == ["Drama"]

    season = _simples(by_target["60"][0])
    assert season["PART_NUMBER"] == ["1"]

    episode = _simples(by_target["50"][0])
    assert episode["TITLE"] == ["Pilot"]
    assert episode["PART_NUMBER"] == ["1"]
    assert episode["DATE_RELEASED"] == ["2008-01-20"]
    assert episode["SYNOPSIS"] == ["Walt learns things."]


def test_multi_episode_emits_one_50_tag_per_block():
    root = _root(render_episode_tags(SHOW_DETAILS, BLOCKS))
    by_target = _tags_by_target(root)
    assert len(by_target["50"]) == 2
    assert len(by_target["60"]) == 1        # one season across both blocks
    first, second = (_simples(t) for t in by_target["50"])
    assert first["PART_NUMBER"] == ["1"]
    assert second["PART_NUMBER"] == ["2"]
    assert second["TITLE"] == ["Second"]
    assert "SYNOPSIS" not in second         # missing meta fields omitted


def test_malformed_release_date_omits_date_tag():
    # Players compose "TITLE (DATE_RELEASED)" for display; a partial date
    # fragment would be worse than no date at all.
    root = _root(render_movie_tags({"title": "Bare", "release_date": "20"}))
    tag = root.find("Tag")
    assert tag is not None
    simples = _simples(tag)
    assert "DATE_RELEASED" not in simples


def test_unicode_survives():
    root = _root(render_movie_tags({"title": "Yuru Camp△ \U0001f3d5"}))
    assert _simples(root.find("Tag"))["TITLE"] == ["Yuru Camp△ \U0001f3d5"]


def test_empty_show_details_drops_childless_70_tag():
    # A show_details of {} must not emit a childless 70-level Tag —
    # MKVToolNix's tags-XML validator rejects <Tag> with no <Simple>
    # children, which would abort the whole propedit/mux call.
    root = _root(render_episode_tags({}, BLOCKS[:1]))
    by_target = _tags_by_target(root)
    assert "70" not in by_target
    assert set(by_target) == {"60", "50"}


def test_empty_blocks_leaves_only_70_tag():
    root = _root(render_episode_tags(SHOW_DETAILS, []))
    by_target = _tags_by_target(root)
    assert set(by_target) == {"70"}


def test_empty_movie_details_emits_no_tag_elements():
    root = _root(render_movie_tags({}))
    assert root.findall("Tag") == []
