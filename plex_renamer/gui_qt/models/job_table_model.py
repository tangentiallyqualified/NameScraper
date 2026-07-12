"""Table model for queue/history jobs."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QTimer, Qt
from PySide6.QtGui import QColor

from ...constants import JobStatus
from ...job_store import RenameJob
from ..theme import qcolor as _theme_qcolor

_HEADERS = ["", "Status", "Name", "Type", "Action", "Files", "When"]
_STATUS_TEXT = {
    JobStatus.PENDING: "Pending",
    JobStatus.RUNNING: "Running",
    JobStatus.COMPLETED: "Completed",
    JobStatus.FAILED: "Failed",
    JobStatus.CANCELLED: "Cancelled",
    JobStatus.REVERTED: "Reverted",
    JobStatus.REVERT_FAILED: "Revert Failed",
}
_STATUS_SORT_ORDER = {
    JobStatus.RUNNING: 0,
    JobStatus.PENDING: 1,
    JobStatus.FAILED: 2,
    JobStatus.REVERT_FAILED: 3,
    JobStatus.COMPLETED: 4,
    JobStatus.REVERTED: 5,
    JobStatus.CANCELLED: 6,
}

SORT_ROLE = Qt.ItemDataRole.UserRole + 1


def _fmt_dt(value: str) -> str:
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is not None:
            dt = dt.astimezone()
        return dt.strftime("%b %d, %H:%M")
    except (TypeError, ValueError):
        return value[:16] if value else ""


def files_cell_text(job: RenameJob) -> str:
    """Spec §11 Files column: '3 files (2 comp.)'; companion suffix drops at 0."""
    videos = job.selected_video_count
    noun = "file" if videos == 1 else "files"
    text = f"{videos} {noun}"
    companions = job.selected_companion_count
    if companions:
        text += f" ({companions} comp.)"
    return text


def _transition_tint(token: str, alpha: int) -> QColor:
    color = _theme_qcolor(token)
    color.setAlpha(alpha)
    return color


class JobTableModel(QAbstractTableModel):
    """Read-only model exposing RenameJob rows to a QTableView."""

    _TRANSITION_COLORS = {
        JobStatus.COMPLETED: _transition_tint("success", 50),
        JobStatus.FAILED: _transition_tint("error", 50),
        JobStatus.REVERTED: _transition_tint("info", 40),
    }

    def __init__(self, *, history: bool = False, parent=None) -> None:
        super().__init__(parent)
        self._history = history
        self._jobs: list[RenameJob] = []
        self._checked_job_ids: set[str] = set()
        # job_id → (op_index, op_count, percent) for running remux jobs.
        self._progress: dict[str, tuple[int, int, int]] = {}
        self._prev_statuses: dict[str, str] = {}
        self._highlight_jobs: dict[str, str] = {}  # job_id -> new status
        self._highlight_timer = QTimer(self)
        self._highlight_timer.setSingleShot(True)
        self._highlight_timer.setInterval(600)
        self._highlight_timer.timeout.connect(self._clear_highlights)

    def set_jobs(self, jobs: list[RenameJob]) -> None:
        # Detect status transitions before resetting
        new_highlights: dict[str, str] = {}
        for job in jobs:
            prev = self._prev_statuses.get(job.job_id)
            if prev is not None and prev != job.status and job.status in self._TRANSITION_COLORS:
                new_highlights[job.job_id] = job.status
        self._prev_statuses = {job.job_id: job.status for job in jobs}
        if new_highlights:
            self._highlight_jobs = new_highlights
            self._highlight_timer.start()

        running_ids = {job.job_id for job in jobs if job.status == JobStatus.RUNNING}
        self._progress = {
            job_id: value for job_id, value in self._progress.items()
            if job_id in running_ids
        }

        self.beginResetModel()
        self._jobs = list(jobs)
        checkable_ids = {job.job_id for job in self._jobs if self.is_checkable_job(job)}
        self._checked_job_ids &= checkable_ids
        self.endResetModel()

    def _clear_highlights(self) -> None:
        if not self._highlight_jobs:
            return
        self._highlight_jobs.clear()
        if self._jobs:
            top_left = self.index(0, 0)
            bottom_right = self.index(len(self._jobs) - 1, self.columnCount() - 1)
            self.dataChanged.emit(top_left, bottom_right, [Qt.ItemDataRole.BackgroundRole])

    def set_progress(self, job_id: str, op_index: int, op_count: int, percent: int) -> None:
        """Live remux progress for a running job (spec §7.2)."""
        self._progress[job_id] = (op_index, op_count, percent)
        for row, job in enumerate(self._jobs):
            if job.job_id == job_id:
                index = self.index(row, 1)
                self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole])
                break

    def jobs(self) -> list[RenameJob]:
        return list(self._jobs)

    def checked_job_ids(self) -> set[str]:
        return set(self._checked_job_ids)

    def checked_jobs(self) -> list[RenameJob]:
        return [job for job in self._jobs if job.job_id in self._checked_job_ids]

    def is_checkable_job(self, job: RenameJob) -> bool:
        if self._history:
            # No Fear remuxes deleted their sources and can never be
            # reverted (spec §7.4) — no revert checkbox for them.
            return (
                job.status == JobStatus.COMPLETED
                and bool(job.undo_data)
                and not job.undo_data.get("irreversible")
            )
        return job.status == JobStatus.PENDING

    def set_checked_job_ids(self, job_ids: set[str]) -> None:
        checkable_ids = {job.job_id for job in self._jobs if self.is_checkable_job(job)}
        normalized = set(job_ids) & checkable_ids
        if normalized == self._checked_job_ids:
            return
        self._checked_job_ids = normalized
        self._emit_check_state_changed()

    def set_jobs_checked(self, job_ids: set[str], checked: bool) -> None:
        checkable_ids = {job.job_id for job in self._jobs if self.is_checkable_job(job)}
        target_ids = set(job_ids) & checkable_ids
        if not target_ids:
            return
        next_checked = set(self._checked_job_ids)
        if checked:
            next_checked.update(target_ids)
        else:
            next_checked.difference_update(target_ids)
        if next_checked == self._checked_job_ids:
            return
        self._checked_job_ids = next_checked
        self._emit_check_state_changed()

    def clear_checked(self) -> None:
        if not self._checked_job_ids:
            return
        self._checked_job_ids.clear()
        self._emit_check_state_changed()

    def job_at(self, row: int) -> RenameJob | None:
        if 0 <= row < len(self._jobs):
            return self._jobs[row]
        return None

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._jobs)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(_HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(_HEADERS):
            return _HEADERS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        job = self._jobs[index.row()]
        column = index.column()
        value_column = column - 1

        if role == Qt.ItemDataRole.CheckStateRole and column == 0:
            if not self.is_checkable_job(job):
                return None
            return Qt.CheckState.Checked if job.job_id in self._checked_job_ids else Qt.CheckState.Unchecked

        if role == Qt.ItemDataRole.DisplayRole:
            if column == 0:
                return ""
            if value_column == 0:
                progress = self._progress.get(job.job_id)
                if progress is not None and job.status == JobStatus.RUNNING:
                    op_index, op_count, percent = progress
                    return f"Running · file {op_index + 1}/{op_count} · {percent}%"
                return _STATUS_TEXT.get(job.status, job.status.title())
            if value_column == 1:
                return job.media_name
            if value_column == 2:
                return {"tv": "TV", "movie": "Movie"}.get(job.media_type, job.media_type.title())
            if value_column == 3:
                return job.job_kind.title()
            if value_column == 4:
                return files_cell_text(job)
            if value_column == 5:
                return _fmt_dt(job.updated_at if self._history else job.created_at)

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if column in (0, 1, 3, 4, 5, 6):
                return int(Qt.AlignmentFlag.AlignCenter)
            return int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

        if role == Qt.ItemDataRole.BackgroundRole:
            highlight_status = self._highlight_jobs.get(job.job_id)
            if highlight_status is not None:
                return self._TRANSITION_COLORS.get(highlight_status)

        if role == Qt.ItemDataRole.UserRole:
            return job

        if role == SORT_ROLE:
            if column == 0:
                return 0
            if value_column == 0:
                return _STATUS_SORT_ORDER.get(job.status, 99)
            if value_column == 1:
                return (job.media_name or "").casefold()
            if value_column == 2:
                return (job.media_type or "").casefold()
            if value_column == 3:
                return (job.job_kind or "").casefold()
            if value_column == 4:
                return int(job.selected_video_count or 0)
            if value_column == 5:
                return job.updated_at if self._history else job.created_at

        return None

    def setData(self, index: QModelIndex, value, role: int = Qt.ItemDataRole.EditRole):
        if not index.isValid() or index.column() != 0 or role != Qt.ItemDataRole.CheckStateRole:
            return False
        job = self._jobs[index.row()]
        if not self.is_checkable_job(job):
            return False
        checked = value == Qt.CheckState.Checked
        if checked:
            if job.job_id in self._checked_job_ids:
                return False
            self._checked_job_ids.add(job.job_id)
        else:
            if job.job_id not in self._checked_job_ids:
                return False
            self._checked_job_ids.remove(job.job_id)
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
        return True

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == 0:
            job = self._jobs[index.row()]
            if not self.is_checkable_job(job):
                return base
            return base | Qt.ItemFlag.ItemIsUserCheckable
        return base

    def _emit_check_state_changed(self) -> None:
        if not self._jobs:
            return
        top_left = self.index(0, 0)
        bottom_right = self.index(len(self._jobs) - 1, 0)
        self.dataChanged.emit(top_left, bottom_right, [Qt.ItemDataRole.CheckStateRole])
