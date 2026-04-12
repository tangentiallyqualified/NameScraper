"""Presentation helpers for MediaDetailPanel metadata payloads."""

from __future__ import annotations

from typing import Any

from ...engine import PreviewItem, ScanState
from ._formatting import clamped_percent
from ._image_utils import pil_to_raw


def format_detail_rating(vote_average: float | None, vote_count: int = 0) -> str:
    if vote_average is None:
        return ""
    return f"{vote_average:.1f}/10" + (f" ({vote_count})" if vote_count else "")


def format_detail_runtime(minutes: int | None) -> str:
    if not minutes:
        return ""
    if minutes >= 60:
        hours, remain = divmod(minutes, 60)
        return f"{hours}h {remain}m" if remain else f"{hours}h"
    return f"{minutes}m"


def detail_state_media_type(state: ScanState) -> str:
    media_type = state.media_info.get("_media_type")
    if media_type in {"movie", "tv"}:
        return media_type
    if any(item.media_type == "movie" for item in state.preview_items):
        return "movie"
    return "movie" if state.media_info.get("title") else "tv"


def detail_state_confidence_value(state: ScanState) -> str:
    return f"{clamped_percent(state.confidence)}%"


def build_detail_fallback_rows(
    state: ScanState,
    preview: PreviewItem | None,
    queue_reason: str,
) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    if queue_reason and detail_state_media_type(state) != "movie":
        rows.append(("Queue", queue_reason))
    rows.append(("Confidence", detail_state_confidence_value(state)))
    if preview is not None:
        rows.append(("File", preview.original.name))
        rows.append(("Status", preview.status))
    return rows


def build_detail_payload(
    tmdb: Any,
    state: ScanState,
    preview: PreviewItem | None,
    queue_reason: str,
    target_width: int,
    *,
    show_discovery_info: bool = False,
) -> tuple[dict[str, Any], Any | None]:
    media_type = detail_state_media_type(state)
    details = (
        tmdb.get_movie_details(state.show_id)
        if media_type == "movie"
        else tmdb.get_tv_details(state.show_id)
    ) or {}

    episode_meta = None
    if preview is not None and preview.season is not None and preview.episodes and state.scanner is not None:
        episode_meta = state.scanner.episode_meta.get((preview.season, preview.episodes[0]))

    image = tmdb.fetch_poster(
        state.show_id,
        media_type=media_type,
        target_width=target_width,
    )
    raw_image = pil_to_raw(image) if image is not None else None

    subtitle_parts = []
    if state.media_info.get("year"):
        subtitle_parts.append(str(state.media_info.get("year")))
    if details.get("tagline"):
        subtitle_parts.append(details["tagline"])
    subtitle = " · ".join(part for part in subtitle_parts if part)

    rows: list[tuple[str, str]] = []
    rating = format_detail_rating(details.get("vote_average", 0), details.get("vote_count", 0))
    if rating:
        rows.append(("Rating", rating))
    if media_type == "movie":
        runtime = format_detail_runtime(details.get("runtime"))
        if runtime:
            rows.append(("Runtime", runtime))
        if details.get("release_date"):
            rows.append(("Release", details["release_date"]))
        genres = ", ".join(g.get("name", "") for g in details.get("genres", []) if g.get("name"))
        if genres:
            rows.append(("Genres", genres))
    else:
        if details.get("status"):
            rows.append(("Status", details["status"]))
        networks = ", ".join(n.get("name", "") for n in details.get("networks", []) if n.get("name"))
        if networks:
            rows.append(("Network", networks))
        season_count = details.get("number_of_seasons")
        episode_count = details.get("number_of_episodes")
        if season_count and episode_count:
            rows.append(("Seasons", f"{season_count} seasons · {episode_count} episodes"))
        if state.completeness is not None:
            rows.append(("Matched", f"{state.total_matched}/{state.total_expected} ({state.match_pct:.0f}%)"))

    rows.append(("Confidence", detail_state_confidence_value(state)))
    if queue_reason and media_type != "movie":
        rows.append(("Queue", queue_reason))
    if preview is not None:
        rows.append(("File", preview.original.name))
        if preview.new_name:
            rows.append(("Rename", preview.new_name))
        rows.append(("Preview", preview.status))
        if episode_meta and episode_meta.get("air_date"):
            rows.append(("Air Date", episode_meta["air_date"]))

    if episode_meta and episode_meta.get("overview"):
        overview = episode_meta["overview"]
    else:
        overview = details.get("overview", "") or "No synopsis available."

    extra_lines: list[str] = []
    if episode_meta:
        if episode_meta.get("directors"):
            extra_lines.append("Directors: " + ", ".join(episode_meta["directors"]))
        if episode_meta.get("writers"):
            extra_lines.append("Writers: " + ", ".join(episode_meta["writers"]))
        guest_names = [guest.get("name", "") for guest in episode_meta.get("guest_stars", []) if guest.get("name")]
        if guest_names:
            extra_lines.append("Guests: " + ", ".join(guest_names[:4]))
    elif media_type == "movie":
        companies = [company.get("name", "") for company in details.get("production_companies", []) if company.get("name")]
        if companies:
            extra_lines.append("Companies: " + ", ".join(companies[:3]))
    else:
        creators = [creator.get("name", "") for creator in details.get("created_by", []) if creator.get("name")]
        if creators:
            extra_lines.append("Creators: " + ", ".join(creators[:3]))
        if show_discovery_info and state.discovery_reason:
            extra_lines.append(f"Discovery: {state.discovery_reason}")

    return (
        {
            "title": state.display_name,
            "subtitle": subtitle,
            "rows": rows,
            "overview": overview,
            "extra": "\n".join(extra_lines),
            "artwork_mode": "poster",
        },
        raw_image,
    )
