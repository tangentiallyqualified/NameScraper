"""Batch auto-accept guards (M-H1 / M-H2 from the 2026-07-10 review).

M-H1: the TV winner's score must be clamped to the same [0, 1] scale as the
runner-up before tie detection, and the stored confidence must never exceed
1.0 — otherwise two identically-named shows (Ghosts US vs UK) fake a 0.15
margin and silently auto-accept the more popular one.

M-H2: the batch movie path must run the same
``apply_movie_confidence_adjustments`` caps as the interactive scanner, so a
sequel-number mismatch (Iron Man folder -> Iron Man 2 result) stays capped
below auto-accept.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from plex_renamer.app.services import (
    MovieLibraryDiscoveryService,
    TVLibraryDiscoveryService,
)
from plex_renamer.app.services.command_gating_service import CommandGatingService
from plex_renamer.engine._batch_orchestrators import (
    BatchMovieOrchestrator,
    BatchTVOrchestrator,
)
from plex_renamer.engine.matching import MOVIE_CAP_SEQUEL_MISMATCH
from plex_renamer.engine.models import PreviewItem, ScanState
from plex_renamer.providers import SeasonMapUnavailableError


class _FakeTMDBSameNameShows:
    """Two shows with the SAME name (US/UK remake pair), no usable details."""

    provider_name = "tmdb"
    language = "en-US"

    GHOSTS_US = {
        "id": 111,
        "name": "Ghosts",
        "year": "2021",
        "poster_path": None,
        "overview": "US remake (more popular, ranked first)",
    }
    GHOSTS_UK = {
        "id": 222,
        "name": "Ghosts",
        "year": "2019",
        "poster_path": None,
        "overview": "UK original",
    }

    def search_tv_batch(self, queries, progress_callback=None):
        results = []
        for i, _query in enumerate(queries, 1):
            if progress_callback:
                progress_callback(i, len(queries))
            results.append([self.GHOSTS_US, self.GHOSTS_UK])
        return results

    def get_tv_details(self, show_id):
        return {}

    def get_season_map(self, show_id):
        return {}, 0

    def get_alternative_titles(self, media_id, media_type="tv"):
        return []


class _ProviderRaising:
    provider_name = "tmdb"

    def get_season_map(self, show_id: int) -> tuple[dict, int]:
        raise SeasonMapUnavailableError(f"tmdb season map unavailable for {show_id}")


class _ProviderExploding:
    provider_name = "tmdb"

    def get_season_map(self, show_id: int) -> tuple[dict, int]:
        raise RuntimeError("provider exploded")


class _DiscoveryMapOutageProvider:
    provider_name = "tmdb"
    language = "en-US"
    MATCH = {
        "id": 7,
        "name": "Example Show",
        "year": "2024",
        "poster_path": None,
        "overview": "",
    }

    def search_tv_batch(self, queries, progress_callback=None):
        return [[self.MATCH] for _query in queries]

    def get_tv_details(self, show_id):
        return {"id": show_id, "seasons": [], "number_of_episodes": 1}

    def get_alternative_titles(self, media_id, media_type="tv"):
        return []

    def get_season_map(self, show_id):
        raise SeasonMapUnavailableError(f"tmdb season map unavailable for {show_id}")


class _DiscoveryUnexpectedFailureProvider(_DiscoveryMapOutageProvider):
    def get_season_map(self, show_id):
        raise RuntimeError("unexpected matching defect")


def _scan_with_provider(tmp_path: Path, provider: object) -> ScanState:
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
        provider,  # type: ignore[arg-type]
        tmp_path,
        discovery_service=TVLibraryDiscoveryService(),
    )
    orchestrator.states = [state]
    orchestrator.scan_all()
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
    assert state.check_vars == {}
    assert (
        not CommandGatingService().evaluate_scan_state(state, allow_show_level_queue=True).enabled
    )


def test_discovery_abstains_from_optional_episode_evidence_during_map_outage(
    tmp_path: Path,
) -> None:
    show = tmp_path / "Example Show (2024)"
    show.mkdir()
    (show / "Example.Show.S01E01.Pilot.mkv").write_text("x")
    orchestrator = BatchTVOrchestrator(
        _DiscoveryMapOutageProvider(),
        tmp_path,
        discovery_service=TVLibraryDiscoveryService(),
    )

    states = orchestrator.discover_shows()

    assert len(states) == 1
    assert states[0].show_id == 7
    assert states[0].scan_error is None
    orchestrator.scan_all()
    assert states[0].scan_error == "Episode guide is unavailable; retry the provider scan."


def test_discovery_does_not_swallow_unexpected_episode_evidence_defects(
    tmp_path: Path,
) -> None:
    show = tmp_path / "Example Show (2024)"
    show.mkdir()
    (show / "Example.Show.S01E01.Pilot.mkv").write_text("x")
    orchestrator = BatchTVOrchestrator(
        _DiscoveryUnexpectedFailureProvider(),
        tmp_path,
        discovery_service=TVLibraryDiscoveryService(),
    )

    with pytest.raises(RuntimeError, match="unexpected matching defect"):
        orchestrator.discover_shows()


class SameNameShowTieDetectionTests(unittest.TestCase):
    def test_same_name_shows_without_year_hint_flag_a_tie(self):
        """A folder named just "Ghosts" (no year) matching two exact-name
        shows must surface tie_detected, not silently auto-accept the more
        popular one at an out-of-scale confidence."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            show = root / "Ghosts"
            show.mkdir()
            for i in range(1, 4):
                (show / f"Ghosts.S01E{i:02d}.mkv").write_text("x")

            orchestrator = BatchTVOrchestrator(
                _FakeTMDBSameNameShows(),
                root,
                discovery_service=TVLibraryDiscoveryService(),
            )
            states = orchestrator.discover_shows()

            self.assertEqual(len(states), 1)
            state = states[0]
            self.assertLessEqual(
                state.confidence,
                1.0,
                f"confidence must stay on the [0,1] scale, got {state.confidence}",
            )
            self.assertTrue(
                state.tie_detected,
                "two exact-name candidates with no distinguishing evidence "
                "must be flagged as a tie",
            )


