from __future__ import annotations

from conftest_qt import QtSmokeBase


class TabBadgeTests(QtSmokeBase):
    def test_triple_digit_count_sets_full_text(self):
        from plex_renamer.gui_qt.widgets.tab_badge import TabBadge

        badge = TabBadge()
        badge.set_count(128)
        self.assertEqual(badge.count_text(), "128")
        # sanity: the count label's size hint fits its text (no clip)
        label = badge._count_label
        self.assertGreaterEqual(
            label.sizeHint().width(),
            label.fontMetrics().horizontalAdvance("128"),
        )

    def test_tv_movie_badges_removed_queue_history_kept(self):
        from plex_renamer.gui_qt.main_window import MainWindow

        window = MainWindow()
        self.assertTrue(hasattr(window, "_queue_badge"))
        self.assertTrue(hasattr(window, "_history_badge"))
        self.assertFalse(hasattr(window, "_tv_badge"))
        self.assertFalse(hasattr(window, "_movie_badge"))
        window.close()
