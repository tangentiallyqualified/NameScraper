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

    def test_mid_flight_mutation_orphans_stale_build(self):
        """Review I1: a mutation completing while a build is in flight must
        orphan that build — the cache-hit re-render supersedes it, so the
        late delivery is dropped instead of rendered/stored."""
        from plex_renamer.app.services.episode_mapping_service import EpisodeMappingService

        state = _table_state("Show A")
        self.model.show_state(state, collapsed_sections=set())
        stale_worker = self.pending.pop()               # pre-mutation build in flight
        # Mutation path completes synchronously mid-flight: unassign a file,
        # reproject, refresh the cache (the refresh_episode_guide shape),
        # then re-render — the resolve hits the fresh cache entry.
        state.assignments.unassign(next(iter(state.assignments.files)))
        EpisodeMappingService().reproject(state)
        fresh_guide = self.cache.refresh_state(state)
        self.model.show_state(state, collapsed_sections=set())
        self.assertEqual(self.pending, [])              # cache hit: nothing scheduled
        self.assertIs(self.model.guide(), fresh_guide)
        stale_worker()                                  # orphaned build delivers late
        self._app.processEvents()
        self.assertIs(self.model.guide(), fresh_guide)  # render kept, not reverted
        self.assertIs(self.cache.cached_guide_for_state(state), fresh_guide)

    def test_failed_build_renders_error_row_not_permanent_skeleton(self):
        state = _table_state("Show A")
        self.model._guide_builder = lambda s: (_ for _ in ()).throw(RuntimeError("boom"))
        self.model.show_state(state, collapsed_sections=set())
        self.pending.pop()()                        # worker runs, builder raises
        self._app.processEvents()
        kinds = [entry.kind for entry in self.model._entries]
        self.assertNotIn("skeleton", kinds)
        self.assertEqual(kinds, ["section-label"])
        row = self.model._entries[0].row_data
        self.assertIn("failed", row.title)
        self.assertIn("retry", row.title)
        self.assertEqual(row.status_tone, "error")
        self.assertEqual(self.model.summary_text(), "Guide unavailable")

    def test_reselect_after_failure_schedules_a_fresh_build(self):
        state = _table_state("Show A")
        self.model._guide_builder = lambda s: (_ for _ in ()).throw(RuntimeError("boom"))
        self.model.show_state(state, collapsed_sections=set())
        self.pending.pop()()
        self._app.processEvents()

        def working_builder(s):
            self.build_calls.append(s)
            return self.cache.build_guide_with_signature(s)

        self.model._guide_builder = working_builder
        self.model.show_state(state, collapsed_sections=set())   # user reselects
        self.assertEqual(len(self.pending), 1)                   # fresh build scheduled
        self.pending.pop()()
        self._app.processEvents()
        self.assertIn("episode", {entry.kind for entry in self.model._entries})
        self.assertNotEqual(self.model.summary_text(), "Guide unavailable")

    def test_summary_text_says_loading_while_skeleton_is_up(self):
        state = _table_state("Show A")
        self.model.show_state(state, collapsed_sections=set())
        self.assertEqual(self.model.summary_text(), "Loading episodes…")
        self.pending.pop()()
        self._app.processEvents()
        self.assertTrue(self.model.summary_text().startswith("4 files"))

    def test_summary_text_for_scan_error_state_reports_counts_not_loading(self):
        """Final-review I1: a scan-error state never enters the loading
        pipeline, so its footer must not claim loading — nor inherit a stale
        "Guide unavailable" from a previously failed build on another state."""
        state = _table_state("Show A")
        self.model._guide_builder = lambda s: (_ for _ in ()).throw(RuntimeError("boom"))
        self.model.show_state(state, collapsed_sections=set())
        self.pending.pop()()
        self._app.processEvents()                       # _guide_error now True
        error_state = _table_state("Show B", media_id=102)
        error_state.scan_error = "TMDB unreachable"
        self.model.show_state(error_state, collapsed_sections=set())
        self.assertEqual(self.model.summary_text(), "0 files · 0 mapped")


class AsyncGuideWorkPanelTests(QtSmokeBase):
    """Panel behavior when the guide arrives while Bulk Assign is active."""

    def test_mid_bulk_delivery_keeps_hidden_toolbar_and_bulk_mode(self):
        """Review I2: a guide landing mid-bulk must not re-show the Approve
        All button (or the overflow menu) that enter_bulk_assign hid; the
        toolbar re-derives on exit_bulk_assign."""
        from plex_renamer.app.services.episode_projection_cache import (
            EpisodeProjectionCacheService,
        )
        from plex_renamer.gui_qt.widgets._work_panel import MediaWorkPanel

        cache = EpisodeProjectionCacheService()
        pending: list = []
        with patch(
            "plex_renamer.gui_qt.widgets._episode_table_model._submit_bg",
            side_effect=pending.append,
        ):
            panel = MediaWorkPanel(
                media_type="tv",
                cached_guide_provider=cache.cached_guide_for_state,
                guide_builder=cache.build_guide_with_signature,
                guide_store=cache.store_guide,
            )
            panel.resize(760, 640)
            panel.show()
            state = _table_state("Show A")
            panel.show_state(state, collapsed_sections=set())
            self.assertEqual(len(pending), 1)               # guide still loading
            panel.enter_bulk_assign()
            pending.pop()()                                 # guide arrives mid-bulk
            self._app.processEvents()
            self.assertIn("episode", {e.kind for e in panel.model._entries})
            self.assertTrue(panel.bulk_assign_active())     # bulk mode survived
            self.assertFalse(panel.approve_all_button.isVisible())
            self.assertFalse(panel.overflow_button.isVisible())
            self.assertTrue(panel.summary_label.text())     # footer still refreshed
            panel.exit_bulk_assign()
            self.assertFalse(panel.bulk_assign_active())
            self.assertTrue(panel.overflow_button.isVisible())  # re-derived on exit
            panel.close()

    def test_same_state_repopulate_mid_bulk_keeps_buttons_hidden(self):
        """Re-review M6: refresh_from_controller repopulates the panel with the
        same state during bulk; show_state's unconditional update_toolbar must
        not re-show the hidden Approve All button (or the overflow menu)."""
        from plex_renamer.app.services.episode_projection_cache import (
            EpisodeProjectionCacheService,
        )
        from plex_renamer.gui_qt.widgets._work_panel import MediaWorkPanel

        cache = EpisodeProjectionCacheService()
        panel = MediaWorkPanel(
            media_type="tv",
            cached_guide_provider=cache.cached_guide_for_state,
            guide_builder=cache.build_guide_with_signature,
            guide_store=cache.store_guide,
        )
        panel.resize(760, 640)
        panel.show()
        state = _table_state("Show A")
        cache.prepare_state(state)                       # cached: sync render
        panel.show_state(state, collapsed_sections=set())
        self.assertTrue(panel.overflow_button.isVisible())
        panel.enter_bulk_assign()   # overflow visibility itself is re-derived by
        # update_toolbar, not by enter_bulk_assign directly; the repopulate
        # below is what exercises the real hide.
        panel.show_state(state, collapsed_sections=set())   # same-state repopulate
        self.assertTrue(panel.bulk_assign_active())
        self.assertFalse(panel.approve_all_button.isVisible())
        self.assertFalse(panel.overflow_button.isVisible())
        panel.exit_bulk_assign()
        self.assertTrue(panel.overflow_button.isVisible())
        panel.close()


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
