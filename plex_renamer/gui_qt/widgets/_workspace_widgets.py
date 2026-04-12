"""Reusable row widgets for the media workspace roster and preview panels."""
from __future__ import annotations

from PySide6.QtCore import QObject, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...engine import PreviewItem, ScanState
from ._formatting import clamped_percent
from ._image_utils import (
    ShimmerOverlay,
    build_placeholder_pixmap,
    scale_pixmap_for_device,
)
from ._media_helpers import (
    companion_summary as _companion_summary,
    confidence_band as _confidence_band,
    confidence_fill_color as _confidence_fill_color,
    file_count_for_state as _file_count_for_state,
    placeholder_initials as _placeholder_initials,
    preview_band as _preview_band,
    preview_band_name as _preview_band_name,
    preview_heading as _preview_heading,
    preview_status_label as _preview_status_label,
    preview_status_tone as _preview_status_tone,
    preview_target_text as _preview_target_text,
    repolish as _repolish,
    state_match_summary as _state_match_summary,
    state_status as _state_status,
    state_status_tone as _state_status_tone,
)


# ── Utility helpers ──────────────────────────────────────────────────

def _state_spans_multiple_seasons(state: ScanState) -> bool:
    if len(state.season_folders) > 1:
        return True
    preview_seasons = {
        preview.season
        for preview in state.preview_items
        if preview.season not in (None, 0)
    }
    return len(preview_seasons) > 1


class _CheckBinding:
    """Small checkbox binding used to reuse engine/controller helpers in Qt."""

    def __init__(self, value: bool) -> None:
        self._value = bool(value)

    def get(self) -> bool:
        return self._value

    def set(self, value: bool) -> None:
        self._value = bool(value)


# ── Bridge for async poster delivery ─────────────────────────────────

class RosterPosterBridge(QObject):
    poster_ready = Signal(object, object)


# ── Custom checkbox / label widgets ──────────────────────────────────

class MasterCheckBox(QCheckBox):
    """Tri-state display checkbox that toggles like a normal binary control.

    Uses QSS for indicator styling — see theme.qss _MasterCheckBox selectors.
    """

    _INDICATOR_SIZE = 18
    _RADIUS = 4
    _BG_OFF = QColor("#3a3a3a")
    _BG_ON = QColor("#3ea463")
    _BG_PARTIAL = QColor("#4a9eda")
    _BORDER_OFF = QColor("#555555")
    _BORDER_ON = QColor("#2d7a4a")
    _CHECK_COLOR = QColor("#ffffff")

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setProperty("cssClass", "master-check")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def nextCheckState(self) -> None:
        self.setCheckState(
            Qt.CheckState.Unchecked
            if self.checkState() == Qt.CheckState.Checked
            else Qt.CheckState.Checked
        )

    def sizeHint(self) -> QSize:
        text_width = self.fontMetrics().horizontalAdvance(self.text())
        return QSize(self._INDICATOR_SIZE + 12 + text_width, max(24, self._INDICATOR_SIZE + 6))

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        state = self.checkState()
        if state == Qt.CheckState.Checked:
            bg, border = self._BG_ON, self._BORDER_ON
        elif state == Qt.CheckState.PartiallyChecked:
            bg, border = self._BG_PARTIAL, self._BG_PARTIAL
        else:
            bg, border = self._BG_OFF, self._BORDER_OFF

        indicator_y = (self.height() - self._INDICATOR_SIZE) / 2
        rect_f = QRectF(1.5, indicator_y, self._INDICATOR_SIZE - 3.0, self._INDICATOR_SIZE - 3.0)
        painter.setBrush(bg)
        painter.setPen(QPen(border, 1.5))
        painter.drawRoundedRect(rect_f, self._RADIUS, self._RADIUS)

        pen = QPen(self._CHECK_COLOR, 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        size = self._INDICATOR_SIZE
        if state == Qt.CheckState.Checked:
            painter.drawLine(int(size * 0.25), int(indicator_y + size * 0.50), int(size * 0.43), int(indicator_y + size * 0.68))
            painter.drawLine(int(size * 0.43), int(indicator_y + size * 0.68), int(size * 0.75), int(indicator_y + size * 0.32))
        elif state == Qt.CheckState.PartiallyChecked:
            y = int(indicator_y + size / 2)
            painter.drawLine(int(size * 0.28), y, int(size * 0.72), y)

        text_rect = self.rect().adjusted(self._INDICATOR_SIZE + 8, 0, 0, 0)
        painter.setPen(QColor("#8d8d8d") if not self.isEnabled() else QColor("#e0e0e0"))
        painter.drawText(text_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), self.text())
        painter.end()


