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


def _episode_filter_state():
    """Two-season guide for episode-filter matching tests (title substring,
    SxxEyy, NxMM, bare season) -- S02E05 titled 'Winterfell' with a '1080p'
    filename to exercise the AND-with-filename-filter case."""
    from plex_renamer.app.models.state_models import (
        EpisodeGuide, EpisodeGuideRow, EpisodeGuideSummary, UnmappedFileRow,
    )
    from plex_renamer.engine.models import PreviewItem, ScanState

    state = ScanState(folder=Path("C:/lib/Show"), media_info={"id": 7, "name": "Show", "year": "2020"})
    state.scanned = True
    p1 = PreviewItem(original=Path("C:/lib/Show/s01e01.mkv"), new_name="Show - S01E01 - Alpha.mkv",
                     target_dir=None, season=1, episodes=[1], status="OK")
    p2 = PreviewItem(original=Path("C:/lib/Show/s02e05.1080p.mkv"), new_name="Show - S02E05 - Winterfell.mkv",
                     target_dir=None, season=2, episodes=[5], status="OK")
    p3 = PreviewItem(original=Path("C:/lib/Show/s02e06.mkv"), new_name="Show - S02E06 - Beta.mkv",
                     target_dir=None, season=2, episodes=[6], status="OK")
    state.preview_items = [p1, p2, p3]
    guide = EpisodeGuide(
        rows=[
            EpisodeGuideRow(season=1, episode=1, title="Alpha", primary_file=p1,
                            target_rename="Show - S01E01 - Alpha.mkv", status="Mapped"),
            EpisodeGuideRow(season=2, episode=5, title="Winterfell", primary_file=p2,
                            target_rename="Show - S02E05 - Winterfell.mkv", status="Mapped"),
            EpisodeGuideRow(season=2, episode=6, title="Beta", primary_file=p3,
                            target_rename="Show - S02E06 - Beta.mkv", status="Mapped"),
        ],
        unmapped_primary_files=[UnmappedFileRow(original=Path("C:/lib/Show/extra.mkv"), reason="no episode parsed")],
        summary=EpisodeGuideSummary(mapped_episodes=3, mapped_primary_files=3, unmapped_primary_files=1),
    )
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

    def _model_with_guide(self, statuses):
        """A minimal single-season guide with one row per status, in order
        (episode numbers 1..N) — enough to exercise inline_actions adjacency
        without the full _guide_state() fixture's companions/completeness."""
        from plex_renamer.app.models.state_models import (
            EpisodeGuide, EpisodeGuideRow, EpisodeGuideSummary,
        )
        from plex_renamer.engine.models import ScanState

        state = ScanState(folder=Path("C:/lib/Show"), media_info={"id": 7, "name": "Show", "year": "2020"})
        state.scanned = True
        rows = [
            EpisodeGuideRow(season=1, episode=i, title=f"Ep{i}", status=status)
            for i, status in enumerate(statuses, start=1)
        ]
        guide = EpisodeGuide(rows=rows, summary=EpisodeGuideSummary())
        return self._model(state, guide)

    def _row_data_for_status(self, model, status):
        from plex_renamer.gui_qt.widgets._episode_table_model import ROW_DATA_ROLE

        for row in range(model.rowCount()):
            if model.row_kind_at(row) != "episode":
                continue
            data = model.index(row, 0).data(ROW_DATA_ROLE)
            if data.status_text == status:
                return data
        raise AssertionError(f"no episode row with status {status!r}")

    def test_review_rows_carry_inline_actions(self):
        model = self._model_with_guide(statuses=["Review", "Mapped"])
        review = self._row_data_for_status(model, "Review")
        ids = [action_id for action_id, _label in review.inline_actions]
        self.assertEqual(ids, ["approve", "reassign", "unassign"])
        mapped = self._row_data_for_status(model, "Mapped")
        self.assertEqual(mapped.inline_actions, ())

    def test_row_adjacent_to_missing_slot_offers_assign_to_more(self):
        model = self._model_with_guide(statuses=["Mapped", "Missing File"])
        mapped = self._row_data_for_status(model, "Mapped")
        self.assertIn("assign_to_more", [a for a, _ in mapped.inline_actions])

    def test_review_row_adjacent_to_missing_slot_inserts_assign_to_more(self):
        model = self._model_with_guide(statuses=["Review", "Missing File"])
        review = self._row_data_for_status(model, "Review")
        ids = [action_id for action_id, _label in review.inline_actions]
        self.assertEqual(ids, ["approve", "reassign", "assign_to_more", "unassign"])

    def test_conflict_row_has_no_inline_actions(self):
        model = self._model_with_guide(statuses=["Conflict", "Missing File"])
        conflict = self._row_data_for_status(model, "Conflict")
        self.assertEqual(conflict.inline_actions, ())

    def test_missing_file_row_has_no_inline_actions_field_populated(self):
        # The legacy "Assign file..." single button is a delegate concern
        # (_row_inline_actions), not a model-owned inline_actions entry.
        model = self._model_with_guide(statuses=["Mapped", "Missing File"])
        missing = self._row_data_for_status(model, "Missing File")
        self.assertEqual(missing.inline_actions, ())

    def test_unmapped_section_row_locates_label(self):
        state, guide = _guide_state()
        model = self._model(state, guide)
        row = model.unmapped_section_row()
        self.assertGreaterEqual(row, 0)
        self.assertEqual(model.row_kind_at(row), "section-label")

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

    def test_unmapped_entry_carries_reason_as_detail(self):
        from plex_renamer.gui_qt.widgets._episode_table_model import ROW_DATA_ROLE

        state, guide = _guide_state()
        model = self._model(state, guide)
        data = model.index(1, 0).data(ROW_DATA_ROLE)   # row kind "unmapped"
        self.assertEqual(data.detail, "no episode parsed")
        self.assertNotEqual(data.title, data.detail)

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

    def _episode_titles(self, model):
        from plex_renamer.gui_qt.widgets._episode_table_model import ROW_DATA_ROLE

        return [
            model.index(r, 0).data(ROW_DATA_ROLE).title
            for r in range(model.rowCount())
            if model.row_kind_at(r) == "episode"
        ]

    def test_episode_filter_matches_title_and_codes(self):
        state, guide = _episode_filter_state()
        model = self._model(state, guide)

        model.set_episode_search("s02e05")
        self.assertEqual(self._episode_titles(model), ["S02E05 · Winterfell"])

        model.set_episode_search("2x05")
        self.assertEqual(self._episode_titles(model), ["S02E05 · Winterfell"])

        model.set_episode_search("winterfell")
        self.assertEqual(self._episode_titles(model), ["S02E05 · Winterfell"])

        model.set_episode_search("s02")
        self.assertEqual(self._episode_titles(model), ["S02E05 · Winterfell", "S02E06 · Beta"])

    def test_episode_filter_ands_with_filename_filter(self):
        state, guide = _episode_filter_state()
        model = self._model(state, guide)
        model.set_search_text("1080p")
        model.set_episode_search("s02")
        self.assertEqual(self._episode_titles(model), ["S02E05 · Winterfell"])

    def test_episode_filter_ignores_non_episode_sections(self):
        state, guide = _episode_filter_state()
        model = self._model(state, guide)
        model.set_episode_search("zzz-no-match")
        kinds = [model.row_kind_at(r) for r in range(model.rowCount())]
        self.assertIn("unmapped", kinds)
        self.assertIn("section-label", kinds)
        self.assertEqual(self._episode_titles(model), [])

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

    def test_movie_rows_are_flat_not_checkable(self):
        """Movie-file rows no longer carry a middle-panel checkbox (GUI V4
        Plan 3 round-2 Task 1) — queue selection flows through the roster
        (left panel) instead. This row's title still renders regardless."""
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
        self.assertFalse(data.checkable)
        self.assertIsNone(data.checked)

    def test_movie_entry_is_not_checkable(self):
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
        row_data = model.index(rows[0], 0).data(ROW_DATA_ROLE)
        self.assertFalse(row_data.checkable)
        self.assertIsNone(row_data.checked)

    def test_movie_status_label_parity(self):
        from plex_renamer.gui_qt.widgets._episode_table_model import _movie_status_label
        class _P:
            def __init__(self, **k): self.__dict__.update(k)
        ok = _P(is_conflict=False, is_unmatched=False, is_review=False, is_skipped=False)
        review = _P(is_conflict=False, is_unmatched=False, is_review=True, is_skipped=False)
        self.assertEqual(_movie_status_label(ok), "Matched")
        self.assertEqual(_movie_status_label(review), "Review")

    def test_folder_section_key_is_folder_preview(self):
        state, guide = _guide_state()
        model = self._model(state, guide)
        self.assertEqual(model.folder_section_key(), "folder-preview")

    def test_folder_row_tooltip_carries_full_source_and_target(self):
        from plex_renamer.gui_qt.widgets._episode_table_model import ROW_DATA_ROLE

        state, guide = _guide_state()
        folder_preview = ("C:/lib/Show", "Show (2020)")
        model = self._model(state, guide, folder_preview=folder_preview)
        rows = [r for r in range(model.rowCount()) if model.row_kind_at(r) == "folder"]
        self.assertEqual(len(rows), 1)
        data = model.index(rows[0], 0).data(ROW_DATA_ROLE)
        self.assertEqual(data.title, "C:/lib/Show")
        self.assertEqual(data.target, "Show (2020)")
        self.assertEqual(data.tooltip, "C:/lib/Show -> Show (2020)")


