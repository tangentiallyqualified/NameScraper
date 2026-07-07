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
        self.assertEqual(view.sizeHintForRow(3), _scale.px(52))     # episode w/ filename line
        self.assertEqual(view.sizeHintForRow(5), _scale.px(34))     # ghost (no filename)

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
