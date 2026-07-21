# Queue Async Test Typing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the 152 Pyright findings in `test_qt_queue_submission_async.py` by replacing ad-hoc untyped nested fakes with reusable typed ports.

**Architecture:** Define module-level fake controllers implementing only the production queue submission signatures, typed deferred-work callbacks, and a warning-box protocol. Reuse builders across tests so exception/success variants override one method rather than redefining untyped nested classes.

**Tech Stack:** Python 3.14, Protocol/Callable, PySide6, Pyright, pytest.

## Global Constraints

- Preserve asynchronous worker/overlay behavior and test timing.
- Do not replace test doubles with `MagicMock` or `Any` containers.
- No new suppressions or production behavior changes.
- Finish the target file at zero Pyright findings.

---

### Task 1: Inventory real queue signatures and create typed fakes

**Files:**
- Modify: `tests/test_qt_queue_submission_async.py`
- Read: `plex_renamer/app/controllers/queue_controller.py`
- Read: `plex_renamer/gui_qt/widgets/_media_workspace_queue_actions.py`

**Interfaces:**
- Produces: `_FakeQueueController.add_tv_batch(...) -> BatchQueueResult`
- Produces: `_FakeQueueController.add_movie_batch(...) -> BatchQueueResult`
- Produces: `_DeferredSubmitter.__call__(fn: Callable[[], None]) -> None`

- [ ] **Step 1: Record the starting rule counts**

Run: `.venv\Scripts\pyright.exe tests\test_qt_queue_submission_async.py`
Expected: 152 errors dominated by missing/unknown parameter types.

- [ ] **Step 2: Move repeated nested fakes to typed module-level classes**

```python
SubmitWork = Callable[[], None]

class _DeferredSubmitter:
    def __init__(self) -> None:
        self.pending: list[SubmitWork] = []

    def __call__(self, work: SubmitWork) -> None:
        self.pending.append(work)

    def run_next(self) -> None:
        self.pending.pop(0)()


class _FakeWarningBox:
    calls: list[tuple[str, str]] = []

    @classmethod
    def warning(cls, parent: QWidget, title: str, text: str) -> None:
        cls.calls.append((title, text))


class _FakeQueueController:
    called: bool

    def __init__(self) -> None:
        self.called = False

    def add_tv_batch(
        self,
        states: list[ScanState],
        library_root: Path,
        output_root: Path,
        command_gating: CommandGatingService,
        settings_service: SettingsService | None = None,
        tmdb_client: object | None = None,
        provider_for_state: Callable[[ScanState], object] | None = None,
        progress: Callable[[str, int, int], None] | None = None,
    ) -> BatchQueueResult:
        del library_root, output_root, command_gating, settings_service, tmdb_client
        del provider_for_state
        self.called = True
        if progress is not None and states:
            progress(states[0].display_name, 1, len(states))
        for state in states:
            state.queued = True
        return BatchQueueResult(added=len(states))

    def add_movie_batch(
        self,
        states: list[ScanState],
        library_root: Path,
        output_root: Path,
        command_gating: CommandGatingService,
        settings_service: SettingsService | None = None,
        tmdb_client: object | None = None,
        progress: Callable[[str, int, int], None] | None = None,
    ) -> BatchQueueResult:
        del library_root, output_root, command_gating, settings_service, tmdb_client
        self.called = True
        if progress is not None and states:
            progress(states[0].display_name, 1, len(states))
        for state in states:
            state.queued = True
        return BatchQueueResult(added=len(states))
```

Use these parameter names and positions because they match `QueueController`; the narrower `object` provider values are intentional test ports and avoid importing concrete network clients.

- [ ] **Step 3: Run Pyright and the module**

Run: `.venv\Scripts\pyright.exe tests\test_qt_queue_submission_async.py`
Expected: missing-parameter findings are removed; remaining errors are narrowed to test state/Qt optionals.

