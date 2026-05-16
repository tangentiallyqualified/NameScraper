# Batch Movie Tab Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the three batch movie tab improvements from [the design spec](../specs/2026-05-16-batch-movie-improvements-design.md): real evidence-based movie confidence, hidden middle-panel checkbox in movie mode, and approve-auto-checks-roster bug fix.

**Architecture:**
- Pure scoring helper `apply_movie_confidence_adjustments` lives in `plex_renamer/engine/matching.py` next to its TV equivalent. `MovieScanner.scan` calls it and stores the adjusted confidence on `PreviewItem.episode_confidence`. `build_movie_library_states` reads from the preview instead of hard-coding 0.5/1.0.
- `PreviewRowWidget` gains a `media_type` argument; in movie mode the toggle switch is hidden.
- The latent bug in `approve_scan_match` is fixed by adding the missing `set_actionable_preview_checks(state, True)` call.

**Tech Stack:** Python 3.11, PySide6 (Qt), unittest, pytest.

---

## File Structure

**Created:**
- `tests/test_movie_confidence_adjustments.py` — unit tests for the new scoring helper.

**Modified:**
- `plex_renamer/engine/matching.py` — adds `apply_movie_confidence_adjustments` and small parsing helper `_extract_sequel_number`.
- `plex_renamer/engine/__init__.py` — re-exports the new helper.
- `plex_renamer/engine/_movie_scanner.py` — invokes the helper, stores confidence on the preview item, derives `REVIEW:` status from the adjusted confidence.
- `plex_renamer/app/controllers/_movie_state_helpers.py` — sources `state.confidence` from `preview.episode_confidence` instead of the 0.5/1.0 stamp.
- `plex_renamer/app/controllers/_match_state_helpers.py` — calls `set_actionable_preview_checks(state, True)` at the end of `approve_scan_match`.
- `plex_renamer/gui_qt/widgets/_workspace_widgets.py` — `PreviewRowWidget.__init__` accepts `media_type`; hides toggle when `media_type == "movie"`.
- `plex_renamer/gui_qt/widgets/_media_workspace_preview.py` — passes `media_type=self._media_type` into `PreviewRowWidget`.
- `tests/test_media_controller.py` — updates `test_approve_match_resolves_movie_preview_review_status` to assert `state.checked is True` (the previously asserted `False` was the bug).
- `tests/test_qt_workspace_widgets.py` — adds a test asserting the movie-mode preview row hides the toggle.

---

## Task 1 — Sequel-number parser

Pure helper for sequel disambiguation evidence. Extract the integer sequel number from a movie title, or `None` if the title has no sequel marker.

**Files:**
- Create: `tests/test_movie_confidence_adjustments.py`
- Modify: `plex_renamer/engine/matching.py` (append at module bottom, before `score_tv_results`)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_movie_confidence_adjustments.py`:

```python
"""Tests for movie confidence postprocessing helpers in engine.matching."""
from __future__ import annotations

import unittest

from plex_renamer.engine.matching import _extract_sequel_number


class ExtractSequelNumberTests(unittest.TestCase):
    def test_no_sequel_marker_returns_none(self):
        self.assertIsNone(_extract_sequel_number("Inception"))
        self.assertIsNone(_extract_sequel_number("The Matrix"))

    def test_arabic_numeral_suffix(self):
        self.assertEqual(_extract_sequel_number("Iron Man 2"), 2)
        self.assertEqual(_extract_sequel_number("Toy Story 3"), 3)
        self.assertEqual(_extract_sequel_number("Saw 7"), 7)

    def test_roman_numeral_suffix(self):
        self.assertEqual(_extract_sequel_number("Rocky II"), 2)
        self.assertEqual(_extract_sequel_number("Halloween III"), 3)
        self.assertEqual(_extract_sequel_number("Star Wars: Episode IV"), 4)

    def test_part_phrasing(self):
        self.assertEqual(_extract_sequel_number("Kill Bill Part 2"), 2)
        self.assertEqual(_extract_sequel_number("Kill Bill: Part II"), 2)
        self.assertEqual(_extract_sequel_number("Dune: Part Two"), 2)

    def test_chapter_phrasing(self):
        self.assertEqual(_extract_sequel_number("John Wick: Chapter 3"), 3)
        self.assertEqual(_extract_sequel_number("It Chapter Two"), 2)

    def test_year_is_not_sequel(self):
        self.assertIsNone(_extract_sequel_number("Blade Runner 2049"))
        self.assertIsNone(_extract_sequel_number("Inception (2010)"))

    def test_case_insensitive(self):
        self.assertEqual(_extract_sequel_number("iron man 2"), 2)
        self.assertEqual(_extract_sequel_number("rocky ii"), 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_movie_confidence_adjustments.py -v`
Expected: `ImportError: cannot import name '_extract_sequel_number' from 'plex_renamer.engine.matching'` (all tests fail to collect).

- [ ] **Step 3: Implement `_extract_sequel_number`**

Append to `plex_renamer/engine/matching.py` (before `score_tv_results`):

```python
import re as _re_sequel

_ROMAN_NUMERAL_MAP = {
    "i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5,
    "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10,
}
_WORD_NUMERAL_MAP = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}

