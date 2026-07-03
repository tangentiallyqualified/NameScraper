"""RC39: conflicts hard-block queueing; conflict rows are numbered pairs."""
from pathlib import Path

from plex_renamer.app.models import QueueCommandState
from plex_renamer.app.services.command_gating_service import CommandGatingService
from plex_renamer.app.services.episode_mapping_service import EpisodeMappingService
from plex_renamer.engine import ScanState
from plex_renamer.engine._episode_projection import project_preview_items
from plex_renamer.engine.episode_assignments import (
    ORIGIN_AUTO,
    EpisodeAssignmentTable,
    EpisodeSlot,
)

ROOT = Path("C:/lib/Demo Show (2020)")
SHOW = {"id": 9, "name": "Demo Show", "year": "2020"}


def _conflicted_state() -> ScanState:
    table = EpisodeAssignmentTable()
    for episode in range(1, 4):
        table.add_slot(EpisodeSlot(season=0, episode=episode, title=f"Special {episode}"))
    color = table.add_file(ROOT / "Short (Color).mkv")
    pencil = table.add_file(ROOT / "Short (Pencil).mkv")
    other = table.add_file(ROOT / "e2.mkv")
    table.assign(color.file_id, 0, [1], origin=ORIGIN_AUTO, confidence=0.5)
    table.assign(pencil.file_id, 0, [1], origin=ORIGIN_AUTO, confidence=0.5)
    table.assign(other.file_id, 0, [2], origin=ORIGIN_AUTO, confidence=1.0)
    state = ScanState(folder=ROOT, media_info=SHOW)
    state.scanned = True
    state.confidence = 1.0
    state.assignments = table
    state.preview_items = project_preview_items(
        table, show_info=SHOW, root=ROOT,
        media_fields={"media_id": 9, "media_name": "Demo Show"},
    )
    return state


def test_conflict_blocks_queue_even_with_actionable_selection():
    state = _conflicted_state()
    state.checked = True
    result = CommandGatingService().evaluate_scan_state(
        state, require_resolved_review=True, allow_show_level_queue=True,
    )
    assert not result.enabled
    assert result.command_state == QueueCommandState.DISABLED_CONFLICT


def test_conflict_rows_numbered_as_one_contested_episode():
    state = _conflicted_state()
    guide = EpisodeMappingService().build_episode_guide(state)
    conflict_rows = [row for row in guide.rows if row.status == "Conflict"]
    assert len(conflict_rows) == 2
    labels = {row.confidence_label for row in conflict_rows}
    assert labels == {"Conflict — file 1 of 2", "Conflict — file 2 of 2"}
