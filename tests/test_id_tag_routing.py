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
    # id_tag_routing is off: no ID-tag lookup runs on the fallback provider.
    # The primary comes up with no candidates at all (RecordingProvider
    # returns []), so the resulting unmatched, still-"auto" state is weak
    # enough to earn a genuine second-opinion fallback search (Task 7
    # fix: unmatched folders are no longer excluded from that pass).
    assert "get_tv_details:81189" not in fallback.calls
    assert fallback.calls == ["search_tv_batch"]


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


def test_specifically_named_child_does_not_inherit_parent_tag(tmp_path: Path) -> None:
    # A specifically-named child ("Attack on Titan (2013)" is a real show
    # title, not a generic season/collection label) under a tagged umbrella
    # container must NOT inherit the container's tag — only a generic-named
    # child (the umbrella-fallback case) is allowed to do that.
    container = tmp_path / "Anime Collection {tvdb-999}"
    show = container / "Attack on Titan (2013)"
    show.mkdir(parents=True)
    (show / "Attack.on.Titan.S01E01.mkv").touch()
    orch, primary, fallback = _orchestrator_with_real_discovery(tmp_path)
    assert fallback is not None
    states = orch.discover_shows()
    assert len(states) == 1
    assert states[0].match_origin != "id_tag"
    assert states[0].show_id != 999
    assert "search_tv_batch" in primary.calls
    # The parent tag must never be consulted for a specifically-named
    # child's ID resolution. The primary still finds no candidates for this
    # child (RecordingProvider returns []), so the resulting unmatched
    # state is weak enough to earn a genuine second-opinion fallback search
    # (Task 7 fix: unmatched folders are no longer excluded from that pass)
    # — that traffic is legitimate and distinct from tag-based routing.
    assert "get_tv_details:999" not in fallback.calls
    assert fallback.calls == ["search_tv_batch"]


def test_generic_named_child_inherits_umbrella_parent_tag(tmp_path: Path) -> None:
    # A generic-named child ("Specials" is a season/collection label, not a
    # show title) under a tagged umbrella container DOES inherit the
    # container's tag, matching the title-matching fallback's own gate
    # (is_generic_show_folder_name).
    container = tmp_path / "Breaking Bad (2008) {tvdb-81189}"
    show = container / "Specials"
    show.mkdir(parents=True)
    (show / "Breaking.Bad.S00E01.mkv").touch()
    orch, primary, fallback = _orchestrator_with_real_discovery(tmp_path)
    assert fallback is not None
    states = orch.discover_shows()
    assert len(states) == 1
    assert states[0].match_origin == "id_tag"
    assert states[0].show_id == 81189
    assert states[0].provider_name == "tvdb"
    assert "get_tv_details:81189" in fallback.calls
    assert primary.calls == []
