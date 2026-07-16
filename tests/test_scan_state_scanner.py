from pathlib import Path
from typing import Any, Protocol, cast

import pytest

from plex_renamer.app.controllers._match_state_helpers import rematch_movie_scan_state
from plex_renamer.app.services.episode_mapping_service import EpisodeMappingService
from plex_renamer.app.services.episode_projection_cache import EpisodeProjectionCacheService
from plex_renamer.constants import MediaType
from plex_renamer.engine import CompletenessReport, MovieScanner, PreviewItem, ScanState
from plex_renamer.engine.episode_assignments import EpisodeAssignmentTable, EpisodeSlot
from plex_renamer.tmdb import TMDBClient


class _StructuralScanner:
    def __init__(self, marker: str) -> None:
        self.marker = marker
        self.show_info: dict[str, object] = {"id": 7, "name": "Show"}
        self.assignment_table: EpisodeAssignmentTable | None = None
        self.episode_meta: dict[tuple[int, int], dict[str, object]] = {
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
            total_matched=len(checked_indices or set[int]()),
            total_missing=[],
        )


class _LegacyMovieRematchScanner:
    def rematch_file(
        self,
        item: PreviewItem,
        chosen: dict[Any, Any],
    ) -> PreviewItem:
        return PreviewItem(
            original=item.original,
            new_name="Legacy Movie (2024).mkv",
            target_dir=item.original.parent / "Legacy Movie (2024)",
            season=None,
            episodes=[],
            status="OK",
            media_type=MediaType.MOVIE,
            media_id=42,
            media_name="Legacy Movie",
        )

    def get_search_results(self, file_path: Path) -> list[dict[Any, Any]]:
        return [{"id": 42, "title": "Legacy Movie", "year": "2024"}]


class _MovieScannerRunner(Protocol):
    def scan(self) -> list[PreviewItem]: ...


def test_movie_scanner_reads_explicit_files_through_its_public_capability() -> None:
    sample = Path("C:/library/sample.mkv")
    scanner = MovieScanner(cast(TMDBClient, object()), sample.parent, files=[sample])
    runner = cast(_MovieScannerRunner, scanner)

    items = runner.scan()

    assert [item.original for item in items] == [sample]
    assert items[0].status == "SKIP: release sample clip"


def test_movie_rematch_accepts_legacy_duck_typed_scanner() -> None:
    source = Path("C:/library/Legacy.Movie.2024.mkv")
    preview = PreviewItem(source, "Wrong.mkv", source.parent, None, [], "REVIEW: verify")
    scanner = _LegacyMovieRematchScanner()
    state = ScanState(source.parent, {"id": 1, "title": "Wrong"}, scanner, preview_items=[preview])

    def clean_folder_name(value: str) -> str:
        return value

    def extract_year(_value: str) -> None:
        return None

    def score_results(
        *_args: object,
        **_kwargs: object,
    ) -> list[tuple[dict[str, object], float]]:
        return []

    rematch_movie_scan_state(
        state,
        {"id": 42, "title": "Legacy Movie", "year": "2024"},
        movie_preview_items=[preview],
        movie_scanner=None,
        clean_folder_name=clean_folder_name,
        extract_year=extract_year,
        score_results=score_results,
    )

    assert state.preview_items[0].new_name == "Legacy Movie (2024).mkv"


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


def test_structural_scanner_metadata_populates_episode_guide() -> None:
    scanner = _StructuralScanner("guide")
    item = PreviewItem(
        original=Path("C:/library/Show/episode.mkv"),
        new_name="Show - S01E01.mkv",
        target_dir=Path("C:/library/Show/Season 01"),
        season=1,
        episodes=[1],
        status="OK",
    )
    state = ScanState(
        folder=Path("C:/library/Show"),
        media_info={"id": 7, "name": "Show"},
        scanner=scanner,
        preview_items=[item],
    )

    guide = EpisodeMappingService().build_episode_guide(state)

    assert guide.rows[0].title == "guide title"
    assert guide.rows[0].air_date == "2024-01-01"
