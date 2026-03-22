"""
Rename engine — media-type-aware scanning, preview building, and execution.

This module contains the core logic that was previously embedded inside the
GUI class.  It operates on plain data structures (dicts, lists, Paths) and
has no tkinter dependency, making it testable and reusable.
"""

from __future__ import annotations

import re
import shutil
from collections import defaultdict
from pathlib import Path
from dataclasses import dataclass, field

from .constants import VIDEO_EXTENSIONS, MediaType
from .parsing import (
    build_movie_name,
    build_tv_name,
    clean_folder_name,
    extract_episode,
    extract_year,
    get_season,
    looks_like_tv_episode,
)
from .tmdb import TMDBClient
from .undo_log import load_log, save_log


# ─── Data structures ─────────────────────────────────────────────────────────

@dataclass
class PreviewItem:
    """One file's rename plan.  The GUI reads these to build the preview."""
    original: Path
    new_name: str | None
    target_dir: Path | None
    season: int | None          # None for movies
    episodes: list[int]         # Empty for movies
    status: str                 # "OK", "SKIP: ...", "CONFLICT: ..."
    media_type: str = MediaType.TV

    def is_move(self) -> bool:
        """True if this rename also moves the file to a different folder."""
        return (
            self.target_dir is not None
            and self.target_dir != self.original.parent
        )


@dataclass
class RenameResult:
    """Outcome of an execute_rename call."""
    renamed_count: int = 0
    errors: list[str] = field(default_factory=list)
    log_entry: dict = field(default_factory=dict)


# ─── TV scanning ─────────────────────────────────────────────────────────────

