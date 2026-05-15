"""Unit tests for the gui_qt scaling helper."""
from __future__ import annotations

import importlib.util
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@unittest.skipUnless(importlib.util.find_spec("PySide6"), "PySide6 is not installed")
class ScaleHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def test_px_is_linear_in_input(self):
        from plex_renamer.gui_qt import _scale

        eight = _scale.px(8)
        sixteen = _scale.px(16)
        self.assertGreater(eight, 0)
        self.assertEqual(sixteen, eight * 2)

    def test_px_zero_returns_zero(self):
        from plex_renamer.gui_qt import _scale

        self.assertEqual(_scale.px(0), 0)

    def test_px_negative_propagates_sign(self):
        from plex_renamer.gui_qt import _scale

        self.assertEqual(_scale.px(-8), -_scale.px(8))

    def test_row_height_uses_font_metrics(self):
        from PySide6.QtGui import QFont, QFontMetrics
        from plex_renamer.gui_qt import _scale

        expected_single = QFontMetrics(QFont()).lineSpacing()
        self.assertGreaterEqual(_scale.row_height(rows=1, padding=0), expected_single)
        self.assertEqual(
            _scale.row_height(rows=2, padding=0),
            _scale.row_height(rows=1, padding=0) * 2,
        )

    def test_row_height_padding_adds(self):
        from plex_renamer.gui_qt import _scale

        bare = _scale.row_height(rows=1, padding=0)
        padded = _scale.row_height(rows=1, padding=8)
        self.assertEqual(padded, bare + _scale.px(8))

    def test_icon_tokens_return_qsize(self):
        from PySide6.QtCore import QSize
        from plex_renamer.gui_qt import _scale

        for token in ("sm", "md", "lg", "xl"):
            size = _scale.icon(token)
            self.assertIsInstance(size, QSize)
            self.assertGreater(size.width(), 0)
            self.assertEqual(size.width(), size.height())

    def test_icon_lg_is_larger_than_sm(self):
        from plex_renamer.gui_qt import _scale

        self.assertGreater(_scale.icon("lg").width(), _scale.icon("sm").width())

    def test_icon_unknown_token_raises(self):
        from plex_renamer.gui_qt import _scale

        with self.assertRaises(KeyError):
            _scale.icon("titanic")

    def test_margins_scales_each_value(self):
        from PySide6.QtCore import QMargins
        from plex_renamer.gui_qt import _scale

        m = _scale.margins(8, 12, 8, 12)
        self.assertIsInstance(m, QMargins)
        self.assertEqual(m.left(), _scale.px(8))
        self.assertEqual(m.top(), _scale.px(12))
        self.assertEqual(m.right(), _scale.px(8))
        self.assertEqual(m.bottom(), _scale.px(12))

    def test_margins_single_value_uniform(self):
        from plex_renamer.gui_qt import _scale

        m = _scale.margins(8)
        self.assertEqual(m.left(), m.top())
        self.assertEqual(m.top(), m.right())
        self.assertEqual(m.right(), m.bottom())
        self.assertEqual(m.left(), _scale.px(8))


if __name__ == "__main__":
    unittest.main()
