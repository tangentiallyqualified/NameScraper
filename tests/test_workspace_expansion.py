# tests/test_workspace_expansion.py
"""Header description follows the expanded episode (M10): the work panel's
header overview swaps to the expanded episode's overview/air-date and
reverts to the remembered series overview on collapse."""
from __future__ import annotations

from conftest_qt import QtSmokeBase


class HeaderFollowsEpisodeTests(QtSmokeBase):
    def _panel(self, media_type="tv"):
        from plex_renamer.gui_qt.widgets._work_panel import MediaWorkPanel

        panel = MediaWorkPanel(media_type=media_type)
        panel.resize(760, 640)
        return panel

    def test_episode_overview_swaps_and_restores(self):
        panel = self._panel(media_type="tv")
        panel._apply_overview_text("Series overview.", "tok")
        panel.set_episode_overview("Episode plot.", "2023-05-01")
        self.assertEqual(panel._overview_label.text(), "Episode plot.\nAir date: 2023-05-01")
        panel.clear_episode_overview()
        self.assertEqual(panel._overview_label.text(), "Series overview.")