class TVScanner:
    """
    Scans a TV series folder and builds PreviewItems using TMDB data.

    Handles:
      - Season folder detection and mapping
      - Season structure mismatch detection (user folders vs TMDB)
      - Consolidated (absolute) and per-folder preview building
      - Specials / Season 0 fuzzy matching

    Caches season_dirs and tmdb_seasons after first computation to avoid
    redundant filesystem walks and API calls across scan/mismatch/consolidated.
    """

    def __init__(self, tmdb: TMDBClient, show_info: dict, root_folder: Path):
        self.tmdb = tmdb
        self.show_info = show_info
        self.root = root_folder
        # Populated during scan — used by the GUI for detail panel
        self.episode_titles: dict[tuple[int, int], str] = {}
        self.episode_posters: dict[tuple[int, int], str | None] = {}
        self.episode_meta: dict[tuple[int, int], dict] = {}  # Rich metadata per episode
        # Cached scan data — computed once, reused across methods
        self._season_dirs: list[tuple[Path, int]] | None = None
        self._tmdb_seasons: dict | None = None

    def _get_season_dirs(self) -> list[tuple[Path, int]]:
        """Find and sort season subdirectories. Cached after first call."""
        if self._season_dirs is not None:
            return self._season_dirs

        # Compute season number once per directory, filter and sort
        dirs_with_season = []
        for d in self.root.iterdir():
            if not d.is_dir():
                continue
            sn = get_season(d)
            if sn is not None:
                dirs_with_season.append((d, sn))

        dirs_with_season.sort(key=lambda x: x[1])

        if not dirs_with_season:
            self._season_dirs = [(self.root, 1)]
        else:
            self._season_dirs = dirs_with_season
        return self._season_dirs

    def _get_tmdb_seasons(self) -> dict:
        """Fetch TMDB season map. Cached after first call (also cached in TMDBClient)."""
        if self._tmdb_seasons is not None:
            return self._tmdb_seasons
        self._tmdb_seasons, _ = self.tmdb.get_season_map(self.show_info["id"])
        return self._tmdb_seasons

    def invalidate_cache(self) -> None:
        """Force re-scan on next call (e.g. after renames)."""
        self._season_dirs = None
        self._tmdb_seasons = None

    def scan(self) -> tuple[list[PreviewItem], bool]:
        """
        Scan the folder and build preview items.

        Returns:
            (items, has_mismatch) — the preview list and whether a
            season structure mismatch was detected.
        """
        season_dirs = self._get_season_dirs()
        tmdb_seasons = self._get_tmdb_seasons()

        mismatched, _, _ = self._detect_mismatch(season_dirs, tmdb_seasons)

        return (
            self._build_normal_preview(season_dirs, tmdb_seasons),
            mismatched,
        )

    def scan_consolidated(self) -> list[PreviewItem]:
        """Build a consolidated (absolute order) preview for mismatch fixes."""
        season_dirs = self._get_season_dirs()
        tmdb_seasons = self._get_tmdb_seasons()
        return self._build_consolidated_preview(season_dirs, tmdb_seasons)

    def get_mismatch_info(self) -> dict:
        """Return info about the season mismatch for UI display."""
        season_dirs = self._get_season_dirs()
        tmdb_seasons = self._get_tmdb_seasons()
        _, user_nums, tmdb_nums = self._detect_mismatch(season_dirs, tmdb_seasons)
        extra = sorted(user_nums - tmdb_nums)
        return {
            "user_seasons": sorted(user_nums),
            "tmdb_seasons": {
                sn: tmdb_seasons[sn]["count"]
                for sn in sorted(tmdb_nums)
                if sn in tmdb_seasons
            },
            "extra_user_seasons": extra,
        }

    # ─── Internal ─────────────────────────────────────────────────────

    def _detect_mismatch(
        self,
        season_dirs: list[tuple[Path, int]],
        tmdb_seasons: dict,
    ) -> tuple[bool, set[int], set[int]]:
        user_nums = {sn for _, sn in season_dirs}
        tmdb_nums = set(tmdb_seasons.keys())
        extra = (user_nums - tmdb_nums) - {0}
        return bool(extra), user_nums, tmdb_nums

    def _store_tmdb_data(self, season_num: int, titles: dict, posters: dict,
                         episodes: dict | None = None):
        """Cache TMDB data for the detail panel."""
        self.episode_titles.update({(season_num, k): v for k, v in titles.items()})
        self.episode_posters.update({(season_num, k): v for k, v in posters.items()})
        if episodes:
            self.episode_meta.update({(season_num, k): v for k, v in episodes.items()})

    def _build_normal_preview(
        self,
        season_dirs: list[tuple[Path, int]],
        tmdb_seasons: dict,
    ) -> list[PreviewItem]:
        items: list[PreviewItem] = []

        for season_dir, season_num in season_dirs:
            if season_num in tmdb_seasons:
                titles = tmdb_seasons[season_num]["titles"]
                posters = tmdb_seasons[season_num]["posters"]
                episodes = tmdb_seasons[season_num].get("episodes", {})
            else:
                season_data = self.tmdb.get_season(self.show_info["id"], season_num)
                titles = season_data["titles"]
                posters = season_data["posters"]
                episodes = season_data.get("episodes", {})

            self._store_tmdb_data(season_num, titles, posters, episodes)

            # Fuzzy title lookup for Season 0
            tmdb_title_lookup = {}
            if season_num == 0 and titles:
                for ep_num, title in titles.items():
                    normalized = re.sub(r"[^a-z0-9]+", "", title.lower())
                    tmdb_title_lookup[normalized] = (ep_num, title)

            specials_target = self.root / "Season 00" if season_num == 0 else None

            for f in sorted(season_dir.iterdir()):
                if not f.is_file() or f.suffix.lower() not in VIDEO_EXTENSIONS:
                    continue

                eps, raw_title, is_season_relative = extract_episode(f.name)

                # Season 0 special handling
                if season_num == 0:
                    item = self._match_special(
                        f, eps, raw_title, titles, tmdb_title_lookup, specials_target,
                    )
                    items.append(item)
                    continue

                # Normal season handling
                if not eps:
                    items.append(PreviewItem(
                        original=f, new_name=None, target_dir=None,
                        season=season_num, episodes=[],
                        status="SKIP: could not parse episode number",
                    ))
                    continue

                ep_titles = [
                    titles.get(ep, raw_title or f"Episode {ep}")
                    for ep in eps
                ]

                new_name = build_tv_name(
                    self.show_info["name"], self.show_info["year"],
                    season_num, eps, ep_titles, f.suffix,
                )

                items.append(PreviewItem(
                    original=f, new_name=new_name, target_dir=None,
                    season=season_num, episodes=eps, status="OK",
                ))

        return items

    def _match_special(
        self,
        f: Path,
        eps: list[int],
        raw_title: str | None,
        titles: dict,
        tmdb_title_lookup: dict,
        specials_target: Path,
    ) -> PreviewItem:
        """Try to match a specials file to a TMDB Season 0 episode."""
        matched_ep = None
        matched_title = None

        # Try by episode number
        if eps:
            for ep_num in eps:
                if ep_num in titles:
                    matched_ep = ep_num
                    matched_title = titles[ep_num]
                    break

        # Try fuzzy title match
        if not matched_ep and raw_title:
            normalized_raw = re.sub(r"[^a-z0-9]+", "", raw_title.lower())
            if normalized_raw in tmdb_title_lookup:
                matched_ep, matched_title = tmdb_title_lookup[normalized_raw]
            else:
                for norm_key, (ep_n, orig_t) in tmdb_title_lookup.items():
                    if (normalized_raw and norm_key and
                            (normalized_raw in norm_key or norm_key in normalized_raw)):
                        matched_ep = ep_n
                        matched_title = orig_t
                        break

        if matched_ep is not None:
            new_name = build_tv_name(
                self.show_info["name"], self.show_info["year"],
                0, [matched_ep], [matched_title], f.suffix,
            )
            return PreviewItem(
                original=f, new_name=new_name, target_dir=specials_target,
                season=0, episodes=[matched_ep], status="OK",
            )

        # No match — keep original name, move to Season 00
        return PreviewItem(
            original=f, new_name=f.name, target_dir=specials_target,
            season=0, episodes=eps, status="OK",
        )

    def _build_consolidated_preview(
        self,
        season_dirs: list[tuple[Path, int]],
        tmdb_seasons: dict,
    ) -> list[PreviewItem]:
        """Build preview mapping files in absolute order to TMDB structure."""
        all_files = self._collect_absolute_files(season_dirs)

        # Flat TMDB episode list in order
        tmdb_list: list[tuple[int, int, str]] = []
        for sn in sorted(tmdb_seasons.keys()):
            sd = tmdb_seasons[sn]
            for ep_num in sorted(sd["titles"].keys()):
                tmdb_list.append((sn, ep_num, sd["titles"][ep_num]))

        # Cache TMDB data
        for sn, sdata in tmdb_seasons.items():
            self._store_tmdb_data(sn, sdata["titles"], sdata["posters"],
                                  sdata.get("episodes", {}))

        items: list[PreviewItem] = []
        tmdb_idx = 0

        for f, abs_num, raw_title, eps, is_sr in all_files:
            num_eps = max(1, len(eps))

            if tmdb_idx >= len(tmdb_list):
                items.append(PreviewItem(
                    original=f, new_name=None, target_dir=None,
                    season=0, episodes=eps,
                    status="SKIP: no matching TMDB episode (extra file?)",
                ))
                continue

            file_eps = []
            file_titles = []
            target_season = tmdb_list[tmdb_idx][0]
            for j in range(num_eps):
                if tmdb_idx + j < len(tmdb_list):
                    sn, ep, title = tmdb_list[tmdb_idx + j]
                    file_eps.append(ep)
                    file_titles.append(title)
                    target_season = sn
            tmdb_idx += num_eps

            target_dir = self.root / f"Season {target_season:02d}"
            new_name = build_tv_name(
                self.show_info["name"], self.show_info["year"],
                target_season, file_eps, file_titles, f.suffix,
            )

            items.append(PreviewItem(
                original=f, new_name=new_name, target_dir=target_dir,
                season=target_season, episodes=file_eps, status="OK",
            ))

        return items

    def _collect_absolute_files(
        self, season_dirs: list[tuple[Path, int]],
    ) -> list[tuple[Path, int, str | None, list[int], bool]]:
        """Collect all video files sorted by absolute episode number."""
        all_files = []
        for season_dir, season_num in season_dirs:
            for f in sorted(season_dir.iterdir()):
                if not f.is_file() or f.suffix.lower() not in VIDEO_EXTENSIONS:
                    continue
                eps, raw_title, is_sr = extract_episode(f.name)
                abs_num = eps[0] if eps else 9999
                all_files.append((f, abs_num, raw_title, eps, is_sr))
        all_files.sort(key=lambda x: x[1])
        return all_files


