"""Table model for queue/history jobs."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor

from ...constants import JobStatus
from ...job_store import RenameJob

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
_STATUS_COLOR = {
    JobStatus.PENDING: QColor("#777777"),
    JobStatus.RUNNING: QColor("#e5a00d"),
    JobStatus.COMPLETED: QColor("#3ea463"),
    JobStatus.FAILED: QColor("#d44040"),
    JobStatus.CANCELLED: QColor("#4a4a4a"),
    JobStatus.REVERTED: QColor("#4a9eda"),
    JobStatus.REVERT_FAILED: QColor("#d44040"),
}


def _fmt_dt(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%b %d, %H:%M")
    except (TypeError, ValueError):
        return value[:16] if value else ""


class JobTableModel(QAbstractTableModel):
    """Read-only model exposing RenameJob rows to a QTableView."""

    def __init__(self, *, history: bool = False, parent=None) -> None:
        super().__init__(parent)
        self._history = history
        self._jobs: list[RenameJob] = []
        self._checked_job_ids: set[str] = set()

    def set_jobs(self, jobs: list[RenameJob]) -> None:
        self.beginResetModel()
        self._jobs = list(jobs)
        valid_ids = {job.job_id for job in self._jobs}
        self._checked_job_ids &= valid_ids
        self.endResetModel()

    def jobs(self) -> list[RenameJob]:
        return list(self._jobs)

    def checked_job_ids(self) -> set[str]:
        return set(self._checked_job_ids)

    def checked_jobs(self) -> list[RenameJob]:
        return [job for job in self._jobs if job.job_id in self._checked_job_ids]

    def set_checked_job_ids(self, job_ids: set[str]) -> None:
        valid_ids = {job.job_id for job in self._jobs}
        normalized = set(job_ids) & valid_ids
        if normalized == self._checked_job_ids:
            return
        self._checked_job_ids = normalized
        self._emit_check_state_changed()

    def set_jobs_checked(self, job_ids: set[str], checked: bool) -> None:
        valid_ids = {job.job_id for job in self._jobs}
        target_ids = set(job_ids) & valid_ids
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
            return Qt.CheckState.Checked if job.job_id in self._checked_job_ids else Qt.CheckState.Unchecked

        if role == Qt.ItemDataRole.DisplayRole:
            if column == 0:
                return ""
            if value_column == 0:
                return _STATUS_TEXT.get(job.status, job.status.title())
            if value_column == 1:
                return job.media_name
            if value_column == 2:
                return {"tv": "TV", "movie": "Movie"}.get(job.media_type, job.media_type.title())
            if value_column == 3:
                return job.job_kind.title()
            if value_column == 4:
                return str(job.selected_count)
            if value_column == 5:
                return _fmt_dt(job.updated_at if self._history else job.created_at)

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if column in (0, 1, 3, 4, 5, 6):
                return int(Qt.AlignmentFlag.AlignCenter)
            return int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

        if role == Qt.ItemDataRole.ForegroundRole and column == 1:
            return _STATUS_COLOR.get(job.status)

        if role == Qt.ItemDataRole.UserRole:
            return job

        return None

    def setData(self, index: QModelIndex, value, role: int = Qt.ItemDataRole.EditRole):
        if not index.isValid() or index.column() != 0 or role != Qt.ItemDataRole.CheckStateRole:
            return False
        job = self._jobs[index.row()]
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
        flags = Qt.ItemFlag.ItemIsEnabled
        if index.column() == 0:
            return flags | Qt.ItemFlag.ItemIsUserCheckable
        return flags | Qt.ItemFlag.ItemIsSelectable

    def _emit_check_state_changed(self) -> None:
        if not self._jobs:
            return
        top_left = self.index(0, 0)
        bottom_right = self.index(len(self._jobs) - 1, 0)
        self.dataChanged.emit(top_left, bottom_right, [Qt.ItemDataRole.CheckStateRole])