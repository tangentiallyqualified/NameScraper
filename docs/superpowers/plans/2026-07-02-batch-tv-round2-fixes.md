# Batch TV Round-2 Fixes (RC16–RC28) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the 13 root causes (RC16–RC28) from [2026-07-02-batch-tv-bug-investigation-round2.md](2026-07-02-batch-tv-bug-investigation-round2.md) so the real library at `P:\data\downloads\in progress files` scans without wrong auto-accepts, phantom conflicts, or unmapped titled files.

**Architecture:** Parsing/normalization fixes land first (they shrink the blast radius of everything downstream), then episode-resolution policy changes in `plex_renamer/engine/_episode_resolution.py`, then the consolidated-scan rewrite, then duplicate-copy projection/GUI, then show scoring. Every new review-confidence path uses the existing `CONF_TITLE_WINS_INEXACT` (0.70) lock mechanism.

**Tech Stack:** Python 3.12 (repo venv `.venv`), pytest, PySide6 (GUI layer), TMDB API (live validation only).

## Global Constraints

- All commands run through the repo venv: `.venv\Scripts\python.exe -m pytest …` (PowerShell). `scripts\test-fast.cmd` runs the fast suite; `scripts\test-smoke.cmd` runs Qt smoke.
- Tests use `tmp_path` and synthetic titles — NEVER hardcode `P:\` media paths in anything that runs as part of the test suite (established project rule). The real library path `P:\data\downloads\in progress files` may appear ONLY in `scripts/scan_real_library.py`, which is run on request; that drive is not always mounted.
- ALL episode-confidence constants live in `plex_renamer/engine/_episode_resolution.py`; do not define confidence values elsewhere.
- Episode preview status strings are minted ONLY in `plex_renamer/engine/_episode_projection.py`.
- Every new evidence tag that must never auto-accept MUST be added to the review-lock set at the bottom of `apply_confidence_adjustments` (`_episode_resolution.py:829-836`).
- Thresholds (do not change): episode auto-accept 0.85, user show auto-accept 0.82 (settings.json), engine default 0.55.
- **RC29 (Reno revival lives under different TMDB entries) is explicitly DEFERRED** — the findings doc marks it a longer-term option; RC18c+d and RC27 fixes stop the catastrophic interleaving. Do not implement alternate-entry probing in this plan.
- Real-library validation harness: `scripts/scan_real_library.py` (already committed alongside this plan). It needs the `P:` drive and a TMDB key; dumps go to `.scan-dumps\` (gitignored).

## Executor learning / verification notes

Things the executor must verify against reality rather than trust from this plan:

1. **Live TMDB titles and air dates** back many expectations (CatDog S2E35 'Sumo Enchanted Evening', Oshi no Ko 35-slot season split 11+13+11, Doctor Who S00E85/E86 prequel titles). Unit tests use synthetic fixtures, so this only matters for the final harness validation — read the actual dump output, don't pattern-match on this doc.
2. Before Task 4 (signature/normalization changes) grep tests for direct callers: `.venv\Scripts\python.exe -m pytest --collect-only -q` after each change and `Grep "match_segmented_title_run|normalize_for_specials" tests/` — existing expectations on `&`-titles will need updating.
3. The GUI auto-accept thresholds come from the user's `settings.json`; the harness prints the thresholds it ran with in `discovery.txt` — check them before interpreting `needs_review` flags.
4. The harness run takes several minutes (live TMDB, ~21 shows). Run it once at the end (Task 19), not per task.

---

### Task 1: RC17 — strip release junk from extracted episode titles

`extract_episode` keeps trailing junk in titles (`'Execution 1080p CR WEB-DL DUAL AAC2 0 H 264-VARYG'`, `'… Toon REPACK'`), degrading exact title evidence to substring (0.90) and breaking segmented-run matching. Truncate extracted titles at the first release-noise token (same strategy `clean_folder_name` uses).

**Files:**
- Modify: `plex_renamer/_parsing_titles.py` (add `strip_release_junk_title` after `clean_title_evidence`)
- Modify: `plex_renamer/_parsing_episodes.py` (wrap every title return)
- Test: `tests/test_release_junk_titles.py` (new)

**Interfaces:**
- Produces: `strip_release_junk_title(title: str | None) -> str | None` in `_parsing_titles.py`. All titles returned by `extract_episode` are junk-free from this task on (Tasks 2–18 rely on this).

- [ ] **Step 1: Write the failing tests**

```python
"""RC17: release junk must not survive in extracted episode titles."""
from plex_renamer.parsing import extract_episode
from plex_renamer._parsing_titles import strip_release_junk_title


def test_strip_helper_truncates_at_first_noise_token():
    assert (
        strip_release_junk_title("Execution 1080p CR WEB-DL DUAL AAC2 0 H 264-VARYG")
        == "Execution"
    )
    assert (
        strip_release_junk_title("De-Zanitized, The Monkey Song & Nighty-Night Toon REPACK")
        == "De-Zanitized, The Monkey Song & Nighty-Night Toon"
    )
    assert strip_release_junk_title("1080p x265") is None
    assert strip_release_junk_title(None) is None
    assert strip_release_junk_title("Armed and Dangerous") == "Armed and Dangerous"


def test_sxe_title_strips_release_junk():
    eps, title, rel = extract_episode(
        "Jujutsu.Kaisen.S03E01.Execution.1080p.CR.WEB-DL.DUAL.AAC2.0.H.264-VARYG.mkv"
    )
    assert eps == [1]
    assert rel is True
    assert title == "Execution"


def test_repack_title_stripped_for_segmented_run():
    _, title, _ = extract_episode(
        "Animaniacs.1993.S01E01.De-Zanitized,.The.Monkey.Song.&.Nighty-Night.Toon.REPACK.1080p.mkv"
    )
    assert title == "De-Zanitized, The Monkey Song & Nighty-Night Toon"


def test_part_title_survives_junk_strip():
    _, title, _ = extract_episode(
        "Archer.2009.S00E04.Heart.of.Archness.Part.1.1080p.NF.WEB-DL.DDP5.1.AV1-DBMS.mkv"
    )
    assert title == "Heart of Archness Part 1"


def test_clean_title_untouched():
    eps, title, rel = extract_episode("Show - S01E05 - Armed and Dangerous.mkv")
    assert eps == [5] and title == "Armed and Dangerous"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests\test_release_junk_titles.py -q`
Expected: FAIL (ImportError on `strip_release_junk_title`, then assertion failures on junk-bearing titles).

- [ ] **Step 3: Implement the helper in `_parsing_titles.py`** (after `clean_title_evidence`)

```python
def strip_release_junk_title(title: str | None) -> str | None:
    """Truncate an extracted episode title at the first release-noise token.

    Episode titles pulled from release filenames keep trailing junk
    ("Execution 1080p CR WEB-DL …"), downgrading exact title evidence to
    substring matches. Token-walk left-to-right and cut at the first
    release-noise token (same strategy as clean_folder_name). Returns None
    when nothing survives.
    """
    if not title:
        return None
    kept: list[str] = []
    for token in title.split():
        if _is_release_noise_token(token):
            break
        kept.append(token)
    result = " ".join(kept).strip(" -–")
    return result or None
```

- [ ] **Step 4: Apply it to every title return in `_parsing_episodes.py`**

Add the import at the top: `from ._parsing_titles import clean_name, clean_title_evidence, strip_release_junk_title` and wrap the five title-producing sites:

- S##E## branch (`line ~87`): `title = strip_release_junk_title(re.sub(r"^\s*[-.]?\s*", "", rest).strip() or None)`
- NxNN branch (`line ~114`): same wrap.
- Dash-delimited branch (`line ~131`): `title = strip_release_junk_title(match.group(3).strip()) if match.group(3) else None`
- `bare_match` branch (`line ~140`): `return [num], strip_release_junk_title(title_text), False`
- Ep##/generic branches (`lines ~150, ~168`): `title = strip_release_junk_title(match.group(2).strip()) if match.group(2) else None`

- [ ] **Step 5: Run the new tests + parsing regression files**

Run: `.venv\Scripts\python.exe -m pytest tests\test_release_junk_titles.py tests\test_parsing_edgecases.py tests\test_scan_improvements.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```
git add plex_renamer/_parsing_titles.py plex_renamer/_parsing_episodes.py tests/test_release_junk_titles.py
git commit -m "fix: strip release junk from extracted episode titles (RC17)"
```

---

### Task 2: RC27 — capture titles after bare `E##`/`##.` prefixes

`extract_episode("E01.He's Not the Messiah, He's a DJ.mkv")` returns `title=None` because the dot separator became a space before the Ep-branch ran, and `bare_match` requires a space after the dot. Lucy's 11 files park at 0.80 review instead of rule-1 0.96 auto; Reno's Complete Series loses its title anchors.

**Files:**
- Modify: `plex_renamer/_parsing_episodes.py:134,142-151`
- Test: `tests/test_bare_episode_prefix_titles.py` (new)

**Interfaces:**
- Produces: `extract_episode` returns the remainder as `title` for `E##.Title`, `E## Title`, `Episode ## Title`, and `##.Title` stems. `is_season_relative` stays `False` for these forms.

- [ ] **Step 1: Write the failing tests**

```python
"""RC27: E##.Title / ##.Title filenames must keep their title evidence."""
from plex_renamer.parsing import extract_episode


def test_e_prefix_dot_title():
    eps, title, rel = extract_episode("E01.He's Not the Messiah, He's a DJ.mkv")
    assert eps == [1]
    assert title == "He's Not the Messiah, He's a DJ"
    assert rel is False


def test_e_prefix_reno_pilot():
    eps, title, _ = extract_episode("E01.The Pilot.mkv")
    assert eps == [1] and title == "The Pilot"


def test_bare_number_dot_no_space():
    eps, title, _ = extract_episode("01.The Pilot.mkv")
    assert eps == [1] and title == "The Pilot"


def test_episode_word_space_title():
    eps, title, _ = extract_episode("Episode 5 The Great Escape.mkv")
    assert eps == [5] and title == "The Great Escape"


def test_no_title_still_none():
    eps, title, _ = extract_episode("Episode 5.mkv")
    assert eps == [5] and title is None


def test_sxe_still_wins():
    eps, title, rel = extract_episode("Show S02E03 Some Title.mkv")
    assert eps == [3] and rel is True
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests\test_bare_episode_prefix_titles.py -q`
Expected: FAIL — `title is None` for the E-prefix and no-space-dot cases.

- [ ] **Step 3: Implement**

In `_parsing_episodes.py`:

1. `bare_match` (line ~134): change the regex from `r"(\d{1,3})\.\s+(.*)"` to `r"(\d{1,3})\.\s*(.*)"` (allow no space after the dot).
2. Ep-branch (line ~142-146): change the pattern so a plain-whitespace separator (the ghost of a dot) also captures the title:

```python
    match = re.search(
        r"\b(?:ep?|episode)\s*(\d{1,3})(?!\d)(?:(?:\s*[-._]+\s*|\s+)(.*))?",
        name,
        re.IGNORECASE,
    )
```

(The generic bare-number branch at line ~153 keeps its `[-._]+`-only separator — a plain space after an unmarked number is title text, not a separator.)

- [ ] **Step 4: Run new tests + parsing regressions**

Run: `.venv\Scripts\python.exe -m pytest tests\test_bare_episode_prefix_titles.py tests\test_release_junk_titles.py tests\test_parsing_edgecases.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```
git commit -am "fix: capture episode titles after bare E##/##. prefixes (RC27)"
```

---

### Task 3: RC20(1)+RC24(a)+RC16(c) — symbol/notation folding in title normalization

`'&'` vs `'and'`, `'#1'` vs `'No. 1'`, superscript digits, and `"I'm"` vs `"I am"` defeat exact matching (Doctor Who 'Love & Monsters', Angry Beavers 'H²-Whoa!', 'Dagski & Norb'). Apostrophes split show-title tokens (`"Hell's"` → `"hell s"`).

**Files:**
- Modify: `plex_renamer/_parsing_names.py:123-147`
- Modify: `plex_renamer/parsing.py` (export `normalize_for_specials_spaced`)
- Test: `tests/test_symbol_folding.py` (new)

**Interfaces:**
- Produces: `_fold_title_symbols(text: str) -> str` and `normalize_for_specials_spaced(text: str) -> str` in `_parsing_names.py`; the latter exported from `plex_renamer.parsing`. `normalize_for_specials` now folds symbols before compacting. `normalize_for_match` removes apostrophes instead of spacing them. Task 4's fuzzy helpers consume `normalize_for_specials_spaced`.

- [ ] **Step 1: Write the failing tests**

```python
"""RC20(1)/RC24(a)/RC16(c): notation variants must normalize identically."""
from plex_renamer.parsing import normalize_for_match, normalize_for_specials
from plex_renamer._parsing_names import normalize_for_specials_spaced


def test_ampersand_folds_to_and():
    assert normalize_for_specials("Love & Monsters") == normalize_for_specials("Love and Monsters")
    assert normalize_for_specials("Dagski & Norb") == normalize_for_specials("Dagski and Norb")


def test_superscript_digits_fold():
    assert normalize_for_specials("H²-Whoa!") == normalize_for_specials("H-2 Whoa")


def test_contraction_and_number_sign_fold():
    assert normalize_for_specials(
        "I Am Not an Animal, I'm Scientist #1"
    ) == normalize_for_specials("I'm Not an Animal... I'm Scientist No. 1")


def test_apostrophe_folds_in_match_normalization():
    assert normalize_for_match("Hell's Paradise") == "hells paradise"
    assert normalize_for_match("Hells Paradise") == "hells paradise"


def test_spaced_form_keeps_tokens():
    assert normalize_for_specials_spaced("Tokyo Colony No. 1 (3)") == "tokyo colony number 1 3"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests\test_symbol_folding.py -q`
Expected: FAIL (ImportError for `normalize_for_specials_spaced`, then mismatched normalizations).

- [ ] **Step 3: Implement in `_parsing_names.py`**

Replace `normalize_for_match` / `normalize_for_specials` with:

```python
_SUPERSCRIPT_DIGITS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")


