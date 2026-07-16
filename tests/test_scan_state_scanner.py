from pathlib import Path

import pytest

from plex_renamer.app.services.episode_mapping_service import EpisodeMappingService
from plex_renamer.app.services.episode_projection_cache import EpisodeProjectionCacheService
from plex_renamer.engine import CompletenessReport, PreviewItem, ScanState
from plex_renamer.engine.episode_assignments import EpisodeAssignmentTable, EpisodeSlot


class _StructuralScanner:
    def __init__(self, marker: str) -> None:
        self.marker = marker
        self.show_info: dict[str, object] = {"id": 7, "name": "Show"}
        self.assignment_table: EpisodeAssignmentTable | None = None
        self.episode_meta = {
            (1, 1): {"name": f"{marker} title", "air_date": "2024-01-01"},
        }
        self.completeness_calls: list[tuple[list[PreviewItem], set[int] | None]] = []

    def scan(self) -> tuple[list[PreviewItem], bool]:
        return [], False

    def scan_consolidated(self) -> list[PreviewItem]:
        return []

    def get_completeness(
        self,
        items: list[PreviewItem],
        checked_indices: set[int] | None = None,
    ) -> CompletenessReport:
        self.completeness_calls.append((items, checked_indices))
        return CompletenessReport(
            seasons={},
            specials=None,
            total_expected=1,
            total_matched=len(checked_indices or set()),
            total_missing=[],
        )


@pytest.mark.parametrize("marker", ["initial", "replacement"])
def test_scan_state_preserves_structural_scanner_identity(marker: str) -> None:
    scanner = _StructuralScanner(marker)

    state = ScanState(
        folder=Path("C:/library/Show"),
        media_info={"id": 7, "name": "Show"},
        scanner=scanner,
    )

    assert state.scanner is scanner


def test_scan_state_scanner_can_be_replaced_and_cleared() -> None:
    initial = _StructuralScanner("initial")
    replacement = _StructuralScanner("replacement")
    state = ScanState(
        folder=Path("C:/library/Show"),
        media_info={"id": 7, "name": "Show"},
        scanner=initial,
    )

    state.scanner = replacement
    assert state.scanner is replacement

    state.reset_scan()
    assert state.scanner is None


def test_structural_scanner_drives_reprojection_completeness() -> None:
    scanner = _StructuralScanner("consumer")
    table = EpisodeAssignmentTable()
    table.add_slot(EpisodeSlot(season=1, episode=1, title="Episode One"))
    state = ScanState(
        folder=Path("C:/library/Show"),
        media_info={"id": 7, "name": "Show"},
        scanner=scanner,
        assignments=table,
    )

    EpisodeMappingService().reproject(state)

    assert scanner.completeness_calls == [([], set())]
    assert state.completeness is not None
    assert state.completeness.total_expected == 1


def test_structural_scanner_episode_metadata_participates_in_cache_signature() -> None:
    scanner = _StructuralScanner("before")
    state = ScanState(
        folder=Path("C:/library/Show"),
        media_info={"id": 7, "name": "Show"},
        scanner=scanner,
    )
    cache = EpisodeProjectionCacheService(EpisodeMappingService())
    before = cache.signature_for_state(state)

    scanner.episode_meta[(1, 1)]["name"] = "after title"

    assert cache.signature_for_state(state) != before
