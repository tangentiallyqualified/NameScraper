# tests/test_roster_delegate.py
"""RosterDelegate geometry, painting smoke, and RosterListView hit-testing."""
from __future__ import annotations

from pathlib import Path

from conftest_qt import QtSmokeBase


def _scale_spacing():
    from plex_renamer.gui_qt import _scale
    return _scale.px(4)   # _CHIP_SPACING_UNITS


def _make_state(name: str):
    from plex_renamer.engine.models import ScanState

    state = ScanState(folder=Path(f"C:/lib/{name}"), media_info={"id": 7, "name": name, "year": "2020"})
    state.scanned = True
    state.confidence = 0.9
    return state


class RosterDelegateTests(QtSmokeBase):
    def _view(self, states, collapsed=None):
        from plex_renamer.gui_qt.widgets._roster_delegate import RosterDelegate, RosterListView
        from plex_renamer.gui_qt.widgets._roster_model import RosterModel

        model = RosterModel(media_type="tv")
        model.set_states(states, collapsed_groups=collapsed or {})
        view = RosterListView()
        delegate = RosterDelegate(view, media_type="tv")
        view.setModel(model)
        view.setItemDelegate(delegate)
        view.resize(380, 600)
        return view, model, delegate

    def test_size_hints_differ_by_kind_and_mode(self):
        from plex_renamer.gui_qt import _scale

        view, model, delegate = self._view([_make_state("A")])
        header_h = view.sizeHintForRow(0)
        state_h = view.sizeHintForRow(1)
        self.assertEqual(header_h, _scale.px(34))
        self.assertEqual(state_h, _scale.px(110))
        delegate.set_compact(True)
        model.set_compact(True)
        self.assertEqual(view.sizeHintForRow(1), _scale.px(56))

    def test_render_grab_produces_pixels(self):
        view, model, delegate = self._view([_make_state("A")])
        view.show()
        pixmap = view.grab()
        self.assertFalse(pixmap.toImage().isNull())
        view.close()

    def test_toggle_click_emits_without_moving_selection(self):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        from plex_renamer.gui_qt.widgets._roster_model import ROW_DATA_ROLE

        view, model, delegate = self._view([_make_state("A")])
        view.show()
        toggled: list[int] = []
        view.toggle_clicked.connect(lambda index: toggled.append(index.row()))
        index = model.index(1, 0)
        rect = view.visualRect(index)
        row_data = index.data(ROW_DATA_ROLE)
        target = delegate.toggle_rect(rect, row_data).center()
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, target)
        self.assertEqual(toggled, [1])
        self.assertNotEqual(view.currentIndex().row(), 1)
        view.close()

    def test_header_click_emits_group(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        view, model, delegate = self._view([_make_state("A")])
        view.show()
        groups: list[str] = []
        view.header_clicked.connect(groups.append)
        rect = view.visualRect(model.index(0, 0))
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, rect.center())
        self.assertEqual(groups, ["matched"])
        view.close()

    def test_chip_tooltip_hit_rects_match_painted_chips(self):
        from unittest.mock import patch

        from PySide6.QtCore import QEvent, QPoint
        from PySide6.QtWidgets import QStyleOptionViewItem, QToolTip
        from PySide6.QtGui import QHelpEvent
        from PySide6.QtGui import QFontMetrics
        from plex_renamer.engine.models import CompletenessReport, SeasonCompleteness
        from plex_renamer.gui_qt import _scale
        from plex_renamer.gui_qt.widgets._roster_delegate import _CONF_BLOCK_U, _CHIP_TOP_GAP_U
        from plex_renamer.gui_qt.widgets._roster_model import ROW_DATA_ROLE
        from plex_renamer.gui_qt.widgets.status_chip import (
            chip_font_metrics,
            chip_rects_wrapped,
        )

        state = _make_state("A")
        seasons = {
            n: SeasonCompleteness(season=n, expected=100, matched=99, missing=[(50, "Ep")])
            for n in (111, 112, 113)
        }
        state.completeness = CompletenessReport(
            seasons=seasons, specials=None,
            total_expected=300, total_matched=297, total_missing=[],
        )
        view, model, delegate = self._view([state])
        view.show()
        index = model.index(1, 0)
        row_data = index.data(ROW_DATA_ROLE)
        self.assertEqual(len(row_data.chips), 3)

        option = QStyleOptionViewItem()
        option.rect = view.visualRect(index)
        body = delegate._body_rect(option.rect)
        line_height = QFontMetrics(view.font()).lineSpacing()
        confidence_y = body.y() + 2 * line_height + _scale.px(4)
        chip_y = confidence_y + _scale.px(_CONF_BLOCK_U) + _scale.px(_CHIP_TOP_GAP_U)
        painted = chip_rects_wrapped(body.x(), chip_y, row_data.chips, chip_font_metrics(), body.width())
        probe = QPoint(painted[2].left() + 1, painted[2].center().y())

        shown: list[str] = []
        with patch.object(
            QToolTip, "showText",
            side_effect=lambda _pos, text, *_args: shown.append(text),
        ):
            event = QHelpEvent(QEvent.Type.ToolTip, probe, view.viewport().mapToGlobal(probe))
            handled = delegate.helpEvent(event, view, option, index)
        self.assertTrue(handled)
        self.assertEqual(shown, [row_data.chips[2].tooltip])
        view.close()