def _fold_title_symbols(text: str) -> str:
    """Fold notation variants ('&' vs 'and', '#1' vs 'No. 1', 'H²', "I'm")
    to one spelling so title comparison is notation-blind. Applied before
    punctuation stripping so contractions still carry their apostrophes."""
    text = text.translate(_SUPERSCRIPT_DIGITS)
    text = re.sub(r"\b[Ii]['’]m\b", "I am", text)
    text = text.replace("&", " and ")
    text = re.sub(r"#\s*(?=\d)", " number ", text)
    text = re.sub(r"\bno\.?\s*(?=\d)", " number ", text, flags=re.IGNORECASE)
    return text


def normalize_for_match(text: str) -> str:
    """
    Normalize a title for fuzzy comparison.

    Strips year suffixes, punctuation, articles, and extra whitespace.
    Apostrophes are REMOVED (not spaced) so "Hell's" == "Hells".
    Returns lowercase with single spaces.
    """
    text = re.sub(r"\s*\(\d{4}\)\s*$", "", text)
    text = text.replace("’", "'").replace("'", "")
    text = re.sub(r"[^\w\s]", " ", text)
    text = text.lower().strip()
    text = re.sub(r"^(?:the|a|an)\s+", "", text)
    return re.sub(r"\s+", " ", text)


def normalize_for_specials_spaced(text: str) -> str:
    """Symbol-folded, space-tokenized normal form (for token-level fuzzy)."""
    return normalize_for_match(_fold_title_symbols(text))


def normalize_for_specials(text: str) -> str:
    """
    Normalize text for specials/extras fuzzy matching.

    Symbol folding + normalize_for_match, then strip everything except
    lowercase alphanumerics for substring matching.
    """
    text = normalize_for_specials_spaced(text)
    return re.sub(r"[^a-z0-9]", "", text)
```

Add `normalize_for_specials_spaced` to the `_parsing_names` import list in `plex_renamer/parsing.py`.

- [ ] **Step 4: Run new tests, then the FULL fast suite** (normalization touches everything)

Run: `.venv\Scripts\python.exe -m pytest tests\test_symbol_folding.py -q` → PASS.
Run: `scripts\test-fast.cmd`
Expected: PASS. If existing tests assert old normalizations of `&`/apostrophe titles, update those expectations (they now fold) — do NOT weaken the new behavior.

- [ ] **Step 5: Commit**

```
git commit -am "fix: fold symbol/notation variants in title normalization (RC20-1, RC24a, RC16c)"
```

---

### Task 4: RC20(2) — bounded fuzzy title matching + fuzzy segmented runs

One-character typos ('Curiou**s**ity', 'Bringin''), token-growth ('Friend' vs 'Friendship'), and reordered tokens ('Tokyo No 1 Colony Part 1' vs 'Tokyo Colony No. 1 (1)') defeat exact/substring matching. Add a bounded fuzzy tier to `match_title_in_titles` and to segmented-run atoms — at review confidence when inexact.

**Files:**
- Modify: `plex_renamer/engine/_episode_resolution.py` (fuzzy helpers, `match_title_in_titles`, `match_segmented_title_run` **signature change**, `resolve_file`, `_shift_run_off_segmented_conflict`, `_claim_strength`, review locks)
- Test: `tests/test_fuzzy_title_matching.py` (new)

**Interfaces:**
- Consumes: `normalize_for_specials_spaced` (Task 3).
- Produces:
  - `_TITLE_FUZZY = 0.86` (module constant).
  - `_fuzzy_title_equal(input_compact: str, input_spaced: str, key_compact: str, key_spaced: str) -> bool`.
  - `match_title_in_titles` may return `TitleMatch(strength=_TITLE_FUZZY)`.
  - **CHANGED:** `match_segmented_title_run(raw_title, titles, expected_count) -> tuple[tuple[int, ...], bool] | None` — now returns `(run, all_exact)`. Grep and update every caller and test.
  - New evidence tag `"title-fuzzy"` (review-locked, `_claim_strength` tier 2).

- [ ] **Step 1: Grep for callers of the changing signature**

Run: `.venv\Scripts\python.exe -m pytest --collect-only -q > NUL` then Grep `match_segmented_title_run` across `plex_renamer/` and `tests/`. Callers today: `resolve_file` (×2), `_shift_run_off_segmented_conflict`, plus any tests. List them; all get updated in Step 4.

- [ ] **Step 2: Write the failing tests**

```python
"""RC20(2): bounded fuzzy matching for titles and segmented-run atoms."""
from plex_renamer.engine._episode_resolution import (
    _TITLE_FUZZY,
    CONF_AGREE,
    CONF_TITLE_WINS_INEXACT,
    match_segmented_title_run,
    match_title_in_titles,
    resolve_file,
)


def test_single_typo_fuzzy_match():
    titles = {37: "Neferkitty", 38: "Curiosity Almost Killed The Cat"}
    match = match_title_in_titles("Curiousity Almost Killed The Cat", titles)
    assert match is not None
    assert match.episode == 38
    assert match.strength == _TITLE_FUZZY


def test_token_prefix_fuzzy_match():
    titles = {10: "Friendship Alliance", 11: "Vice Mayor"}
    match = match_title_in_titles("Friend Alliance", titles)
    assert match is not None and match.episode == 10


def test_token_reorder_with_part_words():
    titles = {5: "Tokyo Colony No. 1 (3)", 6: "Tokyo Colony No. 1 (4)"}
    match = match_title_in_titles("Tokyo No 1 Colony Part 3", titles)
    assert match is not None and match.episode == 5


def test_ambiguous_fuzzy_returns_none():
    titles = {1: "The Cat", 2: "The Bat"}
    assert match_title_in_titles("The Hat", titles) is None


def test_segmented_run_with_fuzzy_atom():
    titles = {1: "To the Moon", 2: "Bringing Down the Mouse", 3: "Unicorn Club"}
    seg = match_segmented_title_run(
        "To The Moon & Bringin' Down The Mouse", titles, 2,
    )
    assert seg is not None
    run, all_exact = seg
    assert run == (1, 2)
    assert all_exact is False


def test_segmented_run_exact_flag_true():
    titles = {1: "To the Moon", 2: "Bringing Down the Mouse"}
    seg = match_segmented_title_run("To the Moon & Bringing Down the Mouse", titles, 2)
    assert seg == ((1, 2), True)


def test_resolve_file_fuzzy_run_is_review():
    titles = {1: "To the Moon", 2: "Bringing Down the Mouse", 3: "Unicorn Club", 4: "Go Gomez Go"}
    resolution = resolve_file(
        parsed_episodes=(1,),
        raw_title="To The Moon & Bringin' Down The Mouse",
        is_season_relative=True,
        season_titles=titles,
        season=1,
    )
    assert resolution.episodes == (1, 2)
    assert resolution.confidence == CONF_TITLE_WINS_INEXACT
    assert "title-fuzzy" in resolution.evidence
```

- [ ] **Step 3: Run to verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests\test_fuzzy_title_matching.py -q`
Expected: FAIL (`_TITLE_FUZZY` ImportError; fuzzy matches return None; seg-run returns a bare tuple).

- [ ] **Step 4: Implement in `_episode_resolution.py`**

Add after the calibration constants:

```python
_TITLE_FUZZY = 0.86          # unique bounded-fuzzy title hit (typos, variants)
_MIN_FUZZY_LEN = 6           # minimum compacted length for edit-distance fuzz
```

Add import: `normalize_for_specials_spaced` from `..parsing`.

Add helpers before `match_title_in_titles`:

```python
def _edit_distance_at_most(a: str, b: str, limit: int) -> bool:
    """Banded Levenshtein: True when edit distance <= limit."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > limit:
        return False
    prev = list(range(len(b) + 1))
    for i, ch_a in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        best = curr[0]
        for j, ch_b in enumerate(b, 1):
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + (ch_a != ch_b))
            best = min(best, curr[j])
        if best > limit:
            return False
        prev = curr
    return prev[-1] <= limit


def _tokens_prefix_equal(a_spaced: str, b_spaced: str) -> bool:
    """Token-aligned near-equality: same token count, each pair equal or one
    a prefix of the other (shorter side >=3 chars), and >=1 exact pair.
    Catches 'Friend Alliance' vs 'Friendship Alliance'."""
    a_tokens, b_tokens = a_spaced.split(), b_spaced.split()
    if len(a_tokens) != len(b_tokens) or not a_tokens:
        return False
    exact = 0
    for token_a, token_b in zip(a_tokens, b_tokens):
        if token_a == token_b:
            exact += 1
            continue
        short, long_ = (
            (token_a, token_b) if len(token_a) <= len(token_b) else (token_b, token_a)
        )
        if len(short) < 3 or not long_.startswith(short):
            return False
    return exact >= 1


def _token_multisets_equal(a_spaced: str, b_spaced: str) -> bool:
    """Reordered-token equality ignoring part-words ('Tokyo No 1 Colony
    Part 3' vs 'Tokyo Colony No. 1 (3)'). Requires >=3 tokens."""
    strip = {"part", "pt"}
    a = sorted(token for token in a_spaced.split() if token not in strip)
    b = sorted(token for token in b_spaced.split() if token not in strip)
    return len(a) >= 3 and a == b


def _fuzzy_title_equal(
    input_compact: str,
    input_spaced: str,
    key_compact: str,
    key_spaced: str,
) -> bool:
    if (
        len(input_compact) >= _MIN_FUZZY_LEN
        and len(key_compact) >= _MIN_FUZZY_LEN
        and _edit_distance_at_most(input_compact, key_compact, 2)
    ):
        return True
    if _tokens_prefix_equal(input_spaced, key_spaced):
        return True
    return _token_multisets_equal(input_spaced, key_spaced)
```

In `match_title_in_titles`, after the substring tier and before the part-number tier, insert:

```python
    spaced = normalize_for_specials_spaced(raw_text)
    fuzzy_hits = [
        (episode, title)
        for key, (episode, title) in lookup.items()
        if _fuzzy_title_equal(
            normalized, spaced, key, normalize_for_specials_spaced(title),
        )
    ]
    if len(fuzzy_hits) == 1:
        episode, title = fuzzy_hits[0]
        return TitleMatch(episode=episode, title=title, strength=_TITLE_FUZZY)
    if len(fuzzy_hits) > 1:
        return None
```

Rewrite `match_segmented_title_run` to return `(run, all_exact)`:

```python
def match_segmented_title_run(
    raw_title: str | None,
    titles: dict[int, str],
    expected_count: int,
) -> tuple[tuple[int, ...], bool] | None:
    """Resolve a combined multi-segment title into an episode run by titles.

    Returns ``(run, all_exact)``; ``all_exact`` is False when any group
    matched a TMDB title fuzzily — callers must then use review confidence.
    Splits on segment separators, merges adjacent atoms into exactly
    *expected_count* groups, accepts only a unique contiguous result.
    """
    if not raw_title or expected_count < 2 or not titles:
        return None
    spans = _segment_atom_spans(raw_title)
    atom_count = len(spans)
    if atom_count < expected_count or atom_count > _MAX_SEGMENT_ATOMS:
        return None
    seen: dict[str, int] = {}
    duplicates: set[str] = set()
    for episode, title in titles.items():
        norm = normalize_for_specials(title)
        if not norm:
            continue
        if norm in seen:
            duplicates.add(norm)
        else:
            seen[norm] = episode
    norm_to_episode = {n: e for n, e in seen.items() if n not in duplicates}
    if not norm_to_episode:
        return None
    spaced_keys = {
        norm: normalize_for_specials_spaced(titles[episode])
        for norm, episode in norm_to_episode.items()
    }

    def _match_piece(piece: str) -> tuple[int | None, bool]:
        compact = normalize_for_specials(piece)
        episode = norm_to_episode.get(compact)
        if episode is not None:
            return episode, True
        spaced = normalize_for_specials_spaced(piece)
        hits = [
            episode
            for norm, episode in norm_to_episode.items()
            if _fuzzy_title_equal(compact, spaced, norm, spaced_keys[norm])
        ]
        if len(hits) == 1:
            return hits[0], False
        return None, False

    matched_runs: dict[tuple[int, ...], bool] = {}
    for cuts in itertools.combinations(range(1, atom_count), expected_count - 1):
        bounds = (0, *cuts, atom_count)
        episodes: list[int] = []
        all_exact = True
        for group in range(expected_count):
            lo, hi = bounds[group], bounds[group + 1]
            piece = raw_title[spans[lo][0]:spans[hi - 1][1]]
            episode, exact = _match_piece(piece)
            if episode is None:
                break
            episodes.append(episode)
            all_exact = all_exact and exact
        else:
            if len(set(episodes)) == expected_count:
                run = tuple(sorted(episodes))
                matched_runs[run] = matched_runs.get(run, False) or all_exact
    if len(matched_runs) != 1:
        return None
    run, all_exact = next(iter(matched_runs.items()))
    if any(b - a != 1 for a, b in zip(run, run[1:])):
        return None
    return run, all_exact
```

Update `resolve_file`'s two seg-run branches:

```python
    if len(parsed_episodes) >= 2:
        seg = match_segmented_title_run(
            raw_title, season_titles, len(parsed_episodes),
        )
        if seg is not None:
            seg_run, seg_exact = seg
            if not seg_exact:
                return Resolution(  # fuzzy atoms -> review
                    episodes=seg_run,
                    confidence=CONF_TITLE_WINS_INEXACT,
                    evidence=frozenset(
                        {"title-segmented", "title-fuzzy", "number-disagree"},
                    ),
                )
            if valid_numbers and set(seg_run) == set(valid_numbers):
                return Resolution(
                    episodes=seg_run,
                    confidence=CONF_AGREE,
                    evidence=frozenset({"number", "title-agree", "title-segmented"}),
                )
            return Resolution(
                episodes=seg_run,
                confidence=CONF_TITLE_WINS,
                evidence=frozenset(
                    {"title-strong", "title-segmented", "number-disagree"},
                ),
            )
```

