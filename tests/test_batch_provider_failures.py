"""Batch behavior when provider season maps are unavailable."""

# pyright: strict

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, cast

import pytest
from _provider_fakes import RecordingProvider

from plex_renamer.app.services import TVLibraryDiscoveryService
from plex_renamer.app.services.command_gating_service import CommandGatingService
from plex_renamer.engine._batch_orchestrators import BatchTVOrchestrator
from plex_renamer.engine.models import PreviewItem, ScanState
from plex_renamer.providers import MetadataProvider, SeasonMapUnavailableError


class _BatchScanPort(Protocol):
    def scan_all(self) -> None: ...


class _CheckVarsView(Protocol):
    check_vars: object


class _ProviderRaising(RecordingProvider):
    def __init__(self) -> None:
        super().__init__("tmdb")

    def get_season_map(self, show_id: int) -> tuple[dict[int, dict[str, Any]], int]:
        raise SeasonMapUnavailableError(f"tmdb season map unavailable for {show_id}")


class _ProviderExploding(RecordingProvider):
    def __init__(self) -> None:
        super().__init__("tmdb")

    def get_season_map(self, show_id: int) -> tuple[dict[int, dict[str, Any]], int]:
        raise RuntimeError("provider exploded")


class _DiscoveryMapOutageProvider(_ProviderRaising):
    match: dict[str, Any] = {
        "id": 7,
        "name": "Example Show",
        "year": "2024",
        "poster_path": None,
        "overview": "",
    }

    def search_tv_batch(
        self,
        queries: list[tuple[str, str | None]],
        max_workers: int = 8,
        progress_callback: Callable[..., Any] | None = None,
    ) -> list[list[dict[str, Any]]]:
        return [[self.match] for _query in queries]

    def get_tv_details(self, show_id: int) -> dict[str, Any]:
        return {"id": show_id, "seasons": [], "number_of_episodes": 1}


class _DiscoveryUnexpectedFailureProvider(_DiscoveryMapOutageProvider):
    def get_season_map(self, show_id: int) -> tuple[dict[int, dict[str, Any]], int]:
        raise RuntimeError("unexpected matching defect")


def _orchestrator_state(
    tmp_path: Path,
    provider: MetadataProvider,
) -> tuple[BatchTVOrchestrator, ScanState]:
    show = tmp_path / "Example Show"
    show.mkdir()
    episode = show / "Example.Show.S01E01.mkv"
    episode.write_text("x")
    state = ScanState(
        folder=show,
        media_info={"id": 7, "name": "Example Show"},
        preview_items=[
            PreviewItem(
                original=episode,
                new_name="Example Show - S01E01.mkv",
                target_dir=show,
                season=1,
                episodes=[1],
                status="OK",
            )
        ],
        checked=True,
    )
    orchestrator = BatchTVOrchestrator(
        provider,
        tmp_path,
        discovery_service=TVLibraryDiscoveryService(),
    )
    orchestrator.states = [state]
    return orchestrator, state


def _scan_with_provider(tmp_path: Path, provider: MetadataProvider) -> ScanState:
    orchestrator, state = _orchestrator_state(tmp_path, provider)
    cast(_BatchScanPort, orchestrator).scan_all()
    return state


def test_batch_failure_sets_scan_error_and_cannot_queue(tmp_path: Path) -> None:
    state = _scan_with_provider(tmp_path, _ProviderRaising())

    assert state.scan_error == "Episode guide is unavailable; retry the provider scan."
    assert state.preview_items == []
    assert state.checked is False
    assert state.scanned is False
    assert (
        not CommandGatingService().evaluate_scan_state(state, allow_show_level_queue=True).enabled
    )


def test_batch_untyped_failure_clears_stale_state_and_cannot_queue(tmp_path: Path) -> None:
    state = _scan_with_provider(tmp_path, _ProviderExploding())

    assert state.scan_error == "provider exploded"
    assert state.preview_items == []
    assert state.checked is False
    assert state.scanned is False
    assert cast(_CheckVarsView, state).check_vars == {}
    assert (
        not CommandGatingService().evaluate_scan_state(state, allow_show_level_queue=True).enabled
    )


def _discovery_orchestrator(tmp_path: Path, provider: MetadataProvider) -> BatchTVOrchestrator:
    show = tmp_path / "Example Show (2024)"
    show.mkdir()
    (show / "Example.Show.S01E01.Pilot.mkv").write_text("x")
    return BatchTVOrchestrator(
        provider,
        tmp_path,
        discovery_service=TVLibraryDiscoveryService(),
    )


def test_discovery_abstains_from_optional_episode_evidence_during_map_outage(
    tmp_path: Path,
) -> None:
    orchestrator = _discovery_orchestrator(tmp_path, _DiscoveryMapOutageProvider())

    states = orchestrator.discover_shows()

    assert len(states) == 1
    assert states[0].show_id == 7
    assert states[0].scan_error is None
    cast(_BatchScanPort, orchestrator).scan_all()
    assert states[0].scan_error == "Episode guide is unavailable; retry the provider scan."


def test_direct_scan_show_marks_typed_provider_failure(tmp_path: Path) -> None:
    orchestrator, state = _orchestrator_state(tmp_path, _ProviderRaising())

    orchestrator.scan_show(state)

    assert state.scan_error == "Episode guide is unavailable; retry the provider scan."
    assert state.scanning is False
    assert state.scanned is False


def test_discovery_does_not_swallow_unexpected_episode_evidence_defects(
    tmp_path: Path,
) -> None:
    orchestrator = _discovery_orchestrator(
        tmp_path,
        _DiscoveryUnexpectedFailureProvider(),
    )

    with pytest.raises(RuntimeError, match="unexpected matching defect"):
        orchestrator.discover_shows()
