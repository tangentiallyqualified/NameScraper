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
            def add_tv_batch(self, states, root, gating):
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
            def add_tv_batch(self, states, root, gating):
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
        workspace = MediaWorkspace(
            media_type="tv",
            media_controller=media_ctrl,
            queue_controller=_FakeQueueController(),
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

            def add_movie_batch(self, states, root, command_gating):
                self.called = True
                return BatchQueueResult(added=len(states))

        media_ctrl = _FakeMediaController()
        queue_ctrl = _FakeQueueController()
        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
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
            widget = workspace._preview_list.itemWidget(workspace._preview_list.item(row))
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
        self.assertTrue(hasattr(widget, "_approve_button"))
        self.assertTrue(hasattr(widget, "_fix_button"))
        self.assertTrue(widget._approve_button.isVisible())
        self.assertTrue(widget._fix_button.isVisible())

        widget._approve_button.click()
        self._app.processEvents()

        self.assertEqual(review_item.status, "OK")
        self.assertEqual(workspace._queue_inline_btn.text(), "Queue This Show")
        self.assertTrue(workspace._queue_inline_btn.isEnabled())

        workspace.close()

    def test_media_workspace_review_episode_fix_button_remaps_within_same_show(self):
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

        with (
            patch(
                "plex_renamer.gui_qt.widgets.media_workspace.QInputDialog.getItem",
                side_effect=AssertionError("episode fix should not use a collapsing combo dropdown"),
            ),
            patch(
                "plex_renamer.gui_qt.widgets._media_workspace_actions.EpisodeChoiceDialog.pick",
                return_value=(1, 2),
            ),
        ):
            widget._fix_button.click()
        self._app.processEvents()

        self.assertEqual(review_item.status, "OK")
        self.assertEqual(review_item.episodes, [2])
        self.assertIn("S01E02", review_item.new_name)
        self.assertEqual(review_item.episode_confidence, 1.0)

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

    def test_media_workspace_episode_guide_rows_have_stable_compact_height(self):
        from plex_renamer.gui_qt.widgets._workspace_widgets import EpisodeGuideRowWidget

        short_row = EpisodeGuideRowWidget(title="S01E01 - Pilot", status="Mapped", original="Pilot.mkv")
        missing_row = EpisodeGuideRowWidget(title="S01E02 - Missing", status="Missing File")
        long_row = EpisodeGuideRowWidget(
            title="S01E03 - This Is A Very Long Episode Title That Should Not Expand The Row Horizontally",
            status="Review",
            original="Example.Show.S01E03.With.A.Long.Release.Name.mkv",
            target="Example Show (2024) - S01E03 - This Is A Very Long Episode Title That Should Not Expand The Row Horizontally.mkv",
            confidence="52%",
        )

        heights = {short_row.sizeHint().height(), missing_row.sizeHint().height(), long_row.sizeHint().height()}
        self.assertEqual(len(heights), 1)
        self.assertLessEqual(next(iter(heights)), 76)

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
        self.assertEqual(widget._fix_button.property("sizeVariant"), "inline")
        self.assertLessEqual(widget._approve_button.sizeHint().height(), 24)
        self.assertLessEqual(widget._fix_button.sizeHint().height(), 24)
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
        self._assert_roster_section_title(workspace, 2, "NEEDS REVIEW")

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

            def add_tv_batch(self, states, root, gating):
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

            def add_movie_batch(self, states, root, gating):
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
