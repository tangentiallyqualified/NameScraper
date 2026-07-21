# Parenthesized Batch Ranges Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parse intentional parenthesized episode ranges such as `[Group] Show Name (01-12) [Batch]` without treating years, title numbers, or ordinary parentheticals as episodes.

**Architecture:** Add a raw-stem parser that claims a parenthesized range only when a separate `[Batch]` tag is present. Run it after explicit SxE/NxN parsing and before generic numeric parsing. Keep the existing maximum-span policy and return absolute episode numbering.

**Tech Stack:** Python 3.14, regular expressions, pytest corpus tests, Ruff, Pyright.

## Global Constraints

- Implement only `PARSE-001`.
- Explicit SxE and NxN markers retain precedence.
- `[Batch]` is mandatory; parentheses alone never become episode evidence.
- Reject descending ranges, years, resolution values, and spans larger than `_MAX_RANGE_SPAN`.
- Remove `xfail` only from the target corpus record.

---

### Task 1: Lock positive and negative policy

**Files:**
- Modify: `tests/parsing_corpus.py:395-400`
- Modify: `tests/test_parsing_edgecases.py`

**Interfaces:**
- Consumes: `extract_episode(filename) -> tuple[list[int], str | None, bool]`

- [ ] **Step 1: Add direct negative cases before production changes**

```python
@pytest.mark.parametrize(
    "name",
    [
        "Show Name (01-12).mkv",
        "Show Name (1999-2010) [Batch].mkv",
        "Show Name (12-01) [Batch].mkv",
        "Show Name (01-24) [Batch].mkv",
        "Show Name (1080-1081) [Batch].mkv",
    ],
)
def test_parenthesized_numbers_require_a_safe_batch_range(name: str) -> None:
    episodes, _title, _relative = extract_episode(name)
    assert episodes == []
```

- [ ] **Step 2: Run the target corpus record and confirm RED**

Run: `.venv\Scripts\python.exe -m pytest tests\test_parsing_corpus.py -q -k "Show_Name_01_12"`
Expected: XFAIL under the current strict corpus marker.

- [ ] **Step 3: Commit the passing negative guards**

```powershell
git add tests/parsing_corpus.py tests/test_parsing_edgecases.py
git commit -m "test: define parenthesized batch range policy"
```

### Task 2: Add the guarded raw-stem parser

**Files:**
- Modify: `plex_renamer/_parsing_episodes.py`
- Modify: `tests/parsing_corpus.py:395-400`

**Interfaces:**
- Produces: `_parse_parenthesized_batch_range(raw_stem: str) -> _EpisodeParse | None`

- [ ] **Step 1: Add the parser with explicit claim rules**

```python
def _parse_parenthesized_batch_range(raw_stem: str) -> _EpisodeParse | None:
    if re.search(r"\[\s*batch\s*\]", raw_stem, re.IGNORECASE) is None:
        return None
    match = re.search(r"\((\d{1,3})-(\d{1,3})\)", raw_stem)
    if match is None:
        return None
    start = int(match.group(1))
    end = int(match.group(2))
    if (
        start in RESOLUTION_NUMBERS
        or end in RESOLUTION_NUMBERS
        or YEAR_MIN <= start <= YEAR_MAX
        or YEAR_MIN <= end <= YEAR_MAX
        or end <= start
        or end - start > _MAX_RANGE_SPAN
    ):
        return [], None, False
    return list(range(start, end + 1)), None, False
```

- [ ] **Step 2: Insert the branch after `_parse_nxn` using `raw_stem`**

```python
for branch, arg in (
    (_parse_sxe, name),
    (_parse_nxn, name),
    (_parse_parenthesized_batch_range, raw_stem),
    (_parse_air_date, name),
```

- [ ] **Step 3: Remove `xfail` from only the batch-range record**

Keep its expected episodes `[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]` and rewrite the note as a supported policy statement.

- [ ] **Step 4: Run RED/GREEN and parser regressions**

Run: `.venv\Scripts\python.exe -m pytest tests\test_parsing_corpus.py tests\test_parsing_edgecases.py tests\test_parsing_parts.py -q`
Expected: PASS with no XPASS.

- [ ] **Step 5: Format, type-check, and commit**

Run: `.venv\Scripts\ruff.exe format plex_renamer\_parsing_episodes.py tests\test_parsing_edgecases.py tests\parsing_corpus.py && .venv\Scripts\ruff.exe check plex_renamer\_parsing_episodes.py tests\test_parsing_edgecases.py tests\parsing_corpus.py && .venv\Scripts\pyright.exe plex_renamer\_parsing_episodes.py tests\test_parsing_edgecases.py`
Expected: all commands exit 0.

```powershell
git add plex_renamer/_parsing_episodes.py tests/parsing_corpus.py tests/test_parsing_edgecases.py
git commit -m "feat: parse guarded parenthesized batch ranges"
```

### Task 3: Close `PARSE-001`

**Files:**
- Modify: `docs/deferred-work.md`

- [ ] **Step 1: Remove `PARSE-001` and update the P2 summary**

- [ ] **Step 2: Run the full parsing suite**

Run: `.venv\Scripts\python.exe -m pytest tests\test_parsing_corpus.py tests\test_parsing_edgecases.py tests\test_parsing_parts.py -q`
Expected: PASS.

- [ ] **Step 3: Commit**

```powershell
git add docs/deferred-work.md
git commit -m "docs: close parenthesized batch parsing debt"
```
