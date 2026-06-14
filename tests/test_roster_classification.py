from __future__ import annotations

from pathlib import Path

from plex_renamer.engine import ScanState
from plex_renamer.engine._episode_projection import project_preview_items
from plex_renamer.engine.episode_assignments import (
    ORIGIN_AUTO,
    EpisodeAssignmentTable,
    EpisodeSlot,
)
from plex_renamer.gui_qt.widgets._media_helpers import (
    has_episode_problems,
    is_state_queue_approvable,
    roster_group,
)

ROOT = Path("C:/lib/Demo Show (2020)")
SHOW = {"id": 9, "name": "Demo Show", "year": "2020"}


def _state(table: EpisodeAssignmentTable, *, needs_review: bool = False) -> ScanState:
    # ``show_id`` and ``needs_review`` are read-only properties on ScanState,
    # derived from ``media_info`` / ``confidence`` / ``tie_detected``. SHOW
    # already supplies the id; a high confidence makes the show-match settled
    # (needs_review False), and ``tie_detected`` forces it True when requested.
    state = ScanState(folder=ROOT, media_info=SHOW)
    state.scanned = True
    state.confidence = 1.0
    if needs_review:
        state.tie_detected = True
    state.assignments = table
    state.preview_items = project_preview_items(
        table, show_info=SHOW, root=ROOT,
        media_fields={"media_id": 9, "media_name": "Demo Show"},
    )
    return state


def _table(count: int = 3) -> EpisodeAssignmentTable:
    table = EpisodeAssignmentTable()
    for episode in range(1, count + 1):
        table.add_slot(EpisodeSlot(season=1, episode=episode, title=f"Ep {episode}"))
    return table


def test_conflict_routes_to_review_episodes():
    table = _table()
    a = table.add_file(ROOT / "a.mkv")
    b = table.add_file(ROOT / "b.mkv")
    table.assign(a.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=1.0)
    table.assign(b.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=1.0)
    state = _state(table)
    assert has_episode_problems(state) is True
    assert roster_group(state, media_type="tv") == "review-episodes"


def test_unmapped_primary_routes_to_review_episodes():
    table = _table()
    ok = table.add_file(ROOT / "ok.mkv")
    table.assign(ok.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=1.0)
    stray = table.add_file(ROOT / "stray.mkv")
    table.mark_unassigned(stray.file_id, "could not parse episode number")
    state = _state(table)
    assert roster_group(state, media_type="tv") == "review-episodes"


def test_needs_review_wins_over_episode_problems():
    table = _table()
    a = table.add_file(ROOT / "a.mkv")
    b = table.add_file(ROOT / "b.mkv")
    table.assign(a.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=1.0)
    table.assign(b.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=1.0)
    state = _state(table, needs_review=True)
    assert roster_group(state, media_type="tv") == "review-match"


def test_clean_show_is_not_a_review_bucket():
    table = _table()
    for episode in range(1, 4):
        entry = table.add_file(ROOT / f"e{episode}.mkv")
        table.assign(entry.file_id, 1, [episode], origin=ORIGIN_AUTO, confidence=1.0)
    state = _state(table)
    assert has_episode_problems(state) is False
    assert roster_group(state, media_type="tv") not in {"review-match", "review-episodes"}


def test_conflict_with_other_mapped_files_is_not_queue_approvable():
    # The checkbox (is_state_queue_approvable) must agree with the section
    # header (roster_group): a conflict keeps the show out of the approvable
    # set even though other files are cleanly mapped and actionable.
    table = _table(count=3)
    e2 = table.add_file(ROOT / "e2.mkv")
    table.assign(e2.file_id, 1, [2], origin=ORIGIN_AUTO, confidence=1.0)
    e3 = table.add_file(ROOT / "e3.mkv")
    table.assign(e3.file_id, 1, [3], origin=ORIGIN_AUTO, confidence=1.0)
    a = table.add_file(ROOT / "a.mkv")
    b = table.add_file(ROOT / "b.mkv")
    table.assign(a.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=1.0)
    table.assign(b.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=1.0)
    state = _state(table)
    assert roster_group(state, media_type="tv") == "review-episodes"
    assert any(item.is_actionable for item in state.preview_items)
    assert is_state_queue_approvable(state, media_type="tv") is False


def test_unmapped_primary_with_mapped_file_is_not_queue_approvable():
    table = _table(count=2)
    ok = table.add_file(ROOT / "ok.mkv")
    table.assign(ok.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=1.0)
    stray = table.add_file(ROOT / "stray.mkv")
    table.mark_unassigned(stray.file_id, "could not parse episode number")
    state = _state(table)
    assert roster_group(state, media_type="tv") == "review-episodes"
    assert any(item.is_actionable for item in state.preview_items)
    assert is_state_queue_approvable(state, media_type="tv") is False


def test_clean_show_is_queue_approvable():
    table = _table()
    for episode in range(1, 4):
        entry = table.add_file(ROOT / f"e{episode}.mkv")
        table.assign(entry.file_id, 1, [episode], origin=ORIGIN_AUTO, confidence=1.0)
    state = _state(table)
    assert has_episode_problems(state) is False
    assert is_state_queue_approvable(state, media_type="tv") is True
