"""Reusable row widgets for the media workspace roster and preview panels."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...engine import PreviewItem
from ._formatting import clamped_percent, percent_text
from ._workspace_widget_primitives import (
    _CheckBinding,
    ClickableRow,
    ElidedLabel,
    MasterCheckBox,
    MiniProgressBar,
    ToggleSwitch,
)
from .. import _scale
from ._media_helpers import (
    companion_summary as _companion_summary,
    confidence_fill_color as _confidence_fill_color,
    preview_band as _preview_band,
    preview_band_name as _preview_band_name,
    preview_heading as _preview_heading,
    preview_status_label as _preview_status_label,
    preview_status_tone as _preview_status_tone,
    preview_target_text as _preview_target_text,
    repolish as _repolish,
)


# ── Utility helpers ──────────────────────────────────────────────────

def _percent_from_label(value: str) -> int | None:
    text = value.strip()
    if not text.endswith("%"):
        return None
    try:
        return max(0, min(100, int(round(float(text[:-1])))))
    except ValueError:
        return None


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
        media_type: str = "tv",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("previewRowCard")
        self.setProperty("cssClass", "preview-row-card")
        self._preview = preview
        self._media_type = media_type
        self._selected = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        show_check = (
            media_type != "movie"
            and preview.is_actionable
            and checkable
        )
        self._check = ToggleSwitch(checked if show_check else False, self)
        self._check.setVisible(show_check)
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
        self._confidence_percent = None
        if show_confidence:
            confidence_row = QHBoxLayout()
            confidence_row.setContentsMargins(0, 0, 0, 0)
            confidence_row.setSpacing(8)
            self._confidence = MiniProgressBar(
                color=_preview_band(self._preview),
                value=clamped_percent(preview.episode_confidence),
            )
            confidence_row.addWidget(self._confidence, stretch=1)

            self._confidence_percent = QLabel(percent_text(preview.episode_confidence), self)
            self._confidence_percent.setProperty("cssClass", "caption")
            self._confidence_percent.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self._confidence_percent.setFixedWidth(
                self._confidence_percent.fontMetrics().horizontalAdvance("100%") + _scale.px(2)
            )
            confidence_row.addWidget(self._confidence_percent)
            body.addLayout(confidence_row)

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

class EpisodeGuideRowWidget(ClickableRow):
    action_requested = Signal(str)
    _COMPACT_ROW_MIN_HEIGHT_GRID_UNITS = 72
    _STATUS_PILL_HORIZONTAL_CHROME = 18

    @property
    def _COMPACT_ROW_MIN_HEIGHT(self) -> int:  # noqa: N802
        return _scale.px(self._COMPACT_ROW_MIN_HEIGHT_GRID_UNITS)

    def __init__(
        self,
        *,
        title: str,
        status: str,
        original: str = "",
        target: str = "",
        confidence: str = "",
        companions: list[str] | None = None,
        actions: list[tuple[str, str]] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("episodeGuideRowCard")
        self.setProperty("cssClass", "preview-row-card")
        self.setProperty("band", self._band_for_status(status))
        self.setProperty("selectionState", "normal")
        self._selected = False
        self._row_height = self._COMPACT_ROW_MIN_HEIGHT
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        actions_list = list(actions) if actions is not None else []
        has_approve = any(action_id == "approve" for action_id, _label in actions_list)
        non_approve_actions = [(action_id, label) for action_id, label in actions_list if action_id != "approve"]
        show_actions = bool(actions_list)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(_scale.margins(7, 8))
        layout.setSpacing(_scale.px(8))

        self._check = ToggleSwitch(False, self)
        self._check.hide()
        layout.addWidget(self._check, alignment=Qt.AlignmentFlag.AlignTop)

        body = QVBoxLayout()
        body.setSpacing(_scale.px(3))
        layout.addLayout(body, stretch=1)

        top_row = QHBoxLayout()
        top_row.setSpacing(_scale.px(8))
        self._title = ElidedLabel(
            title,
            elide_mode=Qt.TextElideMode.ElideRight,
            parent=self,
        )
        self._title.setProperty("cssClass", "row-title")
        self._title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        top_row.addWidget(self._title, stretch=1)

        self._status = QLabel(status, self)
        self._status.setProperty("cssClass", "status-pill")
        self._status.setProperty("tone", self._tone_for_status(status))
        self._status.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._status.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._status.setMinimumWidth(self._status_pill_minimum_width(status))
        top_row.addWidget(self._status, alignment=Qt.AlignmentFlag.AlignTop)
        body.addLayout(top_row)

        self._original = ElidedLabel(
            original,
            elide_mode=Qt.TextElideMode.ElideMiddle,
            parent=self,
        )
        self._original.setProperty("cssClass", "caption")
        self._original.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._original.setVisible(bool(original))
        body.addWidget(self._original)

        self._target = ElidedLabel(
            f"-> {target}" if target else "",
            elide_mode=Qt.TextElideMode.ElideMiddle,
            parent=self,
        )
        self._target.setProperty("cssClass", "row-target")
        self._target.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._target.setVisible(bool(target))
        body.addWidget(self._target)

        companion_text = ", ".join(companions or [])
        self._companions = ElidedLabel(
            f"Companions: {companion_text}" if companion_text else "",
            elide_mode=Qt.TextElideMode.ElideMiddle,
            parent=self,
        )
        self._companions.setProperty("cssClass", "caption")
        self._companions.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._companions.setVisible(bool(companion_text))
        body.addWidget(self._companions)

        confidence_value = _percent_from_label(confidence)
        self._confidence_label = QLabel("Confidence", self)
        self._confidence_label.setProperty("cssClass", "caption")
        self._confidence_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._confidence_label.setVisible(confidence_value is not None)

        self._confidence = MiniProgressBar(
            color=_confidence_fill_color((confidence_value or 0) / 100),
            value=confidence_value or 0,
            parent=self,
        )
        self._confidence.setFixedWidth(_scale.px(96))
        self._confidence.setVisible(confidence_value is not None)

        self._confidence_percent = QLabel(confidence if confidence_value is not None else "", self)
        self._confidence_percent.setProperty("cssClass", "caption")
        self._confidence_percent.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._confidence_percent.setFixedWidth(
            self._confidence_percent.fontMetrics().horizontalAdvance("100%") + _scale.px(2)
        )
        self._confidence_percent.setVisible(confidence_value is not None)

        # Inline Approve button — shown only when an ("approve", ...) action is present.
        self._approve_button = QPushButton("Approve", self)
        self._approve_button.setProperty("cssClass", "primary")
        self._approve_button.setProperty("sizeVariant", "inline")
        self._approve_button.setFixedHeight(_scale.row_height(rows=1, padding=10))
        self._approve_button.setVisible(has_approve)
        self._approve_button.clicked.connect(lambda: self.action_requested.emit("approve"))

        # ⋯ tool button with popup menu for all non-approve actions.
        if non_approve_actions:
            self._actions_button: QToolButton | None = QToolButton(self)
            self._actions_button.setText("⋯")
            self._actions_button.setToolTip("More actions")
            self._actions_button.setAccessibleName("More actions")
            self._actions_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            self._actions_button.setFixedHeight(_scale.row_height(rows=1, padding=10))
            self._actions_button.setFixedWidth(_scale.px(28))
            self._actions_menu = QMenu(self._actions_button)
            for action_id, label in non_approve_actions:
                q_action = QAction(label, self._actions_menu)
                q_action.triggered.connect(
                    lambda _checked=False, aid=action_id: self.action_requested.emit(aid)
                )
                self._actions_menu.addAction(q_action)
            self._actions_button.setMenu(self._actions_menu)
        else:
            self._actions_button = None
            self._actions_menu: QMenu | None = None

        if confidence_value is not None or show_actions:
            confidence_row = QHBoxLayout()
            confidence_row.setContentsMargins(0, 0, 0, 0)
            confidence_row.setSpacing(_scale.px(8))
            confidence_row.addWidget(self._confidence_label)
            confidence_row.addWidget(self._confidence)
            confidence_row.addWidget(self._confidence_percent)
            confidence_row.addWidget(self._approve_button)
            if self._actions_button is not None:
                confidence_row.addWidget(self._actions_button)
            confidence_row.addStretch(1)
            body.addLayout(confidence_row)
            if show_actions:
                body.addStretch(1)

        self._row_height = self._preferred_row_height(show_actions)
        self.setFixedHeight(self._row_height)
        self._apply_style()

    def actions_button(self) -> QToolButton | None:
        """Return the ⋯ tool button, or None if no non-approve actions were supplied."""
        return self._actions_button

    def actions_menu(self) -> QMenu | None:
        """Return the popup menu attached to the ⋯ tool button, or None if no tool button exists."""
        return self._actions_menu

    def approve_button(self) -> QPushButton:
        """Return the inline Approve push button."""
        return self._approve_button

    def sizeHint(self) -> QSize:  # noqa: N802
        hint = super().sizeHint()
        return QSize(hint.width(), self._row_height)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        hint = super().minimumSizeHint()
        return QSize(hint.width(), self._row_height)

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._apply_style()

    def _apply_style(self) -> None:
        self.setProperty("selectionState", "selected" if self._selected else "normal")
        _repolish(self)
        _repolish(self._status)

    def _status_pill_minimum_width(self, text: str) -> int:
        text_width = self._status.fontMetrics().horizontalAdvance(text)
        return max(
            self._status.sizeHint().width(),
            text_width + self._STATUS_PILL_HORIZONTAL_CHROME,
        )

    def _preferred_row_height(self, has_actions: bool) -> int:
        layout = self.layout()
        content_height = layout.sizeHint().height() if layout is not None else 0
        if has_actions:
            return max(self._COMPACT_ROW_MIN_HEIGHT, content_height + self._action_bottom_extra())
        return max(self._COMPACT_ROW_MIN_HEIGHT, content_height)

    def _action_bottom_extra(self) -> int:
        return max(1, self._approve_button.fontMetrics().height() // 3)

    @staticmethod
    def _band_for_status(status: str) -> str:
        if status == "Conflict":
            return "error"
        if status == "Missing File":
            return "muted"
        if status == "Review":
            return "accent"
        return "success"

    @staticmethod
    def _tone_for_status(status: str) -> str:
        if status == "Conflict":
            return "error"
        if status == "Missing File":
            return "muted"
        if status == "Review":
            return "accent"
        return "success"


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
