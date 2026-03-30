"""Shared job detail panel for queue and history tabs."""

from __future__ import annotations

import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QHBoxLayout, QVBoxLayout, QWidget

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
        self._poster_pixmap: QPixmap | None = None
        self._bridge = _PosterBridge(self)
        self._bridge.poster_ready.connect(self._apply_poster)
        self.setProperty("cssClass", "panel")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        self._poster = QLabel()
        self._poster.setFixedSize(96, 144)
        self._poster.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._poster.setProperty("cssClass", "card")
        self._poster.setText("No Poster")
        layout.addWidget(self._poster, alignment=Qt.AlignmentFlag.AlignTop)

        body = QVBoxLayout()
        body.setSpacing(6)
        layout.addLayout(body, stretch=1)

        self._title = QLabel("Select a job to see details")
        self._title.setProperty("cssClass", "heading")
        body.addWidget(self._title)

        self._meta = QLabel("")
        self._meta.setProperty("cssClass", "text-dim")
        body.addWidget(self._meta)

        self._summary = QLabel("")
        self._summary.setWordWrap(True)
        body.addWidget(self._summary)

        self._paths = QLabel("")
        self._paths.setProperty("cssClass", "caption")
        self._paths.setWordWrap(True)
        body.addWidget(self._paths)

        self._error = QLabel("")
        self._error.setWordWrap(True)
        body.addWidget(self._error)

    def clear(self, text: str = "Select a job to see details") -> None:
        self._current_job_id = None
        self._poster_pixmap = None
        self._poster.setPixmap(QPixmap())
        self._poster.setText("No Poster")
        self._title.setText(text)
        self._meta.setText("")
        self._summary.setText("")
        self._paths.setText("")
        self._error.setText("")

    def set_job(self, job: RenameJob | None) -> None:
        if job is None:
            self.clear()
            return

        self._current_job_id = job.job_id
        self._poster_pixmap = None
        self._poster.setPixmap(QPixmap())
        self._poster.setText("Loading...")
        self._title.setText(job.media_name or "Unnamed Job")
        self._meta.setText(
            f"{job.media_type.upper()} · {job.job_kind.title()} · {job.status.title()}"
        )
        self._summary.setText(self._build_summary(job))
        self._paths.setText(
            f"Library: {job.library_root}\nSource: {job.source_folder}"
            + (f"\nTarget Folder: {job.show_folder_rename}" if job.show_folder_rename else "")
        )
        if job.error_message:
            self._error.setText(job.error_message)
            self._error.setStyleSheet("color: #d44040;")
        else:
            self._error.setText("")
            self._error.setStyleSheet("")
        self._request_poster(job)

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
        return " · ".join(parts)

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