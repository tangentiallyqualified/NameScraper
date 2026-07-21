"""Task 8: ``switch_provider`` (manual per-show provider swap) and
persistent provider pins consulted by ``discover_shows``.

A user-initiated ``switch_provider`` call re-resolves a show on another
pooled provider and pins the state's ``match_origin`` to ``"manual"``
(reviewed once, then trusted). A persisted pin (``provider_overrides``,
keyed by ``show_pin_key``) makes ``discover_shows`` route that show's
initial SEARCH to the pinned provider directly — pin outranks ID tag,
but the match is still scored, never hard-coded — and the fallback
second-opinion pass (Task 7) must never second-guess a pinned show away
from its pinned provider.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from _provider_fakes import RecordingProvider

from plex_renamer.app.services import TVLibraryDiscoveryService
from plex_renamer.engine._batch_orchestrators import BatchTVOrchestrator
from plex_renamer.engine._state import get_auto_accept_threshold, set_auto_accept_threshold
from plex_renamer.engine.models import ScanState, show_pin_key

_QueryTuple = tuple[str, str | None]


class _FixedSearchProvider(RecordingProvider):
    """``RecordingProvider`` whose single-query ``search_tv`` returns an
    injected result list instead of the shared fake's hardcoded ``[]``."""

    def __init__(self, name: str, results: list[dict[str, Any]] | None = None) -> None:
        super().__init__(name)
        self._results: list[dict[str, Any]] = results if results is not None else []

    def search_tv(self, query: str, year: str | None = None) -> list[dict[str, Any]]:
        self.calls.append(f"search_tv:{query}")
        return self._results


class _FixedBatchProvider(RecordingProvider):
    """``RecordingProvider`` whose ``search_tv_batch`` returns results
    injected per query (keyed by the query title, case-insensitive)."""

    def __init__(
        self,
        name: str,
        results_by_query: dict[str, list[dict[str, Any]]] | None = None,
    ) -> None:
        super().__init__(name)
        self.results_by_query: dict[str, list[dict[str, Any]]] = results_by_query or {}

    def search_tv_batch(
        self,
        queries: list[_QueryTuple],
        max_workers: int = 8,
        progress_callback: Callable[..., Any] | None = None,
    ) -> list[list[dict[str, Any]]]:
        self.calls.append("search_tv_batch")
        return [self.results_by_query.get(title.lower(), []) for title, _year in queries]


@pytest.fixture()
def auto_accept_threshold() -> Any:
    """Pin the auto-accept threshold to 0.82 for the duration of a test,
    restoring whatever value was active beforehand."""
    previous = get_auto_accept_threshold()
    set_auto_accept_threshold(0.82)
    try:
        yield 0.82
    finally:
        set_auto_accept_threshold(previous)


def _result(result_id: int, name: str, year: str) -> dict[str, Any]:
    return {
        "id": result_id,
        "name": name,
        "year": year,
        "poster_path": None,
        "overview": "",
    }


def _make_show(tmp_path: Path, folder_name: str, episode_name: str) -> Path:
    show = tmp_path / folder_name
    show.mkdir()
    (show / episode_name).write_text("x")
    return show


def _matched_state(folder: Path, provider_name: str = "tmdb") -> ScanState:
    return ScanState(
        folder=folder,
        media_info=_result(1, "Widget Falls", "1999"),
        confidence=0.9,
        provider_name=provider_name,
        match_origin="auto",
        scanned=True,
    )


def test_switch_adopts_best_match_and_resets_scan(tmp_path: Path) -> None:
    folder = _make_show(tmp_path, "Widget Falls", "Widget.Falls.S01E01.mkv")
    state = _matched_state(folder, provider_name="tmdb")

    primary = RecordingProvider("tmdb")
    tvdb_match = _result(2, "Widget Falls", "2023")
    fallback = _FixedSearchProvider("tvdb", [tvdb_match])

    orch = BatchTVOrchestrator(
        primary, tmp_path, TVLibraryDiscoveryService(), fallback_provider=fallback
    )
    orch.states = [state]

    merged_state, switched = orch.switch_provider(state, "tvdb")

    assert switched is True
    assert merged_state.provider_name == "tvdb"
    assert merged_state.match_origin == "manual"
    assert merged_state.scanned is False
    assert merged_state.media_info.get("id") == 2


