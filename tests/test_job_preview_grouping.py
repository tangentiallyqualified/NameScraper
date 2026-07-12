# tests/test_job_preview_grouping.py
"""Companion↔video pairing for the job detail tree (Plan 7, spec §11/§13)."""
import unittest

from plex_renamer.job_store import RenameJob, RenameOp


def _video(stem: str, target_dir: str = "Show/Season 01") -> RenameOp:
    return RenameOp(
        original_relative=f"Show/{stem}.mkv",
        new_name=f"{stem}.mkv",
        target_dir_relative=target_dir,
        status="OK",
        file_type="video",
    )


def _subtitle(name: str, target_dir: str = "Show/Season 01") -> RenameOp:
    return RenameOp(
        original_relative=f"Show/{name}",
        new_name=name,
        target_dir_relative=target_dir,
        status="OK",
        file_type="subtitle",
    )


class PairCompanionsTests(unittest.TestCase):
    def test_companion_pairs_with_stem_prefix_video_in_same_dir(self):
        from plex_renamer.gui_qt.widgets._job_detail_preview import (
            pair_companions_with_videos,
        )

        video = _video("Show - S01E01 - Pilot")
        sub = _subtitle("Show - S01E01 - Pilot.eng.srt")
        paired, unpaired = pair_companions_with_videos([video], [sub])
        self.assertEqual(paired, {id(video): [sub]})
        self.assertEqual(unpaired, [])

    def test_longest_stem_wins_when_one_title_prefixes_another(self):
        from plex_renamer.gui_qt.widgets._job_detail_preview import (
            pair_companions_with_videos,
        )

        short = _video("Show - S01E01 - Part")
        long = _video("Show - S01E01 - Part Two")
        sub = _subtitle("Show - S01E01 - Part Two.eng.srt")
        paired, unpaired = pair_companions_with_videos([short, long], [sub])
        self.assertEqual(paired, {id(long): [sub]})
        self.assertEqual(unpaired, [])

    def test_dir_mismatch_and_no_prefix_stay_unpaired(self):
        from plex_renamer.gui_qt.widgets._job_detail_preview import (
            pair_companions_with_videos,
        )

        video = _video("Show - S01E01 - Pilot")
        other_dir = _subtitle("Show - S01E01 - Pilot.eng.srt", target_dir="Show/Season 02")
        no_prefix = _subtitle("Totally Different.eng.srt")
        paired, unpaired = pair_companions_with_videos([video], [other_dir, no_prefix])
        self.assertEqual(paired, {})
        self.assertEqual(unpaired, [other_dir, no_prefix])

    def test_type_badge_names(self):
        from plex_renamer.gui_qt.widgets._job_detail_preview import type_badge

        self.assertEqual(type_badge("subtitle"), "SUB")
        self.assertEqual(type_badge("nfo"), "NFO")


class PreviewEntriesGroupingTests(unittest.TestCase):
    def _job(self, ops) -> RenameJob:
        return RenameJob(
            library_root="C:/library",
            source_folder="Show",
            media_name="Example Show",
            media_type="tv",
            rename_ops=ops,
        )

    def test_video_rows_carry_companion_children_with_badges(self):
        from plex_renamer.gui_qt.widgets._job_detail_preview import (
            JobPreviewGroup,
            build_job_preview_entries,
        )

        video = _video("Show - S01E01 - Pilot")
        video.season = 1
        sub = _subtitle("Show - S01E01 - Pilot.eng.srt")
        entries = build_job_preview_entries(self._job([video, sub]))
        season_groups = [
            e for e in entries
            if isinstance(e, JobPreviewGroup) and e.label.startswith("Season")
        ]
        self.assertEqual(len(season_groups), 1)
        video_row = season_groups[0].rows[0]
        self.assertEqual(len(video_row.children), 1)
        self.assertEqual(video_row.children[0].badge, "SUB")
        self.assertEqual(video_row.children[0].after, "Show - S01E01 - Pilot.eng.srt")
        # Paired companions do NOT also appear in a flat residual group.
        self.assertFalse(
            any(
                isinstance(e, JobPreviewGroup) and e.label.startswith("Companion Files")
                for e in entries
            )
        )

    def test_unpaired_companions_keep_the_residual_group(self):
        from plex_renamer.gui_qt.widgets._job_detail_preview import (
            JobPreviewGroup,
            build_job_preview_entries,
        )

        video = _video("Show - S01E01 - Pilot")
        video.season = 1
        orphan = _subtitle("Unrelated Name.eng.srt")
        entries = build_job_preview_entries(self._job([video, orphan]))
        residual = [
            e for e in entries
            if isinstance(e, JobPreviewGroup) and e.label == "Companion Files (1)"
        ]
        self.assertEqual(len(residual), 1)
        self.assertEqual(residual[0].rows[0].badge, "SUB")

    def test_movie_rows_carry_children_too(self):
        from plex_renamer.gui_qt.widgets._job_detail_preview import (
            JobPreviewGroup,
            build_job_preview_entries,
        )

        video = _video("Movie (2021)", target_dir="Movie (2021)")
        sub = _subtitle("Movie (2021).eng.srt", target_dir="Movie (2021)")
        job = self._job([video, sub])
        job.media_type = "movie"
        entries = build_job_preview_entries(job)
        file_groups = [
            e for e in entries
            if isinstance(e, JobPreviewGroup) and e.label == "File Rename"
        ]
        self.assertEqual(len(file_groups), 1)
        self.assertEqual(len(file_groups[0].rows[0].children), 1)

    def test_single_file_season_group_label_is_singular(self):
        from plex_renamer.gui_qt.widgets._job_detail_preview import (
            JobPreviewGroup,
            build_job_preview_entries,
        )

        video = _video("Show - S01E01 - Pilot")
        video.season = 1
        entries = build_job_preview_entries(self._job([video]))
        labels = [e.label for e in entries if isinstance(e, JobPreviewGroup)]
        self.assertIn("Season 01 (1 file)", labels)
        self.assertNotIn("Season 01 (1 files)", labels)


if __name__ == "__main__":
    unittest.main()
