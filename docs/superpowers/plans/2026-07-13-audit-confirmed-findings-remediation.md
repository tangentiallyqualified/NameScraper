# Confirmed Audit Findings Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove all 108 findings classified `CONFIRMED` in `docs/audit/findings-review.md` while preserving every reviewed public, test-facing, serialization, SQLite, and Qt framework surface classified `FALSE_POSITIVE`.

**Architecture:** Keep discovery implementations in the application layer and make the engine consume structural discovery ports through constructor injection. Group the remaining cleanup by subsystem so each task removes a coherent set of dead imports, wrappers, fields, or widget bindings and proves behavior with the narrowest relevant tests before running the repository-wide audit.

**Tech Stack:** Python 3.11, PySide6 6.6+, pytest 8+, Ruff, Vulture, the repository audit harness, PowerShell 5.1.

## Global Constraints

- Source of truth: `docs/audit/findings-review.md` and its three linked detailed reviews, generated against production source at commit `486aaef` and manually reviewed at `e5f4f40`.
- Scope is exactly 108 `CONFIRMED` records: 36 non-GUI, 30 GUI-core/early-widget, and 42 late-widget records.
- Do not delete or weaken any of the 95 `FALSE_POSITIVE` surfaces. In particular, preserve Qt overrides and callback parameters, dataclass/serialization fields, SQLite protocol assignments, compatibility re-exports, supported public methods, and deliberate test/introspection seams.
- Do not treat the 142 Radon `MEASURED` records as bugs. Complexity reduction is a separate project.
- Do not add false-positive allowlist work to this plan. Analyzer-noise suppression is useful but is not remediation of a real issue and should be planned separately.
- Start implementation only after the currently uncommitted `docs/audit/findings-review*.md`, `docs/audit/doc-ledger.toml`, and `docs/audit/maps/overview.md` changes are committed or otherwise preserved. Do not overwrite those user changes.
- Execute in an isolated worktree created with `superpowers:using-git-worktrees`.
- Run Python only through `.venv\Scripts\python.exe` and use the existing `scripts\test-fast.cmd`, `scripts\test-smoke.cmd`, and `scripts\audit.cmd` wrappers.
- Preserve behavior while deleting dead surfaces. A cleanup task starts with passing focused tests, makes the exact removals listed, then requires the same focused tests to pass again.
- For widget bindings marked “remove binding; keep builder call,” delete only `self._name =`. The `_toggle`, `_lang_row`, or `_lang_list_row` call, signal connection, and layout insertion must remain.
- A repeated raw finding can represent one source edit. The plan removes `_poster_pixmap` once as a field lifecycle and `QPointF` once as a duplicated Ruff/Vulture import finding, while accounting for every raw record in traceability totals.
- Commit after every task. Do not stage unrelated files from the pre-existing dirty worktree.

## Approach Decision

Three approaches were evaluated for the two confirmed layer violations:

1. **Inject discovery ports (chosen).** `BatchTVOrchestrator` and `BatchMovieOrchestrator` already accept discovery services, and `MediaController` already owns `TVLibraryDiscoveryService`. Making those dependencies explicit removes both forbidden imports with a small, testable API change.
2. **Move discovery services into `engine`.** This would also require moving discovery models and classifiers or creating compatibility wrappers across at least four modules. It makes filesystem orchestration a bottom-layer concern and creates unnecessary migration work.
3. **Move batch orchestrators into `app`.** This restores direction but churns the exported engine API and many engine-focused tests. It is much broader than the two offending imports.

The chosen design adds engine-owned structural protocols only; concrete discovery services and their models remain in `plex_renamer.app`.

---

### Task 1: Restore the engine/application dependency direction

**Findings closed:** 3 records — the two contract violations plus the write-only `MediaController._movie_discovery` assignment.

**Files:**
- Create: `plex_renamer/engine/_discovery_ports.py`
- Modify: `plex_renamer/engine/_batch_orchestrators.py`
- Modify: `plex_renamer/engine/_movie_scanner.py`
- Modify: `plex_renamer/app/controllers/media_controller.py`
- Modify: `scripts/scan_real_library.py`
- Modify: `tests/test_jojo_matching.py`
- Modify: `tests/test_movie_confidence_adjustments.py`
- Create: `tests/audit/test_repository_contracts.py`

**Interfaces:**
- Produces: `TVLibraryDiscoverer.discover_show_roots(library_root: Path) -> Sequence[TVDiscoveryCandidateLike]`.
- Produces: `MovieLibraryDiscoverer.discover_movie_roots(library_root: Path) -> Sequence[MovieDiscoveryCandidateLike]`.
- Changes: both batch orchestrator constructors require a discovery collaborator; there is no engine fallback import.
- Changes: folder-mode `MovieScanner` requires an injected TV discoverer; explicit-file mode remains usable without one because it never performs library discovery.
- Removes: `MediaController(..., movie_discovery=...)` and `self._movie_discovery`.

- [ ] **Step 1: Write a repository-level failing contract test**

Create `tests/audit/test_repository_contracts.py`:

```python
"""Repository-specific architectural contract regressions."""

from pathlib import Path

from audit import _analyze, _graph, _inventory


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_engine_does_not_import_application_layer():
    inventory = _inventory.build_inventory(REPO_ROOT)
    graph = _graph.build_graph(REPO_ROOT, inventory)
    contracts = (REPO_ROOT / "scripts" / "audit" / "contracts.toml").read_text(
        encoding="utf-8",
    )
    findings = _analyze._check_contracts(graph, contracts)
    engine_to_app = [
        finding
        for finding in findings
        if finding["category"] == "layer-violation"
        and finding["symbol"].startswith("plex_renamer.app")
    ]
    assert engine_to_app == []
```

