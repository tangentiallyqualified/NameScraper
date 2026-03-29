from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


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


if __name__ == "__main__":
    unittest.main()