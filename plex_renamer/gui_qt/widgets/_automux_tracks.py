"""AutoMux tracks section (spec §8.1/§8.2): embedded-track keep/strip and
external-sub merge/rename controls rendered from a serialized MuxPlan.

Shared by the TV episode expansion card and the movie work panel. The
widget never mutates the plan it was given — edits emit ``plan_edited``
with a deep-copied dict whose ``user_modified`` flag is set (spec §5.1).
"""

from __future__ import annotations

import copy

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .. import _scale

_TYPE_LABEL = {"video": "VID", "audio": "AUD", "subtitles": "SUB"}

# Track lists past this many rows scroll instead of stretching the
# expansion card / movie work panel indefinitely (Task 8).
_MAX_VISIBLE_ROWS = 8
_ROW_H_U = 24


class AutoMuxTracksWidget(QFrame):
    plan_edited = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("cssClass", "automux-tracks")
        self._plan: dict | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, _scale.px(4), 0, _scale.px(4))
        layout.setSpacing(_scale.px(4))
        self._heading = QLabel("Tracks")
        self._heading.setProperty("cssClass", "field-label")
        layout.addWidget(self._heading)
        self._rows_host = QWidget()
        self._rows = QVBoxLayout(self._rows_host)
        self._rows.setContentsMargins(0, 0, 0, 0)
        self._rows.setSpacing(_scale.px(2))
        self._rows_scroll = QScrollArea()
        self._rows_scroll.setWidgetResizable(True)
        self._rows_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._rows_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._rows_scroll.setWidget(self._rows_host)
        self._rows_scroll.setMaximumHeight(_scale.px(_MAX_VISIBLE_ROWS * _ROW_H_U))
        layout.addWidget(self._rows_scroll)
        self._notice = QLabel("")
        self._notice.setProperty("cssClass", "caption")
        self._notice.setWordWrap(True)
        layout.addWidget(self._notice)

    # ── Display states ────────────────────────────────────────────────

    def show_probing(self) -> None:
        self._plan = None
        self._clear_rows()
        self._notice.setText("Reading tracks…")
        self.updateGeometry()

    def show_error(self, error: str) -> None:
        self._plan = None
        self._clear_rows()
        self._notice.setText(
            f"Tracks unavailable — {error}. "
            "This file will be renamed without remuxing.")
        self.updateGeometry()

    def show_no_actions(self) -> None:
        self._plan = None
        self._clear_rows()
        self._notice.setText("No AutoMux actions apply to this file.")
        self.updateGeometry()

    def show_plan(self, plan: dict, *, locked: bool = False) -> None:
        self._plan = copy.deepcopy(plan)
        self._clear_rows()
        self._notice.setText("; ".join(plan.get("warnings", [])))
        for pos, decision in enumerate(self._plan.get("track_decisions", [])):
            box = QCheckBox(self._embedded_label(decision))
            box.setChecked(bool(decision["keep"]))
            box.setEnabled(decision["track_type"] != "video" and not locked)
            box.setMinimumHeight(_scale.px(20))
            box.toggled.connect(
                lambda checked, p=pos, b=box: self._on_embedded_toggled(p, checked, b))
            self._rows.addWidget(box)
            # A widget added to an already-visible ancestor (this card is a
            # persistent editor, already shown, when a late plan repopulates
            # it) stays invisible until Qt processes a posted show/polish
            # event -- and QBoxLayout::sizeHint() treats an invisible item as
            # empty (contributes 0), so every ancestor sizeHint() up through
            # this widget's own override, _files_section, and the card's
            # outer layout reports a stale (pre-populate) size for one whole
            # event-loop pass. Showing each row synchronously as it is added
            # closes that gap (Task 4, round6): the row-below-target
            # framing test caught this as a real, event-loop-pass-wide
            # viewport snap.
            box.show()
        for pos, merge in enumerate(self._plan.get("subtitle_merges", [])):
            box = QCheckBox(self._merge_label(merge))
            box.setChecked(merge["action"] == "merge")
            box.setEnabled(not locked)
            box.setMinimumHeight(_scale.px(20))
            box.toggled.connect(
                lambda checked, p=pos: self._on_merge_toggled(p, checked))
            self._rows.addWidget(box)
            box.show()  # see the comment above -- same visibility/sizeHint gap
        self.updateGeometry()

    # ── Sizing ────────────────────────────────────────────────────────

    def sizeHint(self) -> QSize:  # noqa: N802
        """QScrollArea.sizeHint() caches its contents widget's ideal size
        the first time it is queried and never invalidates that cache on
        its own (a long-standing Qt quirk) -- once this widget is measured
        while probing (rows_host near-empty), a later many-track
        show_plan() would silently keep reporting the old, small height,
        defeating notify_expanded_row_changed's whole point (Task 8). Read
        the row-list contribution straight from rows_host (always fresh)
        and clamp it to the scroll area's cap ourselves instead of
        trusting the scroll area's own sizeHint()."""
        base = super().sizeHint()
        margins = self.layout().contentsMargins()
        spacing = self.layout().spacing()
        rows_height = min(self._rows_host.sizeHint().height(), self._rows_scroll.maximumHeight())
        total = margins.top() + margins.bottom() + self._heading.sizeHint().height() + spacing + rows_height
        # The notice label sits unconditionally in the layout: even with
        # empty text a QLabel reports a non-zero sizeHint and the layout
        # reserves that space, so always account for it. Gating on
        # self._notice.text() under-reported the hint in the common
        # no-warnings case and squeezed the scroll viewport below the
        # intended 8-row cap.
        total += spacing + self._notice.sizeHint().height()
        return QSize(base.width(), total)

    # ── Internals ─────────────────────────────────────────────────────

    def _clear_rows(self) -> None:
        while self._rows.count():
            item = self._rows.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # Keep the C++ parent while the DeferredDelete is pending:
                # setParent(None) hands ownership to Python, and a GC pass
                # before the event loop runs then double-frees the widget
                # (0xc0000374 heap corruption in offscreen test runs).
                widget.hide()
                widget.deleteLater()

    @staticmethod
    def _embedded_label(decision: dict) -> str:
        parts = [
            _TYPE_LABEL.get(decision["track_type"], "?"),
            decision.get("language", ""),
            decision.get("codec", ""),
            decision.get("name", ""),
        ]
        return " · ".join(str(part) for part in parts if part)

    @staticmethod
    def _merge_label(merge: dict) -> str:
        name = merge["source_relative"].replace("\\", "/").rsplit("/", 1)[-1]
        return f"Merge {name} ({merge['language']})"

    def _on_embedded_toggled(self, pos: int, checked: bool, box: QCheckBox) -> None:
        if self._plan is None:
            return
        decision = self._plan["track_decisions"][pos]
        if decision["track_type"] == "audio" and not checked:
            kept_audio = sum(
                1 for d in self._plan["track_decisions"]
                if d["track_type"] == "audio" and d["keep"])
            if kept_audio <= 1:
                # Safety floor (spec §3.2): never strip the last audio track.
                box.blockSignals(True)
                box.setChecked(True)
                box.blockSignals(False)
                return
        decision["keep"] = checked
        self._emit_edited()

    def _on_merge_toggled(self, pos: int, checked: bool) -> None:
        if self._plan is None:
            return
        self._plan["subtitle_merges"][pos]["action"] = (
            "merge" if checked else "rename")
        self._emit_edited()

    def _emit_edited(self) -> None:
        self._plan["user_modified"] = True
        self.plan_edited.emit(copy.deepcopy(self._plan))