- [ ] **Step 2: Run the contract test and inventory all affected call sites**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\audit\test_repository_contracts.py -q
rg -n "BatchTVOrchestrator\(|BatchMovieOrchestrator\(|MovieScanner\(" plex_renamer tests scripts -g "*.py"
```

Expected: the test fails with exactly two `engine -> app` findings, from `_batch_orchestrators.py` and `_movie_scanner.py`. The search must be copied into the task notes so no folder-mode scanner construction is missed.

- [ ] **Step 3: Add engine-owned structural discovery ports**

Create `plex_renamer/engine/_discovery_ports.py`:

```python
"""Structural ports for application-owned library discovery."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, Sequence


class TVDiscoveryCandidateLike(Protocol):
    folder: Path
    relative_folder: str
    parent_relative_folder: str | None
    discovery_reason: str
    has_direct_season_subdirs: bool
    direct_episode_file_count: int
    direct_video_file_count: int
    discovered_via_symlink: bool


class MovieDiscoveryCandidateLike(Protocol):
    folder: Path
    relative_folder: str
    parent_relative_folder: str | None
    discovery_reason: str
    direct_video_file_count: int
    discovered_via_symlink: bool


class TVLibraryDiscoverer(Protocol):
    def discover_show_roots(
        self,
        library_root: Path,
    ) -> Sequence[TVDiscoveryCandidateLike]: ...


class MovieLibraryDiscoverer(Protocol):
    def discover_movie_roots(
        self,
        library_root: Path,
    ) -> Sequence[MovieDiscoveryCandidateLike]: ...
```

Do not import application dataclasses into this module; the application services satisfy these protocols structurally.

- [ ] **Step 4: Make batch-orchestrator discovery injection mandatory**

In `plex_renamer/engine/_batch_orchestrators.py`, import the two discoverer protocols and change the constructors to:

```python
    def __init__(
        self,
        tmdb: TMDBClient,
        library_root: Path,
        discovery_service: TVLibraryDiscoverer,
    ):
        self.tmdb = tmdb
        self.root = library_root
        self.states: list[ScanState] = []
        self.discovery_service = discovery_service
```

```python
    def __init__(
        self,
        tmdb: TMDBClient,
        library_root: Path,
        discovery_service: MovieLibraryDiscoverer,
    ):
        self.tmdb = tmdb
        self.root = library_root
        self.states: list[ScanState] = []
        self.discovery_service = discovery_service
```

Delete both `_get_discovery_service` methods and replace their callers with direct use:

```python
        discovered = self.discovery_service.discover_show_roots(self.root)
```

```python
        discovered = self.discovery_service.discover_movie_roots(self.root)
```

There must be no `from ..app` import anywhere under `plex_renamer/engine` after this step.

- [ ] **Step 5: Inject TV discovery into folder-mode movie scanning**

In `plex_renamer/engine/_movie_scanner.py`, add `TVLibraryDiscoverer` and change the constructor/state:

```python
    def __init__(
        self,
        tmdb: TMDBClient,
        root_folder: Path,
        files: list[Path] | None = None,
        *,
        tv_discovery_service: TVLibraryDiscoverer | None = None,
    ):
        self.tmdb = tmdb
        self.root = root_folder
        self._explicit_files = files
        self._tv_discovery_service = tv_discovery_service
        self.movie_info: dict[Path, dict] = {}
        self._search_cache: dict[Path, list[dict]] = {}
```

Replace the local application import in `_filter_tv_show_root_files` with:

```python
        if self._tv_discovery_service is None:
            raise RuntimeError(
                "folder-mode MovieScanner requires a TV library discoverer"
            )

        show_roots = self._tv_discovery_service.discover_show_roots(self.root)
```

Keep the existing early return for explicit-file mode before this guard. This lets `BatchMovieOrchestrator.scan_state` continue constructing `MovieScanner(..., files=video_files)` without an irrelevant TV discoverer.

- [ ] **Step 6: Inject the application service and remove dead movie discovery state**

In `plex_renamer/app/controllers/media_controller.py`:

- Remove the `MovieLibraryDiscoveryService` import.
- Remove the `movie_discovery` constructor parameter.
- Remove `self._movie_discovery = movie_discovery or MovieLibraryDiscoveryService()`.
- Change `start_movie_batch` to use `None` as the factory sentinel and build the real scanner with the already-owned TV discoverer:

```python
    def start_movie_batch(
        self,
        folder: Path,
        tmdb: Any,
        *,
        scanner_factory: Any | None = None,
    ) -> None:
        factory = scanner_factory
        if factory is None:
            def factory(client: Any, root: Path) -> MovieScanner:
                return MovieScanner(
                    client,
                    root,
                    tv_discovery_service=self._tv_discovery,
                )

        self._movie_workflow.start_batch(
            folder,
            tmdb,
            scanner_factory=factory,
        )
```

Explicit fake factories used by controller tests remain untouched and receive only `(tmdb, folder)`.

- [ ] **Step 7: Update non-controller construction sites**

In `scripts/scan_real_library.py`, add this import alongside the other `plex_renamer` imports:

```python
from plex_renamer.app.services import TVLibraryDiscoveryService
```

Then replace the existing two-argument orchestrator construction with:

```python
orch = BatchTVOrchestrator(
    tmdb,
    args.root,
    discovery_service=TVLibraryDiscoveryService(),
)
```

In both folder-mode constructions in `tests/test_jojo_matching.py`, construct:

```python
scanner = MovieScanner(
    tmdb,
    root,
    tv_discovery_service=TVLibraryDiscoveryService(),
)
```

In `MovieScannerConfidenceTests._make_scanner` in `tests/test_movie_confidence_adjustments.py`, use the same `tv_discovery_service=TVLibraryDiscoveryService()` keyword and add the service import. Do not add a discoverer to the explicit-file construction inside `BatchMovieOrchestrator.scan_state`.

- [ ] **Step 8: Verify architecture and scan behavior**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\audit\test_repository_contracts.py tests\test_movie_discovery.py tests\test_jojo_matching.py tests\test_media_controller.py tests\test_batch_autoaccept_guards.py tests\test_alt_title_matching.py -q
.venv\Scripts\python.exe -m ruff check plex_renamer\engine plex_renamer\app\controllers scripts\scan_real_library.py tests\audit\test_repository_contracts.py
rg -n "from \.\.app|from plex_renamer\.app|import plex_renamer\.app" plex_renamer\engine
```

Expected: all tests pass; Ruff exits 0; the final search prints nothing.

- [ ] **Step 9: Commit**

```powershell
git add plex_renamer/engine/_discovery_ports.py plex_renamer/engine/_batch_orchestrators.py plex_renamer/engine/_movie_scanner.py plex_renamer/app/controllers/media_controller.py scripts/scan_real_library.py tests/audit/test_repository_contracts.py tests/test_jojo_matching.py tests/test_movie_confidence_adjustments.py
git commit -m "fix(architecture): inject discovery ports into engine"
```

---

### Task 2: Remove dead application-controller, model, and discovery-service surfaces

**Findings closed:** 11 non-GUI records.

**Files:**
- Modify: `plex_renamer/app/controllers/queue_controller.py`
- Modify: `plex_renamer/app/models/state_models.py`
- Modify: `plex_renamer/app/services/_tv_library_classification.py`
- Modify: `plex_renamer/app/services/tv_library_discovery_service.py`
- Test: `tests/test_queue_controller.py`
- Test: `tests/test_scan_progress.py`
- Test: `tests/test_cache_service.py`
- Test: `tests/test_episode_mapping_projection.py`
- Test: `tests/test_movie_discovery.py`
- Test: `tests/test_scan_improvements.py`

**Interfaces:**
- Removes only uncalled private/legacy wrappers and unconsumed model fields.
- Preserves `QueueController.pending_count`, `QueueController.add_single_job`, all exported cache/guide schema fields, and the live classifier APIs.

- [ ] **Step 1: Establish the focused green baseline**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_queue_controller.py tests\test_scan_progress.py tests\test_cache_service.py tests\test_episode_mapping_projection.py tests\test_movie_discovery.py tests\test_scan_improvements.py -q
```

Expected: all selected tests pass before cleanup.

- [ ] **Step 2: Delete the two obsolete queue-controller methods**

From `plex_renamer/app/controllers/queue_controller.py`, delete exactly these two complete methods:

```python
    def record_completed_job(self, job: RenameJob, result: RenameResult) -> None:
        """Record an already-executed rename as a completed history entry.

        Used by the legacy direct-rename path (execute immediately, then
        record for undo).  The PySide6 shell will use queue→execute
        instead, so this method exists to keep the tkinter shell routed
        through the controller rather than accessing JobStore directly.
        """
        record_completed_queue_job(self.job_store, job, result)

    def get_latest_revertible_job(self) -> RenameJob | None:
        """Return the most recent completed job with stored undo data."""
        return self.job_store.get_latest_completed_with_undo()
```

Use the actual full method boundaries in the file. Do not remove `pending_count`, `add_single_job`, bulk removal, or current revert execution paths.

Also remove `record_completed_queue_job` from the `_queue_history_helpers` import because the deleted method is its only caller. Keep `RenameResult`; the executor completion callback annotation still uses it.

- [ ] **Step 3: Delete the three dead state-model members**

From `plex_renamer/app/models/state_models.py`, delete:

- `ScanProgress.is_active`.
- `CacheLookup.is_fresh`.
- The `ignored` field from `EpisodeGuideRow`.

Do not remove `CacheEntry.last_accessed_at`, `CommandGateResult.eligible_job_count`, `EpisodeGuideSummary.mapped_episodes`, `missing_episodes`, `review_required`, `EpisodeGuideRow.episode_key`, or `source_label`.

- [ ] **Step 4: Remove stale TV discovery locals, imports, and forwarding wrappers**

In `plex_renamer/app/services/_tv_library_classification.py`, delete both writes to the unused local `has_direct_season_subdirs`; leave every returned `ClassifiedDirectory.has_direct_season_subdirs=` value unchanged.

In `plex_renamer/app/services/tv_library_discovery_service.py`:

- Remove `get_season` and `is_extras_folder` from the parsing import.
- Remove now-unused `_DirChild` from the classifier import.
- Delete `_counts_as_season_subdir`.
- Delete `_scan_children`.
- Delete `_child_title_matches_parent`.

Keep `_classify_directory`, `_iter_child_dirs`, `_season_children_are_majority`, and `_canonical_path`.

- [ ] **Step 5: Verify the exact symbols are gone and behavior is green**

Run:

```powershell
rg -n "record_completed_job|get_latest_revertible_job|def is_active|def is_fresh|ignored:|has_direct_season_subdirs =|def _counts_as_season_subdir|def _scan_children|def _child_title_matches_parent" plex_renamer\app
.venv\Scripts\python.exe -m ruff check plex_renamer\app
.venv\Scripts\python.exe -m pytest tests\test_queue_controller.py tests\test_scan_progress.py tests\test_cache_service.py tests\test_episode_mapping_projection.py tests\test_movie_discovery.py tests\test_scan_improvements.py -q
```

Expected: the search has no hits for removed declarations/writes; Ruff exits 0; all selected tests pass.

- [ ] **Step 6: Commit**

```powershell
git add plex_renamer/app/controllers/queue_controller.py plex_renamer/app/models/state_models.py plex_renamer/app/services/_tv_library_classification.py plex_renamer/app/services/tv_library_discovery_service.py
git commit -m "chore(app): remove obsolete controller and discovery surfaces"
```

---

### Task 3: Remove dead engine scanner, orchestrator, assignment, and model APIs

**Findings closed:** 12 non-GUI records.

**Files:**
- Modify: `plex_renamer/engine/_batch_orchestrators.py`
- Modify: `plex_renamer/engine/_tv_scanner.py`
- Modify: `plex_renamer/engine/episode_assignments.py`
- Modify: `plex_renamer/engine/models.py`
- Modify: `tests/test_episode_assignments.py`
- Test: `tests/test_scan_improvements.py`
- Test: `tests/test_tv_scanner_normal.py`
- Test: `tests/test_consolidated_assignments.py`
- Test: `tests/test_batch_autoaccept_guards.py`

**Interfaces:**
- Removes private forwarding wrappers and derived convenience properties with zero consumers.
- Removes the obsolete `ingest_preview_items` adapter and its adapter-only tests; direct `EpisodeAssignmentTable` and production consolidated-table coverage remains.
- Preserves `BatchMovieOrchestrator.discover_movies`, `MovieScanner.explicit_files`, `EpisodeAssignmentTable.unclaimed_slots`, and `ROLE_VERSION`.

- [ ] **Step 1: Establish the focused green baseline**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_scan_improvements.py tests\test_tv_scanner_normal.py tests\test_consolidated_assignments.py tests\test_episode_assignments.py tests\test_batch_autoaccept_guards.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Remove three dead batch-orchestrator members**

From `plex_renamer/engine/_batch_orchestrators.py`, delete:

- `BatchTVOrchestrator._boost_tv_scores_with_episode_evidence` only; keep the live module function and calls from `engine/matching.py`.
- `BatchTVOrchestrator.is_tv_library` and any imports orphaned solely by its body.
- `BatchMovieOrchestrator.rematch_movie`; keep application rematching through `MediaControllerMovieWorkflow.rematch_state`.

- [ ] **Step 3: Remove stale TV scanner imports and methods**

From `plex_renamer/engine/_tv_scanner.py`:

- Remove the unused `build_consolidated_preview` import; keep the same-named live class method.
- Remove the unused `SeasonCompleteness` import; keep its import in `_tv_scanner_postprocess.py`.
- Delete `TVScanner.invalidate_cache`.
- Delete `TVScanner.get_mismatch_info`.

Do not alter `_detect_mismatch`, `ScanState.reset_scan`, or `build_consolidated_table`.

- [ ] **Step 4: Remove the obsolete preview-ingestion adapter and adapter-only tests**

Delete `ingest_preview_items` from `plex_renamer/engine/episode_assignments.py`.

In `tests/test_episode_assignments.py`, remove the two imports shown below and delete the complete `TestIngestion` class, from its `class TestIngestion:` line through the line immediately before the `merge_tables, ROLE_VERSION` import:

```python
from plex_renamer.engine.episode_assignments import ingest_preview_items
from plex_renamer.engine.models import PreviewItem
```

Delete the entire three-test `TestIngestion` class. Do not remove the direct table conflict, unassigned-reason, projection, merge, or `ROLE_VERSION` tests elsewhere in the file; those cover the current production abstraction.

- [ ] **Step 5: Remove four dead model conveniences**

From `plex_renamer/engine/models.py`, delete:

- `PreviewItem.is_move`.
- `ScanState.match_pct`.
- `ScanState.all_skipped`.
- `ScanState.actionable_file_count`.

Keep `PreviewItem.is_actionable`, `ScanState.actionable_indices`, completeness data, and duplicate/actionability calculations at their current call sites.

- [ ] **Step 6: Verify symbols, lint, and behavior**

Run:

```powershell
rg -n "def _boost_tv_scores_with_episode_evidence|def is_tv_library|def rematch_movie|build_consolidated_preview|SeasonCompleteness|def invalidate_cache|def get_mismatch_info|def ingest_preview_items|def is_move|def match_pct|def all_skipped|def actionable_file_count" plex_renamer\engine tests\test_episode_assignments.py
.venv\Scripts\python.exe -m ruff check plex_renamer\engine tests\test_episode_assignments.py
.venv\Scripts\python.exe -m pytest tests\test_scan_improvements.py tests\test_tv_scanner_normal.py tests\test_consolidated_assignments.py tests\test_episode_assignments.py tests\test_batch_autoaccept_guards.py -q
```

Expected: no removed declarations/imports remain; Ruff exits 0; all selected tests pass with the adapter-only test count reduced by three.

- [ ] **Step 7: Commit**

```powershell
git add plex_renamer/engine/_batch_orchestrators.py plex_renamer/engine/_tv_scanner.py plex_renamer/engine/episode_assignments.py plex_renamer/engine/models.py tests/test_episode_assignments.py
git commit -m "chore(engine): remove obsolete scan and model APIs"
```

---

### Task 4: Remove dead JobStore and TMDB transport wrappers

**Findings closed:** 10 non-GUI records.

**Files:**
- Modify: `plex_renamer/job_store.py`
- Modify: `plex_renamer/tmdb.py`
- Modify: `tests/test_tmdb.py`
- Create: `tests/test_tmdb_transport.py`
- Test: `tests/test_queue_controller.py`
- Test: `tests/test_job_store_metadata_plan.py`
- Test: `tests/test_job_execution_metadata.py`

**Interfaces:**
- Removes unused JobStore imports and wrappers while retaining all live bulk queue, ordering, propagation, undo, and persistence paths.
- Removes `TMDBClient._get`; low-level HTTP policy tests move to the owning `TMDBTransport.get_json` API.
- Preserves explicit `TMDBAPIError` and `TMDBRateLimitError` compatibility re-exports from `plex_renamer.tmdb`.

- [ ] **Step 1: Establish the focused green baseline**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_queue_controller.py tests\test_job_store_metadata_plan.py tests\test_job_execution_metadata.py tests\test_tmdb.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Remove nine JobStore findings**

In `plex_renamer/job_store.py`, remove the unused imports `json` and `typing.Any`, then delete exactly:

- `RenameJob.is_terminal`.
- `JobStore._migrate_db`.
- `JobStore.remove_job` (singular only; retain `remove_jobs`).
- `JobStore._compact_positions`.
- `JobStore._rebase_path`.
- `JobStore.get_running`.
- `JobStore.get_queued_tmdb_ids`.

Remove the newly orphaned imports `rebase_path`, `migrate_job_store`, and `compact_positions`. Keep `rewrite_job_paths`, `initialize_job_store`, and the live ordering helpers.

Do not remove `JobStore.reorder_job`, `get_queue`, `get_latest_completed_with_undo`, or the extracted helpers called by live methods.

- [ ] **Step 3: Move transport-policy tests to the transport owner**

Create `tests/test_tmdb_transport.py` with a helper and the three existing `_get` cases retargeted to `get_json`:

```python
"""Direct retry and HTTP-policy tests for TMDBTransport."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from plex_renamer._tmdb_transport import TMDBAPIError, TMDBTransport


