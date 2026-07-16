from __future__ import annotations

from collections.abc import Callable, Mapping
from operator import attrgetter
from pathlib import Path
from typing import cast

from plex_renamer.app.services import episode_mapping_service
from plex_renamer.app.services.episode_mapping_service import EpisodeMappingService
from plex_renamer.engine import CompletenessReport, PreviewItem, ScanState, SeasonCompleteness
from plex_renamer.engine.models import TVScanStateScanner


class _MetadataScanner:
    @property
    def episode_meta(self) -> Mapping[tuple[int, int], Mapping[str, object]]:
        return {
            (1, 1): {
                "name": "Scanner Pilot",
                "overview": "Scanner overview",
                "air_date": "2024-01-02",
            }
        }


def test_episode_metadata_lookup_remains_owned_by_mapping_service() -> None:
    root = Path("C:/library/tv/Show")
    completeness = CompletenessReport(
        seasons={
            1: SeasonCompleteness(
                season=1,
                expected=1,
                matched=1,
                missing=[],
                matched_episodes=[(1, "Completeness Pilot")],
            )
        },
        specials=None,
        total_expected=1,
        total_matched=1,
        total_missing=[],
    )
    preview = PreviewItem(
        original=root / "Season 01" / "Show.S01E01.mkv",
        new_name="Show (2024) - S01E01 - Pilot.mkv",
        target_dir=root,
        season=1,
        episodes=[1],
        status="OK",
    )
    state = ScanState(
        folder=root,
        media_info={"id": 10, "name": "Show", "year": "2024"},
        scanner=cast(TVScanStateScanner, _MetadataScanner()),
        preview_items=[preview],
        completeness=completeness,
        scanned=True,
    )

    guide = EpisodeMappingService().build_episode_guide(state)
    episode_title = cast(
        Callable[[ScanState, tuple[int, int]], str],
        attrgetter("_episode_title")(EpisodeMappingService),
    )

    assert guide.rows[0].title == "Scanner Pilot"
    assert guide.rows[0].overview == "Scanner overview"
    assert guide.rows[0].air_date == "2024-01-02"
    assert episode_title.__module__ == episode_mapping_service.__name__


def test_episode_title_is_empty_when_completeness_has_no_matching_season() -> None:
    preview = PreviewItem(
        original=Path("C:/library/tv/Show/Season 02/Show.S02E01.mkv"),
        new_name="Show (2024) - S02E01.mkv",
        target_dir=Path("C:/library/tv/Show"),
        season=2,
        episodes=[1],
        status="OK",
    )
    state = ScanState(
        folder=Path("C:/library/tv/Show"),
        media_info={"id": 10, "name": "Show", "year": "2024"},
        scanner=cast(TVScanStateScanner, _MetadataScanner()),
        preview_items=[preview],
        completeness=CompletenessReport(
            seasons={},
            specials=None,
            total_expected=0,
            total_matched=0,
            total_missing=[],
        ),
        scanned=True,
    )

    guide = EpisodeMappingService().build_episode_guide(state)

    assert guide.rows[0].title == ""