# Match trailing sequel tokens:
#   - "Part 2" / "Part II" / "Part Two"
#   - "Chapter 3" / "Chapter Three"
#   - "Episode IV"
#   - bare trailing "2" / "II" (only if not a 4-digit year)
_SEQUEL_RE = _re_sequel.compile(
    r"""
    (?:
        \b(?:part|chapter|episode)\s+
        (?P<phrase>[ivx]+|\w+|\d{1,2})
        |
        \b(?P<trailing>\d{1,2}|[ivx]+)\s*$
    )
    """,
    _re_sequel.IGNORECASE | _re_sequel.VERBOSE,
)


def _extract_sequel_number(title: str) -> int | None:
    """Return the integer sequel number embedded in *title*, or None.

    Recognises trailing arabic numerals (``Iron Man 2``), roman numerals
    (``Rocky II``), and ``Part/Chapter/Episode`` phrases including word
    numerals (``Dune: Part Two``). A 4-digit token like ``2049`` is treated
    as a year, not a sequel number.
    """
    if not title:
        return None
    stripped = title.strip()
    if stripped.endswith(")"):
        # Drop trailing "(2010)" year annotation before scanning.
        stripped = _re_sequel.sub(r"\s*\(\d{4}\)\s*$", "", stripped)
    for match in _SEQUEL_RE.finditer(stripped):
        token = (match.group("phrase") or match.group("trailing") or "").lower()
        if not token:
            continue
        if token.isdigit():
            value = int(token)
            if 1 <= value <= 99:
                return value
            continue
        if token in _ROMAN_NUMERAL_MAP:
            return _ROMAN_NUMERAL_MAP[token]
        if token in _WORD_NUMERAL_MAP:
            return _WORD_NUMERAL_MAP[token]
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_movie_confidence_adjustments.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```powershell
git add tests/test_movie_confidence_adjustments.py plex_renamer/engine/matching.py
.\scripts\git-publish.cmd -Message "Add sequel-number parser for movie confidence" -Branch dev/GUI3
```

---

## Task 2 — Folder/filename evidence helper

Pure helper that, given a `Path` and a TMDB result, returns the bag of evidence flags the postprocess pass needs.

**Files:**
- Modify: `tests/test_movie_confidence_adjustments.py` (add test class)
- Modify: `plex_renamer/engine/matching.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_movie_confidence_adjustments.py`:

```python
from pathlib import Path

from plex_renamer.engine.matching import _collect_movie_evidence


class CollectMovieEvidenceTests(unittest.TestCase):
    def test_exact_title_match_from_filename(self):
        ev = _collect_movie_evidence(
            file_path=Path("/movies/Inception.2010.mkv"),
            tmdb_title="Inception",
            tmdb_year="2010",
        )
        self.assertTrue(ev.exact_title_match)
        self.assertTrue(ev.year_exact_match)
        self.assertFalse(ev.year_severely_off)
        self.assertFalse(ev.folder_corroborates_title)
        self.assertFalse(ev.sequel_mismatch)

    def test_folder_corroborates_title_with_year(self):
        ev = _collect_movie_evidence(
            file_path=Path("/movies/Inception (2010)/movie.mkv"),
            tmdb_title="Inception",
            tmdb_year="2010",
        )
        self.assertTrue(ev.folder_corroborates_title)
        self.assertTrue(ev.year_exact_match)

    def test_folder_corroborates_without_year(self):
        ev = _collect_movie_evidence(
            file_path=Path("/movies/Inception/movie.mkv"),
            tmdb_title="Inception",
            tmdb_year="2010",
        )
        self.assertTrue(ev.folder_corroborates_title)

    def test_year_severely_off_three_or_more(self):
        ev = _collect_movie_evidence(
            file_path=Path("/movies/Inception.2008.mkv"),
            tmdb_title="Inception",
            tmdb_year="2010",
        )
        self.assertFalse(ev.year_exact_match)
        self.assertFalse(ev.year_severely_off)  # diff is 2

        ev = _collect_movie_evidence(
            file_path=Path("/movies/Inception.2007.mkv"),
            tmdb_title="Inception",
            tmdb_year="2010",
        )
        self.assertTrue(ev.year_severely_off)  # diff is 3

    def test_no_filename_year_yields_no_year_evidence(self):
        ev = _collect_movie_evidence(
            file_path=Path("/movies/Inception.mkv"),
            tmdb_title="Inception",
            tmdb_year="2010",
        )
        self.assertFalse(ev.year_exact_match)
        self.assertFalse(ev.year_severely_off)

    def test_sequel_mismatch_filename_has_number(self):
        ev = _collect_movie_evidence(
            file_path=Path("/movies/Iron Man 2.mkv"),
            tmdb_title="Iron Man",
            tmdb_year="2008",
        )
        self.assertTrue(ev.sequel_mismatch)

    def test_sequel_mismatch_tmdb_has_number(self):
        ev = _collect_movie_evidence(
            file_path=Path("/movies/Iron Man.mkv"),
            tmdb_title="Iron Man 2",
            tmdb_year="2010",
        )
        self.assertTrue(ev.sequel_mismatch)

    def test_sequel_numbers_match(self):
        ev = _collect_movie_evidence(
            file_path=Path("/movies/Iron Man 2.mkv"),
            tmdb_title="Iron Man 2",
            tmdb_year="2010",
        )
        self.assertFalse(ev.sequel_mismatch)

    def test_no_sequel_on_either_side(self):
        ev = _collect_movie_evidence(
            file_path=Path("/movies/Inception.mkv"),
            tmdb_title="Inception",
            tmdb_year="2010",
        )
        self.assertFalse(ev.sequel_mismatch)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_movie_confidence_adjustments.py::CollectMovieEvidenceTests -v`
