"""Provider-neutral season-map availability contract."""

from __future__ import annotations

from typing import Any

import pytest

from plex_renamer.providers import SeasonMapUnavailableError


class EmptySeasonMapProvider:
    def get_season_map(self, show_id: int) -> tuple[dict[int, dict[str, Any]], int]:
        return {}, 0


class UnavailableSeasonMapProvider:
    def get_season_map(self, show_id: int) -> tuple[dict[int, dict[str, Any]], int]:
        raise SeasonMapUnavailableError(f"tmdb season map unavailable for {show_id}")


@pytest.fixture
def empty_provider() -> EmptySeasonMapProvider:
    return EmptySeasonMapProvider()


@pytest.fixture
def failing_provider() -> UnavailableSeasonMapProvider:
    return UnavailableSeasonMapProvider()


def test_valid_empty_map_is_a_success(empty_provider: EmptySeasonMapProvider) -> None:
    assert empty_provider.get_season_map(7) == ({}, 0)


def test_unavailable_map_raises_typed_error(failing_provider: UnavailableSeasonMapProvider) -> None:
    with pytest.raises(SeasonMapUnavailableError, match="tmdb season map unavailable for 7"):
        failing_provider.get_season_map(7)