class _FakeTMDBSequelMovie:
    """Search returns the sequel first for an Iron Man (2008) query."""

    language = "en-US"

    IRON_MAN_2 = {
        "id": 333,
        "title": "Iron Man 2",
        "year": "2010",
        "poster_path": None,
        "overview": "the sequel, ranked first",
    }

    def search_movies_batch(self, queries, progress_callback=None):
        results = []
        for i, _query in enumerate(queries, 1):
            if progress_callback:
                progress_callback(i, len(queries))
            results.append([self.IRON_MAN_2])
        return results

    def get_movie_details(self, movie_id):
        return {}

    def get_alternative_titles(self, media_id, media_type="movie"):
        return []


class BatchMovieConfidenceCapTests(unittest.TestCase):
    def test_sequel_mismatch_capped_in_batch_discovery(self):
        """The sequel-number-mismatch cap the interactive MovieScanner
        applies must also run in batch discovery."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            movie = root / "Iron Man (2008)"
            movie.mkdir()
            (movie / "Iron Man (2008).mkv").write_text("x")

            orchestrator = BatchMovieOrchestrator(
                _FakeTMDBSequelMovie(),
                root,
                discovery_service=MovieLibraryDiscoveryService(),
            )
            states = orchestrator.discover_movies()

            self.assertEqual(len(states), 1)
            state = states[0]
            self.assertLessEqual(
                state.confidence,
                MOVIE_CAP_SEQUEL_MISMATCH,
                "sequel-number mismatch must cap batch confidence to "
                f"{MOVIE_CAP_SEQUEL_MISMATCH}, got {state.confidence}",
            )


class _FakeTMDBSameNameYearedShows:
    """Two shows with the SAME name distinguished only by year (Powerpuff).

    ``get_season_map`` returns matching season/episode-number evidence for
    BOTH candidates (real TMDB responses would differ, but the point here is
    the shared-boost mechanism): the episode-evidence adjustment in
    ``_tv_episode_evidence_adjustment`` adds the same ~0.22 to both raw
    scores, pushing 1.15/0.85 to ~1.37/1.07 — both past 1.0. This reproduces
    the real-library condition (alt-title/episode-evidence boosts stacking
    on top of the exact-title + year bonus) that made the old clamp-both
    approach erase the real 0.30 raw margin.
    """

    provider_name = "tmdb"
    language = "en-US"

    PPG_2016 = {
        "id": 61914,
        "name": "The Powerpuff Girls",
        "year": "2016",
        "poster_path": None,
        "overview": "reboot (ranked first by popularity)",
    }
    PPG_1998 = {
        "id": 607,
        "name": "The Powerpuff Girls",
        "year": "1998",
        "poster_path": None,
        "overview": "original",
    }

    def search_tv_batch(self, queries, progress_callback=None):
        results = []
        for i, _query in enumerate(queries, 1):
            if progress_callback:
                progress_callback(i, len(queries))
            results.append([self.PPG_2016, self.PPG_1998])
        return results

    def get_tv_details(self, show_id):
        return {}

    def get_season_map(self, show_id):
        return {1: {"titles": {1: "Ep1", 2: "Ep2", 3: "Ep3"}}}, 3

    def get_alternative_titles(self, media_id, media_type="tv"):
        return []


class YearHintTieBreakTests(unittest.TestCase):
    def test_year_hint_breaks_same_name_tie(self):
        """A folder carrying (1998) must pick the 1998 show WITHOUT a tie flag,
        even when boosts saturate both candidates' raw scores (RC: round-4
        Powerpuff regression from the 0cc2782 clamp)."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            show = root / "The Powerpuff Girls (1998) Season 1-6 S01-S06"
            show.mkdir()
            for i in range(1, 4):
                (show / f"The Powerpuff Girls (1998) - S01E{i:02d}.mkv").write_text("x")

            orchestrator = BatchTVOrchestrator(
                _FakeTMDBSameNameYearedShows(),
                root,
                discovery_service=TVLibraryDiscoveryService(),
            )
            states = orchestrator.discover_shows()

            self.assertEqual(len(states), 1)
            state = states[0]
            self.assertEqual(state.media_info.get("id"), 607, "must pick the 1998 show")
            self.assertFalse(
                state.tie_detected,
                "a year hint matching exactly one candidate is identity "
                "evidence — no user tiebreaker needed",
            )


if __name__ == "__main__":
    unittest.main()
