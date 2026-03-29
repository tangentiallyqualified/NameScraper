"""Table model for queue/history jobs."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor

from ...constants import JobStatus
from ...job_store import RenameJob

_HEADERS = ["Status", "Name", "Type", "Action", "Files", "When"]
_STATUS_TEXT = {
    JobStatus.PENDING: "Pending",
    JobStatus.RUNNING: "Running",
    JobStatus.COMPLETED: "Completed",
    JobStatus.FAILED: "Failed",
    JobStatus.CANCELLED: "Cancelled",
    JobStatus.REVERTED: "Reverted",
}
_STATUS_COLOR = {
    JobStatus.PENDING: QColor("#777777"),
    JobStatus.RUNNING: QColor("#e5a00d"),
    JobStatus.COMPLETED: QColor("#3ea463"),
    JobStatus.FAILED: QColor("#d44040"),
    JobStatus.CANCELLED: QColor("#4a4a4a"),
    JobStatus.REVERTED: QColor("#4a9eda"),
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

    def set_jobs(self, jobs: list[RenameJob]) -> None:
        self.beginResetModel()
        self._jobs = list(jobs)
        self.endResetModel()

    def jobs(self) -> list[RenameJob]:
        return list(self._jobs)

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

        if role == Qt.ItemDataRole.DisplayRole:
            if column == 0:
                return _STATUS_TEXT.get(job.status, job.status.title())
            if column == 1:
                return job.media_name
            if column == 2:
                return {"tv": "TV", "movie": "Movie"}.get(job.media_type, job.media_type.title())
            if column == 3:
                return job.job_kind.title()
            if column == 4:
                return str(job.selected_count)
            if column == 5:
                return _fmt_dt(job.updated_at if self._history else job.created_at)

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if column in (0, 2, 3, 4, 5):
                return int(Qt.AlignmentFlag.AlignCenter)
            return int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

        if role == Qt.ItemDataRole.ForegroundRole and column == 0:
            return _STATUS_COLOR.get(job.status)

        if role == Qt.ItemDataRole.UserRole:
            return job

        return None

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable