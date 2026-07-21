# GUI Workspace Test Typing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the Pyright clusters in the shared Qt harness, workspace tests, and review-action tests without restructuring the current GUI.

**Architecture:** Type shared Qt test helpers and the dynamic widget surfaces that the UI coordinator installs. Use explicit `isinstance`/`assert is not None` narrowing for Qt role data and optional child widgets. Type fakes against real controller/provider method shapes. Avoid casts to `Any` and avoid suppressing private access.

**Tech Stack:** Python 3.14, PySide6, Protocol/ClassVar/TypeVar, Pyright, pytest/unittest.

## Global Constraints

- Execute after the GUI reassign contract so its helpers are typed once.
- Do not refactor `MediaWorkspaceActionCoordinator` or alter layout/copy.
- Do not add file-level Pyright disables or `cast(Any, ...)`.
- Preserve Qt smoke stability and explicit widget disposal.
- Split commits at shared harness, production annotations, and each test module.

---

### Task 1: Type the shared Qt harness and role-data helpers

**Files:**
- Modify: `tests/conftest_qt.py`
- Test: `tests/test_qt_workspace_widgets.py`

**Interfaces:**
- Produces: `required(value: T | None, label: str) -> T`
- Produces typed return values for roster/episode/card helper methods.

- [ ] **Step 1: Add a generic narrowing helper and typed app state**

```python
from typing import ClassVar, TypeVar

from PySide6.QtWidgets import QApplication, QWidget

T = TypeVar("T")


def required(value: T | None, label: str) -> T:
    if value is None:
        raise AssertionError(f"required Qt value missing: {label}")
    return value


class QtSmokeBase(unittest.TestCase):
    _app: ClassVar[QApplication]
```

Annotate `setUpClass`, `tearDownClass`, `setUp`, `_dispose_top_level_widgets`, and helper parameters/returns using `MediaWorkspace`, `RosterRowData`, `EpisodeRowData`, and `EpisodeExpansionCard` under `TYPE_CHECKING` imports.

- [ ] **Step 2: Run Pyright and shared widget tests**

Run: `.venv\Scripts\pyright.exe tests\conftest_qt.py`
Expected: 0 errors.

Run: `.venv\Scripts\python.exe -m pytest tests\test_qt_workspace_widgets.py -q`
Expected: PASS.

- [ ] **Step 3: Commit**

```powershell
git add tests/conftest_qt.py
git commit -m "types: annotate shared Qt test harness"
```

### Task 2: Declare coordinator-installed workspace widget surfaces

**Files:**
- Modify: `plex_renamer/gui_qt/widgets/media_workspace.py:12-55`
- Read: `plex_renamer/gui_qt/widgets/_media_workspace_ui.py`
- Test: `tests/test_qt_media_workspace.py`

**Interfaces:**
- Produces class annotations for coordinator-installed `_work_panel`, `_roster_panel`, `_queue_inline_btn`, `_fix_match_btn`, `_roster_queue_btn`, and `_roster_master_check`.

- [ ] **Step 1: Add type-only imports and exact class attributes**

```python
if TYPE_CHECKING:
    from PySide6.QtWidgets import QCheckBox, QPushButton, QSplitter, QStackedWidget
    from ._media_workspace_roster import MediaWorkspaceRosterPanel
    from ._work_panel import MediaWorkPanel
    from .empty_state import EmptyStateWidget
    from .scan_progress import ScanProgressWidget


class MediaWorkspace(QWidget):
    _stack: QStackedWidget
    _empty_state: EmptyStateWidget
    _scan_progress: ScanProgressWidget
    _splitter: QSplitter
    _work_panel: MediaWorkPanel
    _roster_panel: MediaWorkspaceRosterPanel
    _roster_master_check: QCheckBox
    _roster_queue_btn: QPushButton
    _queue_inline_btn: QPushButton
    _fix_match_btn: QPushButton
```

These are the complete attributes installed by `MediaWorkspaceUiCoordinator`; do not initialize them to `None` because construction establishes them before public use.

- [ ] **Step 2: Run Pyright against production and note the reduced test count**

