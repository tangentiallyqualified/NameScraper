"""Detail panel for TV and movie media selections in the Qt shell."""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable

from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from ...engine import PreviewItem, ScanState
from ._formatting import clamped_percent
from ._image_utils import ShimmerOverlay, build_placeholder_pixmap, pil_to_raw, raw_to_pixmap


def _format_rating(vote_average: float | None, vote_count: int = 0) -> str:
    if vote_average is None:
        return ""
    return f"{vote_average:.1f}/10" + (f" ({vote_count})" if vote_count else "")


def _format_runtime(minutes: int | None) -> str:
    if not minutes:
        return ""
    if minutes >= 60:
        hours, remain = divmod(minutes, 60)
        return f"{hours}h {remain}m" if remain else f"{hours}h"
    return f"{minutes}m"


class _DetailBridge(QObject):
    metadata_ready = Signal(object, object, str)


def _state_media_type(state: ScanState) -> str:
    media_type = state.media_info.get("_media_type")
    if media_type in {"movie", "tv"}:
        return media_type
    if any(item.media_type == "movie" for item in state.preview_items):
        return "movie"
    return "movie" if state.media_info.get("title") else "tv"


def _auto_accept_threshold(settings) -> float:
    if settings is None:
        return 0.55
    return settings.auto_accept_threshold


def _state_match_summary(state: ScanState, threshold: float) -> str:
    pct = f"{clamped_percent(state.confidence)}%"
    threshold_text = f"{clamped_percent(threshold)}%"
    if state.show_id is None:
        return "No confirmed TMDB match"
    if state.duplicate_of is not None:
        return f"{pct} confidence · duplicate match"
    if state.match_origin == "manual" and not state.needs_review:
        return f"{pct} confidence · manually approved"
    if state.needs_review:
        return f"{pct} confidence · below {threshold_text} threshold"
    return f"{pct} confidence · clears {threshold_text} threshold"


def _selection_artwork_mode(preview: PreviewItem | None) -> str:
    if preview is not None and preview.season is not None and preview.episodes:
        return "still"
    return "poster"


