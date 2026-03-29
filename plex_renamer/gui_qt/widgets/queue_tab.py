"""Queue tab — Phase 3 placeholder, built out in Phase 4.

Shows the empty state by default.  Phase 4 will add the job list,
filtering toolbar, execution controls, and drag-and-drop reorder.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class QueueTab(QWidget):
    """Placeholder queue tab with empty-state messaging."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(12)

        title = QLabel("No jobs queued")
        title.setProperty("cssClass", "heading")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        hint = QLabel("Scan a library and add items to get started.")
        hint.setProperty("cssClass", "text-dim")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)

        btn_row = QWidget()
        btn_layout = QVBoxLayout(btn_row)
        btn_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn_layout.setSpacing(8)

        tv_btn = QPushButton("Go to TV Shows")
        tv_btn.setProperty("cssClass", "secondary")
        tv_btn.setFixedWidth(180)
        tv_btn.clicked.connect(lambda: self._switch_tab(0))
        btn_layout.addWidget(tv_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        movie_btn = QPushButton("Go to Movies")
        movie_btn.setProperty("cssClass", "secondary")
        movie_btn.setFixedWidth(180)
        movie_btn.clicked.connect(lambda: self._switch_tab(1))
        btn_layout.addWidget(movie_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(btn_row)

    def _switch_tab(self, index: int) -> None:
        """Navigate to another tab via the parent QTabWidget."""
        tab_widget = self.parentWidget()
        if tab_widget is not None:
            # QTabWidget wraps each tab in a QStackedWidget
            from PySide6.QtWidgets import QTabWidget
            while tab_widget and not isinstance(tab_widget, QTabWidget):
                tab_widget = tab_widget.parentWidget()
            if tab_widget:
                tab_widget.setCurrentIndex(index)
