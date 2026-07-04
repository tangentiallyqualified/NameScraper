# plex_renamer/gui_qt/widgets/_episode_table_delegate.py
"""Painted episode-table rows: EpisodeTableDelegate + EpisodeTableView (GUI V4 Plan 3)."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QModelIndex, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QListView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

from .. import _scale, theme
from ._episode_table_model import (
    EXPANDED_ROLE,
    ROW_DATA_ROLE,
    ROW_KIND_ROLE,
    SECTION_KEY_ROLE,
    EpisodeRowData,
)
from ._workspace_widget_primitives import paint_check_indicator, paint_mini_progress

_ROW_HEADER_U, _ROW_SINGLE_U, _ROW_DOUBLE_U, _ROW_MOVIE_U = 30, 34, 52, 52
_CHEVRON_U, _TOGGLE_U, _PILL_H_U, _BAR_W_U, _MARGIN_U = 16, 20, 18, 70, 8
_PILL_HPAD_U = 8
_FALLBACK_EXPANDED_HEIGHT_U = 220

_TONE_COLOR = {"success": "success", "warning": "warning", "error": "error", "muted": "text_dim"}

_HEADER_KINDS = {"section-header", "section-label"}
_CHEVRON_KINDS = {"episode", "movie-file"}
_DOUBLE_LINE_KINDS = {"episode", "unmapped", "duplicate", "orphan", "folder"}

_FLASH_DURATION_MS = 700


class EpisodeTableDelegate(QStyledItemDelegate):
    expansion_requested = Signal(QModelIndex)     # chevron click or Enter (view forwards)

    def __init__(self, view: QListView, *, media_type: str, parent=None) -> None:
        super().__init__(parent if parent is not None else view)
        self._view = view
        self._media_type = media_type
        self.expansion_card_provider: Callable[[QModelIndex], QWidget] | None = None
        self._flash_row_index: int = -1
        self._flash_timer: QTimer | None = None
        self._watched_model = None
        self._connect_to_view_model()

    def _connect_to_view_model(self) -> None:
        """Re-emit sizeHintChanged for rows whose EXPANDED_ROLE flipped, so the
        view re-measures row height without waiting for a full relayout."""
        if self._view is None:
            return
        model = self._view.model()
        if model is self._watched_model:
            return
        if self._watched_model is not None:
            try:
                self._watched_model.dataChanged.disconnect(self._on_model_data_changed)
            except (RuntimeError, TypeError):
                pass
        self._watched_model = model
        if model is not None:
            model.dataChanged.connect(self._on_model_data_changed)

    def _on_model_data_changed(self, top_left: QModelIndex, bottom_right: QModelIndex, roles: list[int] | None = None) -> None:
        if roles and EXPANDED_ROLE not in roles:
            return
        for row in range(top_left.row(), bottom_right.row() + 1):
            self.sizeHintChanged.emit(top_left.sibling(row, 0))

    # -- Geometry helpers --------------------------------------------------

    def chevron_rect(self, option_rect: QRect) -> QRect:
        margin = _scale.px(_MARGIN_U)
        size = _scale.px(_CHEVRON_U)
        x = option_rect.x() + margin
        y = option_rect.y() + (option_rect.height() - size) // 2
        return QRect(x, y, size, size)

    def toggle_rect(self, option_rect: QRect) -> QRect:
        margin = _scale.px(_MARGIN_U)
        size = _scale.px(_TOGGLE_U)
        x = option_rect.x() + margin
        y = option_rect.y() + (option_rect.height() - size) // 2
        return QRect(x, y, size, size)

    def _title_x(self, option_rect: QRect, row_data: EpisodeRowData) -> int:
        margin = _scale.px(_MARGIN_U)
        x = option_rect.x() + margin
        if row_data.kind in _CHEVRON_KINDS:
            x += _scale.px(_CHEVRON_U) + margin
        if row_data.kind == "movie-file" and row_data.checkable:
            x += _scale.px(_TOGGLE_U) + margin
        return x

    def _pill_rect(self, option_rect: QRect, row_data: EpisodeRowData, metrics) -> QRect:
        text = row_data.status_text.upper()
        pad = _scale.px(_PILL_HPAD_U)
        height = _scale.px(_PILL_H_U)
        margin = _scale.px(_MARGIN_U)
        width = metrics.horizontalAdvance(text) + 2 * pad
        x = option_rect.right() - margin - width
        y = option_rect.y() + (option_rect.height() - height) // 2
        return QRect(x, y, width, height)

    # -- Sizing --------------------------------------------------------------

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:  # noqa: N802
        del option
        self._connect_to_view_model()
        if index.data(EXPANDED_ROLE):
            editor = None
            if self.expansion_card_provider is not None:
                editor = self._view.indexWidget(index) if self._view is not None else None
            if editor is not None:
                return QSize(0, editor.sizeHint().height())
            return QSize(0, _scale.px(_FALLBACK_EXPANDED_HEIGHT_U))
        kind = index.data(ROW_KIND_ROLE)
        if kind in _HEADER_KINDS:
            return QSize(0, _scale.px(_ROW_HEADER_U))
        if kind == "bulk-hint":
            return QSize(0, _scale.px(_ROW_SINGLE_U))
        if kind == "movie-file":
            return QSize(0, _scale.px(_ROW_MOVIE_U))
        row_data = index.data(ROW_DATA_ROLE)
        if kind in _DOUBLE_LINE_KINDS and row_data is not None and row_data.filename:
            return QSize(0, _scale.px(_ROW_DOUBLE_U))
        return QSize(0, _scale.px(_ROW_SINGLE_U))

    # -- Editor (expansion card; wired fully in Task 5) ----------------------

    def createEditor(self, parent: QWidget, option: QStyleOptionViewItem, index: QModelIndex):  # noqa: N802
        del option
        if self.expansion_card_provider is None or not index.data(EXPANDED_ROLE):
            return None
        editor = self.expansion_card_provider(index)
        if editor is not None:
            # The delegate owns the parenting contract: the provider returns an
            # orphan card, and an orphan editor floats as a top-level window
            # instead of rendering inside the row.
            editor.setParent(parent)
        return editor

    def updateEditorGeometry(self, editor: QWidget, option: QStyleOptionViewItem, index: QModelIndex) -> None:  # noqa: N802
        del index
        editor.setGeometry(option.rect)

    # -- Flash ---------------------------------------------------------------

    def flash_row(self, row: int) -> None:
        self._flash_row_index = row
        if self._flash_timer is not None:
            self._flash_timer.stop()
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._clear_flash)
        self._flash_timer.start(_FLASH_DURATION_MS)
        if self._view is not None:
            self._view.viewport().update()

    def _clear_flash(self) -> None:
        self._flash_row_index = -1
        if self._view is not None:
            self._view.viewport().update()

    # -- Painting --------------------------------------------------------

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        self._connect_to_view_model()
        if index.data(EXPANDED_ROLE):
            # The expansion card editor owns painting for this row.
            return
        kind = index.data(ROW_KIND_ROLE)
        if kind == "bulk-hint":
            painter.save()
            fill = theme.qcolor("selection_bg")
            painter.fillRect(option.rect, fill)
            painter.setPen(theme.qcolor("accent"))
            text_rect = option.rect.adjusted(_scale.px(8), 0, -_scale.px(8), 0)
            painter.drawText(text_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                             index.data() or "")
            painter.restore()
            return
        if kind in _HEADER_KINDS:
            self._paint_header(painter, option, index)
            return
        row_data = index.data(ROW_DATA_ROLE)
        if row_data is None:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        is_ghost = row_data.status_text == "Missing File"
        self._paint_background(painter, option, index, ghost=is_ghost)

        if row_data.kind == "movie-file" and row_data.checkable:
            toggle_rect = self.toggle_rect(option.rect)
            state = Qt.CheckState.Checked if row_data.checked else Qt.CheckState.Unchecked
            paint_check_indicator(painter, toggle_rect.adjusted(1, 1, -1, -1), state)
        if row_data.kind in _CHEVRON_KINDS and not is_ghost:
            self._paint_chevron(painter, option, index)

        self._paint_body(painter, option, row_data, ghost=is_ghost)
        painter.restore()

    def _paint_background(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex, *, ghost: bool) -> None:
        rect = option.rect
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.qcolor("surface"))
        painter.drawRect(rect)

        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected:
            painter.setBrush(theme.qcolor("selection_bg"))
            painter.drawRect(rect)
            pen = QPen(theme.qcolor("accent"), 1)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect.adjusted(0, 0, -1, -1))
        elif hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme.qcolor("card_hover"))
            painter.drawRect(rect)

        if self._flash_row_index != -1 and index.row() == self._flash_row_index:
            flash_color = theme.qcolor("accent")
            flash_color.setAlphaF(0.18)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(flash_color)
            painter.drawRect(rect)

        if ghost:
            pen = QPen(theme.qcolor("border_light"), 1, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            radius = theme.radius("sm")
            painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), radius, radius)

    def _paint_header(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.qcolor("section_header_bg"))
        painter.drawRect(option.rect)
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(theme.qcolor("accent"))
        text_rect = option.rect.adjusted(_scale.px(_MARGIN_U), 0, -_scale.px(_MARGIN_U), 0)
        painter.drawText(text_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), text)
        painter.restore()

    def _paint_chevron(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        del index
        rect = self.chevron_rect(option.rect)
        painter.save()
        painter.setPen(theme.qcolor("text_dim"))
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), "›")
        painter.restore()

    def _paint_body(self, painter: QPainter, option: QStyleOptionViewItem, row_data: EpisodeRowData, *, ghost: bool) -> None:
        metrics = painter.fontMetrics()
        margin = _scale.px(_MARGIN_U)
        title_x = self._title_x(option.rect, row_data)
        pill_rect = self._pill_rect(option.rect, row_data, metrics)
        title_width = max(0, pill_rect.x() - title_x - margin)
        line_height = metrics.lineSpacing()

        # Row height (delegate.sizeHint) is driven by row_data.filename alone —
        # keep the second-line trigger identical so painting never overflows
        # a single-line row (e.g. compact view_mode, which blanks filename
        # even when companions are present).
        has_second_line = bool(row_data.filename)
        if has_second_line:
            first_line_y = option.rect.y() + margin
        else:
            first_line_y = option.rect.y() + (option.rect.height() - line_height) // 2
        first_line_rect = QRect(title_x, first_line_y, title_width, line_height)

        painter.setPen(theme.qcolor("text_muted") if ghost else theme.qcolor("text"))
        title_text = metrics.elidedText(row_data.title, Qt.TextElideMode.ElideRight, title_width)
        if not has_second_line and row_data.companion_count > 0:
            title_text = metrics.elidedText(
                f"{row_data.title}  +{row_data.companion_count} companions",
                Qt.TextElideMode.ElideRight, title_width,
            )
        painter.drawText(first_line_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), title_text)

        if row_data.confidence_pct is not None and row_data.status_text == "Review":
            bar_x = pill_rect.x() - margin - _scale.px(_BAR_W_U)
            bar_rect = QRect(bar_x, first_line_rect.y() + (line_height - _scale.px(4)) // 2, _scale.px(_BAR_W_U), _scale.px(4))
            color = theme.qcolor(_TONE_COLOR.get(row_data.status_tone, "text_dim"))
            paint_mini_progress(painter, bar_rect, value=row_data.confidence_pct, color=color)

        if has_second_line:
            second_line_rect = QRect(title_x, first_line_y + line_height, title_width, line_height)
            second_text = metrics.elidedText(row_data.filename, Qt.TextElideMode.ElideMiddle, title_width)
            if row_data.target:
                arrow_text = f" → {row_data.target}"
                combined_width = max(0, title_width - metrics.horizontalAdvance(second_text))
                second_text += metrics.elidedText(arrow_text, Qt.TextElideMode.ElideRight, combined_width)
            if row_data.companion_count > 0:
                suffix = f"  +{row_data.companion_count} companions"
                combined_width = max(0, title_width - metrics.horizontalAdvance(second_text))
                second_text += metrics.elidedText(suffix, Qt.TextElideMode.ElideRight, combined_width)
            painter.setPen(theme.qcolor("text_dim"))
            painter.drawText(second_line_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), second_text)

        self._paint_pill(painter, pill_rect, row_data, ghost=ghost)

    def _paint_pill(self, painter: QPainter, pill_rect: QRect, row_data: EpisodeRowData, *, ghost: bool) -> None:
        if not row_data.status_text:
            return
        tone_token = "text_dim" if ghost else _TONE_COLOR.get(row_data.status_tone, "text_dim")
        fill = theme.qcolor(tone_token)
        fill.setAlphaF(0.12)
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        radius = theme.radius("pill")
        painter.drawRoundedRect(pill_rect, radius, radius)
        painter.setPen(theme.qcolor(tone_token))
        painter.drawText(pill_rect, int(Qt.AlignmentFlag.AlignCenter), row_data.status_text.upper())
        painter.restore()


class EpisodeTableView(QListView):
    chevron_clicked = Signal(QModelIndex)
    toggle_clicked = Signal(QModelIndex)          # movie-file rows
    header_clicked = Signal(str)                  # section_key of a collapsible header
    expand_key_pressed = Signal(QModelIndex)      # Enter/Return on current row
    bulk_hint_clicked = Signal()                  # problems-filter empty-state hint row

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.setUniformItemSizes(False)
        self.setProperty("cssClass", "row-host-list")
        self._intercepted_row: int = -1
        self.clicked.connect(self._on_clicked)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        index = self.indexAt(pos)
        if index.isValid():
            kind = index.data(ROW_KIND_ROLE)
            delegate = self.itemDelegateForIndex(index)
            if kind in _CHEVRON_KINDS and isinstance(delegate, EpisodeTableDelegate):
                rect = self.visualRect(index)
                if kind == "movie-file":
                    row_data = index.data(ROW_DATA_ROLE)
                    if row_data is not None and row_data.checkable:
                        toggle_rect = delegate.toggle_rect(rect)
                        if toggle_rect.contains(pos):
                            self._intercepted_row = index.row()
                            self.toggle_clicked.emit(index)
                            return
                chevron_rect = delegate.chevron_rect(rect)
                if chevron_rect.contains(pos):
                    self._intercepted_row = index.row()
                    self.chevron_clicked.emit(index)
                    return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        index = self.indexAt(pos)
        if self._intercepted_row != -1 and index.isValid() and index.row() == self._intercepted_row:
            self._intercepted_row = -1
            return
        self._intercepted_row = -1
        super().mouseReleaseEvent(event)

    def _on_clicked(self, index: QModelIndex) -> None:
        kind = index.data(ROW_KIND_ROLE)
        if kind == "section-header":
            section_key = index.data(SECTION_KEY_ROLE)
            if section_key:
                self.header_clicked.emit(section_key)
        elif kind == "bulk-hint":
            self.bulk_hint_clicked.emit()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            index = self.currentIndex()
            if index.isValid() and index.data(ROW_KIND_ROLE) in _CHEVRON_KINDS:
                self.expand_key_pressed.emit(index)
                return
        super().keyPressEvent(event)