Expected: `ImportError: cannot import name '_collect_movie_evidence'`.

- [ ] **Step 3: Implement `_collect_movie_evidence`**

Append to `plex_renamer/engine/matching.py`:

```python
from dataclasses import dataclass as _dataclass


@_dataclass(frozen=True, slots=True)
class _MovieEvidence:
    exact_title_match: bool
    year_exact_match: bool
    year_severely_off: bool
    folder_corroborates_title: bool
    sequel_mismatch: bool


def _collect_movie_evidence(
    *,
    file_path: Path,
    tmdb_title: str,
    tmdb_year: str | None,
) -> _MovieEvidence:
    """Inspect *file_path* against the chosen TMDB title/year and return evidence flags."""
    from ..parsing import clean_folder_name, extract_year, normalize_for_match

    stem = file_path.stem
    raw_filename = clean_folder_name(stem)
    raw_filename_no_year = clean_folder_name(stem, include_year=False)
    folder_clean = clean_folder_name(file_path.parent.name, include_year=False)

    tmdb_norm = normalize_for_match(tmdb_title)
    filename_norm = normalize_for_match(raw_filename_no_year)
    folder_norm = normalize_for_match(folder_clean)

    exact_title_match = bool(tmdb_norm) and (
        filename_norm == tmdb_norm or folder_norm == tmdb_norm
    )

    filename_year = extract_year(stem)
    year_exact_match = False
    year_severely_off = False
    if filename_year and tmdb_year:
        try:
            diff = abs(int(filename_year) - int(tmdb_year))
            year_exact_match = (diff == 0)
            year_severely_off = (diff >= 3)
        except (ValueError, TypeError):
            pass

    folder_corroborates_title = (
        bool(folder_norm) and bool(tmdb_norm) and folder_norm == tmdb_norm
    )

    filename_sequel = _extract_sequel_number(raw_filename)
    tmdb_sequel = _extract_sequel_number(tmdb_title)
    sequel_mismatch = (
        (filename_sequel is not None or tmdb_sequel is not None)
        and filename_sequel != tmdb_sequel
    )

    return _MovieEvidence(
        exact_title_match=exact_title_match,
        year_exact_match=year_exact_match,
        year_severely_off=year_severely_off,
        folder_corroborates_title=folder_corroborates_title,
        sequel_mismatch=sequel_mismatch,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_movie_confidence_adjustments.py -v`
Expected: all tests pass (Task 1 + Task 2 = 16 tests).

- [ ] **Step 5: Commit**

```powershell
git add tests/test_movie_confidence_adjustments.py plex_renamer/engine/matching.py
.\scripts\git-publish.cmd -Message "Add movie evidence collector for confidence postprocess" -Branch dev/GUI3
```

---

## Task 3 — Public `apply_movie_confidence_adjustments`

The public scoring helper that applies floors and caps to a raw confidence using the evidence flags.

**Files:**
- Modify: `tests/test_movie_confidence_adjustments.py`
- Modify: `plex_renamer/engine/matching.py`
- Modify: `plex_renamer/engine/__init__.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_movie_confidence_adjustments.py`:

