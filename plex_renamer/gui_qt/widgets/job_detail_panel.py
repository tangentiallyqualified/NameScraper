"""Shared job detail panel for queue and history tabs."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QSizePolicy, QVBoxLayout, QWidget

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
        self._poster.setFixedSize(96, 144)
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

        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setMinimumHeight(0)
        self._preview.setPlaceholderText("Rename operations appear here.")
        self._preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        body.addWidget(self._preview, stretch=1)

        self._error = QLabel("")
        self._error.setWordWrap(True)
        self._error.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        body.addWidget(self._error)

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
        self._preview.clear()
        self._error.setText("")
        self._open_source_btn.setEnabled(False)
        self._open_target_btn.setEnabled(False)

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
        self._preview.setPlainText(self._build_operation_preview(job))
        self._open_source_btn.setEnabled(self.can_open_source_folder())
        self._open_target_btn.setEnabled(self.can_open_target_folder())
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

    def _build_operation_preview(self, job: RenameJob) -> str:
        ops = job.selected_ops or job.rename_ops
        if not ops:
            return "No rename operations recorded for this job."

        preview_lines: list[str] = []
        if job.show_folder_rename:
            source_name = Path(job.source_folder).name or job.source_folder
            if source_name and source_name != ".":
                preview_lines.append(f"Folder: {source_name} -> {job.show_folder_rename}")
                preview_lines.append("")

        preview_limit = 8
        for op in ops[:preview_limit]:
            target_dir = self._final_target_dir_relative(job, op)
            target_path = target_dir / op.new_name if str(target_dir) not in ("", ".") else Path(op.new_name)
            preview_lines.append(f"{op.original_relative} -> {target_path}")
        if len(ops) > preview_limit:
            preview_lines.append(f"... {len(ops) - preview_limit} more operation(s)")

        if job.companion_ops:
            preview_lines.append("")
            preview_lines.append(f"Companion files included: {len(job.companion_ops)}")

        return "\n".join(preview_lines)

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
                image = tmdb.fetch_image(poster_path, target_width=96)
            elif job.tmdb_id:
                image = tmdb.fetch_poster(job.tmdb_id, media_type=job.media_type, target_width=96)
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