def test_switch_provider_works_when_fallback_matching_disabled(tmp_path: Path) -> None:
    """I1: the Source-selector/switch_provider flow only needs the OTHER
    provider's client pooled — it must keep working with fallback MATCHING
    off. Previously ``ensure_fallback_provider`` starved the pool's second
    slot whenever the toggle was off, so switch_provider had nothing to
    resolve "tvdb" to even though both API keys existed."""
    folder = _make_show(tmp_path, "Widget Falls", "Widget.Falls.S01E01.mkv")
    state = _matched_state(folder, provider_name="tmdb")

    primary = RecordingProvider("tmdb")
    tvdb_match = _result(2, "Widget Falls", "2023")
    fallback = _FixedSearchProvider("tvdb", [tvdb_match])

    # fallback_matching=False mirrors what _tv_batch_helpers wires from
    # settings.tv_fallback_enabled=False — the pool is still fed because the
    # GUI feeds fallback_provider whenever its key exists (I1 fix), never
    # gated by the matching toggle.
    orch = BatchTVOrchestrator(
        primary,
        tmp_path,
        TVLibraryDiscoveryService(),
        fallback_provider=fallback,
        fallback_matching=False,
    )
    orch.states = [state]

    merged_state, switched = orch.switch_provider(state, "tvdb")

    assert switched is True
    assert merged_state.provider_name == "tvdb"
    assert merged_state.media_info.get("id") == 2


def test_switch_no_results_keeps_state(tmp_path: Path) -> None:
    folder = _make_show(tmp_path, "Widget Falls", "Widget.Falls.S01E01.mkv")
    state = _matched_state(folder, provider_name="tmdb")

    primary = RecordingProvider("tmdb")
    fallback = _FixedSearchProvider("tvdb")  # no results injected -> []

    orch = BatchTVOrchestrator(
        primary, tmp_path, TVLibraryDiscoveryService(), fallback_provider=fallback
    )
    orch.states = [state]

    merged_state, switched = orch.switch_provider(state, "tvdb")

    assert switched is False
    assert merged_state.provider_name == "tmdb"
    assert merged_state is state


def test_switch_unknown_provider_keeps_state(tmp_path: Path) -> None:
    folder = _make_show(tmp_path, "Widget Falls", "Widget.Falls.S01E01.mkv")
    state = _matched_state(folder, provider_name="tmdb")

    primary = RecordingProvider("tmdb")
    orch = BatchTVOrchestrator(primary, tmp_path, TVLibraryDiscoveryService())
    orch.states = [state]

    merged_state, switched = orch.switch_provider(state, "nonexistent")

    assert switched is False
    assert merged_state.provider_name == "tmdb"
    assert merged_state is state


def test_pin_routes_discovery_search(tmp_path: Path) -> None:
    folder = _make_show(tmp_path, "Widget Falls", "Widget.Falls.S01E01.mkv")

    primary = _FixedBatchProvider("tmdb", {"widget falls": [_result(1, "Widget Falls", "1999")]})
    fallback = _FixedBatchProvider("tvdb", {"widget falls": [_result(2, "Widget Falls", "2023")]})

    pin_key = show_pin_key(folder)
    orch = BatchTVOrchestrator(
        primary,
        tmp_path,
        TVLibraryDiscoveryService(),
        fallback_provider=fallback,
        provider_overrides={pin_key: {"provider": "tvdb", "show_id": 5}},
    )
    states = orch.discover_shows()

    assert len(states) == 1
    assert states[0].provider_name == "tvdb"
    assert states[0].media_info.get("id") == 2
    # Only the pinned (fallback) provider was searched for this candidate.
    assert "search_tv_batch" in fallback.calls
    assert primary.calls == []