def make_transport(*, max_retries: int = 2) -> TMDBTransport:
    return TMDBTransport(
        api_key="dummy-api-key",
        language="en-US",
        api_base="https://api.themoviedb.org/3",
        max_retries=max_retries,
    )


def test_get_json_returns_none_for_404():
    transport = make_transport()
    response = MagicMock(ok=False, status_code=404)
    transport.rate_limiter.acquire = MagicMock()
    transport.session.get = MagicMock(return_value=response)

    assert transport.get_json("/tv/123") is None
    transport.session.get.assert_called_once_with(
        "https://api.themoviedb.org/3/tv/123",
        params={"api_key": "dummy-api-key", "language": "en-US"},
        timeout=10,
    )
    transport.session.close()


def test_get_json_retries_transient_network_failure_then_succeeds():
    transport = make_transport(max_retries=1)
    response = MagicMock(ok=True)
    response.json.return_value = {"id": 123}
    transport.rate_limiter.acquire = MagicMock()
    transport.session.get = MagicMock(
        side_effect=[requests.RequestException("boom"), response],
    )

    with patch("plex_renamer._tmdb_transport.time.sleep") as sleep_mock:
        assert transport.get_json("/tv/123") == {"id": 123}

    assert transport.session.get.call_count == 2
    sleep_mock.assert_called_once_with(1.0)
    transport.session.close()


