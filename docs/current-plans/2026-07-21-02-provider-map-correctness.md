# Provider-Map Correctness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent unavailable or malformed provider season maps from being treated as valid empty shows.

**Architecture:** Keep the existing `(seasons, total)` success interface so fakes and matching consumers remain stable. Add a provider-neutral `SeasonMapUnavailableError`; use strict transport calls while building season maps and raise that error for transport/API/unavailable-details failures. Validate map shape at the scanner boundary, surface a `scan_error`, and block approval/queue paths.

**Tech Stack:** Python 3.14, TMDB/TVDB transports, dataclasses/protocols, pytest.

## Global Constraints

- Implement only `MATCH-002`; do not add provider selection, translation, or metadata features.
- A valid provider response with zero seasons remains `({}, 0)` and is not an error.
- Provider failures and malformed maps must not auto-approve or queue a show.
- Use typed exceptions rather than sentinel strings or broad `except Exception` at the provider boundary.
- Do not accept new/enlarged audit debt.

---

### Task 1: Define and test the provider-neutral failure contract

**Files:**
- Modify: `plex_renamer/providers.py`
- Test: `tests/test_provider_season_map_failures.py`

**Interfaces:**
- Produces: `class SeasonMapUnavailableError(RuntimeError)`
- Preserves: `MetadataProvider.get_season_map(show_id) -> tuple[dict[int, dict[str, Any]], int]`

- [ ] **Step 1: Create strict tests for valid empty versus unavailable**

```python
from plex_renamer.providers import SeasonMapUnavailableError


def test_valid_empty_map_is_a_success(empty_provider) -> None:
    assert empty_provider.get_season_map(7) == ({}, 0)


def test_unavailable_map_raises_typed_error(failing_provider) -> None:
    with pytest.raises(SeasonMapUnavailableError, match="tmdb season map unavailable for 7"):
        failing_provider.get_season_map(7)
```

Use tiny local provider fakes for the protocol-level test; transport-specific tests are added in Task 2.

- [ ] **Step 2: Run the new test and confirm RED**

Run: `.venv\Scripts\python.exe -m pytest tests\test_provider_season_map_failures.py -q`
Expected: collection FAIL because `SeasonMapUnavailableError` does not exist.

- [ ] **Step 3: Add the exception next to `MetadataProvider`**

```python
class SeasonMapUnavailableError(RuntimeError):
    """Provider could not return a trustworthy season map for a known show."""
```

- [ ] **Step 4: Run the protocol test**

Run: `.venv\Scripts\python.exe -m pytest tests\test_provider_season_map_failures.py -q`
Expected: PASS for the test fakes.

- [ ] **Step 5: Commit**

```powershell
git add plex_renamer/providers.py tests/test_provider_season_map_failures.py
git commit -m "engine: define season map failure contract"
```

### Task 2: Make TMDB and TVDB season-map fetches strict

**Files:**
- Modify: `plex_renamer/tmdb.py:199-236`
- Modify: `plex_renamer/tvdb.py:267-341`
- Test: `tests/test_provider_season_map_failures.py`

**Interfaces:**
- Consumes: `TMDBTransport.get_json` and `TVDBTransport.get_json`, which raise the shared `TMDBError` family and return `None` only for 404.
- Produces: provider errors wrapped as `SeasonMapUnavailableError` with provider/show context.

- [ ] **Step 1: Add failing transport fixtures**

```python
class _FailingTransport:
    def get_json(self, path: str, params: dict[str, object] | None = None) -> dict | None:
        raise TMDBNetworkError("offline")


def test_tmdb_season_map_wraps_transport_failure() -> None:
    client = TMDBClient("key")
    client._transport = _FailingTransport()
    with pytest.raises(SeasonMapUnavailableError, match="tmdb season map unavailable"):
        client.get_season_map(7)


def test_tvdb_season_map_wraps_transport_failure() -> None:
    client = TVDBClient("key", transport=_FailingTransport())
    with pytest.raises(SeasonMapUnavailableError, match="tvdb season map unavailable"):
        client.get_season_map(7)
```

- [ ] **Step 2: Run the provider tests and confirm RED**

Run: `.venv\Scripts\python.exe -m pytest tests\test_provider_season_map_failures.py -q`
Expected: FAIL because both clients currently call safe transports and return `({}, 0)`.

- [ ] **Step 3: Add strict private detail/episode reads used only by season maps**

```python
def _get_tv_details_strict(self, show_id: int) -> dict:
    try:
        data = self._transport.get_json(f"/tv/{show_id}", self._details_params())
    except TMDBError as exc:
        raise SeasonMapUnavailableError(
            f"tmdb season map unavailable for {show_id}: {exc}"
        ) from exc
    if data is None:
        raise SeasonMapUnavailableError(f"tmdb season map unavailable for {show_id}: not found")
    return data
```