Mirror the same `(run, all_exact)` unpacking in the single-number disc-grouping branch: collect `runs = {}` as a dict `run -> exact`, and when exactly one run: exact → existing confidences; fuzzy → `CONF_TITLE_WINS_INEXACT` + `{"title-segmented", "title-fuzzy", "number-disagree"}`.

In rule 5 (title-only), keep 0.88 auto-accept only for substring-or-better:

```python
    if title_match is not None and strong_title:  # rule 5
        if title_match.strength >= _TITLE_SUBSTRING:
            return Resolution(
                episodes=(title_match.episode,),
                confidence=CONF_TITLE_ONLY,
                evidence=frozenset({"title-strong"}),
            )
        return Resolution(  # fuzzy-only match -> review
            episodes=(title_match.episode,),
            confidence=CONF_TITLE_WINS_INEXACT,
            evidence=frozenset({"title-strong-inexact", "title-fuzzy"}),
        )
```

In `_shift_run_off_segmented_conflict`, replace the seg-run comparison:

```python
        seg = match_segmented_title_run(
            entry.raw_title, proposed_titles, len(proposed),
        )
        if seg is None or seg[0] != proposed:
```

Add `"title-fuzzy"` to `_claim_strength` tier 2 (`{"title-strong-inexact", "title-segmented", "title-fuzzy"}`) and to the review-lock set at the bottom of `apply_confidence_adjustments`.

- [ ] **Step 5: Run new tests + resolution regressions, fix direct-caller tests found in Step 1**

Run: `.venv\Scripts\python.exe -m pytest tests\test_fuzzy_title_matching.py tests\test_episode_resolution.py tests\test_conflict_resolution.py tests\test_offset_inference.py tests\test_consolidated_assignments.py -q`
Expected: PASS after updating any test that called `match_segmented_title_run` directly.

- [ ] **Step 6: Commit**

```
git commit -am "feat: bounded fuzzy title matching and fuzzy segmented runs at review confidence (RC20-2)"
```

---

### Task 5: RC21 — underscore as a segment separator in dot-spaced names

`Catscratch.S01E01.To.The.Moon_Bringin'.Down.The.Mouse` loses the `_` boundary before segmentation can see it, so no Catscratch file can decompose and half auto-accept wrong episodes.

**Files:**
- Modify: `plex_renamer/_parsing_titles.py:151-162` (`clean_title_evidence`)
- Test: `tests/test_underscore_segments.py` (new)

**Interfaces:**
- Produces: in dot-spaced stems (≥3 dots) with 1–3 underscores, `_` becomes `" & "` in `clean_title_evidence` output, so `_SEGMENT_SEP` can split it. Underscore-spaced names (`Show_Name_S01E01`) keep the space behavior.

- [ ] **Step 1: Write the failing tests**

```python
"""RC21: '_' between segment titles in dot-spaced names is a separator."""
from plex_renamer.parsing import extract_episode
from plex_renamer.engine._episode_resolution import resolve_file, CONF_TITLE_WINS_INEXACT


def test_underscore_becomes_segment_separator():
    eps, title, rel = extract_episode(
        "Catscratch.S01E01.To.The.Moon_Bringin'.Down.The.Mouse.mkv"
    )
    assert eps == [1] and rel is True
    assert title == "To The Moon & Bringin' Down The Mouse"


def test_underscore_spaced_names_unaffected():
    eps, title, _ = extract_episode("Show_Name_S01E01_Some_Title.mkv")
    assert eps == [1]
    assert title == "Some Title"


def test_catscratch_file_resolves_to_run():
    titles = {1: "To the Moon", 2: "Bringing Down the Mouse", 3: "Unicorn Club", 4: "Go Gomez Go"}
    eps, title, rel = extract_episode(
        "Catscratch.S01E02.Unicorn.Club_Go.Gomez.Go.mkv"
    )
    resolution = resolve_file(
        parsed_episodes=tuple(eps), raw_title=title,
        is_season_relative=rel, season_titles=titles, season=1,
    )
    assert resolution.episodes == (3, 4)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests\test_underscore_segments.py -q`
Expected: FAIL — title has a space where the `&` should be; resolution keeps `(2,)`.

- [ ] **Step 3: Implement in `clean_title_evidence`**

```python
def clean_title_evidence(name: str) -> str:
    """Normalize a filename for episode-TITLE extraction.

    Like ``clean_name`` but PRESERVES descriptive parentheticals such as
    ``(Pilot)``/``(Again)`` (so specials match their TMDB titles) while still
    dropping quality/source parentheticals. Strips square-bracketed tags and
    turns dots/underscores into spaces.

    In dot-spaced release names a lone '_' is the boundary BETWEEN two
    segment titles (Catscratch.S01E01.To.The.Moon_Bringin'.Down.The.Mouse);
    flattening it to a space would erase the only segment separator, so it
    becomes ' & ' instead. Names that use '_' as their word separator (no
    dot spacing) keep the plain-space behavior.
    """
    name = re.sub(r"\[.*?\]", "", name)
    name = _strip_quality_parens(name)
    if name.count(".") >= 3 and 1 <= name.count("_") <= 3:
        name = name.replace("_", " & ")
    name = name.replace(".", " ").replace("_", " ")
    return re.sub(r"\s+", " ", name).strip()
```

- [ ] **Step 4: Run new tests + parsing regressions + smoke of resolution tests**

Run: `.venv\Scripts\python.exe -m pytest tests\test_underscore_segments.py tests\test_release_junk_titles.py tests\test_parsing_edgecases.py tests\test_episode_resolution.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```
git commit -am "fix: treat underscore as segment separator in dot-spaced names (RC21)"
```

---

### Task 6: RC20(3) — extend a rule-2b single-segment match to the full run

When a multi-episode file's combined title only matches ONE segment (typo blocks the other), rule 2b assigns a single episode and drops the rest (CatDog E38, Rugrats E20). Anchor the parsed/atom-count run at the matched segment's position.

**Files:**
- Modify: `plex_renamer/engine/_episode_resolution.py` (`resolve_file` rule 2/2b area; helper `_extend_partial_title_run`)
- Test: `tests/test_run_extension.py` (new)

**Interfaces:**
- Consumes: `_segment_atom_spans`, `match_title_in_titles` (Task 4 fuzzy included).
- Produces: rule-2/2b resolutions for multi-atom titles may return an n-episode run with evidence `{"title-strong-inexact", "number-disagree", "run-extended"}` at `CONF_TITLE_WINS_INEXACT`.

- [ ] **Step 1: Write the failing tests**

```python
"""RC20(3): a one-segment title match extends to the whole segment run."""
from plex_renamer.engine._episode_resolution import (
    CONF_TITLE_WINS_INEXACT,
    resolve_file,
)

CATDOG_S3 = {
    36: "Full Moon Fever",
    37: "Neferkitty",
    38: "Curiosity Almost Killed The Cat",  # file typo: 'Curiousity' + extra words
}


def test_two_number_file_extends_from_matched_first_segment():
    resolution = resolve_file(
        parsed_episodes=(37, 38),
        raw_title="Neferkitty and Curiousity Almost Killed The Big Weird Cat",
        is_season_relative=True,
        season_titles=CATDOG_S3,
        season=3,
    )
    assert resolution.episodes == (37, 38)
    assert "run-extended" in resolution.evidence or "title-agree" in resolution.evidence


RUGRATS_S4 = {
    19: "Chuckie Is Rich",
    20: "The Unfair Pair",       # file says 'The Mattress'
    21: "Looking for Jack",
}


def test_single_number_two_atoms_extends_backwards():
    resolution = resolve_file(
        parsed_episodes=(21,),
        raw_title="The Mattress & Looking for Jack",
        is_season_relative=True,
        season_titles=RUGRATS_S4,
        season=4,
    )
    assert resolution.episodes == (20, 21)
    assert resolution.confidence == CONF_TITLE_WINS_INEXACT
    assert "run-extended" in resolution.evidence


def test_no_extension_when_atom_counts_disagree():
    resolution = resolve_file(
        parsed_episodes=(21,),
        raw_title="Looking for Jack",
        is_season_relative=True,
        season_titles=RUGRATS_S4,
        season=4,
    )
    assert resolution.episodes == (21,)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests\test_run_extension.py -q`
Expected: FAIL — single-episode assignments where runs are expected.

- [ ] **Step 3: Implement**

Add helper after `match_segmented_title_run`:

```python
def _extend_partial_title_run(
    raw_title: str,
    matched_episode: int,
    season_titles: dict[int, str],
    parsed_count: int,
) -> tuple[int, ...] | None:
    """Anchor a run at the one atom that title-matched (RC20(3)).

    A combined multi-segment title where only ONE segment matched (typos
    block the rest) still names its neighbors by position: n atoms with the
    match at index i mean episodes [matched-i .. matched-i+n-1]. Only
    extends when the atom count is unambiguous (== max(parsed, atoms) >= 2),
    exactly one atom matches that episode, and every slot exists.
    """
    spans = _segment_atom_spans(raw_title)
    run_length = max(parsed_count, len(spans))
    if run_length < 2 or len(spans) != run_length:
        return None
    matching_indexes = [
        index
        for index, (lo, hi) in enumerate(spans)
        for match in [match_title_in_titles(raw_title[lo:hi], season_titles)]
        if match is not None and match.episode == matched_episode
    ]
    if len(matching_indexes) != 1:
        return None
    start = matched_episode - matching_indexes[0]
    run = tuple(range(start, start + run_length))
    if any(episode not in season_titles for episode in run):
        return None
    return run
```

In `resolve_file`, inside the `if valid_numbers and title_match is not None:` block, replace the rule 2 / 2b returns with run-extension-aware versions:

```python
        if strong_title and title_match.strength >= _TITLE_EXACT:
            run = None
            if raw_title and (
                len(parsed_episodes) >= 2 or len(_segment_atom_spans(raw_title)) >= 2
            ):
                run = _extend_partial_title_run(
                    raw_title, title_match.episode, season_titles,
                    len(parsed_episodes),
                )
            if run is not None and len(run) > 1:
                return Resolution(  # extended run -> review (partly unverified)
                    episodes=run,
                    confidence=CONF_TITLE_WINS_INEXACT,
                    evidence=frozenset(
                        {"title-strong-inexact", "number-disagree", "run-extended"},
                    ),
                )
            return Resolution(  # rule 2: exact title overrides, auto-accept
                episodes=(title_match.episode,),
                confidence=CONF_TITLE_WINS,
                evidence=frozenset({"title-strong", "number-disagree"}),
            )
        if strong_title:
            run = None
            if raw_title and (
                len(parsed_episodes) >= 2 or len(_segment_atom_spans(raw_title)) >= 2
            ):
                run = _extend_partial_title_run(
                    raw_title, title_match.episode, season_titles,
                    len(parsed_episodes),
                )
            if run is not None and len(run) > 1:
                return Resolution(
                    episodes=run,
                    confidence=CONF_TITLE_WINS_INEXACT,
                    evidence=frozenset(
                        {"title-strong-inexact", "number-disagree", "run-extended"},
                    ),
                )
            return Resolution(  # rule 2b: strong inexact title overrides, REVIEW
                episodes=(title_match.episode,),
                confidence=CONF_TITLE_WINS_INEXACT,
                evidence=frozenset({"title-strong-inexact", "number-disagree"}),
            )
```

Note: the CatDog test may resolve via the multi-episode seg-run branch once fuzzy matching (Task 4) handles the typo — that is fine; the test accepts either evidence. Rule-2b extension is the fallback when fuzzy can't bridge the difference.

Add `"run-extended"` to the review-lock set in `apply_confidence_adjustments`.

- [ ] **Step 4: Run new tests + resolution regressions**

Run: `.venv\Scripts\python.exe -m pytest tests\test_run_extension.py tests\test_episode_resolution.py tests\test_fuzzy_title_matching.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```
git commit -am "feat: extend rule-2b single-segment matches to the anchored run (RC20-3)"
```

---

### Task 7: RC22 — review-cap number-only assignments whose rich title matches nothing + cross-season segmented rescue

Rule 4 + floors auto-accept mis-numbered files at 0.86/0.88 even when their multi-segment titles match ZERO slots in the assigned season (Rugrats S7+, CatDog S3E01-12). Cap those at review, and try their segment titles against other seasons.

**Files:**
- Modify: `plex_renamer/engine/_episode_resolution.py` (`resolve_file` rule-4 area; new `rescue_cross_season_segmented`)
- Modify: `plex_renamer/engine/_tv_scanner.py:235-236,270` (wire the rescue into both preview builders)
- Test: `tests/test_multisegment_zero_match.py` (new)

**Interfaces:**
- Produces:
  - `resolve_file` returns `CONF_WEAK_TITLE_NUMBER_CAP` with evidence `{"number", "title-no-match", "title-multi-segment"}` when a ≥2-atom title matches nothing in a titled season.
  - `rescue_cross_season_segmented(table: EpisodeAssignmentTable) -> None` — reassigns such files (and NOT_IN_SEASON multi-files) whose atoms form an exact run in exactly one other regular season, at `CONF_TITLE_WINS_INEXACT` with `{"title-segmented", "cross-season-rescue"}`.

- [ ] **Step 1: Write the failing tests**