# ─── Movie scanning ──────────────────────────────────────────────────────────

def _prepare_movie_query(stem: str) -> tuple[str, str | None]:
    """
    Shared helper: clean a filename stem into a TMDB search query and year hint.

    Eliminates the duplicated logic that was in both scan() and _scan_single().
    """
    raw_name = clean_folder_name(stem)
    search_query = re.sub(r"\s*\(\d{4}\)\s*$", "", raw_name).strip()
    year_hint = extract_year(stem)
    return search_query, year_hint


def _build_movie_preview_item(
    f: Path, chosen: dict,
) -> PreviewItem:
    """
    Shared helper: build a PreviewItem from a chosen TMDB movie match.

    Eliminates the duplicated PreviewItem construction in scan(), _scan_single(),
    and rematch_file().
    """
    new_name = build_movie_name(chosen["title"], chosen["year"], f.suffix)
    folder_name = build_movie_name(chosen["title"], chosen["year"], "")
    target_dir = f.parent / folder_name

    return PreviewItem(
        original=f, new_name=new_name, target_dir=target_dir,
        season=None, episodes=[], status="OK",
        media_type=MediaType.MOVIE,
    )


class MovieScanner:
    """
    Scans movie files and builds PreviewItems using TMDB data.

    Supports two modes:
      - Batch folder: pass a root_folder, all video files inside are scanned
      - Explicit files: pass a list of file paths directly

    Each file is independently matched against TMDB by cleaning the
    *filename* (not the folder name).  A new folder "Title (Year)" is
    created next to each file, and the file is moved inside.

    This matches Plex's expected structure:
      Movies/Title (Year)/Title (Year).mkv
    """

    def __init__(
        self,
        tmdb: TMDBClient,
        root_folder: Path,
        files: list[Path] | None = None,
    ):
        self.tmdb = tmdb
        self.root = root_folder
        self._explicit_files = files
        # Populated during scan for the detail panel
        self.movie_info: dict[Path, dict] = {}
        # Cached TMDB search results per file for re-matching
        self._search_cache: dict[Path, list[dict]] = {}

    def _get_video_files(self) -> list[Path]:
        """Return the files to process — explicit list or folder scan."""
        if self._explicit_files:
            return sorted(self._explicit_files)
        return sorted(
            f for f in self.root.rglob("*")
            if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
        )

    @staticmethod
    def _filter_sequential_batches(
        files: list[Path],
    ) -> tuple[list[Path], list[PreviewItem]]:
        """
        Detect groups of files that look like sequentially numbered TV episodes.

        Groups files by parent folder, extracts a dash-delimited number from
        each filename (e.g. "Title - 03"), and if 3+ files in the same folder
        share a common prefix with sequential-ish numbers, marks them as TV skips.

        Returns (remaining_files, skipped_items).
        """
        # Pattern: anything, then " - ##" before tags/extension
        _NUM_PATTERN = re.compile(
            r"^(.*?)\s*-\s*(\d{1,3})\s*(?:[\s.\-(v]|$)",
        )

        # Group by parent folder
        by_folder: dict[Path, list[tuple[Path, str, int]]] = defaultdict(list)

        for f in files:
            m = _NUM_PATTERN.search(f.stem)
            if m:
                prefix = m.group(1).strip().lower()
                num = int(m.group(2))
                # Skip numbers that look like years
                if 1900 <= num <= 2099:
                    continue
                by_folder[f.parent].append((f, prefix, num))

        # Find sequential batches (3+ files with same prefix)
        skip_set: set[Path] = set()
        for folder, entries in by_folder.items():
            # Group by prefix
            prefix_groups: dict[str, list[tuple[Path, int]]] = defaultdict(list)
            for f, prefix, num in entries:
                prefix_groups[prefix].append((f, num))

            for prefix, group in prefix_groups.items():
                if len(group) < 3:
                    continue
                # Check if numbers are roughly sequential (allow gaps)
                nums = sorted(n for _, n in group)
                # If the range of numbers is reasonable for a TV series
                # (not like 1, 500, 999) and there are enough of them
                num_range = nums[-1] - nums[0]
                if num_range < len(group) * 3:  # Allow some gaps
                    for f, _ in group:
                        skip_set.add(f)

        remaining = []
        skipped = []
        for f in files:
            if f in skip_set:
                skipped.append(PreviewItem(
                    original=f, new_name=None, target_dir=None,
                    season=None, episodes=[],
                    status="SKIP: looks like a TV episode (sequential batch)",
                    media_type=MediaType.MOVIE,
                ))
            else:
                remaining.append(f)

        return remaining, skipped

    def scan(
        self,
        pick_movie_callback: callable | None = None,
        progress_callback: callable | None = None,
    ) -> list[PreviewItem]:
        """
        Scan files and build preview items with automatic TMDB matching.

        Performance optimizations for large folders:
          - Files that look like TV episodes (S01E01 patterns, season
            folders) are filtered out automatically with a SKIP status.
          - TMDB searches run in parallel using a thread pool.
          - Connection pooling (HTTP keep-alive) via the TMDBClient session.

        For single-file mode (1 file), the pick callback is invoked for
        immediate confirmation.
        """
        items: list[PreviewItem] = []

        # Phase 1: Collect and filter files
        all_video_files = self._get_video_files()
        video_files: list[Path] = []

        for f in all_video_files:
            if looks_like_tv_episode(f):
                items.append(PreviewItem(
                    original=f, new_name=None, target_dir=None,
                    season=None, episodes=[],
                    status="SKIP: looks like a TV episode",
                    media_type=MediaType.MOVIE,
                ))
            else:
                video_files.append(f)

        # Phase 1b: Batch detection — if 3+ remaining files in the same
        # folder share a common name prefix with sequential dash-delimited
        # numbers (e.g. "Title - 01", "Title - 02", "Title - 03"), they're
        # almost certainly TV episodes even without S##E## markers.
        if len(video_files) >= 3:
            video_files, batch_skipped = self._filter_sequential_batches(video_files)
            items.extend(batch_skipped)

        if not video_files:
            return items

        # Single-file mode: serial search with confirmation dialog
        if len(video_files) == 1:
            return items + self._scan_single(
                video_files[0], pick_movie_callback,
            )

        # Phase 2: Build search queries (shared helper eliminates duplication)
        queries = [_prepare_movie_query(f.stem) for f in video_files]

        # Phase 3: Parallel TMDB search
        def _progress(done, total):
            if progress_callback:
                progress_callback(done, total, "Searching TMDB...")

        all_results = self.tmdb.search_movies_batch(
            queries, progress_callback=_progress,
        )

        # Phase 4: Build preview items from results
        for f, (search_query, year_hint), results in zip(
            video_files, queries, all_results,
        ):
            self._search_cache[f] = results

            if not results:
                items.append(PreviewItem(
                    original=f, new_name=None, target_dir=None,
                    season=None, episodes=[],
                    status="REVIEW: no TMDB results — click to search manually",
                    media_type=MediaType.MOVIE,
                ))
                continue

            raw_name = clean_folder_name(f.stem)
            chosen, confidence = self._best_match(results, raw_name, year_hint)
            self.movie_info[f] = chosen

            if confidence < AUTO_ACCEPT_THRESHOLD:
                # Low confidence — flag for user review instead of auto-accepting
                item = _build_movie_preview_item(f, chosen)
                item.status = (
                    f"REVIEW: best match \"{chosen['title']}\" "
                    f"(confidence {confidence:.0%}) — click to verify"
                )
                items.append(item)
            else:
                items.append(_build_movie_preview_item(f, chosen))

        return items

    def _scan_single(
        self,
        f: Path,
        pick_movie_callback: callable | None,
    ) -> list[PreviewItem]:
        """Handle single-file scan with confirmation dialog."""
        search_query, year_hint = _prepare_movie_query(f.stem)

        results = self.tmdb.search_movie(search_query, year_hint)
        if not results:
            results = self.tmdb.search_movie(search_query)
        self._search_cache[f] = results

        if pick_movie_callback:
            chosen = pick_movie_callback(results or [], f.name)
            if chosen is CANCEL_SCAN:
                return []
        else:
            chosen = results[0] if results else None

        if not chosen:
            return [PreviewItem(
                original=f, new_name=None, target_dir=None,
                season=None, episodes=[],
                status="SKIP: no movie selected" if results else
                       "REVIEW: no TMDB results — click to search manually",
                media_type=MediaType.MOVIE,
            )]

        self.movie_info[f] = chosen
        return [_build_movie_preview_item(f, chosen)]

    def rematch_file(
        self, item: PreviewItem, chosen: dict,
    ) -> PreviewItem:
        """
        Re-match a single file to a different TMDB movie.

        Called from the GUI when the user corrects an auto-match or
        resolves a REVIEW item from the preview.
        """
        self.movie_info[item.original] = chosen
        return _build_movie_preview_item(item.original, chosen)

    def get_search_results(self, f: Path) -> list[dict]:
        """Return cached TMDB search results for a file."""
        return self._search_cache.get(f, [])

    @staticmethod
    def _best_match(
        results: list[dict], raw_name: str, year_hint: str | None,
    ) -> tuple[dict, float]:
        """
        Pick the best TMDB result using title similarity + year matching.

        Returns (best_result, confidence) where confidence is 0.0–1.0.
        Delegates scoring to the shared ``score_results`` function.
        """
        scored = score_results(results, raw_name, year_hint, title_key="title")
        if scored:
            return scored[0]
        return results[0], 0.0


