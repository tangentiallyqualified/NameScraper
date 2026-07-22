# pyright: strict

"""Typed validation and strict fetching for untrusted TVDB payloads."""

from __future__ import annotations

from typing import Any, cast

from ._provider_errors import SeasonMapUnavailableError
from ._tmdb_transport import TMDBError
from ._tvdb_transport import TVDBTransport

Payload = dict[str, object]

_SEASON_POSTER_TYPE = 7
_SERIES_DETAILS_LIST_FIELDS = (
    "artworks",
    "seasons",
    "characters",
    "genres",
    "companies",
    "aliases",
)


def _as_mapping(value: object) -> Payload | None:
    if not isinstance(value, dict):
        return None
    return cast(Payload, value)


def _as_record_list(value: object) -> list[Payload] | None:
    if not isinstance(value, list):
        return None
    items = cast(list[object], value)
    if not all(isinstance(item, dict) for item in items):
        return None
    return cast(list[Payload], items)


def validated_record_list(value: object) -> list[dict[str, Any]] | None:
    """Return a typed view of a list containing only mapping records."""
    records = _as_record_list(value)
    if records is None:
        return None
    return cast(list[dict[str, Any]], records)


def _valid_record_fields(payload: Payload) -> bool:
    for field in _SERIES_DETAILS_LIST_FIELDS:
        value = payload.get(field)
        if value is not None and _as_record_list(value) is None:
            return False
    return True


def _record_field(payload: Payload, field: str) -> list[Payload]:
    value = payload.get(field)
    if value is None:
        return []
    return cast(list[Payload], value)


def _valid_identifier(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, str))


def _valid_episode_number(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int)


def _valid_season(season: Payload) -> bool:
    season_type_value = season.get("type")
    if season_type_value is None:
        return True
    season_type = _as_mapping(season_type_value)
    if season_type is None:
        return False
    if season_type.get("type") != "official":
        return True
    return _valid_identifier(season.get("id")) and _valid_episode_number(season.get("number"))


def _valid_artwork(artwork: Payload) -> bool:
    image = artwork.get("image")
    language = artwork.get("language")
    if image is not None and not isinstance(image, str):
        return False
    if language is not None and not isinstance(language, str):
        return False
    return artwork.get("type") != _SEASON_POSTER_TYPE or _valid_identifier(artwork.get("seasonId"))


def _valid_company(company: Payload) -> bool:
    company_type = company.get("companyType")
    return company_type is None or _as_mapping(company_type) is not None


def _valid_nested_records(payload: Payload) -> bool:
    if not all(_valid_season(season) for season in _record_field(payload, "seasons")):
        return False
    if not all(_valid_artwork(artwork) for artwork in _record_field(payload, "artworks")):
        return False
    return all(_valid_company(company) for company in _record_field(payload, "companies"))


def validated_series_details(value: object) -> dict[str, Any] | None:
    """Return details only when every nested record used by normalization is safe."""
    payload = _as_mapping(value)
    if payload is None or not _valid_record_fields(payload):
        return None
    status = payload.get("status")
    if status is not None and _as_mapping(status) is None:
        return None
    if not _valid_nested_records(payload):
        return None
    return cast(dict[str, Any], payload)


def optional_series_details(response: object) -> dict[str, Any] | None:
    """Extract a valid details payload from a best-effort TVDB response."""
    envelope = _as_mapping(response)
    if envelope is None:
        return None
    payload = envelope.get("data")
    if not payload:
        return None
    return validated_series_details(payload)


def _require_series_details(response: object, show_id: int) -> dict[str, Any]:
    if response is None:
        raise SeasonMapUnavailableError(f"tvdb season map unavailable for {show_id}: not found")
    envelope = _as_mapping(response)
    if envelope is None:
        raise SeasonMapUnavailableError(
            f"tvdb season map unavailable for {show_id}: invalid details"
        )
    payload = envelope.get("data")
    if not payload:
        raise SeasonMapUnavailableError(f"tvdb season map unavailable for {show_id}: empty details")
    payload_mapping = _as_mapping(payload)
    if payload_mapping is None:
        raise SeasonMapUnavailableError(f"tvdb season map unavailable for {show_id}: empty details")
    details = validated_series_details(payload_mapping)
    if details is None:
        raise SeasonMapUnavailableError(
            f"tvdb season map unavailable for {show_id}: invalid details"
        )
    return details


def fetch_series_details_strict(transport: TVDBTransport, show_id: int) -> dict[str, Any]:
    """Fetch a trustworthy extended-details payload or raise the provider error."""
    try:
        response = cast(object, transport.get_json(f"/series/{show_id}/extended"))
    except TMDBError as exc:
        raise SeasonMapUnavailableError(
            f"tvdb season map unavailable for {show_id}: {exc}"
        ) from exc
    return _require_series_details(response, show_id)


def _valid_episode(episode: Payload) -> bool:
    season_number = episode.get("seasonNumber")
    episode_number = episode.get("number")
    title = episode.get("name")
    poster = episode.get("image")
    return (
        _valid_episode_number(season_number)
        and _valid_episode_number(episode_number)
        and (title is None or isinstance(title, str))
        and (poster is None or isinstance(poster, str))
    )


def _require_episode_page(response: object, show_id: int) -> tuple[list[dict[str, Any]], bool]:
    if response is None:
        raise SeasonMapUnavailableError(f"tvdb season map unavailable for {show_id}: not found")
    envelope = _as_mapping(response)
    if envelope is None:
        raise SeasonMapUnavailableError(
            f"tvdb season map unavailable for {show_id}: invalid episode data"
        )
    data = _as_mapping(envelope.get("data"))
    if data is None:
        raise SeasonMapUnavailableError(
            f"tvdb season map unavailable for {show_id}: invalid episode data"
        )
    page_episodes = _as_record_list(data.get("episodes"))
    if page_episodes is None:
        raise SeasonMapUnavailableError(
            f"tvdb season map unavailable for {show_id}: invalid episode data"
        )
    if not all(_valid_episode(episode) for episode in page_episodes):
        raise SeasonMapUnavailableError(
            f"tvdb season map unavailable for {show_id}: invalid episode data"
        )
    links_value = envelope.get("links")
    if links_value is None:
        links: Payload = {}
    else:
        parsed_links = _as_mapping(links_value)
        if parsed_links is None:
            raise SeasonMapUnavailableError(
                f"tvdb season map unavailable for {show_id}: invalid pagination"
            )
        links = parsed_links
    return cast(list[dict[str, Any]], page_episodes), bool(links.get("next"))


def fetch_all_episodes_strict(transport: TVDBTransport, show_id: int) -> list[dict[str, Any]]:
    """Fetch and validate every TVDB episode page without caching partial data."""
    episodes: list[dict[str, Any]] = []
    page = 0
    while True:
        try:
            response = cast(
                object,
                transport.get_json(f"/series/{show_id}/episodes/default", {"page": page}),
            )
        except TMDBError as exc:
            raise SeasonMapUnavailableError(
                f"tvdb season map unavailable for {show_id}: {exc}"
            ) from exc
        page_episodes, has_next = _require_episode_page(response, show_id)
        episodes.extend(page_episodes)
        if not has_next:
            return episodes
        page += 1
