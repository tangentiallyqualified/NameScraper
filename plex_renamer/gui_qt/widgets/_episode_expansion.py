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

import html
import os

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...app.models.state_models import EpisodeGuideRow
from ...app.services.automux_service import plan_has_actions
from ...engine import ScanState
from .. import _scale
from .status_chip import ChipSpec, chip_rects, chip_row_height, paint_chip_row

_OPEN_DIR_GLYPH = "📂"
_COLLAPSE_GLYPH = "▾"

# Mirrors _episode_table_delegate._PILL_H_U (geometry contract v2, Task 5/6)
# -- NOT imported, so the painted collapsed row and this QSS-styled card can
# evolve independently. Keep in sync by hand; see task-6-report.md metrics
# table if this drifts from the delegate's painted pill height.
_PILL_HEIGHT_U = 18

_PILL_TONE = {
    "Mapped": "success",
    "Review": "warning",
    "Conflict": "error",
    "Missing File": "muted",
}

# Review-confidence band tones -- mirror _episode_table_delegate.pill_tone so
# the expansion header pill matches the collapsed row's pill exactly.
_PILL_BAND_HIGH_PCT, _PILL_BAND_MID_PCT = 85, 50


def _percent_from_label(value: str) -> int | None:
    """Parse a "NN%" confidence label to an int, mirroring the model helper."""
    text = (value or "").strip()
    if not text.endswith("%"):
        return None
    try:
        return max(0, min(100, int(round(float(text[:-1])))))
    except ValueError:
        return None


def _pill_tone_for(row: EpisodeGuideRow) -> str:
    """Pill tone matching the collapsed-row delegate, including the Review
    confidence bands (success/warning/error) rather than a flat warning."""
    if row.status == "Review":
        pct = _percent_from_label(row.confidence_label)
        if pct is not None:
            if pct >= _PILL_BAND_HIGH_PCT:
                return "success"
            if pct >= _PILL_BAND_MID_PCT:
                return "warning"
            return "error"
    return _PILL_TONE.get(row.status, "muted")


def _subtitle_is_merged(mux_plan: dict | None, subtitle) -> bool:
    """True when ``mux_plan`` merges this subtitle companion into the video.

    A merged subtitle has no standalone output file — the expansion card
    must suppress its "Subtitle Output" row in that case.
    """
    if not mux_plan:
        return False
    sub_name = str(subtitle.original).replace("\\", "/").rsplit("/", 1)[-1]
    for merge in mux_plan.get("subtitle_merges", []):
        if merge.get("action") != "merge":
            continue
        merge_name = str(merge.get("source_relative", "")).replace("\\", "/").rsplit("/", 1)[-1]
        if merge_name == sub_name:
            return True
    return False


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


