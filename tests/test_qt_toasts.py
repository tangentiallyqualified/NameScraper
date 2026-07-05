# tests/test_qt_toasts.py
"""Rebuilt toast card: clamp/expand, copy, sticky errors, hover pause (Plan 6)."""
import shiboken6
from conftest_qt import QtSmokeBase

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

_LONG = "line one is quite long and wraps. " * 12
_SHORT = "All done."

_CARDS: list = []


def _make_card(**kwargs):
    from plex_renamer.gui_qt.widgets.toast_manager import _ToastCard

    defaults = dict(title="Title", message=_SHORT, tone="accent", duration_ms=None)
    defaults.update(kwargs)
    card = _ToastCard(**defaults)
    _CARDS.append(card)
    return card


class _ToastCardTestBase(QtSmokeBase):
    """Destroy every created card before the next test.

    Parentless cards keep live countdown QTimers; left alone they tick on
    whenever a later test pumps the event loop (self-dismissal mid-test) and
    linger as top-level widgets until interpreter-shutdown GC.
    """

    def tearDown(self):
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QApplication

        while _CARDS:
            card = _CARDS.pop()
            if not shiboken6.isValid(card):
                continue
            timer = getattr(card, "_timer", None)
            if timer is not None and shiboken6.isValid(timer):
                timer.stop()
            card.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        super().tearDown()


class ToastCardClampTests(_ToastCardTestBase):
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


class ToastCardStyleTests(_ToastCardTestBase):
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

    def test_toast_card_sizing_routes_through_scale(self):
        from pathlib import Path

        source = Path("plex_renamer/gui_qt/widgets/toast_manager.py").read_text(encoding="utf-8")
        self.assertNotIn("setFixedHeight(3)", source)
        self.assertIn("setFixedHeight(_scale.px(3))", source)
        self.assertIn("+ _scale.px(4)", source)


class ToastCardBehaviorTests(_ToastCardTestBase):
    def test_copy_puts_title_and_full_message_on_clipboard(self):
        from PySide6.QtWidgets import QApplication

        card = _make_card(title="Job failed", message=_LONG)
        card._copy_btn.click()
        self.assertEqual(QApplication.clipboard().text(), "Job failed\n" + _LONG)

    def test_error_tone_defaults_sticky(self):
        card = _make_card(tone="error", duration_ms=None)
        self.assertIsNone(getattr(card, "_timer", None))
        self.assertFalse(card._progress.isVisibleTo(card))

    def test_non_error_tone_defaults_to_countdown(self):
        card = _make_card(tone="success", duration_ms=None)
        self.assertIsNotNone(getattr(card, "_timer", None))
        self.assertEqual(card._duration_ms, 3000)

    def test_explicit_duration_wins_over_tone_default(self):
        card = _make_card(tone="error", duration_ms=1500)
        self.assertEqual(card._duration_ms, 1500)

    def test_hover_pauses_and_resumes_countdown(self):
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QEnterEvent
        from PySide6.QtCore import QPointF

        card = _make_card(tone="success", duration_ms=5000)
        self.assertTrue(card._timer.isActive())
        enter = QEnterEvent(QPointF(1, 1), QPointF(1, 1), QPointF(1, 1))
        card.enterEvent(enter)
        self.assertFalse(card._timer.isActive())
        remaining = card._remaining_ms
        card.leaveEvent(QEvent(QEvent.Type.Leave))
        self.assertTrue(card._timer.isActive())
        self.assertEqual(card._remaining_ms, remaining)


class ToastManagerDefaultTests(_ToastCardTestBase):
    def test_manager_error_toast_defaults_sticky(self):
        from plex_renamer.gui_qt.widgets.toast_manager import ToastManager

        host = QWidget()
        host.resize(800, 600)
        manager = ToastManager(host)
        host.show()
        manager.show_toast(title="Boom", message="bad", tone="error")
        card = manager._toast_widgets()[0]
        self.assertEqual(card._duration_ms, 0)
        host.close()
