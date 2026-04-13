"""Shared job detail panel for queue and history tabs."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QAbstractItemView,
    QGridLayout,
    QLabel,
    QHeaderView,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...job_store import RenameJob
from ._job_detail_data import (
    build_job_fact_values,
    build_job_meta_line,
    build_job_summary,
    primary_target_path,
    resolve_openable_path,
)
from ._job_detail_poster import JobDetailPosterWorkflow
from ._job_detail_preview import JobPreviewGroup, JobPreviewRow, build_job_preview_entries
from ._job_detail_tree import (
    create_preview_group_header,
    job_detail_empty_message,
    refresh_preview_item_sizes,
    set_preview_group_header_label,
    toggle_preview_group_item,
)


class _PosterBridge(QObject):
    """Marshal poster pixmaps from worker threads to the UI thread."""

    poster_ready = Signal(object, str)


class _PreviewTreeWidget(QTreeWidget):
    resized = Signal()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.resized.emit()


class _ElidedPreviewLabel(QLabel):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__("", parent)
        self._full_text = text
        self._display_text = ""
        self.setWordWrap(False)
        self.setMinimumWidth(0)
        self._sync_display_text()

    def setText(self, text: str) -> None:
        self._full_text = text
        self._sync_display_text()

    def text(self) -> str:
        return self._full_text

    def is_elided(self) -> bool:
        return self._display_text != self._full_text

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_display_text()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_display_text()

    def _sync_display_text(self) -> None:
        width = max(40, self.contentsRect().width() or self.width() or 40)
        display = self.fontMetrics().elidedText(
            self._full_text,
            Qt.TextElideMode.ElideRight,
            width,
        )
        self._display_text = display
        super().setText(display)


class _RenamePreviewWidget(QWidget):
    """Compact preview row with labeled original and renamed values."""

    def __init__(
        self,
        *,
        before: str,
        after: str,
        before_label: str = "Original",
        after_label: str = "New",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._before_label_text = before_label
        self._after_label_text = after_label
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 1, 0, 1)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(2)
        layout.setColumnMinimumWidth(0, 52)
        layout.setColumnStretch(1, 1)

        self._after_key = QLabel(after_label)
        self._after_key.setProperty("cssClass", "caption")
        self._after_key.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self._after_key, 0, 0)

        self._after = _ElidedPreviewLabel(after)
        self._after.setProperty("cssClass", "job-preview-target")
        self._after.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(self._after, 0, 1)

        self._before_key = QLabel(before_label)
        self._before_key.setProperty("cssClass", "caption")
        self._before_key.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self._before_key, 1, 0)

        self._before = _ElidedPreviewLabel(before)
        self._before.setProperty("cssClass", "text-dim")
        self._before.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(self._before, 1, 1)
        self._sync_tooltip()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_tooltip()

    def _sync_tooltip(self) -> None:
        tooltip = ""
        if self._before.is_elided() or self._after.is_elided():
            tooltip = (
                f"{self._after_label_text}: {self._after.text()}\n"
                f"{self._before_label_text}: {self._before.text()}"
            )
        self.setToolTip(tooltip)
        self._before.setToolTip(tooltip)
        self._after.setToolTip(tooltip)
        self._before_key.setToolTip(tooltip)
        self._after_key.setToolTip(tooltip)


class JobDetailPanel(QFrame):
    """Shows the selected job summary, preview, and optional poster."""

    _EMPTY_TITLE = "No Job Selected!"

    def __init__(
        self,
        tmdb_provider: Callable[[], object | None] | None = None,
        persist_poster_path: Callable[[str, str | None], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tmdb_provider = tmdb_provider
        self._persist_poster_path = persist_poster_path
        self._history_mode: bool = False
        self._current_job_id: str | None = None
        self._current_job: RenameJob | None = None
        self._poster_pixmap: QPixmap | None = None
        self._bridge = _PosterBridge(self)
        self._poster_workflow = JobDetailPosterWorkflow(self)
        self._bridge.poster_ready.connect(self._apply_poster)
        self.setProperty("cssClass", "panel")
        self.setMinimumWidth(400)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        shell = QVBoxLayout(self)
        shell.setContentsMargins(12, 12, 12, 12)
        shell.setSpacing(0)

        self._stack = QStackedWidget()
        shell.addWidget(self._stack, stretch=1)

        self._empty_page = QWidget()
        empty_layout = QVBoxLayout(self._empty_page)
        empty_layout.setContentsMargins(0, 0, 0, 0)
        empty_layout.setSpacing(0)
        empty_layout.addStretch(1)

        self._empty_card = QFrame()
        self._empty_card.setProperty("cssClass", "job-detail-empty-card")
        self._empty_card.setMaximumWidth(380)
        self._empty_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        empty_card_layout = QVBoxLayout(self._empty_card)
        empty_card_layout.setContentsMargins(28, 28, 28, 28)
        empty_card_layout.setSpacing(12)

        self._empty_title = QLabel(self._EMPTY_TITLE)
        self._empty_title.setProperty("cssClass", "heading")
        self._empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_title.setWordWrap(True)
        self._empty_title.setMargin(3)
        self._empty_title.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self._empty_title.setMinimumHeight((self._empty_title.fontMetrics().lineSpacing() * 2) + 10)
        empty_card_layout.addWidget(self._empty_title)

        self._empty_message = QLabel("")
        self._empty_message.setProperty("cssClass", "text-dim")
        self._empty_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_message.setWordWrap(True)
        self._empty_message.setMargin(4)
        self._empty_message.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self._empty_message.setMinimumHeight((self._empty_message.fontMetrics().lineSpacing() * 3) + 12)
        empty_card_layout.addWidget(self._empty_message)

        empty_layout.addWidget(self._empty_card, alignment=Qt.AlignmentFlag.AlignCenter)
        empty_layout.addStretch(1)
        self._stack.addWidget(self._empty_page)

        self._detail_page = QWidget()
        layout = QVBoxLayout(self._detail_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        summary_row = QHBoxLayout()
        summary_row.setSpacing(12)
        layout.addLayout(summary_row)

        self._poster = QLabel()
        self._poster.setFixedSize(160, 240)
        self._poster.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._poster.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._poster.setProperty("cssClass", "job-poster-card")
        self._poster.setText("No Poster")
        summary_row.addWidget(self._poster, alignment=Qt.AlignmentFlag.AlignTop)

        body = QVBoxLayout()
        body.setSpacing(6)
        summary_row.addLayout(body, stretch=1)

        self._title = QLabel("Select a job to see details")
        self._title.setProperty("cssClass", "heading")
        self._title.setMargin(2)
        self._title.setWordWrap(True)
        self._title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        body.addWidget(self._title)

        self._meta = QLabel("")
        self._meta.setProperty("cssClass", "text-dim")
        self._meta.setMargin(1)
        self._meta.setWordWrap(True)
        self._meta.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        body.addWidget(self._meta)

        self._summary = QLabel("")
        self._summary.setMargin(1)
        self._summary.setWordWrap(True)
        self._summary.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        body.addWidget(self._summary)

        self._facts_card = QFrame()
        self._facts_card.setProperty("cssClass", "job-detail-facts-card")
        facts_layout = QGridLayout(self._facts_card)
        facts_layout.setContentsMargins(12, 12, 12, 12)
        facts_layout.setHorizontalSpacing(14)
        facts_layout.setVerticalSpacing(10)
        facts_layout.setColumnStretch(0, 1)
        facts_layout.setColumnStretch(1, 1)
        self._fact_values: dict[str, QLabel] = {}
        fact_specs = [
            ("Media", "media"),
            ("Action", "action"),
            ("Files", "files"),
            ("Companions", "companions"),
        ]
        for index, (label_text, key) in enumerate(fact_specs):
            cell = QWidget()
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.setSpacing(2)

            key_label = QLabel(label_text)
            key_label.setProperty("cssClass", "caption")
            cell_layout.addWidget(key_label)

            value_label = QLabel("")
            value_label.setProperty("cssClass", "job-detail-fact-value")
            value_label.setWordWrap(True)
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            cell_layout.addWidget(value_label)

            self._fact_values[key] = value_label
            facts_layout.addWidget(cell, index // 2, index % 2)

        body.addWidget(self._facts_card)

        folder_actions = QHBoxLayout()
        folder_actions.setContentsMargins(0, 0, 0, 0)
        folder_actions.setSpacing(8)
        self._open_source_btn = QPushButton("Open Source")
        self._open_source_btn.setProperty("cssClass", "secondary")
        self._open_source_btn.setProperty("sizeVariant", "detail")
        self._open_source_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._open_source_btn.clicked.connect(self.open_source_folder)
        folder_actions.addWidget(self._open_source_btn, stretch=1)

        self._open_target_btn = QPushButton("Open Target")
        self._open_target_btn.setProperty("cssClass", "secondary")
        self._open_target_btn.setProperty("sizeVariant", "detail")
        self._open_target_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._open_target_btn.clicked.connect(self.open_target_folder)
        folder_actions.addWidget(self._open_target_btn, stretch=1)
        body.addLayout(folder_actions)

        self._preview_tree = _PreviewTreeWidget()
        self._preview_tree.setProperty("cssClass", "job-preview-tree")
        self._preview_tree.setColumnCount(1)
        self._preview_tree.setHeaderHidden(True)
        self._preview_tree.setRootIsDecorated(False)
        self._preview_tree.setIndentation(12)
        self._preview_tree.setMinimumHeight(0)
        self._preview_tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._preview_tree.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._preview_tree.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._preview_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._preview_tree.setExpandsOnDoubleClick(False)
        self._preview_tree.header().setStretchLastSection(True)
        self._preview_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._preview_tree.itemClicked.connect(self._on_preview_item_clicked)
        self._preview_tree.itemExpanded.connect(self._on_preview_group_expanded)
        self._preview_tree.itemCollapsed.connect(self._on_preview_group_collapsed)
        self._preview_tree.itemExpanded.connect(self._refresh_preview_item_sizes)
        self._preview_tree.itemCollapsed.connect(self._refresh_preview_item_sizes)
        self._preview_tree.resized.connect(self._refresh_preview_item_sizes)
        layout.addWidget(self._preview_tree, stretch=1)

        self._error = QLabel("")
        self._error.setWordWrap(True)
        self._error.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        layout.addWidget(self._error)

        self._stack.addWidget(self._detail_page)
        self._update_empty_message()
        self.clear()

    def set_history_mode(self, history: bool) -> None:
        """Toggle between queue mode (history=False) and history mode."""
        self._history_mode = history
        self._update_empty_message()

    def clear(self, text: str = _EMPTY_TITLE) -> None:
        self._current_job_id = None
        self._current_job = None
        self._poster_pixmap = None
        self._poster.setPixmap(QPixmap())
        self._poster.setText("No Poster")
        self._title.setText(text)
        self._meta.setText("")
        self._summary.setText("")
        self._summary.hide()
        for label in self._fact_values.values():
            label.setText("")
            label.setToolTip("")
        self._preview_tree.clear()
        self._error.setText("")
        self._open_source_btn.hide()
        self._open_target_btn.hide()
        self._open_source_btn.setEnabled(False)
        self._open_target_btn.setEnabled(False)
        self._empty_title.setText(text)
        self._stack.setCurrentWidget(self._empty_page)

    def set_job(self, job: RenameJob | None) -> None:
        if job is None:
            self.clear()
            return

        self._stack.setCurrentWidget(self._detail_page)
        self._current_job_id = job.job_id
        self._current_job = job
        self._poster_pixmap = None
        self._poster.setPixmap(QPixmap())
        self._poster.setText("Loading...")
        self._title.setText(job.media_name or "Unnamed Job")
        self._meta.setText(self._build_meta_line(job))
        summary_text = self._build_summary(job)
        self._summary.setText(summary_text)
        self._summary.setVisible(bool(summary_text))
        self._populate_fact_values(job)
        self._populate_preview_tree(job)
        self._open_source_btn.show()
        self._open_target_btn.show()
        self._open_source_btn.setEnabled(self.can_open_source_folder())
        if self._history_mode:
            self._open_target_btn.setEnabled(self.can_open_target_folder())
        else:
            self._open_target_btn.setEnabled(False)
        if job.error_message:
            self._error.setText(job.error_message)
            self._error.setStyleSheet("color: #d44040;")
        else:
            self._error.setText("")
            self._error.setStyleSheet("")
        self._request_poster(job)

    def can_open_source_folder(self) -> bool:
        return self._current_job is not None and self._resolve_openable_path(self._current_job.source_path) is not None

    def can_open_target_folder(self) -> bool:
        return self._current_job is not None and self._primary_target_path(self._current_job) is not None

    def open_source_folder(self) -> bool:
        if self._current_job is None:
            return False
        return self._open_path(self._current_job.source_path)

    def open_target_folder(self) -> bool:
        if self._current_job is None:
            return False
        target = self._primary_target_path(self._current_job)
        if target is None:
            return False
        return self._open_path(target)

    def _build_summary(self, job: RenameJob) -> str:
        return build_job_summary(job)

    def _build_meta_line(self, job: RenameJob) -> str:
        return build_job_meta_line(job, history_mode=self._history_mode)

    def _populate_fact_values(self, job: RenameJob) -> None:
        values = build_job_fact_values(job)
        for key, text in values.items():
            label = self._fact_values[key]
            label.setText(text)
            label.setToolTip(text)

    def _populate_preview_tree(self, job: RenameJob) -> None:
        self._preview_tree.clear()
        entries = build_job_preview_entries(job)
        if not entries:
            placeholder = QTreeWidgetItem(self._preview_tree, ["No rename operations recorded."])
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self._refresh_preview_item_sizes()
            return

        for entry in entries:
            self._add_preview_entry(entry)

        self._refresh_preview_item_sizes()

    def _add_preview_entry(self, entry: JobPreviewRow | JobPreviewGroup) -> None:
        if isinstance(entry, JobPreviewGroup):
            header = self._make_group_header(self._preview_tree, entry.label)
            for row in entry.rows:
                self._add_preview_row(
                    header,
                    before=row.before,
                    after=row.after,
                    before_label=row.before_label,
                    after_label=row.after_label,
                )
            header.setExpanded(entry.expanded)
            self._update_group_header_label(header, expanded=entry.expanded)
            return

        self._add_preview_row(
            self._preview_tree,
            before=entry.before,
            after=entry.after,
            before_label=entry.before_label,
            after_label=entry.after_label,
        )

    def _add_preview_row(
        self,
        parent,
        *,
        before: str,
        after: str,
        before_label: str = "Original",
        after_label: str = "New",
    ) -> QTreeWidgetItem:
        item = QTreeWidgetItem(parent, [""])
        widget = _RenamePreviewWidget(
            before=before,
            after=after,
            before_label=before_label,
            after_label=after_label,
            parent=self._preview_tree,
        )
        item.setSizeHint(0, widget.sizeHint())
        self._preview_tree.setItemWidget(item, 0, widget)
        return item

    def _make_group_header(self, parent, label: str) -> QTreeWidgetItem:
        return create_preview_group_header(parent, label)

    def _update_group_header_label(self, item: QTreeWidgetItem, *, expanded: bool) -> None:
        set_preview_group_header_label(item, expanded=expanded)

    def _on_preview_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        toggle_preview_group_item(item)

    def _on_preview_group_expanded(self, item: QTreeWidgetItem) -> None:
        if item.childCount() <= 0:
            return
        self._update_group_header_label(item, expanded=True)

    def _on_preview_group_collapsed(self, item: QTreeWidgetItem) -> None:
        if item.childCount() <= 0:
            return
        self._update_group_header_label(item, expanded=False)

    def _refresh_preview_item_sizes(self, *_args) -> None:
        refresh_preview_item_sizes(self._preview_tree)

    def _update_empty_message(self) -> None:
        self._empty_message.setText(job_detail_empty_message(history_mode=self._history_mode))

    def _primary_target_path(self, job: RenameJob) -> Path | None:
        return primary_target_path(job)

    def _resolve_openable_path(self, path: Path | None) -> Path | None:
        return resolve_openable_path(path)

    def _open_path(self, path: Path) -> bool:
        resolved = self._resolve_openable_path(path)
        if resolved is None:
            return False
        return QDesktopServices.openUrl(QUrl.fromLocalFile(str(resolved)))

    def _request_poster(self, job: RenameJob) -> None:
        self._poster_workflow.request(job)

    def _apply_poster(self, image_data, job_id: str) -> None:
        self._poster_workflow.apply(image_data, job_id)