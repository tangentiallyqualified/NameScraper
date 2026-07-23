# pyright: strict
"""Live MediaWorkspace reassign dispatch and refresh contract coverage."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from conftest_qt import QtSmokeBase
from PySide6.QtWidgets import QPushButton

from plex_renamer.app.services.command_gating_service import CommandGatingService
from plex_renamer.app.services.episode_mapping_service import EpisodeMappingService
from plex_renamer.engine import ScanState
from plex_renamer.engine._episode_projection import project_preview_items
from plex_renamer.engine.episode_assignments import (
    ORIGIN_AUTO,
    EpisodeAssignmentTable,
    EpisodeSlot,
)
from plex_renamer.engine.models import MediaInfoValue, PreviewItem
from plex_renamer.gui_qt.widgets._episode_expansion import EpisodeExpansionCard
from plex_renamer.gui_qt.widgets._work_panel import MediaWorkPanel
from plex_renamer.gui_qt.widgets.episode_assign_dialog import EpisodeAssignDialog
from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace


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


def _open_reassign_button(panel: MediaWorkPanel) -> QPushButton:
    card_row = panel.model.row_for_preview_index(0)
    assert card_row >= 0
    index = panel.model.index(card_row, 0)
    panel.table_view.chevron_clicked.emit(index)
    card = panel.table_view.indexWidget(index)
    assert isinstance(card, EpisodeExpansionCard)
    for button in card.header_action_buttons() + card.action_buttons():
        if button.property("actionId") == "reassign":
            return button
    raise AssertionError("Expected a visible Reassign action")


@dataclass(frozen=True)
class _ReassignFixture:
    workspace: MediaWorkspace
    state: ScanState
    file_id: int
    panel: MediaWorkPanel
    button: QPushButton


class QtMediaWorkspaceReassignContractTests(QtSmokeBase):
    def tearDown(self) -> None:
        self._dispose_top_level_widgets(MediaWorkspace)
        super().tearDown()

    def _reassign_fixture(self) -> _ReassignFixture:
        folder = Path("C:/library/tv/Example")
        media_info: dict[str, MediaInfoValue] = {
            "id": 101,
            "name": "Example Show",
            "year": "2024",
        }
        table = EpisodeAssignmentTable()
        table.add_slot(EpisodeSlot(season=1, episode=1, title="Pilot"))
        table.add_slot(EpisodeSlot(season=1, episode=2, title="Second"))
        entry = table.add_file(folder / "Season 01" / "Example.S01E01.mkv")
        table.assign(entry.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=0.5)
        state = ScanState(
            folder=folder,
            media_info=media_info,
            scanned=True,
            checked=False,
            confidence=1.0,
        )
        state.assignments = table
        state.preview_items = project_preview_items(
            table,
            show_info=media_info,
            root=folder,
            media_fields={"media_id": 101, "media_name": "Example Show"},
        )
        workspace = MediaWorkspace(media_type="tv", media_controller=_FakeMediaController(state))
        workspace.show()
        workspace.show_ready()
        self._app.processEvents()
        panel = workspace.findChild(MediaWorkPanel)
        assert panel is not None
        return _ReassignFixture(
            workspace=workspace,
            state=state,
            file_id=entry.file_id,
            panel=panel,
            button=_open_reassign_button(panel),
        )

    @staticmethod
    def _review_item(fixture: _ReassignFixture) -> PreviewItem:
        return next(item for item in fixture.state.preview_items if item.file_id == fixture.file_id)

    @staticmethod
    def _visible_row(fixture: _ReassignFixture):
        row = fixture.panel.model.row_for_preview_index(0)
        assert row >= 0
        data = fixture.panel.model.row_data_at(row)
        assert data is not None
        return data

    def test_media_workspace_reassign_does_not_mutate_when_dispatch_is_neutralized(self) -> None:
        fixture = self._reassign_fixture()

        with (
            patch.object(
                EpisodeAssignDialog,
                "pick_episodes",
                return_value=[(1, 2)],
            ) as pick,
            patch.object(
                EpisodeMappingService,
                "assign_file",
                autospec=True,
                return_value=None,
            ) as assign,
        ):
            fixture.button.click()
            self._app.processEvents()
        pick.assert_called_once()
        assign.assert_called_once()

        review_item = self._review_item(fixture)
        self.assertEqual(review_item.season, 1)
        self.assertEqual(review_item.episodes, [1])
        row = self._visible_row(fixture)
        self.assertIn("S01E01", row.title)
        self.assertNotIn("S01E02", row.title)
        self.assertIn("S01E01", row.target)
        self.assertNotIn("S01E02", row.target)

        fixture.workspace.close()

    def test_media_workspace_reassign_dispatches_refreshes_and_updates_visible_row(self) -> None:
        fixture = self._reassign_fixture()
        messages: list[tuple[str, int]] = []

        def record_status(text: str, timeout: int) -> None:
            messages.append((text, timeout))

        fixture.workspace.status_message.connect(record_status)
        with (
            patch.object(
                EpisodeAssignDialog,
                "pick_episodes",
                return_value=[(1, 2)],
            ) as pick,
            patch.object(
                EpisodeMappingService,
                "assign_file",
                autospec=True,
                wraps=EpisodeMappingService.assign_file,
            ) as assign,
        ):
            fixture.button.click()
            self._app.processEvents()
        pick.assert_called_once()
        assign.assert_called_once()

        review_item = self._review_item(fixture)
        self.assertEqual(review_item.season, 1)
        self.assertEqual(review_item.episodes, [2])
        self.assertIn(("Episode mapping updated.", 3000), messages)
        row = self._visible_row(fixture)
        self.assertIn("S01E02", row.title)
        self.assertNotIn("S01E01", row.title)
        self.assertIn("S01E02", row.target)
        self.assertNotIn("S01E01", row.target)

        fixture.workspace.close()
