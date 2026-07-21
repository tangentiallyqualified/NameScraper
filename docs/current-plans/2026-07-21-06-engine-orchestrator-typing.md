# Engine Orchestrator Typing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the 28 committed Pyright findings in `_batch_orchestrators.py` by carrying existing discovery and season-folder types through the orchestration boundary.

**Architecture:** Replace `object` candidate tuples and untyped helpers with the structural discovery protocols already defined in `_discovery_ports.py`. Correct the `SeasonFolderEntry` map and narrow nullable preview names before subtitle construction. No runtime behavior or data shape changes.

**Tech Stack:** Python 3.14 typing, Protocol/Sequence/type aliases, Pyright, pytest.

## Global Constraints

- Implement the production-code portion of `QUAL-001`/`QUAL-002` without `Any`, casts to `object`, or new Pyright suppressions.
- Preserve discovery ordering, matching, state construction, and scan output.
- The target file must finish with zero Pyright findings and be removed from legacy typing when strict-clean.
- Baseline updates may prune only.

---

### Task 1: Type TV discovery candidates end to end

**Files:**
- Modify: `plex_renamer/engine/_batch_orchestrators.py:46,218-306`
- Test: `tests/test_scan_improvements.py`
- Test: `tests/test_roster_classification.py`

**Interfaces:**
- Consumes: `TVLibraryDiscoverer.discover_show_roots(...) -> Sequence[TVDiscoveryCandidateLike]`
- Produces: `ShowCandidate = tuple[TVDiscoveryCandidateLike, str, str, str, str | None, list[DirectEpisodeEvidence]]`

- [ ] **Step 1: Capture the initial finding count**

Run: `.venv\Scripts\pyright.exe plex_renamer\engine\_batch_orchestrators.py`
Expected: 28 errors matching the committed baseline.

- [ ] **Step 2: Add the candidate alias and exact signatures**

```python
from collections.abc import Callable, Sequence

ShowCandidate = tuple[
    TVDiscoveryCandidateLike,
    str,
    str,
    str,
    str | None,
    list[DirectEpisodeEvidence],
]

def _build_show_candidates(
    self,
    discovered: Sequence[TVDiscoveryCandidateLike],
    cancel_event: threading.Event | None = None,
) -> list[ShowCandidate]:
    candidates: list[ShowCandidate] = []
```

Annotate `_candidate_state_kwargs(candidate: TVDiscoveryCandidateLike) -> dict[str, object]`, `_build_unmatched_show_state`, and `_build_discovered_show_state` with the same candidate protocol. Remove downstream casts made unnecessary by the alias.

- [ ] **Step 3: Run TV discovery tests**

Run: `.venv\Scripts\python.exe -m pytest tests\test_scan_improvements.py tests\test_roster_classification.py -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```powershell
git add plex_renamer/engine/_batch_orchestrators.py
git commit -m "types: carry TV discovery candidate protocol"
```

### Task 2: Type movie candidates and nullable preview output

**Files:**
- Modify: `plex_renamer/engine/_batch_orchestrators.py:46,1157-1360`
- Test: `tests/test_movie_discovery.py`
- Test: `tests/test_companion_subtitles.py`

**Interfaces:**
- Consumes: `MovieLibraryDiscoverer.discover_movie_roots(...) -> Sequence[MovieDiscoveryCandidateLike]`
- Produces: `MovieCandidate = tuple[MovieDiscoveryCandidateLike, str, str | None, Path | None]`

- [ ] **Step 1: Type the movie entry list**

```python
from ._discovery_ports import (
    MovieDiscoveryCandidateLike,
    MovieLibraryDiscoverer,
    TVDiscoveryCandidateLike,
    TVLibraryDiscoverer,
)

MovieCandidate = tuple[MovieDiscoveryCandidateLike, str, str | None, Path | None]
entries: list[MovieCandidate] = []
```

- [ ] **Step 2: Narrow `item.new_name` before companion construction**

```python
item = _build_movie_preview_item(file, chosen, self.root)
if item.new_name is None:
    raise ValueError(f"movie preview has no target name: {file.name}")
item.companions = _build_subtitle_companions(file, item.new_name)
```

If `_build_movie_preview_item` already guarantees a target, prefer correcting its return type or `PreviewItem.new_name` construction path over adding an unreachable runtime branch; prove the chosen narrowing with its existing tests.

- [ ] **Step 3: Run movie and subtitle regressions**

Run: `.venv\Scripts\python.exe -m pytest tests\test_movie_discovery.py tests\test_companion_subtitles.py tests\test_scan_improvements.py -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```powershell
git add plex_renamer/engine/_batch_orchestrators.py
git commit -m "types: carry movie discovery candidate protocol"
```

### Task 3: Correct season-folder and callback types, then enroll strict

**Files:**
- Modify: `plex_renamer/engine/_batch_orchestrators.py`
- Modify prune-only: `scripts/audit/quality-baseline.json`
- Test: `tests/test_umbrella_season_merge.py`

- [ ] **Step 1: Use the existing season-folder union**

```python
from .models import PreviewItem, ScanState, SeasonFolderEntry

season_map: dict[int, SeasonFolderEntry] = {}
```

Replace bare `Callable` progress callbacks with the existing concrete callback alias, or introduce `ProgressCallback = Callable[[int, int, str], None]` only after matching every call site. Do not silence incompatible callback calls.

- [ ] **Step 2: Reach zero file-scoped errors**

Run: `.venv\Scripts\pyright.exe plex_renamer\engine\_batch_orchestrators.py`
Expected: 0 errors.

- [ ] **Step 3: Run the orchestration regression set**

Run: `.venv\Scripts\python.exe -m pytest tests\test_scan_improvements.py tests\test_movie_discovery.py tests\test_umbrella_season_merge.py tests\test_batch_autoaccept_guards.py -q`
Expected: PASS.

- [ ] **Step 4: Format, prune the baseline, and prove no enlargement**

Run: `.venv\Scripts\ruff.exe format plex_renamer\engine\_batch_orchestrators.py && .venv\Scripts\ruff.exe check plex_renamer\engine\_batch_orchestrators.py`
Expected: exit 0.

Run: `scripts\audit.cmd --update-quality-baseline`
Expected: exit 0 without acceptance flags; the file's Pyright findings and legacy-typing entry are removed.

- [ ] **Step 5: Commit**

```powershell
git add plex_renamer/engine/_batch_orchestrators.py scripts/audit/quality-baseline.json
git commit -m "types: enroll batch orchestrators at strict"
```