def _blur_and_darken(source: QPixmap, radius: int = 12, darkness: float = 0.70) -> QPixmap:
    """Return a blurred, darkened copy of *source* for backdrop use.

    Uses a simple box-blur approximation by scaling down then back up,
    then overlays a dark tint.  This avoids a dependency on
    QGraphicsBlurEffect (which requires a scene/view) and is fast enough
    for the single poster-sized image we need.
    """
    if source.isNull():
        return QPixmap()
    # Scale down to ~1/radius then back up for a fast blur approximation
    w, h = source.width(), source.height()
    tiny = source.scaled(
        max(1, w // radius),
        max(1, h // radius),
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    blurred = tiny.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    # Darken with a semi-transparent overlay
    result = QPixmap(blurred)
    painter = QPainter(result)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
    painter.fillRect(result.rect(), QColor(0, 0, 0, int(255 * darkness)))
    painter.end()
    return result


class _PosterHeroFrame(QFrame):
    """Poster with an optional blurred backdrop that extends behind it."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._backdrop: QPixmap | None = None

    def set_backdrop(self, source: QPixmap | None) -> None:
        if source is None or source.isNull():
            self._backdrop = None
        else:
            self._backdrop = _blur_and_darken(source)
        self.update()

    def clear_backdrop(self) -> None:
        self._backdrop = None
        self.update()

    def paintEvent(self, event) -> None:
        if self._backdrop is not None and not self._backdrop.isNull():
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawPixmap(self.rect(), self._backdrop)
            painter.end()
        super().paintEvent(event)


class MediaDetailPanel(QFrame):
    """Poster and metadata surface for the selected roster or preview item."""

    _MAX_METADATA_CACHE_ENTRIES = 64
    _PORTRAIT_ARTWORK_SIZE = QSize(220, 340)
    _LANDSCAPE_ARTWORK_SIZE = QSize(280, 158)

    def __init__(
        self,
        tmdb_provider: Callable[[], object | None] | None = None,
        settings_service=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tmdb_provider = tmdb_provider
        self._settings = settings_service
        self._current_token = ""
        self._poster_pixmap: QPixmap | None = None
        self._artwork_mode = "poster"
        self._current_state: ScanState | None = None
        self._current_preview: PreviewItem | None = None
        self._current_queue_reason = ""
        self._current_folder_plan = ""
        self._metadata_cache: OrderedDict[str, tuple[dict, QPixmap | None]] = OrderedDict()
        self._loading_tokens: set[str] = set()
        self._bridge = _DetailBridge(self)
        self._bridge.metadata_ready.connect(self._apply_payload)
        self.setProperty("cssClass", "panel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self._hero_frame = _PosterHeroFrame()
        poster_layout = QVBoxLayout(self._hero_frame)
        poster_layout.setContentsMargins(0, 0, 0, 0)
        poster_layout.setSpacing(0)

        self._poster = QLabel("No Poster")
        self._poster.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._set_artwork_mode("poster")
        self._poster.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._poster.setProperty("cssClass", "media-poster")
        self._poster_shimmer: ShimmerOverlay | None = None
        poster_layout.addWidget(self._poster)
        layout.addWidget(self._hero_frame, stretch=0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._body = QWidget()
        body_layout = QVBoxLayout(self._body)
        body_layout.setContentsMargins(0, 0, 4, 0)
        body_layout.setSpacing(10)
        self._scroll.setWidget(self._body)
        layout.addWidget(self._scroll, stretch=1)

        self._title = QLabel("Selection")
        self._title.setProperty("cssClass", "heading")
        self._title.setWordWrap(True)
        body_layout.addWidget(self._title)

        self._subtitle = QLabel("")
        self._subtitle.setProperty("cssClass", "text-dim")
        self._subtitle.setWordWrap(True)
        body_layout.addWidget(self._subtitle)

        self._meta_grid = QWidget()
        meta_layout = QGridLayout(self._meta_grid)
        meta_layout.setContentsMargins(0, 0, 0, 0)
        meta_layout.setHorizontalSpacing(10)
        meta_layout.setVerticalSpacing(6)
        self._meta_rows: list[tuple[QLabel, QLabel]] = []
        for row in range(6):
            key_label = QLabel("")
            key_label.setProperty("cssClass", "caption")
            value_label = QLabel("")
            value_label.setWordWrap(True)
            meta_layout.addWidget(key_label, row, 0, alignment=Qt.AlignmentFlag.AlignTop)
            meta_layout.addWidget(value_label, row, 1)
            self._meta_rows.append((key_label, value_label))
        body_layout.addWidget(self._meta_grid)

        self._overview = QLabel("")
        self._overview.setWordWrap(True)
        self._overview.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        body_layout.addWidget(self._overview)

        self._extra = QLabel("")
        self._extra.setProperty("cssClass", "caption")
        self._extra.setWordWrap(True)
        self._extra.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        body_layout.addWidget(self._extra)

        body_layout.addStretch()

        self.clear()

    def clear(self, text: str = "Choose a roster item to inspect details.") -> None:
        self._current_token = ""
        self._current_state = None
        self._current_preview = None
        self._current_queue_reason = ""
        self._current_folder_plan = ""
        self._poster_pixmap = None
        self._set_artwork_mode("poster")
        self._show_artwork_placeholder()
        self._title.setText("Selection")
        self._subtitle.setText(text)
        for key_label, value_label in self._meta_rows:
            key_label.setText("")
            value_label.setText("")
        self._overview.setText("")
        self._extra.setText("")

    def clear_metadata_cache(self) -> None:
        self._metadata_cache.clear()
        self._loading_tokens.clear()

    def set_selection(
        self,
        state: ScanState | None,
        preview: PreviewItem | None = None,
        queue_reason: str = "",
        folder_plan: str = "",
    ) -> None:
        if state is None:
            self.clear()
            return

        self._current_state = state
        self._current_preview = preview
        self._current_queue_reason = queue_reason
        self._current_folder_plan = folder_plan
        token = self._make_token(state, preview, queue_reason, folder_plan)
        self._current_token = token
        self._title.setText(state.display_name)

        tmdb = self._tmdb_provider() if self._tmdb_provider is not None else None
        if tmdb is None or not state.show_id:
            self._poster_pixmap = None
            self._set_artwork_mode(_selection_artwork_mode(preview))
            self._overview.setText("")
            self._extra.setText("")
            self._subtitle.setText(queue_reason or "TMDB metadata unavailable.")
            self._show_artwork_placeholder(state.display_name)
            self._set_meta_rows(self._fallback_rows(state, preview, queue_reason, folder_plan))
            return

        preview_pending = state.scanning or (not state.scanned and preview is None and not state.preview_items)
        if preview_pending:
            self._poster_pixmap = None
            self._set_artwork_mode(_selection_artwork_mode(preview))
            self._overview.setText("")
            self._extra.setText("")
            self._subtitle.setText("Preview is still loading...")
            self._show_artwork_placeholder(state.display_name)
            self._set_meta_rows(self._fallback_rows(state, preview, queue_reason, folder_plan))
            return

        cached = self._metadata_cache.get(token)
        if cached is not None:
            self._metadata_cache.move_to_end(token)
            self._apply_payload(cached[0], cached[1], token)
            return

        self._subtitle.setText(queue_reason or "Fetching metadata...")
        self._set_artwork_mode(_selection_artwork_mode(preview))
        self._show_artwork_placeholder(state.display_name, loading=True)
        self._set_meta_rows(self._fallback_rows(state, preview, queue_reason, folder_plan))
        if token in self._loading_tokens:
            return
        self._loading_tokens.add(token)

        def _worker() -> None:
            payload = self._build_payload(tmdb, state, preview, queue_reason, folder_plan)
            try:
                self._bridge.metadata_ready.emit(payload[0], payload[1], token)
            except RuntimeError:
                pass

        threading.Thread(target=_worker, daemon=True, name="QtMediaDetail").start()

    def _make_token(
        self,
        state: ScanState,
        preview: PreviewItem | None,
        queue_reason: str,
        folder_plan: str,
    ) -> str:
        preview_part = ""
        if preview is not None:
            preview_part = f":{preview.original}"
        return f"{state.show_id}:{state.folder}{preview_part}:{queue_reason}:{folder_plan}"

    def _fallback_rows(
        self,
        state: ScanState,
        preview: PreviewItem | None,
        queue_reason: str,
        folder_plan: str,
    ) -> list[tuple[str, str]]:
        threshold = _auto_accept_threshold(self._settings)
        rows = [("Queue", queue_reason)] if queue_reason else []
        if folder_plan:
            rows.append(("Folder", folder_plan))
        rows.append(("Match", _state_match_summary(state, threshold)))
        if preview is not None:
            rows.append(("File", preview.original.name))
            rows.append(("Status", preview.status))
        return rows

    def _build_payload(self, tmdb, state: ScanState, preview: PreviewItem | None, queue_reason: str, folder_plan: str):
        media_type = _state_media_type(state)
        threshold = _auto_accept_threshold(self._settings)
        details = (
            tmdb.get_movie_details(state.show_id)
            if media_type == "movie"
            else tmdb.get_tv_details(state.show_id)
        ) or {}

        season_num = None
        episode_meta = None
        if preview is not None and preview.season is not None and preview.episodes and state.scanner is not None:
            season_num = preview.season
            episode_meta = state.scanner.episode_meta.get((preview.season, preview.episodes[0]))
        ep_still = episode_meta.get("still_path") if episode_meta else None

        image = tmdb.fetch_poster(
            state.show_id,
            media_type=media_type,
            season=season_num,
            ep_still=ep_still,
            target_width=280,
        )
        raw_image = pil_to_raw(image) if image is not None else None

        subtitle_parts = []
        if state.media_info.get("year"):
            subtitle_parts.append(str(state.media_info.get("year")))
        if details.get("tagline"):
            subtitle_parts.append(details["tagline"])
        subtitle = " · ".join(part for part in subtitle_parts if part)

        rows: list[tuple[str, str]] = []
        rating = _format_rating(details.get("vote_average", 0), details.get("vote_count", 0))
        if rating:
            rows.append(("Rating", rating))
        if media_type == "movie":
            runtime = _format_runtime(details.get("runtime"))
            if runtime:
                rows.append(("Runtime", runtime))
            if details.get("release_date"):
                rows.append(("Release", details["release_date"]))
            genres = ", ".join(g.get("name", "") for g in details.get("genres", []) if g.get("name"))
            if genres:
                rows.append(("Genres", genres))
        else:
            if details.get("status"):
                rows.append(("Status", details["status"]))
            networks = ", ".join(n.get("name", "") for n in details.get("networks", []) if n.get("name"))
            if networks:
                rows.append(("Network", networks))
            season_count = details.get("number_of_seasons")
            episode_count = details.get("number_of_episodes")
            if season_count and episode_count:
                rows.append(("Seasons", f"{season_count} seasons · {episode_count} episodes"))
            if state.completeness is not None:
                rows.append(("Matched", f"{state.total_matched}/{state.total_expected} ({state.match_pct:.0f}%)"))

        rows.append(("Match", _state_match_summary(state, threshold)))
        if queue_reason:
            rows.append(("Queue", queue_reason))
        if folder_plan:
            rows.append(("Folder", folder_plan))
        if preview is not None:
            rows.append(("File", preview.original.name))
            if preview.new_name:
                rows.append(("Rename", preview.new_name))
            rows.append(("Preview", preview.status))
            if episode_meta and episode_meta.get("air_date"):
                rows.append(("Air Date", episode_meta["air_date"]))

        overview = ""
        if episode_meta and episode_meta.get("overview"):
            overview = episode_meta["overview"]
        else:
            overview = details.get("overview", "") or "No synopsis available."

        extra_lines = []
        if episode_meta:
            if ep_still:
                extra_lines.append("Artwork: episode still")
            if episode_meta.get("directors"):
                extra_lines.append("Directors: " + ", ".join(episode_meta["directors"]))
            if episode_meta.get("writers"):
                extra_lines.append("Writers: " + ", ".join(episode_meta["writers"]))
            guest_names = [guest.get("name", "") for guest in episode_meta.get("guest_stars", []) if guest.get("name")]
            if guest_names:
                extra_lines.append("Guests: " + ", ".join(guest_names[:4]))
        elif media_type == "movie":
            companies = [company.get("name", "") for company in details.get("production_companies", []) if company.get("name")]
            if companies:
                extra_lines.append("Companies: " + ", ".join(companies[:3]))
        else:
            creators = [creator.get("name", "") for creator in details.get("created_by", []) if creator.get("name")]
            if creators:
                extra_lines.append("Creators: " + ", ".join(creators[:3]))
            if self._settings is not None and self._settings.show_discovery_info and state.discovery_reason:
                extra_lines.append(f"Discovery: {state.discovery_reason}")

        return (
            {
                "title": state.display_name,
                "subtitle": subtitle,
                "rows": rows,
                "overview": overview,
                "extra": "\n".join(extra_lines),
                "artwork_mode": "still" if ep_still else "poster",
            },
            raw_image,
        )

    def refresh_current(self) -> None:
        if self._current_state is None:
            return
        self.set_selection(
            self._current_state,
            preview=self._current_preview,
            queue_reason=self._current_queue_reason,
            folder_plan=self._current_folder_plan,
        )

    def _apply_payload(self, payload: dict | None, image_data, token: str) -> None:
        self._loading_tokens.discard(token)
        if payload is None:
            return
        if isinstance(image_data, QPixmap):
            pixmap = image_data
        elif image_data is not None:
            pixmap = raw_to_pixmap(image_data)
        else:
            pixmap = None
        self._metadata_cache[token] = (payload, pixmap)
        self._metadata_cache.move_to_end(token)
        while len(self._metadata_cache) > self._MAX_METADATA_CACHE_ENTRIES:
            self._metadata_cache.popitem(last=False)
        if token != self._current_token:
            return
        self._stop_shimmer()
        self._title.setText(payload.get("title", "Selection"))
        self._subtitle.setText(payload.get("subtitle", ""))
        self._overview.setText(payload.get("overview", ""))
        self._extra.setText(payload.get("extra", ""))
        self._set_artwork_mode(payload.get("artwork_mode", "poster"))
        self._set_meta_rows(payload.get("rows", []))
        if pixmap is None or pixmap.isNull():
            self._poster_pixmap = None
            title = payload.get("title", "Selection")
            self._show_artwork_placeholder(title)
        else:
            self._poster_pixmap = pixmap
            self._poster.setText("")
            self._render_poster()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._render_poster()

    def _render_poster(self) -> None:
        if self._poster_pixmap is None or self._poster_pixmap.isNull():
            self._hero_frame.clear_backdrop()
            return
        target = self._poster.contentsRect().size()
        if not target.isValid():
            target = self._LANDSCAPE_ARTWORK_SIZE if self._artwork_mode == "still" else self._PORTRAIT_ARTWORK_SIZE
        scaled = self._poster_pixmap.scaled(
            target,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._poster.setPixmap(scaled)
        self._hero_frame.set_backdrop(self._poster_pixmap)

    def _set_artwork_mode(self, mode: str) -> None:
        normalized = "still" if mode == "still" else "poster"
        self._artwork_mode = normalized
        size = self._LANDSCAPE_ARTWORK_SIZE if normalized == "still" else self._PORTRAIT_ARTWORK_SIZE
        self._poster.setMinimumWidth(size.width())
        self._poster.setFixedHeight(size.height())

    def _artwork_placeholder_text(self) -> str:
        return "No Episode Image" if self._artwork_mode == "still" else "No Poster"

    def _show_artwork_placeholder(self, label: str = "", *, loading: bool = False) -> None:
        self._poster_pixmap = None
        self._hero_frame.clear_backdrop()
        subtitle = self._artwork_placeholder_text()
        title = "EPISODE" if self._artwork_mode == "still" else (label or "TMDB")
        if self._artwork_mode != "still" and label:
            title = label.split(" (", 1)[0]
        placeholder = build_placeholder_pixmap(
            self._poster.size() if self._poster.size().isValid() else (
                self._LANDSCAPE_ARTWORK_SIZE if self._artwork_mode == "still" else self._PORTRAIT_ARTWORK_SIZE
            ),
            title=title,
            subtitle=subtitle,
            accent="#4a9eda" if self._artwork_mode == "still" else "#e5a00d",
        )
        self._poster.setPixmap(placeholder)
        self._poster.setText("")
        if loading:
            if self._poster_shimmer is None:
                self._poster_shimmer = ShimmerOverlay(self._poster)
        else:
            self._stop_shimmer()

    def _stop_shimmer(self) -> None:
        if self._poster_shimmer is not None:
            self._poster_shimmer.stop()
            self._poster_shimmer = None

    def _set_meta_rows(self, rows: list[tuple[str, str]]) -> None:
        for row_index, (key_label, value_label) in enumerate(self._meta_rows):
            if row_index < len(rows):
                key, value = rows[row_index]
                key_label.setText(key)
                value_label.setText(value)
            else:
                key_label.setText("")
                value_label.setText("")