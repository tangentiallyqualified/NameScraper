from __future__ import annotations

import tempfile
from pathlib import Path

from _scanner_fakes import MetadataScannerFake
from conftest_qt import QtSmokeBase
from PySide6.QtWidgets import QPushButton

from plex_renamer.app.services.command_gating_service import CommandGatingService
from plex_renamer.app.services.settings_service import SettingsService
from plex_renamer.engine import CompletenessReport, PreviewItem, ScanState, SeasonCompleteness
from plex_renamer.gui_qt.widgets._episode_expansion import EpisodeExpansionCard
from plex_renamer.gui_qt.widgets._work_panel import MediaWorkPanel
from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace


def _make_settings(tmp_dir: str, *, metadata_source: str = "tmdb") -> SettingsService:
    settings = SettingsService(path=Path(tmp_dir) / "settings.json")
    settings.tv_metadata_source = metadata_source
    return settings


class _FakeMediaController:
    def __init__(self, state: ScanState) -> None:
        self.command_gating = CommandGatingService()
        self.batch_states = [state]
        self.movie_library_states: list[ScanState] = []
        self.library_selected_index = 0
        self.movie_folder = Path("C:/library/movies")
        self.tv_root_folder = Path("C:/library/tv")

    def select_show(self, index: int) -> ScanState | None:
        self.library_selected_index = index
        if 0 <= index < len(self.batch_states):
            return self.batch_states[index]
        return None

    def sync_queued_states(self) -> None:
        return None


class _FakeProviderClient:
    def __init__(self, name: str) -> None:
        self.provider_name = name


class _FakeSwitchOrchestrator:
    """Stands in for BatchTVOrchestrator's provider-pool surface used by
    the workspace's Source control: ``provider_for`` + ``switch_provider``
    (Task 8 covers the real engine behavior; this only exercises the GUI
    wiring around it)."""

    def __init__(self) -> None:
        self.tmdb = _FakeProviderClient("tmdb")
        self.tvdb = _FakeProviderClient("tvdb")
        self.switch_calls: list[tuple[ScanState, str]] = []

    def provider_for(self, state: ScanState):
        return self.tvdb if state.provider_name == "tvdb" else self.tmdb

    def switch_provider(self, state: ScanState, provider_name: str):
        self.switch_calls.append((state, provider_name))
        state.provider_name = provider_name
        state.match_origin = "manual"
        state.reset_scan()
        return state, True


class _FakeSwitchMediaController(_FakeMediaController):
    def __init__(self, state: ScanState, orchestrator: _FakeSwitchOrchestrator) -> None:
        super().__init__(state)
        self.batch_orchestrator = orchestrator
        self.scan_show_calls: list[tuple[ScanState, object]] = []

    def scan_show(self, state: ScanState, tmdb) -> None:
        self.scan_show_calls.append((state, tmdb))


def _section_titles(panel: MediaWorkPanel) -> list[str]:
    titles: list[str] = []
    for row in range(panel.model.rowCount()):
        data = panel.model.row_data_at(row)
        if data is not None and data.kind in {"section-header", "section-label"}:
            titles.append(data.title)
    return titles


def _row_statuses(panel: MediaWorkPanel) -> list[str]:
    statuses: list[str] = []
    for row in range(panel.model.rowCount()):
        data = panel.model.row_data_at(row)
        if data is not None:
            statuses.append(data.status_text)
    return statuses


def _open_card(panel: MediaWorkPanel, row: int) -> EpisodeExpansionCard:
    index = panel.model.index(row, 0)
    panel.table_view.chevron_clicked.emit(index)
    card = panel.table_view.indexWidget(index)
    assert isinstance(card, EpisodeExpansionCard)
    return card


def _card_action_button(card: EpisodeExpansionCard, action_id: str) -> QPushButton | None:
    for button in card.header_action_buttons() + card.action_buttons():
        if button.property("actionId") == action_id:
            return button
    return None


