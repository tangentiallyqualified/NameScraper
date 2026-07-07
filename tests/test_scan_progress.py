# tests/test_scan_progress.py
"""Conveyor offset is a smooth function of elapsed time (LD1)."""
from __future__ import annotations

from conftest_qt import QtSmokeBase


def test_offset_zero_at_start():
    from plex_renamer.gui_qt.widgets.scan_progress import conveyor_offset
    assert conveyor_offset(0, slot_w=100, cycle_ms=1000) == 0.0

def test_offset_monotonic_within_cycle():
    from plex_renamer.gui_qt.widgets.scan_progress import conveyor_offset
    a = conveyor_offset(200, slot_w=100, cycle_ms=1000)
    b = conveyor_offset(400, slot_w=100, cycle_ms=1000)
    assert 0 <= a < b < 100

def test_offset_wraps_at_cycle():
    from plex_renamer.gui_qt.widgets.scan_progress import conveyor_offset
    assert conveyor_offset(1000, slot_w=100, cycle_ms=1000) == 0.0
    assert conveyor_offset(1200, slot_w=100, cycle_ms=1000) == conveyor_offset(200, slot_w=100, cycle_ms=1000)


class ConveyorPosterTests(QtSmokeBase):
    def test_set_and_add_posters(self):
        from PySide6.QtGui import QPixmap
        from plex_renamer.gui_qt.widgets.scan_progress import ScanProgressWidget
        w = ScanProgressWidget(media_type="tv")
        w.set_posters([QPixmap(10, 14)])
        w.add_poster(QPixmap(10, 14))
        self.assertEqual(len(w._animation._posters), 2)

    def test_set_posters_filters_null_pixmaps(self):
        from PySide6.QtGui import QPixmap
        from plex_renamer.gui_qt.widgets.scan_progress import ScanProgressWidget
        w = ScanProgressWidget(media_type="tv")
        w.set_posters([QPixmap(10, 14), QPixmap(), None])
        self.assertEqual(len(w._animation._posters), 1)

    def test_add_poster_ignores_null_pixmap(self):
        from PySide6.QtGui import QPixmap
        from plex_renamer.gui_qt.widgets.scan_progress import ScanProgressWidget
        w = ScanProgressWidget(media_type="tv")
        w.add_poster(QPixmap())
        w.add_poster(None)
        self.assertEqual(len(w._animation._posters), 0)

    def test_start_clears_posters(self):
        from PySide6.QtGui import QPixmap
        from plex_renamer.gui_qt.widgets.scan_progress import ScanProgressWidget
        w = ScanProgressWidget(media_type="tv")
        w.set_posters([QPixmap(10, 14)])
        w.start()
        self.assertEqual(len(w._animation._posters), 0)
        w.stop()
