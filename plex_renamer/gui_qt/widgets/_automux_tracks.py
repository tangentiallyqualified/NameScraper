"""AutoMux tracks section (spec §8.1/§8.2): embedded-track keep/strip and
external-sub merge/rename controls rendered from a serialized MuxPlan.

Shared by the TV episode expansion card and the movie work panel. The
widget never mutates the plan it was given — edits emit ``plan_edited``
with a deep-copied dict whose ``user_modified`` flag is set (spec §5.1).
"""

from __future__ import annotations

import copy

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import _scale

_TYPE_LABEL = {"video": "VID", "audio": "AUD", "subtitles": "SUB"}

# Track lists past this many rows scroll instead of stretching the
# expansion card / movie work panel indefinitely (Task 8).
_MAX_VISIBLE_ROWS = 8
_ROW_H_U = 24


class _ElidedNoticeLabel(QLabel):
    """A QLabel whose ON-SCREEN text elides to whatever width the heading
    row actually gives it, re-computed from the original source string on
    every resize so widening later can recover characters an earlier narrow
    elision dropped (Task 7, spec §4). ``text()`` keeps QLabel's normal
    contract of returning what is actually rendered -- callers that need
    the un-elided source use the separately set-and-tracked tooltip
    (``AutoMuxTracksWidget._set_notice`` sets both from the same string)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("", parent)
        self._source_text = ""
        self.setWordWrap(False)
        self.setMinimumWidth(0)

    def setText(self, text: str) -> None:  # noqa: N802
        self._source_text = text
        self._sync_display_text()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._sync_display_text()

    def _sync_display_text(self) -> None:
        width = self.width()
        if width <= 0:
            # Not laid out yet -- resizeEvent re-elides once sized; showing
            # the full text meanwhile is harmless (never painted at 0 width).
            super().setText(self._source_text)
            return
        metrics = QFontMetrics(self.font())
        display = metrics.elidedText(self._source_text, Qt.TextElideMode.ElideRight, width)
        super().setText(display)


class AutoMuxTracksWidget(QFrame):
    plan_edited = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("cssClass", "automux-tracks")
        self._plan: dict | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, _scale.px(4), 0, _scale.px(4))
        layout.setSpacing(_scale.px(4))
        # Heading row (spec §4): the notice sits inline, right of "Tracks",
        # in its own row container -- not a separate bottom row -- elided to
        # whatever width remains and always carrying the full text as a
        # tooltip (set on every display-state call below).
        self._heading_row = QWidget()
        heading_layout = QHBoxLayout(self._heading_row)
        heading_layout.setContentsMargins(0, 0, 0, 0)
        heading_layout.setSpacing(_scale.px(6))
        self._heading = QLabel("Tracks")
        self._heading.setProperty("cssClass", "field-label")
        heading_layout.addWidget(self._heading)
        self._notice = _ElidedNoticeLabel()
        self._notice.setProperty("cssClass", "caption")
        self._notice.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        heading_layout.addWidget(self._notice, 1)
        layout.addWidget(self._heading_row)
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

    # ── Display states ────────────────────────────────────────────────

    def show_probing(self) -> None:
        self._plan = None
        self._clear_rows()
        self._set_notice("Reading tracks…")
        self.updateGeometry()

    def show_error(self, error: str) -> None:
        self._plan = None
        self._clear_rows()
        self._set_notice(
            f"Tracks unavailable — {error}. "
            "This file will be renamed without remuxing.")
        self.updateGeometry()

    def show_no_actions(self) -> None:
        self._plan = None
        self._clear_rows()
        self._set_notice("No AutoMux actions apply to this file.")
        self.updateGeometry()

    def show_plan(self, plan: dict, *, locked: bool = False) -> None:
        self._plan = copy.deepcopy(plan)
        self._clear_rows()
        self._set_notice("; ".join(plan.get("warnings", [])))
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

    # ── Fill mode ─────────────────────────────────────────────────────

    def set_fill_mode(self, fill: bool) -> None:
        """``fill=True`` (movie work panel host): lift the row list's 8-row
        max-height cap and let it expand vertically to fill whatever space
        the host gives it. ``fill=False`` (expansion card, the default):
        restore the normal 8-row cap (Task 8). The movie host calls this
        with ``True`` when installing a widget via
        ``MediaWorkPanel.set_automux_tracks`` (spec §4) -- the expansion
        card path never calls it, so cards keep the capped/scrollable
        behavior unconditionally. The mode is fully encoded in the scroll
        area's maximumHeight + size policy -- no separate flag is kept, and
        minimumSizeHint() stays bounded at the fixed 8-row cap regardless
        (see its docstring)."""
        policy = self._rows_scroll.sizePolicy()
        if fill:
            self._rows_scroll.setMaximumHeight(16777215)
            policy.setVerticalPolicy(QSizePolicy.Policy.Expanding)
        else:
            self._rows_scroll.setMaximumHeight(_scale.px(_MAX_VISIBLE_ROWS * _ROW_H_U))
            policy.setVerticalPolicy(QSizePolicy.Policy.Preferred)
        self._rows_scroll.setSizePolicy(policy)
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
        and clamp it to the scroll area's LIVE cap ourselves instead of
        trusting the scroll area's own sizeHint() -- in fill mode
        (set_fill_mode(True)) that cap is lifted, so the preferred size
        grows with content and the movie host's layout hands the widget
        the panel's free space."""
        return self._hint_with_rows_cap(self._rows_scroll.maximumHeight())

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        """Qt's default minimumSizeHint() forwards to
        ``layout().totalMinimumSize()``, which walks this widget's OWN
        internal layout independently of the sizeHint() override above --
        including ``_rows_scroll``, a QScrollArea whose default
        minimumSizeHint() is a roughly-constant, content-blind floor (frame
        + scrollbar chrome) unrelated to how many rows are actually shown.

        Any PARENT layout measuring this widget as a layout item (the
        expansion card's ``_files_section``, the movie panel's
        ``_automux_tracks_host``) computes
        ``widget.sizeHint().expandedTo(widget.minimumSizeHint())``
        (``QWidgetItem::sizeHint()``) -- so without this override, that
        content-blind floor silently wins over the correct, content-driven
        sizeHint() above whenever real content is smaller than it (probing
        placeholder, error/no-actions notice, or just a few tracks),
        reserving genuine dead whitespace in every host (Task 7, spec §4).

        The rows contribution here is clamped to the FIXED 8-row cap, not
        the scroll area's live maximumHeight: in fill mode the live cap is
        lifted, and a minimum that grows with track count would become an
        unshrinkable hard floor on the whole movie work panel (it sits
        directly in a non-collapsible QSplitter, which floors pane sizes
        at minimumSizeHint -- review finding, Task 7). Rows are scrollable
        in every mode, so shrinking below content is always safe. Outside
        fill mode the live cap IS the fixed cap, making this identical to
        sizeHint() -- which is what closes the whitespace gap above."""
        return self._hint_with_rows_cap(_scale.px(_MAX_VISIBLE_ROWS * _ROW_H_U))

    def _hint_with_rows_cap(self, rows_cap: int) -> QSize:
        base = super().sizeHint()
        margins = self.layout().contentsMargins()
        spacing = self.layout().spacing()
        rows_height = min(self._rows_host.sizeHint().height(), rows_cap)
        # The heading row (heading label + inline notice, spec §4) already
        # accounts for the notice's reserved height -- it's no longer a
        # separate bottom row, so there is no second notice contribution
        # to add here.
        total = margins.top() + margins.bottom() + self._heading_row.sizeHint().height() + spacing + rows_height
        return QSize(base.width(), total)

    # ── Internals ─────────────────────────────────────────────────────

    def _set_notice(self, text: str) -> None:
        """Set the inline notice's text and its tooltip to the FULL,
        un-elided text (spec §4) -- called from every display-state method
        above so a long probe error or warnings list is always fully
        readable on hover, even once the on-screen text elides."""
        self._notice.setText(text)
        self._notice.setToolTip(text)

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
