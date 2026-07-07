# tests/test_episode_table_model.py
"""EpisodeTableModel row composition, filters, search, expansion."""
from __future__ import annotations

from pathlib import Path

from conftest_qt import QtSmokeBase


def _guide_state():
    """Synthetic TV state with a real assignment table + completeness."""
    from plex_renamer.engine.models import (
        CompanionFile, CompletenessReport, ScanState, SeasonCompleteness,
    )
    from plex_renamer.app.models.state_models import (
        EpisodeGuide, EpisodeGuideRow, EpisodeGuideSummary, UnmappedFileRow,
    )
    from plex_renamer.engine.models import PreviewItem

    state = ScanState(folder=Path("C:/lib/Show"), media_info={"id": 7, "name": "Show", "year": "2020"})
    state.scanned = True
    p1 = PreviewItem(original=Path("C:/lib/Show/s01e01.mkv"), new_name="Show - S01E01 - One.mkv",
                     target_dir=None, season=1, episodes=[1], status="OK",
                     companions=[CompanionFile(original=Path("C:/lib/Show/s01e01.en.srt"),
                                               new_name="Show - S01E01 - One.en.srt", file_type="subtitle")])
    p2 = PreviewItem(original=Path("C:/lib/Show/s01e02.mkv"), new_name="Show - S01E02 - Two.mkv",
                     target_dir=None, season=1, episodes=[2], status="REVIEW: episode confidence below threshold")
    state.preview_items = [p1, p2]
    state.completeness = CompletenessReport(
        seasons={1: SeasonCompleteness(season=1, expected=3, matched=2, missing=[(3, "Three")])},
        specials=None, total_expected=3, total_matched=2, total_missing=[(1, 3, "Three")],
    )
    guide = EpisodeGuide(rows=[
        EpisodeGuideRow(season=1, episode=1, title="One", primary_file=p1,
                        companions=list(p1.companions),
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


class _StubSettings:
    def __init__(self, view_mode: str = "normal") -> None:
        self.view_mode = view_mode


class EpisodeTableModelTests(QtSmokeBase):
    def _model(self, state, guide, collapsed=None, folder_preview=None, settings_service=None):
        from plex_renamer.gui_qt.widgets._episode_table_model import EpisodeTableModel

        model = EpisodeTableModel(media_type="tv", guide_provider=lambda _s: guide,
                                  settings_service=settings_service)
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

    def test_episode_tooltip_is_rename_preview_not_overview(self):
        from plex_renamer.gui_qt.widgets._episode_table_model import ROW_DATA_ROLE

        state, guide = _guide_state()
        model = self._model(state, guide)
        data = model.index(3, 0).data(ROW_DATA_ROLE)
        self.assertEqual(data.tooltip, guide.rows[0].target_rename)
        self.assertNotEqual(data.tooltip, guide.rows[0].overview)

    def test_subtitle_companion_populates_subtitle_name(self):
        from plex_renamer.gui_qt.widgets._episode_table_model import ROW_DATA_ROLE

        state, guide = _guide_state()
        model = self._model(state, guide)
        data = model.index(3, 0).data(ROW_DATA_ROLE)   # row "One" — has a subtitle companion
        self.assertEqual(data.subtitle_name, str(guide.rows[0].companions[0].original))

    def test_episode_row_without_subtitle_companion_has_empty_subtitle_name(self):
        from plex_renamer.gui_qt.widgets._episode_table_model import ROW_DATA_ROLE

        state, guide = _guide_state()
        model = self._model(state, guide)
        data = model.index(4, 0).data(ROW_DATA_ROLE)   # row "Two" — no companions
        self.assertEqual(data.subtitle_name, "")

    def test_compact_mode_keeps_episode_filename(self):
        from plex_renamer.gui_qt.widgets._episode_table_model import ROW_DATA_ROLE

        state, guide = _guide_state()
        model = self._model(state, guide, settings_service=_StubSettings(view_mode="compact"))
        data = model.index(3, 0).data(ROW_DATA_ROLE)
        self.assertEqual(data.filename, "s01e01.mkv")

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

    def test_summary_text_companion_and_duplicate_segments(self):
        state, guide = _guide_state()
        guide.summary.companion_files = 2
        guide.summary.duplicate_files = 1
        model = self._model(state, guide)
        self.assertEqual(
            model.summary_text(),
            "6 files · 2 mapped · 2 companions · 1 unmapped · 1 duplicates",
        )

    def test_summary_text_empty_omits_zero_segments(self):
        from plex_renamer.gui_qt.widgets._episode_table_model import EpisodeTableModel

        model = EpisodeTableModel(media_type="tv", guide_provider=lambda _s: None)
        self.assertEqual(model.summary_text(), "0 files · 0 mapped")

    def test_movie_summary_counts_companions_and_duplicates(self):
        from plex_renamer.engine.models import CompanionFile, PreviewItem, ScanState
        from plex_renamer.gui_qt.widgets._episode_table_model import EpisodeTableModel

        state = ScanState(folder=Path("C:/lib/Movie"), media_info={"id": 9, "title": "Movie", "year": "2021", "_media_type": "movie"})
        state.scanned = True
        keeper = PreviewItem(original=Path("C:/lib/Movie/movie.mkv"), new_name="Movie (2021).mkv",
                             target_dir=None, season=None, episodes=[], status="OK", media_type="movie",
                             companions=[CompanionFile(original=Path("C:/lib/Movie/movie.en.srt"),
                                                       new_name="Movie (2021).en.srt", file_type="subtitle")])
        extra = PreviewItem(original=Path("C:/lib/Movie/movie copy.mkv"), new_name=None,
                            target_dir=None, season=None, episodes=[],
                            status="DUPLICATE: copy of movie.mkv", media_type="movie")
        state.preview_items = [keeper, extra]
        model = EpisodeTableModel(media_type="movie")
        model.show_state(state, collapsed_sections=set())
        self.assertEqual(model.summary_text(), "2 files · 1 mapped · 1 companions · 1 duplicates")

    def test_problems_filter_bulk_hint_when_only_unmapped_remain(self):
        state, guide = _guide_state()
        guide.rows[1].status = "Mapped"          # no Review/Conflict left
        model = self._model(state, guide)
        model.set_filter_mode("problems")
        kinds = [model.row_kind_at(r) for r in range(model.rowCount())]
        self.assertEqual(kinds[0], "bulk-hint")
        self.assertEqual(kinds.count("bulk-hint"), 1)
        text = model.index(0, 0).data()
        self.assertIn("1 unmapped", text)

    def test_no_bulk_hint_when_review_rows_exist_or_other_filters(self):
        state, guide = _guide_state()
        model = self._model(state, guide)        # guide still has a Review row
        model.set_filter_mode("problems")
        kinds = [model.row_kind_at(r) for r in range(model.rowCount())]
        self.assertNotIn("bulk-hint", kinds)
        guide.rows[1].status = "Mapped"
        model.set_filter_mode("all")
        self.assertNotIn("bulk-hint",
                         [model.row_kind_at(r) for r in range(model.rowCount())])

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

    def test_folder_section_key_is_folder_preview(self):
        state, guide = _guide_state()
        model = self._model(state, guide)
        self.assertEqual(model.folder_section_key(), "folder-preview")
