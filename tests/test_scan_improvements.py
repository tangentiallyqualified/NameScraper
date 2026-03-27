from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from plex_renamer.app.services import TVLibraryDiscoveryService
from plex_renamer.engine import BatchTVOrchestrator
from plex_renamer.job_executor import revert_job
from plex_renamer.job_store import RenameJob


class _FakeTMDB:
    language = "en-US"

    def search_tv_batch(self, queries, progress_callback=None):
        results = []
        total = len(queries)
        for index, (_name, _year) in enumerate(queries, start=1):
            if progress_callback:
                progress_callback(index, total)
            results.append([
                {
                    "id": 100,
                    "name": "Naruto",
                    "year": "2002",
                    "poster_path": None,
                    "overview": "",
                    "number_of_seasons": 1,
                    "number_of_episodes": 220,
                }
            ])
        return results

    def get_alternative_titles(self, media_id, media_type="tv"):
        return []


class ScanImprovementTests(unittest.TestCase):
    def test_nested_discovery_finds_show_roots_but_not_containers_or_movies(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Anime" / "Naruto" / "Season 01").mkdir(parents=True)
            (root / "Anime" / "Naruto" / "Season 01" / "Naruto - S01E01.mkv").write_text("x")
            (root / "Sci-Fi" / "Battlestar Galactica (2004)" / "Season 01").mkdir(parents=True)
            (
                root
                / "Sci-Fi"
                / "Battlestar Galactica (2004)"
                / "Season 01"
                / "Battlestar Galactica - S01E01.mkv"
            ).write_text("x")
            (root / "Movies" / "Inception (2010)").mkdir(parents=True)
            (root / "Movies" / "Inception (2010)" / "Inception.2010.1080p.mkv").write_text("x")

            service = TVLibraryDiscoveryService()
            candidates = service.discover_show_roots(root)
            relative_paths = {candidate.relative_folder for candidate in candidates}

            self.assertEqual(
                relative_paths,
                {
                    "Anime/Naruto",
                    "Sci-Fi/Battlestar Galactica (2004)",
                },
            )

    def test_duplicate_resolution_keeps_primary_relative_path(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Anime" / "Naruto" / "Season 01").mkdir(parents=True)
            (root / "Anime" / "Naruto" / "Season 01" / "Naruto - S01E01.mkv").write_text("x")
            (root / "Anime" / "Naruto Alt" / "Season 01").mkdir(parents=True)
            (root / "Anime" / "Naruto Alt" / "Season 01" / "Naruto - S01E01.mkv").write_text("x")

            orchestrator = BatchTVOrchestrator(
                _FakeTMDB(),
                root,
                discovery_service=TVLibraryDiscoveryService(),
            )

            states = orchestrator.discover_shows()
            by_path = {state.relative_folder: state for state in states}

            self.assertIn("Anime/Naruto", by_path)
            self.assertIn("Anime/Naruto Alt", by_path)

            primary = by_path["Anime/Naruto"]
            duplicate = by_path["Anime/Naruto Alt"]

            self.assertIsNone(primary.duplicate_of)
            self.assertTrue(primary.checked)
            self.assertEqual(duplicate.duplicate_of, primary.display_name)
            self.assertEqual(duplicate.duplicate_of_relative_folder, primary.relative_folder)
            self.assertFalse(duplicate.checked)

    def test_revert_cleanup_preserves_nested_container_boundary(self):
        with TemporaryDirectory() as tmp:
            library_root = Path(tmp) / "TV Root"
            generated_dir = library_root / "Documentaries" / "Generated" / "Season 01"
            generated_dir.mkdir(parents=True)
            restored_file = library_root / "restored.txt"
            generated_file = generated_dir / "restored.txt"
            generated_file.write_text("x")

            job = RenameJob(
                library_root=str(library_root),
                source_folder="Documentaries/Show",
                undo_data={
                    "renames": [
                        {
                            "old": str(restored_file),
                            "new": str(generated_file),
                        }
                    ],
                    "created_dirs": [
                        str(generated_dir),
                    ],
                    "removed_dirs": [],
                    "renamed_dirs": [],
                },
            )

            success, errors = revert_job(job)

            self.assertTrue(success, errors)
            self.assertEqual(errors, [])
            self.assertTrue(restored_file.exists())
            self.assertTrue((library_root / "Documentaries").exists())
            self.assertFalse((library_root / "Documentaries" / "Generated").exists())


if __name__ == "__main__":
    unittest.main()