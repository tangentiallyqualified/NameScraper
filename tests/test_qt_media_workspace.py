from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from plex_renamer.app.controllers.queue_controller import BatchQueueResult
from plex_renamer.app.services.cache_service import PersistentCacheService
from plex_renamer.app.services.command_gating_service import CommandGatingService
from plex_renamer.app.services.settings_service import SettingsService
from plex_renamer.constants import JobStatus
from plex_renamer.engine import (
    CompanionFile,
    CompletenessReport,
    PreviewItem,
    RenameResult,
    ScanState,
    SeasonCompleteness,
)
from plex_renamer.job_store import JobStore

from conftest_qt import QtSmokeBase


class QtMediaWorkspaceTests(QtSmokeBase):
    def test_media_workspace_queue_buttons_use_distinct_labels(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeQueueController:
            def add_tv_batch(self, states, root, output_root, gating):
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
                    original=Path("C:/library/tv/Example.Show.2024/Season 01/Example.Show.S01E01.mkv"),
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
            self.assertIs(workspace._queue_inline_btn, workspace._detail_panel.primary_action_button)
            self.assertGreater(
                workspace._queue_inline_btn.mapTo(workspace._detail_panel._body, QPoint(0, 0)).y(),
                workspace._detail_panel._poster.mapTo(workspace._detail_panel._body, QPoint(0, 0)).y(),
            )
            self.assertGreater(
                workspace._roster_queue_btn.mapTo(workspace, QPoint(0, 0)).y(),
                workspace._roster_list.mapTo(workspace, QPoint(0, 0)).y(),
            )
            self.assertLess(
                workspace._roster_queue_btn.minimumWidth(),
                workspace._queue_inline_btn.sizeHint().width() + 20,
            )
            roster_panel_right = workspace._roster_panel.mapTo(workspace, QPoint(0, 0)).x() + workspace._roster_panel.width()
            queue_button_right = workspace._roster_queue_btn.mapTo(workspace, QPoint(0, 0)).x() + workspace._roster_queue_btn.width()
            self.assertLessEqual(queue_button_right, roster_panel_right)

            workspace.close()

    def test_movie_detail_action_buttons_do_not_squeeze_facts_column(self):
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
        workspace._splitter.setSizes([300, 540, 360])
        self._app.processEvents()

        panel = workspace._detail_panel
        summary_row = panel._body.layout().itemAt(3).layout()
        poster_column = summary_row.itemAt(0).layout()
        summary_body = summary_row.itemAt(1).layout()

        self.assertEqual(workspace._queue_inline_btn.text(), "Approve Match")
        self.assertGreater(panel.width(), 0)
        self.assertGreater(summary_body.geometry().width(), 100)
        self.assertLessEqual(poster_column.geometry().width(), panel._poster.width() + 1)
        self.assertGreaterEqual(panel._facts_card.width(), summary_body.geometry().width() - 1)
        for key_label, value_label in panel._meta_rows:
            if not key_label.text():
                continue
            self.assertTrue(value_label.text())

        workspace.close()

    def test_media_workspace_uses_inline_approve_action_for_review_items(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace, _RosterRowWidget

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

        row_widget = self._roster_widget_for_index(workspace, 0)
        self.assertIsInstance(row_widget, _RosterRowWidget)
        self.assertIsNone(row_widget._approve_btn)
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

        self.assertEqual(workspace._fix_match_btn.text(), "Choose Match")
        self.assertEqual(workspace._queue_inline_btn.text(), "Choose Match")

        workspace.close()

    def test_media_workspace_hides_single_season_badge_for_multi_season_preview(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace, _RosterRowWidget

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
                    original=Path("C:/library/tv/Example.Show.2024/Season 01/Example.Show.S01E01.mkv"),
                    new_name="Example Show (2024) - S01E01 - Pilot.mkv",
                    target_dir=Path("C:/library/tv/Example Show (2024)/Season 01"),
                    season=1,
                    episodes=[1],
                    status="OK",
                ),
                PreviewItem(
                    original=Path("C:/library/tv/Example.Show.2024/Season 02/Example.Show.S02E01.mkv"),
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

        row_widget = self._roster_widget_for_index(workspace, 0)
        self.assertIsInstance(row_widget, _RosterRowWidget)
        self.assertNotIn("Season 1", row_widget._meta.text())

        workspace.close()

    def test_media_workspace_season_one_badge_only_shows_when_show_has_multiple_seasons(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace, _RosterRowWidget

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
                    2: SeasonCompleteness(season=2, expected=1, matched=0, missing=[(1, "Second Season")]),
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

        single_widget = self._roster_widget_for_index(workspace, 0)
        multi_widget = self._roster_widget_for_index(workspace, 1)
        self.assertIsInstance(single_widget, _RosterRowWidget)
        self.assertIsInstance(multi_widget, _RosterRowWidget)
        self.assertNotIn("Season 1", single_widget._meta.text())
        self.assertIn("Season 1", multi_widget._meta.text())

        workspace.close()

    def test_media_workspace_roster_check_syncs_tv_episode_guide_without_file_checks(self):
        from plex_renamer.gui_qt.widgets._workspace_widgets import EpisodeGuideRowWidget
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
                    original=Path("C:/library/tv/Example.Show.2024/Season 01/Example.Show.S01E01.mkv"),
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

        roster_item = workspace._find_roster_item_by_index(0)
        workspace._set_item_check_state(roster_item, True, preview=False)

        self.assertTrue(state.checked)
        self.assertTrue(state.check_vars["0"].get())
        preview_widget = self._preview_widget_for_index(workspace, 0)
        self.assertIsInstance(preview_widget, EpisodeGuideRowWidget)
        self.assertTrue(preview_widget._check.isHidden())

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
            media_info={"id": 101, "title": "Example Movie", "year": "2024", "_media_type": "movie"},
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
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace, _RosterRowWidget

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

        row_widget = self._roster_widget_for_index(workspace, 0)
        self.assertIsInstance(row_widget, _RosterRowWidget)
        self.assertIsNone(row_widget._season_btn)
        self.assertIsNone(row_widget._alternates_widget)
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
        with patch("plex_renamer.gui_qt.widgets.media_workspace.QInputDialog.getInt", return_value=(2, True)):
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
            def add_tv_batch(self, states, root, output_root, gating):
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
                    original=Path("C:/library/tv/Matched.Show.2024/Season 01/Matched.Show.S01E01.mkv"),
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
                    original=Path("C:/library/tv/Unchecked.Show.2024/Season 01/Unchecked.Show.S01E01.mkv"),
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
        from plex_renamer.gui_qt.widgets._workspace_widgets import EpisodeGuideRowWidget
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
                        original=Path("C:/library/tv/Duplicate.Show.2024/Season 01/Duplicate.Show.S01E01.mkv"),
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
                    original=Path("C:/library/tv/Duplicate.Show.2024/Season 01/Duplicate.Show.S01E01.mkv"),
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

        before_widget = self._preview_widget_for_index(workspace, 0)
        self.assertIsInstance(before_widget, EpisodeGuideRowWidget)
        self.assertIn("Original Show (2024)", before_widget._target.text())

        chosen = {"id": 202, "name": "Replacement Show", "year": "2024"}
        with patch("plex_renamer.gui_qt.widgets.media_workspace.MatchPickerDialog.pick", return_value=chosen):
            workspace._fix_match()

        after_widget = self._preview_widget_for_index(workspace, 0)
        self.assertIsInstance(after_widget, EpisodeGuideRowWidget)
        self.assertIn("Replacement Show (2024)", after_widget._target.text())
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
            media_info={"id": 101, "title": "Example Movie", "year": "2024", "_media_type": "movie"},
            preview_items=[],
            scanned=True,
            checked=False,
            confidence=0.42,
            duplicate_of="Primary Movie (2024)",
        )
        media_ctrl = _FakeMediaController(state)
        workspace = MediaWorkspace(media_type="movie", media_controller=media_ctrl)
        workspace.show_ready()

        row_widget = self._roster_widget_for_index(workspace, 0)
        self.assertIsNotNone(row_widget)
        self.assertIsNone(row_widget._approve_btn)

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

        self.assertTrue(any("SPECIALS" in text for text in self._preview_header_texts(workspace)))

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
            queue_controller=type("Q", (), {"add_tv_batch": lambda *args, **kwargs: BatchQueueResult(added=2)})(),
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

            def add_movie_batch(self, states, root, output_root, command_gating):
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
                        original=Path("C:/library/movies/Dune.Part.Two.2024/Dune.Part.Two.2024.mkv"),
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

            self.assertEqual(workspace._roster_list.count(), 3)
            self._assert_roster_section_title(workspace, 0, "MATCHED")
            self.assertIsNone(workspace._roster_list.item(1).data(Qt.ItemDataRole.CheckStateRole))
            self.assertIsNone(workspace._preview_list.item(0).data(Qt.ItemDataRole.CheckStateRole))
            self.assertIn("Folder rename plan:", workspace._folder_plan_label.text())
            self.assertIn("2024", workspace._folder_plan_label.text())
            self.assertGreater(workspace._preview_list.count(), 0)

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
                queue_controller=type("Q", (), {"add_movie_batch": lambda *args, **kwargs: BatchQueueResult(added=1)})(),
                settings_service=settings,
            )
            workspace.show_ready()

            self.assertEqual(workspace._roster_list.count(), 4)
            self._assert_roster_section_title(workspace, 0, "MATCHED")
            self._assert_roster_section_title(workspace, 2, "DUPLICATES")
            self.assertIsNotNone(self._roster_widget_for_index(workspace, 0))
            self.assertIsNotNone(self._roster_widget_for_index(workspace, 1))

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
                queue_controller=type("Q", (), {"add_movie_batch": lambda *args, **kwargs: BatchQueueResult(added=1)})(),
                settings_service=settings,
            )
            workspace.show_ready()

            preview_widget = self._preview_widget_for_index(workspace, 0)
            self.assertIsNotNone(preview_widget)
            self.assertEqual(preview_widget._target.text(), "-> Arrival (2016).mkv")

            settings.view_mode = "compact"
            settings.show_companion_files = True
            workspace.apply_settings()

            preview_widget = self._preview_widget_for_index(workspace, 0)
            self.assertIsNotNone(preview_widget)
            self.assertEqual(preview_widget._target.text(), "-> Arrival (2016).mkv")
            self.assertIsNotNone(preview_widget._companions)
            self.assertIn("Arrival.2016.en.srt", preview_widget._companions.text())
            self.assertEqual(workspace._roster_list.iconSize().width(), 32)

            workspace.close()

    def test_media_workspace_tv_episode_guide_groups_companions_and_missing_rows(self):
        from plex_renamer.gui_qt.widgets._workspace_widgets import EpisodeGuideRowWidget
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

        self.assertTrue(workspace._preview_master_check.isHidden())
        self.assertTrue(workspace._preview_check_summary.isHidden())
        self.assertTrue(workspace._preview_summary.isHidden())
        self.assertIn("Queue preflight:", workspace._queue_preflight_label.text())
        self.assertIn("1 mapped file", workspace._queue_preflight_label.text())
        self.assertIn("1 companion", workspace._queue_preflight_label.text())
        headers = self._preview_header_texts(workspace)
        self.assertFalse(any("EPISODE GUIDE:" in header for header in headers))
        self.assertTrue(any(header.startswith("▾ SEASON 1") for header in headers))
        self.assertTrue(any(header.startswith("▸ SEASON 2") for header in headers))

        mapped_widget = self._preview_widget_for_index(workspace, 0)
        self.assertIsInstance(mapped_widget, EpisodeGuideRowWidget)
        self.assertTrue(mapped_widget._check.isHidden())
        self.assertEqual(mapped_widget._status.text(), "Mapped")
        self.assertIn("Example.S01E01.en.srt", mapped_widget._companions.text())
        self.assertEqual(mapped_widget._confidence_label.text(), "Confidence")
        self.assertEqual(mapped_widget._confidence._value, 100)

        missing_statuses = []
        missing_titles = []
        for row in range(workspace._preview_list.count()):
            item = workspace._preview_list.item(row)
            if item.isHidden():
                continue
            widget = workspace._preview_list.itemWidget(item)
            if isinstance(widget, EpisodeGuideRowWidget):
                missing_statuses.append(widget._status.text())
                missing_titles.append(widget._title.text())
        self.assertIn("Missing File", missing_statuses)
        self.assertNotIn("S02E01 - A Missing Start", missing_titles)

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

        headers = self._preview_header_texts(workspace)

        self.assertTrue(any(header.startswith("▾ SEASON 1") for header in headers))
        self.assertTrue(any(header.startswith("▸ SEASON 2") for header in headers))
        self.assertFalse(any(header.startswith(("V ", "> ")) for header in headers))

        workspace.close()

    def test_media_workspace_episode_guide_reuses_projection_when_toggling_headers(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace
        from plex_renamer.gui_qt.widgets._media_workspace_preview import _PREVIEW_ENTRY_KIND_ROLE

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
        original_builder = workspace._preview_panel._episode_mapping.build_episode_guide
        workspace._preview_panel._episode_mapping.build_episode_guide = MagicMock(wraps=original_builder)
        workspace._preview_panel._episode_guide_cache.clear()

        workspace._populate_preview(state)
        def _first_header():
            return next(
                workspace._preview_list.item(row)
                for row in range(workspace._preview_list.count())
                if workspace._preview_list.item(row).data(_PREVIEW_ENTRY_KIND_ROLE) == "header"
            )

        workspace._on_preview_item_clicked(_first_header())
        workspace._on_preview_item_clicked(_first_header())

        self.assertEqual(workspace._preview_panel._episode_mapping.build_episode_guide.call_count, 1)
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
        workspace._preview_panel._episode_mapping.build_episode_guide = MagicMock(
            side_effect=AssertionError("preview panel should not build TV guide on first render")
        )

        workspace.show_ready()

        media_ctrl.episode_guide_for_state.assert_called_with(state)
        workspace.close()

    def test_media_workspace_episode_header_toggle_hides_rows_without_rebuilding_preview(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace
        from plex_renamer.gui_qt.widgets._media_workspace_preview import (
            _PREVIEW_ENTRY_KIND_ROLE,
            _PREVIEW_SECTION_ROLE,
        )

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
        original_populate = workspace._state_coordinator.populate_preview
        workspace._state_coordinator.populate_preview = MagicMock(wraps=original_populate)
        header = next(
            workspace._preview_list.item(row)
            for row in range(workspace._preview_list.count())
            if (
                workspace._preview_list.item(row).data(_PREVIEW_ENTRY_KIND_ROLE) == "header"
                and str(workspace._preview_list.item(row).data(_PREVIEW_SECTION_ROLE)).startswith(
                    "episode-guide-season:"
                )
            )
        )
        first_episode = next(
            workspace._preview_list.item(row)
            for row in range(workspace._preview_list.count())
            if workspace._preview_list.item(row).data(_PREVIEW_ENTRY_KIND_ROLE) == "episode"
        )
        first_widget = workspace._preview_list.itemWidget(first_episode)

        workspace._on_preview_item_clicked(header)

        workspace._state_coordinator.populate_preview.assert_not_called()
        self.assertTrue(first_episode.isHidden())
        self.assertIs(workspace._preview_list.itemWidget(first_episode), first_widget)
        self.assertTrue(header.text().startswith("\u25b8 SEASON 1"))
        workspace.close()

    def test_media_workspace_folder_header_toggle_hides_rows_without_rebuilding_preview(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace
        from plex_renamer.gui_qt.widgets._media_workspace_preview import (
            _PREVIEW_ENTRY_KIND_ROLE,
            _PREVIEW_SECTION_ROLE,
        )

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
        original_populate = workspace._state_coordinator.populate_preview
        workspace._state_coordinator.populate_preview = MagicMock(wraps=original_populate)
        header = next(
            workspace._preview_list.item(row)
            for row in range(workspace._preview_list.count())
            if (
                workspace._preview_list.item(row).data(_PREVIEW_ENTRY_KIND_ROLE) == "header"
                and workspace._preview_list.item(row).data(_PREVIEW_SECTION_ROLE) == "folder"
            )
        )
        folder_row = next(
            workspace._preview_list.item(row)
            for row in range(workspace._preview_list.count())
            if workspace._preview_list.item(row).data(_PREVIEW_ENTRY_KIND_ROLE) == "folder"
        )
        folder_widget = workspace._preview_list.itemWidget(folder_row)

        workspace._on_preview_item_clicked(header)

        workspace._state_coordinator.populate_preview.assert_not_called()
        self.assertTrue(folder_row.isHidden())
        self.assertIs(workspace._preview_list.itemWidget(folder_row), folder_widget)
        self.assertTrue(header.text().startswith("\u25b8 FOLDER"))
        workspace.close()

    def test_media_workspace_auto_collapsed_specials_header_expands_without_rebuilding_preview(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace
        from plex_renamer.gui_qt.widgets._media_workspace_preview import (
            _PREVIEW_ENTRY_KIND_ROLE,
            _PREVIEW_SECTION_ROLE,
        )
        from plex_renamer.gui_qt.widgets._workspace_widgets import EpisodeGuideRowWidget

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
        original_populate = workspace._state_coordinator.populate_preview
        workspace._state_coordinator.populate_preview = MagicMock(wraps=original_populate)
        header = next(
            workspace._preview_list.item(row)
            for row in range(workspace._preview_list.count())
            if (
                workspace._preview_list.item(row).data(_PREVIEW_ENTRY_KIND_ROLE) == "header"
                and workspace._preview_list.item(row).data(_PREVIEW_SECTION_ROLE) == "episode-guide-season:0"
            )
        )
        special_row = next(
            workspace._preview_list.item(row)
            for row in range(workspace._preview_list.count())
            if (
                isinstance(workspace._preview_list.itemWidget(workspace._preview_list.item(row)), EpisodeGuideRowWidget)
                and workspace._preview_list.itemWidget(workspace._preview_list.item(row))._title.text().startswith("S00")
            )
        )
        self.assertTrue(special_row.isHidden())

        workspace._on_preview_item_clicked(header)

        workspace._state_coordinator.populate_preview.assert_not_called()
        self.assertFalse(special_row.isHidden())
        self.assertTrue(header.text().startswith("\u25be SPECIALS"))
        workspace.close()

    def test_media_workspace_reselecting_show_renders_preview_rows_on_demand(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace
        from plex_renamer.gui_qt.widgets._media_workspace_preview import _PREVIEW_ENTRY_KIND_ROLE

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

        def _first_visible_episode_widget(workspace):
            for row in range(workspace._preview_list.count()):
                item = workspace._preview_list.item(row)
                if item.isHidden() or item.data(_PREVIEW_ENTRY_KIND_ROLE) != "episode":
                    continue
                return workspace._preview_list.itemWidget(item)
            return None

        def _episode_widget_for_title(workspace, title: str):
            for row in range(workspace._preview_list.count()):
                item = workspace._preview_list.item(row)
                if item.data(_PREVIEW_ENTRY_KIND_ROLE) != "episode":
                    continue
                widget = workspace._preview_list.itemWidget(item)
                if widget is not None and title in widget._target.text():
                    return item, widget
            return None, None

        first_state = _state("First Show", 101)
        second_state = _state("Second Show", 202)
        workspace = MediaWorkspace(
            media_type="tv",
            media_controller=_FakeMediaController([first_state, second_state]),
        )
        workspace.show_ready()
        first_widget = _first_visible_episode_widget(workspace)
        self.assertIsNotNone(first_widget)
        second_cached_item, second_cached_widget = _episode_widget_for_title(workspace, "Second Show")
        self.assertIsNone(second_cached_item)
        self.assertIsNone(second_cached_widget)

        second_item = workspace._find_roster_item_by_index(1)
        self.assertIsNotNone(second_item)
        workspace._roster_list.setCurrentItem(second_item)
        self._app.processEvents()
        second_widget = _first_visible_episode_widget(workspace)
        self.assertIsNotNone(second_widget)
        self.assertIsNot(second_widget, first_widget)
        second_header = next(
            workspace._preview_list.item(row)
            for row in range(workspace._preview_list.count())
            if (
                not workspace._preview_list.item(row).isHidden()
                and workspace._preview_list.item(row).data(_PREVIEW_ENTRY_KIND_ROLE) == "header"
                and "SEASON 1" in workspace._preview_list.item(row).text()
            )
        )
        second_episode = next(
            workspace._preview_list.item(row)
            for row in range(workspace._preview_list.count())
            if (
                not workspace._preview_list.item(row).isHidden()
                and workspace._preview_list.item(row).data(_PREVIEW_ENTRY_KIND_ROLE) == "episode"
            )
        )

        workspace._on_preview_item_clicked(second_header)

        self.assertTrue(second_episode.isHidden())
        self.assertTrue(second_header.text().startswith("\u25b8 SEASON 1"))

        first_item = workspace._find_roster_item_by_index(0)
        self.assertIsNotNone(first_item)
        workspace._roster_list.setCurrentItem(first_item)
        self._app.processEvents()

        self.assertIs(_first_visible_episode_widget(workspace), first_widget)
        workspace.close()

    def test_media_workspace_episode_approval_emits_approve_action(self):
        from plex_renamer.engine._episode_projection import project_preview_items
        from plex_renamer.engine.episode_assignments import (
            ORIGIN_AUTO,
            EpisodeAssignmentTable,
            EpisodeSlot,
        )
        from plex_renamer.gui_qt.widgets._workspace_widgets import EpisodeGuideRowWidget
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
            entry.file_id, 1, [1],
            origin=ORIGIN_AUTO, confidence=0.5,
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

        # Find the review-status episode guide row widget.
        widget = next(
            workspace._preview_list.itemWidget(workspace._preview_list.item(row))
            for row in range(workspace._preview_list.count())
            if isinstance(
                workspace._preview_list.itemWidget(workspace._preview_list.item(row)),
                EpisodeGuideRowWidget,
            )
        )
        self.assertEqual(widget._status.text(), "Review")

        # Clicking approve dispatches through handle_episode_row_action → service.approve_file.
        widget._approve_button.click()
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

    def test_episode_row_action_keep_this_resolves_conflict(self):
        """keep_this: dialog-free; winner keeps the slot, loser is unassigned."""
        from plex_renamer.engine._episode_projection import project_preview_items
        from plex_renamer.engine.episode_assignments import (
            ORIGIN_AUTO,
            EpisodeAssignmentTable,
            EpisodeSlot,
        )
        from plex_renamer.app.models.state_models import EpisodeGuideRow
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
            state, row, "reassign", assign_dialog=_StubAssignDialog,
        )
        self._app.processEvents()

        # File should now be assigned to episode 2 (not episode 1).
        assignment = table._assignments.get(file_id)
        self.assertIsNotNone(assignment)
        self.assertEqual(assignment.episodes, (2,))
        workspace.close()

    def test_approve_all_recategorizes_and_auto_checks_show(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace
        from plex_renamer.gui_qt.widgets._media_helpers import (
            is_state_queue_approvable,
        )

        # _make_episode_table_state assigns the only file at confidence 0.5,
        # so the show starts under "Review Episode Matching".
        state, _table, _file_id = self._make_episode_table_state()
        workspace = MediaWorkspace(
            media_type="tv",
            media_controller=self._make_fake_media_ctrl(state),
        )
        workspace.show_ready()

        self._assert_roster_section_title(workspace, 0, "REVIEW EPISODE MATCHING")
        self.assertFalse(is_state_queue_approvable(state, media_type="tv"))

        workspace._approve_all_episode_mappings()
        self._app.processEvents()

        # The roster widget re-syncs out of review and the show is auto-checked.
        self._assert_roster_section_title(workspace, 0, "MATCHED")
        self.assertTrue(is_state_queue_approvable(state, media_type="tv"))
        self.assertTrue(state.checked)

        workspace.close()

    def test_approve_all_with_remaining_conflict_stays_in_review_no_checkbox(self):
        from plex_renamer.engine._episode_projection import project_preview_items
        from plex_renamer.engine.episode_assignments import (
            ORIGIN_AUTO,
            EpisodeAssignmentTable,
            EpisodeSlot,
        )
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace
        from plex_renamer.gui_qt.widgets._media_helpers import is_state_queue_approvable

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
            table, show_info=show_info, root=folder,
            media_fields={"media_id": 77, "media_name": "Conflicted"},
        )

        workspace = MediaWorkspace(
            media_type="tv",
            media_controller=self._make_fake_media_ctrl(state),
        )
        workspace.show_ready()
        self._assert_roster_section_title(workspace, 0, "REVIEW EPISODE MATCHING")

        workspace._approve_all_episode_mappings()
        self._app.processEvents()

        # Conflict remains: the show stays in review with no checkbox / unchecked,
        # so the checkbox stays consistent with the section header.
        self._assert_roster_section_title(workspace, 0, "REVIEW EPISODE MATCHING")
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
            state, row, "reassign", assign_dialog=_CapturingDialog,
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
            state, row, "assign_to_more", assign_dialog=_CapturingDialog,
        )

        self.assertEqual(set(captured.get("preselected") or set()), {(1, 1)})
        self.assertEqual(set(captured.get("current_keys") or set()), {(1, 1)})
        slot_keys = {(c.season, c.episode) for c in captured.get("slots", [])}
        self.assertIn((1, 1), slot_keys)
        self.assertIn((1, 2), slot_keys)
        workspace.close()

    def test_episode_row_action_assign_file_calls_dialog_and_assigns_slot(self):
        """assign_file: stub assign_dialog.pick_file returns a file_id; assignment lands."""
        from plex_renamer.engine._episode_projection import project_preview_items
        from plex_renamer.engine.episode_assignments import (
            ORIGIN_AUTO,
            EpisodeAssignmentTable,
            EpisodeSlot,
        )
        from plex_renamer.app.models.state_models import EpisodeGuideRow
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
            state, row, "assign_file", assign_dialog=_StubAssignDialog,
        )
        self._app.processEvents()

        assignment = table._assignments.get(loose_entry.file_id)
        self.assertIsNotNone(assignment)
        self.assertEqual(assignment.season, 1)
        self.assertEqual(assignment.episodes, (2,))
        workspace.close()

    def test_assign_file_dialog_does_not_double_list_unmatched_extras(self):
        """UNMATCHED extras rows must appear only in 'unassigned', not also in 'assigned'."""
        from plex_renamer.engine._episode_projection import project_preview_items
        from plex_renamer.engine.episode_assignments import (
            ORIGIN_AUTO,
            EpisodeAssignmentTable,
            EpisodeSlot,
        )
        from plex_renamer.app.models.state_models import EpisodeGuideRow
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        folder = Path("C:/library/tv/Example")
        show_info = {"id": 101, "name": "Example Show", "year": "2024"}
        table = EpisodeAssignmentTable()
        table.add_slot(EpisodeSlot(season=1, episode=1, title="Pilot"))
        # Assigned file (appears in assigned list).
        e01_entry = table.add_file(folder / "Season 01" / "A.S01E01.mkv")
        table.assign(e01_entry.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=0.9)
        # Unmatched extras file: has new_name set by projection but no table assignment.
        from plex_renamer.engine.episode_assignments import EpisodeSlot as _Slot, REASON_NO_TITLE_MATCH
        extras_entry = table.add_file(
            folder / "Season 01" / "Extras" / "bts.mkv",
            folder_season=0, from_extras_folder=True,
        )
        table.mark_unassigned(extras_entry.file_id, REASON_NO_TITLE_MATCH)

        state = ScanState(folder=folder, media_info=show_info, scanned=True, confidence=1.0)
        state.assignments = table
        state.preview_items = project_preview_items(
            table, show_info=show_info, root=folder,
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
            state, row, "assign_file", assign_dialog=_CapturingDialog,
        )

        # extras_entry must appear in unassigned only, not in assigned.
        unassigned_ids = {fid for fid, _label in captured_unassigned}
        assigned_ids = {fid for fid, _name in captured_assigned}
        self.assertIn(extras_entry.file_id, unassigned_ids)
        self.assertNotIn(
            extras_entry.file_id, assigned_ids,
            "UNMATCHED extras file must not appear in the 'Already assigned' list",
        )
        workspace.close()

    def test_episode_row_action_error_calls_warning_box_no_crash(self):
        """If the service raises ValueError, warning_box.warning is called; no hang."""
        from plex_renamer.app.models.state_models import EpisodeGuideRow
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        state, table, file_id = self._make_episode_table_state()
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
            state, row, "approve", warning_box=_RecordingWarningBox,
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

    def test_media_workspace_episode_guide_items_preserve_card_gap(self):
        from plex_renamer.gui_qt.widgets._workspace_widgets import EpisodeGuideRowWidget
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
                for episode in range(1, 3)
            ],
            scanned=True,
            confidence=1.0,
        )
        workspace = MediaWorkspace(media_type="tv", media_controller=_FakeMediaController(state))
        workspace.show_ready()
        for row in range(workspace._preview_list.count()):
            item = workspace._preview_list.item(row)
            widget = workspace._preview_list.itemWidget(item)
            if isinstance(widget, EpisodeGuideRowWidget):
                self.assertGreaterEqual(
                    item.sizeHint().height(),
                    widget.sizeHint().height() + 6,
                )
                break
        else:
            self.fail("No episode guide row widget found")
        workspace.close()

    def test_media_workspace_episode_header_toggle_does_not_reload_detail_selection(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace
        from plex_renamer.gui_qt.widgets._media_workspace_preview import _PREVIEW_ENTRY_KIND_ROLE

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
        workspace._detail_panel.set_selection = MagicMock(wraps=workspace._detail_panel.set_selection)
        header = next(
            workspace._preview_list.item(row)
            for row in range(workspace._preview_list.count())
            if workspace._preview_list.item(row).data(_PREVIEW_ENTRY_KIND_ROLE) == "header"
        )

        workspace._on_preview_item_clicked(header)

        workspace._detail_panel.set_selection.assert_not_called()
        workspace.close()

    def test_media_workspace_selected_review_episode_uses_card_actions(self):
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

        review_item = PreviewItem(
            original=Path("C:/library/tv/Example/Season 01/Example.S01E01.mkv"),
            new_name="Example Show (2024) - S01E01 - Pilot.mkv",
            target_dir=Path("C:/library/tv/Example Show (2024)/Season 01"),
            season=1,
            episodes=[1],
            status="REVIEW: episode confidence below threshold",
            episode_confidence=0.5,
        )
        state = ScanState(
            folder=Path("C:/library/tv/Example"),
            media_info={"id": 101, "name": "Example Show", "year": "2024"},
            preview_items=[review_item],
            scanned=True,
            checked=False,
            confidence=1.0,
        )
        workspace = MediaWorkspace(media_type="tv", media_controller=_FakeMediaController(state))
        workspace.show()
        workspace.show_ready()
        self._app.processEvents()

        item = next(
            workspace._preview_list.item(row)
            for row in range(workspace._preview_list.count())
            if workspace._preview_list.item(row).data(Qt.ItemDataRole.UserRole) == 0
        )
        workspace._preview_list.setCurrentItem(item)
        self._app.processEvents()

        widget = workspace._preview_list.itemWidget(item)
        self.assertEqual(workspace._queue_inline_btn.text(), "Queue This Show")
        self.assertNotEqual(workspace._queue_inline_btn.text(), "Approve Episode")
        # New API: approve button visible for Review rows; ⋯ menu for reassign/unassign.
        self.assertTrue(hasattr(widget, "_approve_button"))
        self.assertTrue(widget._approve_button.isVisible())
        self.assertIsNotNone(widget.actions_button())
        menu_labels = [a.text() for a in widget.actions_menu().actions()]
        self.assertIn("Reassign...", menu_labels)
        self.assertIn("Unassign", menu_labels)

        workspace.close()

    def test_media_workspace_review_episode_fix_button_replaced_by_actions_menu(self):
        # TODO(Task 12): restore end-to-end reassign assertions once dispatch is wired.
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

        review_item = PreviewItem(
            original=Path("C:/library/tv/Example/Season 01/Example.S01E01.mkv"),
            new_name="Example Show (2024) - S01E01 - Pilot.mkv",
            target_dir=Path("C:/library/tv/Example Show (2024)/Season 01"),
            season=1,
            episodes=[1],
            status="REVIEW: episode confidence below threshold",
            episode_confidence=0.5,
        )
        state = ScanState(
            folder=Path("C:/library/tv/Example"),
            media_info={"id": 101, "name": "Example Show", "year": "2024"},
            scanner=type(
                "Scanner",
                (),
                {"episode_meta": {(1, 1): {"name": "Pilot"}, (1, 2): {"name": "Second"}}},
            )(),
            preview_items=[review_item],
            scanned=True,
            checked=False,
            confidence=1.0,
        )
        workspace = MediaWorkspace(media_type="tv", media_controller=_FakeMediaController(state))
        workspace.show()
        workspace.show_ready()
        self._app.processEvents()

        item = next(
            workspace._preview_list.item(row)
            for row in range(workspace._preview_list.count())
            if workspace._preview_list.item(row).data(Qt.ItemDataRole.UserRole) == 0
        )
        widget = workspace._preview_list.itemWidget(item)

        # New API: Fix button removed; reassign is now a menu action via the ⋯ tool button.
        self.assertFalse(hasattr(widget, "_fix_button"))
        self.assertIsNotNone(widget.actions_button())
        menu_labels = [a.text() for a in widget.actions_menu().actions()]
        self.assertIn("Reassign...", menu_labels)

        workspace.close()

    def test_media_workspace_approve_all_review_episodes_is_inline_with_filters(self):
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

        first = PreviewItem(
            original=Path("C:/library/tv/Example/Season 01/Example.S01E01.mkv"),
            new_name="Example Show (2024) - S01E01 - Pilot.mkv",
            target_dir=Path("C:/library/tv/Example Show (2024)/Season 01"),
            season=1,
            episodes=[1],
            status="REVIEW: episode confidence below threshold",
            episode_confidence=0.5,
        )
        second = PreviewItem(
            original=Path("C:/library/tv/Example/Season 01/Example.S01E02.mkv"),
            new_name="Example Show (2024) - S01E02 - Second.mkv",
            target_dir=Path("C:/library/tv/Example Show (2024)/Season 01"),
            season=1,
            episodes=[2],
            status="REVIEW: episode confidence below threshold",
            episode_confidence=0.52,
        )
        state = ScanState(
            folder=Path("C:/library/tv/Example"),
            media_info={"id": 101, "name": "Example Show", "year": "2024"},
            preview_items=[first, second],
            scanned=True,
            checked=False,
            confidence=1.0,
        )
        workspace = MediaWorkspace(media_type="tv", media_controller=_FakeMediaController(state))
        workspace.show()
        workspace.show_ready()
        self._app.processEvents()

        approve_all = workspace._preview_panel._approve_all_button

        self.assertTrue(approve_all.isVisible())
        self.assertEqual(approve_all.text(), "Approve All")
        self.assertEqual(approve_all.property("cssClass"), "primary")
        self.assertEqual(
            approve_all.parent(),
            workspace._preview_panel._episode_filter_buttons["unmapped"].parent(),
        )

        approve_all.click()
        self._app.processEvents()

        self.assertEqual([item.status for item in state.preview_items], ["OK", "OK"])
        self.assertFalse(approve_all.isVisible())
        self.assertTrue(workspace._queue_inline_btn.isEnabled())

        workspace.close()

    def test_media_workspace_episode_guide_rows_size_to_visible_actions(self):
        from plex_renamer.gui_qt.widgets._workspace_widgets import EpisodeGuideRowWidget

        # Production-realistic action lists per _episode_row_actions policy.
        short_row = EpisodeGuideRowWidget(
            title="S01E01 - Pilot",
            status="Mapped",
            original="Pilot.mkv",
            actions=[("reassign", "Reassign..."), ("unassign", "Unassign")],
        )
        missing_row = EpisodeGuideRowWidget(
            title="S01E02 - Missing",
            status="Missing File",
            actions=[("assign_file", "Assign file...")],
        )
        long_row = EpisodeGuideRowWidget(
            title="S01E03 - This Is A Very Long Episode Title That Should Not Expand The Row Horizontally",
            status="Review",
            original="Example.Show.S01E03.With.A.Long.Release.Name.mkv",
            target="Example Show (2024) - S01E03 - This Is A Very Long Episode Title That Should Not Expand The Row Horizontally.mkv",
            confidence="52%",
            actions=[("approve", "Approve"), ("reassign", "Reassign..."), ("unassign", "Unassign")],
        )

        # All three rows take the taller (actions) path; long_row is taller still due
        # to the visible confidence meter and target label.
        self.assertEqual(short_row.sizeHint().height(), missing_row.sizeHint().height())
        self.assertLess(short_row.sizeHint().height(), long_row.sizeHint().height())
        self.assertLessEqual(short_row.sizeHint().height(), 96)
        self.assertLessEqual(long_row.sizeHint().height(), 120)

        short_row.close()
        missing_row.close()
        long_row.close()

    def test_media_workspace_episode_review_actions_are_inline_with_confidence_meter(self):
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

        review_item = PreviewItem(
            original=Path("C:/library/tv/Example/Season 01/Example.S01E01.mkv"),
            new_name="Example Show (2024) - S01E01 - Pilot.mkv",
            target_dir=Path("C:/library/tv/Example Show (2024)/Season 01"),
            season=1,
            episodes=[1],
            status="REVIEW: episode confidence below threshold",
            episode_confidence=0.5,
        )
        state = ScanState(
            folder=Path("C:/library/tv/Example"),
            media_info={"id": 101, "name": "Example Show", "year": "2024"},
            preview_items=[review_item],
            scanned=True,
            checked=False,
            confidence=1.0,
        )
        workspace = MediaWorkspace(media_type="tv", media_controller=_FakeMediaController(state))
        workspace.show()
        workspace.show_ready()
        self._app.processEvents()

        widget = self._preview_widget_for_index(workspace, 0)
        before_height = widget.sizeHint().height()

        self.assertEqual(widget._approve_button.property("sizeVariant"), "inline")
        self.assertLessEqual(widget._approve_button.sizeHint().height(), 24)
        self.assertIsNotNone(widget.actions_button())
        self.assertGreater(
            widget._approve_button.mapTo(widget, QPoint(0, 0)).x(),
            widget._confidence.mapTo(widget, QPoint(0, 0)).x(),
        )
        approve_center = (
            widget._approve_button.mapTo(widget, QPoint(0, 0)).y()
            + widget._approve_button.height() // 2
        )
        confidence_center = (
            widget._confidence.mapTo(widget, QPoint(0, 0)).y()
            + widget._confidence.height() // 2
        )
        self.assertLessEqual(abs(approve_center - confidence_center), 4)
        self.assertLessEqual(widget.sizeHint().height(), before_height)

        workspace.close()

    def test_episode_guide_review_action_buttons_are_parented_during_construction(self):
        import plex_renamer.gui_qt.widgets._workspace_widgets as workspace_widgets

        row = workspace_widgets.EpisodeGuideRowWidget(
            title="S01E01 - Pilot",
            status="Review",
            confidence="50%",
            actions=[("approve", "Approve"), ("reassign", "Reassign..."), ("unassign", "Unassign")],
        )

        try:
            # Approve button is present, parented, and not a top-level window.
            self.assertFalse(row._approve_button.isWindow())
            self.assertIsNotNone(row.actions_button())
            self.assertFalse(row.actions_button().isWindow())
            # ⋯ menu carries the non-approve actions.
            labels = [a.text() for a in row.actions_menu().actions()]
            self.assertEqual(labels, ["Reassign...", "Unassign"])
        finally:
            row.close()

    def test_media_workspace_tv_episode_guide_filters_problems_and_unmapped(self):
        from plex_renamer.gui_qt.widgets._workspace_widgets import EpisodeGuideRowWidget
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
                PreviewItem(
                    original=Path("C:/library/tv/Example/Extra.mkv"),
                    new_name=None,
                    target_dir=None,
                    season=None,
                    episodes=[],
                    status="SKIP: no episode mapping",
                ),
            ],
            completeness=CompletenessReport(
                seasons={1: SeasonCompleteness(season=1, expected=2, matched=1, missing=[(2, "Second")])},
                specials=None,
                total_expected=2,
                total_matched=1,
                total_missing=[(1, 2, "Second")],
            ),
            scanned=True,
            checked=False,
            confidence=1.0,
        )

        workspace = MediaWorkspace(media_type="tv", media_controller=_FakeMediaController(state))
        workspace.show_ready()

        # In the default "all" filter, UNMAPPED PRIMARY FILES must appear BEFORE season rows.
        all_headers = self._preview_header_texts(workspace)
        unmapped_indices = [i for i, h in enumerate(all_headers) if "UNMAPPED PRIMARY FILES" in h]
        season_indices = [i for i, h in enumerate(all_headers) if "SEASON 1" in h]
        self.assertTrue(unmapped_indices, "Expected an UNMAPPED PRIMARY FILES header")
        self.assertTrue(season_indices, "Expected a SEASON 1 header")
        self.assertLess(
            unmapped_indices[0],
            season_indices[0],
            "UNMAPPED PRIMARY FILES header must appear before SEASON 1 header",
        )

        workspace._preview_panel._episode_filter_buttons["problems"].click()
        statuses = [
            widget._status.text()
            for row in range(workspace._preview_list.count())
            if isinstance((widget := workspace._preview_list.itemWidget(workspace._preview_list.item(row))), EpisodeGuideRowWidget)
        ]
        self.assertNotIn("Mapped", statuses)
        self.assertIn("Missing File", statuses)
        self.assertTrue(any("UNMAPPED PRIMARY FILES" in header for header in self._preview_header_texts(workspace)))

        workspace._preview_panel._episode_filter_buttons["unmapped"].click()
        headers = self._preview_header_texts(workspace)
        self.assertFalse(any("SEASON 1" in header for header in headers))
        self.assertTrue(any("UNMAPPED PRIMARY FILES" in header for header in headers))

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

        headers = self._preview_header_texts(workspace)
        self.assertTrue(any("UNMAPPED PRIMARY FILES" in header for header in headers))
        self.assertTrue(any("ORPHAN COMPANION FILES" in header for header in headers))
        self.assertTrue(workspace._preview_summary.isHidden())

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
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace, _RosterRowWidget

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
                        original=Path("C:/library/movies/Crash.Collectors.Edition/Crash.Collectors.Edition.mkv"),
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
                queue_controller=type("Q", (), {"add_movie_batch": lambda *args, **kwargs: BatchQueueResult(added=1)})(),
                settings_service=settings,
            )
            workspace.show_ready()

            row_widget = workspace._roster_list.itemWidget(workspace._roster_list.item(1))
            self.assertIsInstance(row_widget, _RosterRowWidget)
            self.assertIsNone(row_widget._alternates_layout)
            self.assertIsNone(row_widget._alternates_widget)
            self.assertTrue(workspace._fix_match_btn.isEnabled())
            self.assertFalse(row_widget._check.isWindow())
            self.assertEqual(row_widget.styleSheet(), "")
            self.assertEqual(row_widget.property("band"), "low")
            self.assertEqual(row_widget.property("selectionState"), "selected")
            self.assertTrue(row_widget._status.isHidden())

            workspace.close()

    def test_media_workspace_sorts_tv_preview_items_by_episode_number(self):
        from plex_renamer.gui_qt.widgets._workspace_widgets import EpisodeGuideRowWidget
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
                        original=Path("C:/library/tv/Example Show/Season 01/Example.Show.S01E03.mkv"),
                        new_name="Example Show (2024) - S01E03 - Episode 3.mkv",
                        target_dir=Path("C:/library/tv/Example Show/Season 01"),
                        season=1,
                        episodes=[3],
                        status="OK",
                    ),
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
                queue_controller=type("Q", (), {"add_tv_batch": lambda *args, **kwargs: BatchQueueResult(added=1)})(),
                settings_service=settings,
            )
            workspace.show_ready()

            preview_indices = []
            for row in range(workspace._preview_list.count()):
                item = workspace._preview_list.item(row)
                index = item.data(Qt.ItemDataRole.UserRole)
                if index is not None:
                    preview_indices.append(index)

            self.assertEqual(preview_indices, [1, 2, 0])

            preview_row_widget = None
            for row in range(workspace._preview_list.count()):
                item = workspace._preview_list.item(row)
                widget = workspace._preview_list.itemWidget(item)
                if isinstance(widget, EpisodeGuideRowWidget):
                    preview_row_widget = widget
                    break

            self.assertIsNotNone(preview_row_widget)
            self.assertFalse(preview_row_widget._check.isWindow())
            self.assertEqual(preview_row_widget.styleSheet(), "")
            self.assertEqual(preview_row_widget.property("band"), "success")
            self.assertEqual(preview_row_widget.property("selectionState"), "selected")
            self.assertEqual(preview_row_widget._status.styleSheet(), "")
            self.assertEqual(preview_row_widget._status.property("tone"), "success")

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

        self.assertTrue(any("SEASON 1 - 1/2" in text for text in self._preview_header_texts(workspace)))

        workspace.close()

    def test_media_workspace_keeps_folder_rename_states_out_of_plex_ready(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace, _RosterRowWidget

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
                        original=Path("C:/library/tv/Example.Show.2024.Source/Season 01/Example Show (2024) - S01E01 - Pilot.mkv"),
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
                queue_controller=type("Q", (), {"add_tv_batch": lambda *args, **kwargs: BatchQueueResult(added=1)})(),
                settings_service=settings,
            )
            workspace.show_ready()

            self._assert_roster_section_title(workspace, 0, "MATCHED")
            row_widget = workspace._roster_list.itemWidget(workspace._roster_list.item(1))
            self.assertIsInstance(row_widget, _RosterRowWidget)
            self.assertTrue(row_widget._status.isHidden())

            workspace.close()

    def test_tv_workspace_blocks_review_duplicate_and_plex_ready_from_queue_selection(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace, _RosterRowWidget

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

        def _episode(path_root: str, season: int, episode: int, *, status: str = "OK", new_name: str | None = None, target_dir: Path | None = None):
            original = Path(f"{path_root}/Season 01/Example.Show.S01E0{episode}.mkv")
            return PreviewItem(
                original=original,
                new_name=new_name if new_name is not None else f"Example Show (2024) - S01E0{episode} - Pilot.mkv",
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
                        original=Path("C:/library/tv/Matched.Show.2024/Season 01/Matched.Show.S01E01.mkv"),
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
                        original=Path("C:/library/tv/Review.Show.2024/Season 01/Review.Show.S01E01.mkv"),
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
                        original=Path("C:/library/tv/Duplicate.Show.2024/Season 01/Duplicate.Show.S01E01.mkv"),
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
                        original=Path(f"{plex_ready_root}/Season 01/Plex Ready Show (2024) - S01E01 - Pilot.mkv"),
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
            media_ctrl.batch_states = [matched_state, review_state, duplicate_state, plex_ready_state]

            workspace = MediaWorkspace(
                media_type="tv",
                media_controller=media_ctrl,
                queue_controller=type("Q", (), {"add_tv_batch": lambda *args, **kwargs: BatchQueueResult(added=1)})(),
                settings_service=settings,
            )
            workspace.show_ready()
            workspace._roster_collapsed["plex-ready"] = False
            workspace.refresh_from_controller()

            matched_widget = self._roster_widget_for_index(workspace, 0)
            review_widget = self._roster_widget_for_index(workspace, 1)
            duplicate_widget = self._roster_widget_for_index(workspace, 2)
            plex_ready_widget = self._roster_widget_for_index(workspace, 3)

            self.assertIsInstance(matched_widget, _RosterRowWidget)
            self.assertFalse(matched_widget._check.isHidden())
            self.assertTrue(matched_state.checked)

            self.assertIsInstance(review_widget, _RosterRowWidget)
            self.assertFalse(review_state.checked)
            self.assertTrue(review_widget._check.isHidden())

            self.assertIsInstance(duplicate_widget, _RosterRowWidget)
            self.assertFalse(duplicate_state.checked)
            self.assertTrue(duplicate_widget._check.isHidden())

            self.assertIsInstance(plex_ready_widget, _RosterRowWidget)
            self.assertFalse(plex_ready_state.checked)
            self.assertTrue(plex_ready_widget._check.isHidden())

            workspace.close()

    def test_tv_workspace_episode_review_state_groups_under_review_and_keeps_row_alignment(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace, _RosterRowWidget

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
                    original=Path("C:/library/tv/Matched.Show.2024/Season 01/Matched.Show.S01E01.mkv"),
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
                    original=Path("C:/library/tv/Episode.Review.Show.2024/Season 01/Episode.Review.Show.S01E01.mkv"),
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
        self._assert_roster_section_title(workspace, 2, "REVIEW EPISODE MATCHING")

        matched_widget = self._roster_widget_for_index(workspace, 0)
        review_widget = self._roster_widget_for_index(workspace, 1)
        self.assertIsInstance(matched_widget, _RosterRowWidget)
        self.assertIsInstance(review_widget, _RosterRowWidget)
        self.assertFalse(matched_widget._check.isHidden())
        self.assertTrue(review_widget._check.isHidden())
        self.assertFalse(episode_review_state.checked)
        self.assertEqual(
            matched_widget._title.mapTo(matched_widget, QPoint(0, 0)).x(),
            review_widget._title.mapTo(review_widget, QPoint(0, 0)).x(),
        )

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
                        original=Path(f"{plex_ready_root}/Season 01/Auto Selected Show (2024) - S01E01 - Pilot.mkv"),
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
                        original=Path("C:/library/tv/Matched.Show.2024/Season 01/Matched.Show.S01E01.mkv"),
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
                        original=Path("C:/library/tv/Review.Show.2024/Season 01/Review.Show.S01E01.mkv"),
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
            workspace = MediaWorkspace(media_type="tv", media_controller=media_ctrl, settings_service=settings)

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
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace, _RosterRowWidget

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
                        original=Path("C:/library/tv/Example.Show.2024.Source/Season 01/Example Show (2024) - S01E01 - Pilot.mkv"),
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
                queue_controller=type("Q", (), {"add_tv_batch": lambda *args, **kwargs: BatchQueueResult(added=1)})(),
                settings_service=settings,
            )
            workspace.show_ready()

            row_widget = workspace._roster_list.itemWidget(workspace._roster_list.item(1))
            self.assertIsInstance(row_widget, _RosterRowWidget)
            self.assertEqual(row_widget._confidence._color.name(), "#777777")

            workspace.close()

    def test_media_workspace_roster_rows_use_placeholder_thumbnail_without_poster(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace, _RosterRowWidget

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
                queue_controller=type("Q", (), {"add_tv_batch": lambda *args, **kwargs: BatchQueueResult(added=1)})(),
                settings_service=settings,
                tmdb_provider=lambda: None,
            )
            workspace.show_ready()

            row_widget = workspace._roster_list.itemWidget(workspace._roster_list.item(1))
            self.assertIsInstance(row_widget, _RosterRowWidget)
            self.assertIsNotNone(row_widget._poster.pixmap())
            self.assertEqual(row_widget._poster.text(), "")

            workspace.close()

    def test_media_workspace_movie_roster_poster_is_vertically_centered(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace, _RosterRowWidget

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
                queue_controller=type("Q", (), {"add_movie_batch": lambda *args, **kwargs: BatchQueueResult(added=1)})(),
                settings_service=settings,
                tmdb_provider=lambda: None,
            )
            workspace.resize(1000, 700)
            workspace.show()
            workspace.show_ready()
            self._app.processEvents()

            row_widget = workspace._roster_list.itemWidget(workspace._roster_list.item(1))
            self.assertIsInstance(row_widget, _RosterRowWidget)
            row_center = row_widget.rect().center().y()
            poster_center = row_widget._poster.geometry().center().y()
            self.assertLessEqual(abs(poster_center - row_center), 2)

            workspace.close()

    def test_media_workspace_shows_threshold_aware_roster_match_text(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace, _RosterRowWidget

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
                        original=Path("C:/library/tv/Review.Show.2024/Season 01/Review.Show.S01E01.mkv"),
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
                queue_controller=type("Q", (), {"add_tv_batch": lambda *args, **kwargs: BatchQueueResult(added=0)})(),
                settings_service=settings,
            )
            workspace.show_ready()

            row_widget = workspace._roster_list.itemWidget(workspace._roster_list.item(1))
            self.assertIsInstance(row_widget, _RosterRowWidget)
            self.assertIn("TMDB - 42%", row_widget._meta.text())
            self.assertNotIn("Review 42%", row_widget._meta.text())
            self.assertEqual(row_widget._confidence_label.text(), "Confidence")
            self.assertEqual(row_widget._confidence._value, 42)
            self.assertIn("needs review", row_widget._meta.text())
            self.assertTrue(row_widget._status.isHidden())
            self.assertEqual(workspace._queue_inline_btn.text(), "Approve Match")

            workspace.close()

    def test_media_workspace_reuses_unchanged_roster_widgets_on_refresh(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace, _RosterRowWidget

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
                queue_controller=type("Q", (), {"add_tv_batch": lambda *args, **kwargs: BatchQueueResult(added=1)})(),
                settings_service=settings,
            )
            workspace.show_ready()

            original_widget = self._roster_widget_for_index(workspace, 0)
            self.assertIsInstance(original_widget, _RosterRowWidget)

            second.queued = True
            workspace.refresh_from_controller()

            refreshed_widget = self._roster_widget_for_index(workspace, 0)
            self.assertIs(refreshed_widget, original_widget)

            workspace.close()

    def test_media_workspace_queues_tv_states_without_crashing_on_regroup(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeQueueController:
            def __init__(self):
                self.called = False

            def add_tv_batch(self, states, root, output_root, gating):
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

    def test_media_workspace_preserves_movie_preview_after_queue_regroup(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _FakeQueueController:
            def __init__(self):
                self.called = False

            def add_movie_batch(self, states, root, output_root, gating):
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

            self.assertEqual(workspace._preview_list.count(), 3)
            workspace._queue_checked()
            self._app.processEvents()

            self.assertTrue(queue_ctrl.called)
            self._assert_roster_section_title(workspace, 0, "QUEUED")
            self.assertEqual(workspace._preview_list.count(), 3)
            self.assertTrue(any("FOLDER" in text for text in self._preview_header_texts(workspace)))
            self.assertIn("Folder rename plan:", workspace._folder_plan_label.text())

            workspace.close()

    def test_media_workspace_movie_refresh_keeps_same_folder_movies_unique_after_approval(self):
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
            media_info={"id": 11, "title": "Evangelion 1.11", "year": "2007", "_media_type": "movie"},
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
            media_info={"id": 44, "title": "Evangelion: 3.0+1.11 Thrice Upon a Time", "year": "2021", "_media_type": "movie"},
            preview_items=[
                PreviewItem(
                    original=root / "[LG] Evangelion 3.0+1.11.mkv",
                    new_name="Evangelion: 3.0+1.11 Thrice Upon a Time (2021).mkv",
                    target_dir=Path("C:/library/movies/Evangelion: 3.0+1.11 Thrice Upon a Time (2021)"),
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
            media_info={"id": 33, "title": "Evangelion: 3.0 You Can (Not) Redo", "year": "2012", "_media_type": "movie"},
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
        self.assertEqual(workspace._roster_list.count(), 5)

        review_state.match_origin = "manual"
        review_state.checked = True
        workspace.refresh_from_controller()
        workspace.refresh_from_controller()

        self.assertEqual(workspace._roster_list.count(), 4)
        self._assert_roster_section_title(workspace, 0, "MATCHED")

        seen_titles = []
        for row in range(workspace._roster_list.count()):
            item = workspace._roster_list.item(row)
            widget = workspace._roster_list.itemWidget(item)
            if widget is not None and hasattr(widget, "_title"):
                seen_titles.append(widget._title.text())
        self.assertEqual(len(seen_titles), 3)
        self.assertEqual(len(set(seen_titles)), 3)
        self.assertIn("Evangelion: 3.0 You Can (Not) Redo (2012)", seen_titles)

        workspace.close()


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
