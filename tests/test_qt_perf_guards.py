# tests/test_qt_perf_guards.py
"""Spec §7 perf guards over a 300-episode show (12 seasons x 25).

Budget on the reference machine: cached switch < 100ms. The wall-clock
assertion below uses a 5x margin (500ms) so offscreen CI variance cannot
flake it; the deterministic guards are the primary protection.
"""
from pathlib import Path
from unittest.mock import patch

from conftest_qt import QtSmokeBase


def _big_state(name: str = "Big Show", *, seasons: int = 12, per_season: int = 25):
    from plex_renamer.app.services.episode_mapping_service import EpisodeMappingService
    from plex_renamer.engine import ScanState
    from plex_renamer.engine.episode_assignments import (
        ORIGIN_MANUAL,
        EpisodeAssignmentTable,
        EpisodeSlot,
    )

    table = EpisodeAssignmentTable()
    for season in range(1, seasons + 1):
        for episode in range(1, per_season + 1):
            table.add_slot(EpisodeSlot(season=season, episode=episode,
                                       title=f"S{season:02d}E{episode:02d}"))
    for season in range(1, seasons + 1):
        for episode in range(1, per_season + 1):
            entry = table.add_file(
                Path(f"C:/library/tv/{name}/s{season:02d}e{episode:02d}.mkv")
            )
            table.assign(entry.file_id, season, [episode], origin=ORIGIN_MANUAL)
    state = ScanState(folder=Path(f"C:/library/tv/{name}"),
                      media_info={"id": 900, "name": name, "year": "2020"})
    state.scanned = True
    state.confidence = 1.0
    state.assignments = table
    EpisodeMappingService().reproject(state)
    return state


class PerfGuardTests(QtSmokeBase):
    def _async_model(self, cache):
        from plex_renamer.gui_qt.widgets._episode_table_model import EpisodeTableModel

        return EpisodeTableModel(
            media_type="tv",
            cached_guide_provider=cache.cached_guide_for_state,
            guide_builder=cache.build_guide_with_signature,
            guide_store=cache.store_guide,
        )

    def test_uncached_300_episode_switch_never_builds_on_gui_thread(self):
        from plex_renamer.app.services.episode_projection_cache import (
            EpisodeProjectionCacheService,
        )

        cache = EpisodeProjectionCacheService()
        pending: list = []
        with patch(
            "plex_renamer.gui_qt.widgets._episode_table_model._submit_bg",
            side_effect=pending.append,
        ):
            model = self._async_model(cache)
            resets: list[bool] = []
            model.modelReset.connect(lambda: resets.append(True))
            model.show_state(_big_state(), collapsed_sections=set())
        self.assertEqual(len(resets), 1)                       # one reset, instant
        self.assertEqual(len(pending), 1)                      # build went to the pool
        self.assertIn("skeleton", {e.kind for e in model._entries})

    def test_cached_300_episode_switch_renders_under_offscreen_budget(self):
        from PySide6.QtCore import QElapsedTimer

        from plex_renamer.app.services.episode_projection_cache import (
            EpisodeProjectionCacheService,
        )

        cache = EpisodeProjectionCacheService()
        state = _big_state()
        cache.prepare_state(state)
        model = self._async_model(cache)
        timer = QElapsedTimer()
        timer.start()
        model.show_state(state, collapsed_sections=set())
        elapsed_ms = timer.elapsed()
        self.assertIn("episode", {e.kind for e in model._entries})
        self.assertLess(
            elapsed_ms, 500,
            f"cached 300-episode switch took {elapsed_ms}ms offscreen "
            "(reference budget 100ms; 5x margin)",
        )

    def test_cached_500_episode_populate_and_first_paint_under_budget(self):
        """Spec §18: synthetic 500-episode state; model population plus the
        first full paint pass stay under budget (generous offscreen margin).
        The 300-episode tests above pin the async invariants; this one is
        the release gate at the spec's stated size."""
        from PySide6.QtCore import QElapsedTimer

        from plex_renamer.app.services.episode_projection_cache import (
            EpisodeProjectionCacheService,
        )
        from plex_renamer.gui_qt.widgets._episode_table_delegate import (
            EpisodeTableDelegate,
            EpisodeTableView,
        )

        cache = EpisodeProjectionCacheService()
        state = _big_state("Huge Show", seasons=20, per_season=25)   # 500 eps
        cache.prepare_state(state)
        model = self._async_model(cache)
        view = EpisodeTableView()
        view.setItemDelegate(EpisodeTableDelegate(view, media_type="tv"))
        view.setModel(model)
        view.resize(900, 700)
        view.show()
        timer = QElapsedTimer()
        timer.start()
        model.show_state(state, collapsed_sections=set())
        pixmap = view.grab()                 # forces the first full paint pass
        elapsed_ms = timer.elapsed()
        self.assertIn("episode", {e.kind for e in model._entries})
        self.assertFalse(pixmap.isNull())
        self.assertLess(
            elapsed_ms, 1000,
            f"cached 500-episode populate + first paint took {elapsed_ms}ms "
            "offscreen (reference budget 200ms; 5x margin)",
        )
        view.close()