def normalize_for_match(text: str) -> str:
    """
    Normalize a title for fuzzy comparison.

    Strips year suffixes, punctuation, articles, and extra whitespace.
    Returns lowercase with single spaces.
    """
    t = re.sub(r"\s*\(\d{4}\)\s*$", "", text)  # strip trailing (YYYY)
    t = re.sub(r"[^\w\s]", " ", t)  # punctuation → spaces
    t = t.lower().strip()
    # Remove leading articles for matching ("the matrix" == "matrix")
    t = re.sub(r"^(?:the|a|an)\s+", "", t)
    return re.sub(r"\s+", " ", t)


def title_similarity(a: str, b: str) -> float:
    """
    Compute a simple title similarity score between 0.0 and 1.0.

    Uses the longest common subsequence ratio, which handles:
      - Exact matches → 1.0
      - Substring matches (Daybreakers vs Daybreak) → high but < 1.0
      - Partial overlaps → proportional score
      - Completely different → near 0.0

    This is lightweight and doesn't need external libraries.
    """
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0

    # Quick check: one is substring of the other
    # "daybreak" in "daybreakers" → high but penalized for length diff
    if a in b or b in a:
        shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
        return len(shorter) / len(longer)

    # LCS length ratio
    m, n = len(a), len(b)
    # Optimize: only keep two rows for O(min(m,n)) space
    if m < n:
        a, b = b, a
        m, n = n, m

    prev = [0] * (n + 1)
    for i in range(1, m + 1):
        curr = [0] * (n + 1)
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                curr[j] = prev[j - 1] + 1
            else:
                curr[j] = max(curr[j - 1], prev[j])
        prev = curr

    lcs_len = prev[n]
    return (2.0 * lcs_len) / (m + n)  # Dice-like coefficient


