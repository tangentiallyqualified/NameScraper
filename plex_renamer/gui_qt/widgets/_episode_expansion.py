# plex_renamer/gui_qt/widgets/_episode_expansion.py
"""EpisodeExpansionCard — persistent-editor detail card for an expanded
episode-table row (GUI V4 Plan 3, spec §3.2.4).

``episode_row_actions`` is moved verbatim from
``MediaWorkspacePreviewPanel._episode_row_actions`` — the action-id
vocabulary it returns is consumed by the frozen
``MediaWorkspaceActionCoordinator.handle_episode_row_action`` contract, so
the ids/order must not change.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...app.models.state_models import EpisodeGuideRow
from ...engine import PreviewItem, ScanState
from .. import _scale
from .status_chip import ChipSpec, chip_rects, chip_row_height, paint_chip_row

_COPY_GLYPH = "⧉"
_OPEN_DIR_GLYPH = "📂"
_COLLAPSE_GLYPH = "▴"
_MERGE_TOOLTIP = "Merge support arrives with mkvmerge integration"


def episode_row_actions(row) -> list[tuple[str, str]]:
    """Action ids + labels available for one episode-guide row.

    Moved verbatim from ``MediaWorkspacePreviewPanel._episode_row_actions``.
    """
    if row.status == "Missing File":
        return [("assign_file", "Assign file...")]
    if row.status == "Conflict":
        return [
            ("keep_this", "Keep this file (unassign others)"),
            ("reassign", "Reassign..."),
            ("assign_to_more", "Assign to more..."),
            ("unassign", "Unassign"),
        ]
    actions: list[tuple[str, str]] = []
    if row.status == "Review":
        actions.append(("approve", "Approve"))
    actions.append(("reassign", "Reassign..."))
    actions.append(("assign_to_more", "Assign to more..."))
    actions.append(("unassign", "Unassign"))
    return actions


class _ChipStrip(QWidget):
    """Tiny inline widget that paints a row of ``status_chip`` chips
    (used for the "Part 1 · Part 2" multi-part seam)."""

    def __init__(self, specs: list[ChipSpec], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._specs = specs
        height = chip_row_height()
        width = 0
        if specs:
            rects = chip_rects(0, 0, specs, self.fontMetrics())
            if rects:
                width = rects[-1].right()
        self.setFixedHeight(height)
        self.setMinimumWidth(width)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        paint_chip_row(painter, 0, 0, self._specs)
        painter.end()


def _copy_path_button(path, parent: QWidget) -> QToolButton:
    button = QToolButton(parent)
    button.setText(_COPY_GLYPH)
    button.setToolTip("Copy path")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.clicked.connect(lambda: QApplication.clipboard().setText(str(path)))
    return button


class EpisodeExpansionCard(QFrame):
    action_requested = Signal(str)
    collapse_requested = Signal()
    open_dir_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("cssClass", "card")
        self._action_buttons: list[QPushButton] = []
        self._copy_buttons: list[QToolButton] = []
        self._open_dir_buttons: list[QToolButton] = []
        self._target_label: QLabel | None = None
        self._build_ui()

    # -- Layout scaffold -----------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        margin = _scale.px(12)
        outer.setContentsMargins(margin, margin, margin, margin)
        outer.setSpacing(_scale.px(8))

        top_row = QHBoxLayout()
        self._collapse_button = QToolButton()
        self._collapse_button.setText(_COLLAPSE_GLYPH)
        self._collapse_button.setToolTip("Collapse")
        self._collapse_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._collapse_button.clicked.connect(self.collapse_requested.emit)
        top_row.addWidget(self._collapse_button)
        top_row.addStretch()
        outer.addLayout(top_row)

        self._files_section = QVBoxLayout()
        self._files_section.setSpacing(_scale.px(4))
        outer.addLayout(self._files_section)

        self._target_row = QHBoxLayout()
        outer.addLayout(self._target_row)

        self._actions_row = QHBoxLayout()
        self._actions_row.setSpacing(_scale.px(6))
        outer.addLayout(self._actions_row)

        outer.addStretch()

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
                continue
            child_layout = item.layout()
            if child_layout is not None:
                self._clear_layout(child_layout)

    # -- Public API -------------------------------------------------------

    def show_episode(self, state: ScanState, row: EpisodeGuideRow) -> None:
        self._reset_content()
        part_specs = self._multi_part_chip_specs(state, row)
        if part_specs:
            self._files_section.addWidget(_ChipStrip(part_specs, self))
        if row.primary_file is not None:
            self._build_labeled_path(
                "Episode Source", str(row.primary_file.original), open_dir=True
            )
        self._build_labeled_path("Episode Output", row.target_rename or "", open_dir=False)
        subtitle = next((c for c in row.companions if c.file_type == "subtitle"), None)
        if subtitle is not None:
            self._build_labeled_path("Subtitle Source", str(subtitle.original), open_dir=True)
            self._build_labeled_path(
                "Subtitle Output", subtitle.new_name or "", open_dir=False
            )
        self._build_actions_row(episode_row_actions(row))

    def show_movie(self, state: ScanState, preview: PreviewItem) -> None:
        del state
        self._reset_content()
        self._build_files_section_for_files(preview.original, preview.companions)
        self._build_target_row(preview.new_name or "")
        # Movie mode: overview lives in the header, no actions row.

    # -- Content builders --------------------------------------------------

    def _reset_content(self) -> None:
        self._action_buttons = []
        self._copy_buttons = []
        self._open_dir_buttons = []
        self._clear_layout(self._files_section)
        self._clear_layout(self._target_row)
        self._clear_layout(self._actions_row)

    def _open_dir_button(self, directory: str) -> QToolButton:
        button = QToolButton(self)
        button.setText(_OPEN_DIR_GLYPH)
        button.setToolTip("Open file directory")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda _checked=False, d=directory: self.open_dir_requested.emit(d))
        return button

    def _build_labeled_path(self, label_text: str, path: str, *, open_dir: bool) -> None:
        row_widget = QWidget(self)
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(_scale.px(6))
        label = QLabel(f"{label_text}: {path}")
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row_layout.addWidget(label, stretch=1)
        if open_dir:
            button = self._open_dir_button(os.path.dirname(path))
            row_layout.addWidget(button)
            self._open_dir_buttons.append(button)
        self._files_section.addWidget(row_widget)

    def _build_files_section_for_files(self, primary_path, companions) -> None:
        self._add_file_row(primary_path, badge=None)
        for companion in companions:
            badge = companion.file_type[:3].upper()
            self._add_file_row(companion.original, badge=badge)

    def _multi_part_chip_specs(self, state: ScanState, row: EpisodeGuideRow) -> list[ChipSpec]:
        table = state.assignments
        if table is None:
            return []
        claims = table.claims(row.season, row.episode)
        if len(claims) <= 1:
            return []
        conflicted = table.conflicted_file_ids()
        non_conflict = [claim for claim in claims if claim.file_id not in conflicted]
        if len(non_conflict) <= 1:
            return []
        return [
            ChipSpec(f"Part {index}", "muted")
            for index in range(1, len(non_conflict) + 1)
        ]

    def _add_file_row(self, path, *, badge: str | None) -> None:
        row_widget = QWidget(self)
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(_scale.px(6))

        if badge:
            badge_label = QLabel(badge)
            badge_label.setProperty("cssClass", "badge")
            badge_label.setProperty("tone", "muted")
            row_layout.addWidget(badge_label)

        path_label = QLabel(str(path))
        path_label.setWordWrap(True)
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row_layout.addWidget(path_label, stretch=1)

        copy_button = _copy_path_button(path, row_widget)
        row_layout.addWidget(copy_button)
        self._copy_buttons.append(copy_button)

        self._files_section.addWidget(row_widget)

    def _build_target_row(self, target_rename: str) -> None:
        label = QLabel(f"→ {target_rename}" if target_rename else "")
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._target_label = label
        self._target_row.addWidget(label, stretch=1)
        copy_button = _copy_path_button(target_rename, self)
        self._target_row.addWidget(copy_button)
        self._copy_buttons.append(copy_button)

    def _build_actions_row(self, actions: list[tuple[str, str]]) -> None:
        for action_id, label in actions:
            button = QPushButton(label)
            button.setProperty("actionId", action_id)
            button.setProperty("cssClass", "primary" if action_id == "approve" else "secondary")
            button.clicked.connect(lambda _checked=False, aid=action_id: self.action_requested.emit(aid))
            self._actions_row.addWidget(button)
            self._action_buttons.append(button)

        merge_button = QPushButton("Merge…")
        merge_button.setEnabled(False)
        merge_button.setToolTip(_MERGE_TOOLTIP)
        merge_button.setProperty("cssClass", "secondary")
        self._actions_row.addWidget(merge_button)
        self._actions_row.addStretch()
