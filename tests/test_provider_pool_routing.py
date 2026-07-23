"""Provider pool: per-state routing of downstream metadata calls."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from _provider_fakes import RecordingProvider


def _orchestrator(
    tmp_path: Path,
) -> tuple[Any, RecordingProvider, RecordingProvider]:
    from plex_renamer.engine._batch_orchestrators import BatchTVOrchestrator
    from plex_renamer.engine._discovery_ports import (
        TVDiscoveryCandidateLike,  # verify import path
    )

    primary = RecordingProvider("tmdb")
    fallback = RecordingProvider("tvdb")

    class NoDiscovery:
        def discover_show_roots(self, library_root: Path) -> list[TVDiscoveryCandidateLike]:
            return []

    orch = BatchTVOrchestrator(primary, tmp_path, NoDiscovery(), fallback_provider=fallback)
    return orch, primary, fallback


def test_provider_for_routes_by_attribution(tmp_path: Path) -> None:
    from plex_renamer.engine.models import ScanState

    orch, primary, fallback = _orchestrator(tmp_path)
    state = ScanState(folder=tmp_path, media_info={"id": 7, "name": "S"})
    assert orch.provider_for(state) is primary
    state.provider_name = "tvdb"
    assert orch.provider_for(state) is fallback


def test_provider_for_unknown_name_falls_back_to_primary(tmp_path: Path) -> None:
    from plex_renamer.engine.models import ScanState

    orch, primary, _fallback = _orchestrator(tmp_path)
    state = ScanState(folder=tmp_path, media_info={"id": 7, "name": "S"})
    state.provider_name = "nonsense"
    assert orch.provider_for(state) is primary


def test_provider_named_returns_none_for_unknown(tmp_path: Path) -> None:
    orch, _primary, _fallback = _orchestrator(tmp_path)
    assert orch.provider_named("nonsense") is None


def test_provider_named_finds_fallback(tmp_path: Path) -> None:
    orch, _primary, fallback = _orchestrator(tmp_path)
    assert orch.provider_named("tvdb") is fallback


def test_provider_pool_without_fallback_still_resolves_primary(tmp_path: Path) -> None:
    from plex_renamer.engine._batch_orchestrators import BatchTVOrchestrator
    from plex_renamer.engine._discovery_ports import TVDiscoveryCandidateLike
    from plex_renamer.engine.models import ScanState

    primary = RecordingProvider("tmdb")

    class NoDiscovery:
        def discover_show_roots(self, library_root: Path) -> list[TVDiscoveryCandidateLike]:
            return []

    orch = BatchTVOrchestrator(primary, tmp_path, NoDiscovery())
    state = ScanState(folder=tmp_path, media_info={"id": 7, "name": "S"})
    assert orch.provider_for(state) is primary
    assert orch.provider_named("tvdb") is None


def test_season_names_use_attributed_provider(tmp_path: Path) -> None:
    orch, primary, fallback = _orchestrator(tmp_path)
    details = orch._show_details_for_match({"id": 7}, provider=fallback)
    orch._season_names_for_match(details)
    assert "get_tv_details:7" in fallback.calls
    assert primary.calls == []


def test_season_names_default_to_primary(tmp_path: Path) -> None:
    orch, primary, fallback = _orchestrator(tmp_path)
    details = orch._show_details_for_match({"id": 7})
    orch._season_names_for_match(details)
    assert "get_tv_details:7" in primary.calls
    assert fallback.calls == []