```python
"""RC22: zero-title-match multi-segment files must not auto-accept."""
from pathlib import Path

from plex_renamer.engine._episode_resolution import (
    CONF_WEAK_TITLE_NUMBER_CAP,
    CONF_TITLE_WINS_INEXACT,
    resolve_file,
    rescue_cross_season_segmented,
)
from plex_renamer.engine.episode_assignments import EpisodeAssignmentTable, EpisodeSlot

S3_TITLES = {1: "New Neighbors", 2: "Dummy Dummy", 3: "Smarter than Smarts"}
S2_TITLES = {34: "Movin On Up", 35: "Sumo Enchanted Evening", 36: "Hotel CatDog"}


def test_zero_match_multisegment_is_review_capped():
    resolution = resolve_file(
        parsed_episodes=(1, 2),
        raw_title="Sumo Enchanted Evening and Hotel CatDog",
        is_season_relative=True,
        season_titles=S3_TITLES,
        season=3,
    )
    assert resolution.episodes == (1, 2)
    assert resolution.confidence == CONF_WEAK_TITLE_NUMBER_CAP
    assert "title-no-match" in resolution.evidence
    assert "title-multi-segment" in resolution.evidence


def _build_table() -> EpisodeAssignmentTable:
    table = EpisodeAssignmentTable()
    for episode, title in S3_TITLES.items():
        table.add_slot(EpisodeSlot(season=3, episode=episode, title=title))
    for episode, title in S2_TITLES.items():
        table.add_slot(EpisodeSlot(season=2, episode=episode, title=title))
    return table


def test_cross_season_segmented_rescue_moves_file():
    table = _build_table()
    entry = table.add_file(
        Path("S03 E01-E02 - Sumo Enchanted Evening and Hotel CatDog.mkv"),
        parsed_episodes=(1, 2),
        raw_title="Sumo Enchanted Evening and Hotel CatDog",
        is_season_relative=True,
        season_hint=3,
        folder_season=3,
    )
    table.assign(
        entry.file_id, 3, [1, 2], origin="auto",
        confidence=CONF_WEAK_TITLE_NUMBER_CAP,
        evidence=frozenset({"number", "title-no-match", "title-multi-segment"}),
    )
    rescue_cross_season_segmented(table)
    assignment = table.assignment_for(entry.file_id)
    assert assignment.season == 2
    assert assignment.episodes == (35, 36)
    assert assignment.confidence == CONF_TITLE_WINS_INEXACT
    assert "cross-season-rescue" in assignment.evidence
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests\test_multisegment_zero_match.py -q`
Expected: FAIL (resolution auto-accepts at 0.86; `rescue_cross_season_segmented` ImportError).

- [ ] **Step 3: Implement the review cap in `resolve_file`**

Inside `if valid_numbers:` (the no-title_match block), after the `_has_ambiguous_title_evidence` branch and before the `season == 0` branch:

```python
        if (
            raw_title
            and title_match is None
            and len(_segment_atom_spans(raw_title)) >= 2
            and any(title for title in season_titles.values())
        ):
            # A rich multi-segment title matching NOTHING in a titled season
            # means the number is a disc/source index, not a season position
            # (Rugrats S7 overflow, CatDog mis-filed seasons). Review-locked.
            return Resolution(
                episodes=valid_numbers,
                confidence=CONF_WEAK_TITLE_NUMBER_CAP,
                evidence=frozenset(
                    {"number", "title-no-match", "title-multi-segment"},
                ),
            )
```

- [ ] **Step 4: Implement `rescue_cross_season_segmented`** (after `rescue_cross_season_titles`)

```python
def rescue_cross_season_segmented(table: EpisodeAssignmentTable) -> None:
    """Re-home multi-segment files whose titles match nothing in their
    assigned season but form an EXACT segmented run in exactly one OTHER
    regular season (CatDog 'Season 3' files holding S2 content). Review
    confidence — the parsed numbers are known-wrong."""
    titles_by_season: dict[int, dict[int, str]] = {}
    for (season, episode), slot in table.slots.items():
        if season != 0 and slot.title:
            titles_by_season.setdefault(season, {})[episode] = slot.title

    candidates: list[tuple[int, int | None]] = []
    for assignment in list(table.assignments()):
        if assignment.origin == ORIGIN_MANUAL:
            continue
        if "title-no-match" not in assignment.evidence:
            continue
        candidates.append((assignment.file_id, assignment.season))
    for file_id, reason in table.unassigned_reasons.items():
        if reason != REASON_NOT_IN_SEASON:
            continue
        entry = table.files[file_id]
        if entry.raw_title and len(entry.parsed_episodes) >= 2:
            candidates.append((file_id, entry.folder_season))

    claimed = {
        (assignment.season, episode)
        for assignment in table.assignments()
        for episode in assignment.episodes
    }
    for file_id, current_season in candidates:
        entry = table.files[file_id]
        expected = max(len(entry.parsed_episodes), 2)
        hits: list[tuple[int, tuple[int, ...]]] = []
        for season, titles in titles_by_season.items():
            if season == current_season:
                continue
            seg = match_segmented_title_run(entry.raw_title, titles, expected)
            if seg is not None and seg[1]:  # exact runs only across seasons
                hits.append((season, seg[0]))
        if len(hits) != 1:
            continue
        season, run = hits[0]
        assignment = table.assignment_for(file_id)
        own = (
            {(assignment.season, e) for e in assignment.episodes}
            if assignment is not None else set()
        )
        run_slots = {(season, episode) for episode in run}
        if run_slots & (claimed - own):
            continue
        table.assign(
            file_id, season, list(run), origin=ORIGIN_AUTO,
            confidence=CONF_TITLE_WINS_INEXACT,
            evidence=frozenset({"title-segmented", "cross-season-rescue"}),
        )
        claimed -= own
        claimed |= run_slots
```

- [ ] **Step 5: Wire into `_tv_scanner.py`**

In `_build_normal_preview` add `rescue_cross_season_segmented` to the import list and call it right after `rescue_cross_season_titles(table)`. In `_build_consolidated_preview` import it and call it right before `apply_uniform_offset_rescue(table)`.

- [ ] **Step 6: Run new tests + regressions**

Run: `.venv\Scripts\python.exe -m pytest tests\test_multisegment_zero_match.py tests\test_episode_resolution.py tests\test_conflict_resolution.py tests\test_offset_inference.py tests\test_scan_improvements.py -q`
Expected: PASS. (`"title-multi-segment"` is already review-locked, so no lock-set change needed.)

- [ ] **Step 7: Commit**

```
git commit -am "fix: review-cap zero-title-match multi-segment numbers, add cross-season segmented rescue (RC22)"
```

---

### Task 8: RC20(4) — same-season fuzzy rescue for lost-conflict/no-match files

