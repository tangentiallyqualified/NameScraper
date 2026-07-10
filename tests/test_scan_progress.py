# tests/test_scan_progress.py
"""Conveyor offset is a smooth function of elapsed time (LD1)."""
from __future__ import annotations

from unittest.mock import patch

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


class AnimationTimerTests(QtSmokeBase):
    def test_animation_timer_runs_at_60fps(self):
        from plex_renamer.gui_qt.widgets.scan_progress import ScanProgressWidget
        widget = ScanProgressWidget(media_type="tv")
        self.assertEqual(widget._animation_timer.interval(), 16)


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


class FillerRotationTests(QtSmokeBase):
    def test_filler_rotation_covers_pool_before_repeating(self):
        from plex_renamer.gui_qt.widgets.scan_progress import ScanProgressWidget
        w = ScanProgressWidget(media_type="tv")
        w.start()
        seen = []
        for _ in range(len(w._fillers)):
            w._rotate_filler()
            seen.append(w._item_label.text())
        self.assertEqual(len(set(seen)), len(w._fillers))
        w.stop()

    def test_filler_order_is_shuffled_per_start(self):
        import plex_renamer.gui_qt.widgets.scan_progress as mod
        from plex_renamer.gui_qt.widgets.scan_progress import ScanProgressWidget

        calls = []
        original_sample = mod.random.sample

        def _tracking_sample(seq, k):
            calls.append(k)
            return original_sample(seq, k)

        with patch.object(mod.random, "sample", side_effect=_tracking_sample):
            w = ScanProgressWidget(media_type="tv")
            w.start()
            self.assertTrue(calls, "start() must reshuffle the filler order")
            w.stop()

    def test_update_progress_does_not_reset_filler_position(self):
        """Real progress updates must not rewind the filler rotation back to
        the start of the shuffled order (that was the 'repeats too often'
        bug): only the 4s quiet-window timer should restart."""
        from plex_renamer.gui_qt.widgets.scan_progress import ScanProgressWidget
        w = ScanProgressWidget(media_type="tv")
        w.start()
        w._rotate_filler()
        w._rotate_filler()
        pos_before = w._filler_pos
        self.assertGreater(pos_before, 0)
        w.update_progress(current_item="Some Show S01E01")
        self.assertEqual(w._filler_pos, pos_before)
        w.stop()
