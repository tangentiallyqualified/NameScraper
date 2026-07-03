"""Blue Submarine No. 6 flow: manually mapping one file to ALL episodes must
leave the show queueable even though its sibling files stay unmapped.

The user assigned the 4-in-1 movie file to S01E01-E04; the three Toonami
promo files remain unmapped primaries, and previously that blocked every
queue path with a fix-match prompt despite a 100% show match.
"""
from pathlib import Path

from plex_renamer.app.models import QueueCommandState
from plex_renamer.app.services.command_gating_service import CommandGatingService
from plex_renamer.app.services.episode_mapping_service import EpisodeMappingService
from plex_renamer.engine import ScanState
from plex_renamer.engine.episode_assignments import (
    EpisodeAssignmentTable,
    EpisodeSlot,
)
from plex_renamer.gui_qt.widgets._media_helpers import (
    is_state_queue_approvable,
    roster_group,
)

ROOT = Path("C:/lib/Blue Submarine No. 6 (1998)")
SHOW = {"id": 30431, "name": "Blue Submarine No. 6", "year": "1998"}
TITLES = {1: "Blues", 2: "Pilots", 3: "Hearts", 4: "Minasoko"}


def _blue_submarine_state() -> tuple[ScanState, int]:
    table = EpisodeAssignmentTable()
    for episode, title in TITLES.items():
        table.add_slot(EpisodeSlot(season=1, episode=episode, title=title))
    names = ("movie.mkv", "promo15.mkv", "promo30.mkv", "promo60.mkv")
    file_ids = []
    for name in names:
        entry = table.add_file(
            ROOT / name,
            parsed_episodes=(),
            raw_title=None,
            is_season_relative=False,
            season_hint=None,
            folder_season=1,
        )
        table.mark_unassigned(entry.file_id, "no TMDB title match")
        file_ids.append(entry.file_id)
    state = ScanState(folder=ROOT, media_info=SHOW)
    state.scanned = True
    state.confidence = 1.0
    state.assignments = table
    EpisodeMappingService().reproject(state)
    return state, file_ids[0]


def test_manual_four_episode_assignment_makes_show_queueable():
    state, movie_id = _blue_submarine_state()
    service = EpisodeMappingService()
    preview = next(
        item for item in state.preview_items if item.file_id == movie_id
    )

    service.assign_file(state, preview, season=1, episodes=[1, 2, 3, 4])

    # Roster checkbox / "Queue This Show" must be available…
    assert is_state_queue_approvable(state, media_type="tv") is True
    # …and the command-gating layer must agree once the show is checked.
    state.checked = True
    result = CommandGatingService().evaluate_scan_state(
        state, require_resolved_review=True, allow_show_level_queue=True,
    )
    assert result.enabled
    assert result.command_state == QueueCommandState.ENABLED
    # The three promos stay visible as unmapped primaries (routing only).
    assert roster_group(state, media_type="tv") == "review-episodes"


def test_unassigned_only_show_is_not_queueable():
    # Before any manual mapping there is nothing actionable — the show must
    # not queue an empty job.
    state, _movie_id = _blue_submarine_state()
    assert is_state_queue_approvable(state, media_type="tv") is False
