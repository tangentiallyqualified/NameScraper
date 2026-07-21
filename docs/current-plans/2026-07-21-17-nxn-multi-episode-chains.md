# NxN Multi-Episode Chains Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parse shared-season `1x01x02` chains as episodes 1 and 2 while rejecting malformed or mixed-season chains.

**Architecture:** Extend the initial NxN matcher to consume one or more same-season episode suffixes before processing dash ranges. Mirror the SxE parser's distinction between explicit points and a dash-introduced range. Update season extraction, TV classification, and title-prefix inference with the same chain grammar.

**Tech Stack:** Python 3.14, regular expressions, pytest corpus tests, Ruff, Pyright.

## Global Constraints

- Implement only `PARSE-005`.
- All chained episodes share the first season.
- Explicit chain points remain verbatim; only a lone dash endpoint expands a range.
- Reject empty suffixes, mixed-season syntax, and alphabetic continuations.
- Remove `xfail` only from the `1x01x02` corpus record.

---

### Task 1: Lock chain and malformed-chain policy

**Files:**
- Modify: `tests/test_parsing_edgecases.py`
- Modify later: `tests/parsing_corpus.py:692-698`

- [ ] **Step 1: Add parsing and classification tables**

```python
@pytest.mark.parametrize(
    ("name", "episodes", "season"),
    [
        ("Show.Name.1x01x02.mkv", [1, 2], 1),
        ("Show.Name.2x003x005.mkv", [3, 5], 2),
        ("Show.Name.1x01x02-04.mkv", [1, 2, 4], 1),
    ],
)
def test_nxn_shared_season_chains(name: str, episodes: list[int], season: int) -> None:
    parsed, _title, relative = extract_episode(name)
    assert parsed == episodes
    assert extract_season_number(name) == season
    assert relative is True
    assert looks_like_tv_episode(Path(name)) is True


@pytest.mark.parametrize(
    "name",
    [
        "Show.Name.1x.mkv",
        "Show.Name.1x01x.mkv",
        "Show.Name.1x01xS02E02.mkv",
        "Show.Name.1x01x02oops.mkv",
    ],
)
def test_malformed_nxn_chains_are_not_extended(name: str) -> None:
    episodes, _title, _relative = extract_episode(name)
    assert episodes != [1, 2]
```

- [ ] **Step 2: Run and confirm RED**

Run: `.venv\Scripts\python.exe -m pytest tests\test_parsing_edgecases.py -q -k nxn`
Expected: shared-season chain cases FAIL or return only the first episode.

### Task 2: Parse explicit points without range expansion

**Files:**
- Modify: `plex_renamer/_parsing_episodes.py`

**Interfaces:**
- Preserves: `_parse_nxn(name: str) -> _EpisodeParse | None`

- [ ] **Step 1: Replace the initial NxN match and point collection**

```python
nxn = re.search(r"\b(\d{1,2})x(\d{2,3}(?:x\d{2,3})*)(?![A-Za-z0-9])", name, re.IGNORECASE)
if nxn is None:
    return None
season_prefix = nxn.group(1)
points = [int(value) for value in nxn.group(2).split("x")]
initial_count = len(points)
rest = name[nxn.end() :]
```

- [ ] **Step 2: Preserve explicit points in the range rule**

```python
if initial_count == 1 and len(points) == 2 and points[1] - points[0] > 1:
    episodes = _expand_range(points[0], points[1])
else:
    episodes = points
```

Retain the current dash-segment loop so `1x01-1x04` continues to expand while `1x01x02-04` stays `[1, 2, 4]`.

- [ ] **Step 3: Widen `extract_season_number` to the same grammar**

Use `r"\b(\d{1,2})x\d{2,3}(?:x\d{2,3})*(?:\s*-\s*(?:\d{1,2}x)?\d{2,3})?(?!\d)"`.

### Task 3: Keep classification and title extraction aligned

**Files:**
- Modify: `plex_renamer/_parsing_tv.py`
- Modify: `tests/parsing_corpus.py:692-698`

- [ ] **Step 1: Update the NxN classifier and prefix patterns**

Use `\b\d{1,2}x\d{2,3}(?:x\d{2,3})*\b` in `_TV_EPISODE_PATTERNS` and `_PREFIX_EPISODE_MARKER_RE`. Use the equivalent repeated-suffix grammar in the NxN `_TV_TITLE_PREFIX_PATTERNS` entry.

- [ ] **Step 2: Remove the target corpus `xfail`**

Keep episodes `[1, 2]`, season `1`, and `is_tv=True`; update the note to a supported convention.

- [ ] **Step 3: Run focused and complete parser tests**

Run: `.venv\Scripts\python.exe -m pytest tests\test_parsing_corpus.py tests\test_parsing_edgecases.py tests\test_parsing_parts.py -q`
Expected: PASS with no XPASS.

- [ ] **Step 4: Format/type-check and commit**

Run: `.venv\Scripts\ruff.exe format plex_renamer\_parsing_episodes.py plex_renamer\_parsing_tv.py tests\test_parsing_edgecases.py tests\parsing_corpus.py && .venv\Scripts\ruff.exe check plex_renamer\_parsing_episodes.py plex_renamer\_parsing_tv.py tests\test_parsing_edgecases.py tests\parsing_corpus.py && .venv\Scripts\pyright.exe plex_renamer\_parsing_episodes.py plex_renamer\_parsing_tv.py tests\test_parsing_edgecases.py`
Expected: all commands exit 0.

```powershell
git add plex_renamer/_parsing_episodes.py plex_renamer/_parsing_tv.py tests/parsing_corpus.py tests/test_parsing_edgecases.py
git commit -m "feat: parse shared-season NxN chains"
```

### Task 4: Close `PARSE-005`

**Files:**
- Modify: `docs/deferred-work.md`

- [ ] **Step 1: Remove `PARSE-005` and update the P2 summary**

- [ ] **Step 2: Run `scripts\test-smoke.cmd`**
Expected: PASS.

- [ ] **Step 3: Commit**

```powershell
git add docs/deferred-work.md
git commit -m "docs: close NxN chain parsing debt"
```
