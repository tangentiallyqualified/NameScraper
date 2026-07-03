"""Project an EpisodeAssignmentTable into PreviewItem rows.

This is the ONLY place episode preview status strings are minted.
"""

from __future__ import annotations

from pathlib import Path

from ..parsing import build_tv_name
from ._movie_scanner import _build_subtitle_companions
from ._state import get_episode_auto_accept_threshold
from .episode_assignments import (
    ORIGIN_MANUAL,
    REASON_DUPLICATE_COPY,
    REASON_NO_PARSE,
    REASON_NO_TITLE_MATCH,
    EpisodeAssignmentTable,
    FileEntry,
)
from .models import EPISODE_REVIEW_STATUS_PREFIX, PreviewItem

_UNASSIGNED_STATUS = {
    REASON_NO_PARSE: "SKIP: could not parse episode number",
}


def _season_dir_name(season: int) -> str:
    return f"Season {season:02d}"


def _conflict_status(season: int, episode: int, other: FileEntry) -> str:
    other_source = other.source_relative_folder or other.path.parent.name
    return (
        f"CONFLICT: duplicate episode claim S{season:02d}E{episode:02d} "
        f"also claimed by {other_source}"
    )


def _unassigned_item(
    entry: FileEntry,
    reason: str,
    root: Path,
    media_fields: dict,
) -> PreviewItem:
    if reason.startswith(REASON_DUPLICATE_COPY):
        return PreviewItem(
            original=entry.path,
            new_name=None,
            target_dir=None,
            season=entry.folder_season,
            episodes=list(entry.parsed_episodes),
            status=f"DUPLICATE: {reason}",
            file_id=entry.file_id,
            source_relative_folder=entry.source_relative_folder,
            **media_fields,
        )
    if entry.folder_season == 0 and reason == REASON_NO_TITLE_MATCH:
        if entry.from_extras_folder:
            return PreviewItem(
                original=entry.path,
                new_name=entry.path.name,
                target_dir=root / "Unmatched" / entry.path.parent.name,
                season=0,
                episodes=list(entry.parsed_episodes),
                status="UNMATCHED: no TMDB special found - moving to Unmatched",
                file_id=entry.file_id,
                source_relative_folder=entry.source_relative_folder,
                **media_fields,
            )
        return PreviewItem(
            original=entry.path,
            new_name=None,
            target_dir=None,
            season=0,
            episodes=list(entry.parsed_episodes),
            status="UNMATCHED: no TMDB special title match",
            file_id=entry.file_id,
            source_relative_folder=entry.source_relative_folder,
            **media_fields,
        )

    status = _UNASSIGNED_STATUS.get(reason) or (f"SKIP: {reason}" if reason else "SKIP")
    return PreviewItem(
        original=entry.path,
        new_name=None,
        target_dir=None,
        season=entry.folder_season,
        episodes=list(entry.parsed_episodes),
        status=status,
        file_id=entry.file_id,
        source_relative_folder=entry.source_relative_folder,
        **media_fields,
    )


def project_preview_items(
    table: EpisodeAssignmentTable,
    *,
    show_info: dict,
    root: Path,
    media_fields: dict,
) -> list[PreviewItem]:
    """Produce exactly one PreviewItem per FileEntry, in guide order."""
    threshold = get_episode_auto_accept_threshold()
    conflicted = table.conflicted_file_ids()
    items: list[PreviewItem] = []

    for file_id, entry in table.files.items():
        assignment = table.assignment_for(file_id)
        if assignment is None:
            reason = table.unassigned_reasons.get(file_id, "")
            items.append(_unassigned_item(entry, reason, root, media_fields))
            continue

        season = assignment.season
        episodes = list(assignment.episodes)
        titles = [
            table.slots[(season, episode)].title or f"Episode {episode}"
            for episode in episodes
        ]
        new_name = build_tv_name(
            show_info["name"],
            show_info.get("year", ""),
            season,
            episodes,
            titles,
            entry.path.suffix,
        )
        target_dir = root / _season_dir_name(season)

        if file_id in conflicted:
            slot_key = next(
                (season, episode)
                for episode in episodes
                if len(table.claims(season, episode)) > 1
            )
            other = next(
                table.files[claim.file_id]
                for claim in table.claims(*slot_key)
                if claim.file_id != file_id
            )
            status = _conflict_status(slot_key[0], slot_key[1], other)
        elif (
            assignment.origin != ORIGIN_MANUAL
            and not assignment.approved
            and assignment.confidence < threshold
        ):
            status = (
                f"{EPISODE_REVIEW_STATUS_PREFIX} "
                f"({assignment.confidence:.0%} < {threshold:.0%})"
            )
        else:
            status = "OK"

        item = PreviewItem(
            original=entry.path,
            new_name=new_name,
            target_dir=target_dir,
            season=season,
            episodes=episodes,
            status=status,
            episode_confidence=assignment.confidence,
            file_id=file_id,
            source_relative_folder=entry.source_relative_folder,
            **media_fields,
        )
        if status.startswith(("OK", "REVIEW")):
            item.companions = _build_subtitle_companions(entry.path, new_name)
        items.append(item)

    items.sort(
        key=lambda item: (
            item.season if item.season is not None else 9999,
            item.episodes[0] if item.episodes else 9999,
            item.is_conflict,
            item.original.name.casefold(),
        )
    )
    return items
