"""Build TV episode-guide and queue-preflight projections."""

from __future__ import annotations

from ...engine import PreviewItem, ScanState
from ..models import (
    EpisodeGuide,
    EpisodeGuideRow,
    EpisodeGuideSummary,
    QueuePreflightSummary,
    UnmappedFileRow,
)


class EpisodeMappingService:
    """Project raw scan preview state into episode-guide workflow state."""

    def build_episode_guide(self, state: ScanState) -> EpisodeGuide:
        source_id = state.active_episode_source or "tmdb"
        guide = EpisodeGuide(
            source_id=source_id,
            source_label=source_id.upper(),
        )
        mapped_keys: set[tuple[int, int]] = set()
        mapped_primary_ids: set[int] = set()
        companion_count = 0
        conflict_count = 0

        for preview in state.preview_items:
            if not self._is_episode_mapped(preview):
                guide.unmapped_primary_files.append(
                    UnmappedFileRow(
                        original=preview.original,
                        reason=preview.status,
                        preview=preview,
                    )
                )
                continue

            if preview.is_conflict:
                conflict_count += 1

            companions = list(preview.companions)
            companion_count += len(companions)
            mapped_primary_ids.add(id(preview))
            for episode in preview.episodes:
                key = (preview.season or 0, episode)
                mapped_keys.add(key)
                guide.rows.append(
                    EpisodeGuideRow(
                        season=key[0],
                        episode=episode,
                        title=self._episode_title(state, key),
                        source_id=source_id,
                        primary_file=preview,
                        companions=companions,
                        target_rename=preview.new_name or "",
                        status=self._status_label(preview),
                        confidence_label=self._confidence_label(preview),
                        overview=self._episode_meta_value(state, key, "overview"),
                        air_date=self._episode_meta_value(state, key, "air_date"),
                    )
                )

        for season, episode, title in self._missing_episode_rows(state):
            key = (season, episode)
            if key in mapped_keys:
                continue
            guide.rows.append(
                EpisodeGuideRow(
                    season=season,
                    episode=episode,
                    title=title,
                    source_id=source_id,
                    status="Missing File",
                    confidence_label="Missing File",
                )
            )

        guide.rows.sort(key=lambda row: (row.season, row.episode, row.status == "Missing File"))
        guide.orphan_companion_files = list(state.orphan_companion_files)
        guide.summary = EpisodeGuideSummary(
            mapped_episodes=sum(1 for row in guide.rows if row.primary_file is not None and row.status != "Conflict"),
            mapped_primary_files=len(mapped_primary_ids),
            companion_files=companion_count,
            missing_episodes=sum(1 for row in guide.rows if row.status == "Missing File"),
            unmapped_primary_files=len(guide.unmapped_primary_files),
            orphan_companion_files=len(guide.orphan_companion_files),
            conflicts=conflict_count,
        )
        return guide

    def build_queue_preflight(self, state: ScanState) -> QueuePreflightSummary:
        guide = self.build_episode_guide(state)
        actionable_primary_ids: set[int] = set()
        companion_count = 0
        for row in guide.rows:
            preview = row.primary_file
            if preview is None or preview.is_conflict or not preview.is_actionable:
                continue
            if id(preview) in actionable_primary_ids:
                continue
            actionable_primary_ids.add(id(preview))
            companion_count += len(preview.companions)

        mapped_primary_files = len(actionable_primary_ids)
        enabled = bool(mapped_primary_files and guide.summary.conflicts == 0)
        parts = [
            f"{mapped_primary_files} mapped file{'s' if mapped_primary_files != 1 else ''}",
            f"{companion_count} companion{'s' if companion_count != 1 else ''}",
            f"{guide.summary.missing_episodes} missing",
            f"{guide.summary.unmapped_primary_files} unmapped",
            f"{guide.summary.orphan_companion_files} orphan companion{'s' if guide.summary.orphan_companion_files != 1 else ''}",
            f"{guide.summary.conflicts} conflict{'s' if guide.summary.conflicts != 1 else ''}",
        ]
        return QueuePreflightSummary(
            enabled=enabled,
            mapped_primary_files=mapped_primary_files,
            companion_files=companion_count,
            missing_episodes=guide.summary.missing_episodes,
            unmapped_primary_files=guide.summary.unmapped_primary_files,
            orphan_companion_files=guide.summary.orphan_companion_files,
            conflicts=guide.summary.conflicts,
            summary_text=" - ".join(parts),
        )

    @staticmethod
    def _is_episode_mapped(preview: PreviewItem) -> bool:
        return (
            preview.season is not None
            and bool(preview.episodes)
            and not preview.is_skipped
            and not preview.is_unmatched
        )

    @staticmethod
    def _status_label(preview: PreviewItem) -> str:
        if preview.is_conflict:
            return "Conflict"
        if preview.is_review:
            return "Review"
        return "Mapped"

    @staticmethod
    def _confidence_label(preview: PreviewItem) -> str:
        if preview.is_conflict:
            return "Conflict"
        if preview.is_unmatched:
            return "No Match Found"
        pct = max(0, min(100, round(preview.episode_confidence * 100)))
        label = "High" if preview.episode_confidence >= 0.85 else "Review"
        return f"{label} {pct}%"

    @staticmethod
    def _episode_meta_value(state: ScanState, key: tuple[int, int], name: str) -> str:
        if state.scanner is None:
            return ""
        meta = state.scanner.episode_meta.get(key, {})
        value = meta.get(name, "")
        return str(value) if value else ""

    @classmethod
    def _episode_title(cls, state: ScanState, key: tuple[int, int]) -> str:
        meta_title = cls._episode_meta_value(state, key, "name")
        if meta_title:
            return meta_title
        completeness = state.completeness
        if completeness is None:
            return ""
        season_num, episode = key
        season = completeness.specials if season_num == 0 else completeness.seasons.get(season_num)
        if season is None:
            return ""
        for matched_episode, title in season.matched_episodes:
            if matched_episode == episode:
                return title
        for missing_episode, title in season.missing:
            if missing_episode == episode:
                return title
        return ""

    @staticmethod
    def _missing_episode_rows(state: ScanState) -> list[tuple[int, int, str]]:
        completeness = state.completeness
        if completeness is None:
            return []
        if completeness.total_missing:
            return list(completeness.total_missing)

        rows: list[tuple[int, int, str]] = []
        if completeness.specials is not None:
            rows.extend((0, episode, title) for episode, title in completeness.specials.missing)
        for season_num, season in completeness.seasons.items():
            rows.extend((season_num, episode, title) for episode, title in season.missing)
        return rows
