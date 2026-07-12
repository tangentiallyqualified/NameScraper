"""Action-label and eligibility helpers for the media workspace."""

from __future__ import annotations

from ...engine import ScanState


def media_noun(workspace) -> str:
    return "movie" if workspace._media_type == "movie" else "show"


def queue_selected_label(workspace) -> str:
    return f"Queue This {'Movie' if workspace._media_type == 'movie' else 'Show'}"


def primary_action_label(workspace, state: ScanState | None) -> str:
    if state is not None and can_inline_assign_season(workspace, state):
        return "Assign Season"
    if state is not None and needs_inline_match_choice(state):
        return "Choose Match"
    if state is not None and can_inline_approve(state):
        return "Approve Match"
    return queue_selected_label(workspace)


def fix_match_label(_workspace, state: ScanState | None) -> str:
    del state
    return "Fix Match"


def fix_match_tone(state: ScanState | None) -> str:
    if state is not None and (state.needs_review or state.tie_detected):
        return "caution"
    return "secondary"


def needs_inline_match_choice(state: ScanState) -> bool:
    return (
        state.show_id is not None
        and state.tie_detected
        and state.needs_review
        and not state.queued
        and not state.scanning
        and state.duplicate_of is None
    )


def can_inline_assign_season(workspace, state: ScanState) -> bool:
    return (
        workspace._media_type == "tv"
        and state.show_id is not None
        and state.duplicate_of is not None
        and state.season_assignment is None
        and not state.queued
        and not state.scanning
    )


def can_inline_approve(state: ScanState) -> bool:
    return (
        state.show_id is not None
        and state.needs_review
        and not state.tie_detected
        and not state.queued
        and not state.scanning
        and state.duplicate_of is None
    )


def can_fix_match(state: ScanState) -> bool:
    return not state.queued and not state.scanning


def can_unassign_all(state: ScanState | None) -> bool:
    """True when the selected show has at least one assigned file to clear."""
    if state is None or state.queued or state.scanning:
        return False
    table = state.assignments
    if table is None:
        return False
    return any(
        preview.file_id is not None
        and table.assignment_for(preview.file_id) is not None
        for preview in state.preview_items
    )