Add the analogous TVDB strict detail and paginated-episode helpers. Existing safe search/details methods remain unchanged. Cache only successful maps, including valid empty maps produced from a non-empty details payload whose season/episode list is empty.

- [ ] **Step 4: Run provider and transport regression suites**

Run: `.venv\Scripts\python.exe -m pytest tests\test_provider_season_map_failures.py tests\test_tmdb.py tests\test_tvdb.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add plex_renamer/tmdb.py plex_renamer/tvdb.py tests/test_provider_season_map_failures.py
git commit -m "fix: distinguish provider map failures"
```

### Task 3: Validate maps and surface actionable scan errors

**Files:**
- Modify: `plex_renamer/engine/_tv_scanner.py:110-118`
- Modify: `plex_renamer/engine/_batch_orchestrators.py:840-945`
- Test: `tests/test_provider_season_map_failures.py`
- Test: `tests/test_batch_autoaccept_guards.py`

**Interfaces:**
- Produces: `validate_season_map(value: object) -> dict[int, dict[str, Any]]`
- Uses: `ScanState.scan_error: str | None` and existing failed-scan queue gates.

- [ ] **Step 1: Add failing malformed/failure/empty scanner tests**

```python
@pytest.mark.parametrize("payload", [(None, 0), ({1: []}, 0), ({"bad": {}}, 0)])
def test_scanner_rejects_malformed_season_maps(tmp_path: Path, payload: object) -> None:
    scanner = _scanner(tmp_path, provider=_ProviderReturning(payload))
    with pytest.raises(SeasonMapUnavailableError, match="malformed season map"):
        scanner.scan()


def test_batch_failure_sets_scan_error_and_cannot_queue(tmp_path: Path) -> None:
    state = _scan_with_provider(tmp_path, _ProviderRaising())
    assert state.scan_error == "Episode guide is unavailable; retry the provider scan."
    assert state.checked is False
    assert state.queueable is False
```

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `.venv\Scripts\python.exe -m pytest tests\test_provider_season_map_failures.py tests\test_batch_autoaccept_guards.py -q`
Expected: FAIL because map shape is unchecked and the typed failure is not converted to state error.

- [ ] **Step 3: Validate the tuple and catch only the typed error at orchestration**

```python
def _normalize_season_map(value: object) -> dict[int, dict[str, Any]]:
    if not isinstance(value, dict):
        raise SeasonMapUnavailableError("malformed season map: expected mapping")
    normalized: dict[int, dict[str, Any]] = {}
    for raw_season, payload in value.items():
        if not isinstance(raw_season, int) or not isinstance(payload, dict):
            raise SeasonMapUnavailableError("malformed season map entry")
        normalized[raw_season] = payload
    return normalized
```

At the batch scan boundary, catch `SeasonMapUnavailableError`, clear previews/checked state, and set the actionable `scan_error`; do not fabricate an empty preview as success.

- [ ] **Step 4: Run scan, matching, and queue-gating suites**

Run: `.venv\Scripts\python.exe -m pytest tests\test_provider_season_map_failures.py tests\test_batch_autoaccept_guards.py tests\test_scan_improvements.py tests\test_queue_submission_automux.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add plex_renamer/engine/_tv_scanner.py plex_renamer/engine/_batch_orchestrators.py tests/test_provider_season_map_failures.py tests/test_batch_autoaccept_guards.py
git commit -m "fix: block scans with unusable episode maps"
```

### Task 4: Close `MATCH-002`

**Files:**
- Modify: `docs/deferred-work.md`

- [ ] **Step 1: Remove the completed entry and update the P1 summary**

Delete `MATCH-002` from the active section and summary; do not retain a completed plan checkbox.

- [ ] **Step 2: Run scoped quality commands**

Run: `.venv\Scripts\ruff.exe format plex_renamer\providers.py plex_renamer\tmdb.py plex_renamer\tvdb.py plex_renamer\engine\_tv_scanner.py plex_renamer\engine\_batch_orchestrators.py tests\test_provider_season_map_failures.py && .venv\Scripts\ruff.exe check plex_renamer\providers.py plex_renamer\tmdb.py plex_renamer\tvdb.py plex_renamer\engine\_tv_scanner.py plex_renamer\engine\_batch_orchestrators.py tests\test_provider_season_map_failures.py && .venv\Scripts\pyright.exe plex_renamer\providers.py plex_renamer\tmdb.py plex_renamer\tvdb.py plex_renamer\engine\_tv_scanner.py plex_renamer\engine\_batch_orchestrators.py tests\test_provider_season_map_failures.py`
Expected: all commands exit 0 and no blanket ignore is introduced.

- [ ] **Step 3: Commit**

```powershell
git add docs/deferred-work.md
git commit -m "docs: close provider map correctness debt"
```
