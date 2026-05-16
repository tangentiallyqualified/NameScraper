"""Preview tree data builders for JobDetailPanel."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from ...job_store import RenameJob, RenameOp
from ._job_detail_data import folder_preview_data


@dataclass(frozen=True)
class JobPreviewRow:
    before: str
    after: str
    before_label: str = "Original"
    after_label: str = "New"


@dataclass(frozen=True)
class JobPreviewGroup:
    label: str
    rows: list[JobPreviewRow] = field(default_factory=list)
    expanded: bool = False


JobPreviewEntry = JobPreviewRow | JobPreviewGroup


def build_job_preview_entries(job: RenameJob) -> list[JobPreviewEntry]:
    entries: list[JobPreviewEntry] = []
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

    entries.extend(_build_video_preview_entries(job, video_ops))

    if companion_ops:
        entries.append(
            JobPreviewGroup(
                label=f"Companion Files ({len(companion_ops)})",
                rows=[_preview_row_for_op(op) for op in companion_ops],
                expanded=False,
            )
        )

    return entries


def _build_video_preview_entries(job: RenameJob, video_ops: list[RenameOp]) -> list[JobPreviewEntry]:
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
                    rows=[_preview_row_for_op(op) for op in season_ops],
                    expanded=False,
                )
            )
        return entries

    rows = [_preview_row_for_op(op) for op in video_ops]
    if job.media_type == "movie":
        return [JobPreviewGroup(label="File Rename", rows=rows, expanded=True)]
    return rows


def _preview_row_for_op(op: RenameOp) -> JobPreviewRow:
    return JobPreviewRow(
        before=Path(op.original_relative).name,
        after=op.new_name,
    )
