"""History tab — Phase 3 placeholder, built out in Phase 4.

Shows an empty-state message.  Phase 4 will add the job history list,
filtering toolbar, and revert controls.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel,
    QVBoxLayout,
    QWidget,
)


class HistoryTab(QWidget):
    """Placeholder history tab with empty-state messaging."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(12)

        title = QLabel("No history yet")
        title.setProperty("cssClass", "heading")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        hint = QLabel("Completed, failed, and reverted jobs will appear here.")
        hint.setProperty("cssClass", "text-dim")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)
