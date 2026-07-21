# OVA Number Disambiguation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prefer an explicit OVA/OAD/ONA episode suffix over numeric title tokens in filenames such as `Area.88.OVA.01.mkv`.

**Architecture:** Add a narrow marker-aware parser before generic bare-number parsing. It claims only a number immediately following the OVA/OAD/ONA token and preserves absolute numbering, while year and resolution guards remain active.

**Tech Stack:** Python 3.14, regular expressions, pytest corpus tests, Ruff, Pyright.

## Global Constraints

- Implement only `PARSE-002`.
- Do not reinterpret unmarked title numbers.
- Recognize `OVA`, `OAD`, and `ONA` case-insensitively.
- Reject year-shaped and resolution-shaped suffixes.
- Remove `xfail` only from the `Area.88.OVA.01` corpus record.

---

### Task 1: Define ambiguity guards

**Files:**
- Modify: `tests/test_parsing_edgecases.py`
- Modify later: `tests/parsing_corpus.py:663-667`

- [ ] **Step 1: Add direct policy tests**

```python
@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Area.88.OVA.01.mkv", [1]),
        ("Project.A-Ko.OVA.02.mkv", [2]),
        ("Title.OAD.03v2.mkv", [3]),
        ("ONA.2007.1080p.mkv", []),
        ("OVA.1080.mkv", []),
        ("Area.88.2004.1080p.mkv", []),
    ],
)
def test_ova_marker_disambiguates_episode_suffix(name: str, expected: list[int]) -> None:
    episodes, _title, relative = extract_episode(name)
    assert episodes == expected
    assert relative is False
```

- [ ] **Step 2: Run and confirm the marked positives are RED**

Run: `.venv\Scripts\python.exe -m pytest tests\test_parsing_edgecases.py -q -k ova_marker`
Expected: at least `Area.88.OVA.01.mkv` FAILS because the bare parser currently selects 88.

### Task 2: Add marker-aware parsing before bare numbers

**Files:**
- Modify: `plex_renamer/_parsing_episodes.py`
- Modify: `tests/parsing_corpus.py:663-667`

**Interfaces:**
- Produces: `_parse_ova_suffix(name: str) -> _EpisodeParse | None`

- [ ] **Step 1: Add the exact helper**

```python
def _parse_ova_suffix(name: str) -> _EpisodeParse | None:
    match = re.search(r"\b(?:OVA|OAD|ONA)[\s._-]+(\d{1,3})(?:v\d+)?\b", name, re.IGNORECASE)
    if match is None:
        return None
    episode = int(match.group(1))
    if episode in RESOLUTION_NUMBERS or YEAR_MIN <= episode <= YEAR_MAX:
        return [], None, False
    return [episode], None, False
```

- [ ] **Step 2: Insert `_parse_ova_suffix` after explicit episode chains and before `_parse_bare_number`**

The branch must precede `_parse_bare_number`; no generic parser ordering changes are allowed.

- [ ] **Step 3: Remove the target `xfail` and update its note**

- [ ] **Step 4: Run focused and full parser suites**

Run: `.venv\Scripts\python.exe -m pytest tests\test_parsing_edgecases.py tests\test_parsing_corpus.py tests\test_parsing_parts.py -q`
Expected: PASS with no XPASS.

- [ ] **Step 5: Format/type-check and commit**

Run: `.venv\Scripts\ruff.exe format plex_renamer\_parsing_episodes.py tests\test_parsing_edgecases.py tests\parsing_corpus.py && .venv\Scripts\ruff.exe check plex_renamer\_parsing_episodes.py tests\test_parsing_edgecases.py tests\parsing_corpus.py && .venv\Scripts\pyright.exe plex_renamer\_parsing_episodes.py tests\test_parsing_edgecases.py`
Expected: all commands exit 0.

```powershell
git add plex_renamer/_parsing_episodes.py tests/parsing_corpus.py tests/test_parsing_edgecases.py
git commit -m "fix: prefer marked OVA episode suffixes"
```

### Task 3: Close `PARSE-002`

**Files:**
- Modify: `docs/deferred-work.md`

- [ ] **Step 1: Remove `PARSE-002` and update the P2 summary**

- [ ] **Step 2: Run `scripts\test-smoke.cmd`**
Expected: PASS.

- [ ] **Step 3: Commit**

```powershell
git add docs/deferred-work.md
git commit -m "docs: close OVA number ambiguity debt"
```