Run: `.venv\Scripts\python.exe -m pytest tests\test_qt_queue_submission_async.py -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```powershell
git add tests/test_qt_queue_submission_async.py
git commit -m "types: consolidate async queue test fakes"
```

### Task 2: Type workspace builders, callbacks, and failure variants

**Files:**
- Modify: `tests/test_qt_queue_submission_async.py`

- [ ] **Step 1: Annotate the workspace builder with real controller types or protocols**

```python
class _MediaControllerPort(Protocol):
    batch_states: list[ScanState]
    movie_library_states: list[ScanState]

class _QueueControllerPort(Protocol):
    def add_tv_batch(
        self,
        states: list[ScanState],
        library_root: Path,
        output_root: Path,
        command_gating: CommandGatingService,
        settings_service: SettingsService | None = None,
        tmdb_client: object | None = None,
        provider_for_state: Callable[[ScanState], object] | None = None,
        progress: Callable[[str, int, int], None] | None = None,
    ) -> BatchQueueResult:
        raise NotImplementedError

    def add_movie_batch(
        self,
        states: list[ScanState],
        library_root: Path,
        output_root: Path,
        command_gating: CommandGatingService,
        settings_service: SettingsService | None = None,
        tmdb_client: object | None = None,
        progress: Callable[[str, int, int], None] | None = None,
    ) -> BatchQueueResult:
        raise NotImplementedError

def _build_tv_workspace(
    self,
    tmp: str,
    media_ctrl: _MediaControllerPort,
    queue_ctrl: _QueueControllerPort,
) -> MediaWorkspace:
    settings = SettingsService(path=Path(tmp) / "settings.json")
    output = Path(tmp) / "tv-output"
    output.mkdir()
    settings.tv_output_folder = str(output)
    workspace = MediaWorkspace(
        media_type="tv",
        media_controller=media_ctrl,
        queue_controller=queue_ctrl,
        settings_service=settings,
    )
    workspace.resize(1200, 700)
    workspace.show()
    workspace.show_ready()
    self._app.processEvents()
    return workspace
```

- [ ] **Step 2: Replace nested exploding controllers with subclasses**

```python
class _ExplodingQueueController(_FakeQueueController):
    def add_movie_batch(
        self,
        states: list[ScanState],
        library_root: Path,
        output_root: Path,
        command_gating: CommandGatingService,
        settings_service: SettingsService | None = None,
        tmdb_client: object | None = None,
        progress: Callable[[str, int, int], None] | None = None,
    ) -> BatchQueueResult:
        del states, library_root, output_root, command_gating, settings_service
        del tmdb_client, progress
        self.called = True
        raise RuntimeError("queue failed")
```

- [ ] **Step 3: Narrow every optional Qt/state value**

Assert overlays, selected states, buttons, and callback payloads are non-`None` before access. Give lambdas named typed functions when Pyright cannot infer signal callback parameters.

- [ ] **Step 4: Reach zero and commit**

Run: `.venv\Scripts\pyright.exe tests\test_qt_queue_submission_async.py`
Expected: 0 errors.

Run: `.venv\Scripts\python.exe -m pytest tests\test_qt_queue_submission_async.py -q`
Expected: PASS.

```powershell
git add tests/test_qt_queue_submission_async.py
git commit -m "types: clear async queue test unknowns"
```

### Task 3: Run queue regressions and prune baseline

**Files:**
- Modify prune-only: `scripts/audit/quality-baseline.json`

- [ ] **Step 1: Run queue and workspace regressions**

Run: `.venv\Scripts\python.exe -m pytest tests\test_qt_queue_submission_async.py tests\test_queue_submission_automux.py tests\test_queue_controller.py tests\test_qt_media_workspace.py -q`
Expected: PASS.

- [ ] **Step 2: Format/check and prune**

Run: `.venv\Scripts\ruff.exe format tests\test_qt_queue_submission_async.py && .venv\Scripts\ruff.exe check tests\test_qt_queue_submission_async.py`
Expected: exit 0.

Run: `scripts\audit.cmd --update-quality-baseline`
Expected: prune-only exit 0; 152 Pyright findings and the legacy file entry are removed.

- [ ] **Step 3: Commit**

```powershell
git add tests/test_qt_queue_submission_async.py scripts/audit/quality-baseline.json
git commit -m "types: enroll async queue tests at strict"
```
