# tests/test_roster_model.py
"""RosterModel row composition, roles, and dataChanged granularity."""
from __future__ import annotations

from pathlib import Path

from conftest_qt import QtSmokeBase


def _make_state(name: str, *, queued=False, checked=True):
    from plex_renamer.engine.models import ScanState

    state = ScanState(folder=Path(f"C:/lib/{name}"), media_info={"id": hash(name) % 100000, "name": name, "year": "2020"})
    state.scanned = True
    state.queued = queued
    state.checked = checked
    state.confidence = 0.9
    return state


class RosterModelTests(QtSmokeBase):
    def _model(self, states, collapsed=None):
        from plex_renamer.gui_qt.widgets._roster_model import RosterModel

        model = RosterModel(media_type="tv")
        model.set_states(states, collapsed_groups=collapsed or {})
        return model

    def test_header_and_state_rows_in_group_order(self):
        from plex_renamer.gui_qt.widgets import _roster_model as rm

        queued = _make_state("Queued Show", queued=True)
        matched = _make_state("Matched Show")
        model = self._model([matched, queued])
        # queued group renders before matched
        self.assertEqual(model.entry_kind_at(0), "header")
        self.assertEqual(model.group_at(0), "queued")
        self.assertIn("QUEUED (1)", model.index(0, 0).data())
        self.assertEqual(model.entry_kind_at(1), "state")
        self.assertEqual(model.state_index_at(1), 1)
        self.assertEqual(model.group_at(2), "matched")
        self.assertEqual(model.state_index_at(3), 0)
        self.assertEqual(model.rowCount(), 4)

    def test_collapsed_group_hides_state_rows_and_flips_arrow(self):
        matched = _make_state("Matched Show")
        model = self._model([matched], collapsed={"matched": True})
        self.assertEqual(model.rowCount(), 1)
        self.assertTrue(model.index(0, 0).data().startswith("▶"))
        self.assertEqual(model.row_for_state_index(0), -1)

    def test_compact_still_builds_season_chips(self):
        from plex_renamer.engine.models import CompletenessReport, SeasonCompleteness
        state = _make_state("Frieren")
        state.completeness = CompletenessReport(
            seasons={1: SeasonCompleteness(season=1, expected=10, matched=10, missing=[])},
            specials=None, total_expected=10, total_matched=10, total_missing=[])
        model = self._model([state])
        model.set_compact(True)
        from plex_renamer.gui_qt.widgets._roster_model import ROW_DATA_ROLE
        data = model.index(1, 0).data(ROW_DATA_ROLE)
        self.assertTrue(data.chips)          # chips present even in compact

    def test_row_data_snapshot_fields(self):
        from plex_renamer.gui_qt.widgets._roster_model import ROW_DATA_ROLE

        state = _make_state("Frieren")
        model = self._model([state])
        data = model.index(1, 0).data(ROW_DATA_ROLE)
        self.assertEqual(data.title, "Frieren (2020)")
        self.assertEqual(data.confidence_pct, 90)
        self.assertTrue(data.checked)
        self.assertEqual(data.chips, ())   # no completeness -> no chips

    def test_refresh_state_emits_single_row_datachanged(self):
        state = _make_state("Frieren")
        model = self._model([state])
        seen: list[tuple[int, int]] = []
        model.dataChanged.connect(lambda tl, br, roles=(): seen.append((tl.row(), br.row())))
        state.checked = False
        model.refresh_state(0)
        self.assertEqual(seen, [(1, 1)])
        from plex_renamer.gui_qt.widgets._roster_model import ROW_DATA_ROLE
        self.assertFalse(model.index(1, 0).data(ROW_DATA_ROLE).checked)

    def test_pending_poster_count_zero_without_provider(self):
        from plex_renamer.gui_qt.widgets._roster_model import RosterModel

        model = RosterModel(media_type="tv")
        self.assertEqual(model.pending_poster_count(), 0)

    def test_header_row_before(self):
        states = [_make_state("A"), _make_state("B")]
        model = self._model(states)
        self.assertEqual(model.header_row_before(2), 0)
        self.assertEqual(model.header_row_before(0), -1)

    def test_headers_not_selectable(self):
        from PySide6.QtCore import Qt

        model = self._model([_make_state("A")])
        self.assertFalse(model.flags(model.index(0, 0)) & Qt.ItemFlag.ItemIsSelectable)
        self.assertTrue(model.flags(model.index(1, 0)) & Qt.ItemFlag.ItemIsSelectable)

    def test_poster_role_transitions_after_fetch(self):
        from unittest.mock import patch

        from PIL import Image

        from plex_renamer.gui_qt.widgets import _roster_model as rm

        state = _make_state("Frieren")
        calls: list[tuple] = []

        class _Tmdb:
            def fetch_poster(self, show_id, *, media_type="tv", target_width=240):
                calls.append((show_id, media_type, target_width))
                return Image.new("RGB", (4, 6), (10, 20, 30))

        model = rm.RosterModel(media_type="tv", tmdb_provider=lambda: _Tmdb())
        with patch.object(rm, "_submit_bg", side_effect=lambda fn: fn()):
            model.set_states([state], collapsed_groups={})
        row = model.row_for_state_index(0)
        self.assertGreaterEqual(row, 0)
        pixmap = model.index(row, 0).data(rm.POSTER_ROLE)
        self.assertIsNotNone(pixmap)
        self.assertFalse(pixmap.isNull())
        self.assertEqual(len(calls), 1)

    def test_loaded_posters_returns_cached_pixmaps(self):
        from PySide6.QtGui import QPixmap

        model = self._model([_make_state("Frieren")])
        pixmap = QPixmap(10, 14)
        model._poster_cache[("tv", 1)] = pixmap
        loaded = model.loaded_posters()
        self.assertEqual(len(loaded), 1)
        self.assertIs(loaded[0], pixmap)
