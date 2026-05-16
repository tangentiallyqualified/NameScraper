"""Cache scan-time TV episode-guide projections for batch UI rendering."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ...engine import ScanState
from ..models import EpisodeGuide
from .episode_mapping_service import EpisodeMappingService


@dataclass(slots=True)
class _CachedEpisodeGuide:
    signature: tuple
    guide: EpisodeGuide


class EpisodeProjectionCacheService:
    def __init__(self, episode_mapping: EpisodeMappingService | None = None) -> None:
        self._episode_mapping = episode_mapping or EpisodeMappingService()
        self._cache: dict[str, _CachedEpisodeGuide] = {}

    @property
    def cache_size(self) -> int:
        return len(self._cache)

    def prepare_states(self, states: Iterable[ScanState]) -> None:
        for state in states:
            if state.preview_items:
                self.prepare_state(state)

    def prepare_state(self, state: ScanState) -> EpisodeGuide:
        signature = self.signature_for_state(state)
        guide = self._episode_mapping.build_episode_guide(state)
        self._cache[self._key_for_state(state)] = _CachedEpisodeGuide(signature, guide)
        return guide

    def guide_for_state(self, state: ScanState) -> EpisodeGuide:
        key = self._key_for_state(state)
        signature = self.signature_for_state(state)
        cached = self._cache.get(key)
        if cached is not None and cached.signature == signature:
            return cached.guide
        return self.prepare_state(state)

    def refresh_state(self, state: ScanState) -> EpisodeGuide:
        self.invalidate_state(state)
        return self.prepare_state(state)

    def invalidate_state(self, state: ScanState) -> None:
        self._cache.pop(self._key_for_state(state), None)

    def invalidate_all(self) -> None:
        self._cache.clear()

    def signature_for_state(self, state: ScanState) -> tuple:
        preview_signature = tuple(
            (
                str(preview.original),
                preview.new_name,
                str(preview.target_dir) if preview.target_dir is not None else "",
                preview.season,
                tuple(preview.episodes),
                preview.status,
                round(preview.episode_confidence, 4),
                tuple(
                    (str(companion.original), companion.new_name, companion.file_type)
                    for companion in preview.companions
                ),
            )
            for preview in state.preview_items
        )
        completeness = state.completeness
        completeness_signature = None
        if completeness is not None:
            completeness_signature = (
                tuple(
                    (
                        season_num,
                        season.expected,
                        season.matched,
                        tuple(season.missing),
                        tuple(season.matched_episodes),
                    )
                    for season_num, season in sorted(completeness.seasons.items())
                ),
                None
                if completeness.specials is None
                else (
                    completeness.specials.expected,
                    completeness.specials.matched,
                    tuple(completeness.specials.missing),
                    tuple(completeness.specials.matched_episodes),
                ),
                completeness.total_expected,
                completeness.total_matched,
                tuple(completeness.total_missing),
            )
        scanner_meta = ()
        if state.scanner is not None:
            scanner_meta = tuple(
                (
                    key,
                    tuple(
                        sorted(
                            (str(name), str(value)) for name, value in meta.items()
                        )
                    ),
                )
                for key, meta in sorted(state.scanner.episode_meta.items())
            )
        orphan_signature = tuple(
            (str(companion.original), companion.new_name, companion.file_type)
            for companion in state.orphan_companion_files
        )
        return (
            state.show_id,
            state.media_info.get("name") or state.media_info.get("title") or "",
            state.media_info.get("year") or "",
            state.active_episode_source,
            tuple(sorted(state.season_names.items())),
            preview_signature,
            completeness_signature,
            scanner_meta,
            orphan_signature,
        )

    @staticmethod
    def _key_for_state(state: ScanState) -> str:
        source = str(state.source_file) if state.source_file is not None else ""
        return f"{state.folder}|{state.show_id}|{source}"
