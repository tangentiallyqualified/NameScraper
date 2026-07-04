# tests/test_work_panel.py
"""Work panel assembly: header, strip, toolbar rules, footer, scroll-to-season."""
from __future__ import annotations

from conftest_qt import QtSmokeBase
from test_episode_table_model import _guide_state


class WorkPanelTests(QtSmokeBase):
    def _panel(self, state, guide):
        from plex_renamer.gui_qt.widgets._work_panel import MediaWorkPanel

        panel = MediaWorkPanel(media_type="tv", guide_provider=lambda _s: guide)
        panel.resize(760, 640)
        panel.show_state(state, collapsed_sections=set(), folder_preview=None)
        return panel

    def test_header_title_and_strip_chips(self):
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        self.assertEqual(panel._title_label.text(), "Show (2020)")
        chip_texts = [b.text() for b in panel._strip_buttons]
        self.assertEqual(chip_texts, ["S1 2/3"])

    def test_toolbar_rules_review_present(self):
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        self.assertTrue(panel.approve_all_button.isVisible() or not panel.isVisible())
        panel.show()
        self.assertTrue(panel.approve_all_button.isVisible())   # guide has a Review row
        panel.close()

    def test_filter_and_search_signals(self):
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        modes: list[str] = []
        panel.filter_changed.connect(modes.append)
        panel.segmented_filter.setCurrentText("Problems")
        self.assertEqual(modes, ["problems"])
        searches: list[str] = []
        panel.search_changed.connect(searches.append)
        panel.search_box.setText("abc")
        self.assertEqual(searches, ["abc"])

    def test_footer_breakdown(self):
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        panel.update_footer()
        self.assertEqual(panel.summary_label.text(), "3 files · 2 mapped · 1 unmapped")

    def test_scroll_to_season_flashes_header(self):
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        panel.show()
        panel.scroll_to_season(1)
        header_row = panel.model.section_header_row("episode-guide-season:1")
        self.assertEqual(panel._delegate._flash_row_index, header_row)
        panel.close()

    def test_movie_mode_hides_tv_toolbar(self):
        from pathlib import Path
        from plex_renamer.engine.models import ScanState
        from plex_renamer.gui_qt.widgets._work_panel import MediaWorkPanel

        state = ScanState(folder=Path("C:/lib/Movie"), media_info={"id": 9, "title": "Movie", "year": "2021", "_media_type": "movie"})
        state.scanned = True
        panel = MediaWorkPanel(media_type="movie")
        panel.show_state(state, collapsed_sections=set(), folder_preview=None)
        panel.show()
        self.assertFalse(panel.segmented_filter.isVisible())
        self.assertFalse(panel.search_box.isVisible())
        self.assertIsNotNone(panel.master_check)   # shown/hidden by update_master_state (Task 5 wiring)
        self.assertEqual(len(panel._strip_buttons), 0)
        panel.close()