def test_pin_outranks_id_tag(tmp_path: Path) -> None:
    # The folder carries a valid {tmdb-1} ID tag, but the pin says tvdb —
    # the pin must win: id-tag resolution is skipped and the search routes
    # to the pinned (tvdb) provider instead.
    folder = tmp_path / "Widget Falls (1999) {tmdb-1}"
    folder.mkdir()
    (folder / "Widget.Falls.S01E01.mkv").write_text("x")

    primary = _FixedBatchProvider("tmdb", {"widget falls": [_result(1, "Widget Falls", "1999")]})
    fallback = _FixedBatchProvider("tvdb", {"widget falls": [_result(2, "Widget Falls", "2023")]})

    pin_key = show_pin_key(folder)
    orch = BatchTVOrchestrator(
        primary,
        tmp_path,
        TVLibraryDiscoveryService(),
        fallback_provider=fallback,
        provider_overrides={pin_key: {"provider": "tvdb"}},
    )
    states = orch.discover_shows()

    assert len(states) == 1
    assert states[0].match_origin != "id_tag"
    assert states[0].provider_name == "tvdb"
    assert states[0].media_info.get("id") == 2
    assert "search_tv_batch" in fallback.calls
    assert primary.calls == []
    # The tag's own provider (tmdb, the primary here) is never consulted
    # via get_tv_details for this candidate.
    assert not any(call.startswith("get_tv_details") for call in primary.calls)


def test_switch_recomputes_season_assignment_for_adopted_name(tmp_path: Path) -> None:
    """M2: mirrors the fallback-adoption recompute (commit 8e9f763) — the
    show-name-suffix branch of ``infer_explicit_season_assignment`` depends
    on the MATCHED show's name, which just changed. Folder "Widget Falls 2"
    has no season-parseable name on its own and its one episode file is
    fansub-style (episode number, no season marker), so no explicit S##E##
    evidence exists either — season can only come from the show-name
    suffix branch, which only resolves once the adopted (tvdb) name
    "Widget Falls" is in play."""
    show = tmp_path / "Widget Falls 2"
    show.mkdir()
    (show / "[SubGroup] Widget Falls - 05 [1080p].mkv").write_text("x")

    state = ScanState(
        folder=show,
        media_info=_result(1, "Zzz Nonsense Thing", "1999"),
        confidence=0.9,
        provider_name="tmdb",
        match_origin="auto",
        scanned=True,
    )

    primary = RecordingProvider("tmdb")
    tvdb_match = _result(2, "Widget Falls", "2023")
    fallback = _FixedSearchProvider("tvdb", [tvdb_match])

    orch = BatchTVOrchestrator(
        primary, tmp_path, TVLibraryDiscoveryService(), fallback_provider=fallback
    )
    orch.states = [state]

    merged_state, switched = orch.switch_provider(state, "tvdb")

    assert switched is True
    assert merged_state.season_assignment == 2


def test_show_pin_key_shape(tmp_path: Path) -> None:
    folder = tmp_path / "Breaking Bad (2008)"
    folder.mkdir()
    assert show_pin_key(folder) == "breaking bad|2008"


def test_pinned_weak_match_not_reassigned_by_fallback_pass(
    tmp_path: Path, auto_accept_threshold: float
) -> None:
    """A pinned candidate whose match on the pinned provider is weak must
    NOT be second-guessed away from that provider by the fallback pass
    (Task 7's ``_apply_fallback_matches``) — a pin means "use this
    provider for this show," full stop, even when the pinned provider's
    own result is a poor title match.
    """
    folder = _make_show(tmp_path, "Widget Falls", "Widget.Falls.S01E01.mkv")

    # The pinned provider (tvdb) only offers a poor title match -> weak.
    pinned_weak = _result(2, "Some Unrelated Show", "1999")
    # The OTHER pool provider (tmdb, acting as fallback_provider here) has
    # an exact match that would clearly win a second-opinion pass if the
    # pin didn't suppress it.
    other_exact = _result(3, "Widget Falls", "2023")

    tvdb = _FixedBatchProvider("tvdb", {"widget falls": [pinned_weak]})
    tmdb_fallback = _FixedBatchProvider("tmdb", {"widget falls": [other_exact]})

    pin_key = show_pin_key(folder)
    orch = BatchTVOrchestrator(
        tvdb,
        tmp_path,
        TVLibraryDiscoveryService(),
        fallback_provider=tmdb_fallback,
        provider_overrides={pin_key: {"provider": "tvdb"}},
    )
    states = orch.discover_shows()

    assert len(states) == 1
    state = states[0]
    # Pinned provider's weak match is kept...
    assert state.provider_name == "tvdb"
    assert state.media_info.get("id") == 2
    assert state.match_origin == "auto"
    assert state.confidence < auto_accept_threshold
    # ...and the fallback pass never ran a second-opinion search for it.
    assert tmdb_fallback.calls == []
