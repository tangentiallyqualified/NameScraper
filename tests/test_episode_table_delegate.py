# tests/test_episode_table_delegate.py
"""EpisodeTableDelegate/View painting smoke, size hints, hit-testing."""
from __future__ import annotations

from conftest_qt import QtSmokeBase
from test_episode_table_model import _guide_state


class EpisodeTableDelegateTests(QtSmokeBase):
    def _view(self, state, guide):
        from plex_renamer.gui_qt.widgets._episode_table_delegate import (
            EpisodeTableDelegate, EpisodeTableView,
        )
        from plex_renamer.gui_qt.widgets._episode_table_model import EpisodeTableModel

        model = EpisodeTableModel(media_type="tv", guide_provider=lambda _s: guide)
        model.show_state(state, collapsed_sections=set())
        view = EpisodeTableView()
        delegate = EpisodeTableDelegate(view, media_type="tv")
        view.setModel(model)
        view.setItemDelegate(delegate)
        view.resize(700, 500)
        return view, model, delegate

    def test_size_hints_by_kind(self):
        from plex_renamer.gui_qt import _scale

        state, guide = _guide_state()
        view, model, delegate = self._view(state, guide)
        self.assertEqual(view.sizeHintForRow(0), _scale.px(30))     # section label
        self.assertEqual(view.sizeHintForRow(2), _scale.px(30))     # season header
        self.assertEqual(view.sizeHintForRow(3), _scale.px(68))     # episode w/ filename + subtitle line
        self.assertEqual(view.sizeHintForRow(4), _scale.px(52))     # episode w/ filename line only
        self.assertEqual(view.sizeHintForRow(5), _scale.px(34))     # ghost (no filename)

    def test_subtitle_row_is_taller_than_plain_row(self):
        from plex_renamer.gui_qt import _scale

        state, guide = _guide_state()
        view, model, delegate = self._view(state, guide)
        # row 3 ("One") has a subtitle companion -> triple-line height;
        # row 4 ("Two") has none -> double-line height.
        self.assertEqual(view.sizeHintForRow(3), _scale.px(68))
        self.assertEqual(view.sizeHintForRow(4), _scale.px(52))
        self.assertGreater(view.sizeHintForRow(3), view.sizeHintForRow(4))

    def test_render_grab(self):
        state, guide = _guide_state()
        view, model, delegate = self._view(state, guide)
        view.show()
        self.assertFalse(view.grab().toImage().isNull())
        view.close()

    def test_persistent_editor_parents_into_viewport(self):
        """An unparented editor is a detached top-level window: the row paints
        as a blank gap while the card floats at desktop coordinates."""
        from plex_renamer.gui_qt.widgets._episode_expansion import EpisodeExpansionCard

        state, guide = _guide_state()
        view, model, delegate = self._view(state, guide)
        view.show()

        def provider(index):
            card = EpisodeExpansionCard()
            card.show_episode(state, model.guide_row_at(index.row()))
            return card

        delegate.expansion_card_provider = provider
        model.set_expanded_row(3)
        view.openPersistentEditor(model.index(3, 0))
        card = view.indexWidget(model.index(3, 0))
        self.assertIsNotNone(card)
        self.assertFalse(card.isWindow())
        self.assertIs(card.window(), view.window())
        view.close()

    def test_chevron_click_emits_without_selection(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        state, guide = _guide_state()
        view, model, delegate = self._view(state, guide)
        view.show()
        hits: list[int] = []
        view.chevron_clicked.connect(lambda index: hits.append(index.row()))
        rect = view.visualRect(model.index(3, 0))
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, delegate.chevron_rect(rect).center())
        self.assertEqual(hits, [3])
        self.assertNotEqual(view.currentIndex().row(), 3)
        view.close()

    def test_header_click_emits_section_key(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        state, guide = _guide_state()
        view, model, delegate = self._view(state, guide)
        view.show()
        keys: list[str] = []
        view.header_clicked.connect(keys.append)
        rect = view.visualRect(model.index(2, 0))
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, rect.center())
        self.assertEqual(keys, ["episode-guide-season:1"])
        view.close()

    def test_enter_emits_expand_on_current_row(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        state, guide = _guide_state()
        view, model, delegate = self._view(state, guide)
        view.show()
        expanded: list[int] = []
        view.expand_key_pressed.connect(lambda index: expanded.append(index.row()))
        view.setCurrentIndex(model.index(3, 0))
        QTest.keyClick(view, Qt.Key.Key_Return)
        self.assertEqual(expanded, [3])
        view.close()

    def test_bulk_hint_click_emits_signal(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        state, guide = _guide_state()
        guide.rows[1].status = "Mapped"
        view, model, delegate = self._view(state, guide)
        model.set_filter_mode("problems")
        view.show()
        fired: list[bool] = []
        view.bulk_hint_clicked.connect(lambda: fired.append(True))
        rect = view.visualRect(model.index(0, 0))
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, rect.center())
        self.assertEqual(fired, [True])
        view.close()


class MovieRowFlatTests(QtSmokeBase):
    def test_movie_file_not_a_chevron_kind(self):
        from plex_renamer.gui_qt.widgets import _episode_table_delegate as d
        self.assertNotIn("movie-file", d._CHEVRON_KINDS)


class PillConfidenceTests(QtSmokeBase):
    def _delegate(self):
        from plex_renamer.gui_qt.widgets._episode_table_delegate import (
            EpisodeTableDelegate, EpisodeTableView,
        )
        view = EpisodeTableView()
        return EpisodeTableDelegate(view, media_type="tv")

    def _row(self, **kw):
        from plex_renamer.gui_qt.widgets._episode_table_model import EpisodeRowData
        base = dict(kind="episode", title="S01E01 · Pilot", status_text="Review",
                    status_tone="warning", confidence_pct=72)
        base.update(kw)
        return EpisodeRowData(**base)

    def test_review_pill_text_includes_percent(self):
        d = self._delegate()
        self.assertEqual(d.pill_text(self._row(confidence_pct=72)), "Review 72%")

    def test_matched_pill_text_includes_percent(self):
        d = self._delegate()
        self.assertEqual(
            d.pill_text(self._row(status_text="Matched", status_tone="success", confidence_pct=96)),
            "Matched 96%")

    def test_review_pill_tone_follows_band(self):
        d = self._delegate()
        self.assertEqual(d.pill_tone(self._row(confidence_pct=90)), "success")
        self.assertEqual(d.pill_tone(self._row(confidence_pct=60)), "warning")
        self.assertEqual(d.pill_tone(self._row(confidence_pct=30)), "error")

    def test_missing_file_pill_text_unchanged(self):
        d = self._delegate()
        r = self._row(status_text="Missing File", status_tone="muted", confidence_pct=None)
        self.assertEqual(d.pill_text(r), "Missing File")
        self.assertEqual(d.pill_tone(r), "muted")


class HelpEventTests(QtSmokeBase):
    def test_tooltip_only_when_elided(self):
        from plex_renamer.gui_qt.widgets._episode_table_delegate import EpisodeTableDelegate, EpisodeTableView
        view = EpisodeTableView()
        d = EpisodeTableDelegate(view, media_type="tv")
        # narrow width -> elided -> tooltip; wide width -> not elided -> no tooltip
        self.assertTrue(d._preview_is_truncated("A very long rename preview.mkv", width=20))
        self.assertFalse(d._preview_is_truncated("x.mkv", width=100000))

    def _view(self, state, guide, *, width=700):
        from plex_renamer.gui_qt.widgets._episode_table_delegate import (
            EpisodeTableDelegate, EpisodeTableView,
        )
        from plex_renamer.gui_qt.widgets._episode_table_model import EpisodeTableModel

        model = EpisodeTableModel(media_type="tv", guide_provider=lambda _s: guide)
        model.show_state(state, collapsed_sections=set())
        view = EpisodeTableView()
        delegate = EpisodeTableDelegate(view, media_type="tv")
        view.setModel(model)
        view.setItemDelegate(delegate)
        view.resize(width, 500)
        return view, model, delegate

    def _help_event_result(self, view, delegate, index):
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QHelpEvent
        from PySide6.QtWidgets import QStyleOptionViewItem

        rect = view.visualRect(index)
        option = QStyleOptionViewItem()
        option.rect = rect
        pos = rect.center()
        event = QHelpEvent(QEvent.Type.ToolTip, pos, view.viewport().mapToGlobal(pos))
        return delegate.helpEvent(event, view, option, index)

    def test_help_event_suppressed_when_row_expanded(self):
        from plex_renamer.gui_qt.widgets._episode_table_model import EXPANDED_ROLE

        # Same long tooltip + narrow view as the "shown when truncated" case
        # below: without the EXPANDED_ROLE guard this would also be
        # truncated and helpEvent would return True, so expansion is the
        # only thing this test can be asserting on.
        state, guide = _guide_state()
        guide.rows[1].target_rename = (
            "Show - S01E02 - A Very Long Episode Title That Cannot Possibly Fit.mkv"
        )
        view, model, delegate = self._view(state, guide, width=260)
        view.show()
        index = model.index(4, 0)
        model.set_expanded_row(4)
        self.assertTrue(index.data(EXPANDED_ROLE))
        handled = self._help_event_result(view, delegate, index)
        self.assertFalse(handled)
        view.close()

    def test_help_event_shown_when_collapsed_and_truncated(self):
        # Give row 4 ("Two") a long rename preview and a narrow view so the
        # computed available width can't fit it -> helpEvent must show it.
        state, guide = _guide_state()
        guide.rows[1].target_rename = (
            "Show - S01E02 - A Very Long Episode Title That Cannot Possibly Fit.mkv"
        )
        view, model, delegate = self._view(state, guide, width=260)
        view.show()
        index = model.index(4, 0)
        handled = self._help_event_result(view, delegate, index)
        self.assertTrue(handled)
        view.close()

    def test_help_event_hidden_when_collapsed_and_fitting(self):
        # Row 3 ("One") keeps its short default target_rename and the view
        # is wide, so the preview fits -> helpEvent must not show a tooltip.
        state, guide = _guide_state()
        view, model, delegate = self._view(state, guide, width=700)
        view.show()
        index = model.index(3, 0)
        handled = self._help_event_result(view, delegate, index)
        self.assertFalse(handled)


class InlineMissingActionTests(QtSmokeBase):
    def test_missing_row_reports_inline_action_rect(self):
        from plex_renamer.gui_qt.widgets._episode_table_delegate import EpisodeTableDelegate, EpisodeTableView
        from plex_renamer.gui_qt.widgets._episode_table_model import EpisodeRowData
        from PySide6.QtCore import QRect
        view = EpisodeTableView()
        d = EpisodeTableDelegate(view, media_type="tv")
        row = EpisodeRowData(kind="episode", title="S01E03", status_text="Missing File", status_tone="muted")
        rect = d.inline_action_rect(QRect(0, 0, 400, 34), row)
        self.assertTrue(rect.isValid() and rect.width() > 0)

    def test_non_missing_row_has_no_inline_action(self):
        from plex_renamer.gui_qt.widgets._episode_table_delegate import EpisodeTableDelegate, EpisodeTableView
        from plex_renamer.gui_qt.widgets._episode_table_model import EpisodeRowData
        from PySide6.QtCore import QRect
        view = EpisodeTableView()
        d = EpisodeTableDelegate(view, media_type="tv")
        row = EpisodeRowData(kind="episode", title="S01E01", status_text="Review", status_tone="warning")
        self.assertFalse(d.inline_action_rect(QRect(0, 0, 400, 34), row).isValid())
        view.close()
