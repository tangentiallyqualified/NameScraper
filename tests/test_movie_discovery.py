from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from plex_renamer.app.models import MovieDirectoryRole
from plex_renamer.app.services import MovieLibraryDiscoveryService


class MovieDiscoveryTests(unittest.TestCase):
    def test_flat_movie_library_with_title_year_folders(self):
        """Flat layout: each movie in its own Title (Year) folder."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Die Hard (1988)").mkdir()
            (root / "Die Hard (1988)" / "Die Hard (1988).mkv").write_text("x")
            (root / "Blade Runner (1982)").mkdir()
            (root / "Blade Runner (1982)" / "Blade Runner (1982).mkv").write_text("x")

            service = MovieLibraryDiscoveryService()
            candidates = service.discover_movie_roots(root)
            relative_paths = {c.relative_folder for c in candidates}

            self.assertEqual(
                relative_paths,
                {"Die Hard (1988)", "Blade Runner (1982)"},
            )
            for c in candidates:
                self.assertEqual(c.discovery_reason, "title_year_folder")
                self.assertTrue(c.has_title_year_folder_name)
                self.assertEqual(c.direct_video_file_count, 1)

    def test_nested_discovery_under_genre_containers(self):
        """Movies nested one level under genre containers."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Action" / "Die Hard (1988)").mkdir(parents=True)
            (root / "Action" / "Die Hard (1988)" / "Die Hard.mkv").write_text("x")
            (root / "Sci-Fi" / "Blade Runner (1982)").mkdir(parents=True)
            (root / "Sci-Fi" / "Blade Runner (1982)" / "Blade Runner.mkv").write_text("x")

            service = MovieLibraryDiscoveryService()
            candidates = service.discover_movie_roots(root)
            relative_paths = {c.relative_folder for c in candidates}

            self.assertEqual(
                relative_paths,
                {"Action/Die Hard (1988)", "Sci-Fi/Blade Runner (1982)"},
            )
            # Verify parent relative folder is set
            by_path = {c.relative_folder: c for c in candidates}
            self.assertEqual(by_path["Action/Die Hard (1988)"].parent_relative_folder, "Action")

    def test_multi_level_nesting(self):
        """Movies nested multiple levels deep."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Region" / "US" / "Inception (2010)").mkdir(parents=True)
            (root / "Region" / "US" / "Inception (2010)" / "Inception.mkv").write_text("x")

            service = MovieLibraryDiscoveryService()
            candidates = service.discover_movie_roots(root)

            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0].relative_folder, "Region/US/Inception (2010)")
            self.assertEqual(candidates[0].depth, 3)

    def test_extras_folders_not_emitted(self):
        """Extras/featurettes folders should never become candidates."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            movie_dir = root / "Inception (2010)"
            movie_dir.mkdir()
            (movie_dir / "Inception.mkv").write_text("x")
            extras = movie_dir / "Featurettes"
            extras.mkdir()
            (extras / "Making Of.mkv").write_text("x")

            service = MovieLibraryDiscoveryService()
            candidates = service.discover_movie_roots(root)

            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0].relative_folder, "Inception (2010)")

    def test_ignored_system_folders_skipped(self):
        """System/junk folders should be skipped entirely."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "$RECYCLE.BIN").mkdir()
            (root / "$RECYCLE.BIN" / "file.mkv").write_text("x")
            (root / "@eaDir").mkdir()
            (root / "Inception (2010)").mkdir()
            (root / "Inception (2010)" / "Inception.mkv").write_text("x")

            service = MovieLibraryDiscoveryService()
            candidates = service.discover_movie_roots(root)

            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0].relative_folder, "Inception (2010)")

    def test_tv_show_roots_excluded(self):
        """Folders with season subdirectories should not become movie candidates."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            # TV show with season folders
            (root / "Naruto" / "Season 01").mkdir(parents=True)
            (root / "Naruto" / "Season 01" / "S01E01.mkv").write_text("x")
            # Actual movie
            (root / "Inception (2010)").mkdir()
            (root / "Inception (2010)" / "Inception.mkv").write_text("x")

            service = MovieLibraryDiscoveryService()
            candidates = service.discover_movie_roots(root)

            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0].relative_folder, "Inception (2010)")

    def test_season_folder_at_root_excluded(self):
        """A season folder directly under the library root should not become a candidate."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Season 01").mkdir()
            (root / "Season 01" / "S01E01.mkv").write_text("x")

            service = MovieLibraryDiscoveryService()
            candidates = service.discover_movie_roots(root)

            self.assertEqual(len(candidates), 0)

    def test_multi_movie_folder_detected(self):
        """A folder with 3+ non-TV video files is a multi-movie folder."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            dump = root / "Unsorted"
            dump.mkdir()
            (dump / "Movie.A.2020.mkv").write_text("x")
            (dump / "Movie.B.2019.mkv").write_text("x")
            (dump / "Movie.C.2021.mkv").write_text("x")

            service = MovieLibraryDiscoveryService()
            candidates = service.discover_movie_roots(root)

            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0].discovery_reason, "multiple_direct_video_files")
            self.assertEqual(candidates[0].direct_video_file_count, 3)

    def test_empty_folders_produce_no_candidates(self):
        """Empty folders should not become candidates."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Empty").mkdir()
            (root / "Also Empty" / "Sub").mkdir(parents=True)

            service = MovieLibraryDiscoveryService()
            candidates = service.discover_movie_roots(root)

            self.assertEqual(len(candidates), 0)

    def test_mixed_root_with_tv_and_movies(self):
        """A root containing both TV and movie subfolders should only emit movies."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            # TV show
            (root / "Breaking Bad" / "Season 01").mkdir(parents=True)
            (root / "Breaking Bad" / "Season 01" / "S01E01.mkv").write_text("x")
            # Movie
            (root / "Inception (2010)").mkdir()
            (root / "Inception (2010)" / "Inception.mkv").write_text("x")
            # Container with movie
            (root / "Classics" / "Casablanca (1942)").mkdir(parents=True)
            (root / "Classics" / "Casablanca (1942)" / "Casablanca.mkv").write_text("x")

            service = MovieLibraryDiscoveryService()
            candidates = service.discover_movie_roots(root)
            relative_paths = {c.relative_folder for c in candidates}

            self.assertEqual(
                relative_paths,
                {"Inception (2010)", "Classics/Casablanca (1942)"},
            )

    def test_movie_root_with_two_editions(self):
        """A movie folder with 2 video files (e.g. theatrical + directors cut)."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            movie = root / "Blade Runner (1982)"
            movie.mkdir()
            (movie / "Blade Runner (1982) - Theatrical.mkv").write_text("x")
            (movie / "Blade Runner (1982) - Final Cut.mkv").write_text("x")

            service = MovieLibraryDiscoveryService()
            candidates = service.discover_movie_roots(root)

            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0].direct_video_file_count, 2)

    def test_classify_directory_returns_correct_role(self):
        """The public classify_directory method returns the role enum."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            movie = root / "Inception (2010)"
            movie.mkdir()
            (movie / "Inception.mkv").write_text("x")

            service = MovieLibraryDiscoveryService()
            role = service.classify_directory(movie)

            self.assertEqual(role, MovieDirectoryRole.MOVIE_ROOT)

    def test_deterministic_sort_order(self):
        """Results should be sorted by normalized relative path."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ["Zodiac (2007)", "Alien (1979)", "Memento (2000)"]:
                (root / name).mkdir()
                (root / name / f"{name}.mkv").write_text("x")

            service = MovieLibraryDiscoveryService()
            candidates = service.discover_movie_roots(root)
            paths = [c.relative_folder for c in candidates]

            self.assertEqual(paths, ["Alien (1979)", "Memento (2000)", "Zodiac (2007)"])

    def test_tv_episode_files_not_counted_as_movies(self):
        """Files matching TV episode patterns should not create movie roots."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "Mixed"
            folder.mkdir()
            (folder / "Show.S01E01.mkv").write_text("x")
            (folder / "Show.S01E02.mkv").write_text("x")

            service = MovieLibraryDiscoveryService()
            candidates = service.discover_movie_roots(root)

            self.assertEqual(len(candidates), 0)


if __name__ == "__main__":
    unittest.main()
