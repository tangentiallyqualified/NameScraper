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
