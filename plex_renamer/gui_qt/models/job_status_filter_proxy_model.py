"""Status-based proxy model for queue and history tables."""

from __future__ import annotations

from PySide6.QtCore import QSortFilterProxyModel, QModelIndex


class JobStatusFilterProxyModel(QSortFilterProxyModel):
    """Filter RenameJob rows by a set of allowed status strings."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._allowed_statuses: set[str] | None = None

    def set_allowed_statuses(self, statuses: set[str] | None) -> None:
        self._allowed_statuses = None if not statuses else set(statuses)
        if hasattr(self, "beginFilterChange") and hasattr(self, "endFilterChange"):
            self.beginFilterChange()
            self.endFilterChange()
        else:
            self.invalidate()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        if self._allowed_statuses is None:
            return True
        source = self.sourceModel()
        if source is None or not hasattr(source, "job_at"):
            return True
        job = source.job_at(source_row)
        if job is None:
            return False
        return job.status in self._allowed_statuses