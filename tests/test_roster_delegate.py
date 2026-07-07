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
        from plex_renamer.gui_qt.widgets._roster_delegate import _CARD_GAP_U

        view, model, delegate = self._view([_make_state("A")])
        header_h = view.sizeHintForRow(0)
        state_h = view.sizeHintForRow(1)
        self.assertEqual(header_h, _scale.px(34))
        self.assertEqual(state_h, _scale.px(110) + 2 * _scale.px(_CARD_GAP_U))
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


class RosterPillRemovalTests(QtSmokeBase):
    """L2: the per-card status pill is redundant with the group header and
    must not be painted; L5: title wrapping must use the full body width."""

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

    def test_title_uses_full_body_width_no_pill_reservation(self):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QFontMetrics
        from PySide6.QtWidgets import QStyleOptionViewItem
        from plex_renamer.gui_qt.widgets._roster_model import ROW_DATA_ROLE

        state = _make_state("Aqua Teen Hunger Force Colon Movie Film")
        view, model, delegate = self._view([state])
        index = model.index(1, 0)
        row_data = index.data(ROW_DATA_ROLE)
        long_title = row_data.title
        self.assertIn("Aqua Teen Hunger Force Colon Movie Film", long_title)

        option = QStyleOptionViewItem()
        option.rect = view.visualRect(index)
        body = delegate._body_rect(option.rect)
        metrics = QFontMetrics(view.font())

        first_line, remainder = delegate._split_title(long_title, metrics, body.width())

        # With the pill gone, _split_title must be called with the *full*
        # body width, not a width narrowed by a reserved pill rect.
        pill_reserved_width = body.width() - _scale_px(80)  # any pill would shave off real width
        self.assertGreater(metrics.horizontalAdvance(first_line), 0)
        self.assertGreater(body.width(), pill_reserved_width)
        self.assertTrue(remainder)
        elided = metrics.elidedText(remainder, Qt.TextElideMode.ElideMiddle, body.width())
        self.assertLessEqual(metrics.horizontalAdvance(elided), body.width())

        # The delegate no longer exposes a pill-rect helper that would shrink
        # the title's available width.
        self.assertFalse(hasattr(delegate, "_pill_rect"))

    def test_pill_not_painted_top_right_corner_matches_background(self):
        """Render the row into a pixmap and inspect the top-right corner of
        the body area: it must match the plain row background, not a
        rounded-rect pill fill (which would create a distinct color blob
        confined to the corner, differing from the rest of the top edge).

        ``view.grab(rect)`` returns an image local to ``rect.topLeft()``, so
        geometry from ``delegate._body_rect()`` (viewport-space) must be
        translated by ``-rect.topLeft()`` before indexing pixels -- otherwise
        the sample point silently lands on an unrelated row (e.g. the
        confidence bar) and the test is meaningless.
        """
        from PySide6.QtGui import QFontMetrics
        from PySide6.QtWidgets import QStyleOptionViewItem

        state = _make_state("A Fully Ready Show")
        view, model, delegate = self._view([state])
        view.show()
        index = model.index(1, 0)
        rect = view.visualRect(index)

        pixmap = view.grab(rect)
        image = pixmap.toImage()
        self.assertFalse(image.isNull())

        body = delegate._body_rect(rect).translated(-rect.topLeft())
        metrics = QFontMetrics(view.font())
        line_height = metrics.lineSpacing()

        # Sample squarely within the first title line's vertical band (never
        # at row 0/1, which can catch antialiasing from the card's rounded
        # top edge): far right, where the pill used to sit, vs. a point on
        # the same row well inside the body (plain background, no pill).
        title_mid_y = min(body.y() + max(1, line_height // 2), image.height() - 1)
        corner_x = min(body.right() - 2, image.width() - 1)
        mid_x = max(body.x(), body.x() + body.width() // 3)

        corner_color = image.pixelColor(corner_x, title_mid_y)
        mid_color = image.pixelColor(mid_x, title_mid_y)

        self.assertEqual(
            corner_color.name(), mid_color.name(),
            "top-right corner of the title row differs from the rest of the "
            "row -- a pill (or other isolated fill) is still being painted",
        )
        view.close()


def _scale_px(n):
    from plex_renamer.gui_qt import _scale
    return _scale.px(n)


class RosterCardGapTests(QtSmokeBase):
    def _any_delegate(self):
        from plex_renamer.gui_qt.widgets._roster_delegate import RosterDelegate, RosterListView

        view = RosterListView()
        delegate = RosterDelegate(view, media_type="tv")
        return delegate

    def test_card_rect_inset_from_option_rect(self):
        from plex_renamer.gui_qt.widgets._roster_delegate import RosterDelegate, _CARD_GAP_U
        from plex_renamer.gui_qt._scale import px
        from PySide6.QtCore import QRect

        delegate = self._any_delegate()          # helper as in earlier classes
        option_rect = QRect(0, 0, 360, px(120))
        card = delegate._card_rect(option_rect)
        self.assertEqual(card.top(), option_rect.top() + px(_CARD_GAP_U))
        self.assertEqual(card.bottom(), option_rect.bottom() - px(_CARD_GAP_U))


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