# Minimum confidence for auto-accepting a match without review
AUTO_ACCEPT_THRESHOLD = 0.55


# Sentinel value returned by the pick callback to cancel the entire scan.
CANCEL_SCAN = object()


def score_results(
    results: list[dict],
    raw_name: str,
    year_hint: str | None,
    title_key: str = "title",
) -> list[tuple[dict, float]]:
    """
    Score a list of TMDB search results against a cleaned name.

    Shared by both TV and movie matching paths.  Each result gets a
    confidence score between 0.0 and 1.0 based on:
      - Title similarity (normalized, case-insensitive) weighted at 70%
      - Year match weighted at 30%  (exact = 1.0, ±1 year = 0.3)
      - Exact normalized title match gets a +0.15 bonus

    Args:
        results:    List of TMDB result dicts.
        raw_name:   Cleaned folder/filename to match against.
        year_hint:  4-digit year string extracted from the source, or None.
        title_key:  Key in each result dict holding the title
                    ("title" for movies, "name" for TV).

    Returns:
        List of (result, score) tuples sorted by score descending.
    """
    query_norm = normalize_for_match(raw_name)
    scored: list[tuple[dict, float]] = []

    for r in results:
        title = r.get(title_key, "")
        title_norm = normalize_for_match(title)

        t_score = title_similarity(query_norm, title_norm)

        year_score = 0.0
        if year_hint and r.get("year"):
            try:
                diff = abs(int(year_hint) - int(r["year"]))
                if diff == 0:
                    year_score = 1.0
                elif diff == 1:
                    year_score = 0.3
            except (ValueError, TypeError):
                pass

        score = (t_score * 0.7) + (year_score * 0.3)

        if query_norm == title_norm:
            score = min(1.0, score + 0.15)

        scored.append((r, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


# ─── Shared utilities ─────────────────────────────────────────────────────────

def check_duplicates(items: list[PreviewItem]) -> None:
    """Flag items that would collide on the same target filename."""
    seen: dict[str, str] = {}
    for item in items:
        if item.new_name is None:
            continue
        key = item.new_name.lower()
        if key in seen:
            item.status = f"CONFLICT: same target as {seen[key]}"
        else:
            seen[key] = item.original.name


def execute_rename(
    items: list[PreviewItem],
    checked_indices: set[int],
    show_name: str,
    root_folder: Path,
) -> RenameResult:
    """
    Perform the actual file renames/moves for checked items.

    Supports cross-folder moves, creates target directories as needed,
    normalizes season folder names, and cleans up empty source dirs.
    Returns a RenameResult with the log entry for undo support.
    """
    result = RenameResult()
    result.log_entry = {
        "show": show_name,
        "renames": [],
        "created_dirs": [],
        "removed_dirs": [],
        "renamed_dirs": [],
    }

    renames: list[tuple[Path, Path, Path]] = []
    source_dirs: set[Path] = set()

    for i in checked_indices:
        if i >= len(items):
            continue
        item = items[i]
        if item.new_name is None or item.status != "OK":
            continue

        src = item.original
        source_dirs.add(src.parent)
        target_dir = item.target_dir or src.parent
        dst = target_dir / item.new_name

        if dst.exists() and src != dst:
            result.errors.append(f"Target already exists: {dst}")
            return result

        renames.append((src, dst, target_dir))

    if not renames:
        return result

    for src, dst, target_dir in renames:
        try:
            if not target_dir.exists():
                target_dir.mkdir(parents=True, exist_ok=True)
                if str(target_dir) not in result.log_entry["created_dirs"]:
                    result.log_entry["created_dirs"].append(str(target_dir))

            if src.parent != target_dir:
                shutil.move(str(src), str(dst))
            else:
                src.rename(dst)

            result.log_entry["renames"].append({
                "old": str(src), "new": str(dst),
            })
            result.renamed_count += 1
        except (OSError, shutil.Error) as e:
            result.errors.append(f"{src.name}: {e}")

    # Normalize season folder names (TV only)
    all_dirs = source_dirs.copy()
    for _, dst, td in renames:
        all_dirs.add(td)

    for season_dir in all_dirs:
        if not season_dir.exists() or season_dir == root_folder:
            continue
        season_num = get_season(season_dir)
        if season_num is None:
            continue
        proper_name = f"Season {season_num:02d}"
        if season_dir.name == proper_name:
            continue
        proper_path = season_dir.parent / proper_name
        if proper_path.exists():
            continue
        try:
            season_dir.rename(proper_path)
            result.log_entry["renamed_dirs"].append({
                "old": str(season_dir), "new": str(proper_path),
            })
        except OSError:
            pass

    # Clean up empty source directories
    for src_dir in source_dirs:
        try:
            if src_dir != root_folder and src_dir.exists():
                if not list(src_dir.iterdir()):
                    src_dir.rmdir()
                    result.log_entry["removed_dirs"].append(str(src_dir))
        except OSError:
            pass

    # Persist log
    log = load_log()
    log.append(result.log_entry)
    save_log(log)

    return result


def execute_undo() -> tuple[bool, list[str]]:
    """
    Undo the most recent rename batch.

    Returns (success, errors).
    """
    log = load_log()
    if not log:
        return False, ["No rename history found."]

    last = log[-1]
    errors: list[str] = []

    # Revert folder renames
    dir_rename_map: dict[str, str] = {}
    for entry in reversed(last.get("renamed_dirs", [])):
        new_dir = Path(entry["new"])
        old_dir = Path(entry["old"])
        try:
            if new_dir.exists():
                new_dir.rename(old_dir)
                dir_rename_map[str(new_dir)] = str(old_dir)
        except OSError as e:
            errors.append(f"Could not revert folder {new_dir.name}: {e}")

    # Recreate removed directories
    for dir_path_str in last.get("removed_dirs", []):
        try:
            Path(dir_path_str).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            errors.append(f"Could not recreate folder {Path(dir_path_str).name}: {e}")

    # Move files back
    for entry in reversed(last["renames"]):
        new_path = Path(entry["new"])
        old_path = Path(entry["old"])

        for renamed_new, renamed_old in dir_rename_map.items():
            if str(new_path).startswith(renamed_new):
                new_path = Path(str(new_path).replace(renamed_new, renamed_old, 1))
            if str(old_path).startswith(renamed_new):
                old_path = Path(str(old_path).replace(renamed_new, renamed_old, 1))

        try:
            old_path.parent.mkdir(parents=True, exist_ok=True)
            if new_path.exists():
                if new_path.parent != old_path.parent:
                    shutil.move(str(new_path), str(old_path))
                else:
                    new_path.rename(old_path)
            else:
                errors.append(f"File not found: {new_path.name}")
        except (OSError, shutil.Error) as e:
            errors.append(f"{new_path.name}: {e}")

    # Remove created directories if empty
    for dir_path_str in last.get("created_dirs", []):
        dir_path = Path(dir_path_str)
        try:
            if dir_path.exists() and not list(dir_path.iterdir()):
                dir_path.rmdir()
        except OSError:
            pass

    log.pop()
    save_log(log)

    return len(errors) == 0, errors
