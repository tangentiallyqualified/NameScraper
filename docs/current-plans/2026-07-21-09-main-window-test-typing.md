# Main Window Test Typing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the 157 Pyright findings in `test_qt_main_window.py` by declaring coordinator-installed facade attributes and narrowing optional widgets.

**Architecture:** Add type-only class annotations to `MainWindow` and `SettingsTab` for services/widgets installed during construction. Tests continue using the existing facade, with runtime assertions for optional lookups. This is a typing declaration pass, not a GUI refactor before V5.

**Tech Stack:** Python 3.14, PySide6, TYPE_CHECKING, Pyright, unittest.

## Global Constraints

- Do not move coordinator responsibilities or alter GUI behavior/layout.
- Declare only attributes actually assigned by bootstrap/tab/settings coordinators.
- No `cast(Any, window)` and no file-level suppressions.
- Run the full main-window module after each production annotation group.

---

### Task 1: Declare bootstrap and tab surfaces on `MainWindow`

**Files:**
- Modify: `plex_renamer/gui_qt/main_window.py:15-58`
- Read: `plex_renamer/gui_qt/_main_window_bootstrap.py`
- Read: `plex_renamer/gui_qt/_main_window_tabs.py`
- Test: `tests/test_qt_main_window.py`

**Interfaces:**
- Declares: `media_ctrl`, `queue_ctrl`, `settings_service`, `_cache_service`, `_tv_workspace`, `_movie_workspace`, `_tabs`, `_toast_manager`, queue/history widgets.

- [ ] **Step 1: Add type-only imports and exact annotations**

```python
if TYPE_CHECKING:
    from PySide6.QtCore import QObject
    from PySide6.QtWidgets import QTabWidget
    from .widgets.history_tab import HistoryTab
    from .widgets.media_workspace import MediaWorkspace
    from .widgets.queue_tab import QueueTab
    from .widgets.settings_tab import SettingsTab
    from .widgets.tab_badge import TabBadge

class MainWindow(QMainWindow):
    media_ctrl: MediaController
    queue_ctrl: QueueController
    settings_service: SettingsService
    _job_store: JobStore
    _command_gating: CommandGatingService
    _refresh_policy: RefreshPolicyService
    _cache_service: PersistentCacheService
    _bridge: QObject
    _queue_bridge: QObject
    _tv_workspace: MediaWorkspace
    _movie_workspace: MediaWorkspace
    _tabs: QTabWidget
    _queue_tab: QueueTab
    _history_tab: HistoryTab
    _settings_tab: SettingsTab
    _queue_badge: TabBadge
    _history_badge: TabBadge
    _toast_manager: ToastManager
```

Also declare the bootstrap feedback fields: `_queue_run_started`, `_queue_run_is_background`, `_job_poster_backfill_started`, `_tv_needs_queue_refresh`, and `_movie_needs_queue_refresh` as `bool`; `_queue_completed_count`, `_queue_failed_count`, `_pending_success_jobs`, and `_pending_success_files` as `int`; `_scan_feedback_token` as `object | None`; and `_success_toast_timer` as `QTimer`. Do not initialize attributes twice.

- [ ] **Step 2: Run Pyright and main-window tests**

Run: `.venv\Scripts\pyright.exe plex_renamer\gui_qt\main_window.py tests\test_qt_main_window.py`
Expected: the 37 `media_ctrl`, 25 workspace, and 18 toast-manager attribute findings disappear.

Run: `.venv\Scripts\python.exe -m pytest tests\test_qt_main_window.py -q`
Expected: PASS.

- [ ] **Step 3: Commit**

```powershell
git add plex_renamer/gui_qt/main_window.py
git commit -m "types: declare main window coordinator surface"
```

### Task 2: Declare settings-tab coordinator surfaces

**Files:**
- Modify: `plex_renamer/gui_qt/widgets/settings_tab.py`
- Read: `plex_renamer/gui_qt/widgets/_settings_tab_sections.py`
- Read: `plex_renamer/gui_qt/widgets/_settings_tab_state.py`
- Test: `tests/test_qt_main_window.py`

