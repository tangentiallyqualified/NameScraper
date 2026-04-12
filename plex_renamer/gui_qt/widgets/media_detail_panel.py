"""Detail panel for TV and movie media selections in the Qt shell."""

from __future__ import annotations

from ...thread_pool import submit as _submit_bg
from collections import OrderedDict
from collections.abc import Callable

from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QFormLayout, QFrame, QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from ...engine import PreviewItem, ScanState
from ._image_utils import (
    ShimmerOverlay,
    build_placeholder_pixmap,
    raw_to_pixmap,
    scale_pixmap_for_device,
)
from ._media_detail_payloads import (
    build_detail_fallback_rows,
    build_detail_payload,
)


class _DetailBridge(QObject):
    metadata_ready = Signal(object, object, str)


class _WrappingDetailLabel(QLabel):
    """Wrapped label that can shrink horizontally inside narrow panels."""

    def hasHeightForWidth(self) -> bool:
        return self.wordWrap() or super().hasHeightForWidth()

    def sizeHint(self):
        hint = super().sizeHint()
        if self.wordWrap():
            hint.setWidth(0)
        return hint

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        if self.wordWrap():
            hint.setWidth(0)
        return hint


class _FactsValueLabel(_WrappingDetailLabel):
    """Wrapped facts-card label with extra descent room for HiDPI text."""

    _DESCENT_PADDING = 6

    def heightForWidth(self, width: int) -> int:
        base = super().heightForWidth(width)
        if base < 0:
            base = self.sizeHint().height()
        return base + self._DESCENT_PADDING

    def sizeHint(self):
        hint = super().sizeHint()
        if self.wordWrap():
            hint.setHeight(hint.height() + self._DESCENT_PADDING)
        return hint

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        if self.wordWrap():
            hint.setHeight(hint.height() + self._DESCENT_PADDING)
        return hint


