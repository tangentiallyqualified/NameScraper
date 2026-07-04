# tests/test_episode_table_model.py
"""EpisodeTableModel row composition, filters, search, expansion."""
from __future__ import annotations

from pathlib import Path

from conftest_qt import QtSmokeBase


def _guide_state():
    """Synthetic TV state with a real assignment table + completeness."""
    from plex_renamer.engine.models import (
        CompletenessReport, ScanState, SeasonCompleteness,
    )
    from plex_renamer.app.models.state_models import (
        EpisodeGuide, EpisodeGuideRow, EpisodeGuideSummary, UnmappedFileRow,
    )
    from plex_renamer.engine.models import PreviewItem

    state = ScanState(folder=Path("C:/lib/Show"), media_info={"id": 7, "name": "Show", "year": "2020"})
    state.scanned = True
    p1 = PreviewItem(original=Path("C:/lib/Show/s01e01.mkv"), new_name="Show - S01E01 - One.mkv",
                     target_dir=None, season=1, episodes=[1], status="OK")
    p2 = PreviewItem(original=Path("C:/lib/Show/s01e02.mkv"), new_name="Show - S01E02 - Two.mkv",
                     target_dir=None, season=1, episodes=[2], status="REVIEW: episode confidence below threshold")
    state.preview_items = [p1, p2]
    state.completeness = CompletenessReport(
        seasons={1: SeasonCompleteness(season=1, expected=3, matched=2, missing=[(3, "Three")])},
        specials=None, total_expected=3, total_matched=2, total_missing=[(1, 3, "Three")],
    )
    guide = EpisodeGuide(rows=[
        EpisodeGuideRow(season=1, episode=1, title="One", primary_file=p1,
                        target_rename="Show - S01E01 - One.mkv", status="Mapped",
                        confidence_label="96%", overview="Ep one.", air_date="2020-01-01"),
        EpisodeGuideRow(season=1, episode=2, title="Two", primary_file=p2,
                        target_rename="Show - S01E02 - Two.mkv", status="Review",
                        confidence_label="61%"),
        EpisodeGuideRow(season=1, episode=3, title="Three", status="Missing File"),
    ], unmapped_primary_files=[UnmappedFileRow(original=Path("C:/lib/Show/extra.mkv"), reason="no episode parsed")],
       summary=EpisodeGuideSummary(mapped_episodes=2, mapped_primary_files=2, companion_files=0,
                                   missing_episodes=1, unmapped_primary_files=1))
    return state, guide