```python
from plex_renamer.engine import apply_movie_confidence_adjustments


class ApplyMovieConfidenceAdjustmentsTests(unittest.TestCase):
    def _call(self, raw, **kwargs):
        return apply_movie_confidence_adjustments(
            raw_confidence=raw,
            file_path=kwargs.get("file_path", Path("/movies/Inception.mkv")),
            tmdb_title=kwargs.get("tmdb_title", "Inception"),
            tmdb_year=kwargs.get("tmdb_year", "2010"),
        )

    def test_exact_title_match_floors_to_095(self):
        result = self._call(0.42, file_path=Path("/movies/Inception.mkv"))
        self.assertGreaterEqual(result, 0.95)

    def test_year_exact_match_floors_to_085(self):
        # No exact title (filename differs), but year matches exactly.
        result = self._call(
            0.20,
            file_path=Path("/movies/incept.2010.mkv"),
            tmdb_title="Inception",
            tmdb_year="2010",
        )
        self.assertGreaterEqual(result, 0.85)

    def test_folder_corroborates_floors_to_088(self):
        result = self._call(
            0.30,
            file_path=Path("/movies/Inception/movie.mkv"),
            tmdb_title="Inception",
            tmdb_year="2010",
        )
        self.assertGreaterEqual(result, 0.88)

    def test_year_severely_off_caps_to_045(self):
        result = self._call(
            0.98,
            file_path=Path("/movies/Inception.2007.mkv"),
            tmdb_title="Inception",
            tmdb_year="2010",
        )
        self.assertLessEqual(result, 0.45)

    def test_sequel_mismatch_caps_to_050(self):
        result = self._call(
            0.95,
            file_path=Path("/movies/Iron Man 2.mkv"),
            tmdb_title="Iron Man",
            tmdb_year="2008",
        )
        self.assertLessEqual(result, 0.50)

    def test_cap_wins_over_floor(self):
        # Exact title match (floor 0.95) AND year severely off (cap 0.45) → 0.45.
        result = self._call(
            0.95,
            file_path=Path("/movies/Inception.2007.mkv"),
            tmdb_title="Inception",
            tmdb_year="2010",
        )
        self.assertLessEqual(result, 0.45)

    def test_no_evidence_leaves_score_unchanged(self):
        result = self._call(
            0.62,
            file_path=Path("/movies/totally_different.mkv"),
            tmdb_title="Inception",
            tmdb_year="2010",
        )
        self.assertAlmostEqual(result, 0.62, places=3)

    def test_never_exceeds_one(self):
        result = self._call(1.0, file_path=Path("/movies/Inception.mkv"))
        self.assertLessEqual(result, 1.0)

    def test_never_below_zero(self):
        result = self._call(
            0.10,
            file_path=Path("/movies/Iron Man 2.mkv"),
            tmdb_title="Iron Man",
            tmdb_year="2008",
        )
        self.assertGreaterEqual(result, 0.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_movie_confidence_adjustments.py::ApplyMovieConfidenceAdjustmentsTests -v`
Expected: `ImportError: cannot import name 'apply_movie_confidence_adjustments'`.

- [ ] **Step 3: Implement `apply_movie_confidence_adjustments`**

Append to `plex_renamer/engine/matching.py`:

```python
# Movie confidence floors and caps. Tweak here as evidence weighting
# is iterated. See docs/superpowers/specs/2026-05-16-batch-movie-improvements-design.md.
MOVIE_FLOOR_EXACT_TITLE = 0.95
MOVIE_FLOOR_FOLDER_CORROBORATES = 0.88
MOVIE_FLOOR_YEAR_EXACT = 0.85
MOVIE_CAP_SEQUEL_MISMATCH = 0.50
MOVIE_CAP_YEAR_SEVERELY_OFF = 0.45


def apply_movie_confidence_adjustments(
    *,
    raw_confidence: float,
    file_path: Path,
    tmdb_title: str,
    tmdb_year: str | None,
) -> float:
    """Return *raw_confidence* adjusted by evidence floors and caps.

    Floors raise confidence; caps lower it. Caps are applied after floors so
    a strong contradicting signal (e.g. wrong year) overrides a corroborating
    one (e.g. matching folder name). Result is clamped to ``[0.0, 1.0]``.
    """
    evidence = _collect_movie_evidence(
        file_path=file_path,
        tmdb_title=tmdb_title,
        tmdb_year=tmdb_year,
    )

    confidence = raw_confidence

    if evidence.exact_title_match:
        confidence = max(confidence, MOVIE_FLOOR_EXACT_TITLE)
    if evidence.folder_corroborates_title:
        confidence = max(confidence, MOVIE_FLOOR_FOLDER_CORROBORATES)
    if evidence.year_exact_match:
        confidence = max(confidence, MOVIE_FLOOR_YEAR_EXACT)

    if evidence.sequel_mismatch:
        confidence = min(confidence, MOVIE_CAP_SEQUEL_MISMATCH)
    if evidence.year_severely_off:
        confidence = min(confidence, MOVIE_CAP_YEAR_SEVERELY_OFF)

    return max(0.0, min(1.0, confidence))
```