Files that lost conflicts or matched nothing, whose fuzzy title hits exactly one UNCLAIMED slot in their own season, should be review-assigned (Angry Beavers' 3 unmapped files ↔ 3 unclaimed same-title slots).

**Files:**
- Modify: `plex_renamer/engine/_episode_resolution.py` (new `rescue_same_season_fuzzy_titles`)
- Modify: `plex_renamer/engine/_tv_scanner.py` (wire into both builders, after `rescue_cross_season_segmented`)
- Test: `tests/test_same_season_rescue.py` (new)

**Interfaces:**
- Consumes: `match_title_in_titles` (fuzzy tier from Task 4).
- Produces: `rescue_same_season_fuzzy_titles(table: EpisodeAssignmentTable) -> None`; new evidence tag `"same-season-rescue"` (review-locked).

- [ ] **Step 1: Write the failing test**

```python
"""RC20(4): fuzzy title -> unique unclaimed same-season slot rescue."""
from pathlib import Path

from plex_renamer.engine._episode_resolution import (
    CONF_TITLE_WINS_INEXACT,
    rescue_same_season_fuzzy_titles,
)
from plex_renamer.engine.episode_assignments import (
    EpisodeAssignmentTable,
    EpisodeSlot,
    lost_conflict_reason,
)


def test_lost_conflict_file_rescued_by_fuzzy_title():
    table = EpisodeAssignmentTable()
    titles = {1: "Zooing Time", 2: "H²-Whoa!", 3: "Fish and Dips"}
    for episode, title in titles.items():
        table.add_slot(EpisodeSlot(season=3, episode=episode, title=title))
    entry = table.add_file(
        Path("The Angry Beavers - S03E05 - H-2 Whoa.mkv"),
        parsed_episodes=(5,),
        raw_title="H-2 Whoa",
        is_season_relative=True,
        season_hint=3,
        folder_season=3,
    )
    table.mark_unassigned(entry.file_id, lost_conflict_reason(3, 5))
    rescue_same_season_fuzzy_titles(table)
    assignment = table.assignment_for(entry.file_id)
    assert assignment is not None
    assert assignment.season == 3 and assignment.episodes == (2,)
    assert assignment.confidence == CONF_TITLE_WINS_INEXACT
    assert "same-season-rescue" in assignment.evidence
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests\test_same_season_rescue.py -q`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement** (after `rescue_cross_season_segmented`)

```python
def rescue_same_season_fuzzy_titles(table: EpisodeAssignmentTable) -> None:
    """Lost-conflict / no-match / not-in-season files whose (possibly fuzzy)
    title hits exactly ONE unclaimed slot in their own season -> review-assign
    (Angry Beavers: 3 unmapped files <-> 3 unclaimed same-title slots)."""
    claimed = {
        (assignment.season, episode)
        for assignment in table.assignments()
        for episode in assignment.episodes
    }
    for file_id, reason in list(table.unassigned_reasons.items()):
        if not (
            reason in (REASON_NOT_IN_SEASON, REASON_NO_TITLE_MATCH)
            or reason.startswith(REASON_LOST_CONFLICT)
        ):
            continue
        entry = table.files.get(file_id)
        if entry is None or not entry.raw_title:
            continue
        season = (
            entry.season_hint if entry.season_hint is not None
            else entry.folder_season
        )
        if season is None or season == 0:
            continue
        unclaimed_titles = {
            episode: slot.title
            for (slot_season, episode), slot in table.slots.items()
            if slot_season == season and slot.title
            and (slot_season, episode) not in claimed
        }
        match = match_title_in_titles(entry.raw_title, unclaimed_titles)
        if match is None or match.strength < STRONG_TITLE_STRENGTH:
            continue
        table.assign(
            file_id, season, [match.episode], origin=ORIGIN_AUTO,
            confidence=CONF_TITLE_WINS_INEXACT,
            evidence=frozenset({"title-fuzzy", "same-season-rescue"}),
        )
        claimed.add((season, match.episode))
```

Add `"same-season-rescue"` to the review-lock set in `apply_confidence_adjustments`. Wire into `_tv_scanner.py`: both builders, immediately after `rescue_cross_season_segmented(table)`.

- [ ] **Step 4: Run new tests + regressions**

Run: `.venv\Scripts\python.exe -m pytest tests\test_same_season_rescue.py tests\test_conflict_resolution.py tests\test_offset_inference.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```
git commit -am "feat: same-season fuzzy title rescue for lost-conflict files (RC20-4)"
```

---

### Task 9: RC24(b) — specials branch must not hijack a valid own-season episode

The cross-season specials pull in `_resolve_into_table` can override a file whose explicit S##E## is valid in its own season (Doctor Who S02E10 → 'Tardisode 10'). Symbol folding (Task 3) fixes the trigger case, but the branch needs the same guard `rescue_cross_season_titles` already has.

**Files:**
- Modify: `plex_renamer/engine/_tv_scanner_normal.py:114-150`
- Test: `tests/test_specials_guards.py` (new — this file grows in Tasks 10–12)

**Interfaces:**
- Consumes/produces: no signature changes; a file with valid explicit own-season numbering may only be pulled to S0 on an EXACT title match when the own season has NO match at all.

- [ ] **Step 1: Write the failing test**

```python
"""RC24(b)/RC25/RC26/RC23: specials-path guards."""
from pathlib import Path

from plex_renamer.engine._tv_scanner_normal import _resolve_into_table
from plex_renamer.engine.episode_assignments import EpisodeAssignmentTable, EpisodeSlot


def _table_with(season, titles, s0_titles=None):
    table = EpisodeAssignmentTable()
    for episode, title in titles.items():
        table.add_slot(EpisodeSlot(season=season, episode=episode, title=title))
    for episode, title in (s0_titles or {}).items():
        table.add_slot(EpisodeSlot(season=0, episode=episode, title=title))
    return table


def test_valid_own_season_episode_not_pulled_to_specials(tmp_path):
    season_titles = {9: "The Satan Pit", 10: "Love & Monsters", 11: "Fear Her"}
    s0_titles = {28: "Tardisode 10: Love And Monsters"}
    table = _table_with(2, season_titles, s0_titles)
    file_path = tmp_path / "Doctor Who - S02E10 - Love and Monsters.mkv"
    file_path.touch()
    _resolve_into_table(
        table,
        file_path=file_path,
        season_num=2,
        season_titles=season_titles,
        specials_titles=s0_titles,
        show_name="Doctor Who",
    )
    assignment = table.assignment_for(0)
    assert assignment is not None
    assert assignment.season == 2
    assert assignment.episodes == (10,)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests\test_specials_guards.py -q`
Expected: With Task 3's folding the own-season match already agrees, so this may PASS on the folding alone. Temporarily verify the guard by checking the stronger case: change `s0_titles` to the exact file title (`{28: "Love and Monsters"}`) — a bare substring/exact S0 hit must still NOT override the valid own-season number when own_match exists. Keep both variants as two tests:

```python
def test_exact_s0_title_still_loses_to_valid_own_number_with_own_match(tmp_path):
    season_titles = {9: "The Satan Pit", 10: "Love & Monsters", 11: "Fear Her"}
    s0_titles = {28: "Love and Monsters"}
    table = _table_with(2, season_titles, s0_titles)
    file_path = tmp_path / "Doctor Who - S02E10 - Love and Monsters.mkv"
    file_path.touch()
    _resolve_into_table(
        table, file_path=file_path, season_num=2,
        season_titles=season_titles, specials_titles=s0_titles,
        show_name="Doctor Who",
    )
    assignment = table.assignment_for(0)
    assert assignment.season == 2 and assignment.episodes == (10,)
```

- [ ] **Step 3: Implement the guard in `_resolve_into_table`**

Before the `if (s0_match is not None …)` condition compute:

```python
        own_explicit_valid = (
            is_season_relative
            and season_hint == season_num
            and bool(episode_numbers)
            and all(episode in season_titles for episode in episode_numbers)
        )
```

and extend the pull condition:

```python
        if (
            s0_match is not None
            and s0_match.strength >= STRONG_TITLE_STRENGTH
            and (own_match is None or s0_match.strength > own_match.strength)
            and (
                not own_explicit_valid
                or (s0_match.strength >= _TITLE_EXACT and own_match is None)
            )
        ):
```

- [ ] **Step 4: Run tests**

Run: `.venv\Scripts\python.exe -m pytest tests\test_specials_guards.py tests\test_tv_scanner_normal.py tests\test_extras_and_prefix_fixes.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```
git commit -am "fix: never pull a valid own-season episode to a special without exact-title proof (RC24b)"
```

---

### Task 10: RC25 — prequel/extras files must not number-claim S0 slots; match titles by segment

"Prequel - S07E13 - The Name of the Doctor - Clarence and the Whispermen" (extras folder → S0 scan) number-claims S00E13 (its PARENT episode number) and its true slot stays unclaimed because 'X - Y' vs TMDB 'Y (X Prequel)' fails substring.

**Files:**
- Modify: `plex_renamer/engine/_tv_scanner_normal.py` (`_resolve_into_table`)
- Test: `tests/test_specials_guards.py` (extend)

**Interfaces:**
- Produces: extras-scanned files with `season_hint not in (None, 0)` make no S0 number claims; new S0 fallback tries dash-segments of the title via `match_title_in_titles` at `CONF_TITLE_WINS_INEXACT` with evidence `{"title-strong-inexact", "segment-title"}` ("segment-title" review-locked via "title-strong-inexact" already in lock set — no lock change needed).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_specials_guards.py`)

```python
def test_prequel_with_parent_number_does_not_claim_s0_number(tmp_path):
    s0_titles = {
        13: "Planet of the Dead",
        85: "She Said, He Said (The Name of the Doctor Prequel)",
        86: "Clarence and the Whispermen (The Name of the Doctor Prequel)",
    }
    table = _table_with(0, {}, s0_titles)
    file_path = (
        tmp_path
        / "Prequel - S07E13 - The Name of the Doctor - Clarence and the Whispermen.mkv"
    )
    file_path.touch()
    _resolve_into_table(
        table, file_path=file_path, season_num=0,
        season_titles=s0_titles, from_extras_folder=True,
        show_name="Doctor Who",
    )
    assignment = table.assignment_for(0)
    assert assignment is not None
    assert assignment.season == 0
    assert assignment.episodes == (86,)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests\test_specials_guards.py -q`
Expected: FAIL — the file claims S00E13 (or unassigns).

- [ ] **Step 3: Implement in `_resolve_into_table`**

Replace the extras number guard:

```python
    if from_extras_folder and not is_season_relative:
        # A bare number in an extras filename ("Season 2 Extra 1", "NCED2")
        # is not an episode number; claiming numbered S0 slots from it
        # produced mass conflicts. Only explicit S00E## numbering counts.
        episode_numbers = []
    elif from_extras_folder and season_hint not in (None, 0):
        # "Prequel - S07E13 - …": the S##E## names the PARENT episode the
        # extra belongs to, not an S0 slot (RC25).
        episode_numbers = []
```

After `resolution = resolve_file(...)` (before the specials cross-match block), add the S0 segment fallback:

```python
    if (
        season_num == 0
        and not resolution.episodes
        and title_evidence
        and " - " in title_evidence
    ):
        # Extras often name themselves "Parent Title - Extra Title" while
        # TMDB lists "Extra Title (Parent Title Prequel)"; per-segment
        # matching bridges the recombination (RC25).
        for segment in reversed(title_evidence.split(" - ")):
            segment = segment.strip()
            if len(segment) < 4:
                continue
            segment_match = match_title_in_titles(segment, season_titles)
            if (
                segment_match is not None
                and segment_match.strength >= STRONG_TITLE_STRENGTH
            ):
                resolution = Resolution(
                    episodes=(segment_match.episode,),
                    confidence=CONF_TITLE_WINS_INEXACT,
                    evidence=frozenset({"title-strong-inexact", "segment-title"}),
                )
                break
```

- [ ] **Step 4: Run tests**

Run: `.venv\Scripts\python.exe -m pytest tests\test_specials_guards.py tests\test_extras_and_prefix_fixes.py tests\test_tv_scanner_normal.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```
git commit -am "fix: extras with parent-episode numbers match S0 by title segments (RC25)"
```

---

### Task 11: RC26 — cleaned-stem title fallback for unparseable files in any season

`The Henry & June Show (1999).mp4` in the show ROOT parses no episode → `REASON_NO_PARSE`; the stem-as-title fallback only ran for `season_num == 0`. TMDB S00E02 is literally 'The Henry & June Show'.

**Files:**
- Modify: `plex_renamer/engine/_tv_scanner_normal.py` (`_resolve_into_table`)
- Test: `tests/test_specials_guards.py` (extend)

**Interfaces:**
- Produces: any video file with no parsed episodes AND no raw_title gets its cleaned stem as title evidence; the existing own-season resolution + S0 cross-match branch does the rest.

- [ ] **Step 1: Write the failing tests** (append)

```python
def test_root_file_with_no_parse_matches_special_by_stem(tmp_path):
    season_titles = {1: "Your Real Best Friend!", 2: "Why June?"}
    s0_titles = {2: "The Henry & June Show", 3: "An Off-Beats Valentine's"}
    table = _table_with(1, season_titles, s0_titles)
    file_path = tmp_path / "The Henry & June Show (1999).mp4"
    file_path.touch()
    _resolve_into_table(
        table, file_path=file_path, season_num=1,
        season_titles=season_titles, specials_titles=s0_titles,
        show_name="KaBlam!",
    )
    assignment = table.assignment_for(0)
    assert assignment is not None
    assert assignment.season == 0 and assignment.episodes == (2,)


def test_offbeats_valentines_stem_substring(tmp_path):
    season_titles = {1: "Your Real Best Friend!"}
    s0_titles = {2: "The Henry & June Show", 3: "An Off-Beats Valentine's"}
    table = _table_with(1, season_titles, s0_titles)
    file_path = tmp_path / "The Off-Beats Valentine's Special (1998).mp4"
    file_path.touch()
    _resolve_into_table(
        table, file_path=file_path, season_num=1,
        season_titles=season_titles, specials_titles=s0_titles,
        show_name="KaBlam!",
    )
    assignment = table.assignment_for(0)
    assert assignment is not None
    assert assignment.season == 0 and assignment.episodes == (3,)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests\test_specials_guards.py -q`
Expected: FAIL — the files stay unassigned (`REASON_NO_PARSE`).

- [ ] **Step 3: Implement**

In `_resolve_into_table`, replace the stem-fallback condition (currently `if season_num == 0 and not title_evidence:`):

```python
    if not title_evidence and (season_num == 0 or not episode_numbers):
        # No parsed episode and no extracted title: the filename itself is
        # the only evidence (root specials like "The Henry & June Show
        # (1999).mp4"). Clean it so quality tags don't pollute the match.
        cleaned_stem = clean_title_evidence(file_path.stem)
        cleaned_stem = _SPECIAL_STEM_PREFIX_RE.sub("", cleaned_stem).strip()
        title_evidence = cleaned_stem or None
```

- [ ] **Step 4: Run tests**

Run: `.venv\Scripts\python.exe -m pytest tests\test_specials_guards.py tests\test_tv_scanner_normal.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```
git commit -am "fix: stem-title fallback for unparseable files in any season (RC26)"
```

---

### Task 12: RC23 — "Part N" specials match "(N)" titles and outrank unreliable S0 numbers

`_strip_part_number` leaves the word "part" in the base ('heart of archness part' ≠ 'heart of archness'), and a part-number match (0.80) can never override a disagreeing S0 number. Archer's three Heart-of-Archness files claim wrong literal S0 numbers.

**Files:**
- Modify: `plex_renamer/engine/_episode_resolution.py` (`_strip_part_number`, `resolve_file`, review locks, `_claim_strength`)
- Test: `tests/test_specials_guards.py` (extend)

**Interfaces:**
- Produces: `_strip_part_number` also strips a trailing `part`/`pt` word from the compacted base; `resolve_file(season=0)` returns a unique part-number title override at `CONF_TITLE_WINS_INEXACT` with evidence `{"title-part-number", "number-disagree"}` (review-locked, `_claim_strength` tier 2).

- [ ] **Step 1: Write the failing tests** (append; note the import additions)

```python
from plex_renamer.engine._episode_resolution import (
    CONF_TITLE_WINS_INEXACT,
    _strip_part_number,
    resolve_file,
)

ARCHER_S0 = {
    3: "Heart of Archness (1)",
    4: "Heart of Archness (2)",
    5: "Heart of Archness (3)",
    6: "L'Espion Mal Fait",
}


def test_strip_part_number_removes_part_word():
    base, part = _strip_part_number("heartofarchnesspart1")
    assert base == "heartofarchness"
    assert part == "1"


def test_specials_part_number_overrides_wrong_s0_number():
    resolution = resolve_file(
        parsed_episodes=(4,),
        raw_title="Heart of Archness Part 1",
        is_season_relative=True,
        season_titles=ARCHER_S0,
        season=0,
    )
    assert resolution.episodes == (3,)
    assert resolution.confidence == CONF_TITLE_WINS_INEXACT
    assert "title-part-number" in resolution.evidence
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests\test_specials_guards.py -q`
Expected: FAIL — base keeps 'part'; resolution keeps episode 4.

- [ ] **Step 3: Implement**

```python
def _strip_part_number(normalized: str) -> tuple[str, str]:
    match = re.search(r"\d{1,2}", normalized)
    if match:
        base = normalized[: match.start()] + normalized[match.end():]
        # 'Heart of Archness Part 1' vs key 'Heart of Archness (1)': the
        # digit is gone but the word 'part' still blocks base equality.
        base = re.sub(r"(?:part|pt)$", "", base)
        return base, match.group()
    return normalized, ""
```

In `resolve_file`, inside `if valid_numbers and title_match is not None:` — after the rule-2b block, before rule 3 — add:

```python
        if season == 0 and title_match.strength >= _TITLE_PART_NUMBER:
            # Specials numbering is source-unreliable; a unique titled part
            # match outranks a disagreeing S0 number (review).
            return Resolution(
                episodes=(title_match.episode,),
                confidence=CONF_TITLE_WINS_INEXACT,
                evidence=frozenset({"title-part-number", "number-disagree"}),
            )
```

Add `"title-part-number"` to the review-lock set in `apply_confidence_adjustments` and to `_claim_strength` tier 2.

- [ ] **Step 4: Run tests**

Run: `.venv\Scripts\python.exe -m pytest tests\test_specials_guards.py tests\test_episode_resolution.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```
git commit -am "fix: part-number specials titles match '(N)' forms and override S0 numbers (RC23)"
```

---

### Task 13: RC18a/b/d — consolidated title matching: two-phase claiming, S0 titles, 4-char floor, fuzzy lookup

Number claims currently consume slots before title claims (CatDog), the 8-char substring floor starves the 50% gate (JJK), and S0 is excluded from the lookup (Reno revival specials).

**Files:**
- Modify: `plex_renamer/engine/_tv_scanner_consolidated.py:56-158` (`match_file_title_to_tmdb`, `try_title_based_matching`)
- Test: `tests/test_consolidated_two_phase.py` (new)

**Interfaces:**
- Consumes: `_fuzzy_title_equal` and `normalize_for_specials_spaced` (import both at module top — no import cycle exists).
- Produces:
  - `match_file_title_to_tmdb(raw_title, title_lookup, number_lookup, used, spaced_lookup=None)` — extra keyword arg; substring floor drops 8→4 via module constant `_MIN_LOOKUP_SUBSTRING_LEN = 4`.
  - `try_title_based_matching` same signature, two-phase behavior; S0 titles participate (regular seasons shadow S0 on duplicate titles).

- [ ] **Step 1: Write the failing tests**

```python
"""RC18a/b/d: two-phase consolidated title matching."""
from pathlib import Path

from plex_renamer.engine._tv_scanner_consolidated import try_title_based_matching


def _entry(name, abs_num, raw_title, eps, rel, hint):
    return (Path(name), abs_num, raw_title, eps, rel, hint)


def _seasons(spec):
    # spec: {season: {episode: title}}
    return {
        season: {"count": len(titles), "titles": dict(titles), "posters": {}}
        for season, titles in spec.items()
    }


def test_title_claims_beat_number_squatters():
    tmdb = _seasons({3: {1: "New Neighbors", 2: "Dummy Dummy"}})
    files = [
        # mis-filed file whose (hint, number) exists -> must NOT keep the slot
        _entry("S03 E01 - Sumo Enchanted Evening.mkv", 1, "Sumo Enchanted Evening", [1], True, 3),
        # genuinely titled file for the same slot
        _entry("S03 E27 - New Neighbors.mkv", 27, "New Neighbors", [27], True, 3),
    ]
    matches = try_title_based_matching(files, tmdb)
    assert matches is not None
    assert matches[1] == (3, 1, "New Neighbors")


def test_short_titles_participate():
    tmdb = _seasons({1: {1: "Cog", 2: "Passion", 3: "Longer Title Here"}})
    files = [
        _entry("a.mkv", 1, "Cog", [1], True, 1),
        _entry("b.mkv", 2, "Passion", [2], True, 1),
    ]
    matches = try_title_based_matching(files, tmdb)
    assert matches is not None
    assert matches[0] == (1, 1, "Cog")
    assert matches[1] == (1, 2, "Passion")


def test_s0_titles_available_for_hint_missing_seasons():
    tmdb = _seasons({
        1: {1: "The Pilot", 2: "Fireworks"},
        0: {46: "Space Force", 47: "Weekend at Bernie"},
    })
    files = [
        _entry("S07E01 - Space Force.mkv", 1, "Space Force", [1], True, 7),
        _entry("S01E01 - The Pilot.mkv", 1, "The Pilot", [1], True, 1),
    ]
    matches = try_title_based_matching(files, tmdb)
    assert matches is not None
    assert matches[0] == (0, 46, "Space Force")
    assert matches[1] == (1, 1, "The Pilot")


def test_regular_season_shadows_s0_duplicate_title():
    tmdb = _seasons({
        1: {1: "The Pilot"},
        0: {1: "The Pilot"},
    })
    files = [_entry("x.mkv", 1, "The Pilot", [1], True, 1)]
    matches = try_title_based_matching(files, tmdb)
    assert matches is not None and matches[0][0] == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests\test_consolidated_two_phase.py -q`
Expected: FAIL — number squatter keeps the slot; short titles excluded; S0 files unmatched.

- [ ] **Step 3: Rewrite `match_file_title_to_tmdb` and `try_title_based_matching`**

Add imports at module top:

```python
from ._episode_resolution import _fuzzy_title_equal
from ..parsing import normalize_for_specials_spaced
```

(add `normalize_for_specials_spaced` to the existing `..parsing` import line; `re` is already imported).

```python
_MIN_LOOKUP_SUBSTRING_LEN = 4


def match_file_title_to_tmdb(
    raw_title: str | None,
    title_lookup: dict[str, tuple[int, int, str]],
    number_lookup: dict[int, tuple[int, int, str]],
    used: set[tuple[int, int]],
    spaced_lookup: dict[str, tuple[int, int, str]] | None = None,
) -> tuple[int, int, str] | None:
    """Match a file's title against the cross-season TMDB title lookup."""
    if not raw_title:
        return None

    cleaned_title = raw_title
    abs_match = _RE_LEADING_ABS_NUM.match(raw_title)
    if abs_match:
        abs_ep = int(abs_match.group(1))
        cleaned_title = raw_title[abs_match.end():]
        if abs_ep in number_lookup:
            result = number_lookup[abs_ep]
            if (result[0], result[1]) not in used:
                return result

    normalized = normalize_for_specials(cleaned_title)
    if not normalized:
        return None

    if normalized in title_lookup:
        result = title_lookup[normalized]
        if (result[0], result[1]) not in used:
            return result

    if len(normalized) < _MIN_LOOKUP_SUBSTRING_LEN:
        return None

    best: tuple[int, int, str] | None = None
    best_len = 0
    for key, value in title_lookup.items():
        if len(key) < _MIN_LOOKUP_SUBSTRING_LEN:
            continue
        if (value[0], value[1]) in used:
            continue
        if normalized in key or key in normalized:
            if len(key) > best_len:
                best = value
                best_len = len(key)
    if best is not None:
        return best

    if spaced_lookup:
        spaced = normalize_for_specials_spaced(cleaned_title)
        hits = [
            value
            for key_spaced, value in spaced_lookup.items()
            if (value[0], value[1]) not in used
            and _fuzzy_title_equal(
                normalized, spaced,
                re.sub(r"[^a-z0-9]", "", key_spaced), key_spaced,
            )
        ]
        if len(hits) == 1:
            return hits[0]
    return None


def try_title_based_matching(
    all_files: list[AbsoluteFileEntry],
    tmdb_seasons: dict,
) -> list[tuple[int, int, str] | None] | None:
    """Two-phase matching: title claims first (all seasons incl. S0), then
    explicit season-hint number fills, then absolute-number prefixes. Title
    claims MUST run first so a mis-numbered file can't squat on a slot a
    genuinely-titled file owns (RC18a)."""
    title_lookup: dict[str, tuple[int, int, str]] = {}
    spaced_lookup: dict[str, tuple[int, int, str]] = {}
    file_count = len(all_files)
    qualifying_seasons = [
        season_num for season_num, season_data in tmdb_seasons.items()
        if season_num != 0 and season_data["count"] >= file_count
    ]
    number_lookup: dict[int, tuple[int, int, str]] = {}
    # Regular seasons first so an S0 special never shadows a same-titled
    # regular episode; S0 keys fill the remaining gaps (RC18d).
    for season_num in sorted(tmdb_seasons.keys(), key=lambda s: (s == 0, s)):
        season_data = tmdb_seasons[season_num]
        for episode_num, title in season_data["titles"].items():
            normalized = normalize_for_specials(title)
            if normalized and normalized not in title_lookup:
                title_lookup[normalized] = (season_num, episode_num, title)
                spaced_lookup[normalize_for_specials_spaced(title)] = (
                    season_num, episode_num, title,
                )
            if (
                season_num != 0
                and len(qualifying_seasons) == 1
                and season_num == qualifying_seasons[0]
                and episode_num not in number_lookup
            ):
                number_lookup[episode_num] = (season_num, episode_num, title)

    if not title_lookup:
        return None

    matches: list[tuple[int, int, str] | None] = [None] * file_count
    used: set[tuple[int, int]] = set()

    def _reserve(match, episode_numbers, is_season_relative, season_hint):
        season_num, episode_num, _title = match
        used.add((season_num, episode_num))
        season_data = tmdb_seasons.get(season_num)
        if (
            season_data
            and is_season_relative
            and season_hint == season_num
            and episode_numbers
            and episode_numbers[0] == episode_num
        ):
            for episode in _contiguous_run(episode_numbers, season_data["titles"]):
                used.add((season_num, episode))

    # Phase 1: pure title claims.
    for index, (_fp, _abs, raw_title, eps, rel, hint) in enumerate(all_files):
        match = match_file_title_to_tmdb(
            raw_title, title_lookup, {}, used, spaced_lookup=spaced_lookup,
        )
        if match is not None:
            matches[index] = match
            _reserve(match, eps, rel, hint)

    # Phase 2: explicit season-hint number fills; Phase 3: absolute prefixes.
    for index, (_fp, _abs, raw_title, eps, rel, hint) in enumerate(all_files):
        if matches[index] is not None:
            continue
        if rel and hint is not None and eps:
            season_data = tmdb_seasons.get(hint)
            if season_data:
                title = season_data["titles"].get(eps[0])
                if title and (hint, eps[0]) not in used:
                    match = (hint, eps[0], title)
                    matches[index] = match
                    _reserve(match, eps, rel, hint)
                    continue
        match = match_file_title_to_tmdb(raw_title, {}, number_lookup, used)
        if match is not None:
            matches[index] = match
            used.add((match[0], match[1]))

    matched_count = sum(1 for match in matches if match is not None)
    if matched_count < len(all_files) * 0.5:
        return None
    return matches
```

- [ ] **Step 4: Guard S0-landed hinted files at review in `build_consolidated_table`**

In the `if item is not None and item.season is not None and item.episodes:` block (note: change the existing `item.season and … item.season != 0` condition to `item.season is not None and item.episodes` so S0 mappings flow through), cap cross-season S0 pulls:

```python
        item = mapped_by_path.get(file_path)
        if item is not None and item.season is not None and item.episodes:
            cand_season = item.season
            if cand_season == 0:
                cand_titles = s0_titles
            else:
                cand_titles = tmdb_seasons.get(cand_season, {}).get("titles", {})
            hint_matches = season_hint is None or season_hint == cand_season
            resolution = resolve_file(
                parsed_episodes=tuple(item.episodes),
                raw_title=raw_title,
                is_season_relative=is_season_relative and hint_matches,
                season_titles=cand_titles,
                season=cand_season,
            )
            if cand_season == 0 and (season_hint or 0) != 0 and resolution.episodes:
                # A hinted regular-season file landing in S0 is a
                # cross-season special pull -> review, never auto (RC18d).
                resolution = Resolution(
                    episodes=resolution.episodes,
                    confidence=min(resolution.confidence, CONF_TITLE_WINS_INEXACT),
                    evidence=resolution.evidence | {"cross-season-special"},
                )
            _apply_resolution(table, entry.file_id, cand_season, resolution)
```

(Import `Resolution` and `CONF_TITLE_WINS_INEXACT` in the function's existing lazy-import line: `from ._episode_resolution import CONF_TITLE_WINS_INEXACT, Resolution, resolve_file`. Note the `season_hint == 0` consolidated branch earlier in the loop still short-circuits true S0-hinted files.)

- [ ] **Step 5: Run tests**

Run: `.venv\Scripts\python.exe -m pytest tests\test_consolidated_two_phase.py tests\test_consolidated_assignments.py tests\test_scan_improvements.py -q`
Expected: PASS (update consolidated regression expectations if the two-phase order changes previously-asserted match tuples — verify each change is an improvement before editing the assertion).

- [ ] **Step 6: Commit**

```
git commit -am "fix: two-phase consolidated title claiming with S0 titles and 4-char floor (RC18a,b,d)"
```

---

### Task 14: RC18c/e — no sequence-mapping for hint-missing files; re-resolve leftovers against their hinted season

The sequential fallback interleaves S07E01/S08E01 into S01E01… (Reno), and match-None files die as NOT_IN_SEASON without ever running `resolve_file` (CatDog S03 E27-E38 would seg-run resolve against hinted S3).

**Files:**
- Modify: `plex_renamer/engine/_tv_scanner_consolidated.py` (`build_consolidated_preview` sequential fallback; `build_consolidated_table` else-branch)
- Test: `tests/test_consolidated_two_phase.py` (extend)

**Interfaces:**
- Produces: sequential fallback emits `SKIP: explicit season not in TMDB` items for hint-missing files; `build_consolidated_table` runs `resolve_file` against the hinted season before marking `REASON_NOT_IN_SEASON`.

- [ ] **Step 1: Write the failing tests** (append)

```python
from plex_renamer.engine._tv_scanner_consolidated import build_consolidated_table


def test_hint_missing_files_are_not_sequence_mapped(tmp_path):
    (tmp_path / "Season 7").mkdir()
    (tmp_path / "Season 1").mkdir()
    s7 = tmp_path / "Season 7" / "Reno - S07E01 - Unknown Title.mkv"
    s1 = tmp_path / "Season 1" / "Reno - S01E01 - Nonmatching Name.mkv"
    s7.touch(); s1.touch()
    tmdb = _seasons({1: {1: "The Investigation", 2: "Fireworks"}})
    table = build_consolidated_table(
        season_dirs=[(tmp_path / "Season 1", 1), (tmp_path / "Season 7", 7)],
        tmdb_seasons=tmdb,
        tmdb=None,
        show_info={"id": 1, "name": "Reno 911!", "year": "2003"},
        root=tmp_path,
        store_tmdb_data=lambda *args: None,
    )
    s7_entry = next(e for e in table.files.values() if e.path == s7)
    assignment = table.assignment_for(s7_entry.file_id)
    # S7 doesn't exist on TMDB: the file must NOT be sequence-mapped into S1.
    assert assignment is None or assignment.season != 1 or assignment.confidence < 0.85


def test_leftover_files_re_resolved_against_hinted_season(tmp_path):
    (tmp_path / "Season 3").mkdir()
    f = tmp_path / "Season 3" / "CatDog - S03 E27-E28 - Monster Truck Folly and CatDogs Gold.mkv"
    f.touch()
    tmdb = _seasons({
        3: {1: "Monster Truck Folly", 2: "CatDog's Gold"},
        # a big season so the title pass can fail the 50% gate:
        1: {n: f"Filler {n}" for n in range(1, 30)},
    })
    table = build_consolidated_table(
        season_dirs=[(tmp_path / "Season 3", 3)],
        tmdb_seasons=tmdb,
        tmdb=None,
        show_info={"id": 1, "name": "CatDog", "year": "1998"},
        root=tmp_path,
        store_tmdb_data=lambda *args: None,
    )
    entry = next(e for e in table.files.values() if e.path == f)
    assignment = table.assignment_for(entry.file_id)
    assert assignment is not None
    assert assignment.season == 3
    assert assignment.episodes == (1, 2)
```

Note for the executor: if the two-phase title pass (Task 13) already matches these fixtures, adjust fixture titles so the title pass genuinely fails (the point is the fallback path). `tmdb=None` is safe because `0 in tmdb_seasons` is only fetched when absent — add `0: {}`-style data or pass a stub with `get_season` returning `{"titles": {}}` if construction fails; use whatever `tests/test_consolidated_assignments.py` already uses as the stub pattern.

- [ ] **Step 2: Run to verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests\test_consolidated_two_phase.py -q`
Expected: the two new tests FAIL (S7 file lands in S1 at 0.86+; CatDog file stays `NOT_IN_SEASON`).

- [ ] **Step 3: Implement the sequential-fallback guard** in `build_consolidated_preview`

At the top of the sequential loop (`for file_path, _abs_num, _raw_title, episode_numbers, is_season_relative, _season_hint in all_files:`):

```python
        if (
            is_season_relative
            and _season_hint is not None
            and _season_hint not in tmdb_seasons
        ):
            # An explicit S## that TMDB doesn't know can't be sequence-
            # mapped — the interleave corrupts every later slot (RC18c).
            items.append(PreviewItem(
                original=file_path,
                new_name=None,
                target_dir=None,
                season=0,
                episodes=episode_numbers,
                status="SKIP: explicit season not in TMDB",
                **media_fields,
            ))
            continue
```

- [ ] **Step 4: Implement leftover re-resolution** in `build_consolidated_table`

Replace the final `else:` branch of the per-file loop:

```python
        else:
            fallback = None
            if season_hint is not None and season_hint != 0:
                hinted_titles = tmdb_seasons.get(season_hint, {}).get("titles", {})
                if hinted_titles:
                    candidate = resolve_file(
                        parsed_episodes=tuple(episode_numbers),
                        raw_title=raw_title,
                        is_season_relative=is_season_relative,
                        season_titles=hinted_titles,
                        season=season_hint,
                    )
                    if candidate.episodes:
                        fallback = (season_hint, candidate)
            if fallback is not None:
                _apply_resolution(table, entry.file_id, fallback[0], fallback[1])
            else:
                table.mark_unassigned(
                    entry.file_id,
                    REASON_NO_PARSE if not episode_numbers else REASON_NOT_IN_SEASON,
                )
```

- [ ] **Step 5: Run tests**

Run: `.venv\Scripts\python.exe -m pytest tests\test_consolidated_two_phase.py tests\test_consolidated_assignments.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```
git commit -am "fix: never sequence-map hint-missing seasons; re-resolve leftovers against hinted season (RC18c,e)"
```

---

### Task 15: RC19 — air-date cluster mapping for folder seasons missing from TMDB

Oshi no Ko S03E01-E11 (no titles at all) must map onto the 3rd airing cluster of TMDB's single consolidated 35-slot season (S01E25 'Down Bad' onward) at review confidence.

**Files:**
- Modify: `plex_renamer/engine/_tv_scanner_consolidated.py` (new `_air_date_clusters`, `apply_air_date_cluster_mapping`; call at end of `build_consolidated_table`)
- Test: `tests/test_air_date_clusters.py` (new)

**Interfaces:**
- Consumes: slot metadata `episodes` dicts with `air_date` (already stored by `_register_season_slots` / season_data).
- Produces: `apply_air_date_cluster_mapping(table, tmdb_seasons) -> None`; evidence `{"number", "air-date-cluster"}` at `CONF_TITLE_WINS_INEXACT` (add `"air-date-cluster"` to the review-lock set in `_episode_resolution.py`).

- [ ] **Step 1: Write the failing tests**

```python
"""RC19: folder-season N maps onto the Nth air-date cluster."""
from pathlib import Path

from plex_renamer.engine._tv_scanner_consolidated import (
    _air_date_clusters,
    apply_air_date_cluster_mapping,
)
from plex_renamer.engine._episode_resolution import CONF_TITLE_WINS_INEXACT
from plex_renamer.engine.episode_assignments import (
    REASON_NOT_IN_SEASON,
    EpisodeAssignmentTable,
    EpisodeSlot,
)


def _season_data():
    titles, episodes = {}, {}
    # three cours: eps 1-11 (2023), 12-24 (2024), 25-35 (2026)
    for episode in range(1, 12):
        titles[episode] = f"A{episode}"
        episodes[episode] = {"air_date": f"2023-04-{episode:02d}"}
    for episode in range(12, 25):
        titles[episode] = f"B{episode}"
        episodes[episode] = {"air_date": f"2024-07-{episode - 11:02d}"}
    for episode in range(25, 36):
        titles[episode] = f"C{episode}"
        episodes[episode] = {"air_date": f"2026-01-{episode - 24:02d}"}
    return {"count": 35, "titles": titles, "episodes": episodes, "posters": {}}


def test_air_date_clusters_split_on_gaps():
    clusters = _air_date_clusters(_season_data())
    assert [len(c) for c in clusters] == [11, 13, 11]
    assert clusters[2][0] == 25


def test_folder_season_maps_to_nth_cluster():
    tmdb_seasons = {1: _season_data()}
    table = EpisodeAssignmentTable()
    data = _season_data()
    for episode, title in data["titles"].items():
        table.add_slot(EpisodeSlot(
            season=1, episode=episode, title=title,
            air_date=data["episodes"][episode]["air_date"],
        ))
    entries = []
    for episode in range(1, 12):
        entry = table.add_file(
            Path(f"Oshi no Ko (2023) S03E{episode:02d}.mkv"),
            parsed_episodes=(episode,),
            raw_title=None,
            is_season_relative=True,
            season_hint=3,
            folder_season=3,
        )
        table.mark_unassigned(entry.file_id, REASON_NOT_IN_SEASON)
        entries.append(entry)
    apply_air_date_cluster_mapping(table, tmdb_seasons)
    first = table.assignment_for(entries[0].file_id)
    assert first is not None
    assert first.season == 1 and first.episodes == (25,)
    assert first.confidence == CONF_TITLE_WINS_INEXACT
    assert "air-date-cluster" in first.evidence
    last = table.assignment_for(entries[10].file_id)
    assert last.episodes == (35,)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests\test_air_date_clusters.py -q`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement** (top of `_tv_scanner_consolidated.py`: add `from datetime import date`; `from .episode_assignments import ORIGIN_AUTO` to the existing import; `from ._episode_resolution import CONF_TITLE_WINS_INEXACT` — module-top import is safe, no cycle)

```python
_CLUSTER_GAP_DAYS = 60


def _parse_air_date(value) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _air_date_clusters(season_data: dict) -> list[list[int]]:
    """Split a season's episodes into airing runs at multi-month gaps.

    Returns [] when any episode lacks a parseable air date — a partial
    clustering would mis-place everything after the hole.
    """
    episodes_meta = season_data.get("episodes", {}) or {}
    dated: list[tuple[int, date]] = []
    for episode_num in sorted(season_data.get("titles", {})):
        meta = episodes_meta.get(episode_num) or {}
        air = _parse_air_date(meta.get("air_date"))
        if air is None:
            return []
        dated.append((episode_num, air))
    if not dated:
        return []
    clusters: list[list[int]] = [[dated[0][0]]]
    previous = dated[0][1]
    for episode_num, air in dated[1:]:
        if (air - previous).days > _CLUSTER_GAP_DAYS:
            clusters.append([])
        clusters[-1].append(episode_num)
        previous = air
    return clusters


def apply_air_date_cluster_mapping(
    table: EpisodeAssignmentTable,
    tmdb_seasons: dict,
) -> None:
    """Map folder-season-N files onto the Nth airing cluster of a single
    consolidated TMDB season (Oshi no Ko S03 -> S01E25.., RC19). Review
    confidence — the mapping is inferred from air dates, not observed."""
    regular = [season for season in tmdb_seasons if season != 0]
    if len(regular) != 1:
        return
    target_season = regular[0]
    clusters = _air_date_clusters(tmdb_seasons[target_season])
    if len(clusters) < 2:
        return
    groups: dict[int, list[int]] = {}
    for file_id in table.unassigned_reasons:
        entry = table.files[file_id]
        hint = entry.season_hint
        if hint is None or hint == 0 or hint in tmdb_seasons:
            continue
        if not entry.parsed_episodes:
            continue
        groups.setdefault(hint, []).append(file_id)
    claimed = {
        (assignment.season, episode)
        for assignment in table.assignments()
        for episode in assignment.episodes
    }
    for hint, file_ids in groups.items():
        if hint > len(clusters):
            continue
        cluster = clusters[hint - 1]
        for file_id in sorted(
            file_ids, key=lambda f: table.files[f].parsed_episodes[0],
        ):
            entry = table.files[file_id]
            index = entry.parsed_episodes[0] - 1
            if index < 0 or index + len(entry.parsed_episodes) > len(cluster):
                continue
            proposed = cluster[index : index + len(entry.parsed_episodes)]
            slots = {(target_season, episode) for episode in proposed}
            if slots & claimed:
                continue
            table.assign(
                file_id, target_season, list(proposed), origin=ORIGIN_AUTO,
                confidence=CONF_TITLE_WINS_INEXACT,
                evidence=frozenset({"number", "air-date-cluster"}),
            )
            claimed |= slots
```

Call it at the end of `build_consolidated_table`, just before `return table`:

```python
    apply_air_date_cluster_mapping(table, tmdb_seasons)
    return table
```

Add `"air-date-cluster"` to the review-lock set in `apply_confidence_adjustments` (`_episode_resolution.py`).

- [ ] **Step 4: Run tests**

Run: `.venv\Scripts\python.exe -m pytest tests\test_air_date_clusters.py tests\test_consolidated_two_phase.py tests\test_consolidated_assignments.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```
git commit -am "feat: map hint-missing folder seasons onto air-date clusters (RC19)"
```

---

### Task 16: RC28 — duplicate copies with different numbers: no inline conflicts, no double counting

"S01E07 - Dexter's Rival" and "S01E34 - Dexter's Rival" both exact-claim E07 and render as a conflict; both inflate the season count. Same-title tied claimants must resolve as duplicate copies (keep the number-agreeing one), and the loser needs a distinct DUPLICATE status grouped separately in the GUI.

**Files:**
- Modify: `plex_renamer/engine/episode_assignments.py` (constants)
- Modify: `plex_renamer/engine/_episode_resolution.py` (`_claims_are_duplicate_copies`, `_auto_resolve_strong_title_conflicts`)
- Modify: `plex_renamer/engine/_episode_projection.py` (`_unassigned_item`)
- Modify: `plex_renamer/engine/models.py` (`PreviewItem.is_duplicate`)
- Modify: `plex_renamer/app/models/state_models.py` (`EpisodeGuide.duplicate_files`, `EpisodeGuideSummary.duplicate_files`)
- Modify: `plex_renamer/app/services/episode_mapping_service.py` (`build_episode_guide`)
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_preview.py` (render "Duplicate Copies" section)
- Test: `tests/test_duplicate_copies.py` (new)

**Interfaces:**
- Produces:
  - `REASON_DUPLICATE_COPY = "duplicate copy"` and `duplicate_copy_reason(season, episode) -> str` in `episode_assignments.py`.
  - Projection status: `f"DUPLICATE: {reason}"`; `PreviewItem.is_duplicate` property.
  - `EpisodeGuide.duplicate_files: list[UnmappedFileRow]`, `EpisodeGuideSummary.duplicate_files: int`.

- [ ] **Step 1: Write the failing tests**

```python
"""RC28: same-title tied claimants are duplicate copies, not conflicts."""
from pathlib import Path

from plex_renamer.engine._episode_resolution import (
    CONF_AGREE, CONF_TITLE_WINS, resolve_table_conflicts,
)
from plex_renamer.engine._episode_projection import project_preview_items
from plex_renamer.engine.episode_assignments import (
    REASON_DUPLICATE_COPY,
    EpisodeAssignmentTable,
    EpisodeSlot,
)


def _dexter_table():
    table = EpisodeAssignmentTable()
    table.add_slot(EpisodeSlot(season=1, episode=7, title="Dexter's Rival"))
    table.add_slot(EpisodeSlot(season=1, episode=8, title="Dee Dee's Room"))
    agreeing = table.add_file(
        Path("S01E07 - Dexter's Rival.mkv"),
        parsed_episodes=(7,), raw_title="Dexter's Rival",
        is_season_relative=True, season_hint=1, folder_season=1,
    )
    mislabeled = table.add_file(
        Path("S01E34 - Dexter's Rival.mkv"),
        parsed_episodes=(34,), raw_title="Dexter's Rival",
        is_season_relative=True, season_hint=1, folder_season=1,
    )
    table.assign(agreeing.file_id, 1, [7], origin="auto",
                 confidence=CONF_AGREE,
                 evidence=frozenset({"number", "title-agree"}))
    table.assign(mislabeled.file_id, 1, [7], origin="auto",
                 confidence=CONF_TITLE_WINS,
                 evidence=frozenset({"title-strong", "number-disagree"}))
    return table, agreeing, mislabeled


def test_differing_numbers_same_title_resolve_as_duplicates():
    table, agreeing, mislabeled = _dexter_table()
    resolve_table_conflicts(table)
    assert table.conflicts() == {}
    assignment = table.assignment_for(agreeing.file_id)
    assert assignment is not None and assignment.episodes == (7,)
    reason = table.unassigned_reasons[mislabeled.file_id]
    assert reason.startswith(REASON_DUPLICATE_COPY)


def test_duplicate_projects_with_duplicate_status(tmp_path):
    table, _agreeing, mislabeled = _dexter_table()
    resolve_table_conflicts(table)
    items = project_preview_items(
        table,
        show_info={"name": "Dexter's Laboratory", "year": "1996"},
        root=tmp_path,
        media_fields={},
    )
    duplicate_items = [item for item in items if item.status.startswith("DUPLICATE")]
    assert len(duplicate_items) == 1
    assert duplicate_items[0].is_duplicate
    assert duplicate_items[0].new_name is None
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests\test_duplicate_copies.py -q`
Expected: FAIL (`REASON_DUPLICATE_COPY` ImportError; conflict persists).

- [ ] **Step 3: Engine changes**

`episode_assignments.py`, next to the other REASON constants:

```python
REASON_DUPLICATE_COPY = "duplicate copy"


def duplicate_copy_reason(season: int, episode: int) -> str:
    """Reason marking a losing duplicate copy of one episode."""
    return f"{REASON_DUPLICATE_COPY} of S{season:02d}E{episode:02d}"
```

`_episode_resolution.py` — import `duplicate_copy_reason`, relax `_claims_are_duplicate_copies` (drop the identical-parsed-numbers requirement):

```python
def _claims_are_duplicate_copies(table: EpisodeAssignmentTable, claims: list) -> bool:
    """True when tied claims share the SAME real title — copies of one
    episode from parallel source folders, even when their parsed numbers
    differ (a mislabeled copy: "S01E34 - Dexter's Rival"). One normalized
    title may extend another with release junk."""
    titles = [
        normalize_for_specials(table.files[claim.file_id].raw_title or "")
        for claim in claims
    ]
    if any(not title for title in titles):
        return False
    shortest = min(titles, key=len)
    return all(title.startswith(shortest) for title in titles)
```

In `_auto_resolve_strong_title_conflicts`, replace the duplicate branch's keep-selection and reason:

```python
        if _claims_are_duplicate_copies(table, winners):
            # Prefer the claimant whose parsed number agrees with the slot;
            # fall back to the first-registered copy.
            keep = next(
                (
                    claim for claim in winners
                    if episode in table.files[claim.file_id].parsed_episodes
                ),
                min(winners, key=lambda claim: claim.file_id),
            )
            table.resolve_conflict(season, episode, winner_file_id=keep.file_id)
            for claim in winners:
                if claim.file_id != keep.file_id:
                    table.mark_unassigned(
                        claim.file_id, duplicate_copy_reason(season, episode),
                    )
            continue
```

- [ ] **Step 4: Projection + model changes**

`_episode_projection.py` — import `REASON_DUPLICATE_COPY`; at the top of `_unassigned_item`:

```python
    if reason.startswith(REASON_DUPLICATE_COPY):
        return PreviewItem(
            original=entry.path,
            new_name=None,
            target_dir=None,
            season=entry.folder_season,
            episodes=list(entry.parsed_episodes),
            status=f"DUPLICATE: {reason}",
            file_id=entry.file_id,
            source_relative_folder=entry.source_relative_folder,
            **media_fields,
        )
```

`models.py`, next to `is_skipped`:

```python
    @property
    def is_duplicate(self) -> bool:
        return self.status.startswith("DUPLICATE")
```

- [ ] **Step 5: Guide + GUI changes**

`state_models.py`: add `duplicate_files: list[UnmappedFileRow] = field(default_factory=list)` to `EpisodeGuide` and `duplicate_files: int = 0` to `EpisodeGuideSummary`.

`episode_mapping_service.py` `build_episode_guide`, at the top of the preview loop (before the `_is_episode_mapped` check):

```python
            if preview.is_duplicate:
                guide.duplicate_files.append(
                    UnmappedFileRow(
                        original=preview.original,
                        reason=preview.status.removeprefix("DUPLICATE: "),
                        preview=preview,
                    )
                )
                continue
```

and add `duplicate_files=len(guide.duplicate_files),` to the `EpisodeGuideSummary(...)` construction.

`_media_workspace_preview.py`: after the `unmapped_primary_files` block (line ~383), add a mirrored section:

```python
        if self._episode_filter in {"all", "problems"} and guide.duplicate_files:
            self.add_static_header(
                f"Duplicate Copies ({len(guide.duplicate_files)})",
                render_key=render_key,
            )
            for duplicate in guide.duplicate_files:
                index = (
                    state.preview_items.index(duplicate.preview)
                    if duplicate.preview in state.preview_items else None
                )
                item = QListWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole, index)
                item.setData(_PREVIEW_ENTRY_KIND_ROLE, "duplicate")
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                self._add_rendered_item(item, render_key)
                widget = _EpisodeGuideRowWidget(
                    title=duplicate.original.name,
                    status="Duplicate",
                    original=str(duplicate.reason),
                    actions=[],
                    parent=self._list_widget,
                )
                widget.clicked.connect(
                    lambda item=item: self._list_widget.setCurrentItem(item)
                )
                self._sync_item_height(item, widget)
                self._list_widget.setItemWidget(item, widget)
```

Duplicates never enter `rows_by_season`, so season headers and ratios exclude them automatically (the double-count came from the conflict rows, which no longer exist).

- [ ] **Step 6: Run tests**

Run: `.venv\Scripts\python.exe -m pytest tests\test_duplicate_copies.py tests\test_conflict_resolution.py tests\test_episode_mapping_projection.py tests\test_episode_projection.py -q`
Expected: PASS (update projection-service tests if they assert the old `SKIP: duplicate copy…` status or summary fields).
Then: `scripts\test-smoke.cmd` → PASS (GUI touched).

- [ ] **Step 7: Commit**

```
git commit -am "fix: duplicate copies with differing numbers resolve silently and group separately (RC28)"
```

---

### Task 17: RC16 — show scoring for year-less folders and TMDB-missing seasons

Year-less release folders forfeit the 0.3 year weight (max ≈0.73 < the 0.82 auto-accept threshold), and the episode-evidence boost *punishes* shows whose folder season is missing from TMDB instead of matching titles across all seasons.

**Files:**
- Modify: `plex_renamer/engine/matching.py:112,317-337`
- Test: `tests/test_show_scoring_no_year.py` (new)

**Interfaces:**
- Produces: `score_results` uses title-only weighting when `year_hint` is falsy; `_tv_episode_evidence_adjustment` matches evidence titles against ALL seasons when the hinted season is missing. (Apostrophe folding for "Hell's" landed in Task 3.)

- [ ] **Step 1: Write the failing tests**

```python
"""RC16: year-less folders must reach auto-accept on exact titles."""
from plex_renamer.engine.matching import _tv_episode_evidence_adjustment, score_results


def test_exact_title_without_year_scores_full():
    results = [{"id": 1, "title": "Jujutsu Kaisen", "year": "2020"}]
    scored = score_results(results, "Jujutsu Kaisen", None)
    assert scored[0][1] >= 1.0  # 1.0 title + 0.15 exact bonus, no year forfeit


def test_year_weighting_unchanged_when_hint_present():
    results = [{"id": 1, "title": "Jujutsu Kaisen", "year": "2020"}]
    scored = score_results(results, "Jujutsu Kaisen", "2020")
    assert scored[0][1] >= 1.0


class _FakeTMDB:
    def __init__(self, seasons):
        self._seasons = seasons

    def get_season_map(self, show_id):
        return self._seasons, {}


class _Evidence:
    def __init__(self, season_num, episode_num, raw_title):
        self.season_num = season_num
        self.episode_num = episode_num
        self.raw_title = raw_title


def test_missing_season_titles_match_across_all_seasons():
    seasons = {1: {"count": 2, "titles": {1: "Execution", 2: "Sendai Colony"}}}
    tmdb = _FakeTMDB(seasons)
    evidence = [
        _Evidence(3, 1, "Execution"),
        _Evidence(3, 2, "Sendai Colony"),
    ]
    adjustment = _tv_episode_evidence_adjustment(tmdb, 1, evidence)
    # coverage penalty (-0.12) must be outweighed by the title boost (+0.24)
    assert adjustment > 0.0
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests\test_show_scoring_no_year.py -q`
Expected: FAIL — year-less score ≈0.85 (0.7+0.15) but adjustment test returns ≤ -0.02.

(If the first assertion unexpectedly passes at 0.85≥…, tighten it: assert `scored[0][1] > 0.9`.)

- [ ] **Step 3: Implement**

`score_results` (line ~112):

```python
        if year_hint:
            score = (t_score * 0.7) + (year_score * 0.3)
        else:
            # No year in the source folder: don't forfeit the year weight —
            # an exact title must be able to reach auto-accept on its own.
            score = t_score
```

`_tv_episode_evidence_adjustment` — replace the per-item loop:

```python
    exact_episode_hits = 0
    title_scores: list[float] = []
    merged_titles: dict[int, str] | None = None
    limited_evidence = evidence[:8]
    for item in limited_evidence:
        season_data = tmdb_seasons.get(item.season_num)
        if season_data:
            season_titles = season_data.get("titles", {})
            if item.episode_num in season_titles:
                exact_episode_hits += 1
            title_scores.append(
                _best_episode_title_similarity(item.raw_title, season_titles)
            )
            continue
        # The hinted season is missing from TMDB (consolidated shows): match
        # the title evidence against every season instead of skipping, so
        # real episode titles still corroborate the show (RC16).
        if merged_titles is None:
            merged_titles = {}
            for data in tmdb_seasons.values():
                for title in data.get("titles", {}).values():
                    merged_titles[len(merged_titles)] = title
        title_scores.append(
            _best_episode_title_similarity(item.raw_title, merged_titles)
        )
```

- [ ] **Step 4: Run tests**

Run: `.venv\Scripts\python.exe -m pytest tests\test_show_scoring_no_year.py tests\test_alt_title_matching.py tests\test_movie_discovery.py tests\test_haikyuu_matching.py tests\test_jojo_matching.py -q`
Expected: PASS (movie/TV scoring shares `score_results` — if a movie test asserted a year-less penalty, verify the new behavior is correct and update the expectation).

- [ ] **Step 5: Commit**

```
git commit -am "fix: title-only show scoring without year hints; cross-season evidence titles (RC16)"
```

---

### Task 18: Evidence-tag bookkeeping from the findings' Notes section

Two small evidence-integrity items from the findings doc: consolidated title-picked assignments self-confirm as 'number'+'title-agree' (circular), and `_rescue_group` tags offset movers with 'season-relative' even when the resolution treated the file as NOT season-relative.

**Files:**
- Modify: `plex_renamer/engine/_tv_scanner_consolidated.py` (`build_consolidated_table`)
- Modify: `plex_renamer/engine/_episode_resolution.py` (`_rescue_group`)
- Test: `tests/test_consolidated_two_phase.py` (extend)

- [ ] **Step 1: Write the failing test** (append)

```python
def test_consolidated_title_pick_carries_marker_tag(tmp_path):
    (tmp_path / "Season 1").mkdir()
    f = tmp_path / "Season 1" / "Show - S01E01 - The Pilot.mkv"
    f.touch()
    tmdb = _seasons({1: {1: "The Pilot", 2: "Fireworks"}})
    table = build_consolidated_table(
        season_dirs=[(tmp_path / "Season 1", 1)],
        tmdb_seasons=tmdb, tmdb=None,
        show_info={"id": 1, "name": "Show", "year": "2020"},
        root=tmp_path, store_tmdb_data=lambda *args: None,
    )
    entry = next(iter(table.files.values()))
    assignment = table.assignment_for(entry.file_id)
    assert "title-consolidated" in assignment.evidence
```

- [ ] **Step 2: Run to verify failure, then implement**

In `build_consolidated_table`, when applying an item-backed resolution, tag it:

```python
            if resolution.episodes:
                resolution = Resolution(
                    episodes=resolution.episodes,
                    confidence=resolution.confidence,
                    evidence=resolution.evidence | {"title-consolidated"},
                    reason=resolution.reason,
                )
            _apply_resolution(table, entry.file_id, cand_season, resolution)
```

(`"title-consolidated"` is informational — do NOT add it to the review-lock set.)

In `_rescue_group`'s final assign loop, only tag season-relative when the hint matches the target season:

```python
        evidence = {"number", "offset-inferred"}
        if entry.is_season_relative and (
            entry.season_hint is None or entry.season_hint == target_season
        ):
            evidence.add("season-relative")
```

- [ ] **Step 3: Run tests**

Run: `.venv\Scripts\python.exe -m pytest tests\test_consolidated_two_phase.py tests\test_offset_inference.py -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```
git commit -am "chore: honest evidence tags for consolidated picks and offset rescues"
```

---

### Task 19: Full-suite verification + real-library validation

**Files:**
- Modify: `docs/superpowers/plans/2026-07-02-batch-tv-bug-investigation-round2.md` (status header)

- [ ] **Step 1: Full fast suite**

Run: `scripts\test-fast.cmd`
Expected: PASS, zero failures.

- [ ] **Step 2: Qt smoke**

Run: `scripts\test-smoke.cmd`
Expected: exit 0 (log at `.pytest_cache/smoke/latest.log`).

- [ ] **Step 3: Real-library harness run** (needs `P:` drive + TMDB key; several minutes)

Run: `.venv\Scripts\python.exe scripts\scan_real_library.py`
If the script exits with code 2 ("library root not found"), the `P:` drive is not mounted — STOP here, report that real-library validation is blocked on drive availability, and hand back to the user; do NOT point the harness at a substitute directory. Otherwise verify each user bug against the dumps in `.scan-dumps\`:

| Check | Expectation |
|---|---|
| discovery.txt: Frieren / JJK / Hell's Paradise | confidence ≥ 0.82, `needs_review=False` (RC16) |
| JJK show dump | episode titles exact ('Execution' not 'Execution 1080p…'); rule-2 assignments at ≥0.90, not per-episode review (RC17) |
| Oshi no Ko | S03E01→S01E25 'Down Bad', E11→S01E35, review confidence with `air-date-cluster` (RC19) |
| Animaniacs REPACK files | seg-run assignments S01E01-E03 style, no wrong disc numbers kept (RC17) |
| Archer Heart of Archness | S00E03/04/05 via `title-part-number` at review (RC23) |
| CatDog | E37-E38 both claimed; S03E27+ resolved via hinted season; Sumo file cross-season-rescued to S2 (RC18/RC20/RC22) |
| Catscratch | 2-episode runs per file at review (RC21) |
| Dexter's Lab | no inline conflict; one DUPLICATE row per copy; season counts correct (RC28) |
| Doctor Who | S02E10 stays S02E10 at 0.96 (RC24); Clarence/She Said → S00E85/E86 (RC25) |
| KaBlam | Henry & June root file → S00E02 (RC26) |
| Lucy | rule-1 0.96 auto (RC27) |
| Reno 911 | S1-6 title-anchored; S7/S8 files S0-matched at review or parked review — NO S01E01 interleave (RC18c/d) |
| Rugrats | S04E21 file claims E20-E21; S7+ mis-numbered files review-capped, not 0.88 OK (RC20/RC22) |
| Angry Beavers | 'H-2 Whoa'/'Scientist #1'/'Dagski & Norb' all mapped (RC20-1) |
| Tom Goes to the Mayor | 'My Bigs Cups'/'Friend Alliance' fuzzy-matched at review (RC20-2) |

- [ ] **Step 4: Record results**

Update the round-2 findings doc's status header to `**Status: fixed — see 2026-07-02-batch-tv-round2-fixes.md**` plus a line per RC noting the regression-test file, mirroring the round-1 doc's format. Note any check that did NOT meet expectation (live TMDB may differ) — do not silently pass.

- [ ] **Step 5: Commit**

```
git commit -am "docs: round-2 TV batch fixes validated against real library (RC16-RC28)"
```

---

## Self-review checklist (completed at plan time)

- **Spec coverage:** RC16 (T3 apostrophes, T17 scoring), RC17 (T1), RC18a/b/d (T13), RC18c/e (T14), RC19 (T15), RC20-1 (T3), RC20-2 (T4), RC20-3 (T6), RC20-4 (T8), RC21 (T5), RC22 (T7), RC23 (T12), RC24 (T3+T9), RC25 (T10), RC26 (T11), RC27 (T2), RC28 (T16), Notes-section items (T18). RC29 deferred by design.
- **Type consistency:** `match_segmented_title_run` returns `(run, all_exact)` from Task 4 onward; Tasks 7, 13–15 were written against the new signature. `normalize_for_specials_spaced` introduced in Task 3, consumed in Tasks 4 and 13.
- **Ordering:** parsing/normalization (T1–T5) precedes resolution-policy (T6–T12) precedes consolidated (T13–T15) precedes GUI/scoring (T16–T17), per the findings doc's suggested order.
