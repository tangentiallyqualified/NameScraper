from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from conftest_qt import QtSmokeBase
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from plex_renamer.app.controllers.queue_controller import BatchQueueResult
from plex_renamer.app.services.command_gating_service import CommandGatingService
from plex_renamer.app.services.settings_service import SettingsService
from plex_renamer.engine import (
    CompanionFile,
    CompletenessReport,
    PreviewItem,
    ScanState,
    SeasonCompleteness,
    get_checked_indices_from_state,
)


class QtMediaWorkspaceTests(QtSmokeBase):
    def tearDown(self):
        # ~90 tests here each build a full MediaWorkspace inline with no
        # disposal; dispose per test to keep GC cycle counts small (see
        # QtSmokeBase._dispose_top_level_widgets for the crash this avoids).
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        self._dispose_top_level_widgets(MediaWorkspace)
        super().tearDown()

    def test_media_workspace_queue_buttons_use_distinct_labels(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeQueueController:
            def add_tv_batch(
                self,
                states,
                root,
                output_root,
                gating,
                settings_service=None,
                tmdb_client=None,
                progress=None,
            ):
                return BatchQueueResult(added=len(states))

        class _FakeMediaController:
            def __init__(self):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        state = ScanState(
            folder=Path("C:/library/tv/Example.Show.2024"),
            media_info={"id": 101, "name": "Example Show", "year": "2024"},
            preview_items=[
                PreviewItem(
                    original=Path(
                        "C:/library/tv/Example.Show.2024/Season 01/Example.Show.S01E01.mkv"
                    ),
                    new_name="Example Show (2024) - S01E01 - Pilot.mkv",
                    target_dir=Path("C:/library/tv/Example Show (2024)/Season 01"),
                    season=1,
                    episodes=[1],
                    status="OK",
                )
            ],
            scanned=True,
            checked=True,
            confidence=1.0,
        )

        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
            media_ctrl = _FakeMediaController()
            media_ctrl.batch_states = [state]

            workspace = MediaWorkspace(
                media_type="tv",
                media_controller=media_ctrl,
                queue_controller=_FakeQueueController(),
                settings_service=settings,
            )
            workspace.resize(1200, 700)
            workspace.show()
            workspace.show_ready()
            self._app.processEvents()

            self.assertEqual(workspace._queue_inline_btn.text(), "Queue This Show")
            self.assertEqual(workspace._roster_queue_btn.text(), "Queue 1 Checked")
            self.assertIs(workspace._queue_inline_btn, workspace._work_panel.primary_action_button)
            self.assertLess(
                workspace._roster_queue_btn.mapTo(workspace, QPoint(0, 0)).y(),
                workspace._roster_panel.view.mapTo(workspace, QPoint(0, 0)).y(),
            )
            self.assertLess(
                workspace._roster_queue_btn.minimumWidth(),
                workspace._queue_inline_btn.sizeHint().width() + 20,
            )
            roster_panel_right = (
                workspace._roster_panel.mapTo(workspace, QPoint(0, 0)).x()
                + workspace._roster_panel.width()
            )
            queue_button_right = (
                workspace._roster_queue_btn.mapTo(workspace, QPoint(0, 0)).x()
                + workspace._roster_queue_btn.width()
            )
            self.assertLessEqual(queue_button_right, roster_panel_right)

            workspace.close()

    def test_movie_review_item_uses_approve_match_primary_action(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = [state]
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.movie_library_states):
                    return self.movie_library_states[index]
                return None

            def sync_queued_states(self):
                return None

        state = ScanState(
            folder=Path("C:/library/movies/Amelie.2001"),
            media_info={"id": 194, "title": "Amelie", "year": "2001", "_media_type": "movie"},
            preview_items=[
                PreviewItem(
                    original=Path("C:/library/movies/Amelie.2001/Amelie.2001.mkv"),
                    new_name="Amelie (2001).mkv",
                    target_dir=Path("C:/library/movies/Amelie (2001)"),
                    season=None,
                    episodes=[],
                    status="REVIEW",
                    media_type="movie",
                    media_id=194,
                    media_name="Amelie",
                )
            ],
            scanned=True,
            checked=False,
            confidence=0.5,
        )

        workspace = MediaWorkspace(
            media_type="movie",
            media_controller=_FakeMediaController(state),
            tmdb_provider=lambda: None,
        )
        workspace.resize(1220, 700)
        workspace.show()
        self._app.processEvents()
        workspace.show_ready()
        self._app.processEvents()

        # Facts-grid + detail-poster layout assertions were removed with the
        # detail panel (GUI V4 Plan 3 Task 5). The surviving behaviour is that a
        # movie review item drives the work panel's primary action.
        self.assertEqual(workspace._queue_inline_btn.text(), "Approve Match")
        self.assertGreater(workspace._work_panel.width(), 0)

        workspace.close()

    def test_media_workspace_uses_inline_approve_action_for_review_items(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = [state]
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        state = ScanState(
            folder=Path("C:/library/tv/Review.Show.2024"),
            media_info={"id": 101, "name": "Review Show", "year": "2024"},
            preview_items=[],
            scanned=True,
            checked=False,
            confidence=0.42,
        )
        media_ctrl = _FakeMediaController(state)
        workspace = MediaWorkspace(media_type="tv", media_controller=media_ctrl)
        workspace.show_ready()

        data = self._roster_row_data_for_index(workspace, 0)
        self.assertIsNotNone(data)
        self.assertEqual(workspace._queue_inline_btn.text(), "Approve Match")

        workspace.close()

    def test_media_workspace_inline_approve_refreshes_group_and_swaps_to_queue_action(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = [state]
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

            def approve_match(self, state):
                state.match_origin = "manual"

        state = ScanState(
            folder=Path("C:/library/tv/Review.Show.2024"),
            media_info={"id": 101, "name": "Review Show", "year": "2024"},
            preview_items=[],
            scanned=True,
            checked=False,
            confidence=0.42,
        )
        media_ctrl = _FakeMediaController(state)
        workspace = MediaWorkspace(media_type="tv", media_controller=media_ctrl)
        workspace.show_ready()

        self.assertEqual(workspace._queue_inline_btn.text(), "Approve Match")

        workspace._activate_selected_primary_action()

        self.assertFalse(state.needs_review)
        self.assertEqual(workspace._queue_inline_btn.text(), "Queue This Show")
        self._assert_roster_section_title(workspace, 0, "MATCHED")
        self.assertFalse(state.checked)

        workspace.close()

    def test_media_workspace_uses_choose_match_labels_for_tied_review_items(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = [state]
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        state = ScanState(
            folder=Path("C:/library/tv/Tied.Show.2024"),
            media_info={"id": 101, "name": "Tied Show", "year": "2024"},
            preview_items=[],
            scanned=True,
            checked=False,
            confidence=0.42,
            tie_detected=True,
        )
        workspace = MediaWorkspace(media_type="tv", media_controller=_FakeMediaController(state))
        workspace.show_ready()

        # Task 3: Fix Match no longer doubles as Choose Match during a tie --
        # it's hidden entirely so the single caution-toned primary button is
        # the sole "Choose Match" affordance.
        self.assertFalse(workspace._fix_match_btn.isVisibleTo(workspace))
        self.assertEqual(workspace._queue_inline_btn.text(), "Choose Match")
        self.assertEqual(workspace._queue_inline_btn.property("cssClass"), "caution")

        workspace.close()

    def _workspace_with_selected_state(
        self, *, tie_detected: bool = False, needs_review: bool = False
    ):
        """Build a one-show TV workspace whose selected state has the given
        needs_review/tie_detected flags, for header-button tone/visibility
        assertions (Task 3)."""
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        confidence = 0.42 if needs_review else 1.0
        state = ScanState(
            folder=Path("C:/library/tv/Header.Show.2024"),
            media_info={"id": 101, "name": "Header Show", "year": "2024"},
            preview_items=[],
            scanned=True,
            checked=False,
            confidence=confidence,
            tie_detected=tie_detected,
        )
        media_ctrl = self._make_fake_media_ctrl(state)
        workspace = MediaWorkspace(media_type="tv", media_controller=media_ctrl)
        workspace.resize(1200, 700)
        workspace.show()
        workspace.show_ready()
        self._app.processEvents()
        return workspace, state

    def test_tie_state_shows_single_caution_choose_match(self):
        workspace, _state = self._workspace_with_selected_state(
            tie_detected=True, needs_review=True
        )
        workspace._update_action_bar()
        self.assertFalse(workspace._fix_match_btn.isVisibleTo(workspace))
        self.assertEqual(workspace._queue_inline_btn.text(), "Choose Match")
        self.assertEqual(workspace._queue_inline_btn.property("cssClass"), "caution")
        workspace.close()

    def test_matched_state_has_neutral_fix_match(self):
        workspace, _state = self._workspace_with_selected_state(
            tie_detected=False, needs_review=False
        )
        workspace._update_action_bar()
        self.assertTrue(workspace._fix_match_btn.isVisibleTo(workspace))
        self.assertEqual(workspace._fix_match_btn.text(), "Fix Match")
        self.assertEqual(workspace._fix_match_btn.property("cssClass"), "secondary")
        workspace.close()

    def test_review_state_has_caution_fix_match(self):
        workspace, _state = self._workspace_with_selected_state(
            tie_detected=False, needs_review=True
        )
        workspace._update_action_bar()
        self.assertEqual(workspace._fix_match_btn.property("cssClass"), "caution")
        workspace.close()

    def test_header_buttons_use_default_size_variant(self):
        workspace, _state = self._workspace_with_selected_state()
        for button in (
            workspace._fix_match_btn,
            workspace._queue_inline_btn,
            workspace._work_panel.automux_button,
        ):
            self.assertIsNone(button.property("sizeVariant"))
        workspace.close()

    def test_empty_batch_reset_restores_header_button_tones(self):
        # Regression (Task 3 review): the empty-batch refresh path returns
        # via _reset_empty_ready_state BEFORE _update_action_bar runs, so the
        # reset itself must undo tie styling -- otherwise a hidden Fix Match
        # button and a caution-toned primary button survive into the
        # empty-ready view.
        workspace, _state = self._workspace_with_selected_state(
            tie_detected=True, needs_review=True
        )
        workspace._update_action_bar()
        self.assertFalse(workspace._fix_match_btn.isVisibleTo(workspace))
        self.assertEqual(workspace._queue_inline_btn.property("cssClass"), "caution")
        # Final-review fix: force the AutoMux button visible first so the
        # reset path's hide() call is actually exercised, not just trivially
        # true because it started out hidden.
        workspace._work_panel.automux_button.show()

        workspace._media_ctrl.batch_states.clear()
        workspace.refresh_from_controller()

        self.assertTrue(workspace._fix_match_btn.isVisibleTo(workspace))
        self.assertEqual(workspace._fix_match_btn.property("cssClass"), "secondary")
        self.assertEqual(workspace._queue_inline_btn.property("cssClass"), "primary")
        self.assertTrue(workspace._work_panel.automux_button.isHidden())
        workspace.close()

    def test_media_workspace_hides_single_season_badge_for_multi_season_preview(self):
        # NOTE: the "Season N" roster meta-line badge this test targeted was
        # removed by the GUI V4 roster spec (poster-forward layout, no
        # per-row meta line). Kept as a render-sanity check for this state
        # shape; the badge-specific assertion has no model equivalent.
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = [state]
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        state = ScanState(
            folder=Path("C:/library/tv/Example.Show.2024"),
            media_info={"id": 101, "name": "Example Show", "year": "2024"},
            preview_items=[
                PreviewItem(
                    original=Path(
                        "C:/library/tv/Example.Show.2024/Season 01/Example.Show.S01E01.mkv"
                    ),
                    new_name="Example Show (2024) - S01E01 - Pilot.mkv",
                    target_dir=Path("C:/library/tv/Example Show (2024)/Season 01"),
                    season=1,
                    episodes=[1],
                    status="OK",
                ),
                PreviewItem(
                    original=Path(
                        "C:/library/tv/Example.Show.2024/Season 02/Example.Show.S02E01.mkv"
                    ),
                    new_name="Example Show (2024) - S02E01 - Return.mkv",
                    target_dir=Path("C:/library/tv/Example Show (2024)/Season 02"),
                    season=2,
                    episodes=[1],
                    status="OK",
                ),
            ],
            scanned=True,
            checked=True,
            confidence=1.0,
            season_assignment=1,
        )
        workspace = MediaWorkspace(media_type="tv", media_controller=_FakeMediaController(state))
        workspace.show_ready()

        data = self._roster_row_data_for_index(workspace, 0)
        self.assertIsNotNone(data)
        self.assertEqual(data.title, state.display_name)

        workspace.close()

    def test_media_workspace_season_one_badge_only_shows_when_show_has_multiple_seasons(self):
        # NOTE: same spec removal as above — the "Season N" badge no longer
        # exists on the model. Kept as a render-sanity check across both
        # single- and multi-season completeness shapes.
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, states):
                self.command_gating = CommandGatingService()
                self.batch_states = states
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        def _state(name: str, completeness: CompletenessReport) -> ScanState:
            return ScanState(
                folder=Path(f"C:/library/tv/{name}"),
                media_info={"id": 101, "name": name, "year": "2024"},
                preview_items=[
                    PreviewItem(
                        original=Path(f"C:/library/tv/{name}/Season 01/{name}.S01E01.mkv"),
                        new_name=f"{name} (2024) - S01E01 - Pilot.mkv",
                        target_dir=Path(f"C:/library/tv/{name} (2024)/Season 01"),
                        season=1,
                        episodes=[1],
                        status="OK",
                    )
                ],
                completeness=completeness,
                scanned=True,
                checked=True,
                confidence=1.0,
                season_assignment=1,
            )

        single_season = _state(
            "Single Season",
            CompletenessReport(
                seasons={1: SeasonCompleteness(season=1, expected=1, matched=1, missing=[])},
                specials=None,
                total_expected=1,
                total_matched=1,
                total_missing=[],
            ),
        )
        multi_season = _state(
            "Multi Season",
            CompletenessReport(
                seasons={
                    1: SeasonCompleteness(season=1, expected=1, matched=1, missing=[]),
                    2: SeasonCompleteness(
                        season=2, expected=1, matched=0, missing=[(1, "Second Season")]
                    ),
                },
                specials=None,
                total_expected=2,
                total_matched=1,
                total_missing=[(2, 1, "Second Season")],
            ),
        )

        workspace = MediaWorkspace(
            media_type="tv",
            media_controller=_FakeMediaController([single_season, multi_season]),
        )
        workspace.show_ready()

        single_data = self._roster_row_data_for_index(workspace, 0)
        multi_data = self._roster_row_data_for_index(workspace, 1)
        self.assertIsNotNone(single_data)
        self.assertIsNotNone(multi_data)
        self.assertEqual(single_data.title, single_season.display_name)
        self.assertEqual(multi_data.title, multi_season.display_name)

        workspace.close()

    def test_media_workspace_roster_check_syncs_tv_episode_guide_without_file_checks(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = [state]
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        state = ScanState(
            folder=Path("C:/library/tv/Example.Show.2024"),
            media_info={"id": 101, "name": "Example Show", "year": "2024"},
            preview_items=[
                PreviewItem(
                    original=Path(
                        "C:/library/tv/Example.Show.2024/Season 01/Example.Show.S01E01.mkv"
                    ),
                    new_name="Example Show (2024) - S01E01 - Pilot.mkv",
                    target_dir=Path("C:/library/tv/Example Show (2024)/Season 01"),
                    season=1,
                    episodes=[1],
                    status="OK",
                )
            ],
            scanned=True,
            checked=False,
            confidence=1.0,
        )
        workspace = MediaWorkspace(media_type="tv", media_controller=_FakeMediaController(state))
        workspace.show_ready()

        workspace._set_roster_check_state(0, True)

        self.assertTrue(state.checked)
        self.assertTrue(state.check_vars["0"].get())
        # TV episode-guide rows never carry a per-file checkbox: the table model
        # only marks movie-file rows checkable.
        row_data = self._episode_row_data_for_preview_index(workspace, 0)
        self.assertIsNotNone(row_data)
        self.assertEqual(row_data.kind, "episode")
        self.assertFalse(row_data.checkable)

        workspace.close()

    def test_check_bindings_cover_mux_only_items(self):
        """Round6 §1: a correctly-named OK item (no rename needed) with an
        action-bearing mux plan is still queue-relevant. The check binding
        must be created and must follow state.checked, instead of staying
        False/absent because the item itself is not a renameable action."""
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = [state]
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        state = ScanState(
            folder=Path("C:/library/tv/Example.Show.2024"),
            media_info={"id": 101, "name": "Example Show", "year": "2024"},
            preview_items=[
                PreviewItem(
                    original=Path(
                        "C:/library/tv/Example.Show.2024/Season 01/Example Show (2024) - S01E01.mkv"
                    ),
                    new_name="Example Show (2024) - S01E01.mkv",
                    target_dir=Path("C:/library/tv/Example.Show.2024/Season 01"),
                    season=1,
                    episodes=[1],
                    status="OK",
                )
            ],
            scanned=True,
            checked=True,
            confidence=1.0,
        )
        self.assertFalse(state.preview_items[0].is_actionable)
        state.mux_plans[0] = {
            "track_decisions": [],
            "subtitle_merges": [
                {
                    "action": "merge",
                    "source_relative": "Example Show (2024) - S01E01.eng.srt",
                    "language": "eng",
                    "set_default": False,
                }
            ],
        }

        workspace = MediaWorkspace(media_type="tv", media_controller=_FakeMediaController(state))
        workspace.show_ready()

        self.assertIn("0", state.check_vars)
        self.assertTrue(state.checked)
        self.assertIs(state.check_vars["0"].get(), True)

        workspace.close()

    def test_check_all_checks_mux_only_items(self):
        """Round6 §1 follow-up: check_all() must not overwrite a mux-only
        item's binding with False. Its per-file predicate previously used
        preview.is_actionable directly, so a show whose only relevant file
        is mux-only ended up state.checked=True with the checkbox forced
        False in the same call."""
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = [state]
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        state = ScanState(
            folder=Path("C:/library/tv/Example.Show.2024"),
            media_info={"id": 101, "name": "Example Show", "year": "2024"},
            preview_items=[
                PreviewItem(
                    original=Path(
                        "C:/library/tv/Example.Show.2024/Season 01/Example Show (2024) - S01E01.mkv"
                    ),
                    new_name="Example Show (2024) - S01E01.mkv",
                    target_dir=Path("C:/library/tv/Example.Show.2024/Season 01"),
                    season=1,
                    episodes=[1],
                    status="OK",
                )
            ],
            scanned=True,
            checked=False,
            confidence=1.0,
        )
        self.assertFalse(state.preview_items[0].is_actionable)
        state.mux_plans[0] = {
            "track_decisions": [],
            "subtitle_merges": [
                {
                    "action": "merge",
                    "source_relative": "Example Show (2024) - S01E01.eng.srt",
                    "language": "eng",
                    "set_default": False,
                }
            ],
        }

        workspace = MediaWorkspace(media_type="tv", media_controller=_FakeMediaController(state))
        workspace._check_all()

        self.assertTrue(state.checked)
        self.assertIs(state.check_vars["0"].get(), True)

        workspace.close()

    def test_check_bindings_cover_mux_only_items_movie(self):
        """Final-round6-review fix: a movie ScanState whose only item is
        mux-only (correctly named, action-bearing mux plan, not opted out)
        must end up checked after the REAL check-toggle sync path
        (_set_state_checked -> MediaWorkspaceSyncCoordinator.set_state_checked)
        runs. That coordinator previously gated its binding.set() call on
        preview.is_actionable alone, so it stomped the binding back to False
        even though the show is queue-relevant via its mux plan."""
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = [state]
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.movie_library_states):
                    return self.movie_library_states[index]
                return None

            def sync_queued_states(self):
                return None

        original = Path("C:/library/movies/Example Movie (2024)/Example Movie (2024).mkv")
        state = ScanState(
            folder=original.parent,
            media_info={
                "id": 101,
                "title": "Example Movie",
                "year": "2024",
                "_media_type": "movie",
            },
            preview_items=[
                PreviewItem(
                    original=original,
                    new_name="Example Movie (2024).mkv",
                    target_dir=original.parent,
                    season=None,
                    episodes=[],
                    status="OK",
                    media_type="movie",
                    media_id=101,
                    media_name="Example Movie",
                )
            ],
            scanned=True,
            checked=False,
            confidence=1.0,
        )
        self.assertFalse(state.preview_items[0].is_actionable)
        state.mux_plans[0] = {
            "track_decisions": [],
            "subtitle_merges": [
                {
                    "action": "merge",
                    "source_relative": "Example Movie (2024).eng.srt",
                    "language": "eng",
                    "set_default": False,
                }
            ],
        }

        workspace = MediaWorkspace(media_type="movie", media_controller=_FakeMediaController(state))
        workspace.show_ready()

        workspace._set_state_checked(state, True)

        self.assertIn("0", state.check_vars)
        self.assertTrue(state.checked)
        self.assertIs(state.check_vars["0"].get(), True)
        self.assertIn(0, get_checked_indices_from_state(state))

        workspace.close()

    def test_auto_check_for_queue_covers_mux_only_item(self):
        """Final-round6-review fix: _auto_check_for_queue (the Approve All
        Episode Mappings pre-tick helper) previously gated its binding.set()
        call on item.is_actionable alone, so a mux-only, correctly-named
        file was never pre-ticked even though it is queue-relevant via its
        mux plan."""
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = [state]
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        state = ScanState(
            folder=Path("C:/library/tv/Example.Show.2024"),
            media_info={"id": 101, "name": "Example Show", "year": "2024"},
            preview_items=[
                PreviewItem(
                    original=Path(
                        "C:/library/tv/Example.Show.2024/Season 01/Example Show (2024) - S01E01.mkv"
                    ),
                    new_name="Example Show (2024) - S01E01.mkv",
                    target_dir=Path("C:/library/tv/Example.Show.2024/Season 01"),
                    season=1,
                    episodes=[1],
                    status="OK",
                )
            ],
            scanned=True,
            checked=False,
            confidence=1.0,
        )
        self.assertFalse(state.preview_items[0].is_actionable)
        state.mux_plans[0] = {
            "track_decisions": [],
            "subtitle_merges": [
                {
                    "action": "merge",
                    "source_relative": "Example Show (2024) - S01E01.eng.srt",
                    "language": "eng",
                    "set_default": False,
                }
            ],
        }

        workspace = MediaWorkspace(media_type="tv", media_controller=_FakeMediaController(state))
        workspace.show_ready()

        workspace._action_coordinator._auto_check_for_queue(state)

        self.assertIn("0", state.check_vars)
        self.assertTrue(state.checked)
        self.assertIs(state.check_vars["0"].get(), True)

        workspace.close()

    def test_media_workspace_approved_movie_auto_checks_preview_file(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = [state]
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.movie_library_states):
                    return self.movie_library_states[index]
                return None

            def sync_queued_states(self):
                return None

            def approve_match(self, state):
                state.match_origin = "manual"
                for binding in state.check_vars.values():
                    binding.set(False)

        state = ScanState(
            folder=Path("C:/library/movies/Example Movie"),
            media_info={
                "id": 101,
                "title": "Example Movie",
                "year": "2024",
                "_media_type": "movie",
            },
            preview_items=[
                PreviewItem(
                    original=Path("C:/library/movies/Example Movie/Example.Movie.2024.mkv"),
                    new_name="Example Movie (2024).mkv",
                    target_dir=Path("C:/library/movies/Example Movie (2024)"),
                    season=None,
                    episodes=[],
                    status="REVIEW: verify",
                    media_type="movie",
                    media_id=101,
                    media_name="Example Movie",
                )
            ],
            scanned=True,
            checked=False,
            confidence=0.42,
        )
        workspace = MediaWorkspace(media_type="movie", media_controller=_FakeMediaController(state))
        workspace.show_ready()

        workspace._approve_match(state)

        self.assertFalse(state.checked)
        self.assertFalse(state.check_vars["0"].get())

        workspace.close()

    def test_media_workspace_uses_inline_assign_season_for_duplicate_tv_items(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = [state]
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        state = ScanState(
            folder=Path("C:/library/tv/Duplicate.Show.2024"),
            media_info={"id": 101, "name": "Duplicate Show", "year": "2024"},
            preview_items=[],
            scanned=True,
            checked=False,
            confidence=0.95,
            duplicate_of="Duplicate Show (2024)",
            alternate_matches=[{"id": 202, "name": "Other Show", "year": "2023"}],
        )
        media_ctrl = _FakeMediaController(state)
        workspace = MediaWorkspace(media_type="tv", media_controller=media_ctrl)
        workspace.show_ready()

        data = self._roster_row_data_for_index(workspace, 0)
        self.assertIsNotNone(data)
        self.assertEqual(workspace._queue_inline_btn.text(), "Assign Season")
        self.assertTrue(workspace._fix_match_btn.isEnabled())

        workspace.close()

    def test_media_workspace_inline_assign_season_swaps_to_queue_action(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = [state]
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

            def assign_season(self, state, season_num):
                state.season_assignment = season_num
                state.duplicate_of = None
                state.duplicate_of_relative_folder = None
                state.checked = True

        state = ScanState(
            folder=Path("C:/library/tv/Duplicate.Show.2024"),
            media_info={"id": 101, "name": "Duplicate Show", "year": "2024"},
            preview_items=[],
            scanned=True,
            checked=False,
            confidence=0.95,
            duplicate_of="Duplicate Show (2024)",
        )
        media_ctrl = _FakeMediaController(state)
        workspace = MediaWorkspace(media_type="tv", media_controller=media_ctrl)
        workspace.show_ready()

        self.assertEqual(workspace._queue_inline_btn.text(), "Assign Season")
        with patch(
            "plex_renamer.gui_qt.widgets.media_workspace.QInputDialog.getInt",
            return_value=(2, True),
        ):
            workspace._activate_selected_primary_action()

        self.assertEqual(state.season_assignment, 2)
        self.assertEqual(workspace._queue_inline_btn.text(), "Queue This Show")
        self._assert_roster_section_title(workspace, 0, "MATCHED")

        workspace.close()

    def test_media_workspace_roster_deselect_all_persists_after_refresh(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, states):
                self.command_gating = CommandGatingService()
                self.batch_states = states
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        states = [
            ScanState(
                folder=Path("C:/library/tv/Example.Show.2024"),
                media_info={"id": 101, "name": "Example Show", "year": "2024"},
                preview_items=[],
                scanned=True,
                checked=True,
                confidence=1.0,
            ),
            ScanState(
                folder=Path("C:/library/tv/Second.Show.2024"),
                media_info={"id": 102, "name": "Second Show", "year": "2024"},
                preview_items=[],
                scanned=True,
                checked=True,
                confidence=1.0,
            ),
        ]
        media_ctrl = _FakeMediaController(states)
        workspace = MediaWorkspace(media_type="tv", media_controller=media_ctrl)
        workspace.show_ready()

        workspace._roster_master_check.setCheckState(Qt.CheckState.Unchecked)
        workspace.refresh_from_controller()

        self.assertFalse(states[0].checked)
        self.assertFalse(states[1].checked)
        self.assertEqual(workspace._roster_queue_btn.text(), "Queue Checked")
        self.assertFalse(workspace._roster_queue_btn.isEnabled())

        workspace.close()

    def test_media_workspace_queue_checked_preserves_unchecked_matched_rows(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeQueueController:
            def add_tv_batch(
                self,
                states,
                root,
                output_root,
                gating,
                settings_service=None,
                tmdb_client=None,
                progress=None,
            ):
                for state in states:
                    state.queued = True
                return BatchQueueResult(added=len(states))

        class _FakeMediaController:
            def __init__(self, states):
                self.command_gating = CommandGatingService()
                self.batch_states = states
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        first = ScanState(
            folder=Path("C:/library/tv/Matched.Show.2024"),
            media_info={"id": 101, "name": "Matched Show", "year": "2024"},
            preview_items=[
                PreviewItem(
                    original=Path(
                        "C:/library/tv/Matched.Show.2024/Season 01/Matched.Show.S01E01.mkv"
                    ),
                    new_name="Matched Show (2024) - S01E01 - Pilot.mkv",
                    target_dir=Path("C:/library/tv/Matched Show (2024)/Season 01"),
                    season=1,
                    episodes=[1],
                    status="OK",
                )
            ],
            scanned=True,
            checked=True,
            confidence=1.0,
        )
        second = ScanState(
            folder=Path("C:/library/tv/Unchecked.Show.2024"),
            media_info={"id": 102, "name": "Unchecked Show", "year": "2024"},
            preview_items=[
                PreviewItem(
                    original=Path(
                        "C:/library/tv/Unchecked.Show.2024/Season 01/Unchecked.Show.S01E01.mkv"
                    ),
                    new_name="Unchecked Show (2024) - S01E01 - Pilot.mkv",
                    target_dir=Path("C:/library/tv/Unchecked Show (2024)/Season 01"),
                    season=1,
                    episodes=[1],
                    status="OK",
                )
            ],
            scanned=True,
            checked=False,
            confidence=1.0,
        )
        media_ctrl = _FakeMediaController([first, second])
        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
            output = Path(tmp) / "tv-output"
            output.mkdir()
            settings.tv_output_folder = str(output)
            workspace = MediaWorkspace(
                media_type="tv",
                media_controller=media_ctrl,
                queue_controller=_FakeQueueController(),
                settings_service=settings,
            )
            workspace.show_ready()

            workspace._queue_checked()

            self.assertTrue(first.queued)
            self.assertFalse(second.checked)
            self._assert_roster_section_title(workspace, 0, "QUEUED")
            self._assert_roster_section_title(workspace, 2, "MATCHED")

            workspace.close()

    def test_media_workspace_fix_match_refreshes_duplicate_tv_preview(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeTMDB:
            def search_tv(self, *_args, **_kwargs):
                return []

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = [state]
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

            def rematch_tv_state(self, state, chosen, tmdb=None):
                state.media_info = chosen
                state.duplicate_of = None
                state.duplicate_of_relative_folder = None
                state.preview_items = []
                state.scanned = False
                state.checked = True
                return state

            def scan_show(self, state, _tmdb):
                state.preview_items = [
                    PreviewItem(
                        original=Path(
                            "C:/library/tv/Duplicate.Show.2024/Season 01/Duplicate.Show.S01E01.mkv"
                        ),
                        new_name="Replacement Show (2024) - S01E01 - Pilot.mkv",
                        target_dir=Path("C:/library/tv/Replacement Show (2024)/Season 01"),
                        season=1,
                        episodes=[1],
                        status="OK",
                    )
                ]
                state.scanned = True
                state.selected_index = 0

        state = ScanState(
            folder=Path("C:/library/tv/Duplicate.Show.2024"),
            media_info={"id": 101, "name": "Original Show", "year": "2024"},
            preview_items=[
                PreviewItem(
                    original=Path(
                        "C:/library/tv/Duplicate.Show.2024/Season 01/Duplicate.Show.S01E01.mkv"
                    ),
                    new_name="Original Show (2024) - S01E01 - Pilot.mkv",
                    target_dir=Path("C:/library/tv/Original Show (2024)/Season 01"),
                    season=1,
                    episodes=[1],
                    status="OK",
                )
            ],
            scanned=True,
            checked=False,
            confidence=0.91,
            duplicate_of="Original Show (2024)",
        )
        media_ctrl = _FakeMediaController(state)
        workspace = MediaWorkspace(
            media_type="tv",
            media_controller=media_ctrl,
            tmdb_provider=_FakeTMDB,
        )
        workspace.show_ready()

        before_data = self._episode_row_data_for_preview_index(workspace, 0)
        self.assertIsNotNone(before_data)
        self.assertIn("Original Show (2024)", before_data.target)

        chosen = {"id": 202, "name": "Replacement Show", "year": "2024"}
        with patch(
            "plex_renamer.gui_qt.widgets.media_workspace.MatchPickerDialog.pick",
            return_value=chosen,
        ):
            workspace._fix_match()

        after_data = self._episode_row_data_for_preview_index(workspace, 0)
        self.assertIsNotNone(after_data)
        self.assertIn("Replacement Show (2024)", after_data.target)
        self.assertEqual(workspace._queue_inline_btn.text(), "Queue This Show")
        self._assert_roster_section_title(workspace, 0, "MATCHED")

        workspace.close()

    def test_media_workspace_blocks_duplicate_movie_approval(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = [state]
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")
                self.approved: list[ScanState] = []

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.movie_library_states):
                    return self.movie_library_states[index]
                return None

            def sync_queued_states(self):
                return None

            def approve_match(self, state):
                self.approved.append(state)

        state = ScanState(
            folder=Path("C:/library/movies/Example Movie"),
            media_info={
                "id": 101,
                "title": "Example Movie",
                "year": "2024",
                "_media_type": "movie",
            },
            preview_items=[],
            scanned=True,
            checked=False,
            confidence=0.42,
            duplicate_of="Primary Movie (2024)",
        )
        media_ctrl = _FakeMediaController(state)
        workspace = MediaWorkspace(media_type="movie", media_controller=media_ctrl)
        workspace.show_ready()

        data = self._roster_row_data_for_index(workspace, 0)
        self.assertIsNotNone(data)

        with patch.object(workspace, "refresh_from_controller") as refresh_mock:
            workspace._approve_match(state)

        self.assertEqual(media_ctrl.approved, [])
        refresh_mock.assert_not_called()
        workspace.close()

    def test_media_workspace_groups_movie_review_duplicates_under_needs_review(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, states):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = states
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.movie_library_states):
                    return self.movie_library_states[index]
                return None

            def sync_queued_states(self):
                return None

        matched_state = ScanState(
            folder=Path("C:/library/movies/Arrival.2016"),
            media_info={"id": 22, "title": "Arrival", "year": "2016", "_media_type": "movie"},
            preview_items=[
                PreviewItem(
                    original=Path("C:/library/movies/Arrival.2016/Arrival.2016.mkv"),
                    new_name="Arrival (2016).mkv",
                    target_dir=Path("C:/library/movies/Arrival (2016)"),
                    season=None,
                    episodes=[],
                    status="OK",
                    media_type="movie",
                    media_id=22,
                    media_name="Arrival",
                )
            ],
            scanned=True,
            checked=True,
            confidence=1.0,
        )
        review_duplicate = ScanState(
            folder=Path("C:/library/movies/Arrival.Source"),
            media_info={"id": 22, "title": "Arrival", "year": "2016", "_media_type": "movie"},
            preview_items=[
                PreviewItem(
                    original=Path("C:/library/movies/Arrival.Source/Arrival.2016.1080p.mkv"),
                    new_name="Arrival (2016).mkv",
                    target_dir=Path("C:/library/movies/Arrival (2016)"),
                    season=None,
                    episodes=[],
                    status="REVIEW: verify",
                    media_type="movie",
                    media_id=22,
                    media_name="Arrival",
                )
            ],
            scanned=True,
            checked=False,
            confidence=0.42,
            duplicate_of="Arrival (2016)",
            duplicate_of_relative_folder="Arrival (2016)",
        )
        media_ctrl = _FakeMediaController([matched_state, review_duplicate])
        workspace = MediaWorkspace(media_type="movie", media_controller=media_ctrl)
        workspace.show_ready()

        self._assert_roster_section_title(workspace, 0, "MATCHED")
        self._assert_roster_section_title(workspace, 2, "DUPLICATES")

        workspace.close()

    def test_media_workspace_labels_season_zero_preview_as_specials(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = [state]
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        state = ScanState(
            folder=Path("C:/library/tv/Yuru Camp Specials"),
            media_info={"id": 303, "name": "Yuru Camp", "year": "2018"},
            preview_items=[
                PreviewItem(
                    original=Path("C:/library/tv/Yuru Camp Specials/Campfire Talk.mkv"),
                    new_name="Yuru Camp (2018) - S00E01 - Campfire Talk.mkv",
                    target_dir=Path("C:/library/tv/Yuru Camp (2018)/Season 00"),
                    season=0,
                    episodes=[1],
                    status="OK",
                )
            ],
            scanned=True,
            checked=True,
            confidence=1.0,
        )
        workspace = MediaWorkspace(media_type="tv", media_controller=_FakeMediaController(state))
        workspace.show_ready()

        self.assertTrue(
            any("SPECIALS" in text.upper() for text in self._episode_section_titles(workspace))
        )

        workspace.close()

    def test_media_workspace_roster_master_checkbox_controls_eligible_states(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, states):
                self.command_gating = CommandGatingService()
                self.batch_states = states
                self.movie_library_states = []
                self.library_selected_index = 0
                self.active_scan = states[0]
                self.tv_root_folder = Path("C:/library/tv")
                self.movie_folder = Path("C:/library/movies")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    self.active_scan = self.batch_states[index]
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        state_a = ScanState(
            folder=Path("C:/library/tv/ShowA"),
            media_info={"id": 1, "name": "Show A", "year": "2020"},
            preview_items=[
                PreviewItem(
                    original=Path("C:/library/tv/ShowA/Season 01/ShowA.S01E01.mkv"),
                    new_name="Show A (2020) - S01E01 - Pilot.mkv",
                    target_dir=Path("C:/library/tv/Show A (2020)/Season 01"),
                    season=1,
                    episodes=[1],
                    status="OK",
                )
            ],
            scanned=True,
            checked=False,
            confidence=1.0,
        )
        state_b = ScanState(
            folder=Path("C:/library/tv/ShowB"),
            media_info={"id": 2, "name": "Show B", "year": "2021"},
            preview_items=[
                PreviewItem(
                    original=Path("C:/library/tv/ShowB/Season 01/ShowB.S01E01.mkv"),
                    new_name="Show B (2021) - S01E01 - Pilot.mkv",
                    target_dir=Path("C:/library/tv/Show B (2021)/Season 01"),
                    season=1,
                    episodes=[1],
                    status="OK",
                )
            ],
            scanned=True,
            checked=False,
            confidence=1.0,
        )

        workspace = MediaWorkspace(
            media_type="tv",
            media_controller=_FakeMediaController([state_a, state_b]),
            queue_controller=type(
                "Q", (), {"add_tv_batch": lambda *args, **kwargs: BatchQueueResult(added=2)}
            )(),
        )
        workspace.show_ready()

        workspace._roster_master_check.click()

        self.assertTrue(state_a.checked)
        self.assertTrue(state_b.checked)
        self.assertEqual(workspace._roster_master_check.checkState(), Qt.CheckState.Checked)

        workspace._roster_master_check.click()

        self.assertFalse(state_a.checked)
        self.assertFalse(state_b.checked)
        self.assertEqual(workspace._roster_master_check.checkState(), Qt.CheckState.Unchecked)

        workspace.close()

    def test_media_workspace_populates_roster_and_preview(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = []
                self.library_selected_index = None
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                states = self.movie_library_states
                if 0 <= index < len(states):
                    return states[index]
                return None

            def sync_queued_states(self):
                return None

        class _FakeQueueController:
            def __init__(self):
                self.called = False

            def add_movie_batch(
                self,
                states,
                root,
                output_root,
                command_gating,
                settings_service=None,
                tmdb_client=None,
                progress=None,
            ):
                self.called = True
                return BatchQueueResult(added=len(states))

        media_ctrl = _FakeMediaController()
        queue_ctrl = _FakeQueueController()
        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
            output = Path(tmp) / "movie-output"
            output.mkdir()
            settings.movie_output_folder = str(output)
            ready_state = ScanState(
                folder=Path("C:/library/movies/Dune.Part.Two.2024"),
                media_info={"id": 11, "title": "Dune: Part Two", "year": "2024"},
                preview_items=[
                    PreviewItem(
                        original=Path(
                            "C:/library/movies/Dune.Part.Two.2024/Dune.Part.Two.2024.mkv"
                        ),
                        new_name="Dune: Part Two (2024).mkv",
                        target_dir=Path("C:/library/movies/Dune: Part Two (2024)"),
                        season=None,
                        episodes=[],
                        status="OK",
                        media_type="movie",
                        media_id=11,
                        media_name="Dune: Part Two",
                        companions=[],
                    )
                ],
                scanned=True,
                checked=True,
                confidence=1.0,
            )
            matched_state = ScanState(
                folder=Path("C:/library/movies/Arrival.2016"),
                media_info={"id": 22, "title": "Arrival", "year": "2016"},
                preview_items=[
                    PreviewItem(
                        original=Path("C:/library/movies/Arrival.2016/Arrival.2016.mkv"),
                        new_name="Arrival (2016).mkv",
                        target_dir=Path("C:/library/movies/Arrival (2016)"),
                        season=None,
                        episodes=[],
                        status="OK",
                        media_type="movie",
                        media_id=22,
                        media_name="Arrival",
                        companions=[],
                    )
                ],
                scanned=False,
                checked=False,
                confidence=1.0,
            )
            media_ctrl.movie_library_states = [ready_state, matched_state]

            workspace = MediaWorkspace(
                media_type="movie",
                media_controller=media_ctrl,
                queue_controller=queue_ctrl,
                settings_service=settings,
            )
            workspace.show_ready()

            self.assertEqual(workspace._roster_panel.model.rowCount(), 3)
            self._assert_roster_section_title(workspace, 0, "MATCHED")
            self.assertIsNone(
                workspace._roster_panel.model.index(1, 0).data(Qt.ItemDataRole.CheckStateRole)
            )
            self.assertGreater(workspace._work_panel.model.rowCount(), 0)
            folder_target = self._folder_section_target(workspace)
            self.assertIsNotNone(folder_target)
            self.assertIn("2024", folder_target)

            workspace._queue_checked()
            self.assertTrue(queue_ctrl.called)

            workspace.close()

    def test_media_workspace_groups_movie_duplicates_once(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = []
                self.library_selected_index = None
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.movie_library_states):
                    return self.movie_library_states[index]
                return None

            def sync_queued_states(self):
                return None

        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
            matched_state = ScanState(
                folder=Path("C:/library/movies/Alien.1979"),
                media_info={"id": 42, "title": "Alien", "year": "1979", "_media_type": "movie"},
                preview_items=[
                    PreviewItem(
                        original=Path("C:/library/movies/Alien.1979/Alien.1979.mkv"),
                        new_name="Alien (1979).mkv",
                        target_dir=Path("C:/library/movies/Alien (1979)"),
                        season=None,
                        episodes=[],
                        status="OK",
                        media_type="movie",
                        media_id=42,
                        media_name="Alien",
                    )
                ],
                scanned=True,
                checked=True,
                confidence=1.0,
            )
            duplicate_state = ScanState(
                folder=Path("C:/library/movies/Alien.Source"),
                media_info={"id": 42, "title": "Alien", "year": "1979", "_media_type": "movie"},
                preview_items=[
                    PreviewItem(
                        original=Path("C:/library/movies/Alien.Source/Alien.1979.1080p.mkv"),
                        new_name="Alien (1979).mkv",
                        target_dir=Path("C:/library/movies/Alien (1979)"),
                        season=None,
                        episodes=[],
                        status="OK",
                        media_type="movie",
                        media_id=42,
                        media_name="Alien",
                    )
                ],
                scanned=True,
                checked=False,
                confidence=1.0,
                duplicate_of="Alien (1979)",
                duplicate_of_relative_folder="Alien (1979)",
            )
            media_ctrl = _FakeMediaController()
            media_ctrl.movie_library_states = [matched_state, duplicate_state]

            workspace = MediaWorkspace(
                media_type="movie",
                media_controller=media_ctrl,
                queue_controller=type(
                    "Q", (), {"add_movie_batch": lambda *args, **kwargs: BatchQueueResult(added=1)}
                )(),
                settings_service=settings,
            )
            workspace.show_ready()

            self.assertEqual(workspace._roster_panel.model.rowCount(), 4)
            self._assert_roster_section_title(workspace, 0, "MATCHED")
            self._assert_roster_section_title(workspace, 2, "DUPLICATES")
            self.assertIsNotNone(self._roster_row_data_for_index(workspace, 0))
            self.assertIsNotNone(self._roster_row_data_for_index(workspace, 1))

            workspace.close()

    def test_media_workspace_applies_live_display_settings(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = []
                self.library_selected_index = None
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                states = self.movie_library_states
                if 0 <= index < len(states):
                    return states[index]
                return None

            def sync_queued_states(self):
                return None

        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
            state = ScanState(
                folder=Path("C:/library/movies/Arrival.2016"),
                media_info={"id": 22, "title": "Arrival", "year": "2016"},
                preview_items=[
                    PreviewItem(
                        original=Path("C:/library/movies/Arrival.2016/Arrival.2016.mkv"),
                        new_name="Arrival (2016).mkv",
                        target_dir=Path("C:/library/movies/Arrival (2016)"),
                        season=None,
                        episodes=[],
                        status="OK",
                        media_type="movie",
                        media_id=22,
                        media_name="Arrival",
                        companions=[],
                    )
                ],
                scanned=True,
                checked=True,
                confidence=1.0,
            )
            state.preview_items[0].companions = [
                CompanionFile(
                    original=Path("C:/library/movies/Arrival.2016/Arrival.2016.en.srt"),
                    new_name="Arrival (2016).en.srt",
                    file_type="subtitle",
                )
            ]

            media_ctrl = _FakeMediaController()
            media_ctrl.movie_library_states = [state]

            workspace = MediaWorkspace(
                media_type="movie",
                media_controller=media_ctrl,
                queue_controller=type(
                    "Q", (), {"add_movie_batch": lambda *args, **kwargs: BatchQueueResult(added=1)}
                )(),
                settings_service=settings,
            )
            workspace.show_ready()

            row_data = self._episode_row_data_for_preview_index(workspace, 0)
            self.assertIsNotNone(row_data)
            self.assertEqual(row_data.target, "Arrival (2016).mkv")

            settings.view_mode = "compact"
            settings.show_companion_files = True
            workspace.apply_settings()

            row_data = self._episode_row_data_for_preview_index(workspace, 0)
            self.assertIsNotNone(row_data)
            self.assertEqual(row_data.target, "Arrival (2016).mkv")
            self.assertEqual(row_data.companion_count, 1)
            # Movie rows are flat (GUI V4 Plan 3 round-2 Task 1): no
            # expansion chevron, so companion filenames are not surfaced via
            # an expansion card for movies — companion_count above is the
            # movie row's only companion signal.
            movie_row = workspace._work_panel.model.row_for_preview_index(0)
            card = self._open_expansion_card(workspace, movie_row)
            self.assertIsNone(card)
            self.assertTrue(workspace._roster_panel.is_compact())

            workspace.close()

    def test_media_workspace_tv_episode_guide_groups_companions_and_missing_rows(self):
        from PySide6.QtWidgets import QLabel

        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = [state]
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        subtitle = CompanionFile(
            original=Path("C:/library/tv/Example/Season 01/Example.S01E01.en.srt"),
            new_name="Example Show (2024) - S01E01 - Pilot.en.srt",
            file_type="subtitle",
        )
        state = ScanState(
            folder=Path("C:/library/tv/Example"),
            media_info={"id": 101, "name": "Example Show", "year": "2024"},
            preview_items=[
                PreviewItem(
                    original=Path("C:/library/tv/Example/Season 01/Example.S01E01.mkv"),
                    new_name="Example Show (2024) - S01E01 - Pilot.mkv",
                    target_dir=Path("C:/library/tv/Example Show (2024)/Season 01"),
                    season=1,
                    episodes=[1],
                    status="OK",
                    companions=[subtitle],
                )
            ],
            completeness=CompletenessReport(
                seasons={
                    1: SeasonCompleteness(
                        season=1,
                        expected=2,
                        matched=1,
                        missing=[(2, "Second")],
                        matched_episodes=[(1, "Pilot")],
                    ),
                    2: SeasonCompleteness(
                        season=2,
                        expected=1,
                        matched=0,
                        missing=[(1, "A Missing Start")],
                        matched_episodes=[],
                    ),
                },
                specials=None,
                total_expected=3,
                total_matched=1,
                total_missing=[(1, 2, "Second"), (2, 1, "A Missing Start")],
            ),
            scanned=True,
            checked=True,
            confidence=1.0,
        )

        workspace = MediaWorkspace(media_type="tv", media_controller=_FakeMediaController(state))
        workspace.show_ready()

        # TV mode: the movie-style master check + its summary are hidden.
        self.assertTrue(workspace._work_panel.master_check.isHidden())
        self.assertTrue(workspace._work_panel.check_summary.isHidden())
        self.assertFalse(hasattr(workspace, "_queue_preflight_label"))
        titles = self._episode_section_titles(workspace)
        self.assertFalse(any("EPISODE GUIDE:" in title.upper() for title in titles))
        self.assertTrue(any(title.upper().startswith("SEASON 1") for title in titles))
        self.assertTrue(any(title.upper().startswith("SEASON 2") for title in titles))
        # Season 1 has a mapped episode (expanded); Season 2 is fully missing
        # and auto-collapses.
        self.assertFalse(self._episode_section_collapsed(workspace, "SEASON 1"))
        self.assertTrue(self._episode_section_collapsed(workspace, "SEASON 2"))

        mapped_data = self._episode_row_data_for_preview_index(workspace, 0)
        self.assertIsNotNone(mapped_data)
        self.assertFalse(mapped_data.checkable)
        self.assertEqual(mapped_data.status_text, "Mapped")
        self.assertEqual(mapped_data.companion_count, 1)
        self.assertEqual(mapped_data.confidence_pct, 100)
        # Companion filenames now live on the expansion card.
        mapped_row = workspace._work_panel.model.row_for_preview_index(0)
        card = self._open_expansion_card(workspace, mapped_row)
        self.assertIsNotNone(card)
        card_text = " ".join(label.text() for label in card.findChildren(QLabel))
        self.assertIn("Example.S01E01.en.srt", card_text)

        statuses = [data.status_text for data in self._episode_row_datas(workspace)]
        titles_all = [data.title for data in self._episode_row_datas(workspace)]
        self.assertIn("Missing File", statuses)
        self.assertNotIn("S02E01 · A Missing Start", titles_all)

        workspace.close()

    def test_media_workspace_tv_episode_guide_uses_queue_style_season_arrows(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = [state]
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        state = ScanState(
            folder=Path("C:/library/tv/Example"),
            media_info={"id": 101, "name": "Example Show", "year": "2024"},
            preview_items=[
                PreviewItem(
                    original=Path("C:/library/tv/Example/Season 01/Example.S01E01.mkv"),
                    new_name="Example Show (2024) - S01E01 - Pilot.mkv",
                    target_dir=Path("C:/library/tv/Example Show (2024)/Season 01"),
                    season=1,
                    episodes=[1],
                    status="OK",
                ),
            ],
            completeness=CompletenessReport(
                seasons={
                    1: SeasonCompleteness(season=1, expected=1, matched=1, missing=[]),
                    2: SeasonCompleteness(season=2, expected=1, matched=0, missing=[(1, "Second")]),
                },
                specials=None,
                total_expected=2,
                total_matched=1,
                total_missing=[(2, 1, "Second")],
            ),
            scanned=True,
            confidence=1.0,
        )

        workspace = MediaWorkspace(media_type="tv", media_controller=_FakeMediaController(state))
        workspace.show()
        workspace.show_ready()
        self._app.processEvents()

        titles = self._episode_section_titles(workspace)

        self.assertTrue(any(title.upper().startswith("SEASON 1") for title in titles))
        self.assertTrue(any(title.upper().startswith("SEASON 2") for title in titles))
        # Season 1 is complete/expanded; season 2 is fully missing and collapsed.
        self.assertFalse(self._episode_section_collapsed(workspace, "SEASON 1"))
        self.assertTrue(self._episode_section_collapsed(workspace, "SEASON 2"))

        workspace.close()

    def test_media_workspace_episode_header_toggle_uses_controller_guide_provider(self):
        # GUI V4 Plan 3 Task 5: the old preview panel cached a built guide and
        # reused it across header toggles (asserting build_episode_guide fired
        # exactly once). The work panel's table model is stateless and rebuilds
        # on every toggle, sourcing the guide from the controller's
        # episode_guide_for_state provider — so the migrated invariant is that
        # toggling routes through that provider rather than an internal builder.
        from plex_renamer.app.services.episode_mapping_service import EpisodeMappingService
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = [state]
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")
                self.episode_guide_for_state = MagicMock(
                    return_value=EpisodeMappingService().build_episode_guide(state)
                )

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        state = ScanState(
            folder=Path("C:/library/tv/Example"),
            media_info={"id": 101, "name": "Example Show", "year": "2024"},
            preview_items=[
                PreviewItem(
                    original=Path("C:/library/tv/Example/Season 01/Example.S01E01.mkv"),
                    new_name="Example Show (2024) - S01E01 - Pilot.mkv",
                    target_dir=Path("C:/library/tv/Example Show (2024)/Season 01"),
                    season=1,
                    episodes=[1],
                    status="OK",
                )
            ],
            scanned=True,
            confidence=1.0,
        )
        media_ctrl = _FakeMediaController(state)
        workspace = MediaWorkspace(media_type="tv", media_controller=media_ctrl)
        workspace.show_ready()

        section_key = self._first_section_key(workspace)
        self.assertIsNotNone(section_key)
        workspace._on_table_section_toggled(section_key)
        workspace._on_table_section_toggled(section_key)

        media_ctrl.episode_guide_for_state.assert_called_with(state)
        workspace.close()

    def test_media_workspace_uses_controller_episode_guide_on_first_show_render(self):
        from plex_renamer.app.services.episode_mapping_service import EpisodeMappingService
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = [state]
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")
                self.episode_guide_for_state = MagicMock(
                    return_value=EpisodeMappingService().build_episode_guide(state)
                )

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        state = ScanState(
            folder=Path("C:/library/tv/Example"),
            media_info={"id": 101, "name": "Example Show", "year": "2024"},
            preview_items=[
                PreviewItem(
                    original=Path("C:/library/tv/Example/Season 01/Example.S01E01.mkv"),
                    new_name="Example Show (2024) - S01E01 - Pilot.mkv",
                    target_dir=Path("C:/library/tv/Example Show (2024)/Season 01"),
                    season=1,
                    episodes=[1],
                    status="OK",
                )
            ],
            scanned=True,
            confidence=1.0,
        )
        media_ctrl = _FakeMediaController(state)
        workspace = MediaWorkspace(media_type="tv", media_controller=media_ctrl)

        workspace.show_ready()

        media_ctrl.episode_guide_for_state.assert_called_with(state)
        workspace.close()

    def test_media_workspace_episode_header_toggle_hides_rows_without_rebuilding_preview(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = [state]
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        state = ScanState(
            folder=Path("C:/library/tv/Example"),
            media_info={"id": 101, "name": "Example Show", "year": "2024"},
            preview_items=[
                PreviewItem(
                    original=Path(f"C:/library/tv/Example/Season 01/Example.S01E{episode:02d}.mkv"),
                    new_name=f"Example Show (2024) - S01E{episode:02d} - Episode {episode}.mkv",
                    target_dir=Path("C:/library/tv/Example Show (2024)/Season 01"),
                    season=1,
                    episodes=[episode],
                    status="OK",
                )
                for episode in range(1, 6)
            ],
            scanned=True,
            confidence=1.0,
        )
        workspace = MediaWorkspace(media_type="tv", media_controller=_FakeMediaController(state))
        workspace.show_ready()
        # Toggling a section collapses via the table model's shared collapsed
        # set; it must NOT trigger a full work-panel re-render (show_in_work_panel).
        original_show = workspace._state_coordinator.show_in_work_panel
        workspace._state_coordinator.show_in_work_panel = MagicMock(wraps=original_show)
        section_key = self._first_section_key(workspace, prefix="episode-guide-season:")
        self.assertIsNotNone(section_key)

        workspace._on_table_section_toggled(section_key)

        workspace._state_coordinator.show_in_work_panel.assert_not_called()
        self.assertTrue(self._episode_section_collapsed(workspace, "SEASON 1"))
        # Collapsed season hides its episode rows.
        self.assertFalse(any(data.kind == "episode" for data in self._episode_row_datas(workspace)))
        workspace.close()

    def test_media_workspace_folder_header_toggle_hides_rows_without_rebuilding_preview(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = [state]
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        state = ScanState(
            folder=Path("C:/library/tv/Example"),
            media_info={"id": 101, "name": "Example Show", "year": "2024"},
            preview_items=[
                PreviewItem(
                    original=Path("C:/library/tv/Example/Season 01/Example.S01E01.mkv"),
                    new_name="Example Show (2024) - S01E01 - Pilot.mkv",
                    target_dir=Path("C:/library/tv/Example Show (2024)/Season 01"),
                    season=1,
                    episodes=[1],
                    status="OK",
                )
            ],
            scanned=True,
            confidence=1.0,
        )
        workspace = MediaWorkspace(media_type="tv", media_controller=_FakeMediaController(state))
        workspace.show_ready()
        original_show = workspace._state_coordinator.show_in_work_panel
        workspace._state_coordinator.show_in_work_panel = MagicMock(wraps=original_show)
        self.assertIsNotNone(self._folder_section_target(workspace))

        workspace._on_table_section_toggled("folder-preview")

        workspace._state_coordinator.show_in_work_panel.assert_not_called()
        self.assertTrue(self._episode_section_collapsed(workspace, "FOLDER"))
        # Collapsed folder section hides its folder row.
        self.assertIsNone(self._folder_section_target(workspace))
        workspace.close()

    def test_folder_preview_source_is_full_path(self):
        from plex_renamer.gui_qt.widgets._media_workspace_view import MediaWorkspaceViewCoordinator

        class _FakeWorkspace:
            _media_type = "tv"

        state = ScanState(
            folder=Path("C:/library/tv/Example.Show.2024"),
            media_info={"name": "Example Show", "year": "2024"},
        )
        coordinator = MediaWorkspaceViewCoordinator(_FakeWorkspace())
        result = coordinator.folder_preview_data(state)
        self.assertIsNotNone(result)
        source, target = result
        self.assertEqual(source, str(state.folder))  # absolute path, not .name
        self.assertEqual(target, "Example Show (2024)")

    def test_media_workspace_auto_collapsed_specials_header_expands_without_rebuilding_preview(
        self,
    ):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = [state]
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        state = ScanState(
            folder=Path("C:/library/tv/Example"),
            media_info={"id": 101, "name": "Example Show", "year": "2024"},
            preview_items=[
                PreviewItem(
                    original=Path("C:/library/tv/Example/Season 01/Example.S01E01.mkv"),
                    new_name="Example Show (2024) - S01E01 - Pilot.mkv",
                    target_dir=Path("C:/library/tv/Example Show (2024)/Season 01"),
                    season=1,
                    episodes=[1],
                    status="OK",
                )
            ],
            completeness=CompletenessReport(
                seasons={
                    1: SeasonCompleteness(
                        season=1,
                        expected=1,
                        matched=1,
                        missing=[],
                        matched_episodes=[(1, "Pilot")],
                    )
                },
                specials=SeasonCompleteness(
                    season=0,
                    expected=1,
                    matched=0,
                    missing=[(1, "Campfire Talk")],
                    matched_episodes=[],
                ),
                total_expected=2,
                total_matched=1,
                total_missing=[(0, 1, "Campfire Talk")],
            ),
            scanned=True,
            confidence=1.0,
        )
        workspace = MediaWorkspace(media_type="tv", media_controller=_FakeMediaController(state))
        workspace.show_ready()
        # Fully-missing specials auto-collapse: no S00 episode row is rendered.
        self.assertTrue(self._episode_section_collapsed(workspace, "SPECIALS"))
        self.assertFalse(
            any(data.title.startswith("S00") for data in self._episode_row_datas(workspace))
        )

        original_show = workspace._state_coordinator.show_in_work_panel
        workspace._state_coordinator.show_in_work_panel = MagicMock(wraps=original_show)

        workspace._on_table_section_toggled("episode-guide-season:0")

        workspace._state_coordinator.show_in_work_panel.assert_not_called()
        self.assertFalse(self._episode_section_collapsed(workspace, "SPECIALS"))
        # Expanding surfaces the missing special row.
        self.assertTrue(
            any(data.title.startswith("S00") for data in self._episode_row_datas(workspace))
        )
        workspace.close()

    def test_media_workspace_reselecting_show_renders_preview_rows_on_demand(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, states):
                self.command_gating = CommandGatingService()
                self.batch_states = states
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        def _state(title: str, show_id: int) -> ScanState:
            folder_name = title.replace(" ", ".")
            return ScanState(
                folder=Path(f"C:/library/tv/{folder_name}"),
                media_info={"id": show_id, "name": title, "year": "2024"},
                preview_items=[
                    PreviewItem(
                        original=Path(
                            f"C:/library/tv/{folder_name}/Season 01/{folder_name}.S01E{episode:02d}.mkv"
                        ),
                        new_name=f"{title} (2024) - S01E{episode:02d} - Episode {episode}.mkv",
                        target_dir=Path(f"C:/library/tv/{title} (2024)/Season 01"),
                        season=1,
                        episodes=[episode],
                        status="OK",
                    )
                    for episode in range(1, 4)
                ],
                scanned=True,
                confidence=1.0,
            )

        def _first_episode_target(workspace):
            for data in self._episode_row_datas(workspace):
                if data.kind == "episode":
                    return data.target
            return None

        first_state = _state("First Show", 101)
        second_state = _state("Second Show", 202)
        workspace = MediaWorkspace(
            media_type="tv",
            media_controller=_FakeMediaController([first_state, second_state]),
        )
        workspace.show_ready()
        # The work-panel model rebuilds rows on every show_state, so widget
        # identity is no longer reused across reselection (GUI V4 Plan 3 Task 5);
        # the migrated invariant is that reselection renders the SELECTED show's
        # rows and toggles still work.
        self.assertIn("First Show", _first_episode_target(workspace))

        panel = workspace._roster_panel
        second_row = panel.model.row_for_state_index(1)
        self.assertGreaterEqual(second_row, 0)
        panel.view.setCurrentIndex(panel.model.index(second_row, 0))
        self._app.processEvents()
        self.assertIn("Second Show", _first_episode_target(workspace))

        section_key = self._first_section_key(workspace, prefix="episode-guide-season:")
        self.assertIsNotNone(section_key)
        workspace._on_table_section_toggled(section_key)
        self.assertTrue(self._episode_section_collapsed(workspace, "SEASON 1"))

        first_row = panel.model.row_for_state_index(0)
        self.assertGreaterEqual(first_row, 0)
        panel.view.setCurrentIndex(panel.model.index(first_row, 0))
        self._app.processEvents()
        self.assertIn("First Show", _first_episode_target(workspace))
        workspace.close()

    def test_media_workspace_episode_approval_emits_approve_action(self):
        from plex_renamer.engine._episode_projection import project_preview_items
        from plex_renamer.engine.episode_assignments import (
            ORIGIN_AUTO,
            EpisodeAssignmentTable,
            EpisodeSlot,
        )
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = [state]
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")
                self.refresh_episode_guide = MagicMock()
                self.invalidate_episode_guide = MagicMock()

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        folder = Path("C:/library/tv/Example")
        show_info = {"id": 101, "name": "Example Show", "year": "2024"}
        table = EpisodeAssignmentTable()
        table.add_slot(EpisodeSlot(season=1, episode=1, title="Pilot"))
        entry = table.add_file(folder / "Season 01" / "Example.S01E01.mkv")
        table.assign(
            entry.file_id,
            1,
            [1],
            origin=ORIGIN_AUTO,
            confidence=0.5,
        )
        state = ScanState(
            folder=folder,
            media_info=show_info,
            scanned=True,
            confidence=1.0,
        )
        state.assignments = table
        state.preview_items = project_preview_items(
            table,
            show_info=show_info,
            root=folder,
            media_fields={"media_id": 101, "media_name": "Example Show"},
        )

        media_ctrl = _FakeMediaController(state)
        workspace = MediaWorkspace(media_type="tv", media_controller=media_ctrl)
        workspace.show_ready()

        # Find the review-status episode row and open its expansion card.
        review_preview_index = state.preview_items.index(
            next(p for p in state.preview_items if p.file_id == entry.file_id)
        )
        row_data = self._episode_row_data_for_preview_index(workspace, review_preview_index)
        self.assertIsNotNone(row_data)
        self.assertEqual(row_data.status_text, "Review")
        card_row = workspace._work_panel.model.row_for_preview_index(review_preview_index)
        card = self._open_expansion_card(workspace, card_row)
        self.assertIsNotNone(card)

        # Clicking approve dispatches through handle_episode_row_action → service.approve_file.
        approve_button = self._card_action_button(card, "approve")
        self.assertIsNotNone(approve_button)
        approve_button.click()
        self._app.processEvents()

        # After approval the projection reprojects: the row's status should flip to "OK".
        review_item = next(p for p in state.preview_items if p.file_id == entry.file_id)
        self.assertEqual(review_item.status, "OK")
        workspace.close()

    # ── helpers shared by row-action dispatch tests ──────────────────────────

    @staticmethod
    def _make_episode_table_state(folder=None, show_info=None):
        """Return (state, table, entry_id) with one auto-assigned file at S01E01."""
        from plex_renamer.engine._episode_projection import project_preview_items
        from plex_renamer.engine.episode_assignments import (
            ORIGIN_AUTO,
            EpisodeAssignmentTable,
            EpisodeSlot,
        )

        folder = folder or Path("C:/library/tv/Example")
        show_info = show_info or {"id": 101, "name": "Example Show", "year": "2024"}
        table = EpisodeAssignmentTable()
        table.add_slot(EpisodeSlot(season=1, episode=1, title="Pilot"))
        table.add_slot(EpisodeSlot(season=1, episode=2, title="Sequel"))
        entry = table.add_file(folder / "Season 01" / "Example.S01E01.mkv")
        table.assign(entry.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=0.5)
        state = ScanState(folder=folder, media_info=show_info, scanned=True, confidence=1.0)
        state.assignments = table
        state.preview_items = project_preview_items(
            table,
            show_info=show_info,
            root=folder,
            media_fields={"media_id": 101, "media_name": "Example Show"},
        )
        return state, table, entry.file_id

    @staticmethod
    def _make_fake_media_ctrl(state):
        class _FakeMediaController:
            def __init__(self, s):
                self.command_gating = CommandGatingService()
                self.batch_states = [s]
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")
                self.refresh_episode_guide = MagicMock()
                self.invalidate_episode_guide = MagicMock()

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        return _FakeMediaController(state)

    # ── grouping / classification tests ───────────────────────────────────────

    def test_specials_unmapped_only_grouping(self):
        from plex_renamer.engine.models import CompletenessReport, SeasonCompleteness
        from plex_renamer.gui_qt.widgets._media_helpers import roster_group

        complete_s1 = SeasonCompleteness(season=1, expected=2, matched=2, missing=[])
        incomplete_s1 = SeasonCompleteness(season=1, expected=3, matched=2, missing=[(3, "Three")])

        # A) regular seasons complete; one unmatched specials-ish extra file -> specials-unmapped
        state_a, _table_a, _file_id_a = (
            self._make_episode_table_state()
        )  # existing factory producing has_episode_problems=True
        state_a.completeness = CompletenessReport(
            seasons={1: complete_s1},
            specials=None,
            total_expected=2,
            total_matched=2,
            total_missing=[],
        )
        for item in state_a.preview_items:  # force problems onto non-regular rows
            if item.is_episode_review or item.is_unmatched or item.is_conflict:
                item.season = None
        self.assertEqual(roster_group(state_a, media_type="tv"), "specials-unmapped")

        # B) same problems but a regular season is incomplete -> stays review-episodes
        state_b, _table_b, _file_id_b = self._make_episode_table_state()
        state_b.completeness = CompletenessReport(
            seasons={1: incomplete_s1},
            specials=None,
            total_expected=3,
            total_matched=2,
            total_missing=[(1, 3, "Three")],
        )
        self.assertEqual(roster_group(state_b, media_type="tv"), "review-episodes")

        # C) a problem row on a regular season -> stays review-episodes
        state_c, _table_c, _file_id_c = self._make_episode_table_state()
        state_c.completeness = CompletenessReport(
            seasons={1: complete_s1},
            specials=None,
            total_expected=2,
            total_matched=2,
            total_missing=[],
        )
        for item in state_c.preview_items:
            if item.is_episode_review or item.is_unmatched or item.is_conflict:
                item.season = 1
        self.assertEqual(roster_group(state_c, media_type="tv"), "review-episodes")

    # ── dispatch tests ───────────────────────────────────────────────────────

    def test_episode_row_action_unassign_removes_file_assignment(self):
        """unassign: dialog-free; file moves from mapped to unassigned."""
        from plex_renamer.app.models.state_models import EpisodeGuideRow
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        state, table, file_id = self._make_episode_table_state()
        workspace = MediaWorkspace(
            media_type="tv",
            media_controller=self._make_fake_media_ctrl(state),
        )
        workspace.show_ready()

        preview = next(p for p in state.preview_items if p.file_id == file_id)
        row = EpisodeGuideRow(season=1, episode=1, title="Pilot", primary_file=preview)

        workspace._action_coordinator.handle_episode_row_action(state, row, "unassign")
        self._app.processEvents()

        # After unassign the file should have no assignment in the table.
        self.assertIsNone(table._assignments.get(file_id))
        # The reprojected preview_items should no longer carry a mapped entry for this file.
        remapped = next((p for p in state.preview_items if p.file_id == file_id), None)
        self.assertIsNotNone(remapped)
        self.assertIsNone(remapped.new_name)
        workspace.close()

    def test_inline_row_action_routes_missing_row_through_handle_episode_row_action(self):
        """M7: the inline "Assign file..." control on a missing-file row must
        route through the same handle_episode_row_action contract as the
        expansion card, without requiring the row to be expanded."""
        from plex_renamer.gui_qt.widgets._episode_table_model import ROW_DATA_ROLE
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        state, _table, _file_id = self._make_episode_table_state()
        # The fixture leaves S01E02 ("Sequel") unassigned; mark it missing via
        # completeness so the guide projects a "Missing File" row for it.
        state.completeness = CompletenessReport(
            seasons={
                1: SeasonCompleteness(season=1, expected=2, matched=1, missing=[(2, "Sequel")])
            },
            specials=None,
            total_expected=2,
            total_matched=1,
            total_missing=[(1, 2, "Sequel")],
        )
        workspace = MediaWorkspace(
            media_type="tv",
            media_controller=self._make_fake_media_ctrl(state),
        )
        workspace.show_ready()

        model = workspace._work_panel.model
        missing_row = next(
            row
            for row in range(model.rowCount())
            if (data := model.index(row, 0).data(ROW_DATA_ROLE)) is not None
            and data.status_text == "Missing File"
        )
        guide_row = model.guide_row_at(missing_row)
        self.assertIsNotNone(guide_row)
        index = model.index(missing_row, 0)

        with patch.object(
            workspace._action_coordinator, "handle_episode_row_action"
        ) as mock_handle:
            workspace._on_inline_row_action(index, "assign_file")

        mock_handle.assert_called_once_with(state, guide_row, "assign_file")
        workspace.close()

    @staticmethod
    def _make_unmapped_file_state():
        """Return (state, table) with one unassigned file (-> an "unmapped"
        row) and an open slot to assign it into."""
        from plex_renamer.engine._episode_projection import project_preview_items
        from plex_renamer.engine.episode_assignments import (
            EpisodeAssignmentTable,
            EpisodeSlot,
        )

        folder = Path("C:/library/tv/Example")
        show_info = {"id": 101, "name": "Example Show", "year": "2024"}
        table = EpisodeAssignmentTable()
        table.add_slot(EpisodeSlot(season=1, episode=1, title="Pilot"))
        table.add_slot(EpisodeSlot(season=1, episode=3, title="Third"))
        table.add_file(folder / "Extra.mkv")
        state = ScanState(folder=folder, media_info=show_info, scanned=True, confidence=1.0)
        state.assignments = table
        state.preview_items = project_preview_items(
            table,
            show_info=show_info,
            root=folder,
            media_fields={"media_id": 101, "media_name": "Example Show"},
        )
        return state, table

    def test_assign_unmapped_file_assigns_selected_slots_via_dialog(self):
        """assign_unmapped_file: stub assign_dialog returns a fixed selection;
        the unmapped file lands in the assignment table (R2 M2)."""
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        state, table = self._make_unmapped_file_state()
        workspace = MediaWorkspace(
            media_type="tv",
            media_controller=self._make_fake_media_ctrl(state),
        )
        workspace.show_ready()

        preview = state.preview_items[0]
        file_id = preview.file_id

        class _FakeAssignDialog:
            @staticmethod
            def pick_episodes(**kwargs):
                return [(1, 3)]

        workspace._action_coordinator.assign_unmapped_file(
            state,
            preview,
            assign_dialog=_FakeAssignDialog,
        )
        self._app.processEvents()

        assignment = table.assignment_for(file_id)
        self.assertIsNotNone(assignment)
        self.assertEqual(assignment.season, 1)
        self.assertEqual(list(assignment.episodes), [3])
        workspace.close()

    def test_inline_row_action_routes_unmapped_row_through_assign_unmapped_file(self):
        """The inline "Assign..." control on an unmapped/duplicate row must
        route through assign_unmapped_file without requiring a guide row."""
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        state, _table = self._make_unmapped_file_state()
        workspace = MediaWorkspace(
            media_type="tv",
            media_controller=self._make_fake_media_ctrl(state),
        )
        workspace.show_ready()

        model = workspace._work_panel.model
        unmapped_row = next(
            row for row in range(model.rowCount()) if model.row_kind_at(row) == "unmapped"
        )
        preview_index = model.preview_index_at(unmapped_row)
        self.assertIsNotNone(preview_index)
        index = model.index(unmapped_row, 0)

        with patch.object(workspace._action_coordinator, "assign_unmapped_file") as mock_assign:
            workspace._on_inline_row_action(index, "assign_unmapped")

        mock_assign.assert_called_once_with(state, state.preview_items[preview_index])
        workspace.close()

    def test_episode_row_action_keep_this_resolves_conflict(self):
        """keep_this: dialog-free; winner keeps the slot, loser is unassigned."""
        from plex_renamer.app.models.state_models import EpisodeGuideRow
        from plex_renamer.engine._episode_projection import project_preview_items
        from plex_renamer.engine.episode_assignments import (
            ORIGIN_AUTO,
            EpisodeAssignmentTable,
            EpisodeSlot,
        )
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        folder = Path("C:/library/tv/Example")
        show_info = {"id": 101, "name": "Example Show", "year": "2024"}
        table = EpisodeAssignmentTable()
        table.add_slot(EpisodeSlot(season=1, episode=1, title="Pilot"))
        winner_entry = table.add_file(folder / "Season 01" / "A.S01E01.mkv")
        loser_entry = table.add_file(folder / "Season 01" / "B.S01E01.mkv")
        table.assign(winner_entry.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=0.9)
        table.assign(loser_entry.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=0.4)

        state = ScanState(folder=folder, media_info=show_info, scanned=True, confidence=1.0)
        state.assignments = table
        state.preview_items = project_preview_items(
            table,
            show_info=show_info,
            root=folder,
            media_fields={"media_id": 101, "media_name": "Example Show"},
        )

        workspace = MediaWorkspace(
            media_type="tv",
            media_controller=self._make_fake_media_ctrl(state),
        )
        workspace.show_ready()

        winner_preview = next(p for p in state.preview_items if p.file_id == winner_entry.file_id)
        row = EpisodeGuideRow(season=1, episode=1, title="Pilot", primary_file=winner_preview)

        workspace._action_coordinator.handle_episode_row_action(state, row, "keep_this")
        self._app.processEvents()

        # Winner retains assignment; loser has been unassigned.
        self.assertIsNotNone(table._assignments.get(winner_entry.file_id))
        self.assertIsNone(table._assignments.get(loser_entry.file_id))
        workspace.close()

    def test_episode_row_action_reassign_calls_dialog_and_moves_file(self):
        """reassign: stub assign_dialog returns a fixed selection; file moves."""
        from plex_renamer.app.models.state_models import EpisodeGuideRow
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        state, table, file_id = self._make_episode_table_state()
        workspace = MediaWorkspace(
            media_type="tv",
            media_controller=self._make_fake_media_ctrl(state),
        )
        workspace.show_ready()

        preview = next(p for p in state.preview_items if p.file_id == file_id)
        row = EpisodeGuideRow(season=1, episode=1, title="Pilot", primary_file=preview)

        # Stub dialog: pick_episodes always returns S01E02.
        class _StubAssignDialog:
            @staticmethod
            def pick_episodes(**_kwargs):
                return [(1, 2)]

        workspace._action_coordinator.handle_episode_row_action(
            state,
            row,
            "reassign",
            assign_dialog=_StubAssignDialog,
        )
        self._app.processEvents()

        # File should now be assigned to episode 2 (not episode 1).
        assignment = table._assignments.get(file_id)
        self.assertIsNotNone(assignment)
        self.assertEqual(assignment.episodes, (2,))
        workspace.close()

    def test_approve_all_recategorizes_and_auto_checks_show(self):
        from plex_renamer.gui_qt.widgets._media_helpers import (
            is_state_queue_approvable,
        )
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        # _make_episode_table_state assigns the only file at confidence 0.5,
        # so the show starts under "Needs Review — Episodes".
        state, _table, _file_id = self._make_episode_table_state()
        workspace = MediaWorkspace(
            media_type="tv",
            media_controller=self._make_fake_media_ctrl(state),
        )
        workspace.show_ready()

        self._assert_roster_section_title(workspace, 0, "NEEDS REVIEW — EPISODES")
        self.assertFalse(is_state_queue_approvable(state, media_type="tv"))

        workspace._approve_all_episode_mappings()
        self._app.processEvents()

        # The roster widget re-syncs out of review and the show is auto-checked.
        self._assert_roster_section_title(workspace, 0, "MATCHED")
        self.assertTrue(is_state_queue_approvable(state, media_type="tv"))
        self.assertTrue(state.checked)

        workspace.close()

    def test_unassign_all_clicked_clears_every_assigned_file(self):
        # The overflow-menu "Unassign All" entry is gone (Task 9), but the
        # unassign_all_clicked signal and the coordinator it drives remain
        # reachable programmatically -- exercise them directly.
        from PySide6.QtWidgets import QMessageBox

        from plex_renamer.engine._episode_projection import project_preview_items
        from plex_renamer.engine.episode_assignments import (
            ORIGIN_AUTO,
            EpisodeAssignmentTable,
            EpisodeSlot,
        )
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        folder = Path("C:/library/tv/Example")
        show_info = {"id": 101, "name": "Example Show", "year": "2024"}
        table = EpisodeAssignmentTable()
        table.add_slot(EpisodeSlot(season=1, episode=1, title="Pilot"))
        table.add_slot(EpisodeSlot(season=1, episode=2, title="Sequel"))
        first = table.add_file(folder / "Season 01" / "Example.S01E01.mkv")
        second = table.add_file(folder / "Season 01" / "Example.S01E02.mkv")
        table.assign(first.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=1.0)
        table.assign(second.file_id, 1, [2], origin=ORIGIN_AUTO, confidence=1.0)
        state = ScanState(folder=folder, media_info=show_info, scanned=True, confidence=1.0)
        state.assignments = table
        state.preview_items = project_preview_items(
            table,
            show_info=show_info,
            root=folder,
            media_fields={"media_id": 101, "media_name": "Example Show"},
        )

        workspace = MediaWorkspace(
            media_type="tv",
            media_controller=self._make_fake_media_ctrl(state),
        )
        workspace.show_ready()

        self.assertIsNotNone(table._assignments.get(first.file_id))
        self.assertIsNotNone(table._assignments.get(second.file_id))

        # Emitting the signal raises the danger confirm dialog (Plan 4 Task 4);
        # stub the blocking modal exec() to auto-answer "Unassign All" (Yes) so
        # the offscreen run still exercises the real signal -> confirm ->
        # unassign chain without sitting in a modal event loop.
        with patch.object(
            QMessageBox,
            "exec",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            workspace._work_panel.unassign_all_clicked.emit()
        self._app.processEvents()

        # Every file is now unassigned in the table...
        self.assertIsNone(table._assignments.get(first.file_id))
        self.assertIsNone(table._assignments.get(second.file_id))
        # ...and the reprojected previews carry no rename target.
        for preview in state.preview_items:
            self.assertIsNone(preview.new_name)

        workspace.close()

    def test_episode_filter_active_state_tracks_selected_filter(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        state, _table, _file_id = self._make_episode_table_state()
        workspace = MediaWorkspace(
            media_type="tv",
            media_controller=self._make_fake_media_ctrl(state),
        )
        workspace.show_ready()

        panel = workspace._work_panel
        segmented = panel.segmented_filter

        # Default filter is "all": the segmented control tracks the model filter.
        self.assertEqual(panel.model.filter_mode(), "all")
        self.assertEqual(segmented.currentText().casefold(), "all")

        # Switching the segmented control moves the model filter to the new value.
        segmented.setCurrentText("Problems")
        self._app.processEvents()

        self.assertEqual(panel.model.filter_mode(), "problems")
        self.assertEqual(segmented.currentText().casefold(), "problems")

        workspace.close()

    def test_approve_all_with_remaining_conflict_stays_in_review_no_checkbox(self):
        from plex_renamer.engine._episode_projection import project_preview_items
        from plex_renamer.engine.episode_assignments import (
            ORIGIN_AUTO,
            EpisodeAssignmentTable,
            EpisodeSlot,
        )
        from plex_renamer.gui_qt.widgets._media_helpers import is_state_queue_approvable
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        folder = Path("C:/library/tv/Conflicted")
        show_info = {"id": 77, "name": "Conflicted", "year": "2024"}
        table = EpisodeAssignmentTable()
        for ep, title in [(1, "Pilot"), (2, "Two"), (3, "Three")]:
            table.add_slot(EpisodeSlot(season=1, episode=ep, title=title))
        # A below-threshold review row (Approve All will approve it)...
        low = table.add_file(folder / "Season 01" / "low.mkv")
        table.assign(low.file_id, 1, [2], origin=ORIGIN_AUTO, confidence=0.5)
        # ...plus a hard conflict on E01 that Approve All does NOT resolve.
        a = table.add_file(folder / "Season 01" / "a.mkv")
        b = table.add_file(folder / "Season 01" / "b.mkv")
        table.assign(a.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=1.0)
        table.assign(b.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=1.0)
        state = ScanState(folder=folder, media_info=show_info, scanned=True, confidence=1.0)
        state.assignments = table
        state.preview_items = project_preview_items(
            table,
            show_info=show_info,
            root=folder,
            media_fields={"media_id": 77, "media_name": "Conflicted"},
        )

        workspace = MediaWorkspace(
            media_type="tv",
            media_controller=self._make_fake_media_ctrl(state),
        )
        workspace.show_ready()
        self._assert_roster_section_title(workspace, 0, "NEEDS REVIEW — EPISODES")

        workspace._approve_all_episode_mappings()
        self._app.processEvents()

        # Conflict remains: the show stays in review with no checkbox / unchecked,
        # so the checkbox stays consistent with the section header.
        self._assert_roster_section_title(workspace, 0, "NEEDS REVIEW — EPISODES")
        self.assertFalse(is_state_queue_approvable(state, media_type="tv"))
        self.assertFalse(state.checked)
        workspace.close()

    def test_reassign_opens_empty_with_current_tagged(self):
        from plex_renamer.app.models.state_models import EpisodeGuideRow
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        state, _table, file_id = self._make_episode_table_state()
        workspace = MediaWorkspace(
            media_type="tv",
            media_controller=self._make_fake_media_ctrl(state),
        )
        workspace.show_ready()

        preview = next(p for p in state.preview_items if p.file_id == file_id)
        row = EpisodeGuideRow(season=1, episode=1, title="Pilot", primary_file=preview)

        captured: dict = {}

        class _CapturingDialog:
            @staticmethod
            def pick_episodes(**kwargs):
                captured.update(kwargs)
                return None  # cancel

        workspace._action_coordinator.handle_episode_row_action(
            state,
            row,
            "reassign",
            assign_dialog=_CapturingDialog,
        )

        self.assertIsNone(captured.get("preselected"))
        self.assertEqual(set(captured.get("current_keys") or set()), {(1, 1)})
        workspace.close()

    def test_assign_to_more_preselects_current_run(self):
        from plex_renamer.app.models.state_models import EpisodeGuideRow
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        # _make_episode_table_state has slots E01 and E02; the file is at E01.
        state, _table, file_id = self._make_episode_table_state()
        workspace = MediaWorkspace(
            media_type="tv",
            media_controller=self._make_fake_media_ctrl(state),
        )
        workspace.show_ready()

        preview = next(p for p in state.preview_items if p.file_id == file_id)
        row = EpisodeGuideRow(season=1, episode=1, title="Pilot", primary_file=preview)

        captured: dict = {}

        class _CapturingDialog:
            @staticmethod
            def pick_episodes(**kwargs):
                captured.update(kwargs)
                return None  # cancel

        workspace._action_coordinator.handle_episode_row_action(
            state,
            row,
            "assign_to_more",
            assign_dialog=_CapturingDialog,
        )

        self.assertEqual(set(captured.get("preselected") or set()), {(1, 1)})
        self.assertEqual(set(captured.get("current_keys") or set()), {(1, 1)})
        slot_keys = {(c.season, c.episode) for c in captured.get("slots", [])}
        self.assertIn((1, 1), slot_keys)
        self.assertIn((1, 2), slot_keys)
        workspace.close()

    def test_episode_row_action_assign_file_calls_dialog_and_assigns_slot(self):
        """assign_file: stub assign_dialog.pick_file returns a file_id; assignment lands."""
        from plex_renamer.app.models.state_models import EpisodeGuideRow
        from plex_renamer.engine._episode_projection import project_preview_items
        from plex_renamer.engine.episode_assignments import (
            ORIGIN_AUTO,
            EpisodeAssignmentTable,
            EpisodeSlot,
        )
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        folder = Path("C:/library/tv/Example")
        show_info = {"id": 101, "name": "Example Show", "year": "2024"}
        table = EpisodeAssignmentTable()
        table.add_slot(EpisodeSlot(season=1, episode=1, title="Pilot"))
        table.add_slot(EpisodeSlot(season=1, episode=2, title="Sequel"))
        # One file assigned to E01; one file unassigned (will be picked and placed at E02).
        e01_entry = table.add_file(folder / "Season 01" / "A.S01E01.mkv")
        table.assign(e01_entry.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=0.9)
        loose_entry = table.add_file(folder / "Season 01" / "Loose.mkv")
        table.mark_unassigned(loose_entry.file_id, "could not parse episode number")

        state = ScanState(folder=folder, media_info=show_info, scanned=True, confidence=1.0)
        state.assignments = table
        state.preview_items = project_preview_items(
            table,
            show_info=show_info,
            root=folder,
            media_fields={"media_id": 101, "media_name": "Example Show"},
        )

        workspace = MediaWorkspace(
            media_type="tv",
            media_controller=self._make_fake_media_ctrl(state),
        )
        workspace.show_ready()

        # Simulate clicking "assign_file" on the S01E02 missing row.
        row = EpisodeGuideRow(season=1, episode=2, title="Sequel", primary_file=None)

        picked_file_id = loose_entry.file_id

        class _StubAssignDialog:
            @staticmethod
            def pick_file(**_kwargs):
                return picked_file_id

        workspace._action_coordinator.handle_episode_row_action(
            state,
            row,
            "assign_file",
            assign_dialog=_StubAssignDialog,
        )
        self._app.processEvents()

        assignment = table._assignments.get(loose_entry.file_id)
        self.assertIsNotNone(assignment)
        self.assertEqual(assignment.season, 1)
        self.assertEqual(assignment.episodes, (2,))
        workspace.close()

    def test_assign_file_dialog_does_not_double_list_unmatched_extras(self):
        """UNMATCHED extras rows must appear only in 'unassigned', not also in 'assigned'."""
        from plex_renamer.app.models.state_models import EpisodeGuideRow
        from plex_renamer.engine._episode_projection import project_preview_items
        from plex_renamer.engine.episode_assignments import (
            ORIGIN_AUTO,
            EpisodeAssignmentTable,
            EpisodeSlot,
        )
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        folder = Path("C:/library/tv/Example")
        show_info = {"id": 101, "name": "Example Show", "year": "2024"}
        table = EpisodeAssignmentTable()
        table.add_slot(EpisodeSlot(season=1, episode=1, title="Pilot"))
        # Assigned file (appears in assigned list).
        e01_entry = table.add_file(folder / "Season 01" / "A.S01E01.mkv")
        table.assign(e01_entry.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=0.9)
        # Unmatched extras file: has new_name set by projection but no table assignment.
        from plex_renamer.engine.episode_assignments import (
            REASON_NO_TITLE_MATCH,
        )

        extras_entry = table.add_file(
            folder / "Season 01" / "Extras" / "bts.mkv",
            folder_season=0,
            from_extras_folder=True,
        )
        table.mark_unassigned(extras_entry.file_id, REASON_NO_TITLE_MATCH)

        state = ScanState(folder=folder, media_info=show_info, scanned=True, confidence=1.0)
        state.assignments = table
        state.preview_items = project_preview_items(
            table,
            show_info=show_info,
            root=folder,
            media_fields={"media_id": 101, "media_name": "Example Show"},
        )

        # Sanity: the extras item has a new_name (unmatched-extras projection sets it).
        extras_preview = next(i for i in state.preview_items if i.file_id == extras_entry.file_id)
        self.assertIsNotNone(extras_preview.new_name)
        self.assertTrue(extras_preview.is_unmatched)

        workspace = MediaWorkspace(
            media_type="tv",
            media_controller=self._make_fake_media_ctrl(state),
        )
        workspace.show_ready()

        row = EpisodeGuideRow(season=1, episode=1, title="Pilot", primary_file=None)

        # Capture what pick_file receives.
        captured_unassigned: list = []
        captured_assigned: list = []

        class _CapturingDialog:
            @staticmethod
            def pick_file(*, unassigned, assigned, **_kwargs):
                captured_unassigned.extend(unassigned)
                captured_assigned.extend(assigned)
                return None  # cancel

        workspace._action_coordinator.handle_episode_row_action(
            state,
            row,
            "assign_file",
            assign_dialog=_CapturingDialog,
        )

        # extras_entry must appear in unassigned only, not in assigned.
        unassigned_ids = {fid for fid, _label in captured_unassigned}
        assigned_ids = {fid for fid, _name in captured_assigned}
        self.assertIn(extras_entry.file_id, unassigned_ids)
        self.assertNotIn(
            extras_entry.file_id,
            assigned_ids,
            "UNMATCHED extras file must not appear in the 'Already assigned' list",
        )
        workspace.close()

    def test_episode_row_action_error_calls_warning_box_no_crash(self):
        """If the service raises ValueError, warning_box.warning is called; no hang."""
        from plex_renamer.app.models.state_models import EpisodeGuideRow
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        state, _table, _file_id = self._make_episode_table_state()
        workspace = MediaWorkspace(
            media_type="tv",
            media_controller=self._make_fake_media_ctrl(state),
        )
        workspace.show_ready()

        # Use a preview with file_id=None so approve_file raises ValueError.
        from plex_renamer.engine import PreviewItem

        bad_preview = PreviewItem(
            original=Path("C:/library/tv/Example/Season 01/NoId.mkv"),
            new_name=None,
            target_dir=None,
            season=1,
            episodes=[1],
            status="REVIEW: low confidence",
        )
        row = EpisodeGuideRow(season=1, episode=1, title="Pilot", primary_file=bad_preview)

        warnings: list[tuple] = []

        class _RecordingWarningBox:
            @staticmethod
            def warning(*args, **kwargs):
                warnings.append(args)

        workspace._action_coordinator.handle_episode_row_action(
            state,
            row,
            "approve",
            warning_box=_RecordingWarningBox,
        )
        self._app.processEvents()

        self.assertEqual(len(warnings), 1, "Expected exactly one warning dialog call")
        workspace.close()

    def test_media_workspace_show_rematch_invalidates_projection_before_rescan(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeTMDB:
            def search_tv(self, *_args, **_kwargs):
                return []

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = [state]
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")
                self.invalidate_episode_guide = MagicMock()
                self.refresh_episode_guide = MagicMock()

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

            def rematch_tv_state(self, state, chosen, tmdb=None):
                state.media_info = chosen
                state.preview_items = []
                state.scanned = False
                return state

            def scan_show(self, state, _tmdb):
                state.preview_items = [
                    PreviewItem(
                        original=Path("C:/library/tv/Example/Season 01/Example.S01E01.mkv"),
                        new_name="Replacement Show (2024) - S01E01 - Pilot.mkv",
                        target_dir=Path("C:/library/tv/Replacement Show (2024)/Season 01"),
                        season=1,
                        episodes=[1],
                        status="OK",
                    )
                ]
                state.scanned = True

        state = ScanState(
            folder=Path("C:/library/tv/Example"),
            media_info={"id": 101, "name": "Original Show", "year": "2024"},
            preview_items=[],
            scanned=False,
            confidence=0.5,
        )
        media_ctrl = _FakeMediaController(state)
        workspace = MediaWorkspace(
            media_type="tv",
            media_controller=media_ctrl,
            tmdb_provider=_FakeTMDB,
        )
        workspace.show_ready()

        workspace._apply_alternate_match(
            state,
            {"id": 202, "name": "Replacement Show", "year": "2024"},
        )

        media_ctrl.invalidate_episode_guide.assert_called_with(state)
        media_ctrl.refresh_episode_guide.assert_called_with(state)
        workspace.close()

    def test_media_workspace_tv_episode_guide_separates_unmapped_and_orphan_companions(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = [state]
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        state = ScanState(
            folder=Path("C:/library/tv/Example"),
            media_info={"id": 101, "name": "Example Show", "year": "2024"},
            preview_items=[
                PreviewItem(
                    original=Path("C:/library/tv/Example/Unknown.mkv"),
                    new_name=None,
                    target_dir=None,
                    season=None,
                    episodes=[],
                    status="SKIP: no episode mapping",
                )
            ],
            orphan_companion_files=[
                CompanionFile(
                    original=Path("C:/library/tv/Example/Unknown.en.srt"),
                    new_name="",
                    file_type="subtitle",
                )
            ],
            scanned=True,
            checked=False,
            confidence=1.0,
        )

        workspace = MediaWorkspace(media_type="tv", media_controller=_FakeMediaController(state))
        workspace.show_ready()

        headers = [t.upper() for t in self._episode_section_titles(workspace)]
        self.assertTrue(any("UNMAPPED PRIMARY FILES" in header for header in headers))
        self.assertTrue(any("ORPHAN COMPANION FILES" in header for header in headers))

        workspace.close()

    def test_match_picker_enter_runs_search_instead_of_accepting(self):
        from plex_renamer.gui_qt.widgets.match_picker_dialog import MatchPickerDialog

        search_calls: list[tuple[str, str | None]] = []

        def _search(query: str, year_hint: str | None) -> list[dict]:
            search_calls.append((query, year_hint))
            return [
                {
                    "id": 99,
                    "title": "Arrival",
                    "year": "2016",
                    "overview": "First contact.",
                }
            ]

        dialog = MatchPickerDialog(
            title="Fix Match",
            title_key="title",
            initial_query="Arrival",
            initial_results=[{"id": 1, "title": "Old Result", "year": "2015"}],
            search_callback=_search,
            year_hint="2016",
        )
        dialog.show()
        self._app.processEvents()

        dialog._query.setFocus()
        dialog._query.selectAll()
        QTest.keyClicks(dialog._query, "Arrival")
        QTest.keyClick(dialog._query, Qt.Key.Key_Return)
        self._app.processEvents()

        self.assertEqual(search_calls, [("Arrival", "2016")])
        self.assertEqual(dialog.result(), 0)
        self.assertTrue(dialog._ok_button.isEnabled())

        dialog.close()

    def test_media_workspace_renders_inline_alternate_matches_for_review_items(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = []
                self.library_selected_index = None
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.movie_library_states):
                    return self.movie_library_states[index]
                return None

            def sync_queued_states(self):
                return None

        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
            review_state = ScanState(
                folder=Path("C:/library/movies/Crash.Collectors.Edition"),
                media_info={"id": 1, "title": "Crash", "year": "1996"},
                preview_items=[
                    PreviewItem(
                        original=Path(
                            "C:/library/movies/Crash.Collectors.Edition/Crash.Collectors.Edition.mkv"
                        ),
                        new_name="Crash (1996).mkv",
                        target_dir=Path("C:/library/movies/Crash (1996)"),
                        season=None,
                        episodes=[],
                        status="REVIEW: verify",
                        media_type="movie",
                        media_id=1,
                        media_name="Crash",
                    )
                ],
                scanned=True,
                checked=False,
                confidence=0.42,
                alternate_matches=[
                    {"id": 2, "title": "Crash", "year": "2004"},
                    {"id": 3, "title": "Crash Landing", "year": "1999"},
                ],
            )
            media_ctrl = _FakeMediaController()
            media_ctrl.movie_library_states = [review_state]

            workspace = MediaWorkspace(
                media_type="movie",
                media_controller=media_ctrl,
                queue_controller=type(
                    "Q", (), {"add_movie_batch": lambda *args, **kwargs: BatchQueueResult(added=1)}
                )(),
                settings_service=settings,
            )
            workspace.show_ready()

            data = self._roster_row_data_for_index(workspace, 0)
            self.assertIsNotNone(data)
            self.assertTrue(workspace._fix_match_btn.isEnabled())
            self.assertEqual(data.band, "low")
            self.assertEqual(workspace._roster_panel.current_state_index(), 0)

            workspace.close()

    def test_media_workspace_sorts_tv_preview_items_by_episode_number(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = []
                self.library_selected_index = None
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
            state = ScanState(
                folder=Path("C:/library/tv/Example Show"),
                media_info={"id": 101, "name": "Example Show", "year": "2024"},
                preview_items=[
                    PreviewItem(
                        original=Path(
                            "C:/library/tv/Example Show/Season 01/Example.Show.S01E03.mkv"
                        ),
                        new_name="Example Show (2024) - S01E03 - Episode 3.mkv",
                        target_dir=Path("C:/library/tv/Example Show/Season 01"),
                        season=1,
                        episodes=[3],
                        status="OK",
                    ),
                    PreviewItem(
                        original=Path(
                            "C:/library/tv/Example Show/Season 01/Example.Show.S01E01.mkv"
                        ),
                        new_name="Example Show (2024) - S01E01 - Episode 1.mkv",
                        target_dir=Path("C:/library/tv/Example Show/Season 01"),
                        season=1,
                        episodes=[1],
                        status="OK",
                    ),
                    PreviewItem(
                        original=Path(
                            "C:/library/tv/Example Show/Season 01/Example.Show.S01E02.mkv"
                        ),
                        new_name="Example Show (2024) - S01E02 - Episode 2.mkv",
                        target_dir=Path("C:/library/tv/Example Show/Season 01"),
                        season=1,
                        episodes=[2],
                        status="OK",
                    ),
                ],
                scanned=True,
                checked=True,
                confidence=1.0,
            )
            media_ctrl = _FakeMediaController()
            media_ctrl.batch_states = [state]

            workspace = MediaWorkspace(
                media_type="tv",
                media_controller=media_ctrl,
                queue_controller=type(
                    "Q", (), {"add_tv_batch": lambda *args, **kwargs: BatchQueueResult(added=1)}
                )(),
                settings_service=settings,
            )
            workspace.show_ready()

            model = workspace._work_panel.model
            preview_indices = [
                model.preview_index_at(row)
                for row in range(model.rowCount())
                if model.row_kind_at(row) == "episode" and model.preview_index_at(row) is not None
            ]

            self.assertEqual(preview_indices, [1, 2, 0])

            # Row painting moved to the delegate; the surviving row-level signal
            # is the model's status tone (was the row widget's "tone" property).
            first_episode = next(
                data for data in self._episode_row_datas(workspace) if data.kind == "episode"
            )
            self.assertEqual(first_episode.status_text, "Mapped")
            self.assertEqual(first_episode.status_tone, "success")

            workspace.close()

    def test_media_workspace_uses_expected_episode_count_in_season_headers(self):
        from plex_renamer.engine import CompletenessReport, SeasonCompleteness
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = [state]
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        state = ScanState(
            folder=Path("C:/library/tv/Example Show"),
            media_info={"id": 101, "name": "Example Show", "year": "2024"},
            preview_items=[
                PreviewItem(
                    original=Path("C:/library/tv/Example Show/Season 01/Example.Show.S01E01.mkv"),
                    new_name="Example Show (2024) - S01E01 - Episode 1.mkv",
                    target_dir=Path("C:/library/tv/Example Show/Season 01"),
                    season=1,
                    episodes=[1],
                    status="OK",
                ),
                PreviewItem(
                    original=Path("C:/library/tv/Example Show/Season 01/Example.Show.S01E02.mkv"),
                    new_name="Example Show (2024) - S01E02 - Episode 2.mkv",
                    target_dir=Path("C:/library/tv/Example Show/Season 01"),
                    season=1,
                    episodes=[2],
                    status="SKIP: sample",
                ),
                PreviewItem(
                    original=Path("C:/library/tv/Example Show/Season 01/Example.Show.S01E03.mkv"),
                    new_name="Example Show (2024) - S01E03 - Episode 3.mkv",
                    target_dir=Path("C:/library/tv/Example Show/Season 01"),
                    season=1,
                    episodes=[3],
                    status="UNMATCHED: extras",
                ),
            ],
            scanned=True,
            checked=True,
            confidence=1.0,
            completeness=CompletenessReport(
                seasons={1: SeasonCompleteness(season=1, expected=2, matched=1, missing=[])},
                specials=None,
                total_expected=2,
                total_matched=1,
                total_missing=[],
            ),
        )
        workspace = MediaWorkspace(media_type="tv", media_controller=_FakeMediaController(state))
        workspace.show_ready()

        # The season header ratio now uses an em-dash: "Season 1 — 1/2".
        self.assertTrue(
            any(
                "SEASON 1" in text.upper() and "1/2" in text
                for text in self._episode_section_titles(workspace)
            )
        )

        workspace.close()

    def test_media_workspace_keeps_folder_rename_states_out_of_plex_ready(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = []
                self.library_selected_index = None
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
            state = ScanState(
                folder=Path("C:/library/tv/Example.Show.2024.Source"),
                media_info={"id": 101, "name": "Example Show", "year": "2024"},
                preview_items=[
                    PreviewItem(
                        original=Path(
                            "C:/library/tv/Example.Show.2024.Source/Season 01/Example Show (2024) - S01E01 - Pilot.mkv"
                        ),
                        new_name="Example Show (2024) - S01E01 - Pilot.mkv",
                        target_dir=Path("C:/library/tv/Example.Show.2024.Source/Season 01"),
                        season=1,
                        episodes=[1],
                        status="OK",
                    )
                ],
                scanned=True,
                checked=True,
                confidence=1.0,
            )
            media_ctrl = _FakeMediaController()
            media_ctrl.batch_states = [state]

            workspace = MediaWorkspace(
                media_type="tv",
                media_controller=media_ctrl,
                queue_controller=type(
                    "Q", (), {"add_tv_batch": lambda *args, **kwargs: BatchQueueResult(added=1)}
                )(),
                settings_service=settings,
            )
            workspace.show_ready()

            self._assert_roster_section_title(workspace, 0, "MATCHED")
            data = self._roster_row_data_for_index(workspace, 0)
            self.assertIsNotNone(data)

            workspace.close()

    def test_tv_workspace_blocks_review_duplicate_and_plex_ready_from_queue_selection(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        def _episode(
            path_root: str,
            season: int,
            episode: int,
            *,
            status: str = "OK",
            new_name: str | None = None,
            target_dir: Path | None = None,
        ):
            original = Path(f"{path_root}/Season 01/Example.Show.S01E0{episode}.mkv")
            return PreviewItem(
                original=original,
                new_name=new_name
                if new_name is not None
                else f"Example Show (2024) - S01E0{episode} - Pilot.mkv",
                target_dir=target_dir if target_dir is not None else Path(f"{path_root}/Season 01"),
                season=season,
                episodes=[episode],
                status=status,
            )

        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
            matched_state = ScanState(
                folder=Path("C:/library/tv/Matched.Show.2024"),
                media_info={"id": 101, "name": "Matched Show", "year": "2024"},
                preview_items=[
                    PreviewItem(
                        original=Path(
                            "C:/library/tv/Matched.Show.2024/Season 01/Matched.Show.S01E01.mkv"
                        ),
                        new_name="Matched Show (2024) - S01E01 - Pilot.mkv",
                        target_dir=Path("C:/library/tv/Matched.Show.2024/Season 01"),
                        season=1,
                        episodes=[1],
                        status="OK",
                    )
                ],
                scanned=True,
                checked=True,
                confidence=1.0,
            )
            review_state = ScanState(
                folder=Path("C:/library/tv/Review.Show.2024"),
                media_info={"id": 102, "name": "Review Show", "year": "2024"},
                preview_items=[
                    PreviewItem(
                        original=Path(
                            "C:/library/tv/Review.Show.2024/Season 01/Review.Show.S01E01.mkv"
                        ),
                        new_name="Review Show (2024) - S01E01 - Pilot.mkv",
                        target_dir=Path("C:/library/tv/Review.Show.2024/Season 01"),
                        season=1,
                        episodes=[1],
                        status="REVIEW",
                    )
                ],
                scanned=True,
                checked=True,
                confidence=0.42,
                alternate_matches=[{"id": 202, "name": "Review Show", "year": "2024"}],
            )
            duplicate_state = ScanState(
                folder=Path("C:/library/tv/Duplicate.Show.2024"),
                media_info={"id": 101, "name": "Matched Show", "year": "2024"},
                preview_items=[
                    PreviewItem(
                        original=Path(
                            "C:/library/tv/Duplicate.Show.2024/Season 01/Duplicate.Show.S01E01.mkv"
                        ),
                        new_name="Matched Show (2024) - S01E01 - Pilot.mkv",
                        target_dir=Path("C:/library/tv/Duplicate.Show.2024/Season 01"),
                        season=1,
                        episodes=[1],
                        status="OK",
                    )
                ],
                scanned=True,
                checked=True,
                confidence=1.0,
                duplicate_of="Matched Show (2024)",
            )
            plex_ready_root = "C:/library/tv/Plex Ready Show (2024)"
            plex_ready_state = ScanState(
                folder=Path(plex_ready_root),
                media_info={"id": 103, "name": "Plex Ready Show", "year": "2024"},
                preview_items=[
                    PreviewItem(
                        original=Path(
                            f"{plex_ready_root}/Season 01/Plex Ready Show (2024) - S01E01 - Pilot.mkv"
                        ),
                        new_name="Plex Ready Show (2024) - S01E01 - Pilot.mkv",
                        target_dir=Path(f"{plex_ready_root}/Season 01"),
                        season=1,
                        episodes=[1],
                        status="OK",
                    )
                ],
                scanned=True,
                checked=True,
                confidence=1.0,
            )

            media_ctrl = _FakeMediaController()
            media_ctrl.batch_states = [
                matched_state,
                review_state,
                duplicate_state,
                plex_ready_state,
            ]

            workspace = MediaWorkspace(
                media_type="tv",
                media_controller=media_ctrl,
                queue_controller=type(
                    "Q", (), {"add_tv_batch": lambda *args, **kwargs: BatchQueueResult(added=1)}
                )(),
                settings_service=settings,
            )
            workspace.show_ready()
            workspace._roster_collapsed["fully-ready"] = False
            workspace.refresh_from_controller()

            matched_data = self._roster_row_data_for_index(workspace, 0)
            review_data = self._roster_row_data_for_index(workspace, 1)
            duplicate_data = self._roster_row_data_for_index(workspace, 2)
            plex_ready_data = self._roster_row_data_for_index(workspace, 3)

            self.assertIsNotNone(matched_data)
            self.assertTrue(matched_data.checkable)
            self.assertTrue(matched_state.checked)

            self.assertIsNotNone(review_data)
            self.assertFalse(review_state.checked)
            self.assertFalse(review_data.checkable)

            self.assertIsNotNone(duplicate_data)
            self.assertFalse(duplicate_state.checked)
            self.assertFalse(duplicate_data.checkable)

            self.assertIsNotNone(plex_ready_data)
            self.assertFalse(plex_ready_state.checked)
            self.assertFalse(plex_ready_data.checkable)

            workspace.close()

    def test_tv_workspace_episode_review_state_groups_under_review_and_keeps_row_alignment(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, states):
                self.command_gating = CommandGatingService()
                self.batch_states = list(states)
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        matched_state = ScanState(
            folder=Path("C:/library/tv/Matched.Show.2024"),
            media_info={"id": 101, "name": "Matched Show", "year": "2024"},
            preview_items=[
                PreviewItem(
                    original=Path(
                        "C:/library/tv/Matched.Show.2024/Season 01/Matched.Show.S01E01.mkv"
                    ),
                    new_name="Matched Show (2024) - S01E01 - Pilot.mkv",
                    target_dir=Path("C:/library/tv/Matched.Show.2024/Season 01"),
                    season=1,
                    episodes=[1],
                    status="OK",
                )
            ],
            scanned=True,
            checked=True,
            confidence=1.0,
        )
        episode_review_state = ScanState(
            folder=Path("C:/library/tv/Episode.Review.Show.2024"),
            media_info={"id": 102, "name": "Episode Review Show", "year": "2024"},
            preview_items=[
                PreviewItem(
                    original=Path(
                        "C:/library/tv/Episode.Review.Show.2024/Season 01/Episode.Review.Show.S01E01.mkv"
                    ),
                    new_name="Episode Review Show (2024) - S01E01 - Pilot.mkv",
                    target_dir=Path("C:/library/tv/Episode.Review.Show.2024/Season 01"),
                    season=1,
                    episodes=[1],
                    status="REVIEW: episode confidence below threshold",
                    episode_confidence=0.5,
                )
            ],
            scanned=True,
            checked=True,
            confidence=1.0,
        )

        workspace = MediaWorkspace(
            media_type="tv",
            media_controller=_FakeMediaController([matched_state, episode_review_state]),
        )
        workspace.resize(1200, 700)
        workspace.show()
        workspace.show_ready()
        self._app.processEvents()

        self._assert_roster_section_title(workspace, 0, "MATCHED")
        self._assert_roster_section_title(workspace, 2, "NEEDS REVIEW — EPISODES")

        matched_data = self._roster_row_data_for_index(workspace, 0)
        review_data = self._roster_row_data_for_index(workspace, 1)
        self.assertIsNotNone(matched_data)
        self.assertIsNotNone(review_data)
        self.assertTrue(matched_data.checkable)
        self.assertFalse(review_data.checkable)
        self.assertFalse(episode_review_state.checked)

        workspace.close()

    def test_media_workspace_prefers_matched_when_auto_selection_lands_on_plex_ready(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, states):
                self.command_gating = CommandGatingService()
                self.batch_states = list(states)
                self.movie_library_states = []
                self.library_selected_index = None
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
            plex_ready_root = "C:/library/tv/Auto Selected Show (2024)"
            plex_ready_state = ScanState(
                folder=Path(plex_ready_root),
                media_info={"id": 101, "name": "Auto Selected Show", "year": "2024"},
                preview_items=[
                    PreviewItem(
                        original=Path(
                            f"{plex_ready_root}/Season 01/Auto Selected Show (2024) - S01E01 - Pilot.mkv"
                        ),
                        new_name="Auto Selected Show (2024) - S01E01 - Pilot.mkv",
                        target_dir=Path(f"{plex_ready_root}/Season 01"),
                        season=1,
                        episodes=[1],
                        status="OK",
                    )
                ],
                scanned=True,
                checked=False,
                confidence=1.0,
            )
            matched_state = ScanState(
                folder=Path("C:/library/tv/Matched.Show.2024"),
                media_info={"id": 102, "name": "Matched Show", "year": "2024"},
                preview_items=[
                    PreviewItem(
                        original=Path(
                            "C:/library/tv/Matched.Show.2024/Season 01/Matched.Show.S01E01.mkv"
                        ),
                        new_name="Matched Show (2024) - S01E01 - Pilot.mkv",
                        target_dir=Path("C:/library/tv/Matched.Show.2024/Season 01"),
                        season=1,
                        episodes=[1],
                        status="OK",
                    )
                ],
                scanned=True,
                checked=True,
                confidence=0.93,
            )
            review_state = ScanState(
                folder=Path("C:/library/tv/Review.Show.2024"),
                media_info={"id": 103, "name": "Review Show", "year": "2024"},
                preview_items=[
                    PreviewItem(
                        original=Path(
                            "C:/library/tv/Review.Show.2024/Season 01/Review.Show.S01E01.mkv"
                        ),
                        new_name="Review Show (2024) - S01E01 - Pilot.mkv",
                        target_dir=Path("C:/library/tv/Review.Show.2024/Season 01"),
                        season=1,
                        episodes=[1],
                        status="REVIEW",
                    )
                ],
                scanned=True,
                checked=False,
                confidence=0.54,
                alternate_matches=[{"id": 203, "name": "Review Show", "year": "2024"}],
            )

            media_ctrl = _FakeMediaController([plex_ready_state, matched_state, review_state])
            workspace = MediaWorkspace(
                media_type="tv", media_controller=media_ctrl, settings_service=settings
            )

            workspace.show_ready()
            self.assertEqual(media_ctrl.library_selected_index, 1)
            self.assertEqual(workspace._selected_state(), matched_state)

            media_ctrl.library_selected_index = 0
            workspace._roster_selection_is_auto = True
            workspace.refresh_from_controller()

            self.assertEqual(media_ctrl.library_selected_index, 1)
            self.assertEqual(workspace._selected_state(), matched_state)

            workspace.close()

    def test_media_workspace_mutes_roster_confidence_for_queued_items(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = []
                self.library_selected_index = None
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
            state = ScanState(
                folder=Path("C:/library/tv/Example.Show.2024.Source"),
                media_info={"id": 101, "name": "Example Show", "year": "2024"},
                preview_items=[
                    PreviewItem(
                        original=Path(
                            "C:/library/tv/Example.Show.2024.Source/Season 01/Example Show (2024) - S01E01 - Pilot.mkv"
                        ),
                        new_name="Example Show (2024) - S01E01 - Pilot.mkv",
                        target_dir=Path("C:/library/tv/Example.Show.2024.Source/Season 01"),
                        season=1,
                        episodes=[1],
                        status="OK",
                    )
                ],
                scanned=True,
                checked=True,
                confidence=1.0,
                queued=True,
            )
            media_ctrl = _FakeMediaController()
            media_ctrl.batch_states = [state]

            workspace = MediaWorkspace(
                media_type="tv",
                media_controller=media_ctrl,
                queue_controller=type(
                    "Q", (), {"add_tv_batch": lambda *args, **kwargs: BatchQueueResult(added=1)}
                )(),
                settings_service=settings,
            )
            workspace.show_ready()

            from plex_renamer.gui_qt import theme

            data = self._roster_row_data_for_index(workspace, 0)
            self.assertIsNotNone(data)
            self.assertEqual(data.confidence_color, theme.color("text_dim"))

            workspace.close()

    def test_media_workspace_roster_rows_use_placeholder_thumbnail_without_poster(self):
        from plex_renamer.gui_qt.widgets._roster_model import POSTER_ROLE, ROW_DATA_ROLE
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = []
                self.library_selected_index = None
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
            state = ScanState(
                folder=Path("C:/library/tv/Example.Show.2024.Source"),
                media_info={"id": 101, "name": "Example Show", "year": "2024"},
                preview_items=[],
                scanned=True,
                checked=True,
                confidence=1.0,
            )
            media_ctrl = _FakeMediaController()
            media_ctrl.batch_states = [state]

            workspace = MediaWorkspace(
                media_type="tv",
                media_controller=media_ctrl,
                queue_controller=type(
                    "Q", (), {"add_tv_batch": lambda *args, **kwargs: BatchQueueResult(added=1)}
                )(),
                settings_service=settings,
                tmdb_provider=lambda: None,
            )
            workspace.show_ready()

            model = workspace._roster_panel.model
            row = model.row_for_state_index(0)
            self.assertGreaterEqual(row, 0)
            data = model.index(row, 0).data(ROW_DATA_ROLE)
            self.assertIsNotNone(data)
            # No TMDB provider means no poster pixmap ever lands on the
            # model; the delegate paints a placeholder (initials/accent)
            # from RosterRowData in that case.
            self.assertIsNone(model.index(row, 0).data(POSTER_ROLE))
            self.assertTrue(data.placeholder_initials)
            self.assertTrue(data.placeholder_accent)

            workspace.close()

    def test_media_workspace_movie_roster_poster_is_vertically_centered(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, state):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = [state]
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_movie(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.movie_library_states):
                    return self.movie_library_states[index]
                return None

            def select_show(self, index):
                return self.select_movie(index)

            def sync_queued_states(self):
                return None

        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
            state = ScanState(
                folder=Path("C:/library/movies/Arrival.2016"),
                media_info={"id": 22, "title": "Arrival", "year": "2016", "_media_type": "movie"},
                preview_items=[
                    PreviewItem(
                        original=Path("C:/library/movies/Arrival.2016/Arrival.2016.mkv"),
                        new_name="Arrival (2016).mkv",
                        target_dir=Path("C:/library/movies/Arrival (2016)"),
                        season=None,
                        episodes=[],
                        status="OK",
                        media_type="movie",
                        media_id=22,
                        media_name="Arrival",
                    )
                ],
                scanned=True,
                checked=True,
                confidence=1.0,
            )
            workspace = MediaWorkspace(
                media_type="movie",
                media_controller=_FakeMediaController(state),
                queue_controller=type(
                    "Q", (), {"add_movie_batch": lambda *args, **kwargs: BatchQueueResult(added=1)}
                )(),
                settings_service=settings,
                tmdb_provider=lambda: None,
            )
            workspace.resize(1000, 700)
            workspace.show()
            workspace.show_ready()
            self._app.processEvents()

            # Row widgets are gone (delegate-painted rows); the vertical
            # centering behavior itself now lives in
            # RosterDelegate._poster_rect for media_type="movie". Assert the
            # geometry invariant directly at that layer.
            from PySide6.QtCore import QRect

            delegate = workspace._roster_panel._delegate
            self.assertEqual(delegate._media_type, "movie")
            option_rect = QRect(0, 0, 300, 110)
            card_rect = delegate._card_rect(option_rect)
            poster_rect = delegate._poster_rect(card_rect)
            self.assertLessEqual(abs(poster_rect.center().y() - card_rect.center().y()), 2)

            workspace.close()

    def test_media_workspace_shows_threshold_aware_roster_match_text(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = []
                self.library_selected_index = None
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
            settings.auto_accept_threshold = 0.6
            review_state = ScanState(
                folder=Path("C:/library/tv/Review.Show.2024"),
                media_info={"id": 102, "name": "Review Show", "year": "2024"},
                preview_items=[
                    PreviewItem(
                        original=Path(
                            "C:/library/tv/Review.Show.2024/Season 01/Review.Show.S01E01.mkv"
                        ),
                        new_name="Review Show (2024) - S01E01 - Pilot.mkv",
                        target_dir=Path("C:/library/tv/Review.Show.2024/Season 01"),
                        season=1,
                        episodes=[1],
                        status="REVIEW",
                    )
                ],
                scanned=True,
                confidence=0.42,
                alternate_matches=[{"id": 202, "name": "Review Show", "year": "2024"}],
            )
            media_ctrl = _FakeMediaController()
            media_ctrl.batch_states = [review_state]

            workspace = MediaWorkspace(
                media_type="tv",
                media_controller=media_ctrl,
                queue_controller=type(
                    "Q", (), {"add_tv_batch": lambda *args, **kwargs: BatchQueueResult(added=0)}
                )(),
                settings_service=settings,
            )
            workspace.show_ready()

            # NOTE: the "TMDB - 42%" / "Review 42%" / "needs review" meta-line
            # text this test targeted was removed by the GUI V4 roster spec
            # (poster-forward layout, no per-row meta line, §5). The
            # threshold-aware confidence *value* and review routing survive
            # on the model/action-bar; the phrasing itself has no equivalent.
            data = self._roster_row_data_for_index(workspace, 0)
            self.assertIsNotNone(data)
            self.assertEqual(data.confidence_pct, 42)
            self.assertEqual(workspace._queue_inline_btn.text(), "Approve Match")

            workspace.close()

    def test_media_workspace_reuses_unchanged_roster_widgets_on_refresh(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = []
                self.library_selected_index = None
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        def _make_state(name: str, tmdb_id: int) -> ScanState:
            return ScanState(
                folder=Path(f"C:/library/tv/{name}"),
                media_info={"id": tmdb_id, "name": name, "year": "2024"},
                preview_items=[
                    PreviewItem(
                        original=Path(f"C:/library/tv/{name}/Season 01/{name}.S01E01.mkv"),
                        new_name=f"{name} (2024) - S01E01 - Pilot.mkv",
                        target_dir=Path(f"C:/library/tv/{name}/Season 01"),
                        season=1,
                        episodes=[1],
                        status="OK",
                    )
                ],
                scanned=True,
                checked=True,
                confidence=1.0,
            )

        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
            first = _make_state("Example Show", 101)
            second = _make_state("Another Show", 202)
            media_ctrl = _FakeMediaController()
            media_ctrl.batch_states = [first, second]

            workspace = MediaWorkspace(
                media_type="tv",
                media_controller=media_ctrl,
                queue_controller=type(
                    "Q", (), {"add_tv_batch": lambda *args, **kwargs: BatchQueueResult(added=1)}
                )(),
                settings_service=settings,
            )
            workspace.show_ready()

            original_data = self._roster_row_data_for_index(workspace, 0)
            self.assertIsNotNone(original_data)

            second.queued = True
            workspace.refresh_from_controller()

            # State 0 (Example Show) itself did not change: its model row
            # data should be unaffected by state 1's regroup (previously
            # verified via per-row widget reuse; the model has no per-row
            # widgets, so assert content stability directly instead).
            refreshed_data = self._roster_row_data_for_index(workspace, 0)
            self.assertIsNotNone(refreshed_data)
            self.assertEqual(refreshed_data, original_data)

            workspace.close()

    def test_media_workspace_queues_tv_states_without_crashing_on_regroup(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeQueueController:
            def __init__(self):
                self.called = False

            def add_tv_batch(
                self,
                states,
                root,
                output_root,
                gating,
                settings_service=None,
                tmdb_client=None,
                progress=None,
            ):
                self.called = True
                for state in states:
                    state.queued = True
                return BatchQueueResult(added=len(states))

        class _FakeMediaController:
            def __init__(self):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = []
                self.library_selected_index = None
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        def _make_state(name: str, tmdb_id: int) -> ScanState:
            return ScanState(
                folder=Path(f"C:/library/tv/{name}"),
                media_info={"id": tmdb_id, "name": name, "year": "2024"},
                preview_items=[
                    PreviewItem(
                        original=Path(f"C:/library/tv/{name}/Season 01/{name}.S01E01.mkv"),
                        new_name=f"{name} (2024) - S01E01 - Pilot.mkv",
                        target_dir=Path(f"C:/library/tv/{name}/Season 01"),
                        season=1,
                        episodes=[1],
                        status="OK",
                    )
                ],
                scanned=True,
                checked=True,
                confidence=1.0,
            )

        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
            output = Path(tmp) / "tv-output"
            output.mkdir()
            settings.tv_output_folder = str(output)
            media_ctrl = _FakeMediaController()
            media_ctrl.batch_states = [
                _make_state("Show.One.2024", 101),
                _make_state("Show.Two.2024", 102),
            ]
            queue_ctrl = _FakeQueueController()

            workspace = MediaWorkspace(
                media_type="tv",
                media_controller=media_ctrl,
                queue_controller=queue_ctrl,
                settings_service=settings,
            )
            workspace.show_ready()

            workspace._queue_checked()
            self._app.processEvents()

            self.assertTrue(queue_ctrl.called)
            self._assert_roster_section_title(workspace, 0, "QUEUED")

            workspace.close()

    def test_queue_post_success_sync_failure_reports_queued_with_warnings(self):
        """add_batch succeeded (jobs exist) but the post-queue view sync
        raised: report 'Queued With Warnings' instead of 'Queue Failed',
        and still emit queue_changed so the queue tab learns."""
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeQueueController:
            def __init__(self):
                self.called = False

            def add_tv_batch(
                self,
                states,
                root,
                output_root,
                gating,
                settings_service=None,
                tmdb_client=None,
                progress=None,
            ):
                self.called = True
                for state in states:
                    state.queued = True
                return BatchQueueResult(added=len(states))

        class _FakeMediaController:
            def __init__(self):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = []
                self.library_selected_index = None
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        def _make_state(name: str, tmdb_id: int) -> ScanState:
            return ScanState(
                folder=Path(f"C:/library/tv/{name}"),
                media_info={"id": tmdb_id, "name": name, "year": "2024"},
                preview_items=[
                    PreviewItem(
                        original=Path(f"C:/library/tv/{name}/Season 01/{name}.S01E01.mkv"),
                        new_name=f"{name} (2024) - S01E01 - Pilot.mkv",
                        target_dir=Path(f"C:/library/tv/{name}/Season 01"),
                        season=1,
                        episodes=[1],
                        status="OK",
                    )
                ],
                scanned=True,
                checked=True,
                confidence=1.0,
            )

        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
            output = Path(tmp) / "tv-output"
            output.mkdir()
            settings.tv_output_folder = str(output)
            media_ctrl = _FakeMediaController()
            media_ctrl.batch_states = [
                _make_state("Show.One.2024", 101),
                _make_state("Show.Two.2024", 102),
            ]
            queue_ctrl = _FakeQueueController()

            workspace = MediaWorkspace(
                media_type="tv",
                media_controller=media_ctrl,
                queue_controller=queue_ctrl,
                settings_service=settings,
            )
            workspace.show_ready()

            calls = []

            class _Box:
                @staticmethod
                def warning(parent, title, text):
                    calls.append((title, text))

            workspace._media_ctrl.sync_queued_states = lambda: (_ for _ in ()).throw(
                RuntimeError("sync boom")
            )
            fired = []
            workspace.queue_changed.connect(lambda: fired.append(True))
            workspace._action_coordinator.queue_states(
                media_ctrl.batch_states,
                empty_message="Select at least one actionable item before queueing.",
                warning_box=_Box,
            )
            self._app.processEvents()

            self.assertTrue(queue_ctrl.called)  # batch handoff succeeded
            self.assertEqual(calls[0][0], "Queued With Warnings")
            self.assertIn("queued", calls[0][1])
            self.assertEqual(fired, [True])  # jobs exist; queue tab must learn

            workspace.close()

    def test_queue_batch_failure_reports_queue_failed_without_queue_changed(self):
        """add_tv_batch itself raised: box titled 'Queue Failed', and
        queue_changed must NOT be emitted (no jobs exist to learn about)."""
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _ExplodingQueueController:
            def __init__(self):
                self.called = False

            def add_tv_batch(
                self,
                states,
                root,
                output_root,
                gating,
                settings_service=None,
                tmdb_client=None,
                progress=None,
            ):
                self.called = True
                raise RuntimeError("queue boom")

        class _FakeMediaController:
            def __init__(self):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = []
                self.library_selected_index = None
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        def _make_state(name: str, tmdb_id: int) -> ScanState:
            return ScanState(
                folder=Path(f"C:/library/tv/{name}"),
                media_info={"id": tmdb_id, "name": name, "year": "2024"},
                preview_items=[
                    PreviewItem(
                        original=Path(f"C:/library/tv/{name}/Season 01/{name}.S01E01.mkv"),
                        new_name=f"{name} (2024) - S01E01 - Pilot.mkv",
                        target_dir=Path(f"C:/library/tv/{name}/Season 01"),
                        season=1,
                        episodes=[1],
                        status="OK",
                    )
                ],
                scanned=True,
                checked=True,
                confidence=1.0,
            )

        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
            output = Path(tmp) / "tv-output"
            output.mkdir()
            settings.tv_output_folder = str(output)
            media_ctrl = _FakeMediaController()
            media_ctrl.batch_states = [_make_state("Show.One.2024", 101)]
            queue_ctrl = _ExplodingQueueController()

            workspace = MediaWorkspace(
                media_type="tv",
                media_controller=media_ctrl,
                queue_controller=queue_ctrl,
                settings_service=settings,
            )
            workspace.show_ready()

            calls = []

            class _Box:
                @staticmethod
                def warning(parent, title, text):
                    calls.append((title, text))

            fired = []
            workspace.queue_changed.connect(lambda: fired.append(True))
            workspace._action_coordinator.queue_states(
                media_ctrl.batch_states,
                empty_message="Select at least one actionable item before queueing.",
                warning_box=_Box,
            )
            self._app.processEvents()

            self.assertTrue(queue_ctrl.called)
            self.assertEqual(calls[0][0], "Queue Failed")
            self.assertIn("queue boom", calls[0][1])
            self.assertEqual(fired, [])  # nothing queued, nothing to learn
            workspace.close()

    def test_media_workspace_queueing_shows_busy_overlay_during_handoff(self):
        from plex_renamer.gui_qt.widgets.busy_overlay import BusyOverlay
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeQueueController:
            def add_tv_batch(
                self,
                states,
                root,
                output_root,
                gating,
                settings_service=None,
                tmdb_client=None,
                progress=None,
            ):
                for state in states:
                    state.queued = True
                return BatchQueueResult(added=len(states))

        class _FakeMediaController:
            def __init__(self):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = []
                self.library_selected_index = None
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        state = ScanState(
            folder=Path("C:/library/tv/Overlay.Show.2024"),
            media_info={"id": 101, "name": "Overlay Show", "year": "2024"},
            preview_items=[
                PreviewItem(
                    original=Path(
                        "C:/library/tv/Overlay.Show.2024/Season 01/Overlay.Show.S01E01.mkv"
                    ),
                    new_name="Overlay Show (2024) - S01E01 - Pilot.mkv",
                    target_dir=Path("C:/library/tv/Overlay Show (2024)/Season 01"),
                    season=1,
                    episodes=[1],
                    status="OK",
                )
            ],
            scanned=True,
            checked=True,
            confidence=1.0,
        )

        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
            output = Path(tmp) / "tv-output"
            output.mkdir()
            settings.tv_output_folder = str(output)
            media_ctrl = _FakeMediaController()
            media_ctrl.batch_states = [state]
            queue_ctrl = _FakeQueueController()

            workspace = MediaWorkspace(
                media_type="tv",
                media_controller=media_ctrl,
                queue_controller=queue_ctrl,
                settings_service=settings,
            )
            workspace.resize(1200, 700)
            workspace.show()
            workspace.show_ready()
            self._app.processEvents()

            seen: dict[str, bool] = {}
            original_add = queue_ctrl.add_tv_batch

            def observing_add(
                states,
                root,
                output_root,
                gating,
                settings_service=None,
                tmdb_client=None,
                progress=None,
            ):
                overlay = workspace.findChild(BusyOverlay)
                seen["visible"] = overlay is not None and overlay.isVisible()
                return original_add(states, root, output_root, gating)

            queue_ctrl.add_tv_batch = observing_add
            workspace._roster_queue_btn.click()

            self.assertTrue(seen.get("visible"))
            self.assertIsNone(workspace.findChild(BusyOverlay))
            workspace.close()

    def test_media_workspace_preserves_movie_preview_after_queue_regroup(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeQueueController:
            def __init__(self):
                self.called = False

            def add_movie_batch(
                self,
                states,
                root,
                output_root,
                gating,
                settings_service=None,
                tmdb_client=None,
                progress=None,
            ):
                self.called = True
                for state in states:
                    state.queued = True
                return BatchQueueResult(added=len(states))

        class _FakeMediaController:
            def __init__(self):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = []
                self.library_selected_index = None
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.movie_library_states):
                    return self.movie_library_states[index]
                return None

            def sync_queued_states(self):
                return None

        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
            output = Path(tmp) / "movie-output"
            output.mkdir()
            settings.movie_output_folder = str(output)
            state = ScanState(
                folder=Path("C:/library/movies/Arrival.2016"),
                media_info={"id": 22, "title": "Arrival", "year": "2016", "_media_type": "movie"},
                preview_items=[
                    PreviewItem(
                        original=Path("C:/library/movies/Arrival.2016/Arrival.2016.mkv"),
                        new_name="Arrival (2016).mkv",
                        target_dir=Path("C:/library/movies/Arrival (2016)"),
                        season=None,
                        episodes=[],
                        status="OK",
                        media_type="movie",
                        media_id=22,
                        media_name="Arrival",
                    )
                ],
                scanned=True,
                checked=True,
                confidence=1.0,
            )
            media_ctrl = _FakeMediaController()
            media_ctrl.movie_library_states = [state]
            queue_ctrl = _FakeQueueController()

            workspace = MediaWorkspace(
                media_type="movie",
                media_controller=media_ctrl,
                queue_controller=queue_ctrl,
                settings_service=settings,
            )
            workspace.show_ready()

            row_count_before = workspace._work_panel.model.rowCount()
            self.assertGreater(row_count_before, 0)
            workspace._queue_checked()
            self._app.processEvents()

            self.assertTrue(queue_ctrl.called)
            self._assert_roster_section_title(workspace, 0, "QUEUED")
            # Preview content is preserved across the queue regroup.
            self.assertEqual(workspace._work_panel.model.rowCount(), row_count_before)
            self.assertTrue(
                any("FOLDER" in t.upper() for t in self._episode_section_titles(workspace))
            )
            self.assertIsNotNone(self._folder_section_target(workspace))

            workspace.close()

    def test_queue_selected_movie_auto_checks_unchecked_state(self):
        """Clicking 'queue this movie' on an unchecked entry IS the approval
        (round5 5a) - it must auto-check the entry rather than refuse with
        'select at least one actionable file'."""
        from plex_renamer.gui_qt.widgets._media_workspace_queue_actions import (
            queue_selected_state,
        )
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeQueueController:
            def __init__(self):
                self.called_with = None
                self.checked_at_call = None

            def add_movie_batch(
                self,
                states,
                root,
                output_root,
                gating,
                settings_service=None,
                tmdb_client=None,
                progress=None,
            ):
                # Capture checked-state at call time: a successful queue
                # legitimately unchecks the item afterward (queued items move
                # to the QUEUED group and are no longer "selected to queue"),
                # so the meaningful assertion is what gating saw, not what
                # survives the post-queue refresh.
                self.called_with = list(states)
                self.checked_at_call = [state.checked for state in states]
                for state in states:
                    state.queued = True
                return BatchQueueResult(added=len(states))

        class _FakeMediaController:
            def __init__(self):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = []
                self.library_selected_index = None
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.movie_library_states):
                    return self.movie_library_states[index]
                return None

            def sync_queued_states(self):
                return None

        class _FakeWarningBox:
            calls: list = []

            @staticmethod
            def warning(parent, title, text):
                _FakeWarningBox.calls.append((title, text))

        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
            output = Path(tmp) / "movie-output"
            output.mkdir()
            settings.movie_output_folder = str(output)
            state = ScanState(
                folder=Path("C:/library/movies/Arrival.2016"),
                media_info={"id": 22, "title": "Arrival", "year": "2016"},
                preview_items=[
                    PreviewItem(
                        original=Path("C:/library/movies/Arrival.2016/Arrival.2016.mkv"),
                        new_name="Arrival (2016).mkv",
                        target_dir=Path("C:/library/movies/Arrival (2016)"),
                        season=None,
                        episodes=[],
                        status="OK",
                        media_type="movie",
                        media_id=22,
                        media_name="Arrival",
                    )
                ],
                scanned=True,
                checked=False,
                confidence=1.0,
            )
            media_ctrl = _FakeMediaController()
            media_ctrl.movie_library_states = [state]
            queue_ctrl = _FakeQueueController()

            workspace = MediaWorkspace(
                media_type="movie",
                media_controller=media_ctrl,
                queue_controller=queue_ctrl,
                settings_service=settings,
            )
            workspace.show_ready()

            self.assertFalse(state.checked)

            queue_selected_state(workspace, warning_box=_FakeWarningBox)

            self.assertEqual(queue_ctrl.called_with, [state])
            self.assertEqual(queue_ctrl.checked_at_call, [True])
            self.assertEqual(_FakeWarningBox.calls, [])

            workspace.close()

    def test_queue_selected_movie_reverts_auto_check_when_queue_fails(self):
        """If the queue attempt bails after the auto-check, the revert must
        unwind BOTH state.checked and the per-file check_vars bindings -
        otherwise the roster checkbox stays visibly checked over an
        unchecked state."""
        from plex_renamer.gui_qt.widgets._media_workspace_queue_actions import (
            queue_selected_state,
        )
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _ExplodingQueueController:
            def __init__(self):
                self.called = False

            def add_movie_batch(
                self,
                states,
                root,
                output_root,
                gating,
                settings_service=None,
                tmdb_client=None,
                progress=None,
            ):
                self.called = True
                raise RuntimeError("queue boom")

        class _FakeMediaController:
            def __init__(self):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = []
                self.library_selected_index = None
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.movie_library_states):
                    return self.movie_library_states[index]
                return None

            def sync_queued_states(self):
                return None

        class _FakeWarningBox:
            calls: list = []

            @staticmethod
            def warning(parent, title, text):
                _FakeWarningBox.calls.append((title, text))

        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
            output = Path(tmp) / "movie-output"
            output.mkdir()
            settings.movie_output_folder = str(output)
            state = ScanState(
                folder=Path("C:/library/movies/Arrival.2016"),
                media_info={"id": 22, "title": "Arrival", "year": "2016"},
                preview_items=[
                    PreviewItem(
                        original=Path("C:/library/movies/Arrival.2016/Arrival.2016.mkv"),
                        new_name="Arrival (2016).mkv",
                        target_dir=Path("C:/library/movies/Arrival (2016)"),
                        season=None,
                        episodes=[],
                        status="OK",
                        media_type="movie",
                        media_id=22,
                        media_name="Arrival",
                    )
                ],
                scanned=True,
                checked=False,
                confidence=1.0,
            )
            media_ctrl = _FakeMediaController()
            media_ctrl.movie_library_states = [state]
            queue_ctrl = _ExplodingQueueController()

            workspace = MediaWorkspace(
                media_type="movie",
                media_controller=media_ctrl,
                queue_controller=queue_ctrl,
                settings_service=settings,
            )
            workspace.show_ready()

            self.assertFalse(state.checked)

            queue_selected_state(workspace, warning_box=_FakeWarningBox)

            self.assertTrue(queue_ctrl.called)
            self.assertEqual(len(_FakeWarningBox.calls), 1)
            self.assertEqual(_FakeWarningBox.calls[0][0], "Queue Failed")
            # Auto-check fully unwound: flag AND bindings back to False.
            self.assertFalse(state.checked)
            self.assertFalse(state.queued)
            self.assertEqual(
                {key: binding.get() for key, binding in state.check_vars.items()},
                {"0": False},
            )

            workspace.close()

    def test_queue_selected_show_auto_checks_unchecked_state(self):
        """TV parity for round5 5a: 'Queue This Show' shares queue_selected_state
        with the movie path, so an unchecked show is auto-checked too."""
        from plex_renamer.gui_qt.widgets._media_workspace_queue_actions import (
            queue_selected_state,
        )
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeQueueController:
            def __init__(self):
                self.called_with = None
                self.checked_at_call = None

            def add_tv_batch(
                self,
                states,
                root,
                output_root,
                gating,
                settings_service=None,
                tmdb_client=None,
                progress=None,
            ):
                self.called_with = list(states)
                self.checked_at_call = [state.checked for state in states]
                for state in states:
                    state.queued = True
                return BatchQueueResult(added=len(states))

        class _FakeMediaController:
            def __init__(self):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = []
                self.library_selected_index = None
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        class _FakeWarningBox:
            calls: list = []

            @staticmethod
            def warning(parent, title, text):
                _FakeWarningBox.calls.append((title, text))

        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
            output = Path(tmp) / "tv-output"
            output.mkdir()
            settings.tv_output_folder = str(output)
            state = ScanState(
                folder=Path("C:/library/tv/Show.One.2024"),
                media_info={"id": 101, "name": "Show One", "year": "2024"},
                preview_items=[
                    PreviewItem(
                        original=Path("C:/library/tv/Show.One.2024/Season 01/Show.One.S01E01.mkv"),
                        new_name="Show One (2024) - S01E01 - Pilot.mkv",
                        target_dir=Path("C:/library/tv/Show.One.2024/Season 01"),
                        season=1,
                        episodes=[1],
                        status="OK",
                    )
                ],
                scanned=True,
                checked=False,
                confidence=1.0,
            )
            media_ctrl = _FakeMediaController()
            media_ctrl.batch_states = [state]
            queue_ctrl = _FakeQueueController()

            workspace = MediaWorkspace(
                media_type="tv",
                media_controller=media_ctrl,
                queue_controller=queue_ctrl,
                settings_service=settings,
            )
            workspace.show_ready()

            self.assertFalse(state.checked)

            queue_selected_state(workspace, warning_box=_FakeWarningBox)

            self.assertEqual(queue_ctrl.called_with, [state])
            self.assertEqual(queue_ctrl.checked_at_call, [True])
            self.assertEqual(_FakeWarningBox.calls, [])

            workspace.close()

    def test_media_workspace_movie_refresh_keeps_same_folder_movies_unique_after_approval(self):
        from plex_renamer.gui_qt.widgets._roster_model import ROW_DATA_ROLE
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeMediaController:
            def __init__(self, states):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = states
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.movie_library_states):
                    return self.movie_library_states[index]
                return None

            def sync_queued_states(self):
                return None

        root = Path("C:/library/movies/Quarantine")
        matched_one = ScanState(
            folder=root,
            source_file=root / "[QM] Evangelion 1.11.mkv",
            media_info={
                "id": 11,
                "title": "Evangelion 1.11",
                "year": "2007",
                "_media_type": "movie",
            },
            preview_items=[
                PreviewItem(
                    original=root / "[QM] Evangelion 1.11.mkv",
                    new_name="Evangelion 1.11 (2007).mkv",
                    target_dir=Path("C:/library/movies/Evangelion 1.11 (2007)"),
                    season=None,
                    episodes=[],
                    status="OK",
                    media_type="movie",
                    media_id=11,
                    media_name="Evangelion 1.11",
                )
            ],
            scanned=True,
            checked=True,
            confidence=1.0,
        )
        matched_two = ScanState(
            folder=root,
            source_file=root / "[LG] Evangelion 3.0+1.11.mkv",
            media_info={
                "id": 44,
                "title": "Evangelion: 3.0+1.11 Thrice Upon a Time",
                "year": "2021",
                "_media_type": "movie",
            },
            preview_items=[
                PreviewItem(
                    original=root / "[LG] Evangelion 3.0+1.11.mkv",
                    new_name="Evangelion: 3.0+1.11 Thrice Upon a Time (2021).mkv",
                    target_dir=Path(
                        "C:/library/movies/Evangelion: 3.0+1.11 Thrice Upon a Time (2021)"
                    ),
                    season=None,
                    episodes=[],
                    status="OK",
                    media_type="movie",
                    media_id=44,
                    media_name="Evangelion: 3.0+1.11 Thrice Upon a Time",
                )
            ],
            scanned=True,
            checked=True,
            confidence=1.0,
        )
        review_state = ScanState(
            folder=root,
            source_file=root / "[Baws] Evangelion 3.33.mkv",
            media_info={
                "id": 33,
                "title": "Evangelion: 3.0 You Can (Not) Redo",
                "year": "2012",
                "_media_type": "movie",
            },
            preview_items=[
                PreviewItem(
                    original=root / "[Baws] Evangelion 3.33.mkv",
                    new_name="Evangelion: 3.0 You Can (Not) Redo (2012).mkv",
                    target_dir=Path("C:/library/movies/Evangelion: 3.0 You Can (Not) Redo (2012)"),
                    season=None,
                    episodes=[],
                    status="REVIEW: verify",
                    media_type="movie",
                    media_id=33,
                    media_name="Evangelion: 3.0 You Can (Not) Redo",
                )
            ],
            scanned=True,
            checked=False,
            confidence=0.42,
        )

        media_ctrl = _FakeMediaController([matched_one, matched_two, review_state])
        workspace = MediaWorkspace(media_type="movie", media_controller=media_ctrl)
        workspace.show_ready()
        self.assertEqual(workspace._roster_panel.model.rowCount(), 5)

        review_state.match_origin = "manual"
        review_state.checked = True
        workspace.refresh_from_controller()
        workspace.refresh_from_controller()

        model = workspace._roster_panel.model
        self.assertEqual(model.rowCount(), 4)
        self._assert_roster_section_title(workspace, 0, "MATCHED")

        seen_titles = []
        for row in range(model.rowCount()):
            if model.entry_kind_at(row) != "state":
                continue
            data = model.index(row, 0).data(ROW_DATA_ROLE)
            seen_titles.append(data.title)
        self.assertEqual(len(seen_titles), 3)
        self.assertEqual(len(set(seen_titles)), 3)
        self.assertIn("Evangelion: 3.0 You Can (Not) Redo (2012)", seen_titles)

        workspace.close()


# ---------------------------------------------------------------------------
# Bulk Assign workspace wiring tests (Plan 4, Task 4)
# ---------------------------------------------------------------------------


class BulkAssignWorkspaceTests(QtSmokeBase):
    def tearDown(self):
        # Same per-test disposal as QtMediaWorkspaceTests: every test here
        # builds a MediaWorkspace via _tv_workspace_with_table_state.
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        self._dispose_top_level_widgets(MediaWorkspace)
        super().tearDown()

    def _bulk_table_state(
        self, folder_name: str, *, media_id: int = 101, assign_first: bool = False
    ):
        from plex_renamer.app.services.episode_mapping_service import EpisodeMappingService
        from plex_renamer.engine.episode_assignments import (
            ORIGIN_MANUAL,
            EpisodeAssignmentTable,
            EpisodeSlot,
        )

        table = EpisodeAssignmentTable()
        for episode in range(1, 5):
            table.add_slot(EpisodeSlot(season=1, episode=episode, title=f"Ep {episode}"))
        file_ids: list[int] = []
        # Each file carries scan-time parse evidence matching its own free
        # slot (a->E01, b->E02, c->E03) so auto_map_remaining (Task 14:
        # evidence-based, no positional fallback) still maps all three.
        evidence_by_name = {
            "a.mkv": (1,),
            "b.mkv": (2,),
            "c.mkv": (3,),
        }
        for name, episodes in evidence_by_name.items():
            entry = table.add_file(
                Path(f"C:/library/tv/{folder_name}/{name}"),
                parsed_episodes=episodes,
                season_hint=1,
            )
            table.mark_unassigned(entry.file_id, "no episode parsed")
            file_ids.append(entry.file_id)
        if assign_first:
            table.assign(file_ids[0], 1, [1], origin=ORIGIN_MANUAL)
            table.assign(file_ids[1], 1, [2], origin=ORIGIN_MANUAL)
        state = ScanState(
            folder=Path(f"C:/library/tv/{folder_name}"),
            media_info={"id": media_id, "name": folder_name, "year": "2024"},
        )
        state.scanned = True
        state.confidence = 1.0
        state.assignments = table
        EpisodeMappingService().reproject(state)
        return state

    def _tv_workspace_with_table_state(
        self, *, assign_first: bool = False, extra_state: bool = False
    ):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        state = self._bulk_table_state("Show", assign_first=assign_first)
        states = [state]
        if extra_state:
            states.append(self._bulk_table_state("Other Show", media_id=102))

        class _FakeQueueController:
            def add_tv_batch(
                self,
                states,
                root,
                output_root,
                gating,
                settings_service=None,
                tmdb_client=None,
                progress=None,
            ):
                return None

        class _FakeMediaController:
            def __init__(self):
                self.command_gating = CommandGatingService()
                self.batch_states = states
                self.movie_library_states = []
                self.library_selected_index = 0
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        tmp = TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        settings = SettingsService(path=Path(tmp.name) / "settings.json")
        workspace = MediaWorkspace(
            media_type="tv",
            media_controller=_FakeMediaController(),
            queue_controller=_FakeQueueController(),
            settings_service=settings,
        )
        # No addCleanup(workspace.close) here: tearDown's
        # _dispose_top_level_widgets already close+deleteLater's the
        # workspace, and cleanups run *after* tearDown — a close() cleanup
        # would then poke an already-deleted C++ object and raise.
        workspace.resize(1200, 700)
        workspace.show()
        workspace.show_ready()
        self._app.processEvents()
        self.assertIs(workspace._selected_state(), state)
        return workspace

    def test_overflow_entry_enters_bulk_mode(self):
        workspace = self._tv_workspace_with_table_state()
        workspace._enter_bulk_assign()
        self.assertTrue(workspace._work_panel.bulk_assign_active())
        # files pane populated from the state's unassigned previews
        self.assertEqual(workspace._work_panel.bulk_panel._files_model.rowCount(), 3)

    def test_apply_lands_assignments_and_exits_with_one_toast(self):
        workspace = self._tv_workspace_with_table_state()
        state = workspace._selected_state()
        workspace._enter_bulk_assign()
        panel = workspace._work_panel.bulk_panel
        panel.auto_map_remaining()
        toasts: list[tuple] = []
        workspace.toast_requested.connect(lambda *a: toasts.append(a))
        panel._apply_button.click()
        self.assertFalse(workspace._work_panel.bulk_assign_active())
        self.assertEqual(len(toasts), 1)
        self.assertEqual(toasts[0][2], "success")
        self.assertIn("3", toasts[0][1])  # "Assigned 3 file(s)."
        table = state.assignments
        self.assertEqual(len(table.assignments()), 3)

    def test_apply_with_skipped_pair_reports_error_tone_and_reason(self):
        # One staged pair targets a slot that is no longer valid in the table
        # (S1E99 doesn't exist — the claimed/invalid-slot skip path in
        # apply_assignments): the single toast must switch to the error tone
        # and spell out the skip reason.
        workspace = self._tv_workspace_with_table_state()
        state = workspace._selected_state()
        workspace._enter_bulk_assign()
        panel = workspace._work_panel.bulk_panel
        panel.auto_map_remaining()
        toasts: list[tuple] = []
        workspace.toast_requested.connect(lambda *a: toasts.append(a))
        staged = panel.staged_pairs()
        pairs = [*staged[:-1], (staged[-1][0], 1, 99)]
        workspace._on_bulk_apply(pairs)
        self.assertFalse(workspace._work_panel.bulk_assign_active())
        self.assertEqual(len(toasts), 1)
        self.assertEqual(toasts[0][2], "error")
        self.assertIn("skipped (slot already claimed or no longer valid)", toasts[0][1])
        self.assertEqual(len(state.assignments.assignments()), 2)

    def test_cancel_discards_and_restores_table(self):
        workspace = self._tv_workspace_with_table_state()
        state = workspace._selected_state()
        workspace._enter_bulk_assign()
        workspace._work_panel.bulk_panel.auto_map_remaining()
        workspace._work_panel.bulk_panel._cancel_button.click()
        self.assertFalse(workspace._work_panel.bulk_assign_active())
        self.assertEqual(state.assignments.assignments(), [])  # nothing applied

    def test_unassign_all_confirms_with_exact_count_and_offers_bulk(self):
        from PySide6.QtWidgets import QMessageBox

        workspace = self._tv_workspace_with_table_state(assign_first=True)  # pre-assign 2 files
        state = workspace._selected_state()
        prompts: list[str] = []

        class _Box:
            StandardButton = QMessageBox.StandardButton

            @staticmethod
            def question(parent, title, text, buttons, default):
                prompts.append(text)
                return QMessageBox.StandardButton.Yes  # plain unassign

        workspace._action_coordinator.unassign_all_episode_mappings(warning_box=_Box)
        self.assertIn("2", prompts[0])  # exact count in the prompt
        self.assertEqual(state.assignments.assignments(), [])
        self.assertFalse(workspace._work_panel.bulk_assign_active())

    def test_unassign_all_bulk_offer_enters_mode(self):
        from PySide6.QtWidgets import QMessageBox

        workspace = self._tv_workspace_with_table_state(assign_first=True)

        class _Box:
            StandardButton = QMessageBox.StandardButton

            @staticmethod
            def question(parent, title, text, buttons, default):
                return QMessageBox.StandardButton.YesToAll  # "Unassign & Bulk Assign…"

        workspace._action_coordinator.unassign_all_episode_mappings(warning_box=_Box)
        self.assertTrue(workspace._work_panel.bulk_assign_active())

    def test_apply_with_missing_table_exits_gracefully(self):
        # I1: the assignment table vanished between enter and Apply (rescan /
        # reset). Apply must exit bulk mode gracefully - no exception, no
        # service call, no success toast.
        workspace = self._tv_workspace_with_table_state()
        state = workspace._selected_state()
        workspace._enter_bulk_assign()
        panel = workspace._work_panel.bulk_panel
        panel.auto_map_remaining()
        toasts: list[tuple] = []
        workspace.toast_requested.connect(lambda *a: toasts.append(a))
        state.assignments = None
        workspace._on_bulk_apply(panel.staged_pairs())  # must not raise
        self.assertFalse(workspace._work_panel.bulk_assign_active())
        self.assertEqual(toasts, [])  # nothing was applied

    def test_selection_change_discards_bulk_mode(self):
        # I2: bulk mode is pinned to the state it was entered on; switching
        # the roster selection mid-staging discards the session instead of
        # applying the stale pairs against the newly selected show.
        workspace = self._tv_workspace_with_table_state(extra_state=True)
        state0 = workspace._selected_state()
        state1 = workspace._media_ctrl.batch_states[1]
        workspace._enter_bulk_assign()
        panel = workspace._work_panel
        panel.bulk_panel.auto_map_remaining()
        # A repopulate of the SAME state (background refresh) keeps the mode…
        workspace._populate_preview(state0)
        self.assertTrue(panel.bulk_assign_active())
        # …but a real roster switch exits and discards staging. Drive the
        # view's selection model (what a user click/keyboard nav does) — the
        # programmatic _set_roster_current_state suppresses state_selected by
        # design and never populates the work panel itself.
        roster = workspace._roster_panel
        second_row = roster.model.row_for_state_index(1)
        self.assertGreaterEqual(second_row, 0)
        roster.view.setCurrentIndex(roster.model.index(second_row, 0))
        self._app.processEvents()
        self.assertFalse(panel.bulk_assign_active())
        self.assertEqual(panel.bulk_panel.staged_pairs(), [])
        self.assertEqual(state0.assignments.assignments(), [])  # nothing landed
        # A fresh bulk session on the new selection still works end-to-end.
        self.assertIs(workspace._selected_state(), state1)
        workspace._enter_bulk_assign()
        workspace._work_panel.bulk_panel.auto_map_remaining()
        toasts: list[tuple] = []
        workspace.toast_requested.connect(lambda *a: toasts.append(a))
        workspace._work_panel.bulk_panel._apply_button.click()
        self.assertFalse(workspace._work_panel.bulk_assign_active())
        self.assertEqual(len(toasts), 1)
        self.assertEqual(len(state1.assignments.assignments()), 3)
        self.assertEqual(state0.assignments.assignments(), [])

    def test_bulk_apply_shows_busy_overlay_during_service_call(self):
        from unittest.mock import patch

        from plex_renamer.gui_qt.widgets.busy_overlay import BusyOverlay

        workspace = self._tv_workspace_with_table_state()
        workspace._enter_bulk_assign()
        panel = workspace._work_panel.bulk_panel
        panel.auto_map_remaining()
        seen: dict[str, bool] = {}

        def observing_apply(service_self, state, *, assign_pairs, unassign_file_ids):
            overlay = workspace._work_panel.findChild(BusyOverlay)
            seen["visible"] = overlay is not None and overlay.isVisible()
            return (len(assign_pairs), 0)

        with patch(
            "plex_renamer.gui_qt.widgets._media_workspace_actions.EpisodeMappingService.apply_bulk",
            new=observing_apply,
        ):
            workspace._on_bulk_apply(panel.staged_pairs())
        self.assertTrue(seen.get("visible"))
        self.assertIsNone(workspace._work_panel.findChild(BusyOverlay))

    def test_apply_stages_unassign_and_assign_together(self):
        # Bulk Assign v2: one unassign + one assign staged in the same
        # session must both land through a single apply_requested(pairs,
        # unassigns) round trip - the table changes both ways and the
        # toast reports both counts.
        workspace = self._tv_workspace_with_table_state(assign_first=True)
        state = workspace._selected_state()
        table = state.assignments
        unassign_file_id = table.claims(1, 1)[0].file_id  # a.mkv, claims S01E01
        assign_file_id = next(
            entry.file_id
            for entry in table.files.values()
            if entry.path.name == "c.mkv"  # unassigned fixture file
        )
        workspace._enter_bulk_assign()
        panel = workspace._work_panel.bulk_panel
        # Stage the unassign via the real slot-click path.
        row_slot = panel._slots_model.row_for_key((1, 1))
        panel._on_slot_clicked(panel._slots_model.index(row_slot, 0))
        self.assertEqual(panel.staged_unassigns(), [unassign_file_id])
        # Stage the assign via the real drag/drop path, onto a free slot.
        panel._handle_drop(assign_file_id, (1, 3))
        self.assertIn((assign_file_id, 1, 3), panel.staged_pairs())
        toasts: list[tuple] = []
        workspace.toast_requested.connect(lambda *a: toasts.append(a))
        panel._apply_button.click()
        self.assertFalse(workspace._work_panel.bulk_assign_active())
        self.assertEqual(len(toasts), 1)
        self.assertEqual(toasts[0][2], "success")
        self.assertIn("Assigned 1 file(s).", toasts[0][1])
        self.assertIn("Unassigned 1 file(s).", toasts[0][1])
        # The unassigned file lost its claim...
        self.assertIsNone(table.assignment_for(unassign_file_id))
        # ...and the newly assigned file picked up the staged slot.
        new_assignment = table.assignment_for(assign_file_id)
        self.assertIsNotNone(new_assignment)
        self.assertEqual(new_assignment.season, 1)
        self.assertEqual(tuple(new_assignment.episodes), (3,))


# ---------------------------------------------------------------------------
# EpisodeAssignDialog tests
# ---------------------------------------------------------------------------

from plex_renamer.app.models.state_models import EpisodeSlotChoice  # noqa: E402
from plex_renamer.gui_qt.widgets.episode_assign_dialog import EpisodeAssignDialog  # noqa: E402


def _slot_choices():
    return [
        EpisodeSlotChoice(season=1, episode=1, title="Pilot", claimed_by="e1.mkv"),
        EpisodeSlotChoice(season=1, episode=2, title="Heist"),
        EpisodeSlotChoice(season=1, episode=3, title="Endgame"),
        EpisodeSlotChoice(season=2, episode=1, title="Reboot"),
    ]


class TestEpisodeAssignDialog(QtSmokeBase):
    def test_contiguous_same_season_selection_enables_ok(self):
        dialog = EpisodeAssignDialog(slots=_slot_choices())
        dialog.set_checked([(1, 2), (1, 3)])
        self.assertTrue(dialog.is_selection_valid())
        dialog.close()

    def test_non_contiguous_selection_disables_ok(self):
        dialog = EpisodeAssignDialog(slots=_slot_choices())
        dialog.set_checked([(1, 1), (1, 3)])
        self.assertFalse(dialog.is_selection_valid())
        self.assertIn("contiguous", dialog.validation_text().lower())
        dialog.close()

    def test_cross_season_selection_disables_ok(self):
        dialog = EpisodeAssignDialog(slots=_slot_choices())
        dialog.set_checked([(1, 3), (2, 1)])
        self.assertFalse(dialog.is_selection_valid())
        self.assertIn("season", dialog.validation_text().lower())
        dialog.close()

    def test_claimed_slot_shows_claimant(self):
        dialog = EpisodeAssignDialog(slots=_slot_choices())
        self.assertIn("e1.mkv", dialog.slot_row_text(1, 1))
        dialog.close()

    def test_selected_episodes_returned(self):
        dialog = EpisodeAssignDialog(slots=_slot_choices())
        dialog.set_checked([(1, 2), (1, 3)])
        self.assertEqual(dialog.selected_episodes(), [(1, 2), (1, 3)])
        dialog.close()

    def test_current_slot_tagged_current_not_claimed(self):
        slots = [
            EpisodeSlotChoice(season=2, episode=5, title="Goodbye", claimed_by="file.mkv"),
        ]
        dialog = EpisodeAssignDialog(slots=slots, current_keys={(2, 5)})
        text = dialog.slot_row_text(2, 5)
        self.assertIn("[current]", text)
        self.assertNotIn("claimed by", text)
        dialog.close()

    def test_focus_season_expanded_others_collapsed(self):
        slots = [
            EpisodeSlotChoice(season=0, episode=1, title="Special"),
            EpisodeSlotChoice(season=1, episode=1, title="Pilot"),
            EpisodeSlotChoice(season=2, episode=5, title="Goodbye"),
        ]
        dialog = EpisodeAssignDialog(slots=slots, current_keys={(2, 5)})
        self.assertTrue(dialog.is_season_expanded(2))
        self.assertFalse(dialog.is_season_expanded(0))
        self.assertFalse(dialog.is_season_expanded(1))
        dialog.close()

    def test_preselected_keys_start_checked(self):
        dialog = EpisodeAssignDialog(slots=_slot_choices(), preselected=[(1, 2)])
        self.assertEqual(dialog.selected_episodes(), [(1, 2)])
        dialog.close()

    def test_dialog_is_dpi_sized_with_no_horizontal_scrollbar(self):
        from plex_renamer.gui_qt import _scale

        dialog = EpisodeAssignDialog(slots=_slot_choices())
        self.assertGreaterEqual(dialog.minimumWidth(), _scale.px(460))
        self.assertGreaterEqual(dialog.minimumHeight(), _scale.px(420))
        self.assertGreaterEqual(dialog.width(), dialog.minimumWidth())
        self.assertEqual(
            dialog._tree.horizontalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        )
        dialog.close()

    def test_assign_dialog_shows_full_filename_unelided(self):
        from plex_renamer.app.models.state_models import EpisodeSlotChoice
        from plex_renamer.gui_qt.widgets.episode_assign_dialog import EpisodeAssignDialog

        long_name = "Show.Name.2020.S01E01.Absurdly.Long.Release.Tag.Chain.1080p.WEB-DL.DDP5.1.H.264-GROUP.mkv"
        dialog = EpisodeAssignDialog(
            slots=[EpisodeSlotChoice(season=1, episode=1, title="One")],
            file_label=long_name,
        )
        label = dialog._file_label
        self.assertEqual(label.text(), long_name)  # no "…" elision
        self.assertTrue(label.wordWrap())
        dialog.close()
