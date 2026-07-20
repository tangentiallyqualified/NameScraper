"""Task 7: confidence-gated fallback pass.

A weak primary match (``match_origin == "auto"``, confidence below the
auto-accept threshold) gets a second opinion from the pooled fallback
provider (e.g. TVDB) during ``discover_shows``. The fallback candidate is
adopted only when it strictly outscores the primary match, and adoption
always sets ``match_origin == "fallback"`` (which ``ScanState.needs_review``
treats as always-review, regardless of the adopted score) plus
``provider_name`` to the fallback provider's name.
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

_QueryTuple = tuple[str, str | None]


class _FixedResultProvider(RecordingProvider):
    """``RecordingProvider`` whose ``search_tv_batch`` returns results
    injected per query (keyed by the query title, case-insensitive) instead
    of the shared fake's hardcoded empty lists.

    Backward compatible with ``RecordingProvider``: with no results
    injected, every query still gets ``[]``, matching the base fake.
    """

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


class _RaisingProvider(RecordingProvider):
    """Fallback fake whose search always raises, for the error-resilience case."""

    def search_tv_batch(
        self,
        queries: list[_QueryTuple],
        max_workers: int = 8,
        progress_callback: Callable[..., Any] | None = None,
    ) -> list[list[dict[str, Any]]]:
        self.calls.append("search_tv_batch")
        raise RuntimeError("fallback provider unavailable")


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


def _make_show(tmp_path: Path, folder_name: str, episode_name: str) -> Path:
    show = tmp_path / folder_name
    show.mkdir()
    (show / episode_name).write_text("x")
    return show


def _result(result_id: int, name: str, year: str) -> dict[str, Any]:
    return {
        "id": result_id,
        "name": name,
        "year": year,
        "poster_path": None,
        "overview": "",
    }


def test_weak_primary_adopts_stronger_fallback(
    tmp_path: Path, auto_accept_threshold: float
) -> None:
    _make_show(tmp_path, "Widget Falls", "Widget.Falls.S01E01.mkv")

    # Primary's only candidate is a poor title match for "Widget Falls".
    primary_junk = _result(1, "Some Completely Different Show", "1999")
    # Fallback's candidate is an exact title match.
    fallback_exact = _result(2, "Widget Falls", "2023")

    primary = _FixedResultProvider("tmdb", {"widget falls": [primary_junk]})
    fallback = _FixedResultProvider("tvdb", {"widget falls": [fallback_exact]})

    orch = BatchTVOrchestrator(
        primary, tmp_path, TVLibraryDiscoveryService(), fallback_provider=fallback
    )
    states = orch.discover_shows()

    assert len(states) == 1
    state = states[0]
    assert "search_tv_batch" in fallback.calls
    assert state.media_info.get("id") == 2
    assert state.provider_name == "tvdb"
    assert state.match_origin == "fallback"
    assert state.needs_review is True


def test_fallback_skipped_when_disabled(tmp_path: Path, auto_accept_threshold: float) -> None:
    _make_show(tmp_path, "Widget Falls", "Widget.Falls.S01E01.mkv")

    primary_junk = _result(1, "Some Completely Different Show", "1999")
    primary = _FixedResultProvider("tmdb", {"widget falls": [primary_junk]})
    # A fallback fake exists but is never wired into the orchestrator.
    unused_fallback = _FixedResultProvider("tvdb")

    orch = BatchTVOrchestrator(
        primary, tmp_path, TVLibraryDiscoveryService(), fallback_provider=None
    )
    states = orch.discover_shows()

    assert len(states) == 1
    assert states[0].match_origin == "auto"
    assert states[0].provider_name == "tmdb"
    assert unused_fallback.calls == []


def test_confident_primary_not_second_guessed(tmp_path: Path, auto_accept_threshold: float) -> None:
    _make_show(tmp_path, "Widget Falls", "Widget.Falls.S01E01.mkv")

    # Primary finds an exact title match -> well above the 0.82 threshold.
    primary_exact = _result(1, "Widget Falls", "2023")
    fallback_candidate = _result(2, "Zzz Nonsense Thing", "1999")

    primary = _FixedResultProvider("tmdb", {"widget falls": [primary_exact]})
    fallback = _FixedResultProvider("tvdb", {"widget falls": [fallback_candidate]})

    orch = BatchTVOrchestrator(
        primary, tmp_path, TVLibraryDiscoveryService(), fallback_provider=fallback
    )
    states = orch.discover_shows()

    assert len(states) == 1
    state = states[0]
    assert state.confidence >= auto_accept_threshold
    assert state.match_origin == "auto"
    assert state.provider_name == "tmdb"
    assert fallback.calls == []


def test_weaker_fallback_leaves_primary(tmp_path: Path, auto_accept_threshold: float) -> None:
    _make_show(tmp_path, "Widget Falls", "Widget.Falls.S01E01.mkv")

    # Primary's best candidate is a partial title match: weak enough to
    # need review, but scores well above the near-zero junk fallback below.
    primary_weak = _result(3, "Widgetopolis", "2023")
    fallback_junk = _result(4, "Wxyz Junk", "1999")

    primary = _FixedResultProvider("tmdb", {"widget falls": [primary_weak]})
    fallback = _FixedResultProvider("tvdb", {"widget falls": [fallback_junk]})

    orch = BatchTVOrchestrator(
        primary, tmp_path, TVLibraryDiscoveryService(), fallback_provider=fallback
    )
    states = orch.discover_shows()

    assert len(states) == 1
    state = states[0]
    assert "search_tv_batch" in fallback.calls
    assert state.confidence < auto_accept_threshold
    assert state.media_info.get("id") == 3
    assert state.match_origin == "auto"
    assert state.provider_name == "tmdb"


def test_fallback_errors_never_break_scan(tmp_path: Path, auto_accept_threshold: float) -> None:
    _make_show(tmp_path, "Widget Falls", "Widget.Falls.S01E01.mkv")

    primary_weak = _result(3, "Widgetopolis", "2023")
    primary = _FixedResultProvider("tmdb", {"widget falls": [primary_weak]})
    fallback = _RaisingProvider("tvdb")

    orch = BatchTVOrchestrator(
        primary, tmp_path, TVLibraryDiscoveryService(), fallback_provider=fallback
    )
    states = orch.discover_shows()

    assert len(states) == 1
    state = states[0]
    assert "search_tv_batch" in fallback.calls
    assert state.media_info.get("id") == 3
    assert state.match_origin == "auto"
    assert state.provider_name == "tmdb"


def test_unmatched_primary_adopts_fallback_match(
    tmp_path: Path, auto_accept_threshold: float
) -> None:
    """A folder the primary provider couldn't match AT ALL (no candidates,
    confidence 0.0) is the strongest case for a second opinion — it must
    still reach the fallback pass, not be excluded as "not really weak"."""
    _make_show(tmp_path, "Widget Falls", "Widget.Falls.S01E01.mkv")

    # Primary finds nothing for this folder at all.
    primary = _FixedResultProvider("tmdb")
    fallback_exact = _result(5, "Widget Falls", "2023")
    fallback = _FixedResultProvider("tvdb", {"widget falls": [fallback_exact]})

    orch = BatchTVOrchestrator(
        primary, tmp_path, TVLibraryDiscoveryService(), fallback_provider=fallback
    )
    states = orch.discover_shows()

    assert len(states) == 1
    state = states[0]
    assert "search_tv_batch" in fallback.calls
    assert state.media_info.get("id") == 5
    assert state.provider_name == "tvdb"
    assert state.match_origin == "fallback"
    assert state.needs_review is True


def test_fallback_adoption_recomputes_season_assignment(
    tmp_path: Path, auto_accept_threshold: float
) -> None:
    """Season assignment depends on the MATCHED show's name (the
    show-name+season-suffix branch of ``infer_explicit_season_assignment``).
    Adoption must recompute it against the adopted (fallback) show name,
    not silently carry over whatever the primary's name produced.

    Folder "Widget Falls 2" has no season-parseable name on its own
    (``get_season`` returns None) and its one episode file is fansub-style
    with an episode number but no season marker, so no explicit S##E##
    evidence exists either — the season can only come from the show-name
    suffix branch. Against the primary's unrelated name, that branch finds
    no prefix match (season_assignment stays None); against the fallback's
    exact "Widget Falls" name, "widget falls 2" starts with "widget falls"
    and the "2" suffix resolves to season 2.
    """
    show = tmp_path / "Widget Falls 2"
    show.mkdir()
    (show / "[SubGroup] Widget Falls - 05 [1080p].mkv").write_text("x")

    primary_junk = _result(1, "Zzz Nonsense Thing", "1999")
    fallback_exact = _result(2, "Widget Falls", "2023")

    primary = _FixedResultProvider("tmdb", {"widget falls 2": [primary_junk]})
    fallback = _FixedResultProvider("tvdb", {"widget falls 2": [fallback_exact]})

    orch = BatchTVOrchestrator(
        primary, tmp_path, TVLibraryDiscoveryService(), fallback_provider=fallback
    )
    states = orch.discover_shows()

    assert len(states) == 1
    state = states[0]
    assert state.match_origin == "fallback"
    assert state.media_info.get("id") == 2
    assert state.season_assignment == 2
