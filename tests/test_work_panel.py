# tests/test_work_panel.py
"""Work panel assembly: header, strip, toolbar rules, scroll-to-season."""

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

    def _layout_of(self, widget):
        """The QLayout that directly contains ``widget``, or None."""
        parent = widget.parentWidget()
        if parent is None:
            return None
        layout = parent.layout()
        if layout is None:
            return None
        for item_layout in self._iter_sub_layouts(layout):
            if item_layout.indexOf(widget) != -1:
                return item_layout
        if layout.indexOf(widget) != -1:
            return layout
        return None

    def _iter_sub_layouts(self, layout):
        for i in range(layout.count()):
            item = layout.itemAt(i)
            sub = item.layout()
            if sub is not None:
                yield sub
                yield from self._iter_sub_layouts(sub)

    def test_summary_label_lives_in_toolbar(self):
        panel = self._panel(*_guide_state())
        # The summary label must share a layout row with the search box.
        self.assertIs(self._layout_of(panel._summary_label), self._layout_of(panel._search_box))

    def test_bulk_mode_hides_filter_search_and_summary(self):
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        panel.show()
        panel.enter_bulk_assign()
        self.assertFalse(panel._segmented_filter.isVisible())
        self.assertFalse(panel._search_box.isVisible())
        self.assertFalse(panel._summary_label.isVisible())
        panel.exit_bulk_assign()
        self.assertTrue(panel._segmented_filter.isVisible())
        self.assertTrue(panel._search_box.isVisible())
        self.assertTrue(panel._summary_label.isVisible())
        panel.close()

    def test_header_title_and_strip_chips(self):
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        self.assertEqual(panel._title_label.text(), "Show (2020)")
        chip_texts = [b.text() for b in panel._strip_buttons]
        # Fixture guide carries one unmapped primary file (extra.mkv), so the
        # strip's "Unmapped" chip (keyed off guide.unmapped_primary_files,
        # not the assignment table) is expected between Series and S1.
        self.assertEqual(chip_texts, ["Series", "Unmapped (1)", "S1 2/3"])

    def test_toolbar_rules_review_present(self):
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        self.assertTrue(panel.approve_all_button.isVisible() or not panel.isVisible())
        panel.show()
        self.assertTrue(panel.approve_all_button.isVisible())  # guide has a Review row
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

    def test_episode_filter_box_present_with_placeholder(self):
        panel = self._panel(*_guide_state())
        self.assertEqual(panel.episode_search_box.placeholderText(), "Filter episodes…")

    def test_episode_filter_box_emits_signal(self):
        panel = self._panel(*_guide_state())
        searches: list[str] = []
        panel.episode_search_changed.connect(searches.append)
        panel.episode_search_box.setText("s02")
        self.assertEqual(searches, ["s02"])

    def test_filter_has_no_unmapped_segment(self):
        panel = self._panel(*_guide_state())
        self.assertEqual(set(panel.segmented_filter._buttons), {"All", "Problems"})

    def _panel_with_unmapped_guide_files(self, count: int):
        """Build a panel whose *guide* (not the assignment table) carries
        ``count`` unmapped primary files -- the strip chip and the
        unmapped-section scroll target both derive from
        ``guide.unmapped_primary_files`` so they never disagree."""
        from pathlib import Path

        from plex_renamer.app.models.state_models import UnmappedFileRow

        state, guide = _guide_state()
        guide.unmapped_primary_files = [
            UnmappedFileRow(
                original=Path(f"C:/lib/Show/unassigned{i}.mkv"), reason="no episode parsed"
            )
            for i in range(count)
        ]
        panel = self._panel(state, guide)
        return panel, state

    def test_strip_includes_unmapped_chip_when_files_unassigned(self):
        panel, state = self._panel_with_unmapped_guide_files(count=2)
        panel.refresh_header(state)
        labels = [b.text() for b in panel._strip_buttons]
        self.assertIn("Unmapped (2)", labels)

    def test_strip_omits_unmapped_chip_when_only_duplicates(self):
        """Regression for the dead-click bug: a losing duplicate copy used to
        count as "unassigned" (assignment-table based count) even though the
        guide routes it to duplicate_files, not unmapped_primary_files -- the
        chip would say "Unmapped (1)" while unmapped_section_row() was -1 and
        the click did nothing. Deriving the count from the guide keeps the
        chip and the section in agreement: no unmapped files means no chip."""
        from pathlib import Path

        from plex_renamer.app.models.state_models import UnmappedFileRow

        state, guide = _guide_state()
        guide.unmapped_primary_files = []
        guide.duplicate_files = [
            UnmappedFileRow(original=Path("C:/lib/Show/dup.mkv"), reason="duplicate of S01E01"),
        ]
        panel = self._panel(state, guide)
        labels = [b.text() for b in panel._strip_buttons]
        self.assertFalse(any(label.startswith("Unmapped") for label in labels))

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

        state = ScanState(
            folder=Path("C:/lib/Movie"),
            media_info={"id": 9, "title": "Movie", "year": "2021", "_media_type": "movie"},
        )
        state.scanned = True
        panel = MediaWorkPanel(media_type="movie")
        panel.show_state(state, collapsed_sections=set(), folder_preview=None)
        panel.show()
        self.assertFalse(panel.segmented_filter.isVisible())
        self.assertFalse(panel.search_box.isVisible())
        self.assertFalse(panel.episode_search_box.isVisible())
        self.assertIsNotNone(
            panel.master_check
        )  # shown/hidden by update_master_state (Task 5 wiring)
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
        self.assertFalse(panel.segmented_filter.isVisible())
        self.assertFalse(panel.search_box.isVisible())
        self.assertFalse(panel.approve_all_button.isVisible())
        panel.exit_bulk_assign()
        self.assertFalse(panel.bulk_assign_active())
        self.assertIs(panel._table_stack.currentWidget(), panel.table_view)
        self.assertTrue(panel.segmented_filter.isVisible())
        panel.close()

    def test_bulk_assign_hides_season_strip(self):
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        self.assertTrue(panel._strip_buttons)  # fixture renders at least one chip
        self.assertFalse(panel._strip_scroll.isHidden())
        panel.enter_bulk_assign()
        self.assertTrue(panel._strip_scroll.isHidden())
        panel.exit_bulk_assign()
        self.assertFalse(panel._strip_scroll.isHidden())
        panel.close()

    def test_guide_loaded_does_not_reshow_filter_search_during_bulk_assign(self):
        # Task 5: update_toolbar() used to set segmented_filter/search_box
        # visibility unconditionally from is_movie, ignoring bulk_active --
        # so a mid-bulk async guide arrival (_on_guide_loaded calls
        # update_toolbar) would silently re-show them behind the bulk panel,
        # the same class of regression already fixed for the season strip.
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        panel.show()
        panel.enter_bulk_assign()
        self.assertFalse(panel._segmented_filter.isVisible())
        self.assertFalse(panel._search_box.isVisible())
        panel._on_guide_loaded()
        self.assertFalse(panel._segmented_filter.isVisible())
        self.assertFalse(panel._search_box.isVisible())
        panel.exit_bulk_assign()
        self.assertTrue(panel._segmented_filter.isVisible())
        self.assertTrue(panel._search_box.isVisible())
        panel.close()

    def test_guide_loaded_does_not_reshow_strip_during_bulk_assign(self):
        # Final-review fix: _on_guide_loaded's strip refresh lacked the
        # bulk-assign guard that update_toolbar already had, so an async
        # guide arriving mid-bulk-assign would silently re-show the season
        # strip behind the bulk panel. exit_bulk_assign already resets
        # _strip_key and re-refreshes, so hiding here is safe.
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        panel.enter_bulk_assign()
        self.assertTrue(panel._strip_scroll.isHidden())
        # Force _refresh_strip to treat the chips as changed (simulating the
        # real scenario: an async guide arriving with a different
        # unmapped_primary_files count than the skeleton paint had) -- the
        # _strip_key cache would otherwise make _refresh_strip a no-op
        # regardless of the bulk guard, masking the regression.
        panel._strip_key = None
        panel._on_guide_loaded()
        self.assertTrue(panel._strip_scroll.isHidden())
        panel.exit_bulk_assign()
        self.assertFalse(panel._strip_scroll.isHidden())
        panel.close()

    def test_overflow_menu_emits_bulk_assign_requested(self):
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        fired: list[bool] = []
        panel.bulk_assign_requested.connect(lambda: fired.append(True))
        actions = panel.overflow_button.menu().actions()
        self.assertEqual([a.text() for a in actions], ["Bulk Assign…"])
        actions[0].trigger()
        self.assertEqual(fired, [True])

    def test_overflow_menu_has_no_unassign_all(self):
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        labels = [a.text() for a in panel.overflow_button.menu().actions()]
        self.assertNotIn("Unassign All", labels)
        self.assertIn("Bulk Assign…", labels)

    def test_unassign_all_clicked_signal_still_reachable_programmatically(self):
        # The overflow-menu entry is gone (Task 9), but the signal itself and
        # MediaWorkspaceActionCoordinator.unassign_all_episode_mappings remain
        # -- exercised directly here since there's no more UI to trigger it.
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        fired: list[bool] = []
        panel.unassign_all_clicked.connect(lambda: fired.append(True))
        panel.unassign_all_clicked.emit()
        self.assertEqual(fired, [True])

    def test_inline_action_clicked_reemits_as_inline_row_action(self):
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        fired: list[tuple] = []
        panel.inline_row_action.connect(
            lambda index, action_id: fired.append((index.row(), action_id))
        )
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

        state = ScanState(
            folder=Path("C:/lib/Movie"),
            media_info={"id": 9, "title": "Movie", "year": "2021", "_media_type": "movie"},
        )
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
        state.match_origin = "manual"  # avoid needs_review gating on default confidence=0.0
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

    def test_movie_mode_tracks_below_table_and_table_compact(self):
        # Round5 Task 6 (spec 2a): in movie mode the folder block + movie-file
        # table sits ABOVE the AutoMux tracks section, sized to its own
        # content, while the tracks host takes the remaining vertical space.
        from PySide6.QtWidgets import QWidget

        from plex_renamer.gui_qt.widgets._work_panel import MediaWorkPanel

        panel = MediaWorkPanel(media_type="movie")
        state = self._movie_state_actionable()
        panel.show_state(
            state, collapsed_sections=set(), folder_preview=("Movie.2021.1080p", "Movie (2021)")
        )
        panel.show()

        tracks = QWidget()
        tracks.setMinimumHeight(400)
        panel.set_automux_tracks(tracks)

        outer = panel.layout()

        def _find_position(target) -> int:
            for i in range(outer.count()):
                item = outer.itemAt(i)
                if item.widget() is not None and _contains_widget(item.widget(), target):
                    return i
                if item.layout() is not None and item.layout() is target:
                    return i
            raise AssertionError(f"{target!r} not found in outer layout")

        def _contains_widget(container, target) -> bool:
            if container is target:
                return True
            layout = container.layout()
            if layout is None:
                return False
            for i in range(layout.count()):
                item = layout.itemAt(i)
                if item.widget() is not None and _contains_widget(item.widget(), target):
                    return True
            return False

        table_pos = _find_position(panel._table_view)
        tracks_pos = _find_position(panel._automux_tracks_host)
        self.assertLess(table_pos, tracks_pos, "folder/table block must sit above the tracks")

        view = panel.table_view
        self.assertLess(view.maximumHeight(), 16777215)
        panel.close()

    def test_movie_mode_freed_space_goes_to_tracks_not_gap(self):
        # Final whole-branch review Finding 1: the compact-table max-height
        # cap in _compact_movie_table_height lands on _table_view, but the
        # outer layout's stretch=1 item is stack_host (the QStackedLayout
        # wrapper around _table_view + the bulk-assign panel). QStackedLayout
        # does not propagate the child's maximumHeight to the host, so a tall
        # panel splits its free space ~50/50 between stack_host and the
        # tracks host, creating a dead gap INSIDE stack_host instead of
        # routing that space to the tracks section (spec 2a).
        from PySide6.QtWidgets import QWidget

        from plex_renamer.gui_qt.widgets._work_panel import MediaWorkPanel

        panel = MediaWorkPanel(media_type="movie")
        state = self._movie_state_actionable()
        panel.show_state(
            state, collapsed_sections=set(), folder_preview=("Movie.2021.1080p", "Movie (2021)")
        )
        panel.resize(760, 900)
        panel.show()

        tracks = QWidget()
        tracks.setMinimumHeight(400)
        panel.set_automux_tracks(tracks)

        self._app.processEvents()
        panel.layout().activate()
        self._app.processEvents()

        view = panel.table_view
        stack_host = view.parentWidget()
        table_cap = view.maximumHeight()

        # The stack host must not be granted materially more height than the
        # compact table needs -- otherwise the excess becomes a dead gap
        # inside the host that never reaches the tracks section below it.
        self.assertLessEqual(
            stack_host.height(),
            table_cap + 20,
            f"stack_host got {stack_host.height()}px but the table only needs "
            f"{table_cap}px -- freed space is trapped as a dead gap instead "
            f"of going to the tracks section",
        )

        # The freed space must instead go to the tracks section, not
        # disappear as blank space between the folder block and the tracks.
        self.assertGreater(
            tracks.height(),
            panel.height() - table_cap - 200,
            "tracks section did not receive the freed panel space",
        )
        panel.close()

    def test_movie_mode_tracks_widget_fills_available_space(self):
        # Task 7 (spec §4): set_automux_tracks must lift the real
        # AutoMuxTracksWidget's normal 8-row cap in the movie host (via
        # set_fill_mode(True)) so a big plan's row viewport can grow into
        # the panel's freed space, instead of staying pinned at 8 rows with
        # a dead gap between the widget and the panel bottom.
        from plex_renamer.gui_qt import _scale
        from plex_renamer.gui_qt.widgets._automux_tracks import AutoMuxTracksWidget
        from plex_renamer.gui_qt.widgets._work_panel import MediaWorkPanel

        panel = MediaWorkPanel(media_type="movie")
        state = self._movie_state_actionable()
        panel.show_state(
            state, collapsed_sections=set(), folder_preview=("Movie.2021.1080p", "Movie (2021)")
        )
        panel.resize(760, 900)
        panel.show()

        plan = {
            "output_name": "Movie.mkv",
            "track_decisions": [
                {
                    "track_id": i,
                    "track_type": "audio",
                    "codec": "aac",
                    "language": "eng",
                    "name": f"Track {i}",
                    "keep": True,
                    "make_default": i == 0,
                    "reason": "retained",
                }
                for i in range(20)
            ],
            "subtitle_merges": [],
            "strip_track_names": False,
            "no_fear": False,
            "mkvmerge_path": "",
            "warnings": [],
            "user_modified": False,
        }
        tracks = AutoMuxTracksWidget()
        tracks.show_plan(plan)
        panel.set_automux_tracks(tracks)

        self._app.processEvents()
        panel.layout().activate()
        self._app.processEvents()
        self._app.processEvents()

        self.assertGreater(
            tracks._rows_scroll.height(),
            _scale.px(8 * 24),
            "the movie host must lift the 8-row cap so a 20-track plan's viewport can grow past it",
        )

        # The gap between the tracks widget's bottom and the panel's bottom
        # must only be the panel's own outer margin -- not a dead strip of
        # unused space below a still-capped widget.
        panel_bottom = panel.height()
        tracks_bottom = tracks.mapTo(panel, tracks.rect().bottomLeft()).y()
        margin = panel.layout().contentsMargins().bottom()
        self.assertLessEqual(
            panel_bottom - tracks_bottom,
            margin + _scale.px(8),
            f"{panel_bottom - tracks_bottom}px gap below the tracks widget "
            f"exceeds the panel's own {margin}px margin",
        )
        panel.close()

    def test_refresh_header_reuses_strip_buttons_when_seasons_unchanged(self):
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        before = [id(button) for button in panel._strip_buttons]
        self.assertTrue(before)  # fixture renders at least one chip
        panel.refresh_header(state)  # action-bar sync repeats this constantly
        panel.refresh_header(state)
        self.assertEqual([id(button) for button in panel._strip_buttons], before)
        panel.close()

    def test_refresh_strip_rebuilds_after_completeness_change(self):
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        before = [id(button) for button in panel._strip_buttons]
        season = next(iter(state.completeness.seasons.values()))
        season.matched += 1  # chip text/tone derives from this
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

    def test_overview_expansion_resets_on_series_token_change(self):
        # Final-review fix: _overview_expanded was only ever set in __init__
        # and the toggle click handler, so an expanded overview from series
        # A persisted (still expanded, toggle stuck on "less") when the user
        # switched to series B. _apply_overview_text now resets on a token
        # change, but must NOT reset on a same-token re-apply (the async
        # TMDB response landing for the series still on screen).
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        panel.show()
        panel._overview_label.setFixedWidth(200)
        long_text = ("Long overview. " * 60).strip()
        panel._apply_overview_text(long_text, "a")
        panel._on_overview_toggle_clicked()
        self.assertTrue(panel._overview_expanded)
        self.assertEqual(panel._overview_toggle.text(), "less")

        # Same-token re-apply (async response for the still-current series)
        # must not collapse the user's expansion.
        panel._apply_overview_text(long_text, "a")
        self.assertTrue(panel._overview_expanded)
        self.assertEqual(panel._overview_toggle.text(), "less")

        # A different token (series switch) must reset to collapsed.
        other_text = ("Different overview. " * 60).strip()
        panel._apply_overview_text(other_text, "b")
        self.assertFalse(panel._overview_expanded)
        self.assertEqual(panel._overview_toggle.text(), "more")
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
        panel._overview_label.setFixedWidth(0)  # never-laid-out cache-hit condition
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

    def test_overview_overflow_gate_matches_clamp_threshold(self):
        # Task 7: _overview_overflows() (the toggle-visibility gate) used a
        # hardcoded "2*lineSpacing()+1" threshold while _apply_overview_clamp()
        # (the actual visual clamp) used "2*lineSpacing()+_scale.px(6)" -- two
        # different magic numbers for what should be the same "does this text
        # fit in two collapsed lines?" question. Pin the contract directly via
        # a stubbed fontMetrics() so the test doesn't depend on a specific
        # font/DPI happening to land a real string in the gap between the two
        # thresholds: at line_spacing=20, the old gate threshold is 41 and the
        # clamp threshold is 46 (both at 96 DPI / scale 1.0) -- a wrapped
        # height of 43 sits in that gap. The clamp would NOT clip it (43 <=
        # 46), so the toggle must not claim overflow either.
        from PySide6.QtCore import QRect

        state, guide = _guide_state()
        panel = self._panel(state, guide)
        panel.show()
        panel._overview_label.setText("stubbed overview text")

        line_spacing = 20
        gap_height = 2 * line_spacing + 3  # strictly between 41 and 46

        class _StubMetrics:
            def lineSpacing(self):
                return line_spacing

            def boundingRect(self, *args, **kwargs):
                return QRect(0, 0, 300, gap_height)

        panel._overview_label.fontMetrics = lambda: _StubMetrics()

        panel._overview_expanded = False
        panel._apply_overview_clamp()
        clamp_max = panel._overview_label.maximumHeight()
        self.assertGreaterEqual(
            clamp_max,
            gap_height,
            "sanity check: the clamp must not actually clip this height",
        )
        self.assertFalse(
            panel._overview_overflows(),
            "overflow gate disagreed with the clamp it's supposed to gate: "
            f"reported overflow for a {gap_height}px block that fits within "
            f"the {clamp_max}px clamp",
        )
        panel.close()

    def test_overview_toggle_has_stable_fixed_width(self):
        # Task 7: without a fixed width, the toggle's layout width tracks
        # QPushButton.sizeHint(), which is computed in C++ from the button's
        # OWN fontMetrics() -- not reachable by monkeypatching (unlike the
        # QLabel gate above, which is pure-Python). Under the app's real
        # theme.qss, "more" and "less" measure differently (confirmed via a
        # manual offscreen probe with QT_QPA_FONTDIR pointed at real fonts:
        # sizeHint 45px vs 37px) so the button visibly resizes on click. The
        # offscreen test font's fallback glyphs happen to size "more"/"less"
        # identically (see test_qt_job_detail_panel.py's note on this), which
        # would mask a width-delta assertion here -- so this pins the fix's
        # actual mechanism instead: a symmetric fixed width, set once,
        # independent of which of the two labels is currently showing.
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        toggle = panel._overview_toggle

        self.assertGreater(toggle.minimumWidth(), 0)
        self.assertEqual(
            toggle.minimumWidth(),
            toggle.maximumWidth(),
            "toggle width must be fixed so 'more'/'less' can't resize it",
        )

        fixed_width = toggle.width()
        panel.show()
        panel._apply_overview_text(("Long overview. " * 60).strip(), "tok")
        self._app.processEvents()
        self.assertTrue(panel._overview_toggle.isVisible())
        self.assertEqual(toggle.width(), fixed_width)

        panel._on_overview_toggle_clicked()
        self._app.processEvents()
        self.assertEqual(toggle.width(), fixed_width)
        panel.close()

    def test_clamp_height_leaves_descender_room(self):
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        fm = panel._overview_label.fontMetrics()
        panel._overview_expanded = False
        panel._apply_overview_clamp()
        # clamp must be >= two full line heights (no mid-letter clipping)
        self.assertGreaterEqual(panel._overview_label.maximumHeight(), 2 * fm.lineSpacing())

    def test_overview_label_height_stable_across_text_lengths(self):
        # Task 8: only maximumHeight was pinned when collapsed, so a
        # 1-line overview left minimumHeight at 0 and the label shrank to
        # its content -- shifting everything below it when the user
        # switched from a show with a long overview to one with a short
        # one. Both bounds must be pinned to the same two-line height
        # while collapsed, regardless of how much text is set.
        from plex_renamer.gui_qt import _scale

        state, guide = _guide_state()
        panel = self._panel(state, guide)
        panel.show()
        fm = panel._overview_label.fontMetrics()
        two_lines = 2 * fm.lineSpacing() + _scale.px(6)  # _OVERVIEW_CLAMP_PAD_U

        panel._apply_overview_text("A short one-line overview.", "tok-a")
        self._app.processEvents()
        self.assertEqual(panel._overview_label.minimumHeight(), two_lines)
        self.assertEqual(panel._overview_label.maximumHeight(), two_lines)

        panel._apply_overview_text(("Long overview. " * 60).strip(), "tok-b")
        self._app.processEvents()
        self.assertEqual(panel._overview_label.minimumHeight(), two_lines)
        self.assertEqual(
            panel._overview_label.maximumHeight(), two_lines
        )  # still clamped collapsed
        panel.close()

    def test_series_chip_present_in_strip(self):
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        labels = [b.text() for b in panel._strip_buttons]
        self.assertEqual(labels[0], "Series")
        self.assertEqual(labels[1:], ["Unmapped (1)", "S1 2/3"])

    def test_series_chip_hidden_in_movie_mode(self):
        from pathlib import Path

        from plex_renamer.engine.models import ScanState
        from plex_renamer.gui_qt.widgets._work_panel import MediaWorkPanel

        state = ScanState(
            folder=Path("C:/lib/Movie"),
            media_info={"id": 9, "title": "Movie", "year": "2021", "_media_type": "movie"},
        )
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

    def test_primary_action_button_lives_in_header_and_no_preflight(self):
        # Task 10: Queue This Show moved out of the toolbar row into the
        # header title row alongside Fix Match / AutoMux.
        # Task 5: the footer is gone -- summary_label now lives in the same
        # toolbar row as approve_all_button, so there's no separate footer
        # layout to check it against.
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        self.assertFalse(hasattr(panel, "_queue_preflight_label"))
        outer = panel.layout()
        sub_layouts = [
            item.layout()
            for item in (outer.itemAt(i) for i in range(outer.count()))
            if item.layout() is not None
        ]
        toolbar = next(lay for lay in sub_layouts if lay.indexOf(panel.approve_all_button) != -1)
        title_row = next(lay for lay in sub_layouts if lay.indexOf(panel._title_label) != -1)
        self.assertIs(toolbar, self._layout_of(panel.summary_label))
        self.assertEqual(toolbar.indexOf(panel.primary_action_button), -1)
        self.assertNotEqual(title_row.indexOf(panel.primary_action_button), -1)
        panel.close()

    def test_fix_match_button_is_in_header_title_row(self):
        # Layout-tree invariant (adapted from the brief): title_row and toolbar
        # are sibling QHBoxLayouts added directly to the panel's outer layout,
        # so every widget in either bubbles up to the same parentWidget() (the
        # panel itself) -- that assertion can't distinguish the two rows.
        # Instead, walk the outer layout to find title_row (the layout that
        # contains the title label) and assert fix_match_button lives in that
        # same layout, not in the toolbar layout (the one containing
        # approve_all_button).
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        outer = panel.layout()
        sub_layouts = [
            item.layout()
            for item in (outer.itemAt(i) for i in range(outer.count()))
            if item.layout() is not None
        ]
        title_row = next(lay for lay in sub_layouts if lay.indexOf(panel._title_label) != -1)
        toolbar = next(lay for lay in sub_layouts if lay.indexOf(panel.approve_all_button) != -1)
        self.assertNotEqual(title_row, toolbar)
        self.assertNotEqual(title_row.indexOf(panel.fix_match_button), -1)
        self.assertEqual(toolbar.indexOf(panel.fix_match_button), -1)

    def test_header_buttons_restyled_and_colocated(self):
        # Task 10: Fix Match, AutoMux toggle (danger while enabled), and
        # Queue This Show all sit in the same header title row, visually
        # parallel to Approve All.
        # Task 3: Fix Match's default cssClass is neutral ("secondary") --
        # the action bar re-tones it to "caution" per-state -- and all three
        # header buttons use the default (big-format) size, no sizeVariant.
        state, guide = _guide_state()
        panel = self._panel(state, guide)
        self.assertEqual(panel._fix_match_button.property("cssClass"), "secondary")
        self.assertEqual(panel._automux_button.property("cssClass"), "danger")
        self.assertIsNone(panel._primary_action_button.property("sizeVariant"))
        self.assertIsNone(panel._fix_match_button.property("sizeVariant"))
        self.assertIsNone(panel._automux_button.property("sizeVariant"))

    def test_source_pill_has_no_percentage(self):
        panel, state = self._panel_with_matched_state(confidence=0.93)
        panel.refresh_header(state)
        self.assertEqual(panel._source_pill.text(), "TMDB")
        self.assertNotIn("%", panel._source_pill.text())
        panel.close()
