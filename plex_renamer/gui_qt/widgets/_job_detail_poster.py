"""Poster loading workflow for JobDetailPanel."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap

from ...job_store import RenameJob
from ...thread_pool import submit as _submit_bg
from ._image_utils import pil_to_raw, raw_to_pixmap


class _JobDetailPosterPanel(Protocol):
    _tmdb_provider: Callable[[], object | None] | None
    _persist_poster_path: Callable[[str, str | None], None] | None
    _current_job_id: str | None
    _poster_pixmap: QPixmap | None
    _bridge: Any
    _poster: Any


class JobDetailPosterWorkflow:
    def __init__(self, panel: _JobDetailPosterPanel) -> None:
        self._panel = panel

    def request(self, job: RenameJob) -> None:
        panel = self._panel
        if panel._tmdb_provider is None:
            self._show_no_poster()
            return

        tmdb = panel._tmdb_provider()
        if tmdb is None:
            self._show_no_poster()
            return

        def _worker() -> None:
            image = None
            poster_path = job.poster_path
            if not poster_path and job.tmdb_id:
                poster_path = tmdb.get_cached_poster_path(job.tmdb_id, media_type=job.media_type)
                if poster_path:
                    self._persist_poster_path(job, poster_path)

            if poster_path:
                image = tmdb.fetch_image(poster_path, target_width=200)
            elif job.tmdb_id:
                image = tmdb.fetch_poster(job.tmdb_id, media_type=job.media_type, target_width=200)
                poster_path = tmdb.get_cached_poster_path(job.tmdb_id, media_type=job.media_type)
                if poster_path:
                    self._persist_poster_path(job, poster_path)

            try:
                panel._bridge.poster_ready.emit(None if image is None else pil_to_raw(image), job.job_id)
            except RuntimeError:
                return

        _submit_bg(_worker)

    def apply(self, image_data: Any, job_id: str) -> None:
        panel = self._panel
        if job_id != panel._current_job_id:
            return
        if image_data is None:
            self._show_no_poster()
            return

        pixmap = raw_to_pixmap(image_data)
        if pixmap.isNull():
            self._show_no_poster()
            return

        panel._poster_pixmap = pixmap
        panel._poster.setText("")
        panel._poster.setPixmap(
            pixmap.scaled(
                panel._poster.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _persist_poster_path(self, job: RenameJob, poster_path: str) -> None:
        panel = self._panel
        job.poster_path = poster_path
        if panel._persist_poster_path is not None:
            panel._persist_poster_path(job.job_id, poster_path)

    def _show_no_poster(self) -> None:
        panel = self._panel
        panel._poster_pixmap = None
        panel._poster.setPixmap(QPixmap())
        panel._poster.setText("No Poster")
