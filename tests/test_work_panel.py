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

    def _panel_unshown(self, state, guide):
        """Like _panel(), but skips the pre-emptive resize() -- used to
        reproduce the "never laid out yet" cache-hit condition from the
        Task 3 review finding."""
        from plex_renamer.gui_qt.widgets._work_panel import MediaWorkPanel

        panel = MediaWorkPanel(media_type="tv", guide_provider=lambda _s: guide)
        panel.show_state(state, collapsed_sections=set(), folder_preview=None)
        return panel

    def test_header_title_and_strip_chips(self):
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        self.assertEqual(panel._title_label.text(), "Show (2020)")
        chip_texts = [b.text() for b in panel._strip_buttons]
        self.assertEqual(chip_texts, ["Series", "S1 2/3"])

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

    def test_filter_has_no_unmapped_segment(self):
        panel = self._panel(*_guide_state())
        self.assertEqual(set(panel.segmented_filter._buttons), {"All", "Problems"})

    def _panel_with_unassigned_files(self, count: int):
        from pathlib import Path

        from plex_renamer.engine.episode_assignments import EpisodeAssignmentTable

        state, guide = _guide_state()
        table = EpisodeAssignmentTable()
        for i in range(count):
            table.add_file(Path(f"C:/lib/Show/unassigned{i}.mkv"))
        state.assignments = table
        panel = self._panel(state, guide)
        return panel, state

    def test_strip_includes_unmapped_chip_when_files_unassigned(self):
        panel, state = self._panel_with_unassigned_files(count=2)
        panel.refresh_header(state)
        labels = [b.text() for b in panel._strip_buttons]
        self.assertIn("Unmapped (2)", labels)

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

    def test_bulk_mode_swaps_stack_and_gates_toolbar(self):
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        panel.show()
        self.assertFalse(panel.bulk_assign_active())
        panel.enter_bulk_assign()
        self.assertTrue(panel.bulk_assign_active())
        self.assertIs(panel._table_stack.currentWidget(), panel.bulk_panel)
        self.assertFalse(panel.segmented_filter.isEnabled())
        self.assertFalse(panel.search_box.isEnabled())
        self.assertFalse(panel.approve_all_button.isVisible())
        panel.exit_bulk_assign()
        self.assertFalse(panel.bulk_assign_active())
        self.assertIs(panel._table_stack.currentWidget(), panel.table_view)
        self.assertTrue(panel.segmented_filter.isEnabled())
        panel.close()

    def test_overflow_menu_emits_bulk_assign_requested(self):
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        fired: list[bool] = []
        panel.bulk_assign_requested.connect(lambda: fired.append(True))
        actions = panel.overflow_button.menu().actions()
        self.assertEqual([a.text() for a in actions], ["Bulk Assign…", "Unassign All"])
        actions[0].trigger()
        self.assertEqual(fired, [True])

    def test_unassign_all_lives_in_overflow_menu(self):
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        labels = [a.text() for a in panel.overflow_button.menu().actions()]
        self.assertIn("Unassign All", labels)
        self.assertIn("Bulk Assign…", labels)

    def test_unassign_all_menu_action_emits_signal(self):
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        fired: list[bool] = []
        panel.unassign_all_clicked.connect(lambda: fired.append(True))
        actions = {a.text(): a for a in panel.overflow_button.menu().actions()}
        action = actions["Unassign All"]
        action.setEnabled(True)   # fixture has no assignments; force-enable to test wiring
        action.trigger()
        self.assertEqual(fired, [True])

    def test_inline_action_clicked_reemits_as_inline_row_action(self):
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        fired: list[tuple] = []
        panel.inline_row_action.connect(lambda index, action_id: fired.append((index.row(), action_id)))
        index = panel.model.index(3, 0)
        panel.table_view.inline_action_clicked.emit(index, "assign_file")
        self.assertEqual(fired, [(3, "assign_file")])

    def test_unassign_all_button_removed(self):
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        self.assertIsNone(getattr(panel, "_unassign_all_button", None))
        self.assertFalse(hasattr(panel, "unassign_all_button"))

    def test_movie_mode_hides_overflow(self):
        from pathlib import Path
        from plex_renamer.engine.models import ScanState
        from plex_renamer.gui_qt.widgets._work_panel import MediaWorkPanel

        state = ScanState(folder=Path("C:/lib/Movie"), media_info={"id": 9, "title": "Movie", "year": "2021", "_media_type": "movie"})
        state.scanned = True
        panel = MediaWorkPanel(media_type="movie")
        panel.show_state(state, collapsed_sections=set(), folder_preview=None)
        panel.show()
        self.assertFalse(panel.overflow_button.isVisible())
        panel.close()

    def _movie_state_actionable(self):
        from pathlib import Path
        from plex_renamer.engine.models import PreviewItem, ScanState

        state = ScanState(
            folder=Path("C:/lib/Movie"),
            media_info={"id": 9, "title": "Movie", "year": "2021", "_media_type": "movie"},
        )
        state.scanned = True
        state.match_origin = "manual"   # avoid needs_review gating on default confidence=0.0
        state.preview_items = [
            PreviewItem(
                original=Path("C:/lib/Movie/movie.mkv"),
                new_name="Movie (2021).mkv",
                target_dir=Path("C:/lib/Movie"),
                season=None,
                episodes=[],
                status="OK",
                media_type="movie",
            )
        ]
        return state

    def test_movie_master_check_hidden(self):
        from plex_renamer.gui_qt.widgets._work_panel import MediaWorkPanel

        panel = MediaWorkPanel(media_type="movie")
        state = self._movie_state_actionable()
        panel.show_state(state, collapsed_sections=set(), folder_preview=None)
        panel.show()
        panel.update_master_state(state)
        self.assertFalse(panel.master_check.isVisible())
        self.assertFalse(panel.check_summary.isVisible())
        panel.close()

    def test_refresh_header_reuses_strip_buttons_when_seasons_unchanged(self):
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        before = [id(button) for button in panel._strip_buttons]
        self.assertTrue(before)                       # fixture renders at least one chip
        panel.refresh_header(state)                   # action-bar sync repeats this constantly
        panel.refresh_header(state)
        self.assertEqual([id(button) for button in panel._strip_buttons], before)
        panel.close()

    def test_refresh_strip_rebuilds_after_completeness_change(self):
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        before = [id(button) for button in panel._strip_buttons]
        season = next(iter(state.completeness.seasons.values()))
        season.matched += 1                           # chip text/tone derives from this
        panel.refresh_header(state)
        after = [id(button) for button in panel._strip_buttons]
        self.assertNotEqual(after, before)
        panel.close()

    def test_clear_resets_strip_key_so_next_show_rebuilds(self):
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        panel.clear()
        self.assertEqual(panel._strip_buttons, [])
        panel.refresh_header(state)
        self.assertTrue(panel._strip_buttons)
        panel.close()

    def test_short_overview_hides_more_toggle(self):
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        panel.show()
        panel._overview_label.setFixedWidth(400)
        panel._apply_overview_text("A short overview.", "tok")
        self.assertFalse(panel._overview_toggle.isVisible())
        panel.close()

    def test_long_overview_shows_more_toggle(self):
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        panel.show()
        panel._overview_label.setFixedWidth(200)
        panel._apply_overview_text(("Long overview. " * 60).strip(), "tok")
        self.assertTrue(panel._overview_toggle.isVisible())
        panel.close()

    def test_overview_toggle_self_corrects_once_real_width_is_available(self):
        # Reproduces the Task 3 review finding: on a TMDB-cache HIT,
        # _apply_overview_text runs synchronously during show_state(), which
        # can happen before the panel has ever been laid out/shown -- at
        # that point self._overview_label.width() is genuinely 0 (simulated
        # here with setFixedWidth(0), the exact condition named in the
        # finding), so _overview_overflows() falls back to
        # sizeHint().width(): an unconstrained-wrap preferred width that
        # does NOT match the real column width once the panel is actually
        # shown. Without a showEvent/resizeEvent recheck, the wrong verdict
        # computed at width 0 PERSISTS even after the panel is shown at a
        # real (here: wide-enough-to-fit) width.
        state, guide = _guide_state()
        panel = self._panel_unshown(state, guide)
        panel._overview_label.setFixedWidth(0)   # never-laid-out cache-hit condition
        short_overview = "A brief show synopsis in a single short sentence."
        panel._apply_overview_text(short_overview, "tok")

        # Release the artificial fixed width and lay the panel out for real,
        # at a width wide enough that this short overview fits on two lines
        # (i.e. the toggle should NOT be needed here).
        panel._overview_label.setMinimumWidth(0)
        panel._overview_label.setMaximumWidth(16777215)
        panel.resize(900, 640)
        panel.show()
        self._app.processEvents()

        self.assertGreater(panel._overview_label.width(), 0)
        self.assertFalse(
            panel._overview_overflows(),
            "sanity check: this overview must fit within two lines at the real width",
        )
        self.assertFalse(
            panel._overview_toggle.isVisible(),
            "toggle verdict computed at width 0 (sizeHint fallback) must not "
            "persist once the panel is laid out at its real, wider width",
        )
        panel.close()

    def test_clamp_height_leaves_descender_room(self):
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        fm = panel._overview_label.fontMetrics()
        panel._overview_expanded = False
        panel._apply_overview_clamp()
        # clamp must be >= two full line heights (no mid-letter clipping)
        self.assertGreaterEqual(panel._overview_label.maximumHeight(), 2 * fm.lineSpacing())

    def test_series_chip_present_in_strip(self):
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        labels = [b.text() for b in panel._strip_buttons]
        self.assertEqual(labels[0], "Series")
        self.assertEqual(labels[1:], ["S1 2/3"])

    def test_series_chip_hidden_in_movie_mode(self):
        from pathlib import Path
        from plex_renamer.engine.models import ScanState
        from plex_renamer.gui_qt.widgets._work_panel import MediaWorkPanel

        state = ScanState(folder=Path("C:/lib/Movie"), media_info={"id": 9, "title": "Movie", "year": "2021", "_media_type": "movie"})
        state.scanned = True
        panel = MediaWorkPanel(media_type="movie")
        panel.show_state(state, collapsed_sections=set(), folder_preview=None)
        panel.show()
        labels = [b.text() for b in panel._strip_buttons]
        self.assertNotIn("Series", labels)
        self.assertEqual(len(panel._strip_buttons), 0)
        panel.close()

    def test_scroll_to_folder_section_targets_folder_header(self):
        from plex_renamer.gui_qt.widgets._work_panel import MediaWorkPanel

        state, guide = _guide_state()
        panel = MediaWorkPanel(media_type="tv", guide_provider=lambda _s: guide)
        panel.resize(760, 640)
        panel.show_state(
            state,
            collapsed_sections=set(),
            folder_preview=("Show.S01.1080p", "Show (2020)"),
        )
        panel.show()
        header_row = panel.model.section_header_row("folder-preview")
        self.assertGreaterEqual(header_row, 0)
        panel.scroll_to_folder_section()
        self.assertEqual(panel._delegate._flash_row_index, header_row)
        panel.close()

    def _panel_with_matched_state(self, confidence: float):
        # "Matched" requires: show_id set (fixture default), not needs_review
        # (confidence >= auto-accept threshold, match_origin left "auto"),
        # no episode problems (all items "OK"), match_origin != "manual"
        # (else "Approved"), and not fully-ready (still actionable renames
        # pending, so is_fully_ready_state stays False).
        state, guide = _guide_state()
        for item in state.preview_items:
            item.status = "OK"
        state.confidence = confidence
        panel = self._panel(state, guide)
        return panel, state

    def test_matched_status_pill_is_green_with_confidence(self):
        panel, state = self._panel_with_matched_state(confidence=0.93)
        panel.refresh_header(state)
        self.assertEqual(panel._status_pill.text(), "MATCHED · 93%")
        self.assertEqual(panel._status_pill.property("tone"), "success")
        panel.close()

    def test_overview_toggle_reserves_layout_space_when_hidden(self):
        from plex_renamer.gui_qt.widgets._work_panel import MediaWorkPanel

        panel = MediaWorkPanel(media_type="tv")
        self.assertTrue(panel._overview_toggle.sizePolicy().retainSizeWhenHidden())

    def test_primary_action_button_lives_in_toolbar_and_no_preflight(self):
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        self.assertFalse(hasattr(panel, "_queue_preflight_label"))
        outer = panel.layout()
        sub_layouts = [
            item.layout() for item in (outer.itemAt(i) for i in range(outer.count()))
            if item.layout() is not None
        ]
        toolbar = next(lay for lay in sub_layouts if lay.indexOf(panel.approve_all_button) != -1)
        footer = next(lay for lay in sub_layouts if lay.indexOf(panel.summary_label) != -1)
        self.assertNotEqual(toolbar.indexOf(panel.primary_action_button), -1)
        self.assertEqual(footer.indexOf(panel.primary_action_button), -1)
        self.assertEqual(footer.count(), 2)   # summary_label + trailing stretch only
        panel.close()

    def test_fix_match_button_is_in_header_title_row(self):
        # Layout-tree invariant (adapted from the brief): title_row and footer
        # are sibling QHBoxLayouts added directly to the panel's outer layout,
        # so every widget in either bubbles up to the same parentWidget() (the
        # panel itself) -- that assertion can't distinguish the two rows.
        # Instead, walk the outer layout to find title_row (the layout that
        # contains the title label) and assert fix_match_button lives in that
        # same layout, not in the footer layout (the one containing
        # primary_action_button).
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        outer = panel.layout()
        sub_layouts = [
            item.layout() for item in (outer.itemAt(i) for i in range(outer.count()))
            if item.layout() is not None
        ]
        title_row = next(lay for lay in sub_layouts if lay.indexOf(panel._title_label) != -1)
        footer = next(lay for lay in sub_layouts if lay.indexOf(panel.primary_action_button) != -1)
        self.assertNotEqual(title_row, footer)
        self.assertNotEqual(title_row.indexOf(panel.fix_match_button), -1)
        self.assertEqual(footer.indexOf(panel.fix_match_button), -1)
