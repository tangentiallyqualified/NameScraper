# plex_renamer/gui_qt/widgets/_roster_delegate.py
"""Painted roster rows: RosterDelegate + RosterListView (GUI V4 §7)."""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QHelpEvent, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QListView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolTip,
    QWidget,
)

from .. import _scale, theme
from ._image_utils import build_placeholder_pixmap, scale_pixmap_for_device
from ._roster_model import GROUP_ROLE, KIND_ROLE, POSTER_ROLE, ROW_DATA_ROLE, RosterRowData
from ._workspace_widget_primitives import paint_check_indicator, paint_mini_progress
from .status_chip import (
    chip_font_metrics,
    chip_rects_wrapped,
    chip_wrapped_height,
    paint_chip_row_wrapped,
)

_MARGIN_U = 8
_TOGGLE_U = 20
_POSTER_W_U, _POSTER_H_U = 64, 94
_ROW_NORMAL_U, _ROW_HEADER_U = 110, 34
_BAR_W_U = 110
_HEADER_PAD_LEFT_U = 12
_CHIP_TOP_GAP_U = 6
_CONF_BLOCK_U = 18  # confidence bar (4u) + pct baseline padding
_CARD_GAP_U = 2  # vertical gap separating consecutive roster cards (R2 L2)
_CARD_HMARGIN_U = 6  # left/right inset so cards clear the panel edges (R2 L1)
_ROW_COMPACT_U = 64  # compact base height: no poster to accommodate (R2 L3)


