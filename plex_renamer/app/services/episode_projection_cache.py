"""Cache scan-time TV episode-guide projections for batch UI rendering."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol, TypeAlias, cast

from ...engine import ScanState
from ...engine.models import TVScanStateScanner
from ..models import EpisodeGuide
from .episode_mapping_service import EpisodeMappingService

EpisodeDetailSignature: TypeAlias = tuple[int, str]
CompanionProjectionSignature: TypeAlias = tuple[str, str, str]
PreviewProjectionSignature: TypeAlias = tuple[
    str,
    str | None,
    str,
    int | None,
    tuple[int, ...],
    str,
    float,
    tuple[CompanionProjectionSignature, ...],
]
SeasonProjectionSignature: TypeAlias = tuple[
    int,
    int,
    int,
    tuple[EpisodeDetailSignature, ...],
    tuple[EpisodeDetailSignature, ...],
]
SpecialsProjectionSignature: TypeAlias = tuple[
    int,
    int,
    tuple[EpisodeDetailSignature, ...],
    tuple[EpisodeDetailSignature, ...],
]
MissingEpisodeSignature: TypeAlias = tuple[int, int, str]
CompletenessProjectionSignature: TypeAlias = tuple[
    tuple[SeasonProjectionSignature, ...],
    SpecialsProjectionSignature | None,
    int,
    int,
    tuple[MissingEpisodeSignature, ...],
]
ScannerMetadataValueSignature: TypeAlias = tuple[str, str]
ScannerMetadataEntrySignature: TypeAlias = tuple[
    tuple[int, int], tuple[ScannerMetadataValueSignature, ...]
]
ScannerMetadataSignature: TypeAlias = tuple[ScannerMetadataEntrySignature, ...]
SeasonNameSignature: TypeAlias = tuple[int, str]
EpisodeProjectionSignature: TypeAlias = tuple[
    int | None,
    str,
    str,
    str,
    tuple[SeasonNameSignature, ...],
    tuple[PreviewProjectionSignature, ...],
    CompletenessProjectionSignature | None,
    ScannerMetadataSignature,
    tuple[CompanionProjectionSignature, ...],
]


class _ProjectionMediaState(Protocol):
    media_info: dict[str, str | int | None]


@dataclass(slots=True)
class _CachedEpisodeGuide:
    signature: EpisodeProjectionSignature
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

    def cached_guide_for_state(self, state: ScanState) -> EpisodeGuide | None:
        """Signature-checked peek: return the cached guide or None. Never builds."""
        cached = self._cache.get(self._key_for_state(state))
        if cached is not None and cached.signature == self.signature_for_state(state):
            return cached.guide
        return None

    def build_guide_with_signature(
        self, state: ScanState
    ) -> tuple[EpisodeGuide, EpisodeProjectionSignature]:
        """Build a guide plus the signature captured BEFORE the build.

        Safe to call off the GUI thread: pure reads over the state. If the
        state mutates mid-build, the pre-build signature no longer matches on
        the next peek, so the stored result degrades to a cache miss instead
        of a wrong hit.
        """
        signature = self.signature_for_state(state)
        return self._episode_mapping.build_episode_guide(state), signature

    def store_guide(
        self,
        state: ScanState,
        guide: EpisodeGuide,
        signature: EpisodeProjectionSignature,
    ) -> None:
        self._cache[self._key_for_state(state)] = _CachedEpisodeGuide(signature, guide)

    def refresh_state(self, state: ScanState) -> EpisodeGuide:
        self.invalidate_state(state)
        return self.prepare_state(state)

    def invalidate_state(self, state: ScanState) -> None:
        self._cache.pop(self._key_for_state(state), None)

    def invalidate_all(self) -> None:
        self._cache.clear()

    def signature_for_state(self, state: ScanState) -> EpisodeProjectionSignature:
        media_info = cast(_ProjectionMediaState, state).media_info
        preview_signature: tuple[PreviewProjectionSignature, ...] = tuple(
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
        completeness_signature: CompletenessProjectionSignature | None = None
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
        scanner_meta: ScannerMetadataSignature = ()
        if state.scanner is not None:
            scanner = cast(TVScanStateScanner, state.scanner)
            scanner_meta = tuple(
                (
                    key,
                    tuple(sorted((str(name), str(value)) for name, value in meta.items())),
                )
                for key, meta in sorted(scanner.episode_meta.items())
            )
        orphan_signature: tuple[CompanionProjectionSignature, ...] = tuple(
            (str(companion.original), companion.new_name, companion.file_type)
            for companion in state.orphan_companion_files
        )
        return (
            state.show_id,
            str(media_info.get("name") or media_info.get("title") or ""),
            str(media_info.get("year") or ""),
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
