# tests/test_bulk_assign_panel.py
"""BulkAssignPanel staging: assign-in-order, auto-map, drag pairs, apply payload."""
from __future__ import annotations

from pathlib import Path

from conftest_qt import QtSmokeBase


def _bulk_state(slots: int = 5, names: tuple[str, ...] = ("b.mkv", "a.mkv", "c.mkv")):
    from plex_renamer.app.services.episode_mapping_service import EpisodeMappingService
    from plex_renamer.engine import ScanState
    from plex_renamer.engine.episode_assignments import (
        ORIGIN_MANUAL, EpisodeAssignmentTable, EpisodeSlot,
    )

    table = EpisodeAssignmentTable()
    for episode in range(1, slots + 1):
        table.add_slot(EpisodeSlot(season=1, episode=episode, title=f"Ep {episode}"))
    for name in names:
        entry = table.add_file(Path(f"C:/lib/Show/{name}"))
        table.mark_unassigned(entry.file_id, "no episode parsed")
    claimed = table.add_file(Path("C:/lib/Show/claimed.mkv"))
    table.assign(claimed.file_id, 1, [2], origin=ORIGIN_MANUAL)   # E02 pre-claimed
    state = ScanState(folder=Path("C:/lib/Show"), media_info={"id": 5, "name": "Show", "year": "2020"})
    state.scanned = True
    state.assignments = table
    service = EpisodeMappingService()
    service.reproject(state)
    return state, service


class BulkAssignPanelTests(QtSmokeBase):
    def _panel(self):
        from plex_renamer.gui_qt.widgets._bulk_assign_panel import BulkAssignPanel

        state, service = _bulk_state()
        panel = BulkAssignPanel()
        panel.resize(900, 600)
        panel.show_state(state, service)
        return panel

    def test_files_sorted_and_searchable(self):
        panel = self._panel()
        model = panel._files_model
        names = [model.index(r, 0).data() for r in range(model.rowCount())]
        self.assertEqual(names, ["a.mkv", "b.mkv", "c.mkv"])
        panel._search_box.setText("b.m")
        self.assertEqual(panel._files_model.rowCount(), 1)
        panel._search_box.setText("")
        self.assertEqual(panel._files_model.rowCount(), 3)

    def test_assign_in_order_skips_claimed_and_unchecks(self):
        from PySide6.QtCore import Qt

        panel = self._panel()
        model = panel._files_model
        for row in range(2):  # check a.mkv + b.mkv
            model.setData(model.index(row, 0), Qt.CheckState.Checked.value,
                          Qt.ItemDataRole.CheckStateRole)
        panel._anchor_key = (1, 1)
        panel.assign_in_order()
        pairs = {(season, episode) for _fid, season, episode in panel.staged_pairs()}
        self.assertEqual(pairs, {(1, 1), (1, 3)})   # E02 claimed → skipped
        self.assertEqual(model.checked_file_ids(), [])

    def test_auto_map_remaining_fills_unclaimed_in_order(self):
        panel = self._panel()
        panel.auto_map_remaining()
        episodes = sorted(episode for _fid, _s, episode in panel.staged_pairs())
        self.assertEqual(episodes, [1, 3, 4])       # 3 files onto E01/E03/E04 (E02 claimed)
        self.assertEqual(len(panel.staged_pairs()), 3)

    def test_drop_stages_single_pair_and_rejects_claimed(self):
        panel = self._panel()
        file_id = panel._files_model.file_id_at(0)
        panel._handle_drop(file_id, (1, 4))
        self.assertIn((file_id, 1, 4), panel.staged_pairs())
        panel._handle_drop(file_id, (1, 2))          # claimed → ignored
        self.assertIn((file_id, 1, 4), panel.staged_pairs())
        self.assertEqual(len(panel.staged_pairs()), 1)

    def test_apply_emits_payload_and_reset_clears(self):
        panel = self._panel()
        panel.auto_map_remaining()
        fired: list[list] = []
        panel.apply_requested.connect(fired.append)
        self.assertTrue(panel._apply_button.isEnabled())
        panel._apply_button.click()
        self.assertEqual(len(fired), 1)
        self.assertEqual(len(fired[0]), 3)
        panel.reset_staging()
        self.assertEqual(panel.staged_pairs(), [])
        self.assertFalse(panel._apply_button.isEnabled())

    def test_slot_rows_show_claim_and_staged_markers(self):
        panel = self._panel()
        model = panel._slots_model
        claimed_row = model.row_for_key((1, 2))
        self.assertIn("claimed.mkv", model.index(claimed_row, 0).data())
        panel._handle_drop(panel._files_model.file_id_at(0), (1, 1))
        staged_row = panel._slots_model.row_for_key((1, 1))
        self.assertIn("→", panel._slots_model.index(staged_row, 0).data())