def test_get_json_raises_api_error_for_non_retryable_client_failure():
    transport = make_transport()
    response = MagicMock(ok=False, status_code=400, text="bad request")
    transport.rate_limiter.acquire = MagicMock()
    transport.session.get = MagicMock(return_value=response)

    with pytest.raises(TMDBAPIError):
        transport.get_json("/tv/123")

    transport.session.close()
```

Remove the corresponding three `TMDBClient._get` tests from `tests/test_tmdb.py`; leave all client metadata, caching, image, and `_get_safe`-mocked behavior tests there.

- [ ] **Step 4: Delete the private client wrapper**

From `plex_renamer/tmdb.py`, delete only:

```python
    def _get(self, path: str, params: dict | None = None) -> dict | None:
        """Make a GET request to the TMDB API with rate limiting and retry."""
        return self._transport.get_json(path, params)
```

Keep `_get_safe`, `TMDBAPIError`, `TMDBRateLimitError`, and the other intentional exception exports.

- [ ] **Step 5: Verify persistence and transport behavior**

Run:

```powershell
.venv\Scripts\python.exe -m ruff check plex_renamer\job_store.py plex_renamer\tmdb.py tests\test_tmdb.py tests\test_tmdb_transport.py
.venv\Scripts\python.exe -m pytest tests\test_queue_controller.py tests\test_job_store_metadata_plan.py tests\test_job_execution_metadata.py tests\test_tmdb.py tests\test_tmdb_transport.py -q
```

Expected: Ruff exits 0 and all selected tests pass.

- [ ] **Step 6: Commit**

```powershell
git add plex_renamer/job_store.py plex_renamer/tmdb.py tests/test_tmdb.py tests/test_tmdb_transport.py
git commit -m "chore(core): remove dead store and TMDB wrappers"
```

---

### Task 5: Remove dead GUI shell, model, delegate, and overwritten initialization surfaces

**Findings closed:** 17 GUI-core/early-widget records.

**Files:**
- Modify: `plex_renamer/gui_qt/app.py`
- Modify: `plex_renamer/gui_qt/main_window.py`
- Modify: `plex_renamer/gui_qt/widgets/_bulk_assign_panel.py`
- Modify: `plex_renamer/gui_qt/widgets/_episode_expansion.py`
- Modify: `plex_renamer/gui_qt/widgets/_episode_table_delegate.py`
- Modify: `plex_renamer/gui_qt/widgets/_episode_table_model.py`
- Modify: `plex_renamer/gui_qt/widgets/_job_list_tab.py`
- Test: `tests/test_qt_main_window.py`
- Test: `tests/test_bulk_assign_panel.py`
- Test: `tests/test_episode_expansion.py`
- Test: `tests/test_episode_table_model.py`
- Test: `tests/test_qt_media_workspace.py`

**Interfaces:**
- Removes bypassed coordinator wrappers, one unused signal, stale getters, and constructor writes overwritten before observation.
- Preserves later test-observed writes to `_claimed_file_by_key`, `_copy_buttons`, and `_header_row`.

- [ ] **Step 1: Establish the GUI-focused green baseline**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_qt_main_window.py tests\test_bulk_assign_panel.py tests\test_episode_expansion.py tests\test_episode_table_model.py tests\test_qt_media_workspace.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Remove the redundant popup-filter attribute write**

In `plex_renamer/gui_qt/app.py`, change:

```python
    popup_filter = PopupDismissFilter(app)
    app.installEventFilter(popup_filter)
    app._popup_filter = popup_filter
