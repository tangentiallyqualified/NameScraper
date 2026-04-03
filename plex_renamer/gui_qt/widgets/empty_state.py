"""Empty-state widget shown when no folder has been selected.

Features a dashed-border drop zone that accepts dragged folders,
a click-to-browse action, and a recent folders list from SettingsService.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QStyle,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from ...app.services.settings_service import SettingsService


class EmptyStateWidget(QWidget):
    """Centered drop zone with folder picker and recent folders."""

    folder_selected = Signal(str)

    def __init__(
        self,
        media_type: str = "tv",
        settings_service: "SettingsService | None" = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._media_type = media_type
        self._settings = settings_service
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # ── Drop zone ────────────────────────────────────────────
        self._drop_zone = _DropZone(self._media_type, parent=self)
        self._drop_zone.clicked.connect(self.open_folder_dialog)
        self._drop_zone.folder_dropped.connect(self._on_folder)
        outer.addWidget(self._drop_zone, alignment=Qt.AlignmentFlag.AlignCenter)

        # ── Recent folders ───────────────────────────────────────
        self._recent_container = QWidget()
        self._recent_layout = QVBoxLayout(self._recent_container)
        self._recent_layout.setContentsMargins(0, 16, 0, 0)
        self._recent_layout.setSpacing(4)
        outer.addWidget(self._recent_container, alignment=Qt.AlignmentFlag.AlignCenter)

        self.refresh_recent_folders()

    def refresh_recent_folders(self) -> None:
        """Rebuild the recent folders list from settings."""
        # Clear existing
        while self._recent_layout.count():
            item = self._recent_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if self._settings is None:
            self._recent_container.hide()
            return

        folders = (
            self._settings.recent_tv_folders
            if self._media_type == "tv"
            else self._settings.recent_movie_folders
        )

        if not folders:
            self._recent_container.hide()
            return

        header = QLabel("Recent folders")
        header.setProperty("cssClass", "caption")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._recent_layout.addWidget(header)

        for folder in folders[:5]:
            entry = _RecentFolderEntry(folder)
            entry.clicked.connect(self._on_folder)
            self._recent_layout.addWidget(entry)

        self._recent_container.show()

    def open_folder_dialog(self) -> None:
        label = "Select TV Library Folder" if self._media_type == "tv" else "Select Movie Folder"
        path = QFileDialog.getExistingDirectory(self, label)
        if path:
            self._on_folder(path)

    def _on_folder(self, path: str) -> None:
        self.folder_selected.emit(path)


class _DropZone(QFrame):
    """Dashed-border drop target that accepts folder drags and clicks."""

    clicked = Signal()
    folder_dropped = Signal(str)

    def __init__(self, media_type: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("cssClass", "drop-zone")
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedSize(360, 220)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(12)

        # Folder icon using Qt built-in style icon
        icon_label = QLabel()
        icon_label.setProperty("cssClass", "drop-zone-icon")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        style = QApplication.style()
        if style is not None:
            folder_icon = style.standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)
            icon_label.setPixmap(folder_icon.pixmap(QSize(48, 48)))
        else:
            icon_label.setText("\U0001F4C2")
        layout.addWidget(icon_label)

        title = "Select TV Library Folder" if media_type == "tv" else "Select Movie Folder"
        title_label = QLabel(title)
        title_label.setProperty("cssClass", "heading")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        hint = QLabel("Choose the root folder, or drag and drop it here.")
        hint.setProperty("cssClass", "text-dim")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)

    # ── Drag and drop ────────────────────────────────────────────

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls and Path(urls[0].toLocalFile()).is_dir():
                event.acceptProposedAction()
                self.setProperty("dragOver", True)
                self.style().unpolish(self)
                self.style().polish(self)
                return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self.setProperty("dragOver", False)
        self.style().unpolish(self)
        self.style().polish(self)

    def dropEvent(self, event: QDropEvent) -> None:
        self.setProperty("dragOver", False)
        self.style().unpolish(self)
        self.style().polish(self)

        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if Path(path).is_dir():
                self.folder_dropped.emit(path)
                event.acceptProposedAction()
                return
        event.ignore()

    # ── Click and keyboard ───────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Space):
            self.clicked.emit()
        else:
            super().keyPressEvent(event)


class _RecentFolderEntry(QWidget):
    """A single clickable recent folder row."""

    clicked = Signal(str)

    def __init__(self, folder_path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._path = folder_path
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        p = Path(folder_path)
        name_label = QLabel(p.name)
        name_label.setProperty("cssClass", "recent-folder-name")
        layout.addWidget(name_label)

        path_label = QLabel(str(p.parent))
        path_label.setProperty("cssClass", "recent-folder-path")
        layout.addWidget(path_label)
        layout.addStretch()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._path)
