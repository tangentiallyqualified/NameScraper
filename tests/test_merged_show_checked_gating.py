"""RC47: merging duplicate-group siblings must not force-check the primary.

TV states are created unchecked (the GUI checks queue-approvable shows
explicitly); `reconcile_scanned_episode_claims` used to re-check merged
primaries whenever any item was actionable, so merged shows arrived
pre-checked even while sitting in Review Episodes.
"""
from pathlib import Path

from plex_renamer.engine._batch_tv_episode_claims import (
    reconcile_scanned_episode_claims,
)
from plex_renamer.engine.models import PreviewItem, ScanState


def _state(folder: str, checked: bool, items: list[PreviewItem]) -> ScanState:
    return ScanState(
        folder=Path(folder),
        media_info={"id": 539, "name": "Squidbillies"},
        preview_items=items,
        relative_folder=Path(folder).name,
        scanned=True,
        checked=checked,
    )


def _ok_item(name: str, season: int, episode: int) -> PreviewItem:
    return PreviewItem(
        original=Path(f"C:/lib/src/{name}"),
        new_name=f"Show - S{season:02d}E{episode:02d} - X.mkv",
        target_dir=Path("C:/lib/dst"),
        season=season,
        episodes=[episode],
        status="OK",
    )


def test_merged_primary_stays_unchecked_when_no_member_was_checked():
    primary = _state("C:/lib/a", False, [_ok_item("a.mkv", 1, 1)])
    sibling = _state("C:/lib/b", False, [_ok_item("b.mkv", 1, 2)])

    reconcile_scanned_episode_claims([primary, sibling], Path("C:/lib"))

    assert primary.checked is False


def test_merged_primary_keeps_a_member_check():
    primary = _state("C:/lib/a", False, [_ok_item("a.mkv", 1, 1)])
    sibling = _state("C:/lib/b", True, [_ok_item("b.mkv", 1, 2)])

    reconcile_scanned_episode_claims([primary, sibling], Path("C:/lib"))

    assert primary.checked is True
