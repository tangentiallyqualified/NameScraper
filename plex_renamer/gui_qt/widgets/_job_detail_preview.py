"""Preview tree data builders for JobDetailPanel."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from ...job_store import RenameJob, RenameOp
from ._job_detail_data import (
    final_target_dir_relative,
    folder_preview_data,
    folder_preview_source_name,
)


@dataclass(frozen=True)
class JobPreviewRow:
    before: str
    after: str
    before_label: str = "Original"
    after_label: str = "New"
    badge: str = ""
    children: tuple["JobPreviewRow", ...] = ()


@dataclass(frozen=True)
class JobPreviewGroup:
    label: str
    rows: list[JobPreviewRow] = field(default_factory=list)
    expanded: bool = False


JobPreviewEntry = JobPreviewRow | JobPreviewGroup


_TYPE_BADGES = {"subtitle": "SUB"}


def type_badge(file_type: str) -> str:
    return _TYPE_BADGES.get(file_type, (file_type[:4] or "file").upper())


def pair_companions_with_videos(
    video_ops: list[RenameOp],
    companion_ops: list[RenameOp],
) -> tuple[dict[int, list[RenameOp]], list[RenameOp]]:
    """Pair each companion with the video whose target stem prefixes the
    companion's ``new_name`` in the same target dir (longest stem wins).

    Read-model heuristic only — ``RenameOp`` persists no linkage and §16
    forbids job-store schema changes.  Unmatched companions are returned
    for the residual "Companion Files" group, never dropped.
    """
    paired: dict[int, list[RenameOp]] = {}
    unpaired: list[RenameOp] = []
    for companion in companion_ops:
        best: RenameOp | None = None
        best_stem_len = -1
        for video in video_ops:
            if video.target_dir_relative != companion.target_dir_relative:
                continue
            stem = Path(video.new_name).stem
            if not stem or not companion.new_name.startswith(stem + "."):
                continue
            if len(stem) > best_stem_len:
                best, best_stem_len = video, len(stem)
        if best is None:
            unpaired.append(companion)
        else:
            paired.setdefault(id(best), []).append(companion)
    return paired, unpaired


def build_job_preview_entries(job: RenameJob) -> list[JobPreviewEntry]:
    entries: list[JobPreviewEntry] = []
    if job.output_root:
        target_name = _output_top_folder_name(job)
        source_name = folder_preview_source_name(job, include_media_name=True)
        if target_name and source_name:
            entries.append(
                JobPreviewGroup(
                    label="Output Folder",
                    rows=[
                        JobPreviewRow(
                            before=source_name,
                            after=target_name,
                            before_label="Source",
                            after_label="Output",
                        )
                    ],
                    expanded=True,
                )
            )
    else:
        folder_preview = folder_preview_data(job)
        if folder_preview is not None:
            source_name, target_name = folder_preview
            entries.append(
                JobPreviewGroup(
                    label="Folder Rename",
                    rows=[
                        JobPreviewRow(
                            before=source_name,
                            after=target_name,
                            before_label="Source",
                            after_label="Target",
                        )
                    ],
                    expanded=True,
                )
            )

    ops = job.selected_ops or job.rename_ops
    if not ops:
        return entries

    video_ops = [op for op in ops if op.file_type == "video"]
    companion_ops = [op for op in ops if op.file_type != "video"]
    paired, unpaired = pair_companions_with_videos(video_ops, companion_ops)

    entries.extend(_build_video_preview_entries(job, video_ops, paired))

    if unpaired:
        entries.append(
            JobPreviewGroup(
                label=f"Companion Files ({len(unpaired)})",
                rows=[_preview_row_for_op(op) for op in unpaired],
                expanded=False,
            )
        )

    return entries


def _output_top_folder_name(job: RenameJob) -> str | None:
    ops = job.selected_ops or job.rename_ops
    for op in ops:
        parts = [part for part in final_target_dir_relative(job, op).parts if part not in {"", "."}]
        if parts:
            return parts[0]
    return None


def _build_video_preview_entries(
    job: RenameJob,
    video_ops: list[RenameOp],
    paired: dict[int, list[RenameOp]],
) -> list[JobPreviewEntry]:
    if not video_ops:
        return []

    if job.media_type == "tv" and any(op.season is not None for op in video_ops):
        by_season: dict[int | None, list[RenameOp]] = defaultdict(list)
        for op in video_ops:
            by_season[op.season].append(op)

        entries: list[JobPreviewEntry] = []
        for season_num in sorted(by_season, key=lambda value: (value is None, value or 0)):
            season_ops = by_season[season_num]
            if season_num is not None:
                label = f"Season {season_num:02d} ({len(season_ops)} files)"
            else:
                label = f"Other Files ({len(season_ops)} files)"
            entries.append(
                JobPreviewGroup(
                    label=label,
                    rows=[_video_preview_row(op, paired) for op in season_ops],
                    expanded=False,
                )
            )
        return entries

    rows = [_video_preview_row(op, paired) for op in video_ops]
    if job.media_type == "movie":
        return [JobPreviewGroup(label="File Rename", rows=rows, expanded=True)]
    return rows


def _video_preview_row(op: RenameOp, paired: dict[int, list[RenameOp]]) -> JobPreviewRow:
    children = tuple(_preview_row_for_op(c) for c in paired.get(id(op), ()))
    return JobPreviewRow(
        before=Path(op.original_relative).name,
        after=op.new_name,
        children=children,
    )


def _preview_row_for_op(op: RenameOp) -> JobPreviewRow:
    badge = type_badge(op.file_type) if op.file_type != "video" else ""
    return JobPreviewRow(
        before=Path(op.original_relative).name,
        after=op.new_name,
        badge=badge,
    )
