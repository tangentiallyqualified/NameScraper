"""Shared Qt smoke-test base class and helpers."""
from __future__ import annotations

from contextlib import ExitStack
import importlib.util
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt


@unittest.skipUnless(importlib.util.find_spec("PySide6"), "PySide6 is not installed")
class QtSmokeBase(unittest.TestCase):
    """Base class providing isolated Qt app, settings, cache, and job store."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        from plex_renamer.app.services.cache_service import PersistentCacheService
        from plex_renamer.app.services.settings_service import SettingsService
        from plex_renamer.job_store import JobStore

        self._main_window_stack = ExitStack()
        self.addCleanup(self._main_window_stack.close)
        self._main_window_tmp = TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._main_window_tmp.cleanup)
        base = Path(self._main_window_tmp.name)
        isolated_settings = SettingsService(path=base / "settings.json")
        isolated_cache = PersistentCacheService(db_path=base / "cache.db")
        isolated_store = JobStore(db_path=base / "jobs.db")
        self.addCleanup(isolated_store.close)
        self._main_window_stack.enter_context(
            patch("plex_renamer.gui_qt.main_window.SettingsService", return_value=isolated_settings)
        )
        self._main_window_stack.enter_context(
            patch("plex_renamer.gui_qt.main_window.PersistentCacheService", return_value=isolated_cache)
        )
        self._main_window_stack.enter_context(
            patch("plex_renamer.gui_qt.main_window.JobStore", return_value=isolated_store)
        )

    # -- Shared helpers --------------------------------------------------

    def _reset_main_window_queue(self, window) -> None:
        queued_ids = [job.job_id for job in window.queue_ctrl.get_queue()]
        if queued_ids:
            window.queue_ctrl.remove_jobs(queued_ids)
        if window.queue_ctrl.get_history():
            window.queue_ctrl.clear_history()
        window._on_queue_changed()
        self._app.processEvents()

    def _roster_widget_for_index(self, workspace, index: int):
        for row in range(workspace._roster_list.count()):
            item = workspace._roster_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == index:
                return workspace._roster_list.itemWidget(item)
        return None

    def _preview_widget_for_index(self, workspace, index: int):
        for row in range(workspace._preview_list.count()):
            item = workspace._preview_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == index:
                return workspace._preview_list.itemWidget(item)
        return None

    def _preview_header_texts(self, workspace) -> list[str]:
        headers: list[str] = []
        for row in range(workspace._preview_list.count()):
            item = workspace._preview_list.item(row)
            text = item.text().strip()
            if text:
                headers.append(text)
        return headers

    def _assert_roster_section_title(self, workspace, row: int, expected: str) -> None:
        text = workspace._roster_list.item(row).text().strip()
        normalized = text.removeprefix("▼").removeprefix("▶").strip()
        if " (" in normalized:
            normalized = normalized.split(" (", 1)[0]
        self.assertEqual(normalized, expected)
