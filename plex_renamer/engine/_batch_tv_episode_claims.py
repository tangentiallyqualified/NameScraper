"""Episode-claim reconciliation for scanned batch TV siblings."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import cast

from ._batch_tv_duplicates import normalized_relative_folder
from ._episode_projection import project_preview_items
from ._episode_resolution import resolve_table_conflicts
from .episode_assignments import merge_tables
from .models import PreviewItem, ScanState, TVScanStateScanner


def assign_preview_source_folders(
    state: ScanState,
    library_root: Path,
) -> None:
    """Populate source-folder labels for scanned preview rows."""
    for item in state.preview_items:
        if item.source_relative_folder:
            continue
        item.source_relative_folder = _relative_folder(item.original.parent, library_root)


def reconcile_scanned_episode_claims(
    states: list[ScanState],
    library_root: Path,
) -> dict[int, ScanState]:
    """Merge scanned same-show TV siblings by episode claim.

    Returns a mapping from removed state id to the primary state that absorbed it.
    """
    replacements: dict[int, ScanState] = {}
    groups: dict[int, list[ScanState]] = {}
    for state in states:
        if state.show_id is None or not state.scanned or not state.preview_items:
            continue
        groups.setdefault(state.show_id, []).append(state)

    removed: set[int] = set()
    for group in groups.values():
        if len(group) < 2:
            continue
        primary = min(group, key=_primary_priority)
        ordered = [primary] + sorted(
            (state for state in group if state is not primary),
            key=_primary_priority,
        )

        if all(state.assignments is not None for state in ordered):
            for state in ordered:
                assign_preview_source_folders(state, library_root)
                for entry in state.assignments.files.values():
                    if not entry.source_relative_folder:
                        entry.source_relative_folder = _relative_folder(
                            entry.path.parent, library_root,
                        )
                if state is not primary:
                    merge_tables(primary.assignments, state.assignments)
                    removed.add(id(state))
                    replacements[id(state)] = primary
            # Merging sibling tables can create new same-slot claims
            # (duplicate copies of a season in two source roots); resolve
            # them so an episode is never listed twice in conflict.
            resolve_table_conflicts(primary.assignments)
            primary.preview_items = project_preview_items(
                primary.assignments,
                show_info=primary.media_info,
                root=primary.folder,
                media_fields={
                    "media_id": primary.show_id,
                    "media_name": primary.media_info.get("name"),
                },
            )
        else:
            # Legacy path for states scanned before the table existed.
            merged_items: list[PreviewItem] = []
            claimed: dict[tuple[int, int], PreviewItem] = {}

            for state in ordered:
                assign_preview_source_folders(state, library_root)
                for item in state.preview_items:
                    keys = _episode_claim_keys(item)
                    overlapping = [key for key in keys if key in claimed]
                    if overlapping:
                        item.status = _duplicate_claim_status(overlapping, claimed)
                    else:
                        for key in keys:
                            claimed[key] = item
                    merged_items.append(item)
                if state is not primary:
                    removed.add(id(state))
                    replacements[id(state)] = primary

            primary.preview_items = sorted(
                merged_items,
                key=lambda item: (
                    item.season if item.season is not None else 9999,
                    item.episodes[0] if item.episodes else 9999,
                    item.is_conflict,
                    item.source_relative_folder.casefold(),
                    item.original.name.casefold(),
                ),
            )
        primary.direct_video_file_count = sum(state.direct_video_file_count for state in group)
        primary.direct_episode_file_count = sum(state.direct_episode_file_count for state in group)
        primary.duplicate_of = None
        primary.duplicate_of_relative_folder = None
        # States are created unchecked and only the user (or explicit queue
        # actions) checks them; merging must preserve that, not re-check the
        # primary just because rows are actionable (RC47).
        primary.checked = any(state.checked for state in group)
        primary.reset_gui_state()
        if primary.scanner is not None:
            scanner = cast(TVScanStateScanner, primary.scanner)
            checked = {
                index for index, item in enumerate(primary.preview_items)
                if item.status == "OK"
            }
            primary.completeness = scanner.get_completeness(
                primary.preview_items,
                checked_indices=checked,
            )

    if removed:
        states[:] = [state for state in states if id(state) not in removed]
    return replacements


def _primary_priority(state: ScanState) -> tuple[int, int, float, int, str]:
    return (
        1 if state.duplicate_of is not None else 0,
        -len([item for item in state.preview_items if item.status == "OK"]),
        -state.confidence,
        len(PurePosixPath(normalized_relative_folder(state.relative_folder, state.folder)).parts),
        normalized_relative_folder(state.relative_folder, state.folder),
    )


def _episode_claim_keys(item: PreviewItem) -> list[tuple[int, int]]:
    if (
        item.season is None
        or not item.episodes
        or item.new_name is None
        or item.is_skipped
        or item.is_unmatched
        or item.is_conflict
    ):
        return []
    return [(item.season, episode) for episode in item.episodes]


def _duplicate_claim_status(
    overlapping: list[tuple[int, int]],
    claimed: dict[tuple[int, int], PreviewItem],
) -> str:
    season, episode = overlapping[0]
    other = claimed[overlapping[0]]
    other_source = other.source_relative_folder or other.original.parent.name
    return (
        f"CONFLICT: duplicate episode claim S{season:02d}E{episode:02d} "
        f"also claimed by {other_source}"
    )


def _relative_folder(folder: Path, library_root: Path) -> str:
    try:
        return folder.relative_to(library_root).as_posix()
    except ValueError:
        return folder.as_posix()