```

to:

```python
    popup_filter = PopupDismissFilter(app)
    app.installEventFilter(popup_filter)
```

The parent and blocking `app.exec()` retain the filter lifetime.

- [ ] **Step 3: Delete seven bypassed MainWindow wrappers**

From `plex_renamer/gui_qt/main_window.py`, delete exactly:

- `_restore_tmdb_cache_snapshot`.
- `_refresh_media_workspaces`.
- `_active_media_workspace_for_shortcuts`.
- `_text_input_focused`.
- `_active_workspace`.
- `_capture_active_snapshot`.
- `_save_window_state`.

Keep the coordinator instances and the direct calls from initialization, shortcuts, scan callbacks, tab state, and close preparation.

- [ ] **Step 4: Remove only overwritten early-widget initializations**

In `_bulk_assign_panel.py`, delete the constructor’s empty `_claimed_file_by_key` assignment at the reviewed line near 442. Keep the populated assignment in `show_state()` and all test reads.

In `_episode_expansion.py`, delete:

- The constructor initialization of `_copy_buttons` near line 158; keep `_reset_content()` assigning it before the only observation.
- The constructor `None` initialization of `_header_row` near line 162; keep `_build_ui()` assigning the real layout.

- [ ] **Step 5: Remove the unused delegate signal and model surfaces**

In `_episode_table_delegate.py`, delete only the `expansion_requested = Signal(...)` declaration. Keep all Qt delegate virtuals and persistent-editor behavior.

In `_episode_table_model.py`:

- Remove `_Entry.collapsible` from the dataclass/model entry definition.
- Remove both `collapsible=` constructor arguments near the reviewed lines 632 and 774.
- Delete the `search_text` getter; keep `set_search_text` and `_search_text`.
- Delete the `episode_search` getter; keep `set_episode_search` and `_episode_search`.
- Delete `refresh_checks` and remove the stale `_work_panel.py` comment that names it if the comment remains after the method deletion.

- [ ] **Step 6: Remove the dead list-pane helper**

Delete `_insert_panel_before_detail` from `_job_list_tab.py`. Keep `_finish_list_pane()` and subclass construction paths.

- [ ] **Step 7: Verify GUI behavior**

Run:

```powershell
.venv\Scripts\python.exe -m ruff check plex_renamer\gui_qt\app.py plex_renamer\gui_qt\main_window.py plex_renamer\gui_qt\widgets\_bulk_assign_panel.py plex_renamer\gui_qt\widgets\_episode_expansion.py plex_renamer\gui_qt\widgets\_episode_table_delegate.py plex_renamer\gui_qt\widgets\_episode_table_model.py plex_renamer\gui_qt\widgets\_job_list_tab.py
.venv\Scripts\python.exe -m pytest tests\test_qt_main_window.py tests\test_bulk_assign_panel.py tests\test_episode_expansion.py tests\test_episode_table_model.py tests\test_qt_media_workspace.py -q
```

Expected: Ruff exits 0; all selected tests pass.

- [ ] **Step 8: Commit**

```powershell
git add plex_renamer/gui_qt/app.py plex_renamer/gui_qt/main_window.py plex_renamer/gui_qt/widgets/_bulk_assign_panel.py plex_renamer/gui_qt/widgets/_episode_expansion.py plex_renamer/gui_qt/widgets/_episode_table_delegate.py plex_renamer/gui_qt/widgets/_episode_table_model.py plex_renamer/gui_qt/widgets/_job_list_tab.py plex_renamer/gui_qt/widgets/_work_panel.py
git commit -m "chore(gui): remove bypassed shell and model surfaces"
```

---

### Task 6: Remove orphaned GUI presentation helpers and widget classes

**Findings closed:** 14 GUI records — `ShimmerOverlay`, ten `_media_helpers`, and three dead primitive classes.

**Files:**
- Modify: `plex_renamer/gui_qt/widgets/_image_utils.py`
- Modify: `plex_renamer/gui_qt/widgets/_media_helpers.py`
- Modify: `plex_renamer/gui_qt/widgets/_workspace_widget_primitives.py`
- Modify: imports in any file exposed by Ruff after deletion
- Test: `tests/test_qt_workspace_widgets.py`
- Test: `tests/test_qt_media_workspace.py`
- Test: `tests/test_roster_delegate.py`

**Interfaces:**
- Removes complete zero-consumer classes/functions, including their internal Qt overrides only as part of deleting the enclosing dead class.
- Preserves `MasterCheckBox`, its Qt overrides, `paint_check_indicator`, `paint_mini_progress`, `preview_band_name`, and all imported live formatting helpers.

- [ ] **Step 1: Establish the focused green baseline**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_qt_workspace_widgets.py tests\test_qt_media_workspace.py tests\test_roster_delegate.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Remove the dead shimmer class**

Delete the entire `ShimmerOverlay` class from `_image_utils.py`, including its `paintEvent`. Then remove imports used only by that class, as identified by Ruff. Do not alter other image loading, scaling, or pixmap helpers.

- [ ] **Step 3: Remove ten orphaned media presentation helpers**

Delete these exact top-level functions from `_media_helpers.py`:

```text
file_count_for_state
state_match_summary
roster_signature
match_label
preview_band
preview_heading
preview_target_text
tv_preview_sort_key
companion_summary
make_section_header
```

Keep `preview_band_name` and every other imported/live helper. After deleting the functions, let Ruff identify and remove only imports that became unused.

- [ ] **Step 4: Remove three dead widget classes**

Delete these complete classes from `_workspace_widget_primitives.py`:

```text
ClickableRow
ToggleSwitch
MiniProgressBar
```

This intentionally removes `ToggleSwitch.paintEvent` and `MiniProgressBar.paintEvent` with their dead enclosing classes. Keep `MasterCheckBox.nextCheckState`, `MasterCheckBox.paintEvent`, `paint_check_indicator`, and `paint_mini_progress`.

Run Ruff and remove class-only imports such as `QFrame` or `Signal` only if no live declaration still needs them.

- [ ] **Step 5: Verify imports and widget behavior**

Run:

```powershell
rg -n "class ShimmerOverlay|def file_count_for_state|def state_match_summary|def roster_signature|def match_label|def preview_band\(|def preview_heading|def preview_target_text|def tv_preview_sort_key|def companion_summary|def make_section_header|class ClickableRow|class ToggleSwitch|class MiniProgressBar" plex_renamer\gui_qt\widgets
.venv\Scripts\python.exe -m ruff check plex_renamer\gui_qt\widgets\_image_utils.py plex_renamer\gui_qt\widgets\_media_helpers.py plex_renamer\gui_qt\widgets\_workspace_widget_primitives.py
.venv\Scripts\python.exe -m pytest tests\test_qt_workspace_widgets.py tests\test_qt_media_workspace.py tests\test_roster_delegate.py -q
```

Expected: no removed declaration remains; Ruff exits 0; all selected tests pass.

- [ ] **Step 6: Commit**

```powershell
git add plex_renamer/gui_qt/widgets/_image_utils.py plex_renamer/gui_qt/widgets/_media_helpers.py plex_renamer/gui_qt/widgets/_workspace_widget_primitives.py
git commit -m "chore(gui): remove orphaned presentation helpers"
```

---

### Task 7: Remove dead settings bindings and the write-only poster field lifecycle

**Findings closed:** 23 GUI records — 18 settings attribute bindings and five `_poster_pixmap` writes/declarations across the two review partitions.

**Files:**
- Modify: `plex_renamer/gui_qt/widgets/_settings_automux_page.py`
- Modify: `plex_renamer/gui_qt/widgets/_settings_metadata_page.py`
- Modify: `plex_renamer/gui_qt/widgets/job_detail_panel.py`
- Modify: `plex_renamer/gui_qt/widgets/_job_detail_poster.py`
- Test: `tests/test_settings_tab_automux.py`
- Test: `tests/test_settings_metadata_keys.py`
- Test: `tests/test_qt_job_detail_panel.py`

**Interfaces:**
- Keeps every settings control creation, signal connection, closure capture, and layout insertion; only unnecessary instance names disappear.
- Keeps `_merge_subs_cb`, `_merge_langs_edit`, `_default_audio_edit`, and `_no_fear_cb`, which are intentional test/UI handles.
- Removes `_poster_pixmap` entirely; the owning `QLabel` remains the single source of displayed poster state.

- [ ] **Step 1: Establish the focused green baseline**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_settings_tab_automux.py tests\test_settings_metadata_keys.py tests\test_qt_job_detail_panel.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Remove seven AutoMux instance bindings but preserve calls**

In `_settings_automux_page.py`, rewrite only these assignments as expression calls:

```python
        self._lang_row(
            body, "Default subtitle language", "automux_default_sub_language")
        self._lang_row(
            body, "Language for untagged external subs (empty = und)",
            "automux_untagged_sub_language")
        self._toggle(
            body, "Strip embedded subtitles not in the retain list",
            "automux_strip_subs")
        self._lang_list_row(
            body, "Retained subtitle languages", "automux_retain_sub_languages")
        self._toggle(
            body, "Strip embedded audio not in the retain list",
            "automux_strip_audio")
        self._lang_list_row(
            body, "Retained audio languages", "automux_retain_audio_languages")
        self._toggle(
            body, "Strip track names from remuxed files",
            "automux_strip_track_names")
