"""Build TV episode-guide and queue-preflight projections."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ...parsing import build_tv_name
from ...engine import PreviewItem, ScanState
from ..models import (
    EpisodeGuide,
    EpisodeGuideRow,
    EpisodeGuideSummary,
    EpisodeSlotChoice,
    QueuePreflightSummary,
    UnmappedFileRow,
)

if TYPE_CHECKING:
    from ...engine.episode_assignments import EpisodeAssignmentTable


class EpisodeMappingService:
    """Project raw scan preview state into episode-guide workflow state."""

    def episode_choices(self, state: ScanState) -> list[tuple[str, int, int]]:
        """Return selectable episodes within the currently matched show."""
        keys: set[tuple[int, int]] = set()
        if state.scanner is not None:
            keys.update(state.scanner.episode_meta)
        completeness = state.completeness
        if completeness is not None:
            if completeness.specials is not None:
                keys.update((0, episode) for episode, _title in completeness.specials.matched_episodes)
                keys.update((0, episode) for episode, _title in completeness.specials.missing)
            for season_num, season in completeness.seasons.items():
                keys.update((season_num, episode) for episode, _title in season.matched_episodes)
                keys.update((season_num, episode) for episode, _title in season.missing)
            keys.update((season, episode) for season, episode, _title in completeness.total_missing)
        for preview in state.preview_items:
            if preview.season is None:
                continue
            keys.update((preview.season, episode) for episode in preview.episodes)

        choices: list[tuple[str, int, int]] = []
        for season, episode in sorted(keys):
            title = self._episode_title(state, (season, episode)) or f"Episode {episode}"
            choices.append((f"S{season:02d}E{episode:02d} - {title}", season, episode))
        return choices

    def remap_preview_to_episode(
        self,
        state: ScanState,
        preview: PreviewItem,
        *,
        season: int,
        episode: int,
    ) -> PreviewItem:
        """Map one preview item to a different episode in the same show."""
        old_name = preview.new_name or ""
        title = self._episode_title(state, (season, episode)) or f"Episode {episode}"
        show_name = state.media_info.get("name") or state.media_info.get("title") or state.folder.name
        year = str(state.media_info.get("year") or "")

        preview.season = season
        preview.episodes = [episode]
        preview.status = "OK"
        preview.episode_confidence = 1.0
        preview.new_name = build_tv_name(
            show_name,
            year,
            season,
            [episode],
            [title],
            preview.original.suffix,
        )
        preview.target_dir = self._target_dir_for_episode(state, preview, season)
        self._retarget_companions(preview, old_name)
        return preview

    # ── table-backed mutations ──────────────────────────────────────

    @staticmethod
    def _require_table(state: ScanState) -> "EpisodeAssignmentTable":
        table = state.assignments
        if table is None:
            raise ValueError("This show has no assignment table (rescan needed)")
        return table

    def reproject(self, state: ScanState) -> None:
        from ...engine._episode_projection import project_preview_items

        table = self._require_table(state)
        state.preview_items = project_preview_items(
            table,
            show_info=state.media_info,
            root=state.folder,
            media_fields={
                "media_id": state.show_id,
                "media_name": state.media_info.get("name"),
            },
        )
        if state.scanner is not None:
            checked = {
                index for index, item in enumerate(state.preview_items)
                if item.status == "OK"
            }
            state.completeness = state.scanner.get_completeness(
                state.preview_items, checked_indices=checked,
            )
        state.reset_gui_state()

    def assign_file(
        self,
        state: ScanState,
        preview: PreviewItem,
        *,
        season: int,
        episodes: list[int],
    ) -> None:
        from ...engine.episode_assignments import ORIGIN_MANUAL

        table = self._require_table(state)
        if preview.file_id is None:
            raise ValueError("Preview row is not linked to a scanned file")
        table.assign(
            preview.file_id, season, episodes,
            origin=ORIGIN_MANUAL, displace=True,
        )
        self.reproject(state)

    def unassign_file(self, state: ScanState, preview: PreviewItem) -> None:
        table = self._require_table(state)
        if preview.file_id is None:
            raise ValueError("Preview row is not linked to a scanned file")
        table.unassign(preview.file_id)
        self.reproject(state)

    def approve_file(self, state: ScanState, preview: PreviewItem) -> None:
        table = self._require_table(state)
        if preview.file_id is None:
            raise ValueError("Preview row is not linked to a scanned file")
        table.set_approved(preview.file_id)
        self.reproject(state)

    def approve_all(self, state: ScanState) -> int:
        table = self._require_table(state)
        count = 0
        for preview in state.preview_items:
            if preview.is_episode_review and preview.file_id is not None:
                table.set_approved(preview.file_id)
                count += 1
        if count:
            self.reproject(state)
        return count

    def resolve_conflict(
        self, state: ScanState, season: int, episode: int, winner: PreviewItem,
    ) -> None:
        table = self._require_table(state)
        if winner.file_id is None:
            raise ValueError("Preview row is not linked to a scanned file")
        table.resolve_conflict(season, episode, winner_file_id=winner.file_id)
        self.reproject(state)

    # ── choices for the dialogs ─────────────────────────────────────

    def episode_slot_choices(self, state: ScanState) -> list[EpisodeSlotChoice]:
        table = self._require_table(state)
        choices: list[EpisodeSlotChoice] = []
        for key, slot in sorted(table.slots.items()):
            claimant = table.claimant(*key)
            choices.append(EpisodeSlotChoice(
                season=slot.season,
                episode=slot.episode,
                title=slot.title,
                claimed_by=claimant.path.name if claimant else None,
            ))
        return choices

    def unassigned_file_previews(self, state: ScanState) -> list[PreviewItem]:
        table = self._require_table(state)
        unassigned_ids = {entry.file_id for entry, _ in table.unassigned_files()}
        return [
            preview for preview in state.preview_items
            if preview.file_id in unassigned_ids
        ]

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
                reason = preview.status
                if state.assignments is not None and preview.file_id is not None:
                    reason = state.assignments.unassigned_reasons.get(
                        preview.file_id, preview.status,
                    )
                guide.unmapped_primary_files.append(
                    UnmappedFileRow(
                        original=preview.original,
                        reason=reason,
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
            review_required=sum(1 for row in guide.rows if row.status == "Review"),
        )
        return guide

    def build_queue_preflight(self, state: ScanState) -> QueuePreflightSummary:
        guide = self.build_episode_guide(state)
        actionable_primary_ids: set[int] = set()
        companion_count = 0
        review_required = 0
        for row in guide.rows:
            preview = row.primary_file
            if preview is None or preview.is_conflict or not preview.is_actionable:
                continue
            if preview.is_review:
                review_required += 1
                continue
            if id(preview) in actionable_primary_ids:
                continue
            actionable_primary_ids.add(id(preview))
            companion_count += len(preview.companions)

        conflicts = guide.summary.conflicts
        if state.assignments is not None:
            conflicts = len(state.assignments.conflicts())
        mapped_primary_files = len(actionable_primary_ids)
        enabled = bool(mapped_primary_files and conflicts == 0 and review_required == 0)
        parts = [
            f"{mapped_primary_files} mapped file{'s' if mapped_primary_files != 1 else ''}",
            f"{companion_count} companion{'s' if companion_count != 1 else ''}",
            f"{guide.summary.missing_episodes} missing",
            f"{guide.summary.unmapped_primary_files} unmapped",
            f"{guide.summary.orphan_companion_files} orphan companion{'s' if guide.summary.orphan_companion_files != 1 else ''}",
            f"{conflicts} conflict{'s' if conflicts != 1 else ''}",
            f"{review_required} review",
        ]
        return QueuePreflightSummary(
            enabled=enabled,
            mapped_primary_files=mapped_primary_files,
            companion_files=companion_count,
            missing_episodes=guide.summary.missing_episodes,
            unmapped_primary_files=guide.summary.unmapped_primary_files,
            orphan_companion_files=guide.summary.orphan_companion_files,
            conflicts=conflicts,
            review_required=review_required,
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
        return f"{pct}%"

    @staticmethod
    def _target_dir_for_episode(state: ScanState, preview: PreviewItem, season: int) -> Path:
        target_dir = preview.target_dir or preview.original.parent
        parent = target_dir
        if target_dir.name.lower().startswith("season ") or target_dir.name.lower() == "specials":
            parent = target_dir.parent
        elif preview.target_dir is None:
            parent = state.folder
        folder_name = "Specials" if season == 0 else f"Season {season:02d}"
        return parent / folder_name

    @staticmethod
    def _retarget_companions(preview: PreviewItem, old_video_name: str) -> None:
        if preview.new_name is None:
            return
        old_stem = Path(old_video_name).stem if old_video_name else preview.original.stem
        new_stem = Path(preview.new_name).stem
        for companion in preview.companions:
            if companion.new_name and companion.new_name.startswith(old_stem):
                companion.new_name = new_stem + companion.new_name[len(old_stem):]
            else:
                companion.new_name = new_stem + companion.original.suffix

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