class QtMediaWorkspaceReviewActionsTests(QtSmokeBase):
    def tearDown(self):
        self._dispose_top_level_widgets(MediaWorkspace)
        super().tearDown()

    @staticmethod
    def _panel(workspace: MediaWorkspace) -> MediaWorkPanel:
        panel = workspace.findChild(MediaWorkPanel)
        assert panel is not None
        return panel

    def test_media_workspace_selected_review_episode_uses_card_actions(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

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

        panel = self._panel(workspace)
        card_row = panel.model.row_for_preview_index(0)
        self.assertGreaterEqual(card_row, 0)
        card = _open_card(panel, card_row)

        self.assertEqual(panel.primary_action_button.text(), "Queue This Show")
        self.assertNotEqual(panel.primary_action_button.text(), "Approve Episode")
        # New API: the expansion card carries the Approve button plus reassign /
        # unassign actions for Review rows.
        self.assertIsNotNone(_card_action_button(card, "approve"))
        # Round5 §4a: Review above-fold actions (reassign/unassign) are hosted
        # in the header parity strip; the card still carries them.
        card_labels = [
            button.text() for button in card.header_action_buttons() + card.action_buttons()
        ]
        self.assertIn("Reassign...", card_labels)
        self.assertIn("Unassign", card_labels)

        workspace.close()

    def test_media_workspace_review_episode_fix_button_replaced_by_actions_menu(self):
        # TODO(Task 12): restore end-to-end reassign assertions once dispatch is wired.
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

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
            scanner=MetadataScannerFake(
                {
                    (1, 1): {"name": "Pilot"},
                    (1, 2): {"name": "Second"},
                }
            ),
            preview_items=[review_item],
            scanned=True,
            checked=False,
            confidence=1.0,
        )
        workspace = MediaWorkspace(media_type="tv", media_controller=_FakeMediaController(state))
        workspace.show()
        workspace.show_ready()
        self._app.processEvents()

        panel = self._panel(workspace)
        card_row = panel.model.row_for_preview_index(0)
        self.assertGreaterEqual(card_row, 0)
        card = _open_card(panel, card_row)

        # New API: no per-row Fix button; reassign is an expansion-card action
        # (round5 §4a hosts it in the header parity strip for Review rows).
        card_labels = [
            button.text() for button in card.header_action_buttons() + card.action_buttons()
        ]
        self.assertIn("Reassign...", card_labels)

        workspace.close()

    def test_media_workspace_approve_all_review_episodes_is_inline_with_filters(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

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

        panel = self._panel(workspace)
        approve_all = panel.approve_all_button

        self.assertTrue(approve_all.isVisible())
        self.assertEqual(approve_all.text(), "Approve All")
        self.assertEqual(approve_all.property("cssClass"), "primary")
        # Approve All lives in the work panel's toolbar alongside the segmented
        # filter control.
        self.assertIs(approve_all.parent(), panel.segmented_filter.parent())

        approve_all.click()
        self._app.processEvents()

        self.assertEqual([item.status for item in state.preview_items], ["OK", "OK"])
        self.assertFalse(approve_all.isVisible())
        self.assertTrue(panel.primary_action_button.isEnabled())

        workspace.close()

    def test_media_workspace_tv_episode_guide_filters_all_and_problems(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

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
                seasons={
                    1: SeasonCompleteness(season=1, expected=2, matched=1, missing=[(2, "Second")])
                },
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
        panel = self._panel(workspace)

        # In the default "all" filter, UNMAPPED PRIMARY FILES must appear BEFORE season rows.
        all_headers = [title.upper() for title in _section_titles(panel)]
        unmapped_indices = [i for i, h in enumerate(all_headers) if "UNMAPPED PRIMARY FILES" in h]
        season_indices = [i for i, h in enumerate(all_headers) if "SEASON 1" in h]
        self.assertTrue(unmapped_indices, "Expected an UNMAPPED PRIMARY FILES header")
        self.assertTrue(season_indices, "Expected a SEASON 1 header")
        self.assertLess(
            unmapped_indices[0],
            season_indices[0],
            "UNMAPPED PRIMARY FILES header must appear before SEASON 1 header",
        )

        panel.segmented_filter.setCurrentText("Problems")
        statuses = _row_statuses(panel)
        self.assertNotIn("Mapped", statuses)
        self.assertIn("Missing File", statuses)
        self.assertTrue(
            any("UNMAPPED PRIMARY FILES" in title.upper() for title in _section_titles(panel))
        )

        # The old dedicated "Unmapped" filter segment is gone (R2 M9): unmapped
        # files are reached via a season-strip chip instead, and the segmented
        # control only offers All/Problems.
        filter_labels = {
            button.text() for button in panel.segmented_filter.findChildren(QPushButton)
        }
        self.assertEqual(filter_labels, {"All", "Problems"})

        workspace.close()


class QtMediaWorkspaceSourceSelectorTests(QtSmokeBase):
    """Task 9's workspace Source selector: switch_provider + pin persist +
    rescan through the newly attributed provider's client."""

    def tearDown(self):
        self._dispose_top_level_widgets(MediaWorkspace)
        super().tearDown()

    def test_switch_source_persists_pin_and_rescans_through_new_provider(self):
        state = ScanState(
            folder=Path("C:/library/tv/Example"),
            media_info={"id": 101, "name": "Example Show", "year": "2024"},
            provider_name="tmdb",
            scanned=True,
            checked=False,
            confidence=1.0,
        )
        orchestrator = _FakeSwitchOrchestrator()
        controller = _FakeSwitchMediaController(state, orchestrator)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            settings = _make_settings(tmp_dir, metadata_source="tmdb")
            workspace = MediaWorkspace(
                media_type="tv", media_controller=controller, settings_service=settings
            )
            workspace.show()
            workspace.show_ready()
            self._app.processEvents()

            workspace._on_source_selected("tvdb")

            self.assertEqual(orchestrator.switch_calls, [(state, "tvdb")])
            self.assertEqual(state.provider_name, "tvdb")

            from plex_renamer.engine.models import show_pin_key

            pin_key = show_pin_key(state.folder)
            self.assertEqual(
                settings.tv_provider_overrides,
                {pin_key: {"provider": "tvdb", "show_id": 101}},
            )
            self.assertEqual(len(controller.scan_show_calls), 1)
            scanned_state, client = controller.scan_show_calls[0]
            self.assertIs(scanned_state, state)
            self.assertIs(client, orchestrator.tvdb)

            workspace.close()

    def test_switch_source_back_to_default_source_clears_pin(self):
        state = ScanState(
            folder=Path("C:/library/tv/Example"),
            media_info={"id": 101, "name": "Example Show", "year": "2024"},
            provider_name="tvdb",
            scanned=True,
            checked=False,
            confidence=1.0,
        )
        orchestrator = _FakeSwitchOrchestrator()
        controller = _FakeSwitchMediaController(state, orchestrator)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            settings = _make_settings(tmp_dir, metadata_source="tmdb")
            from plex_renamer.engine.models import show_pin_key

            pin_key = show_pin_key(state.folder)
            settings.tv_provider_overrides = {pin_key: {"provider": "tvdb", "show_id": 101}}
            workspace = MediaWorkspace(
                media_type="tv", media_controller=controller, settings_service=settings
            )
            workspace.show()
            workspace.show_ready()
            self._app.processEvents()

            workspace._on_source_selected("tmdb")

            self.assertEqual(settings.tv_provider_overrides, {})

            workspace.close()

    def test_switch_source_prunes_corrupt_pins_on_write(self):
        """Task 8 note: corrupt/unresolvable pins are pruned the next time
        the GUI writes the overrides dict."""
        state = ScanState(
            folder=Path("C:/library/tv/Example"),
            media_info={"id": 101, "name": "Example Show", "year": "2024"},
            provider_name="tmdb",
            scanned=True,
            checked=False,
            confidence=1.0,
        )
        orchestrator = _FakeSwitchOrchestrator()
        controller = _FakeSwitchMediaController(state, orchestrator)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            settings = _make_settings(tmp_dir, metadata_source="tmdb")
            settings.tv_provider_overrides = {
                "corrupt|2000": {"provider": "nonexistent", "show_id": 5},
                "malformed": "not-a-dict",
            }
            workspace = MediaWorkspace(
                media_type="tv", media_controller=controller, settings_service=settings
            )
            workspace.show()
            workspace.show_ready()
            self._app.processEvents()

            workspace._on_source_selected("tvdb")

            from plex_renamer.engine.models import show_pin_key

            pin_key = show_pin_key(state.folder)
            self.assertEqual(
                settings.tv_provider_overrides,
                {pin_key: {"provider": "tvdb", "show_id": 101}},
            )

            workspace.close()