class EpisodeTableModelTests(QtSmokeBase):
    def _model(self, state, guide, collapsed=None, folder_preview=None):
        from plex_renamer.gui_qt.widgets._episode_table_model import EpisodeTableModel

        model = EpisodeTableModel(media_type="tv", guide_provider=lambda _s: guide)
        model.show_state(state, collapsed_sections=collapsed if collapsed is not None else set(),
                         folder_preview=folder_preview)
        return model

    def test_tv_composition_order_and_kinds(self):
        state, guide = _guide_state()
        model = self._model(state, guide)
        kinds = [model.row_kind_at(row) for row in range(model.rowCount())]
        # unmapped label+row, season header, 3 episode rows (incl. ghost)
        self.assertEqual(kinds, ["section-label", "unmapped", "section-header",
                                 "episode", "episode", "episode"])

    def test_ghost_row_is_missing_file_episode(self):
        from plex_renamer.gui_qt.widgets._episode_table_model import ROW_DATA_ROLE

        state, guide = _guide_state()
        model = self._model(state, guide)
        data = model.index(5, 0).data(ROW_DATA_ROLE)
        self.assertEqual(data.status_text, "Missing File")
        self.assertEqual(data.status_tone, "muted")
        self.assertEqual(data.title, "S01E03 · Three")

    def test_season_header_shows_ratio_and_missing(self):
        state, guide = _guide_state()
        model = self._model(state, guide)
        header_row = model.section_header_row(model.season_section_key(1))
        text = model.index(header_row, 0).data()
        self.assertIn("Season 1", text)
        self.assertIn("2/3", text)
        self.assertIn("missing E03", text)

    def test_problems_filter_drops_mapped_keeps_review_and_ghost(self):
        state, guide = _guide_state()
        model = self._model(state, guide)
        model.set_filter_mode("problems")
        titles = [model.index(r, 0).data() for r in range(model.rowCount())
                  if model.row_kind_at(r) == "episode"]
        self.assertEqual(len(titles), 2)
        self.assertNotIn("S01E01 · One", titles)

    def test_search_filters_by_filename(self):
        state, guide = _guide_state()
        model = self._model(state, guide)
        model.set_search_text("s01e02")
        episode_rows = [r for r in range(model.rowCount()) if model.row_kind_at(r) == "episode"]
        self.assertEqual(len(episode_rows), 1)
        model.set_search_text("")
        self.assertEqual(len([r for r in range(model.rowCount()) if model.row_kind_at(r) == "episode"]), 3)

    def test_collapse_hides_member_rows(self):
        state, guide = _guide_state()
        collapsed: set[str] = set()
        model = self._model(state, guide, collapsed=collapsed)
        key = model.season_section_key(1)
        model.toggle_section(key)
        self.assertIn(key, collapsed)
        self.assertEqual([model.row_kind_at(r) for r in range(model.rowCount())],
                         ["section-label", "unmapped", "section-header"])

    def test_expanded_row_roundtrip_emits_expanded_role(self):
        from plex_renamer.gui_qt.widgets._episode_table_model import EXPANDED_ROLE

        state, guide = _guide_state()
        model = self._model(state, guide)
        events: list[tuple[int, int]] = []
        model.dataChanged.connect(lambda tl, br, roles=(): events.append((tl.row(), br.row())))
        model.set_expanded_row(3)
        self.assertTrue(model.index(3, 0).data(EXPANDED_ROLE))
        model.set_expanded_row(4)
        self.assertFalse(model.index(3, 0).data(EXPANDED_ROLE))
        self.assertIn((3, 3), events)
        self.assertIn((4, 4), events)

    def test_search_rebuild_resets_expanded_row(self):
        from plex_renamer.gui_qt.widgets._episode_table_model import EXPANDED_ROLE

        state, guide = _guide_state()
        model = self._model(state, guide)
        model.set_expanded_row(3)
        self.assertTrue(model.index(3, 0).data(EXPANDED_ROLE))

        model.set_search_text("s01e02")
        self.assertIsNone(model.expanded_row())
        for row in range(model.rowCount()):
            self.assertFalse(model.index(row, 0).data(EXPANDED_ROLE))

    def test_section_toggle_rebuild_resets_expanded_row(self):
        from plex_renamer.gui_qt.widgets._episode_table_model import EXPANDED_ROLE

        state, guide = _guide_state()
        model = self._model(state, guide)
        model.set_expanded_row(3)
        self.assertTrue(model.index(3, 0).data(EXPANDED_ROLE))

        model.toggle_section(model.season_section_key(1))
        self.assertIsNone(model.expanded_row())
        for row in range(model.rowCount()):
            self.assertFalse(model.index(row, 0).data(EXPANDED_ROLE))

    def test_summary_text_breakdown(self):
        state, guide = _guide_state()
        model = self._model(state, guide)
        self.assertEqual(model.summary_text(), "3 files · 2 mapped · 1 unmapped")

    def test_movie_rows_carry_checks(self):
        from plex_renamer.engine.models import PreviewItem, ScanState
        from plex_renamer.gui_qt.widgets._episode_table_model import ROW_DATA_ROLE, EpisodeTableModel
        from plex_renamer.gui_qt.widgets._workspace_widget_primitives import _CheckBinding

        state = ScanState(folder=Path("C:/lib/Movie"), media_info={"id": 9, "title": "Movie", "year": "2021", "_media_type": "movie"})
        state.scanned = True
        state.confidence = 0.9
        preview = PreviewItem(original=Path("C:/lib/Movie/movie.mkv"), new_name="Movie (2021).mkv",
                              target_dir=None, season=None, episodes=[], status="OK", media_type="movie")
        state.preview_items = [preview]
        state.check_vars["0"] = _CheckBinding(True)
        model = EpisodeTableModel(media_type="movie")
        model.show_state(state, collapsed_sections=set())
        rows = [r for r in range(model.rowCount()) if model.row_kind_at(r) == "movie-file"]
        self.assertEqual(len(rows), 1)
        data = model.index(rows[0], 0).data(ROW_DATA_ROLE)
        self.assertEqual(data.title, "movie.mkv")
        self.assertTrue(data.checked)
        self.assertEqual(data.status_text, "OK")
