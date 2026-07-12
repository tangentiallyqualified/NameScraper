# plex_renamer/gui_qt/widgets/_episode_table_delegate.py
"""Painted episode-table rows: EpisodeTableDelegate + EpisodeTableView (GUI V4 Plan 3)."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QModelIndex, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QHelpEvent, QKeyEvent, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QListView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolTip,
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

_ROW_HEADER_U, _ROW_SINGLE_U, _ROW_DOUBLE_U, _ROW_MOVIE_U = 30, 34, 52, 52
_ROW_TRIPLE_U = 68
_CHEVRON_U, _PILL_H_U, _MARGIN_U = 16, 18, 8
_PILL_HPAD_U = 8
_FALLBACK_EXPANDED_HEIGHT_U = 220
_INLINE_ACTION_W_U, _INLINE_ACTION_H_U = 84, 20
_ACTION_STRIP_U = 24

_TONE_COLOR = {"success": "success", "warning": "warning", "error": "error", "muted": "text_dim"}

# Wash tint laid under Review/Conflict rows (token, alpha); movie rows keep
# the raw uppercase "CONFLICT" status label.
_STATUS_WASH = {
    "Review": ("warning", 0.05),
    "Conflict": ("error", 0.06),
    "CONFLICT": ("error", 0.06),
}

# Review-pill confidence band thresholds (percent); mirrors
# _media_helpers.confidence_band's 0.85 / 0.5 score thresholds.
_PILL_BAND_HIGH_PCT, _PILL_BAND_MID_PCT = 85, 50

_HEADER_KINDS = {"section-header", "section-label"}
_CHEVRON_KINDS = {"episode"}
_DOUBLE_LINE_KINDS = {"episode", "unmapped", "duplicate", "orphan", "folder"}
_INLINE_ASSIGN_KINDS = {"unmapped", "duplicate"}

_FLASH_DURATION_MS = 700


def _row_inline_actions(row_data: EpisodeRowData) -> tuple[tuple[str, str], ...]:
    """(action_id, label) pairs for a row's inline button(s).

    Missing File / unmapped / duplicate rows keep the legacy single button
    (placed left of the pill, painted with `_paint_action_button`'s accent
    style below). Everything else defers to the model-computed
    `row_data.inline_actions` action strip (Task 6).
    """
    if row_data.status_text == "Missing File":
        return (("assign_file", "Assign file…"),)
    if row_data.kind in _INLINE_ASSIGN_KINDS:
        return (("assign_unmapped", "Assign…"),)
    return row_data.inline_actions


def _is_legacy_action_row(row_data: EpisodeRowData) -> bool:
    """True for rows whose inline action renders left of the pill (today's
    single-button placement) rather than on the bottom action strip."""
    return row_data.status_text == "Missing File" or row_data.kind in _INLINE_ASSIGN_KINDS


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

    def _title_x(self, option_rect: QRect, row_data: EpisodeRowData) -> int:
        margin = _scale.px(_MARGIN_U)
        x = option_rect.x() + margin
        if row_data.kind in _CHEVRON_KINDS:
            x += _scale.px(_CHEVRON_U) + margin
        return x

    def pill_text(self, row_data: EpisodeRowData) -> str:
        if row_data.confidence_pct is not None and row_data.status_text in ("Review", "Matched", "Mapped"):
            return f"{row_data.status_text} {row_data.confidence_pct}%"
        return row_data.status_text

    def pill_tone(self, row_data: EpisodeRowData) -> str:
        if row_data.status_text == "Review" and row_data.confidence_pct is not None:
            if row_data.confidence_pct >= _PILL_BAND_HIGH_PCT:
                return "success"
            if row_data.confidence_pct >= _PILL_BAND_MID_PCT:
                return "warning"
            return "error"
        return row_data.status_tone

    def _pill_rect(self, option_rect: QRect, row_data: EpisodeRowData, metrics) -> QRect:
        text = self.pill_text(row_data).upper()
        pad = _scale.px(_PILL_HPAD_U)
        height = _scale.px(_PILL_H_U)
        margin = _scale.px(_MARGIN_U)
        width = metrics.horizontalAdvance(text) + 2 * pad
        x = option_rect.right() - margin - width
        y = option_rect.y() + (option_rect.height() - height) // 2
        return QRect(x, y, width, height)

    def _left_anchor(self, option_rect: QRect, row_data: EpisodeRowData, metrics) -> int:
        """X coordinate of the leftmost pill/legacy-action rect on the row --
        the anchor the MUX chip (and text_right_edge) sit left of."""
        anchor = self._pill_rect(option_rect, row_data, metrics).x()
        if _is_legacy_action_row(row_data):
            rects = self.inline_action_rects(option_rect, row_data)
            if rects and rects[0][1].isValid():
                anchor = min(anchor, rects[0][1].x())
        return anchor

    def mux_chip_rect(self, option_rect: QRect, row_data: EpisodeRowData, metrics) -> QRect:
        """Compact 'MUX' chip rect, sat left of the pill (and legacy inline
        action, when present) -- invalid QRect() when the row's file will
        not actually be muxed (round5 §1b)."""
        if not row_data.mux_active:
            return QRect()
        text = "MUX"
        pad = _scale.px(_PILL_HPAD_U)
        height = _scale.px(_PILL_H_U)
        margin = _scale.px(_MARGIN_U)
        width = metrics.horizontalAdvance(text) + 2 * pad
        x = self._left_anchor(option_rect, row_data, metrics) - margin - width
        y = option_rect.y() + (option_rect.height() - height) // 2
        return QRect(x, y, width, height)

    def inline_action_rects(self, option_rect: QRect, row_data: EpisodeRowData) -> list[tuple[str, QRect]]:
        """Hit/paint rects for the row's inline action button(s).

        Legacy rows (Missing File / unmapped / duplicate) get a single rect
        left of the pill, vertically centered — today's placement. Everything
        else with `row_data.inline_actions` gets a bottom-row action strip,
        right-aligned, buttons laid out right-to-left from the row's right
        margin (so the returned list stays in left-to-right button order).
        """
        actions = _row_inline_actions(row_data)
        if not actions:
            return []
        margin = _scale.px(_MARGIN_U)
        height = _scale.px(_INLINE_ACTION_H_U)
        metrics = self._view.fontMetrics() if self._view else None
        if _is_legacy_action_row(row_data):
            pill = self._pill_rect(option_rect, row_data, metrics) if metrics else QRect()
            width = _scale.px(_INLINE_ACTION_W_U)
            x = pill.x() - margin - width
            y = option_rect.y() + (option_rect.height() - height) // 2
            return [(actions[0][0], QRect(x, y, width, height))]
        rects: list[tuple[str, QRect]] = []
        y = option_rect.bottom() - margin - height
        x = option_rect.right() - margin
        for action_id, label in reversed(actions):
            width = (metrics.horizontalAdvance(label) if metrics else 60) + 2 * _scale.px(_PILL_HPAD_U)
            x -= width
            rects.append((action_id, QRect(x, y, width, height)))
            x -= _scale.px(4)
        rects.reverse()
        return rects

    def text_right_edge(self, option_rect: QRect, row_data: EpisodeRowData, metrics) -> int:
        """X coordinate the row's text lines must not cross: the pill, the
        legacy inline action button when the row has one, or the MUX chip
        when the row's file will be muxed. Action-strip buttons live on
        their own bottom row and never constrain the text width, so only
        the legacy placement is considered here."""
        right = self._left_anchor(option_rect, row_data, metrics)
        chip = self.mux_chip_rect(option_rect, row_data, metrics)
        if chip.isValid():
            right = min(right, chip.x())
        return right - _scale.px(_MARGIN_U)

    # -- Tooltip -------------------------------------------------------------

    def _preview_is_truncated(self, text: str, width: int) -> bool:
        if not text or width <= 0:
            return False
        metrics = self._view.fontMetrics() if self._view is not None else None
        if metrics is None:
            return False
        return metrics.horizontalAdvance(text) > width

    def helpEvent(self, event, view, option, index):  # noqa: N802
        if event.type() != QHelpEvent.Type.ToolTip or index.data(EXPANDED_ROLE):
            QToolTip.hideText()
            return False
        row_data = index.data(ROW_DATA_ROLE)
        if row_data is None or not row_data.tooltip:
            QToolTip.hideText()
            return False
        # Generic across row kinds: episode/unmapped/duplicate rows each set
        # their own `tooltip` string (rename preview, unmapped/duplicate
        # reason), so this gate has no episode-specific logic.
        title_x = self._title_x(option.rect, row_data)
        width = max(0, self.text_right_edge(option.rect, row_data, self._view.fontMetrics()) - title_x)
        if self._preview_is_truncated(row_data.tooltip, width):
            QToolTip.showText(event.globalPos(), row_data.tooltip, view)
            return True
        QToolTip.hideText()
        return False

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
        if kind == "skeleton":
            return QSize(0, _scale.px(_ROW_SINGLE_U))
        if kind == "movie-file":
            return QSize(0, _scale.px(_ROW_MOVIE_U))
        row_data = index.data(ROW_DATA_ROLE)
        base = _ROW_SINGLE_U
        if row_data is not None:
            if row_data.subtitle_name:
                base = _ROW_TRIPLE_U
            elif kind in _DOUBLE_LINE_KINDS and row_data.filename:
                base = _ROW_DOUBLE_U
            if row_data.inline_actions:
                return QSize(0, _scale.px(base + _ACTION_STRIP_U))
        return QSize(0, _scale.px(base))

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
        if row_data.kind == "skeleton":
            self._paint_skeleton_row(painter, option.rect)
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        is_ghost = row_data.status_text == "Missing File"
        self._paint_background(painter, option, index, ghost=is_ghost)

        if row_data.kind in _CHEVRON_KINDS and not is_ghost:
            self._paint_chevron(painter, option, index)

        self._paint_body(painter, option, row_data, ghost=is_ghost)
        painter.restore()

    def _paint_background(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex, *, ghost: bool) -> None:
        rect = option.rect
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.qcolor("surface"))
        painter.drawRect(rect)

        row_data = index.data(ROW_DATA_ROLE)
        wash = _STATUS_WASH.get(row_data.status_text) if row_data is not None else None
        if wash is not None and not ghost:
            token, alpha = wash
            color = theme.qcolor(token)
            color.setAlphaF(alpha)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
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
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), "▸")
        painter.restore()

    def _paint_skeleton_row(self, painter: QPainter, rect: QRect) -> None:
        margin = _scale.px(_MARGIN_U)
        bar_height = _scale.px(10)
        bar = QRect(
            rect.x() + margin,
            rect.y() + (rect.height() - bar_height) // 2,
            int(rect.width() * 0.55),
            bar_height,
        )
        color = QColor(theme.color("text_dim"))
        color.setAlpha(50)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        radius = bar_height // 2
        painter.drawRoundedRect(bar, radius, radius)
        painter.restore()

    def _paint_body(self, painter: QPainter, option: QStyleOptionViewItem, row_data: EpisodeRowData, *, ghost: bool) -> None:
        metrics = painter.fontMetrics()
        margin = _scale.px(_MARGIN_U)
        title_x = self._title_x(option.rect, row_data)
        pill_rect = self._pill_rect(option.rect, row_data, metrics)
        title_width = max(0, self.text_right_edge(option.rect, row_data, metrics) - title_x)
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
        painter.drawText(first_line_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), title_text)

        if has_second_line:
            second_line_rect = QRect(title_x, first_line_y + line_height, title_width, line_height)
            second_source = row_data.detail or row_data.filename
            second_text = metrics.elidedText(second_source, Qt.TextElideMode.ElideMiddle, title_width)
            painter.setPen(theme.qcolor("text_dim"))
            painter.drawText(second_line_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), second_text)
            if row_data.subtitle_name:
                third_line_rect = QRect(title_x, first_line_y + 2 * line_height, title_width, line_height)
                sub_text = metrics.elidedText(
                    f"Subtitles: {row_data.subtitle_name}", Qt.TextElideMode.ElideMiddle, title_width,
                )
                painter.setPen(theme.qcolor("text_muted"))
                painter.drawText(third_line_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), sub_text)

        self._paint_pill(painter, pill_rect, row_data, ghost=ghost)
        self._paint_mux_chip(painter, self.mux_chip_rect(option.rect, row_data, metrics))

        labels = dict(_row_inline_actions(row_data))
        for action_id, rect in self.inline_action_rects(option.rect, row_data):
            self._paint_action_button(painter, rect, action_id, labels.get(action_id, ""))

    def _paint_action_button(
        self, painter: QPainter, rect: QRect, action_id: str, label: str,
    ) -> None:
        if not rect.isValid():
            return
        painter.save()
        radius = theme.radius("sm")
        if action_id == "approve":
            fill = theme.qcolor("accent")
            fill.setAlphaF(0.14)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill)
            painter.drawRoundedRect(rect, radius, radius)
            painter.setPen(theme.qcolor("accent"))
        else:
            fill = theme.qcolor("text_dim")
            fill.setAlphaF(0.10)
            border = theme.qcolor("text_dim")
            border.setAlphaF(0.4)
            painter.setPen(QPen(border, 1))
            painter.setBrush(fill)
            painter.drawRoundedRect(rect.adjusted(0, 0, -1, -1), radius, radius)
            painter.setPen(theme.qcolor("text"))
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), label)
        painter.restore()

    def _paint_pill(self, painter: QPainter, pill_rect: QRect, row_data: EpisodeRowData, *, ghost: bool) -> None:
        text = self.pill_text(row_data)
        if not text:
            return
        tone_token = "text_dim" if ghost else _TONE_COLOR.get(self.pill_tone(row_data), "text_dim")
        fill = theme.qcolor(tone_token)
        fill.setAlphaF(0.12)
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        radius = theme.radius("pill")
        painter.drawRoundedRect(pill_rect, radius, radius)
        painter.setPen(theme.qcolor(tone_token))
        painter.drawText(pill_rect, int(Qt.AlignmentFlag.AlignCenter), text.upper())
        painter.restore()

    def _paint_mux_chip(self, painter: QPainter, chip_rect: QRect) -> None:
        """Compact 'MUX' chip -- same visual language as _paint_pill but a
        fixed "info" tone (matches the roster AutoMux chip, _roster_model.py)."""
        if not chip_rect.isValid():
            return
        fill = theme.qcolor("info")
        fill.setAlphaF(0.12)
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        radius = theme.radius("pill")
        painter.drawRoundedRect(chip_rect, radius, radius)
        painter.setPen(theme.qcolor("info"))
        painter.drawText(chip_rect, int(Qt.AlignmentFlag.AlignCenter), "MUX")
        painter.restore()


class EpisodeTableView(QListView):
    chevron_clicked = Signal(QModelIndex)
    header_clicked = Signal(str)                  # section_key of a collapsible header
    expand_key_pressed = Signal(QModelIndex)      # Enter/Return on current row
    bulk_hint_clicked = Signal()                  # problems-filter empty-state hint row
    inline_action_clicked = Signal(QModelIndex, str)  # missing-file row inline action (e.g. "assign_file")

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
            if isinstance(delegate, EpisodeTableDelegate) and kind in (_CHEVRON_KINDS | _INLINE_ASSIGN_KINDS):
                rect = self.visualRect(index)
                row_data = index.data(ROW_DATA_ROLE)
                rects = delegate.inline_action_rects(rect, row_data) if row_data is not None else []
                for action_id, action_rect in rects:
                    if action_rect.isValid() and action_rect.contains(pos):
                        self._intercepted_row = index.row()
                        self.inline_action_clicked.emit(index, action_id)
                        return
                if kind in _CHEVRON_KINDS and (row_data is None or row_data.status_text != "Missing File"):
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
                row_data = index.data(ROW_DATA_ROLE)
                if row_data is not None and row_data.status_text == "Missing File":
                    return
                self.expand_key_pressed.emit(index)
                return
        super().keyPressEvent(event)