# A plan that carries an actionable decision (mirrors PLAN in
# test_workspace_automux.py, trimmed to what plan_has_actions() checks).
_ACTION_PLAN = {
    "track_decisions": [],
    "subtitle_merges": [{"source_relative": "Show/a.eng.srt", "action": "merge",
                          "language": "eng", "set_default": False}],
}


class MuxActiveRowDataTests(QtSmokeBase):
    """Round5 spec 1b: EpisodeRowData.mux_active mirrors file_mux_active()."""

    def _model(self, state, guide):
        return EpisodeTableModelTests._model(self, state, guide)

    def _row_data_for_status(self, model, status):
        return EpisodeTableModelTests._row_data_for_status(self, model, status)

    def test_episode_row_data_carries_mux_active(self):
        state, guide = _guide_state()
        # "One" (status Mapped) maps to preview_items[0] in _guide_state().
        state.mux_plans[0] = dict(_ACTION_PLAN)
        model = self._model(state, guide)
        row_data = self._row_data_for_status(model, "Mapped")
        self.assertTrue(row_data.mux_active)

        state.mux_opt_outs.add(0)
        model = self._model(state, guide)
        row_data = self._row_data_for_status(model, "Mapped")
        self.assertFalse(row_data.mux_active)

    def test_refresh_row_data_flips_mux_active_after_plan_lands(self):
        """Warm-time refresh wiring (Task 3 step 5): mutating
        state.mux_plans after the model is built and calling
        refresh_row_data(state) must rebuild row_data so mux_active
        reflects the newly-landed plan without a reselect."""
        state, guide = _guide_state()
        model = self._model(state, guide)
        row_data = self._row_data_for_status(model, "Mapped")
        self.assertFalse(row_data.mux_active)

        state.mux_plans[0] = dict(_ACTION_PLAN)
        model.refresh_row_data(state)
        row_data = self._row_data_for_status(model, "Mapped")
        self.assertTrue(row_data.mux_active)
