from __future__ import annotations

import unittest
from pathlib import Path

from plex_renamer.app.services.episode_mapping_service import EpisodeMappingService
from plex_renamer.engine import (
    CompanionFile,
    CompletenessReport,
    PreviewItem,
    ScanState,
    SeasonCompleteness,
)


def _preview(
    name: str,
    *,
    new_name: str | None = None,
    season: int | None = 1,
    episodes: list[int] | None = None,
    status: str = "OK",
    companions: list[CompanionFile] | None = None,
) -> PreviewItem:
    return PreviewItem(
        original=Path(f"C:/library/tv/Show/Season 01/{name}"),
        new_name=new_name or f"Show (2024) - S01E01 - Pilot{name[-4:]}",
        target_dir=Path("C:/library/tv/Show (2024)/Season 01"),
        season=season,
        episodes=episodes if episodes is not None else [1],
        status=status,
        companions=companions or [],
    )


class EpisodeMappingProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = EpisodeMappingService()

    def test_episode_guide_groups_companions_under_mapped_episode(self):
        subtitle = CompanionFile(
            original=Path("C:/library/tv/Show/Season 01/Show.S01E01.en.srt"),
            new_name="Show (2024) - S01E01 - Pilot.en.srt",
            file_type="subtitle",
        )
        item = _preview("Show.S01E01.mkv", companions=[subtitle])
        completeness = CompletenessReport(
            seasons={
                1: SeasonCompleteness(
                    season=1,
                    expected=2,
                    matched=1,
                    missing=[(2, "Second")],
                    matched_episodes=[(1, "Pilot")],
                )
            },
            specials=None,
            total_expected=2,
            total_matched=1,
            total_missing=[(1, 2, "Second")],
        )
        state = ScanState(
            folder=Path("C:/library/tv/Show"),
            media_info={"id": 10, "name": "Show", "year": "2024"},
            preview_items=[item],
            completeness=completeness,
            scanned=True,
        )

        guide = self.service.build_episode_guide(state)

        self.assertEqual(guide.source_label, "TMDB")
        self.assertEqual(guide.summary.mapped_episodes, 1)
        self.assertEqual(guide.summary.companion_files, 1)
        self.assertEqual(guide.summary.missing_episodes, 1)
        self.assertEqual(len(guide.rows), 2)
        mapped = guide.rows[0]
        self.assertEqual(mapped.status, "Mapped")
        self.assertEqual(mapped.episode_key, (1, 1))
        self.assertEqual(mapped.companions, [subtitle])
        self.assertEqual(mapped.target_rename, "Show (2024) - S01E01 - Pilot.mkv")
        missing = guide.rows[1]
        self.assertEqual(missing.status, "Missing File")
        self.assertEqual(missing.episode_key, (1, 2))
        self.assertIsNone(missing.primary_file)

    def test_unmapped_primary_files_and_orphan_companions_are_separate(self):
        orphan = CompanionFile(
            original=Path("C:/library/tv/Show/Season 01/Show.S01E99.en.srt"),
            new_name="",
            file_type="subtitle",
        )
        state = ScanState(
            folder=Path("C:/library/tv/Show"),
            media_info={"id": 10, "name": "Show", "year": "2024"},
            preview_items=[
                _preview(
                    "Show.Unknown.mkv",
                    new_name=None,
                    season=None,
                    episodes=[],
                    status="SKIP: no episode mapping",
                )
            ],
            orphan_companion_files=[orphan],
            scanned=True,
        )

        guide = self.service.build_episode_guide(state)

        self.assertEqual(guide.summary.unmapped_primary_files, 1)
        self.assertEqual(guide.summary.orphan_companion_files, 1)
        self.assertEqual(guide.unmapped_primary_files[0].reason, "SKIP: no episode mapping")
        self.assertEqual(guide.orphan_companion_files, [orphan])

    def test_queue_preflight_counts_companions_and_conflicts(self):
        subtitle = CompanionFile(
            original=Path("C:/library/tv/Show/Season 01/Show.S01E01.en.srt"),
            new_name="Show (2024) - S01E01 - Pilot.en.srt",
            file_type="subtitle",
        )
        conflict = _preview(
            "Show.S01E02.mkv",
            new_name="Show (2024) - S01E02 - Second.mkv",
            episodes=[2],
            status="CONFLICT: target exists",
        )
        state = ScanState(
            folder=Path("C:/library/tv/Show"),
            media_info={"id": 10, "name": "Show", "year": "2024"},
            preview_items=[_preview("Show.S01E01.mkv", companions=[subtitle]), conflict],
            scanned=True,
            checked=True,
        )

        preflight = self.service.build_queue_preflight(state)

        self.assertFalse(preflight.enabled)
        self.assertEqual(preflight.mapped_primary_files, 1)
        self.assertEqual(preflight.companion_files, 1)
        self.assertEqual(preflight.conflicts, 1)
        self.assertIn("1 companion", preflight.summary_text)
        self.assertIn("1 conflict", preflight.summary_text)

    def test_queue_preflight_blocks_review_required_episode_mappings(self):
        review_item = _preview(
            "Show.S01E01.mkv",
            status="REVIEW: episode confidence below threshold",
        )
        state = ScanState(
            folder=Path("C:/library/tv/Show"),
            media_info={"id": 10, "name": "Show", "year": "2024"},
            preview_items=[review_item],
            scanned=True,
            checked=True,
        )

        preflight = self.service.build_queue_preflight(state)

        self.assertFalse(preflight.enabled)
        self.assertEqual(preflight.mapped_primary_files, 0)
        self.assertEqual(preflight.review_required, 1)
        self.assertIn("1 review", preflight.summary_text)

    def test_remap_preview_item_to_selected_episode_recomputes_name_and_companions(self):
        companion = CompanionFile(
            original=Path("C:/library/tv/Show/Season 01/Show.S01E01.eng.sup.mks"),
            new_name="Show (2024) - S01E01 - Pilot.eng.sup.mks",
            file_type="subtitle",
        )
        review_item = _preview(
            "Show.S01E01.mkv",
            status="REVIEW: episode confidence below threshold",
            companions=[companion],
        )
        state = ScanState(
            folder=Path("C:/library/tv/Show"),
            media_info={"id": 10, "name": "Show", "year": "2024"},
            scanner=type(
                "Scanner",
                (),
                {"episode_meta": {(1, 1): {"name": "Pilot"}, (1, 2): {"name": "Second"}}},
            )(),
            preview_items=[review_item],
            completeness=CompletenessReport(
                seasons={
                    1: SeasonCompleteness(
                        season=1,
                        expected=2,
                        matched=1,
                        missing=[(2, "Second")],
                        matched_episodes=[(1, "Pilot")],
                    )
                },
                specials=None,
                total_expected=2,
                total_matched=1,
                total_missing=[(1, 2, "Second")],
            ),
            scanned=True,
        )

        self.service.remap_preview_to_episode(state, review_item, season=1, episode=2)

        self.assertEqual(review_item.status, "OK")
        self.assertEqual(review_item.season, 1)
        self.assertEqual(review_item.episodes, [2])
        self.assertEqual(review_item.episode_confidence, 1.0)
        self.assertEqual(review_item.new_name, "Show (2024) - S01E02 - Second.mkv")
        self.assertEqual(
            companion.new_name,
            "Show (2024) - S01E02 - Second.eng.sup.mks",
        )
        guide = self.service.build_episode_guide(state)
        mapped_rows = [row for row in guide.rows if row.primary_file is review_item]
        self.assertEqual([row.episode_key for row in mapped_rows], [(1, 2)])
        preflight = self.service.build_queue_preflight(state)
        self.assertTrue(preflight.enabled)
        self.assertEqual(preflight.review_required, 0)


if __name__ == "__main__":
    unittest.main()
