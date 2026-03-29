from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from plex_renamer.app.controllers.queue_controller import BatchQueueResult
from plex_renamer.app.services.command_gating_service import CommandGatingService
from plex_renamer.app.services.settings_service import SettingsService
from plex_renamer.constants import JobStatus
from plex_renamer.engine import CompanionFile, PreviewItem, ScanState


@unittest.skipUnless(importlib.util.find_spec("PySide6"), "PySide6 is not installed")
class QtSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def test_main_window_instantiates(self):
        from plex_renamer.gui_qt.main_window import MainWindow

        window = MainWindow()
        self.assertEqual(window.windowTitle(), "Plex Renamer")
        self.assertEqual(window.centralWidget().__class__.__name__, "QTabWidget")
        window.close()

    def test_main_window_undo_reverts_latest_job_and_switches_to_history(self):
        from PySide6.QtWidgets import QMessageBox
        from plex_renamer.constants import JobStatus
        from plex_renamer.engine import RenameResult
        from plex_renamer.gui_qt.main_window import MainWindow
        from plex_renamer.job_store import RenameJob

        window = MainWindow()
        job = RenameJob(
            library_root="C:/library",
            source_folder="Show",
            media_name="Example Show",
            status=JobStatus.COMPLETED,
            undo_data={"renames": [{"old": "a", "new": "b"}]},
        )
        window.queue_ctrl.get_latest_revertible_job = MagicMock(return_value=job)
        window.queue_ctrl.revert_job = MagicMock(return_value=(True, []))
        window._history_tab.select_job = MagicMock()

        with patch(
            "plex_renamer.gui_qt.main_window.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            window._on_undo()

        window.queue_ctrl.revert_job.assert_called_once_with(job.job_id)
        window._history_tab.select_job.assert_called_once_with(job.job_id)
        self.assertEqual(window.centralWidget().currentIndex(), 3)
        window.close()

    def test_main_window_queue_events_create_toasts(self):
        from plex_renamer.constants import JobStatus
        from plex_renamer.engine import RenameResult
        from plex_renamer.gui_qt.main_window import MainWindow
        from plex_renamer.job_store import RenameJob

        window = MainWindow()
        job = RenameJob(
            library_root="C:/library",
            source_folder="Show",
            media_name="Example Show",
            status=JobStatus.RUNNING,
        )

        window._on_job_started(job)
        window._on_job_completed(job, RenameResult(renamed_count=12))
        self.assertEqual(window._toast_manager.toast_count(), 1)

        window._history_tab.select_job = MagicMock()
        window._on_job_failed(job, "permission denied")
        self.assertEqual(window._toast_manager.toast_count(), 2)

        window._show_history_job(job.job_id)
        window._history_tab.select_job.assert_called_once_with(job.job_id)
        self.assertEqual(window.centralWidget().currentIndex(), 3)

        window._on_queue_finished()
        self.assertGreaterEqual(window._toast_manager.toast_count(), 3)
        window.close()

    def test_history_tab_revert_uses_inline_confirmation_banner(self):
        from plex_renamer.app.controllers.queue_controller import QueueController
        from plex_renamer.constants import JobStatus
        from plex_renamer.gui_qt.widgets.history_tab import HistoryTab
        from plex_renamer.job_store import JobStore, RenameJob

        with TemporaryDirectory() as tmp:
            store = JobStore(Path(tmp) / "jobs.sqlite3")
            queue_ctrl = QueueController(store)
            job = RenameJob(
                library_root="C:/library",
                source_folder="Show",
                media_name="Example Show",
                status=JobStatus.COMPLETED,
                undo_data={"renames": [{"old": "a", "new": "b"}, {"old": "c", "new": "d"}]},
            )
            store.add_job(job)
            queue_ctrl.revert_job = MagicMock(return_value=(True, []))

            history_tab = HistoryTab(queue_ctrl)
            history_tab.select_job(job.job_id)

            history_tab._revert_selected()

            self.assertFalse(history_tab._revert_banner.isHidden())
            self.assertIn("move 2 files", history_tab._revert_banner_label.text())

            history_tab._confirm_revert()

            queue_ctrl.revert_job.assert_called_once_with(job.job_id)
            self.assertTrue(history_tab._revert_banner.isHidden())
            history_tab.close()
            store.close()

    def test_queue_and_history_tabs_refresh(self):
        from plex_renamer.app.controllers.queue_controller import QueueController
        from plex_renamer.gui_qt.widgets.history_tab import HistoryTab
        from plex_renamer.gui_qt.widgets.queue_tab import QueueTab
        from plex_renamer.job_store import JobStore, RenameJob

        with TemporaryDirectory() as tmp:
            store = JobStore(db_path=Path(tmp) / "jobs.db")
            controller = QueueController(store)
            controller.job_store.add_job(
                RenameJob(
                    library_root=tmp,
                    source_folder="Show",
                    media_name="Example Show",
                    tmdb_id=123,
                )
            )
            controller.job_store.add_job(
                RenameJob(
                    library_root=tmp,
                    source_folder="Movie",
                    media_type="movie",
                    media_name="Example Movie",
                    tmdb_id=456,
                    status=JobStatus.COMPLETED,
                    rename_ops=[],
                )
            )

            queue_tab = QueueTab(controller)
            history_tab = HistoryTab(controller)
            queue_tab.refresh()
            history_tab.refresh()

            self.assertEqual(queue_tab._model.rowCount(), 1)
            self.assertEqual(history_tab._model.rowCount(), 1)
            self.assertEqual(queue_tab._proxy.rowCount(), 1)
            self.assertEqual(history_tab._proxy.rowCount(), 1)

            queue_tab._filter_combo.setCurrentText("Running Only")
            self.assertEqual(queue_tab._proxy.rowCount(), 0)
            queue_tab._filter_combo.setCurrentText("Pending Only")
            self.assertEqual(queue_tab._proxy.rowCount(), 1)

            history_tab._filter_combo.setCurrentText("Failed Only")
            self.assertEqual(history_tab._proxy.rowCount(), 0)
            history_tab._filter_combo.setCurrentText("Completed Only")
            self.assertEqual(history_tab._proxy.rowCount(), 1)

            queue_tab._select_all()
            self.assertEqual(len(queue_tab._table.selectionModel().selectedRows()), 1)
            queue_tab._clear_selection()
            self.assertEqual(len(queue_tab._table.selectionModel().selectedRows()), 0)

            history_tab._select_all()
            self.assertEqual(len(history_tab._table.selectionModel().selectedRows()), 1)
            history_tab._clear_selection()
            self.assertEqual(len(history_tab._table.selectionModel().selectedRows()), 0)

            queue_tab.close()
            history_tab.close()
            controller.close()

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

            self.assertEqual(workspace._roster_list.count(), 4)
            self.assertEqual(workspace._roster_list.item(0).text(), "PLEX READY")
            self.assertEqual(workspace._roster_list.item(2).text(), "MATCHED")
            self.assertIn("Folder rename plan:", workspace._folder_plan_label.text())
            self.assertIn("2024", workspace._folder_plan_label.text())
            self.assertGreater(workspace._preview_list.count(), 0)

            workspace._queue_checked()
            self.assertTrue(queue_ctrl.called)

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

            default_text = workspace._preview_list.item(0).text()
            self.assertIn("\n->", default_text)

            settings.view_mode = "compact"
            settings.show_companion_files = True
            workspace.apply_settings()

            compact_text = workspace._preview_list.item(0).text()
            self.assertNotIn("\n->", compact_text)
            self.assertIn("companion", compact_text)
            self.assertEqual(workspace._roster_list.iconSize().width(), 32)

            workspace.close()


if __name__ == "__main__":
    unittest.main()