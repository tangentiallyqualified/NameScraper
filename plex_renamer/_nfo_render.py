"""Render Kodi-convention NFO XML from cached TMDB payloads.

Pure functions — no I/O, no network. Inputs are the raw cached payloads
from TMDBClient.get_tv_details()/get_movie_details() and the per-episode
dicts produced by _tmdb_metadata_builder.build_season_payload().

Missing fields are omitted entirely (never written empty) — Jellyfin
treats absent and empty elements differently.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

_DECLARATION = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
_MAX_ACTORS = 15


def _child(parent: ET.Element, tag: str, value) -> None:
    if value is None:
        return
    text = str(value).strip()
    if not text:
        return
    ET.SubElement(parent, tag).text = text


def _rating(parent: ET.Element, vote_average, vote_count) -> None:
    if not vote_average:
        return
    ratings = ET.SubElement(parent, "ratings")
    rating = ET.SubElement(
        ratings, "rating", {"name": "tmdb", "max": "10", "default": "true"})
    _child(rating, "value", f"{float(vote_average):.1f}")
    if vote_count:
        _child(rating, "votes", int(vote_count))


def _uniqueid(parent: ET.Element, tmdb_id) -> None:
    if not tmdb_id:
        return
    uid = ET.SubElement(parent, "uniqueid", {"type": "tmdb", "default": "true"})
    uid.text = str(tmdb_id)


def _actors(parent: ET.Element, cast: list[dict]) -> None:
    for fallback_order, member in enumerate(cast[:_MAX_ACTORS]):
        name = (member.get("name") or "").strip()
        if not name:
            continue
        actor = ET.SubElement(parent, "actor")
        _child(actor, "name", name)
        _child(actor, "role", member.get("character"))
        _child(actor, "order", member.get("order", fallback_order))


def _year_from(date_text) -> str | None:
    text = str(date_text or "")
    return text[:4] if len(text) >= 4 else None


def _serialize(root: ET.Element) -> str:
    ET.indent(root)
    return ET.tostring(root, encoding="unicode") + "\n"


def render_tvshow_nfo(details: dict) -> str:
    root = ET.Element("tvshow")
    _child(root, "title", details.get("name"))
    _child(root, "plot", details.get("overview"))
    premiered = details.get("first_air_date")
    _child(root, "premiered", premiered)
    _child(root, "year", _year_from(premiered))
    for genre in details.get("genres") or []:
        _child(root, "genre", genre.get("name"))
    for network in details.get("networks") or []:
        _child(root, "studio", network.get("name"))
    _child(root, "status", details.get("status"))
    run_times = details.get("episode_run_time") or []
    if run_times:
        _child(root, "runtime", run_times[0])
    _rating(root, details.get("vote_average"), details.get("vote_count"))
    _uniqueid(root, details.get("id"))
    _actors(root, (details.get("credits") or {}).get("cast") or [])
    return _DECLARATION + _serialize(root)


def render_movie_nfo(details: dict) -> str:
    root = ET.Element("movie")
    _child(root, "title", details.get("title"))
    _child(root, "originaltitle", details.get("original_title"))
    release = details.get("release_date")
    _child(root, "year", _year_from(release))
    _child(root, "plot", details.get("overview"))
    _child(root, "tagline", details.get("tagline"))
    _child(root, "runtime", details.get("runtime"))
    _child(root, "premiered", release)
    for genre in details.get("genres") or []:
        _child(root, "genre", genre.get("name"))
    for company in details.get("production_companies") or []:
        _child(root, "studio", company.get("name"))
    _rating(root, details.get("vote_average"), details.get("vote_count"))
    _uniqueid(root, details.get("id"))
    _actors(root, (details.get("credits") or {}).get("cast") or [])
    return _DECLARATION + _serialize(root)


def render_episode_nfo(blocks: list[dict]) -> str:
    """One <episodedetails> root per block, concatenated after a single
    declaration — the Kodi multi-episode file convention (deliberately
    multi-root; Kodi and Jellyfin both parse it)."""
    parts: list[str] = []
    for block in blocks:
        meta = block.get("meta") or {}
        root = ET.Element("episodedetails")
        _child(root, "title", meta.get("name"))
        _child(root, "season", block["season"])
        _child(root, "episode", block["episode"])
        _child(root, "plot", meta.get("overview"))
        _child(root, "aired", meta.get("air_date"))
        _child(root, "runtime", meta.get("runtime"))
        _rating(root, meta.get("vote_average"), meta.get("vote_count"))
        for director in meta.get("directors") or []:
            _child(root, "director", director)
        for writer in meta.get("writers") or []:
            _child(root, "credits", writer)
        guest_cast = [
            {"name": g.get("name"), "character": g.get("character"),
             "order": order}
            for order, g in enumerate(meta.get("guest_stars") or [])
        ]
        _actors(root, guest_cast)
        parts.append(_serialize(root))
    return _DECLARATION + "".join(parts)
