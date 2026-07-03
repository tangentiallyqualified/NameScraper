# tests/test_roster_delegate.py
"""RosterDelegate geometry, painting smoke, and RosterListView hit-testing."""
from __future__ import annotations

from pathlib import Path

from conftest_qt import QtSmokeBase


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
