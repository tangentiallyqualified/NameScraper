"""Detail panel for TV and movie media selections in the Qt shell."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable

from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...engine import PreviewItem, ScanState
from ._media_detail_artwork import (
    detail_artwork_fetch_width,
    render_detail_artwork,
    set_detail_artwork_mode,
    show_detail_artwork_placeholder,
    stop_detail_shimmer,
)
from ._image_utils import (
    ShimmerOverlay,
)
from ._media_detail_payloads import (
    build_detail_fallback_rows,
    build_detail_payload,
)
from ._media_detail_workflow import MediaDetailWorkflowCoordinator


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
        self._workflow = MediaDetailWorkflowCoordinator(self)
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
        body_layout.setSpacing(8)
        self._scroll.setWidget(self._body)
        layout.addWidget(self._scroll, stretch=1)

        self._queue_preflight = _WrappingDetailLabel("")
        self._queue_preflight.setProperty("cssClass", "caption")
        self._queue_preflight.setWordWrap(True)
        self._queue_preflight.setMargin(0)
        self._queue_preflight.hide()

        self._title = _WrappingDetailLabel("Selection")
        self._title.setProperty("cssClass", "heading")
        self._title.setWordWrap(True)
        self._title.setMargin(2)
        self._title.setMinimumWidth(0)
        self._title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        body_layout.addWidget(self._title)
        body_layout.addWidget(self._queue_preflight)

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

        poster_column = QVBoxLayout()
        poster_column.setContentsMargins(0, 0, 0, 0)
        poster_column.setSpacing(8)
        summary_row.addLayout(poster_column)

        self._poster = QLabel("No Poster")
        self._poster.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._poster.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._poster.setProperty("cssClass", "job-poster-card")
        self._poster_shimmer: ShimmerOverlay | None = None
        self._set_artwork_mode("poster")
        poster_column.addWidget(self._poster, alignment=Qt.AlignmentFlag.AlignTop)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        self._fix_match_button = QPushButton("Fix Match")
        self._fix_match_button.setProperty("cssClass", "secondary")
        self._fix_match_button.setEnabled(False)
        actions.addWidget(self._fix_match_button)

        self._primary_action_button = QPushButton("")
        self._primary_action_button.setEnabled(False)
        actions.addWidget(self._primary_action_button)
        poster_column.addLayout(actions)
        poster_column.addStretch(1)

        self._summary_body = QVBoxLayout()
        self._summary_body.setContentsMargins(0, 0, 0, 0)
        self._summary_body.setSpacing(8)
        summary_row.addLayout(self._summary_body, stretch=1)

        self._facts_card = QFrame()
        self._facts_card.setProperty("cssClass", "job-detail-facts-card")
        self._facts_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self._facts_card.setMaximumWidth(280)
        self._meta_grid = QWidget()
        meta_layout = QGridLayout(self._meta_grid)
        meta_layout.setContentsMargins(0, 0, 0, 0)
        meta_layout.setHorizontalSpacing(6)
        meta_layout.setVerticalSpacing(6)
        meta_layout.setColumnStretch(0, 0)
        meta_layout.setColumnStretch(1, 1)
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
            meta_layout.addWidget(key_label, row, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            meta_layout.addWidget(value_label, row, 1)
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
        self._subtitle.show()
        self._queue_preflight.clear()
        self._queue_preflight.hide()
        for key_label, value_label in self._meta_rows:
            key_label.setText("")
            value_label.setText("")
            key_label.hide()
            value_label.hide()
        self._overview.setText("")
        self._extra.setText("")

    def clear_metadata_cache(self) -> None:
        self._workflow.clear_metadata_cache()

    @property
    def fix_match_button(self) -> QPushButton:
        return self._fix_match_button

    @property
    def primary_action_button(self) -> QPushButton:
        return self._primary_action_button

    @property
    def queue_preflight_label(self) -> QLabel:
        return self._queue_preflight

    def set_selection(
        self,
        state: ScanState | None,
        preview: PreviewItem | None = None,
        queue_reason: str = "",
        folder_plan: str = "",
    ) -> None:
        self._workflow.set_selection(
            state,
            preview=preview,
            queue_reason=queue_reason,
            folder_plan=folder_plan,
        )

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
        self._workflow.refresh_current()

    def _apply_payload(self, payload: dict | None, image_data, token: str) -> None:
        self._workflow.apply_payload(payload, image_data, token)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_facts_card_height()
        self._render_poster()

    def _render_poster(self) -> None:
        render_detail_artwork(
            self._poster,
            self._poster_pixmap,
            self._artwork_mode,
            portrait_size=self._PORTRAIT_ARTWORK_SIZE,
            landscape_size=self._LANDSCAPE_ARTWORK_SIZE,
        )

    def _set_artwork_mode(self, mode: str) -> None:
        facts_card = self._facts_card if hasattr(self, "_facts_card") else None
        self._artwork_mode = set_detail_artwork_mode(
            self._poster,
            facts_card,
            mode,
            portrait_size=self._PORTRAIT_ARTWORK_SIZE,
            landscape_size=self._LANDSCAPE_ARTWORK_SIZE,
        )

    def _show_artwork_placeholder(self, label: str = "", *, loading: bool = False) -> None:
        self._poster_pixmap = None
        self._poster_shimmer = show_detail_artwork_placeholder(
            self._poster,
            self._poster_shimmer,
            self._artwork_mode,
            label=label,
            loading=loading,
            portrait_size=self._PORTRAIT_ARTWORK_SIZE,
            landscape_size=self._LANDSCAPE_ARTWORK_SIZE,
        )

    def _stop_shimmer(self) -> None:
        stop_detail_shimmer(self._poster_shimmer)
        self._poster_shimmer = None

    def _artwork_fetch_width(self, mode: str) -> int:
        return detail_artwork_fetch_width(
            self._poster,
            mode,
            portrait_size=self._PORTRAIT_ARTWORK_SIZE,
            landscape_size=self._LANDSCAPE_ARTWORK_SIZE,
        )

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
                key_label.setVisible(True)
                value_label.setVisible(True)
            else:
                key_label.setText("")
                value_label.setText("")
                key_label.hide()
                value_label.hide()
