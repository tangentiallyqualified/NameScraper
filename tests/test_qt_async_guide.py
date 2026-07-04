# tests/test_qt_async_guide.py
"""Async episode-guide pipeline: skeleton rows, token staleness, delivery (Plan 5)."""
from pathlib import Path
from unittest.mock import patch

from conftest_qt import QtSmokeBase


def _table_state(folder_name: str, *, episodes: int = 4, media_id: int = 101):
    from plex_renamer.app.services.episode_mapping_service import EpisodeMappingService
    from plex_renamer.engine import ScanState
    from plex_renamer.engine.episode_assignments import (
        ORIGIN_MANUAL,
        EpisodeAssignmentTable,
        EpisodeSlot,
    )

    table = EpisodeAssignmentTable()
    for episode in range(1, episodes + 1):
        table.add_slot(EpisodeSlot(season=1, episode=episode, title=f"Ep {episode}"))
    for episode in range(1, episodes + 1):
        entry = table.add_file(Path(f"C:/library/tv/{folder_name}/e{episode:02d}.mkv"))
        table.assign(entry.file_id, 1, [episode], origin=ORIGIN_MANUAL)
    state = ScanState(
        folder=Path(f"C:/library/tv/{folder_name}"),
        media_info={"id": media_id, "name": folder_name, "year": "2024"},
    )
    state.scanned = True
    state.confidence = 1.0
    state.assignments = table
    EpisodeMappingService().reproject(state)
    return state


class AsyncGuideModelTests(QtSmokeBase):
    """Deterministic scheduling: _submit_bg patched to capture workers."""

    def setUp(self):
        super().setUp()
        from plex_renamer.app.services.episode_projection_cache import (
            EpisodeProjectionCacheService,
        )
        from plex_renamer.gui_qt.widgets._episode_table_model import EpisodeTableModel

        self.cache = EpisodeProjectionCacheService()
        self.build_calls: list = []
        self.pending: list = []

        def counting_builder(state):
            self.build_calls.append(state)
            return self.cache.build_guide_with_signature(state)

        self._submit_patch = patch(
            "plex_renamer.gui_qt.widgets._episode_table_model._submit_bg",
            side_effect=self.pending.append,
        )
        self._submit_patch.start()
        self.addCleanup(self._submit_patch.stop)
        self.model = EpisodeTableModel(
            media_type="tv",
            cached_guide_provider=self.cache.cached_guide_for_state,
            guide_builder=counting_builder,
            guide_store=self.cache.store_guide,
        )

    def _kinds(self):
        return [entry.kind for entry in self.model._entries]

    def test_uncached_state_shows_skeleton_without_sync_build(self):
        state = _table_state("Show A")
        self.model.show_state(state, collapsed_sections=set())
        self.assertEqual(self.build_calls, [])          # nothing built on the GUI thread
        self.assertEqual(len(self.pending), 1)          # one worker scheduled
        kinds = set(self._kinds())
        self.assertIn("skeleton", kinds)
        self.assertNotIn("episode", kinds)

    def test_delivery_fills_table_stores_guide_and_emits_guide_loaded(self):
        state = _table_state("Show A")
        loaded: list[bool] = []
        self.model.guide_loaded.connect(lambda: loaded.append(True))
        self.model.show_state(state, collapsed_sections=set())
        self.pending.pop()()                            # run the captured worker
        self._app.processEvents()                       # deliver the bridge signal
        self.assertEqual(len(self.build_calls), 1)
        self.assertIn("episode", set(self._kinds()))
        self.assertNotIn("skeleton", set(self._kinds()))
        self.assertEqual(loaded, [True])
        self.assertIsNotNone(self.cache.cached_guide_for_state(state))

    def test_stale_delivery_is_dropped_after_state_switch(self):
        state_a = _table_state("Show A")
        state_b = _table_state("Show B", media_id=102)
        self.model.show_state(state_a, collapsed_sections=set())
        worker_a = self.pending.pop()
        self.model.show_state(state_b, collapsed_sections=set())
        worker_b = self.pending.pop()
        worker_a()                                      # stale: token moved on
        self._app.processEvents()
        self.assertIn("skeleton", set(self._kinds()))   # B still loading, A dropped
        self.assertIsNone(self.cache.cached_guide_for_state(state_a))
        worker_b()
        self._app.processEvents()
        self.assertIs(self.model.state(), state_b)
        self.assertIn("episode", set(self._kinds()))

    def test_cached_state_renders_synchronously_without_scheduling(self):
        state = _table_state("Show A")
        self.cache.prepare_state(state)
        self.model.show_state(state, collapsed_sections=set())
        self.assertEqual(self.pending, [])
        self.assertEqual(self.build_calls, [])
        self.assertIn("episode", set(self._kinds()))


class AsyncGuideRealThreadTest(QtSmokeBase):
    """One unpatched end-to-end pass over the real thread pool."""

    def test_guide_arrives_via_real_pool(self):
        from PySide6.QtTest import QTest

        from plex_renamer.app.services.episode_projection_cache import (
            EpisodeProjectionCacheService,
        )
        from plex_renamer.gui_qt.widgets._episode_table_model import EpisodeTableModel

        cache = EpisodeProjectionCacheService()
        model = EpisodeTableModel(
            media_type="tv",
            cached_guide_provider=cache.cached_guide_for_state,
            guide_builder=cache.build_guide_with_signature,
            guide_store=cache.store_guide,
        )
        loaded: list[bool] = []
        model.guide_loaded.connect(lambda: loaded.append(True))
        model.show_state(_table_state("Real Show"), collapsed_sections=set())
        for _ in range(200):                            # ≤ 10s hard cap
            if loaded:
                break
            QTest.qWait(50)
        self.assertEqual(loaded, [True])
        self.assertIn("episode", {entry.kind for entry in model._entries})
