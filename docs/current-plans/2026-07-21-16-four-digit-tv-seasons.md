# Four-Digit TV Seasons Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make TV classification and title inference agree with the existing parser for valid `SYYYYE##` filenames.

**Architecture:** Widen only season widths attached to an explicit `S...E...` marker from two to four digits across the TV classifier and title-prefix patterns. Year-bearing names without an `E` marker remain movies.

**Tech Stack:** Python 3.14, regular expressions, pathlib, pytest corpus tests, Ruff, Pyright.

## Global Constraints

- Implement only `PARSE-004`.
- Require an explicit `E` marker for four-digit seasons.
- Do not widen folder-only `S####` heuristics.
- Reject five-digit seasons.
- Preserve ordinary movie-year classification.

---

### Task 1: Characterize classification and prefix behavior

**Files:**
- Modify: `tests/test_parsing_edgecases.py`
- Modify later: `tests/parsing_corpus.py:684-690`

- [ ] **Step 1: Add exact positive and negative tests**

```python
@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Show.Name.S2020E01.1080p.WEB.mkv", True),
        ("Show.Name.S0001E02.mkv", True),
        ("Movie.Name.2020.1080p.WEB.mkv", False),
        ("Show.Name.S2020.1080p.WEB.mkv", False),
        ("Show.Name.S20201E01.mkv", False),
    ],
)
def test_four_digit_season_requires_explicit_episode_marker(
    name: str, expected: bool
) -> None:
    assert looks_like_tv_episode(Path(name)) is expected


def test_four_digit_season_keeps_clean_title_prefix() -> None:
    assert extract_source_title_prefix("Show.Name.S2020E01.1080p.WEB.mkv") == "Show Name"
```

- [ ] **Step 2: Run and confirm RED**

Run: `.venv\Scripts\python.exe -m pytest tests\test_parsing_edgecases.py -q -k four_digit_season`
Expected: positive classification/prefix cases FAIL.

### Task 2: Widen explicit marker patterns consistently

**Files:**
- Modify: `plex_renamer/_parsing_tv.py`
- Modify: `tests/parsing_corpus.py:684-690`

- [ ] **Step 1: Change only explicit SxE regex widths**

Apply `S\d{1,4}E\d{1,3}` to:

- the first `_TV_EPISODE_PATTERNS` entry;
- `_PREFIX_EPISODE_MARKER_RE`;
- the SxE entry in `_TV_TITLE_PREFIX_PATTERNS`.

Keep `_TV_FOLDER_PATTERNS` unchanged so a folder named `S2020` is not promoted by this plan.

- [ ] **Step 2: Remove the target corpus `xfail`**

Preserve `episodes=[1]`, `season=2020`, and `is_tv=True`; update the note to state that explicit four-digit seasons are supported.

- [ ] **Step 3: Run parser and title-prefix regressions**

Run: `.venv\Scripts\python.exe -m pytest tests\test_parsing_corpus.py tests\test_parsing_edgecases.py tests\test_scan_improvements.py -q`
Expected: PASS with no XPASS.

- [ ] **Step 4: Format/type-check and commit**

Run: `.venv\Scripts\ruff.exe format plex_renamer\_parsing_tv.py tests\test_parsing_edgecases.py tests\parsing_corpus.py && .venv\Scripts\ruff.exe check plex_renamer\_parsing_tv.py tests\test_parsing_edgecases.py tests\parsing_corpus.py && .venv\Scripts\pyright.exe plex_renamer\_parsing_tv.py tests\test_parsing_edgecases.py`
Expected: all commands exit 0.

```powershell
git add plex_renamer/_parsing_tv.py tests/parsing_corpus.py tests/test_parsing_edgecases.py
git commit -m "fix: classify explicit four-digit TV seasons"
```

### Task 3: Close `PARSE-004`

**Files:**
- Modify: `docs/deferred-work.md`

- [ ] **Step 1: Remove `PARSE-004` and update the P2 summary**

- [ ] **Step 2: Run `scripts\test-smoke.cmd`**
Expected: PASS.

- [ ] **Step 3: Commit**

```powershell
git add docs/deferred-work.md
git commit -m "docs: close four-digit season classification debt"
```
