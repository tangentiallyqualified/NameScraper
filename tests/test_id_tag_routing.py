"""ID-tag routing: a bracketed provider-ID tag on a show folder (or its
umbrella parent) resolves that show by direct ``get_tv_details`` on the
tag's provider instead of going through the search/scoring path
(Task 6)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from _provider_fakes import RecordingProvider

from plex_renamer.app.services import TVLibraryDiscoveryService
from plex_renamer.engine._batch_orchestrators import BatchTVOrchestrator


def _orchestrator_with_real_discovery(
    tmp_path: Path,
    *,
    use_fallback: bool = True,
    id_tag_routing: bool = True,
) -> tuple[BatchTVOrchestrator, RecordingProvider, RecordingProvider | None]:
    primary = RecordingProvider("tmdb")
    fallback = RecordingProvider("tvdb") if use_fallback else None
    orch = BatchTVOrchestrator(
        primary,
        tmp_path,
        TVLibraryDiscoveryService(),
        fallback_provider=fallback,
        id_tag_routing=id_tag_routing,
    )
    return orch, primary, fallback


def test_tagged_folder_resolves_by_direct_id(tmp_path: Path) -> None:
    show = tmp_path / "Breaking Bad (2008) {tvdb-81189}"
    show.mkdir()
    (show / "Breaking.Bad.S01E01.mkv").touch()
    orch, primary, fallback = _orchestrator_with_real_discovery(tmp_path)
    assert fallback is not None
    states = orch.discover_shows()
    assert len(states) == 1
    assert states[0].provider_name == "tvdb"
    assert states[0].show_id == 81189
    assert states[0].confidence == 1.0
    assert states[0].match_origin == "id_tag"
    assert states[0].needs_review is False
    assert "get_tv_details:81189" in fallback.calls
    assert "search_tv_batch" not in fallback.calls
    # The tag-routed candidate never touches the primary provider at all.
    assert primary.calls == []


def test_tag_ignored_when_setting_off(tmp_path: Path) -> None:
    show = tmp_path / "Breaking Bad (2008) {tvdb-81189}"
    show.mkdir()
    (show / "Breaking.Bad.S01E01.mkv").touch()
    orch, primary, fallback = _orchestrator_with_real_discovery(tmp_path, id_tag_routing=False)
    assert fallback is not None
    states = orch.discover_shows()
    assert len(states) == 1
    assert states[0].match_origin == "auto"
    assert states[0].provider_name == "tmdb"
    assert "search_tv_batch" in primary.calls
    # id_tag_routing is off: the fallback provider is never consulted.
    assert fallback.calls == []


def test_tag_ignored_when_provider_missing(tmp_path: Path) -> None:
    show = tmp_path / "Breaking Bad (2008) {tvdb-81189}"
    show.mkdir()
    (show / "Breaking.Bad.S01E01.mkv").touch()
    orch, primary, fallback = _orchestrator_with_real_discovery(tmp_path, use_fallback=False)
    assert fallback is None
    states = orch.discover_shows()
    assert len(states) == 1
    assert states[0].match_origin == "auto"
    assert states[0].provider_name == "tmdb"
    assert "search_tv_batch" in primary.calls


def test_failed_id_lookup_falls_through(tmp_path: Path) -> None:
    show = tmp_path / "Breaking Bad (2008) {tvdb-81189}"
    show.mkdir()
    (show / "Breaking.Bad.S01E01.mkv").touch()

    class _NoDetailsProvider(RecordingProvider):
        def get_tv_details(self, show_id: int) -> dict[str, Any] | None:
            self.calls.append(f"get_tv_details:{show_id}")
            return None

    primary = RecordingProvider("tmdb")
    fallback = _NoDetailsProvider("tvdb")
    orch = BatchTVOrchestrator(
        primary,
        tmp_path,
        TVLibraryDiscoveryService(),
        fallback_provider=fallback,
    )
    states = orch.discover_shows()
    assert len(states) == 1
    assert states[0].match_origin == "auto"
    assert states[0].provider_name == "tmdb"
    assert "get_tv_details:81189" in fallback.calls
    # Lookup failed -> falls through to the normal search path, no crash.
    assert "search_tv_batch" in primary.calls