class EpisodeExpansionCard(QFrame):
    action_requested = Signal(str)
    collapse_requested = Signal()
    open_dir_requested = Signal(str)
    # Per-episode AutoMux opt-out toggle (round5 spec §4b). A NEW signal path,
    # deliberately separate from action_requested so the frozen
    # episode_row_actions id vocabulary stays byte-identical.
    mux_optout_toggled = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("cssClass", "expansion-card")
        self._action_buttons: list[QPushButton] = []
        self._header_action_buttons: list[QPushButton] = []
        self._mux_optout_button: QPushButton | None = None
        self._copy_buttons: list[QToolButton] = []
        self._open_dir_buttons: list[QToolButton] = []
        self._title_label: QLabel | None = None
        self._status_pill: QLabel | None = None
        self._header_row: QHBoxLayout | None = None
        self._build_ui()

    def sizeHint(self) -> QSize:  # noqa: N802
        """QWidget.sizeHint() normally forwards to layout().totalSizeHint(),
        but Qt caches that independently of layout().sizeHint() and does
        not reliably invalidate it when a child already living inside this
        (persistent-editor) card changes its own preferred size later --
        exactly what happens when the AutoMux tracks widget repopulates
        from a probing placeholder to a many-track plan after the editor
        has already been measured once (Task 8's async plan_ready ->
        notify_expanded_row_changed reflow).

        A second, independent layer of the same quirk: _files_section (the
        tracks widget's actual parent layout) is a nested, non-top-level
        sub-layout with its own cached sizeHint that Qt only ever
        auto-invalidates on the *top-level* layout (this widget's own
        updateGeometry() chain stops at self.layout(), never reaching
        _files_section). Explicitly invalidating it here forces a fresh
        recompute on every query instead of trusting either cache."""
        self._files_section.invalidate()
        return self.layout().sizeHint()

    # -- Layout scaffold -----------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        margin = _scale.px(12)
        outer.setContentsMargins(margin, margin, margin, margin)
        outer.setSpacing(_scale.px(8))

        class _CollapseHeader(QWidget):
            def __init__(self, card: "EpisodeExpansionCard") -> None:
                super().__init__(card)
                self._card = card
                self.setCursor(Qt.CursorShape.PointingHandCursor)
                self.setToolTip("Collapse")

            def mousePressEvent(self, event) -> None:  # noqa: N802
                # Final-review fix: only a left click should collapse the
                # card -- right/middle clicks used to collapse it too
                # because the button wasn't checked.
                if event.button() != Qt.MouseButton.LeftButton:
                    super().mousePressEvent(event)
                    return
                self._card.collapse_requested.emit()
                event.accept()

        self._header_widget = _CollapseHeader(self)
        top_row = QHBoxLayout(self._header_widget)
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(_scale.px(6))
        self._header_row = top_row
        self._collapse_button = QToolButton()
        self._collapse_button.setText(_COLLAPSE_GLYPH)
        self._collapse_button.setProperty("cssClass", "expansion-collapse")
        self._collapse_button.setToolTip("Collapse")
        self._collapse_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._collapse_button.setFixedSize(_scale.px(16), _scale.px(16))
        self._collapse_button.clicked.connect(self.collapse_requested.emit)
        top_row.addWidget(self._collapse_button)
        self._title_label = QLabel("")
        top_row.addWidget(self._title_label)
        # Header parity (round5 spec §4a): title, stretch, then the status
        # pill LAST so it right-aligns exactly like the collapsed row's pill.
        top_row.addStretch()
        self._status_pill = QLabel("")
        self._status_pill.setProperty("cssClass", "expansion-pill")
        self._status_pill.setFixedHeight(_scale.px(_PILL_HEIGHT_U))
        top_row.addWidget(self._status_pill)
        outer.addWidget(self._header_widget)

        # Geometry contract v2 mirrored on the card (Task 6): above-fold
        # action buttons form their own right-aligned vertical column
        # directly under the pill -- not siblings inserted into the header
        # row (that was round5's approach; it made the header re-render
        # rather than "grow in place"). An QHBoxLayout with addStretch()
        # anchors the column's right edge to the same right margin the
        # pill sits flush against.
        self._header_actions_host = QHBoxLayout()
        self._header_actions_host.setContentsMargins(0, 0, 0, 0)
        self._header_actions_host.addStretch()
        self._header_actions_column = QVBoxLayout()
        self._header_actions_column.setSpacing(_scale.px(4))
        self._header_actions_host.addLayout(self._header_actions_column)
        outer.addLayout(self._header_actions_host)

        self._actions_row = QHBoxLayout()
        self._actions_row.setSpacing(_scale.px(6))
        outer.addLayout(self._actions_row)

        self._files_section = QVBoxLayout()
        self._files_section.setSpacing(_scale.px(4))
        outer.addLayout(self._files_section)

        self._target_row = QHBoxLayout()
        outer.addLayout(self._target_row)

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

    def show_episode(
        self,
        state: ScanState,
        row: EpisodeGuideRow,
        *,
        mux_plan: dict | None = None,
        preview_index: int | None = None,
        above_fold_ids: tuple[str, ...] = (),
    ) -> None:
        self._reset_content()
        self._apply_header(row)
        self._build_header_actions(row, above_fold_ids)
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
            if _subtitle_is_merged(mux_plan, subtitle):
                self._build_labeled_path(
                    "Subtitle Source",
                    str(subtitle.original),
                    open_dir=True,
                    note="(merged into the video by AutoMux)",
                )
            else:
                self._build_labeled_path(
                    "Subtitle Source", str(subtitle.original), open_dir=True
                )
                self._build_labeled_path(
                    "Subtitle Output", subtitle.new_name or "", open_dir=False
                )
        self._build_actions_row(
            episode_row_actions(row),
            above_fold_ids=above_fold_ids,
            state=state,
            mux_plan=mux_plan,
            preview_index=preview_index,
        )

    # -- Test/introspection accessors -------------------------------------

    def header_action_buttons(self) -> list[QPushButton]:
        """Above-fold action buttons, stacked in a right-aligned column
        directly under the status pill, in the order they were supplied."""
        return list(self._header_action_buttons)

    def action_buttons(self) -> list[QPushButton]:
        """Below-fold action buttons (the ones NOT promoted to the header)."""
        return list(self._action_buttons)

    def status_pill_text(self) -> str:
        return self._status_pill.text() if self._status_pill is not None else ""

    def mux_optout_button(self) -> QPushButton | None:
        return self._mux_optout_button

    def add_tracks_widget(self, widget: QWidget) -> None:
        """Insert the AutoMux tracks section after the file-path rows
        (spec §8.1 — tracks live between the paths and the actions row)."""
        self._files_section.addWidget(widget)

    # -- Content builders --------------------------------------------------

    def _apply_header(self, row: EpisodeGuideRow) -> None:
        title = f"S{row.season:02d}E{row.episode:02d}"
        if row.title:
            title = f"{title} · {row.title}"
        self._title_label.setText(title)
        pill_text = row.status.upper()
        label = row.confidence_label.strip()
        if label.endswith("%") and row.status in ("Mapped", "Review"):
            pill_text = f"{pill_text} {label}"
        self._status_pill.setText(pill_text)
        self._status_pill.setProperty("tone", _pill_tone_for(row))
        style = self._status_pill.style()
        if style is not None:
            style.unpolish(self._status_pill)
            style.polish(self._status_pill)

    def _make_action_button(self, action_id: str, label: str) -> QPushButton:
        button = QPushButton(label)
        button.setProperty("actionId", action_id)
        # Every card button (header column, below-fold, opt-out) shares the
        # same "row-action" visual language as the collapsed row's painted
        # buttons (geometry contract v2, Task 5/6) -- the tone property picks
        # the per-state fill/text from theme.qss.tmpl.
        button.setProperty("cssClass", "row-action")
        button.setProperty("tone", "primary" if action_id == "approve" else "secondary")
        button.setFixedHeight(_scale.px(_PILL_HEIGHT_U))
        button.clicked.connect(
            lambda _checked=False, aid=action_id: self.action_requested.emit(aid))
        return button

    def _build_header_actions(
        self, row: EpisodeGuideRow, above_fold_ids: tuple[str, ...]
    ) -> None:
        """Promote the collapsed row's inline-strip actions into a
        right-aligned column stacked directly under the status pill (mirrors
        the delegate's action column, geometry contract v2). Labels come from
        the frozen ``episode_row_actions`` map so the header and below-fold
        rows share a single label source."""
        if not above_fold_ids:
            return
        labels = dict(episode_row_actions(row))
        for action_id in above_fold_ids:
            button = self._make_action_button(action_id, labels.get(action_id, action_id))
            self._header_actions_column.addWidget(button)
            self._header_action_buttons.append(button)

    def _reset_content(self) -> None:
        self._action_buttons = []
        self._copy_buttons = []
        self._open_dir_buttons = []
        self._mux_optout_button = None
        self._header_action_buttons = []
        self._clear_layout(self._header_actions_column)
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

    def _build_labeled_path(self, label_text: str, path: str, *, open_dir: bool, note: str = "") -> None:
        row_widget = QWidget(self)
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(_scale.px(6))
        body = html.escape(path)
        if note:
            body = f"{body} <i>{html.escape(note)}</i>"
        label = QLabel(f"<b>{html.escape(label_text)}:</b> {body}")
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row_layout.addWidget(label, stretch=1)
        if open_dir:
            button = self._open_dir_button(os.path.dirname(path))
            row_layout.addWidget(button)
            self._open_dir_buttons.append(button)
        self._files_section.addWidget(row_widget)

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

    def _build_actions_row(
        self,
        actions: list[tuple[str, str]],
        *,
        above_fold_ids: tuple[str, ...] = (),
        state: ScanState | None = None,
        mux_plan: dict | None = None,
        preview_index: int | None = None,
    ) -> None:
        for action_id, label in actions:
            if action_id in above_fold_ids:
                continue    # already hosted in the header row
            button = self._make_action_button(action_id, label)
            self._actions_row.addWidget(button)
            self._action_buttons.append(button)

        self._maybe_add_optout_button(state, mux_plan, preview_index)
        self._actions_row.addStretch()

    def _maybe_add_optout_button(
        self, state: ScanState | None, mux_plan: dict | None, preview_index: int | None
    ) -> None:
        """Add the per-episode AutoMux opt-out toggle when this file has a
        cached action-bearing plan (or is already opted out, so it can be
        re-enabled). Session-scoped on ``state.mux_opt_outs`` -- no persistence."""
        if state is None or preview_index is None:
            return
        opted_out = preview_index in state.mux_opt_outs
        has_actions = bool(mux_plan) and plan_has_actions(mux_plan)
        if not (has_actions or opted_out):
            return
        label = (
            "Enable AutoMux for this episode"
            if opted_out
            else "Disable AutoMux for this episode"
        )
        button = QPushButton(label)
        button.setProperty("actionId", "mux_optout")
        button.setProperty("cssClass", "row-action")
        button.setProperty("tone", "caution")
        button.setFixedHeight(_scale.px(_PILL_HEIGHT_U))
        button.clicked.connect(lambda _checked=False: self.mux_optout_toggled.emit())
        self._actions_row.addWidget(button)
        self._mux_optout_button = button