class RosterDelegate(QStyledItemDelegate):
    def __init__(self, view: QListView, *, media_type: str, parent=None) -> None:
        super().__init__(parent if parent is not None else view)
        self._view = view
        self._media_type = media_type
        self._compact = False

    def set_compact(self, compact: bool) -> None:
        self._compact = compact

    # -- Geometry helpers --------------------------------------------------

    def _card_rect(self, option_rect: QRect) -> QRect:
        """The painted card rect, inset from the full row rect by the
        inter-card gap (R2 L2) and the left/right edge margin (R2 L1) so
        consecutive cards no longer touch each other or the panel edges.
        This is the ONLY place that insets from the raw row rect; every
        other geometry helper below takes this already-inset rect."""
        gap = _scale.px(_CARD_GAP_U)
        hmargin = _scale.px(_CARD_HMARGIN_U)
        return option_rect.adjusted(hmargin, gap, -hmargin, -gap)

    def toggle_rect(self, option_rect: QRect, row_data: RosterRowData) -> QRect:
        del row_data
        card_rect = self._card_rect(option_rect)
        margin = _scale.px(_MARGIN_U)
        size = _scale.px(_TOGGLE_U)
        x = card_rect.x() + margin
        y = card_rect.y() + margin
        return QRect(x, y, size, size)

    def _poster_rect(self, card_rect: QRect) -> QRect:
        margin = _scale.px(_MARGIN_U)
        toggle_size = _scale.px(_TOGGLE_U)
        poster_w = _scale.px(_POSTER_W_U)
        poster_h = _scale.px(_POSTER_H_U)
        x = card_rect.x() + margin + toggle_size + margin
        if self._media_type == "movie":
            y = card_rect.y() + (card_rect.height() - poster_h) // 2
        else:
            y = card_rect.y() + margin
        return QRect(x, y, poster_w, poster_h)

    def _body_rect(self, card_rect: QRect) -> QRect:
        margin = _scale.px(_MARGIN_U)
        if self._compact:
            body_x = card_rect.x() + margin + _scale.px(_TOGGLE_U) + margin
        else:
            poster_rect = self._poster_rect(card_rect)
            body_x = poster_rect.right() + margin + 1
        body_right = card_rect.right() - margin
        return QRect(
            body_x,
            card_rect.y() + margin,
            max(0, body_right - body_x),
            card_rect.height() - 2 * margin,
        )

    # -- Painting ------------------------------------------------------------

    def _body_width(self) -> int:
        margin = _scale.px(_MARGIN_U)
        view_w = self._view.viewport().width() if self._view is not None else _scale.px(360)
        toggle = _scale.px(_TOGGLE_U)
        poster = 0 if self._compact else _scale.px(_POSTER_W_U) + margin + 1
        body_x = margin + toggle + margin + poster
        return max(_scale.px(80), view_w - body_x - margin - 2 * _scale.px(_CARD_HMARGIN_U))

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        del option
        kind = index.data(KIND_ROLE)
        if kind == "header":
            return QSize(0, _scale.px(_ROW_HEADER_U))
        gap2 = 2 * _scale.px(_CARD_GAP_U)
        row_data = index.data(ROW_DATA_ROLE)
        metrics = QFontMetrics(self._view.font()) if self._view is not None else None
        line_height = metrics.lineSpacing() if metrics is not None else _scale.px(16)
        chip_h = 0
        if row_data is not None and row_data.chips:
            chip_h = _scale.px(_CHIP_TOP_GAP_U) + chip_wrapped_height(
                row_data.chips, chip_font_metrics(), self._body_width()
            )
        content = (
            gap2 + 2 * _scale.px(_MARGIN_U) + 2 * line_height + _scale.px(_CONF_BLOCK_U) + chip_h
        )
        if self._compact:
            return QSize(0, max(_scale.px(_ROW_COMPACT_U) + gap2, content))
        return QSize(0, max(_scale.px(_ROW_NORMAL_U) + gap2, content))

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        kind = index.data(KIND_ROLE)
        if kind == "header":
            self._paint_header(painter, option, index)
            return
        row_data = index.data(ROW_DATA_ROLE)
        if row_data is None:
            return
        poster = index.data(POSTER_ROLE)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        card = self._card_rect(option.rect)
        self._paint_background(painter, option, card, row_data)
        if row_data.checkable:
            state = Qt.CheckState.Checked if row_data.checked else Qt.CheckState.Unchecked
            toggle_rect = self.toggle_rect(option.rect, row_data)
            paint_check_indicator(painter, toggle_rect.adjusted(1, 1, -1, -1), state)
        if not self._compact:
            self._paint_poster(painter, poster, row_data, card)
        self._paint_body(painter, row_data, card)
        painter.restore()

    def _paint_background(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        card_rect: QRect,
        row_data: RosterRowData,
    ) -> None:
        del row_data  # band tint removed (R2 L6); band stays in the model for other consumers
        radius = theme.radius("md")
        painter.setPen(QPen(theme.qcolor("border_light"), 1))
        painter.setBrush(theme.qcolor("card"))
        painter.drawRoundedRect(card_rect, radius, radius)

        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected:
            painter.setBrush(theme.qcolor("selection_bg"))
            painter.drawRoundedRect(card_rect, radius, radius)
            pen = QPen(theme.qcolor("accent"), 1)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            adjusted = card_rect.adjusted(0, 0, -1, -1)
            painter.drawRoundedRect(adjusted, radius, radius)
        elif hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme.qcolor("card_hover"))
            painter.drawRoundedRect(card_rect, radius, radius)

    def _paint_header(
        self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex
    ) -> None:
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.qcolor("section_header_bg"))
        painter.drawRect(option.rect)
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(theme.qcolor("accent"))
        text_rect = option.rect.adjusted(_scale.px(_HEADER_PAD_LEFT_U), 0, 0, 0)
        painter.drawText(
            text_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), text.upper()
        )
        painter.restore()

    def _paint_poster(
        self, painter: QPainter, poster, row_data: RosterRowData, card_rect: QRect
    ) -> None:
        rect = self._poster_rect(card_rect)
        device_pixel_ratio = self._view.devicePixelRatioF() if self._view is not None else 1.0
        if poster is not None and not poster.isNull():
            scaled = scale_pixmap_for_device(
                poster, rect.size(), device_pixel_ratio=device_pixel_ratio
            )
        else:
            scaled = build_placeholder_pixmap(
                rect.size(),
                title=row_data.placeholder_initials,
                subtitle="",
                accent=row_data.placeholder_accent,
                device_pixel_ratio=device_pixel_ratio,
            )
        painter.drawPixmap(rect, scaled)

    def _paint_body(self, painter: QPainter, row_data: RosterRowData, card_rect: QRect) -> None:
        body_rect = self._body_rect(card_rect)
        metrics = painter.fontMetrics()
        line_height = metrics.lineSpacing()

        first_line_rect = QRect(body_rect.x(), body_rect.y(), body_rect.width(), line_height)
        second_line_rect = QRect(
            body_rect.x(), body_rect.y() + line_height, body_rect.width(), line_height
        )

        painter.setPen(theme.qcolor("text"))
        title = row_data.title
        first_line, remainder = self._split_title(title, metrics, first_line_rect.width())
        first_line = metrics.elidedText(
            first_line, Qt.TextElideMode.ElideRight, first_line_rect.width()
        )
        painter.drawText(
            first_line_rect,
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            first_line,
        )
        if remainder:
            elided = metrics.elidedText(
                remainder, Qt.TextElideMode.ElideMiddle, second_line_rect.width()
            )
            painter.drawText(
                second_line_rect,
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                elided,
            )

        confidence_y = body_rect.y() + 2 * line_height + _scale.px(4)
        bar_rect = QRect(body_rect.x(), confidence_y, _scale.px(_BAR_W_U), _scale.px(4))
        painter.save()
        paint_mini_progress(
            painter,
            bar_rect,
            value=row_data.confidence_pct,
            color=QColor(row_data.confidence_color),
        )
        painter.restore()
        pct_text = f"{row_data.confidence_pct}%"
        pct_rect = QRect(
            bar_rect.right() + _scale.px(8),
            bar_rect.y() - _scale.px(6),
            _scale.px(48),
            _scale.px(16),
        )
        painter.setPen(theme.qcolor("text_dim"))
        painter.drawText(
            pct_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), pct_text
        )

        if row_data.chips:
            chip_y = confidence_y + _scale.px(_CONF_BLOCK_U) + _scale.px(_CHIP_TOP_GAP_U)
            painter.setPen(theme.qcolor("text"))
            paint_chip_row_wrapped(
                painter, body_rect.x(), chip_y, row_data.chips, body_rect.width()
            )

    def _split_title(self, title: str, metrics: QFontMetrics, width: int) -> tuple[str, str]:
        if width <= 0:
            return "", title
        if metrics.horizontalAdvance(title) <= width:
            return title, ""
        for cut in range(len(title), 0, -1):
            candidate = title[:cut]
            if metrics.horizontalAdvance(candidate) <= width:
                remainder = title[cut:].lstrip()
                return candidate, remainder
        return "", title

    # -- Tooltips --------------------------------------------------------

    def helpEvent(
        self,
        event: QHelpEvent,
        view,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> bool:
        if event.type() != QHelpEvent.Type.ToolTip:
            return super().helpEvent(event, view, option, index)
        if index.data(KIND_ROLE) != "state":
            return super().helpEvent(event, view, option, index)
        row_data = index.data(ROW_DATA_ROLE)
        if row_data is None or not row_data.chips:
            return super().helpEvent(event, view, option, index)

        body_rect = self._body_rect(self._card_rect(option.rect))
        painter_metrics = QFontMetrics(self._view.font()) if self._view is not None else None
        line_height = (
            painter_metrics.lineSpacing() if painter_metrics is not None else _scale.px(16)
        )
        confidence_y = body_rect.y() + 2 * line_height + _scale.px(4)
        chip_y = confidence_y + _scale.px(_CONF_BLOCK_U) + _scale.px(_CHIP_TOP_GAP_U)
        rects = chip_rects_wrapped(
            body_rect.x(), chip_y, row_data.chips, chip_font_metrics(), body_rect.width()
        )
        point = event.pos()
        for chip, rect in zip(row_data.chips, rects, strict=False):
            if rect.contains(point):
                if chip.tooltip:
                    QToolTip.showText(event.globalPos(), chip.tooltip, view)
                    return True
                break
        return super().helpEvent(event, view, option, index)


class RosterListView(QListView):
    toggle_clicked = Signal(QModelIndex)  # pressed inside a state row's toggle rect
    header_clicked = Signal(str)  # group key

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.setUniformItemSizes(False)
        self.setProperty("cssClass", "row-host-list")
        self._intercepted_row: int = -1

    def mousePressEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        index = self.indexAt(pos)
        if index.isValid():
            kind = index.data(KIND_ROLE)
            delegate = self.itemDelegateForIndex(index)
            if kind == "state" and isinstance(delegate, RosterDelegate):
                row_data = index.data(ROW_DATA_ROLE)
                if row_data is not None:
                    rect = self.visualRect(index)
                    toggle_rect = delegate.toggle_rect(rect, row_data)
                    if toggle_rect.contains(pos):
                        self._intercepted_row = index.row()
                        self.toggle_clicked.emit(index)
                        return
            elif kind == "header":
                group = index.data(GROUP_ROLE)
                if group:
                    self.header_clicked.emit(group)
                return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        index = self.indexAt(pos)
        if self._intercepted_row != -1 and index.isValid() and index.row() == self._intercepted_row:
            self._intercepted_row = -1
            return
        self._intercepted_row = -1
        super().mouseReleaseEvent(event)
