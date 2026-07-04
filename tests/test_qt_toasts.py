# tests/test_qt_toasts.py
"""Rebuilt toast card: clamp/expand, copy, sticky errors, hover pause (Plan 6)."""
from conftest_qt import QtSmokeBase

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

_LONG = "line one is quite long and wraps. " * 12
_SHORT = "All done."


def _make_card(**kwargs):
    from plex_renamer.gui_qt.widgets.toast_manager import _ToastCard

    defaults = dict(title="Title", message=_SHORT, tone="accent", duration_ms=None)
    defaults.update(kwargs)
    return _ToastCard(**defaults)


class ToastCardClampTests(QtSmokeBase):
    def _host(self, card, height=600):
        host = QWidget()
        host.resize(500, height)
        card.setParent(host)
        card.setFixedWidth(360)
        host.show()
        card.show()
        card.updateGeometry()
        self._app.processEvents()
        return host

    def test_short_message_has_no_show_more(self):
        card = _make_card(message=_SHORT)
        host = self._host(card)
        self.assertFalse(card._show_more_btn.isVisible())
        host.close()

    def test_long_message_clamps_to_three_lines_and_offers_show_more(self):
        card = _make_card(message=_LONG)
        host = self._host(card)
        self.assertTrue(card._show_more_btn.isVisible())
        line = card._message_label.fontMetrics().lineSpacing()
        self.assertLessEqual(card._body.height(), line * 3 + 8)
        self.assertEqual(card._show_more_btn.text(), "Show more")
        host.close()

    def test_expand_caps_at_forty_percent_of_window_and_scrolls(self):
        card = _make_card(message=_LONG * 6)
        host = self._host(card, height=400)
        card._show_more_btn.click()
        self._app.processEvents()
        self.assertTrue(card._expanded)
        self.assertLessEqual(card._body.height(), int(host.height() * 0.4) + 2)
        self.assertEqual(
            card._body.verticalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAsNeeded,
        )
        self.assertEqual(card._show_more_btn.text(), "Show less")
        host.close()

    def test_update_message_collapses_expansion(self):
        card = _make_card(message=_LONG)
        host = self._host(card)
        card.set_expanded(True)
        card.update_message(title="T2", message=_LONG)
        self.assertFalse(card._expanded)
        host.close()


class ToastCardStyleTests(QtSmokeBase):
    def test_card_has_no_inline_stylesheet(self):
        card = _make_card()
        self.assertEqual(card.styleSheet(), "")
        self.assertEqual(card._progress.styleSheet(), "")

    def test_unknown_tone_normalizes_to_accent(self):
        card = _make_card(tone="mystery")
        self.assertEqual(card.property("tone"), "accent")
        self.assertEqual(card._icon_label.property("tone"), "accent")

    def test_tone_icon_glyphs(self):
        for tone, glyph in (("success", "✓"), ("error", "!"), ("accent", "i")):
            card = _make_card(tone=tone)
            self.assertEqual(card._icon_label.text(), glyph)
