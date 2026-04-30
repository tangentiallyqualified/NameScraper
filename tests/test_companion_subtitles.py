from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from plex_renamer.engine._movie_scanner import _build_subtitle_companions
from plex_renamer.parsing import find_companion_subtitles


class CompanionSubtitleTests(unittest.TestCase):
    def test_sup_mks_sidecar_pairs_with_matching_video_and_preserves_tags(self):
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            video = folder / "[Kawaiika-Raws] Bartender 03 [BDRip 1920x1080 HEVC FLAC].mkv"
            sidecar = folder / "[Kawaiika-Raws] Bartender 03 [BDRip 1920x1080 HEVC FLAC].eng.[BD].sup.mks"
            video.write_text("video")
            sidecar.write_text("subtitle")

            paired = find_companion_subtitles(video)

            self.assertEqual(paired, [(sidecar, ".eng.[BD].sup")])

    def test_sup_mks_rename_uses_video_target_stem_and_original_sidecar_suffix(self):
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            video = folder / "[Kawaiika-Raws] Bartender 03 [BDRip 1920x1080 HEVC FLAC].mkv"
            sidecar = folder / "[Kawaiika-Raws] Bartender 03 [BDRip 1920x1080 HEVC FLAC].eng.[BD].sup.mks"
            video.write_text("video")
            sidecar.write_text("subtitle")

            companions = _build_subtitle_companions(
                video,
                "Bartender (2006) - S01E03 - Glass of Regret.mkv",
            )

            self.assertEqual(len(companions), 1)
            self.assertEqual(companions[0].original, sidecar)
            self.assertEqual(
                companions[0].new_name,
                "Bartender (2006) - S01E03 - Glass of Regret.eng.[BD].sup.mks",
            )


if __name__ == "__main__":
    unittest.main()