- [ ] **Step 1: Add exact widget annotations**

```python
class SettingsTab(QScrollArea):
    _destinations_page: SettingsSectionCard
    _destinations_status: QLabel
    _key_status: QLabel
    _cache_stats: QLabel
    _history_confirm: QLabel
    _cache_confirm: QLabel
    _threshold_label: QLabel
    _episode_threshold_label: QLabel
    _save_destinations_btn: QPushButton
    _save_key_btn: QPushButton
    _test_key_btn: QPushButton
    _clear_history_btn: QPushButton
    _clear_cache_btn: QPushButton
    _clear_all_btn: QPushButton
    _export_log_btn: QPushButton
    _view_mode_combo: QComboBox
    _lang_combo: QComboBox
    _tv_source_combo: QComboBox
    _cache_size_combo: QComboBox
    _log_combo: QComboBox
    _companion_cb: QCheckBox
    _discovery_cb: QCheckBox
    _confidence_cb: QCheckBox
    _fallback_cb: QCheckBox
    _id_tag_routing_cb: QCheckBox
    _threshold_slider: QSlider
    _episode_threshold_slider: QSlider
    _api_key_input: QLineEdit
    _tvdb_key_input: QLineEdit
    _advanced_group: QGroupBox
    _metadata_page: MetadataSettingsPage
    _automux_page: AutoMuxSettingsPage
```

- [ ] **Step 2: Run Pyright and tests**

Run: `.venv\Scripts\pyright.exe plex_renamer\gui_qt\widgets\settings_tab.py tests\test_qt_main_window.py`
Expected: settings attribute findings disappear; remaining errors are optional widget narrowing.

Run: `.venv\Scripts\python.exe -m pytest tests\test_qt_main_window.py -q`
Expected: PASS.

- [ ] **Step 3: Commit**

```powershell
git add plex_renamer/gui_qt/widgets/settings_tab.py
git commit -m "types: declare settings tab widget surface"
```

### Task 3: Narrow optional Qt lookups and enroll the test strict

**Files:**
- Modify: `tests/test_qt_main_window.py`
- Modify prune-only: `scripts/audit/quality-baseline.json`

- [ ] **Step 1: Add runtime narrowing at optional APIs**

```python
tab = window._tabs.widget(index)
self.assertIsNotNone(tab)
assert tab is not None

action = next((item for item in menu.actions() if item.text() == expected), None)
self.assertIsNotNone(action)
assert action is not None
action.trigger()
```

Apply this to the four optional-member findings and any `findChild`/`widget` result. Use the concrete widget type with `isinstance` when later assertions depend on custom attributes.

- [ ] **Step 2: Reach zero and run the module**

Run: `.venv\Scripts\pyright.exe tests\test_qt_main_window.py`
Expected: 0 errors.

Run: `.venv\Scripts\python.exe -m pytest tests\test_qt_main_window.py -q`
Expected: PASS.

- [ ] **Step 3: Format, smoke, and prune**

Run: `.venv\Scripts\ruff.exe format plex_renamer\gui_qt\main_window.py plex_renamer\gui_qt\widgets\settings_tab.py tests\test_qt_main_window.py && .venv\Scripts\ruff.exe check plex_renamer\gui_qt\main_window.py plex_renamer\gui_qt\widgets\settings_tab.py tests\test_qt_main_window.py`
Expected: exit 0.

Run: `scripts\test-smoke.cmd`
Expected: PASS.

Run: `scripts\audit.cmd --update-quality-baseline`
Expected: prune-only exit 0; 157 findings and the legacy entry are removed.

- [ ] **Step 4: Commit**

```powershell
git add plex_renamer/gui_qt/main_window.py plex_renamer/gui_qt/widgets/settings_tab.py tests/test_qt_main_window.py scripts/audit/quality-baseline.json
git commit -m "types: enroll main window tests at strict"
```
