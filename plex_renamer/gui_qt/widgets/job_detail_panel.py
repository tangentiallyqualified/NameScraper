"""Shared job detail panel for queue and history tabs."""

from __future__ import annotations

import threading
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

from ...constants import JobStatus
from ...job_store import RenameJob
from ._image_utils import pil_to_raw, raw_to_pixmap


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

        folder_actions = QHBoxLayout()
        folder_actions.setContentsMargins(0, 0, 0, 0)
        folder_actions.setSpacing(8)
        self._open_source_btn = QPushButton("Open Source")
        self._open_source_btn.setProperty("cssClass", "secondary")
        self._open_source_btn.setProperty("sizeVariant", "detail")
        self._open_source_btn.clicked.connect(self.open_source_folder)
        folder_actions.addWidget(self._open_source_btn)

        self._open_target_btn = QPushButton("Open Target")
        self._open_target_btn.setProperty("cssClass", "secondary")
        self._open_target_btn.setProperty("sizeVariant", "detail")
        self._open_target_btn.clicked.connect(self.open_target_folder)
        folder_actions.addWidget(self._open_target_btn)
        folder_actions.addStretch()
        body.addLayout(folder_actions)

        preview_heading = QLabel("Rename Preview")
        preview_heading.setProperty("cssClass", "text-dim")
        layout.addWidget(preview_heading)

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
        self._preview_tree.clear()
        self._error.setText("")
        self._open_source_btn.hide()
        self._open_target_btn.hide()
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
        self._meta.setText(
            f"{job.media_type.upper()} · {job.job_kind.title()} · {job.status.title()}"
        )
        self._summary.setText(self._build_summary(job))
        self._populate_preview_tree(job)
        self._open_source_btn.show()
        self._open_source_btn.setEnabled(self.can_open_source_folder())
        if self._history_mode:
            self._open_target_btn.show()
            self._open_target_btn.setEnabled(self.can_open_target_folder())
        else:
            self._open_target_btn.hide()
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
        renames = job.selected_count
        companion = len(job.companion_ops)
        parts = [f"{renames} selected file(s)"]
        if companion:
            parts.append(f"{companion} companion file(s)")
        if job.depends_on:
            parts.append(f"Depends on {job.depends_on[:8]}...")
        if job.status == JobStatus.REVERTED:
            parts.append("Reverted")
        elif job.status == JobStatus.REVERT_FAILED:
            parts.append("Revert Failed")
        return " · ".join(parts)

    def _populate_preview_tree(self, job: RenameJob) -> None:
        self._preview_tree.clear()
        ops = job.selected_ops or job.rename_ops
        has_preview_rows = False

        folder_preview = self._folder_preview_data(job)
        if folder_preview is not None:
            source_name, target_name = folder_preview
            folder_header = self._make_group_header(self._preview_tree, "Folder Rename")
            self._add_preview_row(
                folder_header,
                before=source_name,
                after=target_name,
                before_label="Source",
                after_label="Target",
            )
            folder_header.setExpanded(True)
            self._update_group_header_label(folder_header, expanded=True)
            has_preview_rows = True

        if not ops:
            if not has_preview_rows:
                placeholder = QTreeWidgetItem(self._preview_tree, ["No rename operations recorded."])
                placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self._refresh_preview_item_sizes()
            return

        video_ops = [op for op in ops if op.file_type == "video"]
        companion_ops = [op for op in ops if op.file_type != "video"]

        # Group video ops by season
        is_tv = job.media_type == "tv"
        if is_tv and any(op.season is not None for op in video_ops):
            from collections import defaultdict
            by_season: dict[int | None, list] = defaultdict(list)
            for op in video_ops:
                by_season[op.season].append(op)
            for season_num in sorted(by_season, key=lambda s: (s is None, s or 0)):
                season_ops = by_season[season_num]
                if season_num is not None:
                    label = f"Season {season_num:02d} ({len(season_ops)} files)"
                else:
                    label = f"Other Files ({len(season_ops)} files)"
                header = self._make_group_header(self._preview_tree, label)
                for op in season_ops:
                    original = Path(op.original_relative).name
                    self._add_preview_row(header, before=original, after=op.new_name)
                header.setExpanded(False)
                has_preview_rows = True
        else:
            video_parent = self._preview_tree
            if job.media_type == "movie" and video_ops:
                video_parent = self._make_group_header(self._preview_tree, "File Rename")
                video_parent.setExpanded(True)
                self._update_group_header_label(video_parent, expanded=True)
            for op in video_ops:
                original = Path(op.original_relative).name
                self._add_preview_row(video_parent, before=original, after=op.new_name)
                has_preview_rows = True

        # Companion files section
        if companion_ops:
            comp_header = self._make_group_header(
                self._preview_tree,
                f"Companion Files ({len(companion_ops)})",
            )
            for op in companion_ops:
                original = Path(op.original_relative).name
                self._add_preview_row(comp_header, before=original, after=op.new_name)
            comp_header.setExpanded(False)
            has_preview_rows = True

        if not has_preview_rows:
            placeholder = QTreeWidgetItem(self._preview_tree, ["No rename operations recorded."])
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)

        self._refresh_preview_item_sizes()

    def _folder_preview_data(self, job: RenameJob) -> tuple[str, str] | None:
        if job.show_folder_rename:
            source_name = self._folder_preview_source_name(job, include_media_name=True)
            if source_name:
                return source_name, job.show_folder_rename
            return None

        if job.media_type != "movie":
            return None

        source_name = self._folder_preview_source_name(job, include_media_name=False)
        target_name = self._movie_target_folder_name(job)
        if not source_name or not target_name or source_name == target_name:
            return None
        return source_name, target_name

    def _folder_preview_source_name(
        self,
        job: RenameJob,
        *,
        include_media_name: bool = True,
    ) -> str | None:
        source_name = Path(job.source_folder).name or job.source_folder
        if source_name and source_name != ".":
            return source_name

        ops = job.selected_ops or job.rename_ops
        for op in ops:
            parent = Path(op.original_relative).parent
            parts = [part for part in parent.parts if part not in {"", "."}]
            if parts:
                return parts[0]

        library_root_name = Path(job.library_root).name
        if library_root_name:
            return library_root_name

        if include_media_name and job.media_name:
            return job.media_name
        return None

    def _movie_target_folder_name(self, job: RenameJob) -> str | None:
        ops = job.selected_ops or job.rename_ops
        candidate_ops = [op for op in ops if op.file_type == "video"] or ops
        target_names: set[str] = set()
        for op in candidate_ops:
            parts = [part for part in Path(op.target_dir_relative).parts if part not in {"", "."}]
            if parts:
                target_names.add(parts[0])
        if len(target_names) != 1:
            return None
        return next(iter(target_names))

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
        item = QTreeWidgetItem(parent, [""])
        item.setData(0, Qt.ItemDataRole.UserRole, label)
        item.setFirstColumnSpanned(True)
        font = item.font(0)
        font.setBold(True)
        item.setFont(0, font)
        self._update_group_header_label(item, expanded=False)
        return item

    def _update_group_header_label(self, item: QTreeWidgetItem, *, expanded: bool) -> None:
        base_label = item.data(0, Qt.ItemDataRole.UserRole) or item.text(0)
        prefix = "▾ " if expanded else "▸ "
        item.setText(0, f"{prefix}{base_label}")

    def _on_preview_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        if item.childCount() <= 0:
            return
        item.setExpanded(not item.isExpanded())

    def _on_preview_group_expanded(self, item: QTreeWidgetItem) -> None:
        if item.childCount() <= 0:
            return
        self._update_group_header_label(item, expanded=True)

    def _on_preview_group_collapsed(self, item: QTreeWidgetItem) -> None:
        if item.childCount() <= 0:
            return
        self._update_group_header_label(item, expanded=False)

    def _refresh_preview_item_sizes(self, *_args) -> None:
        reserved_scrollbar = self._preview_tree.verticalScrollBar().sizeHint().width() + 6
        viewport_width = max(220, self._preview_tree.viewport().width() - reserved_scrollbar)

        def _walk(parent: QTreeWidgetItem | None, depth: int) -> None:
            count = parent.childCount() if parent is not None else self._preview_tree.topLevelItemCount()
            for row in range(count):
                item = parent.child(row) if parent is not None else self._preview_tree.topLevelItem(row)
                widget = self._preview_tree.itemWidget(item, 0)
                if widget is not None:
                    available_width = max(180, viewport_width - (depth * self._preview_tree.indentation()))
                    widget.setFixedWidth(available_width)
                    widget.adjustSize()
                    if isinstance(widget, _RenamePreviewWidget):
                        widget._sync_tooltip()
                    item.setSizeHint(0, widget.sizeHint())
                _walk(item, depth + 1)

        _walk(None, 0)

    def _update_empty_message(self) -> None:
        if self._history_mode:
            self._empty_message.setText(
                "History entries will appear here. Select one to review its rename preview, poster, and file locations."
            )
            return
        self._empty_message.setText(
            "Queued jobs will appear here. Select one to review its rename preview, poster, and file locations."
        )


    def _target_paths(self, job: RenameJob) -> list[Path]:
        paths: list[Path] = []
        seen: set[Path] = set()
        ops = job.selected_ops or job.rename_ops
        for op in ops:
            target = Path(job.library_root) / self._final_target_dir_relative(job, op)
            if target not in seen:
                seen.add(target)
                paths.append(target)
        if not paths and job.show_folder_rename:
            source_folder = Path(job.source_folder)
            if job.source_folder in ("", "."):
                fallback = Path(job.library_root) / job.show_folder_rename
            else:
                fallback = Path(job.library_root) / source_folder.parent / job.show_folder_rename
            paths.append(fallback)
        return paths

    def _primary_target_path(self, job: RenameJob) -> Path | None:
        targets = self._target_paths(job)
        if not targets:
            return None
        return targets[0]

    def _final_target_dir_relative(self, job: RenameJob, op) -> Path:
        target_dir = Path(op.target_dir_relative)
        if not job.show_folder_rename or job.source_folder in ("", "."):
            return target_dir
        source_parts = Path(job.source_folder).parts
        target_parts = target_dir.parts
        if len(target_parts) >= len(source_parts) and tuple(target_parts[: len(source_parts)]) == source_parts:
            replacement = (*source_parts[:-1], job.show_folder_rename, *target_parts[len(source_parts):])
            return Path(*replacement)
        return target_dir

    def _resolve_openable_path(self, path: Path | None) -> Path | None:
        candidate = path
        while candidate is not None:
            if candidate.exists():
                return candidate
            parent = candidate.parent
            if parent == candidate:
                break
            candidate = parent
        return None

    def _open_path(self, path: Path) -> bool:
        resolved = self._resolve_openable_path(path)
        if resolved is None:
            return False
        return QDesktopServices.openUrl(QUrl.fromLocalFile(str(resolved)))

    def _request_poster(self, job: RenameJob) -> None:
        if self._tmdb_provider is None:
            self._poster.setText("No Poster")
            return
        tmdb = self._tmdb_provider()
        if tmdb is None:
            self._poster.setText("No Poster")
            return

        def _worker() -> None:
            image = None
            poster_path = job.poster_path
            if not poster_path and job.tmdb_id:
                poster_path = tmdb.get_cached_poster_path(job.tmdb_id, media_type=job.media_type)
                if poster_path:
                    job.poster_path = poster_path
                    if self._persist_poster_path is not None:
                        self._persist_poster_path(job.job_id, poster_path)

            if poster_path:
                image = tmdb.fetch_image(poster_path, target_width=200)
            elif job.tmdb_id:
                image = tmdb.fetch_poster(job.tmdb_id, media_type=job.media_type, target_width=200)
                poster_path = tmdb.get_cached_poster_path(job.tmdb_id, media_type=job.media_type)
                if poster_path:
                    job.poster_path = poster_path
                    if self._persist_poster_path is not None:
                        self._persist_poster_path(job.job_id, poster_path)
            if image is None:
                try:
                    self._bridge.poster_ready.emit(None, job.job_id)
                except RuntimeError:
                    return
                return
            try:
                self._bridge.poster_ready.emit(pil_to_raw(image), job.job_id)
            except RuntimeError:
                return

        threading.Thread(target=_worker, daemon=True, name="QtJobPoster").start()

    def _apply_poster(self, image_data, job_id: str) -> None:
        if job_id != self._current_job_id:
            return
        if image_data is None:
            self._poster_pixmap = None
            self._poster.setPixmap(QPixmap())
            self._poster.setText("No Poster")
            return
        pixmap = raw_to_pixmap(image_data)
        if pixmap.isNull():
            self._poster_pixmap = None
            self._poster.setPixmap(QPixmap())
            self._poster.setText("No Poster")
            return
        self._poster_pixmap = pixmap
        self._poster.setText("")
        scaled = pixmap.scaled(
            self._poster.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._poster.setPixmap(scaled)