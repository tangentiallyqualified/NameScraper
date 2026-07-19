"""Render Matroska global-tags XML from cached TMDB payloads.

Pure functions — no I/O, no network (spec: mkv-embedded-metadata).
Inputs are the raw cached payloads from TMDBClient.get_movie_details()/
get_tv_details() and the same episode block dicts _nfo_render consumes.

Target levels follow the Matroska tagging spec: 70 = collection (show),
60 = season, 50 = movie/episode. Missing fields are omitted entirely,
never written empty.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

_DECLARATION = '<?xml version="1.0" encoding="UTF-8"?>\n'


def _simple(tag_el: ET.Element, name: str, value) -> None:
    if value is None:
        return
    text = str(value).strip()
    if not text:
        return
    simple = ET.SubElement(tag_el, "Simple")
    ET.SubElement(simple, "Name").text = name
    ET.SubElement(simple, "String").text = text


def _tag(root: ET.Element, target_type_value: int) -> ET.Element:
    tag = ET.SubElement(root, "Tag")
    targets = ET.SubElement(tag, "Targets")
    ET.SubElement(targets, "TargetTypeValue").text = str(target_type_value)
    return tag


def _drop_childless_tags(root: ET.Element) -> None:
    # MKVToolNix's tags-XML validator rejects a <Tag> with no <Simple>
    # child ("<Tag> is missing the <Simple> child."), aborting the whole
    # mkvpropedit/mkvmerge call. A details dict with no renderable
    # fields (or an empty {}) must not produce one.
    for tag in list(root.findall("Tag")):
        if tag.find("Simple") is None:
            root.remove(tag)


def _serialize(root: ET.Element) -> str:
    _drop_childless_tags(root)
    ET.indent(root)
    return _DECLARATION + ET.tostring(root, encoding="unicode") + "\n"


def _release_year(date_text) -> str | None:
    """Year-only DATE_RELEASED (reduced-precision ISO 8601, allowed by the
    Matroska spec). Players like MPC-BE compose their display title as
    "TITLE (DATE_RELEASED)", so a full date renders as
    "Movie (2003-06-05)" instead of "Movie (2003)". The full release
    date still lands in the NFO <premiered> element."""
    text = str(date_text or "")
    return text[:4] if len(text) >= 4 else None


def render_movie_tags(details: dict) -> str:
    root = ET.Element("Tags")
    tag = _tag(root, 50)
    _simple(tag, "TITLE", details.get("title"))
    _simple(tag, "DATE_RELEASED", _release_year(details.get("release_date")))
    _simple(tag, "SYNOPSIS", details.get("overview"))
    for genre in details.get("genres") or []:
        _simple(tag, "GENRE", genre.get("name"))
    return _serialize(root)


def render_episode_tags(show_details: dict, blocks: list[dict]) -> str:
    """Layered 70 (show) / 60 (season) / 50 (per-episode) tags.

    Multi-episode files get one 50-level tag per spanned episode,
    mirroring the NFO multi-block convention.
    """
    show_details = show_details or {}
    root = ET.Element("Tags")

    show = _tag(root, 70)
    _simple(show, "TITLE", show_details.get("name"))
    for genre in show_details.get("genres") or []:
        _simple(show, "GENRE", genre.get("name"))

    for season in sorted({b["season"] for b in blocks}):
        _simple(_tag(root, 60), "PART_NUMBER", season)

    for block in blocks:
        meta = block.get("meta") or {}
        episode = _tag(root, 50)
        _simple(episode, "TITLE", meta.get("name"))
        _simple(episode, "PART_NUMBER", block.get("episode"))
        _simple(episode, "DATE_RELEASED", meta.get("air_date"))
        _simple(episode, "SYNOPSIS", meta.get("overview"))

    return _serialize(root)