class ElidedLabel(QLabel):
    def __init__(
        self,
        text: str = "",
        *,
        elide_mode: Qt.TextElideMode = Qt.TextElideMode.ElideMiddle,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._full_text = text
        self._elide_mode = elide_mode
        self.setWordWrap(False)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._apply_elision()

    def setText(self, text: str) -> None:  # noqa: N802
        self._full_text = text
        self._apply_elision()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_elision()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._apply_elision()

    def _apply_elision(self) -> None:
        if not self._full_text:
            super().setText("")
            self.setToolTip("")
            return
        available_width = max(0, self.contentsRect().width())
        if available_width <= 0:
            display_text = self._full_text
        else:
            display_text = self.fontMetrics().elidedText(
                self._full_text,
                self._elide_mode,
                available_width,
            )
        super().setText(display_text)
        self.setToolTip(self._full_text if display_text != self._full_text else "")


# ── Base row / toggle widgets ────────────────────────────────────────

class ClickableRow(QFrame):
    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def mousePressEvent(self, event) -> None:
        self.clicked.emit()
        super().mousePressEvent(event)


class ToggleSwitch(QCheckBox):
    _SIZE = 20
    _RADIUS = 4
    _BG_OFF = QColor("#3a3a3a")
    _BG_ON = QColor("#3ea463")
    _BG_PARTIAL = QColor("#4a9eda")
    _BORDER_OFF = QColor("#555555")
    _BORDER_ON = QColor("#2d7a4a")
    _CHECK_COLOR = QColor("#ffffff")

    def __init__(self, checked: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText("")
        self.setChecked(checked)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(self._SIZE, self._SIZE)

    def sizeHint(self) -> QSize:
        return QSize(self._SIZE, self._SIZE)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        state = self.checkState()
        if state == Qt.CheckState.Checked:
            bg, border = self._BG_ON, self._BORDER_ON
        elif state == Qt.CheckState.PartiallyChecked:
            bg, border = self._BG_PARTIAL, self._BG_PARTIAL
        else:
            bg, border = self._BG_OFF, self._BORDER_OFF

        s = self._SIZE
        margin = 1.5
        rect_f = QRectF(margin, margin, s - 2 * margin, s - 2 * margin)
        p.setBrush(bg)
        p.setPen(QPen(border, 1.5))
        p.drawRoundedRect(rect_f, self._RADIUS, self._RADIUS)

        pen = QPen(self._CHECK_COLOR, 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        if state == Qt.CheckState.Checked:
            # Checkmark
            p.drawLine(int(s * 0.25), int(s * 0.50), int(s * 0.43), int(s * 0.68))
            p.drawLine(int(s * 0.43), int(s * 0.68), int(s * 0.75), int(s * 0.32))
        elif state == Qt.CheckState.PartiallyChecked:
            # Dash
            y = s // 2
            p.drawLine(int(s * 0.28), y, int(s * 0.72), y)

        p.end()


class MiniProgressBar(QWidget):
    def __init__(self, *, color: str, value: int = 0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor(color)
        self._value = max(0, min(100, value))
        self.setFixedHeight(4)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def setValue(self, value: int) -> None:
        self._value = max(0, min(100, value))
        self.update()

    def setColor(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(120, 4)

    def paintEvent(self, event) -> None:
        del event
        rect = self.rect()
        if not rect.isValid():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#2a2a2a"))
        painter.drawRoundedRect(rect, 2, 2)
        fill_width = int(rect.width() * (self._value / 100.0))
        if fill_width <= 0:
            return
        fill_rect = rect.adjusted(0, 0, fill_width - rect.width(), 0)
        painter.setBrush(self._color)
        painter.drawRoundedRect(fill_rect, 2, 2)


# ── Roster row widget ────────────────────────────────────────────────

class RosterRowWidget(ClickableRow):
    check_toggled = Signal(bool)
    season_assign_requested = Signal()
    geometry_changed = Signal()

    def __init__(
        self,
        state: ScanState,
        *,
        compact: bool,
        media_type: str,
        auto_accept_threshold: float,
        checkable: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("rosterRowCard")
        self.setProperty("cssClass", "roster-row-card")
        self._state = state
        self._compact = compact
        self._media_type = media_type
        self._auto_accept_threshold = auto_accept_threshold
        self._selected = False
        self._poster = QLabel()
        self._poster_size = QSize(34, 50) if compact else QSize(48, 70)
        self._poster.setFixedSize(self._poster_size)
        self._poster.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._shimmer: ShimmerOverlay | None = None
        if not compact:
            self._apply_placeholder_poster()
            self._shimmer = ShimmerOverlay(self._poster)
        self._poster.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self._check = ToggleSwitch(state.checked if checkable else False, self)
        self._check.setVisible(checkable)
        self._check.toggled.connect(self.check_toggled.emit)
        layout.addWidget(self._check, alignment=Qt.AlignmentFlag.AlignTop)

        if not compact:
            layout.addWidget(self._poster, alignment=Qt.AlignmentFlag.AlignTop)

        body = QVBoxLayout()
        body.setSpacing(4)
        layout.addLayout(body, stretch=1)

        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        self._title = QLabel(state.display_name)
        self._title.setProperty("cssClass", "row-title")
        self._title.setWordWrap(True)
        self._title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        title_row.addWidget(self._title, stretch=1)

        self._status = QLabel(_state_status(state)[0].upper())
        self._status.setProperty("cssClass", "status-pill")
        self._status.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._status.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        title_row.addWidget(
            self._status,
            alignment=Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
        )
        self._status.hide()
        body.addLayout(title_row)

        meta_parts = [f"{_file_count_for_state(state)} file(s)"]
        if state.season_assignment is not None and not _state_spans_multiple_seasons(state):
            meta_parts.append(f"Season {state.season_assignment}")
        if state.duplicate_of is not None:
            duplicate_target = state.duplicate_of_relative_folder or state.duplicate_of
            meta_parts.append(f"Same match as {duplicate_target}")
        elif state.show_id is not None:
            meta_parts.append(_state_match_summary(state, auto_accept_threshold))
        if state.needs_review and state.alternate_matches and not state.queued:
            n_alts = min(len(state.alternate_matches), 2)
            meta_parts.append(f"{n_alts} alternative{'s' if n_alts != 1 else ''}")
        self._meta = QLabel(" · ".join(meta_parts))
        self._meta.setProperty("cssClass", "caption")
        self._meta.setWordWrap(True)
        self._meta.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._meta.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        body.addWidget(self._meta)

        self._confidence = MiniProgressBar(
            color=_confidence_fill_color(self._state.confidence, state=self._state),
            value=clamped_percent(state.confidence),
        )
        body.addWidget(self._confidence)

        self._approve_btn = None

        self._season_btn = None

        self._alternates_layout = None
        self._alternates_widget = None
        self._confirm_row = None

        self._apply_style()

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._apply_style()

    def set_checked(self, checked: bool) -> None:
        blocked = self._check.blockSignals(True)
        self._check.setChecked(checked)
        self._check.blockSignals(blocked)

    def set_poster(self, pixmap: QPixmap) -> None:
        if self._compact or pixmap.isNull():
            if not self._compact:
                self._apply_placeholder_poster()
            return
        if self._shimmer is not None:
            self._shimmer.stop()
            self._shimmer = None
        self._poster.setText("")
        self._poster.setPixmap(
            scale_pixmap_for_device(
                pixmap,
                self._poster.size(),
                device_pixel_ratio=self._poster_device_pixel_ratio(),
            )
        )

    def _apply_placeholder_poster(self) -> None:
        title = _placeholder_initials(self._state.display_name)
        placeholder = build_placeholder_pixmap(
            self._poster_size,
            title=title,
            subtitle="",
            accent=_state_status(self._state)[1].name(),
            device_pixel_ratio=self._poster_device_pixel_ratio(),
        )
        self._poster.setPixmap(placeholder)
        self._poster.setText("")

    def poster_request_width(self) -> int:
        return max(220, min(420, int(round(self._poster_size.width() * self._poster_device_pixel_ratio() * 2.0))))

    def _poster_device_pixel_ratio(self) -> float:
        try:
            return max(1.0, float(self._poster.devicePixelRatioF()))
        except Exception:
            return 1.0

    def _apply_style(self) -> None:
        self.setProperty("band", _confidence_band(self._state.confidence, state=self._state))
        self.setProperty("selectionState", "selected" if self._selected else "normal")
        self._status.setProperty("tone", _state_status_tone(self._state))
        _repolish(self)
        _repolish(self._status)
        self._confidence.setColor(_confidence_fill_color(self._state.confidence, state=self._state))


# ── Preview row widget ───────────────────────────────────────────────

class PreviewRowWidget(ClickableRow):
    check_toggled = Signal(bool)

    def __init__(
        self,
        preview: PreviewItem,
        *,
        compact: bool,
        show_confidence: bool,
        show_companions: bool,
        checked: bool,
        checkable: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("previewRowCard")
        self.setProperty("cssClass", "preview-row-card")
        self._preview = preview
        self._selected = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self._check = ToggleSwitch(checked if preview.is_actionable and checkable else False, self)
        self._check.setVisible(preview.is_actionable and checkable)
        self._check.toggled.connect(self.check_toggled.emit)
        layout.addWidget(self._check, alignment=Qt.AlignmentFlag.AlignTop)

        body = QVBoxLayout()
        body.setSpacing(4)
        layout.addLayout(body, stretch=1)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        original = _preview_heading(preview, compact=compact)
        self._original = QLabel(original)
        self._original.setProperty("cssClass", "row-title")
        self._original.setWordWrap(True)
        self._original.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        top_row.addWidget(self._original, stretch=1)

        self._status = QLabel(_preview_status_label(preview))
        self._status.setProperty("cssClass", "status-pill")
        self._status.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        top_row.addWidget(self._status, alignment=Qt.AlignmentFlag.AlignTop)
        body.addLayout(top_row)

        self._target = QLabel(_preview_target_text(preview))
        self._target.setProperty("cssClass", "row-target")
        self._target.setWordWrap(True)
        self._target.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        body.addWidget(self._target)

        if show_companions and preview.companions:
            self._companions = QLabel(_companion_summary(preview))
            self._companions.setProperty("cssClass", "caption")
            self._companions.setWordWrap(True)
            self._companions.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            body.addWidget(self._companions)
        else:
            self._companions = None

        self._confidence = None
        if show_confidence:
            self._confidence = MiniProgressBar(
                color=_preview_band(self._preview),
                value=clamped_percent(preview.episode_confidence),
            )
            body.addWidget(self._confidence)

        self._apply_style()

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._apply_style()

    def set_checked(self, checked: bool) -> None:
        if not self._check.isVisible():
            return
        blocked = self._check.blockSignals(True)
        self._check.setChecked(checked)
        self._check.blockSignals(blocked)

    def _apply_style(self) -> None:
        self.setProperty("band", _preview_band_name(self._preview))
        self.setProperty("selectionState", "selected" if self._selected else "normal")
        self._status.setProperty("tone", _preview_status_tone(self._preview))
        _repolish(self)
        _repolish(self._status)
        if self._confidence is not None:
            self._confidence.setColor(_preview_band(self._preview))


# ── Folder preview row widget ────────────────────────────────────────

class FolderPreviewRowWidget(QFrame):
    def __init__(self, source_name: str, target_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setProperty("cssClass", "preview-row-card")
        self.setProperty("band", "muted")
        self.setProperty("selectionState", "normal")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 5, 6, 5)
        layout.setSpacing(6)

        self._original = ElidedLabel(
            source_name,
            elide_mode=Qt.TextElideMode.ElideRight,
            parent=self,
        )
        self._original.setProperty("cssClass", "row-title")
        self._original.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self._original, stretch=1)

        self._arrow = QLabel("->")
        self._arrow.setProperty("cssClass", "caption")
        self._arrow.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._arrow.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        layout.addWidget(self._arrow, alignment=Qt.AlignmentFlag.AlignVCenter)

        self._target = QLabel(target_name)
        self._target.setProperty("cssClass", "row-target")
        self._target.setWordWrap(False)
        self._target.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._target.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._target.setToolTip(target_name)
        layout.addWidget(self._target)

        _repolish(self)
