"""Pure metadata shaping helpers for TMDB client responses."""

from __future__ import annotations

from typing import Any


def build_tv_search_results(data: dict | None) -> list[dict]:
    if not data:
        return []

    results: list[dict] = []
    for show in data.get("results", []):
        air_date = show.get("first_air_date") or ""
        year = air_date[:4] if len(air_date) >= 4 else ""
        results.append({
            "id": show["id"],
            "name": show["name"],
            "year": year,
            "poster_path": show.get("poster_path"),
            "overview": show.get("overview", ""),
        })
    return results


def build_movie_search_results(data: dict | None) -> list[dict]:
    if not data:
        return []

    results: list[dict] = []
    for movie in data.get("results", []):
        release_date = movie.get("release_date") or ""
        year = release_date[:4] if len(release_date) >= 4 else ""
        results.append({
            "id": movie["id"],
            "title": movie["title"],
            "year": year,
            "poster_path": movie.get("poster_path"),
            "overview": movie.get("overview", ""),
        })
    return results


def build_empty_season_payload() -> dict[str, Any]:
    return {
        "titles": {},
        "posters": {},
        "episodes": {},
        "season_poster_path": None,
    }


def build_season_payload(data: dict | None) -> dict[str, Any]:
    if not data:
        return build_empty_season_payload()

    titles: dict[int, str] = {}
    posters: dict[int, str | None] = {}
    episodes: dict[int, dict[str, Any]] = {}

    for episode in data.get("episodes", []):
        episode_number = episode["episode_number"]
        titles[episode_number] = episode.get("name", f"Episode {episode_number}")
        posters[episode_number] = episode.get("still_path")
        guest_stars = episode.get("guest_stars", [])
        crew = episode.get("crew", [])
        episodes[episode_number] = {
            "name": titles[episode_number],
            "overview": episode.get("overview", ""),
            "air_date": episode.get("air_date", ""),
            "vote_average": episode.get("vote_average", 0),
            "vote_count": episode.get("vote_count", 0),
            "runtime": episode.get("runtime"),
            "still_path": posters[episode_number],
            "directors": [
                crew_member.get("name", "")
                for crew_member in crew
                if crew_member.get("job") == "Director" and crew_member.get("name")
            ],
            "writers": [
                crew_member.get("name", "")
                for crew_member in crew
                if crew_member.get("job") in ("Writer", "Teleplay", "Story")
                and crew_member.get("name")
            ],
            "guest_stars": [
                {
                    "name": guest_star.get("name", ""),
                    "character": guest_star.get("character", ""),
                }
                for guest_star in guest_stars[:5]
            ],
        }

    return {
        "titles": titles,
        "posters": posters,
        "episodes": episodes,
        "season_poster_path": data.get("poster_path"),
    }