Run: `.venv\Scripts\pyright.exe plex_renamer\gui_qt\widgets\media_workspace.py tests\test_qt_media_workspace.py`
Expected: production file 0 errors and the test's attribute-access cluster materially reduced.

- [ ] **Step 3: Run workspace tests and commit**

Run: `.venv\Scripts\python.exe -m pytest tests\test_qt_media_workspace.py -q`
Expected: PASS.

```powershell
git add plex_renamer/gui_qt/widgets/media_workspace.py
git commit -m "types: declare media workspace widget surface"
```

### Task 3: Narrow workspace model and optional values

**Files:**
- Modify: `tests/test_qt_media_workspace.py`

- [ ] **Step 1: Replace implicit optional access with discriminating assertions**

Use `required(...)` or explicit assertions before every `file_id`, selected state, section key, `findChild`, and role-data access:

```python
state = workspace._selected_state()
self.assertIsNotNone(state)
assert state is not None

file_id = preview.file_id
self.assertIsNotNone(file_id)
assert file_id is not None
assignment = state.assignment_table.assignment_for(file_id)

section_key = self._first_section_key(workspace, prefix="episodes:")
self.assertIsInstance(section_key, str)
assert isinstance(section_key, str)
workspace._on_table_section_toggled(section_key)
```

For Qt role data, assert the concrete `EpisodeRowData`/`RosterRowData` type before reading fields. Do not cast unknown role payloads without a runtime assertion.

- [ ] **Step 2: Run Pyright to zero for the file**

Run: `.venv\Scripts\pyright.exe tests\test_qt_media_workspace.py`
Expected: 0 errors.

- [ ] **Step 3: Run the full workspace module**

Run: `.venv\Scripts\python.exe -m pytest tests\test_qt_media_workspace.py -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```powershell
git add tests/test_qt_media_workspace.py
git commit -m "types: narrow media workspace test state"
```

### Task 4: Type review-action fakes and close both test clusters

**Files:**
- Modify: `tests/test_qt_media_workspace_review_actions.py`
- Modify prune-only: `scripts/audit/quality-baseline.json`

- [ ] **Step 1: Give fakes exact provider/controller signatures**

```python
from typing import Any

class _FakeProviderClient:
    def search_tv(self, query: str, year: str | None = None) -> list[dict[str, Any]]:
        return []

class _FakeSwitchMediaController(_FakeMediaController):
    scan_show_calls: list[tuple[ScanState, object]]
    rematch_calls: list[tuple[ScanState, dict[str, Any], object]]

    def scan_show(self, state: ScanState, tmdb: object) -> None:
        self.scan_show_calls.append((state, tmdb))

    def rematch_tv_state(
        self, state: ScanState, chosen: dict[str, Any], tmdb: object
    ) -> ScanState:
        self.rematch_calls.append((state, chosen, tmdb))
        return state
```

`Any` is allowed only inside provider payload mappings whose schema is genuinely external; do not use it for controller or widget objects.

- [ ] **Step 2: Replace direct protected calls with live public actions**

Where a test currently invokes `_fix_match`, `_apply_alternate_match`, `_on_source_selected`, or `_prompt_assign_season`, trigger the corresponding button/signal/public action already used by the workspace. This removes private-usage findings and strengthens behavior coverage.

- [ ] **Step 3: Reach zero errors and run both modules**

Run: `.venv\Scripts\pyright.exe tests\test_qt_media_workspace.py tests\test_qt_media_workspace_review_actions.py`
Expected: 0 errors.

Run: `.venv\Scripts\python.exe -m pytest tests\test_qt_media_workspace.py tests\test_qt_media_workspace_review_actions.py -q`
Expected: PASS.

- [ ] **Step 4: Prune baseline and commit**

Run: `scripts\audit.cmd --update-quality-baseline`
Expected: prune-only exit 0; both files' Pyright findings are removed.

```powershell
git add tests/test_qt_media_workspace.py tests/test_qt_media_workspace_review_actions.py scripts/audit/quality-baseline.json
git commit -m "types: clear workspace Qt test debt"
```