```

Do not alter the retained assignments to `_merge_subs_cb`, `_merge_langs_edit`, `_default_audio_edit`, or `_no_fear_cb`.

- [ ] **Step 3: Remove eleven metadata instance bindings but preserve calls**

In `_settings_metadata_page.py`, remove only the `self._... =` portion for these controls, preserving the calls and exact arguments:

```text
_nfo_cb
_episode_nfo_cb
_poster_cb
_fanart_cb
_season_posters_cb
_episode_thumbs_cb
_clearlogo_cb
_plex_naming_cb
_embed_title_cb
_embed_cover_cb
_embed_tags_cb
```

The resulting statements remain `self._toggle(body, label, setting_key)` calls in their current order.

- [ ] **Step 4: Remove the complete write-only poster field lifecycle**

In `job_detail_panel.py`, delete:

```python
        self._poster_pixmap: QPixmap | None = None
```

and the two later `self._poster_pixmap = None` assignments from `clear()` and `set_job()`.

In `_job_detail_poster.py`, delete the `_poster_pixmap` field from `_PosterPanel` protocol and delete:

```python
        panel._poster_pixmap = pixmap
```

```python
        panel._poster_pixmap = None
```

Keep every `panel._poster.setPixmap(...)`, `setText(...)`, scaling, and persistence call. Remove `QPixmap` imports only where Ruff proves they became unused; both modules still use `QPixmap()` for visible clearing, so they are expected to remain.

- [ ] **Step 5: Verify settings behavior and poster display**

Run:

```powershell
rg -n "_default_sub_edit|_untagged_sub_edit|_strip_subs_cb|_retain_subs_edit|_strip_audio_cb|_retain_audio_edit|_strip_names_cb|_nfo_cb|_episode_nfo_cb|_poster_cb|_fanart_cb|_season_posters_cb|_episode_thumbs_cb|_clearlogo_cb|_plex_naming_cb|_embed_title_cb|_embed_cover_cb|_embed_tags_cb|_poster_pixmap" plex_renamer\gui_qt\widgets
.venv\Scripts\python.exe -m ruff check plex_renamer\gui_qt\widgets\_settings_automux_page.py plex_renamer\gui_qt\widgets\_settings_metadata_page.py plex_renamer\gui_qt\widgets\job_detail_panel.py plex_renamer\gui_qt\widgets\_job_detail_poster.py
.venv\Scripts\python.exe -m pytest tests\test_settings_tab_automux.py tests\test_settings_metadata_keys.py tests\test_qt_job_detail_panel.py -q
```

Expected: the removed names have no hits; retained test-facing settings handles still exist; Ruff exits 0; all tests pass.

- [ ] **Step 6: Commit**

```powershell
git add plex_renamer/gui_qt/widgets/_settings_automux_page.py plex_renamer/gui_qt/widgets/_settings_metadata_page.py plex_renamer/gui_qt/widgets/job_detail_panel.py plex_renamer/gui_qt/widgets/_job_detail_poster.py
git commit -m "chore(gui): drop dead settings and poster bindings"
```

---

### Task 8: Remove remaining stale GUI wrappers, imports, aliases, and constructor arguments

**Findings closed:** 18 late-widget records, including the duplicated Ruff/Vulture `QPointF` record with one import edit.

**Files:**
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_ui.py`
- Modify: `plex_renamer/gui_qt/widgets/_roster_delegate.py`
- Modify: `plex_renamer/gui_qt/widgets/empty_state.py`
- Modify: `plex_renamer/gui_qt/widgets/media_workspace.py`
- Modify: `plex_renamer/gui_qt/widgets/queue_tab.py`
- Modify: `plex_renamer/gui_qt/_main_window_tabs.py`
- Modify: `plex_renamer/gui_qt/widgets/scan_progress.py`
- Modify: `plex_renamer/gui_qt/widgets/settings_tab.py`
- Modify: `plex_renamer/gui_qt/widgets/tab_badge.py`
- Modify: `plex_renamer/gui_qt/widgets/toast_manager.py`
- Test: `tests/test_roster_delegate.py`
- Test: `tests/test_qt_media_workspace.py`
- Test: `tests/test_queue_tab_remux.py`
- Test: `tests/test_qt_main_window.py`
- Test: `tests/test_scan_progress.py`
- Test: `tests/test_tab_badge.py`
- Test: `tests/test_qt_toasts.py`

