"""BusyOverlay + busy_scope behavior (GUI V4 Plan 5, spec §7)."""

from conftest_qt import QtSmokeBase


class BusyOverlayTests(QtSmokeBase):
    def _host(self):
        from PySide6.QtWidgets import QWidget

        host = QWidget()
        host.resize(400, 300)
        host.show()
        self.addCleanup(host.close)
        return host

    def test_immediate_scope_shows_covering_host_and_removes(self):
        from plex_renamer.gui_qt.widgets.busy_overlay import BusyOverlay, busy_scope

        host = self._host()
        with busy_scope(host, "Applying…", immediate=True) as overlay:
            self.assertTrue(overlay.isVisible())
            self.assertEqual(overlay.geometry(), host.rect())
            self.assertEqual(overlay._label.text(), "Applying…")
        self.assertIsNone(host.findChild(BusyOverlay))

    def test_deferred_scope_stays_hidden_before_delay(self):
        from plex_renamer.gui_qt.widgets.busy_overlay import BusyOverlay, busy_scope

        host = self._host()
        with busy_scope(host, delay_ms=60_000) as overlay:
            self._app.processEvents()
            self.assertFalse(overlay.isVisible())
        self.assertIsNone(host.findChild(BusyOverlay))

    def test_deferred_scope_shows_once_delay_elapses(self):
        import time

        from PySide6.QtTest import QTest

        from plex_renamer.gui_qt.widgets.busy_overlay import busy_scope

        host = self._host()
        with busy_scope(host, delay_ms=1) as overlay:
            # Poll rather than a single fixed qWait: under machine load a
            # lone qWait(50) intermittently returns before the 1ms deferred
            # timer has fired (observed flake in full smoke runs).
            deadline = time.monotonic() + 5.0
            while not overlay.isVisible() and time.monotonic() < deadline:
                QTest.qWait(10)
            self.assertTrue(overlay.isVisible())

    def test_exception_inside_scope_still_removes_overlay(self):
        from plex_renamer.gui_qt.widgets.busy_overlay import BusyOverlay, busy_scope

        host = self._host()
        with self.assertRaises(RuntimeError), busy_scope(host, immediate=True):
            raise RuntimeError("boom")
        self.assertIsNone(host.findChild(BusyOverlay))

    def test_overlay_tracks_host_resize(self):
        from plex_renamer.gui_qt.widgets.busy_overlay import busy_scope

        host = self._host()
        with busy_scope(host, immediate=True) as overlay:
            host.resize(620, 480)
            self._app.processEvents()
            self.assertEqual(overlay.geometry(), host.rect())