Modify `plex_renamer/engine/__init__.py` — in the `from .matching import` block, add `apply_movie_confidence_adjustments`, and add the same name to `__all__` (keep alphabetical order):

```python
from .matching import (
    apply_movie_confidence_adjustments,
    boost_scores_with_alt_titles,
    boost_tv_scores_with_episode_evidence,
    pick_alternate_matches,
    score_results,
    score_tv_results,
    title_similarity,
)
```

And in `__all__`:

```python
    "apply_movie_confidence_adjustments",
    "boost_scores_with_alt_titles",
```

(Insert before `"boost_scores_with_alt_titles"`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_movie_confidence_adjustments.py -v`
Expected: all 25 tests pass.

- [ ] **Step 5: Commit**

```powershell
git add tests/test_movie_confidence_adjustments.py plex_renamer/engine/matching.py plex_renamer/engine/__init__.py
.\scripts\git-publish.cmd -Message "Add apply_movie_confidence_adjustments with floors and caps" -Branch dev/GUI3
```

---

## Task 4 — Pipe adjusted confidence through `MovieScanner.scan`

Wire the new helper into the scanner so `PreviewItem.episode_confidence` carries the real adjusted score and `REVIEW:` status reflects it.

**Files:**
- Modify: `plex_renamer/engine/_movie_scanner.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_movie_confidence_adjustments.py`:

```python
from unittest.mock import MagicMock
from plex_renamer.engine import MovieScanner


class MovieScannerConfidenceTests(unittest.TestCase):
    def _make_scanner(self, tmp: Path, tmdb_results: list[dict]) -> MovieScanner:
        tmdb = MagicMock()
        tmdb.language = "en-US"
        tmdb.search_movies_batch.return_value = [tmdb_results]
        tmdb.search_with_fallback.return_value = tmdb_results
        tmdb.search_movie.return_value = tmdb_results
        tmdb.get_alternative_titles.return_value = []
        return MovieScanner(tmdb, tmp)

    def test_preview_item_carries_real_confidence(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "Inception.2010.mkv").touch()
            (tmp / "filler1.mkv").touch()
            (tmp / "filler2.mkv").touch()
            scanner = self._make_scanner(tmp, [
                {"id": 27205, "title": "Inception", "year": "2010",
                 "poster_path": None, "overview": ""},
            ])
            items = scanner.scan()
            inception = next(i for i in items if "Inception" in i.original.name)
            self.assertGreaterEqual(inception.episode_confidence, 0.95)

    def test_review_status_set_for_low_confidence(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "Iron Man 2.mkv").touch()
            (tmp / "filler1.mkv").touch()
            (tmp / "filler2.mkv").touch()
            # TMDB returns Iron Man (no 2) — should trigger sequel-mismatch cap.
            scanner = self._make_scanner(tmp, [
                {"id": 1726, "title": "Iron Man", "year": "2008",
                 "poster_path": None, "overview": ""},
            ])
            items = scanner.scan()
            iron = next(i for i in items if "Iron Man" in i.original.name)
            self.assertLessEqual(iron.episode_confidence, 0.50)
            self.assertTrue(iron.status.startswith("REVIEW"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_movie_confidence_adjustments.py::MovieScannerConfidenceTests -v`
Expected: tests fail — `episode_confidence` is the default `1.0`, not the adjusted score.

- [ ] **Step 3: Update `MovieScanner.scan` and `_scan_single`**

In `plex_renamer/engine/_movie_scanner.py`, update the import block (around line 23-27):

```python
from .matching import (
    _country_from_language,
    apply_movie_confidence_adjustments,
    boost_scores_with_alt_titles,
    score_results,
)
```

Then update the batch loop in `scan()` (around line 299-309). Replace:

```python
            chosen, confidence = self._best_match(results, raw_name, year_hint)
            self.movie_info[file_path] = chosen

            item = _build_movie_preview_item(file_path, chosen, self.root)
            item.companions = _build_subtitle_companions(file_path, item.new_name)
            if confidence < get_auto_accept_threshold():
                item.status = (
                    f"REVIEW: best match \"{chosen['title']}\" "
                    f"(confidence {confidence:.0%}) — click to verify"
                )
            items.append(item)
```

with:

```python
            chosen, raw_confidence = self._best_match(results, raw_name, year_hint)
            self.movie_info[file_path] = chosen

            confidence = apply_movie_confidence_adjustments(
                raw_confidence=raw_confidence,
                file_path=file_path,
                tmdb_title=chosen.get("title", ""),
                tmdb_year=chosen.get("year"),
            )

            item = _build_movie_preview_item(file_path, chosen, self.root)
            item.episode_confidence = confidence
            item.companions = _build_subtitle_companions(file_path, item.new_name)
            if confidence < get_auto_accept_threshold():
                item.status = (
                    f"REVIEW: best match \"{chosen['title']}\" "
                    f"(confidence {confidence:.0%}) — click to verify"
                )
            items.append(item)
```

Also update `_scan_single` (around line 350-354) so manual single-file picks stamp confidence too. Replace:

```python
        self.movie_info[file_path] = chosen
        item = _build_movie_preview_item(file_path, chosen, self.root)
        item.companions = _build_subtitle_companions(file_path, item.new_name)
        return [item]
```

with:

```python
        self.movie_info[file_path] = chosen
        item = _build_movie_preview_item(file_path, chosen, self.root)
        # Manual single-file selection: user picked from the dialog, treat as 1.0.
        item.episode_confidence = 1.0
        item.companions = _build_subtitle_companions(file_path, item.new_name)
        return [item]
```

Update `rematch_file` (around line 356-363) likewise, since a manual rematch should also be 1.0:

```python
    def rematch_file(
        self,
        item: PreviewItem,
        chosen: dict,
    ) -> PreviewItem:
        """Re-match a single file to a different TMDB movie."""
        self.movie_info[item.original] = chosen
        new_item = _build_movie_preview_item(item.original, chosen, self.root)
        new_item.episode_confidence = 1.0
        return new_item
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_movie_confidence_adjustments.py -v`
Expected: all 27 tests pass.

Then run the broader scanner regression to make sure nothing else broke:

Run: `python -m pytest tests/test_movie_discovery.py tests/test_alt_title_matching.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add plex_renamer/engine/_movie_scanner.py tests/test_movie_confidence_adjustments.py
.\scripts\git-publish.cmd -Message "Apply movie confidence adjustments in scanner" -Branch dev/GUI3
```

---

## Task 5 — Read confidence from preview in `build_movie_library_states`

Replace the hard-coded `0.5`/`1.0` stamp with the real adjusted value from the preview.

**Files:**
- Modify: `plex_renamer/app/controllers/_movie_state_helpers.py`
- Modify: `tests/test_media_controller.py` (only if existing assertion fails)

- [ ] **Step 1: Update `build_movie_library_states`**

In `plex_renamer/app/controllers/_movie_state_helpers.py`, replace lines 32-34:

```python
        confidence = 1.0 if media_id else 0.0
        if item.status.startswith("REVIEW"):
            confidence = 0.5 if media_id else 0.0
```

with:

```python
        if media_id:
            confidence = item.episode_confidence
        else:
            confidence = 0.0
```

- [ ] **Step 2: Run movie controller tests**

Run: `python -m pytest tests/test_media_controller.py -q -k movie`
Expected: all pass. If any existing test asserts `state.confidence == 1.0` after a scan that previously stamped 1.0, update the assertion to read from the preview's `episode_confidence` (which defaults to 1.0 on `PreviewItem` so unchanged-fixture tests should still pass).

- [ ] **Step 3: Run the full scanner-adjacent regression**

Run: `python -m pytest tests/test_movie_confidence_adjustments.py tests/test_movie_discovery.py tests/test_media_controller.py -q`
Expected: all pass.

- [ ] **Step 4: Commit**

```powershell
git add plex_renamer/app/controllers/_movie_state_helpers.py
.\scripts\git-publish.cmd -Message "Source movie state confidence from preview" -Branch dev/GUI3
```

---

## Task 6 — Fix approve auto-check bug

One-line wire-up plus the test that proves the bug.

**Files:**
- Modify: `plex_renamer/app/controllers/_match_state_helpers.py`
- Modify: `tests/test_media_controller.py` (existing test asserts the bug; flip its assertion)

- [ ] **Step 1: Update the existing test to assert the *correct* behavior**

In `tests/test_media_controller.py` at the `test_approve_match_resolves_movie_preview_review_status` test (around line 1228), replace:

```python
        self.assertFalse(state.checked)
```

with:

```python
        self.assertTrue(state.checked)
```

- [ ] **Step 2: Run the test to verify it now fails**

Run: `python -m pytest tests/test_media_controller.py::ApproveMovieMatchTests::test_approve_match_resolves_movie_preview_review_status -v`

(If the test class name differs from `ApproveMovieMatchTests`, use the class name shown by `pytest --collect-only -q tests/test_media_controller.py | grep approve_match_resolves`.)

Expected: FAIL — `assert False is True` because `state.checked` is still False (the bug is still present).

- [ ] **Step 3: Add the missing call**

In `plex_renamer/app/controllers/_match_state_helpers.py`, find `approve_scan_match` (lines 29-44) and add one line before `return True`:

```python
def approve_scan_match(
    state: ScanState,
    *,
    resolve_movie_preview_review: Any,
    set_actionable_preview_checks: Any,
) -> bool:
    if (
        state.show_id is None
        or state.queued
        or state.scanning
        or state.duplicate_of is not None
    ):
        return False
    state.match_origin = "manual"
    resolve_movie_preview_review(state)
    set_actionable_preview_checks(state, True)
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_media_controller.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add plex_renamer/app/controllers/_match_state_helpers.py tests/test_media_controller.py
.\scripts\git-publish.cmd -Message "Auto-check roster row when match is approved" -Branch dev/GUI3
```

---

## Task 7 — Hide middle-panel checkbox in movie mode

`PreviewRowWidget` takes a `media_type` kwarg; in movie mode the toggle stays in the layout slot but is hidden.

**Files:**
- Modify: `plex_renamer/gui_qt/widgets/_workspace_widgets.py`
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_preview.py`
- Modify: `tests/test_qt_workspace_widgets.py`

- [ ] **Step 1: Write the failing test**

Look first at the existing structure of `tests/test_qt_workspace_widgets.py` (to copy fixtures / `setUp`):

Run: `python -m pytest tests/test_qt_workspace_widgets.py --collect-only -q`

Then append a new test class. Use the existing `_make_preview` / fixture pattern from the file — show the actual fixture code by running:

```powershell
Get-Content tests/test_qt_workspace_widgets.py | Select-String -Pattern 'PreviewRowWidget|_make_preview|PreviewItem\(' -Context 2,8
```

Append this test (adapt the fixture line to match the existing helpers — if there's no helper, build a `PreviewItem` inline matching the surrounding tests):

```python
class MoviePreviewRowCheckboxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def _make_movie_preview(self):
        from pathlib import Path
        from plex_renamer.constants import MediaType
        from plex_renamer.engine import PreviewItem
        return PreviewItem(
            original=Path("/movies/Inception.mkv"),
            new_name="Inception (2010).mkv",
            target_dir=Path("/movies/Inception (2010)"),
            season=None,
            episodes=[],
            status="OK",
            media_type=MediaType.MOVIE,
            media_id=27205,
            media_name="Inception",
        )

    def test_movie_mode_hides_checkbox(self):
        from plex_renamer.gui_qt.widgets._workspace_widgets import PreviewRowWidget
        widget = PreviewRowWidget(
            self._make_movie_preview(),
            compact=False,
            show_confidence=True,
            show_companions=False,
            checked=False,
            checkable=True,
            media_type="movie",
        )
        self.assertFalse(widget._check.isVisible())

    def test_tv_mode_shows_checkbox_when_actionable(self):
        from pathlib import Path
        from plex_renamer.constants import MediaType
        from plex_renamer.engine import PreviewItem
        from plex_renamer.gui_qt.widgets._workspace_widgets import PreviewRowWidget
        tv_preview = PreviewItem(
            original=Path("/tv/show/s01e01.mkv"),
            new_name="Show - S01E01.mkv",
            target_dir=Path("/tv/show"),
            season=1,
            episodes=[1],
            status="OK",
            media_type=MediaType.TV,
        )
        widget = PreviewRowWidget(
            tv_preview,
            compact=False,
            show_confidence=True,
            show_companions=False,
            checked=False,
            checkable=True,
            media_type="tv",
        )
        widget.show()  # Qt widgets are not visible until shown.
        self.assertTrue(widget._check.isVisibleTo(widget))
```

(Note: `isVisible()` returns False for an unshown widget. Use `isVisibleTo(parent)` to check the *would-be* visibility set by `setVisible`; this is what the test for hiding actually checks too — `setVisible(False)` makes `isVisibleTo(parent)` False even without showing.)

Actually, for the movie test, the most direct assertion is:

```python
        self.assertFalse(widget._check.isVisibleTo(widget))
```

Update the movie test accordingly — replace `self.assertFalse(widget._check.isVisible())` with `self.assertFalse(widget._check.isVisibleTo(widget))`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_qt_workspace_widgets.py::MoviePreviewRowCheckboxTests -v`
Expected: FAIL — `PreviewRowWidget.__init__()` got an unexpected keyword argument `'media_type'`.

- [ ] **Step 3: Add `media_type` to `PreviewRowWidget`**

In `plex_renamer/gui_qt/widgets/_workspace_widgets.py`, update `PreviewRowWidget.__init__` (around line 307-331). Add `media_type: str = "tv"` to the signature and gate the toggle visibility on it:

```python
    def __init__(
        self,
        preview: PreviewItem,
        *,
        compact: bool,
        show_confidence: bool,
        show_companions: bool,
        checked: bool,
        checkable: bool,
        media_type: str = "tv",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("previewRowCard")
        self.setProperty("cssClass", "preview-row-card")
        self._preview = preview
        self._media_type = media_type
        self._selected = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        show_check = (
            media_type != "movie"
            and preview.is_actionable
            and checkable
        )
        self._check = ToggleSwitch(checked if show_check else False, self)
        self._check.setVisible(show_check)
        self._check.toggled.connect(self.check_toggled.emit)
        layout.addWidget(self._check, alignment=Qt.AlignmentFlag.AlignTop)
```

Update `set_checked` (around line 394-399) so it's a no-op in movie mode too — already gated on `isVisible()`, no change needed.

- [ ] **Step 4: Pass `media_type` from `attach_preview_widget`**

In `plex_renamer/gui_qt/widgets/_media_workspace_preview.py`, update `attach_preview_widget` (around line 807-825). Add the kwarg:

```python
        widget = _PreviewRowWidget(
            preview,
            compact=compact,
            show_confidence=show_confidence,
            show_companions=show_companions,
            checked=state.check_vars.get(str(index), _CheckBinding(False)).get(),
            checkable=_is_state_queue_approvable(state, media_type=self._media_type),
            media_type=self._media_type,
            parent=self._list_widget,
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_qt_workspace_widgets.py -q`
Expected: all pass.

- [ ] **Step 6: Run the Qt smoke suite**

Run: `scripts\test-smoke.cmd`
Expected: exit code 0. (Full output is captured at `.pytest_cache/smoke/latest.log`.)

- [ ] **Step 7: Commit**

```powershell
git add plex_renamer/gui_qt/widgets/_workspace_widgets.py plex_renamer/gui_qt/widgets/_media_workspace_preview.py tests/test_qt_workspace_widgets.py
.\scripts\git-publish.cmd -Message "Hide middle-panel checkbox in movie mode" -Branch dev/GUI3
```

---

## Task 8 — Final regression sweep

Catch any cross-suite breakage before declaring done.

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest -q`
Expected: all pass.

- [ ] **Step 2: Run the Qt smoke**

Run: `scripts\test-smoke.cmd`
Expected: exit code 0.

- [ ] **Step 3: Manual GUI sanity** (operator-driven)

Launch the app, scan a folder with at least one well-named movie (`Inception.2010.mkv`) and one ambiguous one (`Iron Man 2.mkv` while pointing TMDB at the wrong year). Verify:
- Roster confidence bars show *different* widths for high vs. REVIEW rows (not just 50% / 100%).
- Middle-panel preview row in movie mode has no toggle switch where TV mode has one.
- Approving a REVIEW row via the dialog flips the roster row's switch on.

- [ ] **Step 4: No commit unless step 3 surfaced a fix.**

---

## Self-Review

**Spec coverage:**

- [x] Issue 1 — Movie confidence: Tasks 1–5 (helpers, scanner, state helper).
- [x] Issue 2 — Middle-panel checkbox: Task 7.
- [x] Issue 3 — Approve auto-checks: Task 6.
- [x] Surfacing: roster bar reads `state.confidence` (unchanged renderer); REVIEW string derived in scanner (Task 4).
- [x] Manual approve still sets 1.0: covered by the existing `resolve_movie_preview_review` doing `max(state.confidence, 1.0)` plus `set_actionable_preview_checks` flipping `state.checked`.
- [x] Out-of-scope (settings exposure, runtime/popularity evidence): not in plan, as designed.

**Placeholder scan:** none. Every step has either exact code or an exact command.

**Type consistency:** `_extract_sequel_number` → `int | None` (Task 1) → used in `_collect_movie_evidence` (Task 2) with that exact return type. `_MovieEvidence` fields (Task 2) consumed by `apply_movie_confidence_adjustments` (Task 3) with matching names. `apply_movie_confidence_adjustments` keyword args (`raw_confidence`, `file_path`, `tmdb_title`, `tmdb_year`) used identically in Task 4 scanner call site. `PreviewRowWidget(media_type=...)` (Task 7) — kwarg name matches in widget definition and caller.
