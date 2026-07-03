"""Helpers for converting scan preview state into persistent queue jobs."""

from __future__ import annotations

from pathlib import Path

from ..constants import MediaType
from .models import PreviewItem, ScanState


def get_checked_indices_from_state(state: ScanState) -> set[int]:
    """Return indices of checked, actionable preview items from a scan state."""
    return {
        index for index, item in enumerate(state.preview_items)
        if state.check_vars.get(str(index)) is not None
        and state.check_vars[str(index)].get()
        and _is_queue_actionable(item)
    }


def _is_queue_actionable(item: PreviewItem) -> bool:
    return item.is_actionable and not item.is_unmatched


def _fallback_target_relative(
    item: PreviewItem,
    target_dir: Path,
    show_folder: str | None,
) -> str:
    if show_folder:
        if item.season is not None:
            return str(Path(show_folder) / f"Season {item.season:02d}")
        return show_folder
    return str(target_dir)


def _build_rename_ops(
    items: list[PreviewItem],
    checked_indices: set[int],
    source_root: Path,
    output_root: Path,
    show_folder: str | None = None,
) -> list:
    """Convert preview items into serializable RenameOp rows."""
    from ..job_store import RenameOp

    ops = []
    for index, item in enumerate(items):
        if not _is_queue_actionable(item):
            continue

        target_dir = item.target_dir or item.original.parent

        try:
            original_rel = str(item.original.relative_to(source_root))
        except ValueError:
            original_rel = str(item.original)

        try:
            target_rel = str(target_dir.relative_to(output_root))
        except ValueError:
            # A target dir outside the output root means the preview was
            # never retargeted (it still points into the scan source). An
            # absolute path here would make the executor reject the job, so
            # rebuild the canonical output-relative destination instead.
            target_rel = _fallback_target_relative(item, target_dir, show_folder)

        is_selected = index in checked_indices
        ops.append(RenameOp(
            original_relative=original_rel,
            new_name=item.new_name,
            target_dir_relative=target_rel,
            status=item.status,
            season=item.season,
            episodes=list(item.episodes),
            selected=is_selected,
            file_type="video",
        ))

        for companion in item.companions:
            try:
                companion_rel = str(companion.original.relative_to(source_root))
            except ValueError:
                companion_rel = str(companion.original)

            ops.append(RenameOp(
                original_relative=companion_rel,
                new_name=companion.new_name,
                target_dir_relative=target_rel,
                status="OK",
                season=item.season,
                episodes=list(item.episodes),
                selected=is_selected,
                file_type=companion.file_type,
            ))

    return ops


def build_rename_job_from_state(
    state: ScanState,
    library_root: Path,
    output_root: Path,
    show_folder_rename: str | None = None,
    checked_indices: set[int] | None = None,
) -> "RenameJob":
    """Create a RenameJob from a TV batch scan state."""
    from ..job_store import RenameJob

    from ..parsing import build_show_folder_name

    checked_indices = checked_indices or get_checked_indices_from_state(state)
    fallback_folder = show_folder_rename or build_show_folder_name(
        state.media_info.get("name", ""),
        state.media_info.get("year", ""),
    )
    ops = _build_rename_ops(
        state.preview_items,
        checked_indices,
        library_root,
        output_root,
        show_folder=fallback_folder or None,
    )

    if state.relative_folder:
        source_folder = state.relative_folder
    else:
        try:
            source_folder = str(state.folder.relative_to(library_root))
        except ValueError:
            source_folder = state.folder.name

    return RenameJob(
        media_type=MediaType.TV,
        tmdb_id=state.show_id or 0,
        media_name=state.display_name,
        poster_path=state.media_info.get("poster_path"),
        library_root=str(library_root),
        output_root=str(output_root),
        source_folder=source_folder,
        rename_ops=ops,
        show_folder_rename=show_folder_rename,
    )


def build_rename_job_from_items(
    items: list[PreviewItem],
    checked_indices: set[int],
    media_type: str,
    tmdb_id: int,
    media_name: str,
    library_root: Path,
    output_root: Path,
    source_folder: Path,
    show_folder_rename: str | None = None,
    poster_path: str | None = None,
) -> "RenameJob":
    """Create a RenameJob from raw preview items."""
    from ..job_store import RenameJob

    ops = _build_rename_ops(
        items,
        checked_indices,
        library_root,
        output_root,
        show_folder=show_folder_rename,
    )

    if media_type == MediaType.MOVIE:
        try:
            if source_folder.resolve() == library_root.resolve():
                show_folder_rename = None
        except OSError:
            if source_folder == library_root:
                show_folder_rename = None

    try:
        source_rel = str(source_folder.relative_to(library_root))
    except ValueError:
        source_rel = str(source_folder)

    return RenameJob(
        media_type=media_type,
        tmdb_id=tmdb_id,
        media_name=media_name,
        poster_path=poster_path,
        library_root=str(library_root),
        output_root=str(output_root),
        source_folder=source_rel,
        rename_ops=ops,
        show_folder_rename=show_folder_rename,
    )
