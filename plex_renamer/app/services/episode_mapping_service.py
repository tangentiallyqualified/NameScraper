"""Build TV episode-guide projections."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from ...engine import PreviewItem, ScanState
from ...engine.models import TVScannerOperations, TVScanStateScanner
from ..models import (
    EpisodeGuide,
    EpisodeGuideRow,
    EpisodeGuideSummary,
    EpisodeSlotChoice,
    UnmappedFileRow,
)

if TYPE_CHECKING:
    from ...engine.episode_assignments import EpisodeAssignmentTable


class EpisodeMappingService:
    """Project raw scan preview state into episode-guide workflow state."""

    # ── table-backed mutations ──────────────────────────────────────

    @staticmethod
    def _require_table(state: ScanState) -> EpisodeAssignmentTable:
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
            scanner = cast(TVScannerOperations, state.scanner)
            checked = {
                index for index, item in enumerate(state.preview_items) if item.status == "OK"
            }
            state.completeness = scanner.get_completeness(
                state.preview_items,
                checked_indices=checked,
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
            preview.file_id,
            season,
            episodes,
            origin=ORIGIN_MANUAL,
            displace=True,
        )
        self.reproject(state)

    def assign_or_extend_file(
        self,
        state: ScanState,
        preview: PreviewItem,
        *,
        season: int,
        episode: int,
    ) -> None:
        """Assign one episode, extending an adjacent run in the same season.
        Otherwise replace the file's prior run with that episode.
        """
        from ...engine.episode_assignments import ORIGIN_MANUAL

        table = self._require_table(state)
        if preview.file_id is None:
            raise ValueError("Preview row is not linked to a scanned file")
        episodes = [episode]
        existing = table.assignment_for(preview.file_id)
        if existing is not None and existing.season == season:
            run = sorted(existing.episodes)
            if episode == run[0] - 1 or episode == run[-1] + 1:
                episodes = sorted(set(run) | {episode})
        table.assign(
            preview.file_id,
            season,
            episodes,
            origin=ORIGIN_MANUAL,
            displace=True,
        )
        self.reproject(state)

    def unassign_file(self, state: ScanState, preview: PreviewItem) -> None:
        table = self._require_table(state)
        if preview.file_id is None:
            raise ValueError("Preview row is not linked to a scanned file")
        table.unassign(preview.file_id)
        self.reproject(state)

    def merge_files(
        self,
        state: ScanState,
        ordered_file_ids: list[int],
        *,
        season: int,
        episodes: list[int],
    ) -> None:
        """Manually group *ordered_file_ids* (merge order) into one episode."""
        from ...engine.episode_assignments import ORIGIN_MANUAL

        table = self._require_table(state)
        table.group_parts(ordered_file_ids, season, episodes, origin=ORIGIN_MANUAL)
        self.reproject(state)

    def ungroup_file(self, state: ScanState, preview: PreviewItem) -> None:
        """Dissolve the part group anchored on *preview*'s file."""
        table = self._require_table(state)
        if preview.file_id is None:
            raise ValueError("Preview row is not linked to a scanned file")
        table.ungroup_parts(preview.file_id)
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

    def apply_assignments(
        self,
        state: ScanState,
        pairs: list[tuple[int, int, int]],
    ) -> tuple[int, int]:
        """Apply (file_id, season, episode) pairs as one batch (Bulk Assign).

        Thin wrapper over ``apply_bulk`` with no unassigns; kept so existing
        callers are unaffected.
        """
        return self.apply_bulk(state, assign_pairs=pairs, unassign_file_ids=[])

    def apply_bulk(
        self,
        state: ScanState,
        *,
        assign_pairs: list[tuple[int, int, int]],
        unassign_file_ids: list[int],
    ) -> tuple[int, int]:
        """One-shot Bulk Assign apply: unassign first, then grouped assigns,
        exactly one reproject. Returns (applied_assignments, skipped).

        Assign pairs are grouped by (file_id, season) into one
        ``table.assign(..., displace=True)`` call per file, so a file with
        multiple (file_id, season, episode) pairs lands as one contiguous
        multi-episode run instead of overwriting itself pair by pair.
        """
        from ...engine.episode_assignments import ORIGIN_MANUAL

        table = self._require_table(state)
        changed = False
        for file_id in unassign_file_ids:
            table.unassign(file_id)
            changed = True
        grouped: dict[tuple[int, int], list[int]] = {}
        for file_id, season, episode in assign_pairs:
            grouped.setdefault((file_id, season), []).append(episode)
        applied = 0
        skipped = 0
        for (file_id, season), episodes in grouped.items():
            try:
                table.assign(
                    file_id,
                    season,
                    sorted(set(episodes)),
                    origin=ORIGIN_MANUAL,
                    displace=True,
                )
            except ValueError:
                skipped += 1
                continue
            applied += 1
            changed = True
        if changed:
            self.reproject(state)
        return applied, skipped

    def unassign_all(self, state: ScanState) -> int:
        """Unassign every assigned file with one reproject (bulk Unassign All)."""
        table = self._require_table(state)
        file_ids = [assignment.file_id for assignment in table.assignments()]
        for file_id in file_ids:
            table.unassign(file_id)
        if file_ids:
            self.reproject(state)
        return len(file_ids)

    def resolve_conflict(
        self,
        state: ScanState,
        season: int,
        episode: int,
        winner: PreviewItem,
    ) -> None:
        table = self._require_table(state)
        if winner.file_id is None:
            raise ValueError("Preview row is not linked to a scanned file")
        table.resolve_conflict(season, episode, winner_file_id=winner.file_id)
        self.reproject(state)

    def suggest_assignments(
        self,
        state: ScanState,
        file_ids: list[int],
        *,
        taken: set[tuple[int, int]],
    ) -> list[tuple[int, int, int]]:
        """Evidence-based staging suggestions for Bulk Assign's Auto-map.

        Uses each file's scan-time parse evidence only — a file with no
        parsed episodes (or whose target slot is missing or already taken)
        is skipped, never positional-filled: silent wrong mappings cost far
        more than leaving a file unstaged.

        ``taken`` is the SOLE source of already-occupied slots — this method
        deliberately does NOT also consult ``table.claimed_slots()``. The
        table doesn't know about in-progress panel staging (e.g. a file the
        caller has staged to unassign); the caller owns availability and
        must pass a ``taken`` set that already reflects it. Folding in
        ``table.claimed_slots()`` here would re-block slots the caller just
        freed, breaking the Unassign-all -> Auto-map-remaining round trip.
        """
        table = self._require_table(state)
        claimed = set(taken)
        suggestions: list[tuple[int, int, int]] = []
        for file_id in file_ids:
            entry = table.files.get(file_id)
            if entry is None or not entry.parsed_episodes:
                continue
            season = entry.season_hint if entry.season_hint is not None else entry.folder_season
            if season is None:
                continue
            keys = [(season, episode) for episode in entry.parsed_episodes]
            if any(key not in table.slots or key in claimed for key in keys):
                continue
            claimed.update(keys)
            suggestions.extend((file_id, season, episode) for _season, episode in keys)
        return suggestions

    # ── choices for the dialogs ─────────────────────────────────────

    def episode_slot_choices(self, state: ScanState) -> list[EpisodeSlotChoice]:
        table = self._require_table(state)
        choices: list[EpisodeSlotChoice] = []
        for key, slot in sorted(table.slots.items()):
            claims = table.claims(*key)
            claimants = tuple(
                (claim.file_id, table.files[claim.file_id].path.name) for claim in claims
            )
            claimed_file_id = claims[0].file_id if len(claims) == 1 else None
            claimant = table.files.get(claimed_file_id) if claimed_file_id is not None else None
            choices.append(
                EpisodeSlotChoice(
                    season=slot.season,
                    episode=slot.episode,
                    title=slot.title,
                    claimed_by=claimant.path.name if claimant else None,
                    claimed_file_id=claimed_file_id,
                    claimants=claimants,
                )
            )
        return choices

    def all_primary_file_previews(self, state: ScanState) -> list[PreviewItem]:
        """Every scanned primary file, assigned or not (Bulk Assign pool)."""
        self._require_table(state)
        return [p for p in state.preview_items if p.file_id is not None]

    def unassigned_file_previews(self, state: ScanState) -> list[PreviewItem]:
        table = self._require_table(state)
        unassigned_ids = {entry.file_id for entry, _ in table.unassigned_files()}
        return [preview for preview in state.preview_items if preview.file_id in unassigned_ids]

    def unassigned_file_choices(self, state: ScanState) -> list[tuple[int, str]]:
        """Return (file_id, display_label) pairs for the file picker dialog."""
        table = self._require_table(state)
        result: list[tuple[int, str]] = []
        for candidate in self.unassigned_file_previews(state):
            if candidate.file_id is None:
                continue
            reason = table.unassigned_reasons.get(candidate.file_id, "")
            label = f"{candidate.original.name}  ({reason})" if reason else candidate.original.name
            result.append((candidate.file_id, label))
        return result

    def shareable_file_choices(
        self,
        state: ScanState,
        *,
        season: int,
        episode: int,
    ) -> list[tuple[int, str]]:
        """Assigned files whose run is contiguous-adjacent to (season, episode).

        These can be extended into the target episode without unassigning
        them from their current run.
        """
        table = self._require_table(state)
        result: list[tuple[int, str]] = []
        for assignment in table.assignments():
            if assignment.season != season:
                continue
            run = sorted(assignment.episodes)
            if episode == run[0] - 1 or episode == run[-1] + 1:
                entry = table.files[assignment.file_id]
                result.append((assignment.file_id, entry.path.name))
        return result

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

        # Conflicted slots render one row per claimant; number them so the
        # pair reads as ONE contested episode, not two copies of it (RC39).
        conflict_totals: dict[tuple[int, int], int] = {}
        for preview in state.preview_items:
            if preview.is_conflict and self._is_episode_mapped(preview):
                for episode in preview.episodes:
                    key = (preview.season or 0, episode)
                    conflict_totals[key] = conflict_totals.get(key, 0) + 1
        conflict_seen: dict[tuple[int, int], int] = {}

        for preview in state.preview_items:
            if preview.is_duplicate:
                guide.duplicate_files.append(
                    UnmappedFileRow(
                        original=preview.original,
                        reason=preview.status.removeprefix("DUPLICATE: "),
                        preview=preview,
                    )
                )
                continue
            if not self._is_episode_mapped(preview):
                reason = preview.status
                if state.assignments is not None and preview.file_id is not None:
                    reason = state.assignments.unassigned_reasons.get(
                        preview.file_id,
                        preview.status,
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
                confidence_label = self._confidence_label(preview)
                if preview.is_conflict and conflict_totals.get(key, 0) > 1:
                    conflict_seen[key] = conflict_seen.get(key, 0) + 1
                    confidence_label = (
                        f"Conflict — file {conflict_seen[key]} of {conflict_totals[key]}"
                    )
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
                        confidence_label=confidence_label,
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
            mapped_episodes=sum(
                1 for row in guide.rows if row.primary_file is not None and row.status != "Conflict"
            ),
            mapped_primary_files=len(mapped_primary_ids),
            companion_files=companion_count,
            missing_episodes=sum(1 for row in guide.rows if row.status == "Missing File"),
            unmapped_primary_files=len(guide.unmapped_primary_files),
            orphan_companion_files=len(guide.orphan_companion_files),
            conflicts=conflict_count,
            review_required=sum(1 for row in guide.rows if row.status == "Review"),
            duplicate_files=len(guide.duplicate_files),
        )
        return guide

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
    def _episode_meta_value(state: ScanState, key: tuple[int, int], name: str) -> str:
        if state.scanner is None:
            return ""
        scanner = cast(TVScanStateScanner, state.scanner)
        meta = scanner.episode_meta.get(key, {})
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
        for candidates in (
            season.matched_episodes,
            season.review_episodes,
            season.missing,
        ):
            for candidate_episode, title in candidates:
                if candidate_episode == episode:
                    return title
        return ""

    @staticmethod
    def _missing_episode_rows(state: ScanState) -> list[tuple[int, int, str]]:
        completeness = state.completeness
        if completeness is None:
            return []
        # total_missing covers regular seasons only (specials are excluded from
        # the completeness %); always append specials so missing S0 rows render.
        rows: list[tuple[int, int, str]] = list(completeness.total_missing)
        if completeness.specials is not None:
            rows.extend((0, episode, title) for episode, title in completeness.specials.missing)
        return rows
