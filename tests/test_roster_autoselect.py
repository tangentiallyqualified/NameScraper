# tests/test_roster_autoselect.py
"""Roster auto-selects the topmost result after a fresh scan (L6)."""
from __future__ import annotations

from pathlib import Path

from conftest_qt import QtSmokeBase


def _make_state(name, *, queued=False):
    from plex_renamer.engine.models import ScanState
    state = ScanState(folder=Path(f"C:/lib/{name}"),
                      media_info={"id": hash(name) % 100000, "name": name,
                                  "year": "2020", "_media_type": "tv"})
    state.scanned = True
    state.queued = queued
    state.confidence = 0.9
    return state


class RosterAutoSelectTests(QtSmokeBase):
    def _panel(self):
        from plex_renamer.gui_qt.widgets._media_workspace_roster import MediaWorkspaceRosterPanel
        return MediaWorkspaceRosterPanel(media_type="tv")

    def test_first_state_row_skips_header(self):
        panel = self._panel()
        panel.sync_items([_make_state("Alpha"), _make_state("Beta")], collapsed_groups={})
        self.assertEqual(panel.model.entry_kind_at(panel.model.first_state_row()), "state")

    def test_fresh_sync_auto_selects_first_state_and_emits(self):
        panel = self._panel()
        emitted: list[int] = []
        panel.state_selected.connect(emitted.append)
        panel.sync_items([_make_state("Alpha"), _make_state("Beta")], collapsed_groups={})
        self.assertIsNotNone(panel.current_state_index())
        self.assertEqual(panel.current_state_index(),
                         panel.model.state_index_at(panel.model.first_state_row()))
        self.assertTrue(emitted)                     # work panel driven

    def test_existing_selection_is_preserved(self):
        panel = self._panel()
        states = [_make_state("Alpha"), _make_state("Beta")]
        panel.sync_items(states, collapsed_groups={})
        panel.set_current_state(1)
        panel.sync_items(states, collapsed_groups={})   # re-sync
        self.assertEqual(panel.current_state_index(), 1)
