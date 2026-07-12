from __future__ import annotations

import unittest
from pathlib import Path

from plex_renamer.app.services.episode_mapping_service import EpisodeMappingService
from plex_renamer.app.services.episode_projection_cache import EpisodeProjectionCacheService
from plex_renamer.engine import PreviewItem, ScanState


def _state_with_preview(status: str = "OK") -> ScanState:
    return ScanState(
        folder=Path("C:/library/tv/Example"),
        media_info={"id": 101, "name": "Example Show", "year": "2024"},
        preview_items=[
            PreviewItem(
                original=Path("C:/library/tv/Example/Season 01/Example.S01E01.mkv"),
                new_name="Example Show (2024) - S01E01 - Pilot.mkv",
                target_dir=Path("C:/library/tv/Example Show (2024)/Season 01"),
                season=1,
                episodes=[1],
                status=status,
            )
        ],
        scanned=True,
        confidence=1.0,
    )


def test_episode_projection_cache_reuses_prepared_guide_until_state_changes():
    service = EpisodeProjectionCacheService(EpisodeMappingService())
    state = _state_with_preview()

    prepared = service.prepare_state(state)
    reused = service.guide_for_state(state)

    assert reused is prepared
    assert service.cache_size == 1

    state.preview_items[0].status = "REVIEW: episode confidence below threshold"
    state.preview_items[0].episode_confidence = 0.42
    rebuilt = service.guide_for_state(state)

    assert rebuilt is not prepared
    assert rebuilt.rows[0].status == "Review"


def test_episode_projection_cache_invalidate_state_forces_rebuild():
    service = EpisodeProjectionCacheService(EpisodeMappingService())
    state = _state_with_preview()

    prepared = service.prepare_state(state)
    service.invalidate_state(state)
    rebuilt = service.guide_for_state(state)

    assert rebuilt is not prepared
    assert service.cache_size == 1


def test_episode_projection_cache_signature_tracks_match_and_episode_mapping_state():
    service = EpisodeProjectionCacheService(EpisodeMappingService())
    state = _state_with_preview()

    first_signature = service.signature_for_state(state)
    state.media_info = {"id": 202, "name": "Replacement Show", "year": "2024"}
    match_signature = service.signature_for_state(state)
    state.preview_items[0].season = 2
    state.preview_items[0].episodes = [3]
    mapping_signature = service.signature_for_state(state)

    assert match_signature != first_signature
    assert mapping_signature != match_signature


class CachedPeekAndStoreTests(unittest.TestCase):
    """Plan 5: Qt-free primitives backing the async guide pipeline."""

    def _state(self, name: str = "Show") -> ScanState:
        state = ScanState(
            folder=Path(f"C:/library/tv/{name}"),
            media_info={"id": 5, "name": name, "year": "2024"},
        )
        state.scanned = True
        return state

    def test_cached_guide_for_state_returns_none_when_unbuilt(self):
        service = EpisodeProjectionCacheService()
        self.assertIsNone(service.cached_guide_for_state(self._state()))

    def test_cached_guide_for_state_hits_after_prepare_and_misses_after_mutation(self):
        service = EpisodeProjectionCacheService()
        state = self._state()
        built = service.prepare_state(state)
        self.assertIs(service.cached_guide_for_state(state), built)
        state.media_info["name"] = "Renamed Show"   # signature-relevant mutation
        self.assertIsNone(service.cached_guide_for_state(state))

    def test_build_guide_with_signature_matches_prebuild_signature(self):
        service = EpisodeProjectionCacheService()
        state = self._state()
        expected_signature = service.signature_for_state(state)
        guide, signature = service.build_guide_with_signature(state)
        self.assertEqual(signature, expected_signature)
        self.assertIsNotNone(guide)

    def test_store_guide_roundtrips_through_cached_peek(self):
        service = EpisodeProjectionCacheService()
        state = self._state()
        guide, signature = service.build_guide_with_signature(state)
        service.store_guide(state, guide, signature)
        self.assertIs(service.cached_guide_for_state(state), guide)
        self.assertEqual(service.cache_size, 1)
