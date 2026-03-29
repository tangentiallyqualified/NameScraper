from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from plex_renamer.app.controllers.queue_controller import BatchQueueResult
from plex_renamer.app.services.command_gating_service import CommandGatingService
from plex_renamer.engine import PreviewItem, ScanState


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

            queue_tab = QueueTab(controller)
            history_tab = HistoryTab(controller)
            queue_tab.refresh()
            history_tab.refresh()

            self.assertEqual(queue_tab._model.rowCount(), 1)
            self.assertEqual(history_tab._model.rowCount(), 0)

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
        state = ScanState(
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
                )
            ],
            scanned=True,
            checked=True,
            confidence=1.0,
        )
        media_ctrl.movie_library_states = [state]

        workspace = MediaWorkspace(
            media_type="movie",
            media_controller=media_ctrl,
            queue_controller=queue_ctrl,
        )
        workspace.show_ready()

        self.assertEqual(workspace._roster_list.count(), 2)
        self.assertEqual(workspace._roster_list.item(0).text(), "Ready")
        self.assertIn("Folder rename plan:", workspace._folder_plan_label.text())
        self.assertIn("2024", workspace._folder_plan_label.text())
        self.assertGreater(workspace._preview_list.count(), 0)

        workspace._queue_checked()
        self.assertTrue(queue_ctrl.called)

        workspace.close()


if __name__ == "__main__":
    unittest.main()