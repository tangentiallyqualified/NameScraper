# tests/test_scan_progress.py
"""Conveyor offset is a smooth function of elapsed time (LD1)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from conftest_qt import QtSmokeBase


def test_overall_fraction_blends_phase_and_items():
    from plex_renamer.gui_qt.widgets.scan_progress import overall_progress_fraction

    # phase 2 of 5 (index 1), halfway through its items
    assert overall_progress_fraction(5, 1, 5, 10, 1) == pytest.approx((1 + 0.5) / 5)


def test_overall_fraction_without_totals_uses_completed_phases():
    from plex_renamer.gui_qt.widgets.scan_progress import overall_progress_fraction

    assert overall_progress_fraction(5, 2, 0, 0, 2) == pytest.approx(2 / 5)


def test_overall_fraction_no_active_phase_uses_completed_ratio():
    from plex_renamer.gui_qt.widgets.scan_progress import overall_progress_fraction

    assert overall_progress_fraction(5, None, 0, 0, 5) == pytest.approx(1.0)


def test_overall_fraction_empty_checklist_is_zero():
    from plex_renamer.gui_qt.widgets.scan_progress import overall_progress_fraction

    assert overall_progress_fraction(0, None, 0, 0, 0) == 0.0


def test_overall_fraction_clamps_done_above_total():
    from plex_renamer.gui_qt.widgets.scan_progress import overall_progress_fraction

    assert overall_progress_fraction(2, 0, 999, 10, 0) == pytest.approx(0.5)


def test_stepper_widget_is_gone():
    import plex_renamer.gui_qt.widgets.scan_progress as mod

    assert not hasattr(mod, "_PhaseStepper")


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
    assert conveyor_offset(1200, slot_w=100, cycle_ms=1000) == conveyor_offset(
        200, slot_w=100, cycle_ms=1000
    )


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


class ConveyorDprPaintTests(QtSmokeBase):
    """DPR-aware paint: scaled pixmaps carry devicePixelRatio and are cached
    across paints instead of being rescaled every animation frame."""

    def _painted_animation(self, poster_size=(20, 30)):
        from PySide6.QtGui import QPixmap

        from plex_renamer.gui_qt.widgets.scan_progress import _ConveyorAnimation

        anim = _ConveyorAnimation()
        anim.resize(500, 200)
        anim.set_posters([QPixmap(*poster_size)])
        anim.set_active(True)
        anim.grab()  # forces paintEvent even offscreen/hidden
        return anim

    def test_paint_populates_scaled_cache_with_dpr_set(self):
        anim = self._painted_animation()
        self.assertEqual(len(anim._scaled_cache), 1)
        scaled = next(iter(anim._scaled_cache.values()))
        self.assertEqual(scaled.devicePixelRatio(), anim.devicePixelRatioF())

    def test_repainting_reuses_cached_scaled_pixmap(self):
        anim = self._painted_animation()
        cached = next(iter(anim._scaled_cache.values()))
        anim.grab()
        self.assertEqual(len(anim._scaled_cache), 1)
        self.assertIs(next(iter(anim._scaled_cache.values())), cached)

    def test_reset_posters_clears_scaled_cache(self):
        anim = self._painted_animation()
        self.assertEqual(len(anim._scaled_cache), 1)
        anim.reset_posters()
        self.assertEqual(len(anim._scaled_cache), 0)


class ConveyorPosterAssignmentTest(QtSmokeBase):
    def _pixmap(self, color):
        from PySide6.QtGui import QPixmap

        pm = QPixmap(10, 15)
        pm.fill(color)
        return pm

    def _animation(self):
        from plex_renamer.gui_qt.widgets.scan_progress import _ConveyorAnimation

        return _ConveyorAnimation()

    def test_card_gets_no_poster_if_none_loaded_at_crossing(self):
        from PySide6.QtCore import Qt

        anim = self._animation()
        # Card 3 crosses the beam with an empty pool: stays empty forever.
        self.assertIsNone(anim.poster_for_card(3, crossed=True))
        anim.add_poster(self._pixmap(Qt.red))
        self.assertIsNone(anim.poster_for_card(3, crossed=True))

    def test_posters_assigned_in_order_at_crossing_and_sticky(self):
        from PySide6.QtCore import Qt

        anim = self._animation()
        red = self._pixmap(Qt.red)
        blue = self._pixmap(Qt.blue)
        anim.add_poster(red)
        anim.add_poster(blue)
        first = anim.poster_for_card(1, crossed=True)
        second = anim.poster_for_card(2, crossed=True)
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertNotEqual(first.cacheKey(), second.cacheKey())
        # Re-querying never reshuffles.
        self.assertEqual(anim.poster_for_card(1, crossed=True).cacheKey(), first.cacheKey())

    def test_not_yet_crossed_card_has_no_poster(self):
        from PySide6.QtCore import Qt

        anim = self._animation()
        anim.add_poster(self._pixmap(Qt.red))
        self.assertIsNone(anim.poster_for_card(5, crossed=False))

    def test_set_posters_is_additive_by_cachekey(self):
        from PySide6.QtCore import Qt

        anim = self._animation()
        red = self._pixmap(Qt.red)
        anim.set_posters([red])
        anim.set_posters([red])  # repeated feed tick: no duplicate
        anim.poster_for_card(1, crossed=True)
        self.assertIsNone(anim.poster_for_card(2, crossed=True))  # pool exhausted


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

    def test_filler_rotation_wraps_with_fresh_shuffle(self):
        # Pins the exhausted-order reshuffle branch deterministically; left to
        # the rotation timer alone, its coverage depends on how long a scan
        # happens to run on the measuring machine.
        from plex_renamer.gui_qt.widgets.scan_progress import ScanProgressWidget

        w = ScanProgressWidget(media_type="tv")
        w.start()
        for _ in range(len(w._fillers)):
            w._rotate_filler()
        last_before_wrap = w._item_label.text()
        w._rotate_filler()
        self.assertEqual(w._filler_pos, 1)
        self.assertNotEqual(w._item_label.text(), last_before_wrap)
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