**Interfaces:**
- Removes six stale `MediaWorkspace` coordinator forwards plus its unused `splitter` property.
- Removes obsolete `QueueTab.navigate_to_media` and `TabBadge.show_failure_pip` constructor inputs from both definitions and their only callers.
- Preserves `_ToastCard._full_message`; only the uncalled `full_message()` method is removed.

- [ ] **Step 1: Establish the focused green baseline**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_roster_delegate.py tests\test_qt_media_workspace.py tests\test_queue_tab_remux.py tests\test_qt_main_window.py tests\test_scan_progress.py tests\test_tab_badge.py tests\test_qt_toasts.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Remove two simple write-only aliases/bindings**

In `_media_workspace_ui.py`, delete only:

```python
workspace._roster_selection_summary = workspace._roster_panel.selection_summary
```

Keep roster panel construction, ownership, and connections.

In `_roster_delegate.py`, replace the chained assignment:

```python
metrics = painter_metrics = painter.fontMetrics()
```

with:

```python
painter_metrics = painter.fontMetrics()
```

- [ ] **Step 3: Remove unused imports**

- Remove `QSize` and `QSizePolicy` from `empty_state.py`.
- Remove `QPointF` once from `scan_progress.py`; this closes both raw analyzer records.
- Remove `QSize` from `tab_badge.py`.

Keep all Qt drag/drop and paint overrides.

- [ ] **Step 4: Delete seven dead MediaWorkspace surfaces**

From `media_workspace.py`, delete:

- `splitter` property.
- `_preferred_batch_focus_index`.
- `_normalize_queue_selection`.
- `_update_preview_master_state`.
- `_selected_preview`.
- `_folder_plan_text`.
- `_season_expected_count`.

Keep `_splitter` itself and direct coordinator calls. After deleting `_selected_preview` and `_folder_plan_text`, search `MediaWorkspaceViewCoordinator.selected_preview` and `.folder_plan_text`; if each has no remaining consumer, remove those coordinator methods in the same commit and rerun the same tests. This is not optional guesswork: delete only when the post-wrapper `rg` proves zero callers.

- [ ] **Step 5: Remove obsolete QueueTab navigation injection**

In `queue_tab.py`, remove `navigate_to_media` from the constructor signature and remove `self._navigate_to_media = navigate_to_media`.

In `_main_window_tabs.py`, remove the corresponding keyword argument from the sole `QueueTab(...)` construction. Do not remove any other tab navigation behavior.

- [ ] **Step 6: Remove remaining stale wrapper and badge parameter**

