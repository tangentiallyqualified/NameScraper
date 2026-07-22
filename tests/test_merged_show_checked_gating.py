"""RC47: merging duplicate-group siblings must not force-check the primary.

TV states are created unchecked (the GUI checks queue-approvable shows
explicitly); `reconcile_scanned_episode_claims` used to re-check merged
primaries whenever any item was actionable, so merged shows arrived
pre-checked even while sitting in Review Episodes.
"""

from pathlib import Path

import pytest

from plex_renamer.app.services import TVLibraryDiscoveryService
from plex_renamer.engine._batch_orchestrators import BatchTVOrchestrator
from plex_renamer.engine._batch_tv_episode_claims import (
    reconcile_scanned_episode_claims,
)
from plex_renamer.engine.models import PreviewItem, ScanState
from plex_renamer.providers import SeasonMapUnavailableError


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


@pytest.mark.parametrize(
    ("error", "expected_scan_error"),
    [
        (
            SeasonMapUnavailableError("tmdb season map unavailable for 539"),
            "Episode guide is unavailable; retry the provider scan.",
        ),
        (RuntimeError("merged scanner exploded"), "merged scanner exploded"),
    ],
)
def test_merged_rescan_failure_fails_closed(
    tmp_path: Path,
    error: Exception,
    expected_scan_error: str,
) -> None:
    class _Provider:
        provider_name = "tmdb"

    season_one = _state(str(tmp_path / "Show S01"), True, [_ok_item("a.mkv", 1, 1)])
    season_two = _state(str(tmp_path / "Show S02"), True, [_ok_item("b.mkv", 2, 1)])
    season_one.folder.mkdir()
    season_two.folder.mkdir()
    orchestrator = BatchTVOrchestrator(
        _Provider(),  # type: ignore[arg-type]
        tmp_path,
        discovery_service=TVLibraryDiscoveryService(),
    )
    orchestrator.states = [season_one, season_two]
    attempted: list[ScanState] = []

    def _fail_scan(state: ScanState, **_kwargs: object) -> None:
        attempted.append(state)
        raise error

    orchestrator.scan_show = _fail_scan  # type: ignore[method-assign]

    orchestrator._reconcile_scanned_siblings()

    assert attempted
    failed_state = attempted[-1]
    assert failed_state in orchestrator.states
    assert failed_state.scan_error == expected_scan_error
    assert failed_state.preview_items == []
    assert failed_state.scanned is False
    assert failed_state.checked is False