class ChipWrapTests(QtSmokeBase):
    def _chips(self, n):
        from plex_renamer.gui_qt.widgets.status_chip import ChipSpec
        return [ChipSpec(f"S{i} 9/10", "warning", "") for i in range(1, n + 1)]

    def test_chips_wrap_to_multiple_rows_when_narrow(self):
        from plex_renamer.gui_qt.widgets.status_chip import (
            chip_font_metrics, chip_rects_wrapped, chip_row_height,
        )
        chips = self._chips(6)
        metrics = chip_font_metrics()
        one_chip_w = metrics.horizontalAdvance("S1 9/10") + 40
        rects = chip_rects_wrapped(0, 0, chips, metrics, max_width=one_chip_w)
        tops = sorted({r.top() for r in rects})
        self.assertGreater(len(tops), 1)                 # wrapped
        self.assertEqual(tops[1] - tops[0], chip_row_height() + _scale_spacing())
        # every chip fits within max_width
        self.assertTrue(all(r.right() <= one_chip_w for r in rects))

    def test_single_row_when_wide(self):
        from plex_renamer.gui_qt.widgets.status_chip import (
            chip_font_metrics, chip_rects_wrapped,
        )
        chips = self._chips(3)
        metrics = chip_font_metrics()
        rects = chip_rects_wrapped(0, 0, chips, metrics, max_width=100000)
        self.assertEqual(len({r.top() for r in rects}), 1)

    def test_wrapped_height_grows_with_rows(self):
        from plex_renamer.gui_qt.widgets.status_chip import (
            chip_font_metrics, chip_wrapped_height,
        )
        metrics = chip_font_metrics()
        narrow = chip_wrapped_height(self._chips(6), metrics, max_width=
                                     metrics.horizontalAdvance("S1 9/10") + 40)
        wide = chip_wrapped_height(self._chips(6), metrics, max_width=100000)
        self.assertGreater(narrow, wide)


class RosterSizeHintTests(QtSmokeBase):
    def _state_with_seasons(self, n_seasons):
        from pathlib import Path
        from plex_renamer.engine.models import (
            ScanState, CompletenessReport, SeasonCompleteness,
        )
        state = ScanState(folder=Path("C:/lib/Big Show"),
                          media_info={"id": 1, "name": "Big Show", "year": "2020",
                                      "_media_type": "tv"})
        state.scanned = True
        state.confidence = 0.9
        seasons = {i: SeasonCompleteness(season=i, expected=10, matched=9,
                                         missing=[(1, "Ep 1")]) for i in range(1, n_seasons + 1)}
        state.completeness = CompletenessReport(
            seasons=seasons, specials=None,
            total_expected=10 * n_seasons, total_matched=9 * n_seasons, total_missing=[])
        return state

    def _card_height(self, state):
        from plex_renamer.gui_qt.widgets._roster_delegate import RosterDelegate, RosterListView
        from plex_renamer.gui_qt.widgets._roster_model import RosterModel
        from PySide6.QtWidgets import QStyleOptionViewItem

        model = RosterModel(media_type="tv")
        model.set_states([state], collapsed_groups={})
        view = RosterListView()
        view.setModel(model)
        delegate = RosterDelegate(view, media_type="tv")
        view.setItemDelegate(delegate)
        view.resize(360, 800)
        index = model.index(1, 0)
        option = QStyleOptionViewItem()
        option.rect = view.visualRect(index)
        return delegate.sizeHint(option, index).height()

    def test_many_seasons_grows_card_height(self):
        from plex_renamer.gui_qt._scale import px
        from plex_renamer.gui_qt.widgets._roster_delegate import _ROW_NORMAL_U
        tall = self._card_height(self._state_with_seasons(12))
        base = self._card_height(self._state_with_seasons(1))
        self.assertGreaterEqual(base, px(_ROW_NORMAL_U) - 1)
        self.assertGreater(tall, base)