Delete `SettingsTab._set_key_status` from `settings_tab.py`; keep all direct `SettingsTabActionsCoordinator.set_key_status` calls.

In `tab_badge.py`, remove `show_failure_pip` from `TabBadge.__init__`. In `_main_window_tabs.py`, remove `show_failure_pip=True` from the queue badge construction. Keep `set_failure_visible`, `failure_visible`, and `count_text`.

- [ ] **Step 7: Remove only the unused toast accessor**

Delete `_ToastCard.full_message()` from `toast_manager.py`. Keep the `_full_message` field, copy-to-clipboard behavior, and `update_message` writes.

- [ ] **Step 8: Verify GUI behavior**

Run:

```powershell
.venv\Scripts\python.exe -m ruff check plex_renamer\gui_qt
.venv\Scripts\python.exe -m pytest tests\test_roster_delegate.py tests\test_qt_media_workspace.py tests\test_queue_tab_remux.py tests\test_qt_main_window.py tests\test_scan_progress.py tests\test_tab_badge.py tests\test_qt_toasts.py -q
```

Expected: Ruff exits 0 and all selected tests pass.

- [ ] **Step 9: Commit**

```powershell
git add plex_renamer/gui_qt/widgets/_media_workspace_ui.py plex_renamer/gui_qt/widgets/_roster_delegate.py plex_renamer/gui_qt/widgets/empty_state.py plex_renamer/gui_qt/widgets/media_workspace.py plex_renamer/gui_qt/widgets/queue_tab.py plex_renamer/gui_qt/_main_window_tabs.py plex_renamer/gui_qt/widgets/scan_progress.py plex_renamer/gui_qt/widgets/settings_tab.py plex_renamer/gui_qt/widgets/tab_badge.py plex_renamer/gui_qt/widgets/toast_manager.py
git commit -m "chore(gui): remove stale widget wrappers and inputs"
```

---

### Task 9: Prove all confirmed findings are remediated and refresh generated audit output

**Findings closed:** verification gate for all 108 records; no new source remediation is introduced here.

**Files:**
- Modify: generated files under `docs/audit/` only through `scripts\audit.cmd`
- Review: `.audit/analysis.json`
- Review: `docs/audit/maps/overview.md`
- Review: `docs/audit/findings-review.md` and all three detailed review files

**Interfaces:**
- Produces a fresh audit artifact whose residual dead-code findings are explainable by the 95 reviewed false positives or by new findings requiring separate triage.
- Produces zero `engine -> app` layer violations.
- Does not edit generated checklist markers by hand.

- [ ] **Step 1: Run the complete automated test sweep**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\audit -q
scripts\test-fast.cmd
scripts\test-smoke.cmd
```

Expected: every command exits 0. Test counts may be lower only by the three deliberately deleted `TestIngestion` adapter tests; all other count changes must be explained before continuing.

- [ ] **Step 2: Run lint and regenerate the audit**

Run:

```powershell
.venv\Scripts\python.exe -m ruff check plex_renamer tests scripts
scripts\audit.cmd
```

Expected: Ruff exits 0; the audit completes successfully; the layer-contract section reports no violations.

- [ ] **Step 3: Reconcile the fresh audit against the curated verdicts**

Check all of the following:

```powershell
rg -n "forbidden import.*plex_renamer\.app|engine.*imports plex_renamer\.app" docs\audit .audit
rg -n "_poster_pixmap|_movie_discovery|ingest_preview_items|show_failure_pip|_roster_selection_summary" plex_renamer tests scripts
git diff -- docs\audit
```

Expected:

- The first search prints nothing.
- The second search prints nothing except historical prose in curated review documents if those documents are included in a broader manual search.
- The generated diff reflects source cleanup and refreshed counts only; curated review files remain intact.
- Every old `CONFIRMED` row maps to Tasks 1–8 below. Any newly emitted dead-code record is manually inspected rather than automatically deleted.

- [ ] **Step 4: Confirm traceability totals**

Use this accounting table during review:

| Task | Non-GUI | GUI core/early | Late widgets | Total |
|---|---:|---:|---:|---:|
| 1. Dependency direction + movie discovery state | 3 | 0 | 0 | 3 |
| 2. Application/controller/service cleanup | 11 | 0 | 0 | 11 |
| 3. Engine scanner/model cleanup | 12 | 0 | 0 | 12 |
| 4. JobStore/TMDB cleanup | 10 | 0 | 0 | 10 |
| 5. GUI shell/model cleanup | 0 | 17 | 0 | 17 |
| 6. Orphaned GUI helpers/classes | 0 | 11 | 3 | 14 |
| 7. Settings bindings + poster lifecycle | 0 | 2 | 21 | 23 |
| 8. Remaining late-widget cleanup | 0 | 0 | 18 | 18 |
| **Total** | **36** | **30** | **42** | **108** |

The partition split in Tasks 6 and 7 matters only for raw-record accounting; each implementation edit remains grouped by source ownership.

- [ ] **Step 5: Commit refreshed audit artifacts**

```powershell
git add docs/audit
git commit -m "chore(audit): refresh findings after confirmed cleanup"
```

- [ ] **Step 6: Final whole-branch verification**

Run once more after the generated-output commit:

```powershell
git status --short
.venv\Scripts\python.exe -m pytest tests\audit -q
scripts\test-fast.cmd
scripts\test-smoke.cmd
```

Expected: only intentionally untracked local files, if any, appear in status; all three verification commands exit 0.

Then use `superpowers:requesting-code-review` followed by `superpowers:finishing-a-development-branch`.

---

## Self-Review Notes

- **Spec coverage:** All 108 confirmed records are assigned once through the 36/30/42 partition totals. The two architecture findings are resolved by injection, and duplicate/write-level records are grouped without losing count.
- **False-positive safety:** Every cross-cutting caution in the review is represented as a global constraint or a task-local “keep” instruction. The plan never proposes broad symbol suppression or blanket deletion.
- **Type consistency:** `TVLibraryDiscoverer` and `MovieLibraryDiscoverer` are the only new ports. The concrete application services satisfy them structurally; the engine never imports application model types.
- **No generated-file hand editing:** Audit output is refreshed only with `scripts\audit.cmd`; curated review prose remains outside generated markers.
- **No placeholders:** Each task lists exact files, exact symbols, focused commands, expected results, and a commit boundary. The one conditional transitive deletion in Task 8 is guarded by an exact zero-caller search because the detailed review explicitly calls for reassessing those coordinator methods after wrapper removal.