def _selection_artwork_mode(preview: PreviewItem | None) -> str:
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
    _PORTRAIT_ARTWORK_SIZE = QSize(148, 222)
    _LANDSCAPE_ARTWORK_SIZE = QSize(220, 124)

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

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._body = QFrame()
        self._body.setProperty("cssClass", "media-detail-content-surface")
        body_layout = QVBoxLayout(self._body)
        body_layout.setContentsMargins(14, 12, 14, 14)
        body_layout.setSpacing(12)
        self._scroll.setWidget(self._body)
        layout.addWidget(self._scroll, stretch=1)

        self._title = _WrappingDetailLabel("Selection")
        self._title.setProperty("cssClass", "heading")
        self._title.setWordWrap(True)
        self._title.setMargin(2)
        self._title.setMinimumWidth(0)
        self._title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        body_layout.addWidget(self._title)

        self._subtitle = _WrappingDetailLabel("")
        self._subtitle.setProperty("cssClass", "text-dim")
        self._subtitle.setWordWrap(True)
        self._subtitle.setMargin(2)
        self._subtitle.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._subtitle.setMinimumWidth(0)
        self._subtitle.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        body_layout.addWidget(self._subtitle)

        summary_row = QHBoxLayout()
        summary_row.setContentsMargins(0, 0, 0, 0)
        summary_row.setSpacing(12)
        body_layout.addLayout(summary_row)

        self._poster = QLabel("No Poster")
        self._poster.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._poster.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._poster.setProperty("cssClass", "job-poster-card")
        self._poster_shimmer: ShimmerOverlay | None = None
        self._set_artwork_mode("poster")
        summary_row.addWidget(self._poster, alignment=Qt.AlignmentFlag.AlignTop)

        self._summary_body = QVBoxLayout()
        self._summary_body.setContentsMargins(0, 0, 0, 0)
        self._summary_body.setSpacing(8)
        summary_row.addLayout(self._summary_body, stretch=1)

        self._facts_card = QFrame()
        self._facts_card.setProperty("cssClass", "job-detail-facts-card")
        self._facts_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self._facts_card.setMaximumWidth(280)
        self._meta_grid = QWidget()
        meta_layout = QFormLayout(self._meta_grid)
        meta_layout.setContentsMargins(0, 0, 0, 0)
        meta_layout.setHorizontalSpacing(6)
        meta_layout.setVerticalSpacing(6)
        meta_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        meta_layout.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        meta_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._meta_rows: list[tuple[QLabel, QLabel]] = []
        for row in range(6):
            key_label = QLabel("")
            key_label.setProperty("cssClass", "caption")
            key_label.setMargin(1)
            key_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            value_label = _FactsValueLabel("")
            value_label.setProperty("cssClass", "job-detail-fact-value")
            value_label.setWordWrap(True)
            value_label.setMargin(2)
            value_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            value_label.setMinimumWidth(0)
            value_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            meta_layout.addRow(key_label, value_label)
            self._meta_rows.append((key_label, value_label))
        facts_layout = QVBoxLayout(self._facts_card)
        facts_layout.setContentsMargins(12, 12, 12, 12)
        facts_layout.setSpacing(0)
        facts_layout.addWidget(self._meta_grid)
        self._summary_body.addWidget(self._facts_card)
        self._summary_body.addStretch(1)
        self._sync_facts_card_height()

        self._overview = _WrappingDetailLabel("")
        self._overview.setWordWrap(True)
        self._overview.setMargin(2)
        self._overview.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._overview.setMinimumWidth(0)
        self._overview.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        body_layout.addWidget(self._overview)

        self._extra = _WrappingDetailLabel("")
        self._extra.setProperty("cssClass", "caption")
        self._extra.setWordWrap(True)
        self._extra.setMargin(2)
        self._extra.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._extra.setMinimumWidth(0)
        self._extra.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
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
        target_width = self._artwork_fetch_width(_selection_artwork_mode(preview))

        def _worker() -> None:
            payload = self._build_payload(tmdb, state, preview, queue_reason, folder_plan, target_width)
            try:
                self._bridge.metadata_ready.emit(payload[0], payload[1], token)
            except RuntimeError:
                pass

        _submit_bg(_worker)

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
        return build_detail_fallback_rows(
            state,
            preview,
            queue_reason,
        )

    def _build_payload(
        self,
        tmdb,
        state: ScanState,
        preview: PreviewItem | None,
        queue_reason: str,
        folder_plan: str,
        target_width: int,
    ):
        return build_detail_payload(
            tmdb,
            state,
            preview,
            queue_reason,
            target_width,
            show_discovery_info=bool(
                self._settings is not None and self._settings.show_discovery_info
            ),
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
        self._sync_facts_card_height()
        self._render_poster()

    def _render_poster(self) -> None:
        if self._poster_pixmap is None or self._poster_pixmap.isNull():
            return
        target = self._poster.contentsRect().size()
        if not target.isValid():
            target = self._LANDSCAPE_ARTWORK_SIZE if self._artwork_mode == "still" else self._PORTRAIT_ARTWORK_SIZE
        scaled = scale_pixmap_for_device(
            self._poster_pixmap,
            target,
            device_pixel_ratio=self._artwork_device_pixel_ratio(),
        )
        self._poster.setPixmap(scaled)

    def _set_artwork_mode(self, mode: str) -> None:
        normalized = "still" if mode == "still" else "poster"
        self._artwork_mode = normalized
        size = self._LANDSCAPE_ARTWORK_SIZE if normalized == "still" else self._PORTRAIT_ARTWORK_SIZE
        self._poster.setFixedSize(size)
        self._sync_facts_card_height()

    def _artwork_placeholder_text(self) -> str:
        return "No Episode Image" if self._artwork_mode == "still" else "No Poster"

    def _show_artwork_placeholder(self, label: str = "", *, loading: bool = False) -> None:
        self._poster_pixmap = None
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
            device_pixel_ratio=self._artwork_device_pixel_ratio(),
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

    def _artwork_device_pixel_ratio(self) -> float:
        try:
            return max(1.0, float(self._poster.devicePixelRatioF()))
        except Exception:
            return 1.0

    def _artwork_fetch_width(self, mode: str) -> int:
        logical = self._LANDSCAPE_ARTWORK_SIZE if mode == "still" else self._PORTRAIT_ARTWORK_SIZE
        ratio = self._artwork_device_pixel_ratio()
        return max(500, min(1100, int(round(logical.width() * ratio * 1.6))))

    def _sync_facts_card_height(self) -> None:
        if not hasattr(self, "_facts_card"):
            return
        self._facts_card.setFixedHeight(self._poster.height())

    def _set_meta_rows(self, rows: list[tuple[str, str]]) -> None:
        for row_index, (key_label, value_label) in enumerate(self._meta_rows):
            if row_index < len(rows):
                key, value = rows[row_index]
                key_label.setText(key)
                value_label.setText(value)
            else:
                key_label.setText("")
                value_label.setText("")