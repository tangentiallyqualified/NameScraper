# Dotted Version Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent movie/version tokens such as `Evangelion.1.11...2007` from producing phantom episode assignments.

**Architecture:** Add a raw-stem guard that claims dotted decimal versions only when a later release year confirms movie-style context. Place it before generic leading/bare numeric parsing, leaving explicit SxE, NxN, and episode-marker forms untouched.

**Tech Stack:** Python 3.14, regular expressions, pytest corpus tests, Ruff, Pyright.

## Global Constraints

- Implement only `PARSE-003`.
- A dotted decimal alone is insufficient; a later plausible year is required.
- Explicit SxE/NxN/Episode markers retain precedence.
- Preserve leading `NN. Title (YYYY)` episode behavior.
- Remove `xfail` only from the Evangelion version corpus record.

---

### Task 1: Lock movie-versus-episode examples

**Files:**
- Modify: `tests/test_parsing_edgecases.py`
- Modify later: `tests/parsing_corpus.py:669-675`

- [ ] **Step 1: Add the decision table**

```python
@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Evangelion.1.11.You.Are.Not.Alone.2007.1080p.mkv", []),
        ("Movie.2.22.Version.2009.1080p.mkv", []),
        ("01. Pilot (2007).mkv", [1]),
        ("Show.S01E11.2007.1080p.mkv", [11]),
        ("Show.1x11.2007.1080p.mkv", [11]),
    ],
)
def test_dotted_versions_do_not_override_explicit_episode_forms(
    name: str, expected: list[int]
) -> None:
    episodes, _title, _relative = extract_episode(name)
    assert episodes == expected
```

- [ ] **Step 2: Run and confirm RED**

Run: `.venv\Scripts\python.exe -m pytest tests\test_parsing_edgecases.py -q -k dotted_versions`
Expected: the two movie-version cases FAIL with phantom episode numbers.

### Task 2: Add the guarded terminal parse

**Files:**
- Modify: `plex_renamer/_parsing_episodes.py`
- Modify: `tests/parsing_corpus.py:669-675`

**Interfaces:**
- Produces: `_parse_dotted_movie_version(raw_stem: str) -> _EpisodeParse | None`

- [ ] **Step 1: Add the raw-stem guard**

```python
def _parse_dotted_movie_version(raw_stem: str) -> _EpisodeParse | None:
    version = re.search(r"(?<!\d)(\d{1,2})\.(\d{2})(?!\d)", raw_stem)
    if version is None:
        return None
    later_text = raw_stem[version.end() :]
    if re.search(r"(?<!\d)(?:19|20)\d{2}(?!\d)", later_text) is None:
        return None
    return [], None, False
```

- [ ] **Step 2: Run it after explicit marker branches and before `_parse_leading_number_dot`**

Use `raw_stem` as the argument. This preserves explicit markers while preventing the later generic numeric branches from claiming the version.

- [ ] **Step 3: Remove the target `xfail` and retain `year="2007"`, `is_tv=False`**

- [ ] **Step 4: Run parsing regressions**

Run: `.venv\Scripts\python.exe -m pytest tests\test_parsing_corpus.py tests\test_parsing_edgecases.py tests\test_parsing_parts.py -q`
Expected: PASS with no XPASS.

- [ ] **Step 5: Format/type-check and commit**

Run: `.venv\Scripts\ruff.exe format plex_renamer\_parsing_episodes.py tests\test_parsing_edgecases.py tests\parsing_corpus.py && .venv\Scripts\ruff.exe check plex_renamer\_parsing_episodes.py tests\test_parsing_edgecases.py tests\parsing_corpus.py && .venv\Scripts\pyright.exe plex_renamer\_parsing_episodes.py tests\test_parsing_edgecases.py`
Expected: all commands exit 0.

```powershell
git add plex_renamer/_parsing_episodes.py tests/parsing_corpus.py tests/test_parsing_edgecases.py
git commit -m "fix: suppress dotted movie version episodes"
```

### Task 3: Close `PARSE-003`

**Files:**
- Modify: `docs/deferred-work.md`

- [ ] **Step 1: Remove `PARSE-003` and update the P2 summary**

- [ ] **Step 2: Run `scripts\test-smoke.cmd`**
Expected: PASS.

- [ ] **Step 3: Commit**

```powershell
git add docs/deferred-work.md
git commit -m "docs: close dotted version parsing debt"
```
