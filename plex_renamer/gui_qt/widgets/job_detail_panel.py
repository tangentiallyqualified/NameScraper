"""Shared job detail panel for queue and history tabs."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from ...constants import JobStatus
from ...job_store import RenameJob
from ._image_utils import pil_to_raw, raw_to_pixmap


class _PosterBridge(QObject):
    """Marshal poster pixmaps from worker threads to the UI thread."""

    poster_ready = Signal(object, str)


class JobDetailPanel(QFrame):
    """Shows the selected job summary, status, paths, and optional poster."""

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
        self.setMinimumWidth(360)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        self._poster = QLabel()
        self._poster.setFixedSize(160, 240)
        self._poster.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._poster.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._poster.setProperty("cssClass", "card")
        self._poster.setText("No Poster")
        layout.addWidget(self._poster, alignment=Qt.AlignmentFlag.AlignTop)

        body = QVBoxLayout()
        body.setSpacing(6)
        layout.addLayout(body, stretch=1)

        self._title = QLabel("Select a job to see details")
        self._title.setProperty("cssClass", "heading")
        self._title.setWordWrap(True)
        self._title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        body.addWidget(self._title)

        self._meta = QLabel("")
        self._meta.setProperty("cssClass", "text-dim")
        self._meta.setWordWrap(True)
        self._meta.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        body.addWidget(self._meta)

        self._summary = QLabel("")
        self._summary.setWordWrap(True)
        self._summary.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        body.addWidget(self._summary)

        folder_actions = QVBoxLayout()
        folder_actions.setSpacing(6)
        self._open_source_btn = QPushButton("Open Source Folder")
        self._open_source_btn.setProperty("cssClass", "secondary")
        self._open_source_btn.clicked.connect(self.open_source_folder)
        folder_actions.addWidget(self._open_source_btn)

        self._open_target_btn = QPushButton("Open Target Folder")
        self._open_target_btn.setProperty("cssClass", "secondary")
        self._open_target_btn.clicked.connect(self.open_target_folder)
        folder_actions.addWidget(self._open_target_btn)
        body.addLayout(folder_actions)

        self._paths = QLabel("")
        self._paths.setProperty("cssClass", "caption")
        self._paths.setWordWrap(True)
        self._paths.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        body.addWidget(self._paths)

        preview_heading = QLabel("Rename Preview")
        preview_heading.setProperty("cssClass", "text-dim")
        body.addWidget(preview_heading)

        self._preview_tree = QTreeWidget()
        self._preview_tree.setHeaderLabels(["Original", "New Name"])
        self._preview_tree.setRootIsDecorated(True)
        self._preview_tree.setMinimumHeight(0)
        self._preview_tree.setSelectionMode(QTreeWidget.SelectionMode.NoSelection)
        self._preview_tree.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._preview_tree.header().setStretchLastSection(False)
        self._preview_tree.header().setSectionResizeMode(0, self._preview_tree.header().ResizeMode.Stretch)
        self._preview_tree.header().setSectionResizeMode(1, self._preview_tree.header().ResizeMode.Stretch)
        body.addWidget(self._preview_tree, stretch=1)

        self._error = QLabel("")
        self._error.setWordWrap(True)
        self._error.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        body.addWidget(self._error)

    def set_history_mode(self, history: bool) -> None:
        """Toggle between queue mode (history=False) and history mode."""
        self._history_mode = history

    def clear(self, text: str = "Select a job to see details") -> None:
        self._current_job_id = None
        self._current_job = None
        self._poster_pixmap = None
        self._poster.setPixmap(QPixmap())
        self._poster.setText("No Poster")
        self._title.setText(text)
        self._meta.setText("")
        self._summary.setText("")
        self._paths.setText("")
        self._preview_tree.clear()
        self._error.setText("")
        self._open_source_btn.hide()
        self._open_target_btn.hide()

    def set_job(self, job: RenameJob | None) -> None:
        if job is None:
            self.clear()
            return

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
        self._paths.setText(self._build_path_summary(job))
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

    def _build_path_summary(self, job: RenameJob) -> str:
        lines = [
            f"Library: {job.library_root}",
            f"Source: {job.source_path}",
        ]
        if job.show_folder_rename:
            source_name = Path(job.source_folder).name or job.source_folder
            lines.append(f"Folder Rename: {source_name} -> {job.show_folder_rename}")
        targets = self._target_paths(job)
        if targets:
            preview_targets = [str(path) for path in targets[:2]]
            target_text = "\n".join(f"Target: {path}" for path in preview_targets)
            lines.append(target_text)
            if len(targets) > 2:
                lines.append(f"Target Folders: {len(targets)} total")
        return "\n".join(lines)

    def _populate_preview_tree(self, job: RenameJob) -> None:
        self._preview_tree.clear()
        ops = job.selected_ops or job.rename_ops
        if not ops:
            placeholder = QTreeWidgetItem(self._preview_tree, ["No rename operations recorded.", ""])
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            return

        # Folder rename banner
        if job.show_folder_rename:
            source_name = Path(job.source_folder).name or job.source_folder
            if source_name and source_name != ".":
                folder_item = QTreeWidgetItem(self._preview_tree, [source_name, job.show_folder_rename])
                folder_item.setFirstColumnSpanned(False)
                font = folder_item.font(0)
                font.setBold(True)
                folder_item.setFont(0, font)
                folder_item.setFont(1, font)

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
                header = QTreeWidgetItem(self._preview_tree, [label, ""])
                header.setFirstColumnSpanned(True)
                font = header.font(0)
                font.setBold(True)
                header.setFont(0, font)
                for op in season_ops:
                    original = Path(op.original_relative).name
                    QTreeWidgetItem(header, [original, op.new_name])
                header.setExpanded(len(by_season) <= 3)
        else:
            for op in video_ops:
                original = Path(op.original_relative).name
                QTreeWidgetItem(self._preview_tree, [original, op.new_name])

        # Companion files section
        if companion_ops:
            comp_header = QTreeWidgetItem(
                self._preview_tree,
                [f"Companion Files ({len(companion_ops)})", ""],
            )
            comp_header.setFirstColumnSpanned(True)
            font = comp_header.font(0)
            font.setBold(True)
            comp_header.setFont(0, font)
            for op in companion_ops:
                original = Path(op.original_relative).name
                QTreeWidgetItem(comp_header, [original, op.new_name])
            comp_header.setExpanded(False)


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
                self._bridge.poster_ready.emit(None, job.job_id)
                return
            self._bridge.poster_ready.emit(pil_to_raw(image), job.job_id)

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