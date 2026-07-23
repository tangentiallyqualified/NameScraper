"""Prove matching runs against any MetadataProvider, not TMDBClient."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PIL import Image

from plex_renamer.engine._batch_tv_match_policy import (
    episode_count_tiebreak,
    primary_name_breaks_tie,
)
from plex_renamer.engine.matching import (
    boost_tv_scores_with_episode_evidence,
    score_tv_results,
)
from plex_renamer.engine.models import DirectEpisodeEvidence
from plex_renamer.metadata_types import MediaInfo, ScoredMediaInfo
from plex_renamer.providers import MetadataProvider


class FakeProvider:
    provider_name = "fake"
    language = "en-US"

    def search_tv(self, query: str, year: str | None = None) -> list[MediaInfo]:
        return []

    def search_tv_batch(
        self,
        queries: list[tuple[str, str | None]],
        max_workers: int = 8,
        progress_callback: Callable[..., Any] | None = None,
    ) -> list[list[MediaInfo]]:
        return [[] for _ in queries]

    def search_with_fallback(
        self,
        query: str,
        search_fn: Callable[..., list[MediaInfo]],
        min_words: int = 1,
        **kwargs: Any,
    ) -> list[MediaInfo]:
        return search_fn(query, **kwargs)

    def get_tv_details(self, show_id: int) -> dict[str, Any] | None:
        return {
            "id": show_id,
            "name": "Frieren",
            "first_air_date": "2023-09-29",
            "status": "Ended",
            "number_of_episodes": 28,
            "number_of_seasons": 1,
            "seasons": [{"season_number": 1, "episode_count": 28, "name": "Season 1"}],
        }

    def get_season(self, show_id: int, season_num: int) -> dict[str, Any]:
        return {"titles": {}, "posters": {}, "episodes": {}, "season_poster_path": None}

    def get_season_map(self, show_id: int) -> tuple[dict[int, dict[str, Any]], int]:
        return {}, 0

    def get_alternative_titles(
        self, media_id: int, media_type: str = "movie"
    ) -> list[tuple[str, str]]:
        return [("Sousou no Frieren", "")]

    def fetch_image(self, image_path: str | None, target_width: int = 300) -> Image.Image | None:
        return None

    def fetch_poster(
        self,
        media_id: int,
        media_type: str = "tv",
        season: int | None = None,
        ep_still: str | None = None,
        target_width: int = 300,
    ) -> Image.Image | None:
        return None

    def fetch_image_bytes(self, image_path: str | None, size: str = "original") -> bytes | None:
        return None

    def get_cached_poster_path(self, media_id: int, media_type: str = "tv") -> str | None:
        return None

    def clear_cache(self) -> None:
        return None


def test_fake_provider_satisfies_protocol() -> None:
    assert isinstance(FakeProvider(), MetadataProvider)


def test_score_tv_results_accepts_any_provider(tmp_path: Path) -> None:
    results: list[MediaInfo] = [
        {
            "id": 1,
            "name": "Frieren: Beyond Journey's End",
            "year": "2023",
            "poster_path": None,
            "overview": "",
        },
        {
            "id": 2,
            "name": "Unrelated Show",
            "year": "1999",
            "poster_path": None,
            "overview": "",
        },
    ]
    scored: ScoredMediaInfo = score_tv_results(
        results, "Frieren", "2023", FakeProvider(), folder=tmp_path
    )
    assert len(scored) == 2
    scored_ids = {result["id"] for result, _score in scored}
    assert scored_ids == {1, 2}
    assert scored[0][0]["id"] == 1


class _RejectsNonIntegerAltTitleIds(FakeProvider):
    def get_alternative_titles(
        self, media_id: int, media_type: str = "movie"
    ) -> list[tuple[str, str]]:
        assert isinstance(media_id, int)
        return []


def test_score_tv_results_skips_non_integer_media_id(tmp_path: Path) -> None:
    result: MediaInfo = {
        "id": "invalid",
        "name": "Unrelated Show",
        "year": "1999",
        "poster_path": None,
        "overview": "",
    }

    scored = score_tv_results(
        [result],
        "Expected Show",
        "2024",
        _RejectsNonIntegerAltTitleIds(),
        folder=tmp_path,
    )

    assert scored[0][0] is result


class _RejectsInvalidEpisodeEvidenceIds(FakeProvider):
    def get_season_map(self, show_id: int) -> tuple[dict[int, dict[str, Any]], int]:
        assert type(show_id) is int
        return {}, 0


def test_episode_evidence_skips_invalid_boolean_media_id() -> None:
    result: MediaInfo = {"id": True, "name": "Show", "year": "2024"}
    scored: ScoredMediaInfo = [(result, 0.5)]

    updated = boost_tv_scores_with_episode_evidence(
        _RejectsInvalidEpisodeEvidenceIds(),
        scored,
        [DirectEpisodeEvidence(1, 1, "Pilot")],
    )

    assert updated == scored
    assert updated[0][0] is result


class _RejectsInvalidDetailIds(FakeProvider):
    def get_tv_details(self, show_id: int) -> dict[str, Any] | None:
        assert type(show_id) is int
        return super().get_tv_details(show_id)


def test_episode_count_tiebreak_skips_invalid_boolean_media_id() -> None:
    result: MediaInfo = {"id": False, "name": "Show", "year": "2024"}

    best, score, discriminated = episode_count_tiebreak(
        _RejectsInvalidDetailIds(),
        [(result, 0.9)],
        file_count=28,
    )

    assert best is result
    assert score == 0.9
    assert discriminated is False


def test_primary_name_tie_policy_treats_malformed_names_as_empty() -> None:
    malformed_best: MediaInfo = {"id": 1, "name": 42, "year": "2024"}
    matching_runner: MediaInfo = {"id": 2, "name": "Expected Show", "year": "2024"}
    matching_best: MediaInfo = {"id": 1, "name": "Expected Show", "year": "2024"}
    malformed_runner: MediaInfo = {"id": 2, "name": 84, "year": "2024"}

    assert primary_name_breaks_tie(malformed_best, matching_runner, "Expected Show", None) is False
    assert primary_name_breaks_tie(matching_best, malformed_runner, "Expected Show", None) is True
