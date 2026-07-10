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


@unittest.skipUnless(importlib.util.find_spec("PySide6"), "PySide6 is not installed")
class QtSmokeBase(unittest.TestCase):
    """Base class providing isolated Qt app, settings, cache, and job store."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls):
        # Background tasks submitted via plex_renamer.thread_pool must not
        # outlive the tests that spawned them: the pool's atexit shutdown uses
        # wait=False, so a worker still running at interpreter exit races
        # Qt/CPython teardown and access-violates (0xC0000005) short pytest
        # runs. Flush the queue before the next class (no-op when idle).
        import gc
        from concurrent.futures import wait

        from plex_renamer import thread_pool

        wait([thread_pool.submit(lambda: None) for _ in range(8)], timeout=30)
        # Drain pending DeferredDeletes and collect Python↔Qt reference
        # cycles at a safe point while the QApplication is alive. Left to
        # its own schedule, Python 3.14's incremental GC can finalize
        # Qt-object cycles mid-event-loop in a later class or during
        # interpreter exit, corrupting the native heap (0xC0000374).
        cls._app.processEvents()
        gc.collect()
        cls._app.processEvents()
        super().tearDownClass()

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
        self._main_window_stack.enter_context(
            patch("plex_renamer.gui_qt.main_window.get_api_key", return_value=None)
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

    def _roster_row_data_for_index(self, workspace, index: int):
        """RosterRowData snapshot for the state at controller index, or None."""
        from plex_renamer.gui_qt.widgets._roster_model import ROW_DATA_ROLE

        model = workspace._roster_panel.model
        row = model.row_for_state_index(index)
        if row < 0:
            return None
        return model.index(row, 0).data(ROW_DATA_ROLE)

    def _episode_row_data_for_preview_index(self, workspace, index: int):
        from plex_renamer.gui_qt.widgets._episode_table_model import ROW_DATA_ROLE

        model = workspace._work_panel.model
        row = model.row_for_preview_index(index)
        if row < 0:
            return None
        return model.index(row, 0).data(ROW_DATA_ROLE)

    def _episode_section_titles(self, workspace) -> list[str]:
        model = workspace._work_panel.model
        titles: list[str] = []
        for row in range(model.rowCount()):
            if model.row_kind_at(row) in {"section-header", "section-label"}:
                text = (model.index(row, 0).data() or "").strip()
                for prefix in ("▸ ", "▾ "):
                    text = text.removeprefix(prefix)
                titles.append(text)
        return titles

    def _open_expansion_card(self, workspace, row: int):
        view = workspace._work_panel.table_view
        model = workspace._work_panel.model
        workspace._on_table_expand_requested(model.index(row, 0))
        return view.indexWidget(model.index(row, 0))

    def _card_action_button(self, card, action_id: str):
        """The expansion card's QPushButton whose actionId property matches, or None."""
        for button in card._action_buttons:
            if button.property("actionId") == action_id:
                return button
        return None

    def _folder_section_target(self, workspace) -> str | None:
        """Target-name string of the FOLDER section's folder row, or None."""
        from plex_renamer.gui_qt.widgets._episode_table_model import ROW_DATA_ROLE

        model = workspace._work_panel.model
        for row in range(model.rowCount()):
            if model.row_kind_at(row) == "folder":
                data = model.index(row, 0).data(ROW_DATA_ROLE)
                return data.target if data is not None else None
        return None

    def _episode_section_collapsed(self, workspace, title_substr: str) -> bool | None:
        """Collapsed state of the section-header whose title contains
        ``title_substr`` (case-insensitive), or None if not found."""
        from plex_renamer.gui_qt.widgets._episode_table_model import ROW_DATA_ROLE

        model = workspace._work_panel.model
        needle = title_substr.casefold()
        for row in range(model.rowCount()):
            if model.row_kind_at(row) != "section-header":
                continue
            data = model.index(row, 0).data(ROW_DATA_ROLE)
            if data is not None and needle in data.title.casefold():
                return data.collapsed
        return None

    def _first_section_key(self, workspace, *, prefix: str | None = None):
        """SECTION_KEY_ROLE of the first collapsible section-header, optionally
        filtered to keys starting with ``prefix``."""
        from plex_renamer.gui_qt.widgets._episode_table_model import SECTION_KEY_ROLE

        model = workspace._work_panel.model
        for row in range(model.rowCount()):
            if model.row_kind_at(row) != "section-header":
                continue
            key = model.index(row, 0).data(SECTION_KEY_ROLE)
            if key is None:
                continue
            if prefix is not None and not str(key).startswith(prefix):
                continue
            return key
        return None

    def _episode_row_datas(self, workspace) -> list:
        """All visible EpisodeRowData snapshots in table order."""
        from plex_renamer.gui_qt.widgets._episode_table_model import ROW_DATA_ROLE

        model = workspace._work_panel.model
        datas = []
        for row in range(model.rowCount()):
            data = model.index(row, 0).data(ROW_DATA_ROLE)
            if data is not None:
                datas.append(data)
        return datas

    def _assert_roster_section_title(self, workspace, row: int, expected: str) -> None:
        model = workspace._roster_panel.model
        text = (model.index(row, 0).data() or "").strip()
        normalized = text.removeprefix("▼").removeprefix("▶").strip()
        if " (" in normalized:
            normalized = normalized.split(" (", 1)[0]
        self.assertEqual(normalized, expected)
