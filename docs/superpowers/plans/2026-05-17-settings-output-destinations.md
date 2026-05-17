# Settings Output Destinations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle Settings around destination categories and make TV/movie rename jobs move selected files into configured output folders while leaving original folders and unmatched files intact.

**Architecture:** Add persisted output roots to `SettingsService`, validate them before scan startup, stamp scan states with the active output root, and persist `RenameJob.output_root` for destination-aware execution. Scanners can keep producing canonical source-root previews, but controller/queue helpers retarget actionable preview items into output-root-relative job operations. The executor takes the new path only for jobs with `output_root`, preserving completed legacy history while blocking pending legacy jobs from execution.

**Tech Stack:** Python 3.12, PySide6 widgets/QSS, SQLite job store, pytest/unittest test suite, existing `JobStore`, `QueueController`, `MediaController`, and Qt widget helpers.

---

## Scope Check

The approved spec has two visible surfaces, Settings UX and filesystem behavior, but they are not independent enough to split. Scan gating depends on destination settings, queue preview depends on destination-aware scan state, and execution depends on destination-aware queued jobs. This single plan stages the work so each task is testable and committable.

## File Structure

- Create `plex_renamer/app/services/output_destination_service.py`
  - Owns path validation, existing-directory checks, and scan source/output relationship validation.
- Modify `plex_renamer/app/services/_settings_schema.py`
  - Adds `tv_output_folder` and `movie_output_folder` defaults/schema.
- Modify `plex_renamer/app/services/settings_service.py`
  - Adds typed destination accessors and validation convenience methods.
- Modify `plex_renamer/gui_qt/widgets/settings_tab.py`
  - Changes the Settings shell from one long scroll to a category layout.
- Modify `plex_renamer/gui_qt/widgets/_settings_tab_sections.py`
  - Builds category pages and destination controls.
- Modify `plex_renamer/gui_qt/widgets/_settings_tab_state.py`
  - Syncs destination paths between UI and service.
- Modify `plex_renamer/gui_qt/resources/theme.qss`
  - Adds category sidebar, path field, and destination status styling.
- Modify `plex_renamer/gui_qt/_main_window_scan.py`
  - Blocks scans before discovery when destination settings are invalid.
- Modify `plex_renamer/engine/models.py`
  - Adds `ScanState.output_root` so preview/queue helpers know the configured output root.
- Modify `plex_renamer/app/controllers/_tv_batch_helpers.py`
  - Stamps discovered TV states with the active TV output root and retargets scanned preview items.
- Modify `plex_renamer/app/controllers/_movie_batch_helpers.py`
  - Retargets movie preview items to the active movie output root before publishing scan results.
- Modify `plex_renamer/app/controllers/_controller_match_helpers.py`
  - Retargets rematched TV/movie preview items after the scanner rebuilds them.
- Modify `plex_renamer/engine/_queue_bridge.py`
  - Builds output-root-relative rename ops, ignores unmatched/unactionable items, and persists `output_root`.
- Modify `plex_renamer/app/controllers/_queue_submission_helpers.py`
  - Requires output roots for TV/movie queue submission.
- Modify `plex_renamer/app/controllers/queue_controller.py`
  - Exposes output-root parameters.
- Modify `plex_renamer/gui_qt/widgets/_media_workspace_queue_actions.py`
  - Passes output roots from settings into queue submission.
- Modify `plex_renamer/job_store.py`, `plex_renamer/_job_store_db.py`, `plex_renamer/_job_store_codec.py`
  - Adds nullable `output_root` storage with migration to schema version 3.
- Modify `plex_renamer/job_executor.py`, `plex_renamer/_job_execution_filesystem.py`
  - Adds destination-aware execution, collision routing, legacy pending blocking, and output-root constrained revert cleanup.
- Modify `plex_renamer/app/controllers/_job_projection_helpers.py`
  - Projects completed destination-aware jobs using `output_root`.
- Modify `plex_renamer/gui_qt/widgets/_job_detail_data.py`, `plex_renamer/gui_qt/widgets/_job_detail_preview.py`
  - Shows Source/Output rather than source folder rename semantics for new jobs.
- Modify tests:
  - `tests/test_settings_service.py`
  - `tests/test_qt_main_window.py`
  - `tests/test_media_controller.py`
  - `tests/test_queue_controller.py`
  - `tests/test_scan_improvements.py`
  - `tests/test_qt_job_detail_panel.py`

---

### Task 1: Destination Settings And Validation Service

**Files:**
- Create: `plex_renamer/app/services/output_destination_service.py`
- Modify: `plex_renamer/app/services/_settings_schema.py`
- Modify: `plex_renamer/app/services/settings_service.py`
- Test: `tests/test_settings_service.py`

- [ ] **Step 1: Write failing settings and validation tests**

Append this test class to `tests/test_settings_service.py` before the `if __name__ == "__main__":` block:

```python
class TestOutputDestinations(unittest.TestCase):
    """Persistent TV/movie output folder settings and validation."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.path = self.root / "settings.json"
        self.svc = SettingsService(path=self.path)

    def tearDown(self):
        self._tmp.cleanup()

    def test_output_folders_default_to_empty(self):
        self.assertEqual(self.svc.tv_output_folder, "")
        self.assertEqual(self.svc.movie_output_folder, "")
        self.assertIsNone(self.svc.valid_tv_output_folder)
        self.assertIsNone(self.svc.valid_movie_output_folder)

    def test_output_folders_roundtrip(self):
        tv = self.root / "TV Output"
        movies = self.root / "Movie Output"
        tv.mkdir()
        movies.mkdir()

        self.svc.tv_output_folder = str(tv)
        self.svc.movie_output_folder = str(movies)

        reloaded = SettingsService(path=self.path)
        self.assertEqual(Path(reloaded.tv_output_folder), tv)
        self.assertEqual(Path(reloaded.movie_output_folder), movies)
        self.assertEqual(reloaded.valid_tv_output_folder, tv.resolve())
        self.assertEqual(reloaded.valid_movie_output_folder, movies.resolve())

    def test_output_folder_validation_requires_existing_directory(self):
        missing = self.root / "missing"
        status = self.svc.validate_output_folder(str(missing))

        self.assertFalse(status.valid)
        self.assertIn("does not exist", status.reason)

    def test_scan_output_relationship_rejects_same_directory(self):
        output = self.root / "media"
        output.mkdir()

        status = self.svc.validate_scan_output_relationship(output, output)

        self.assertFalse(status.valid)
        self.assertIn("cannot be the same", status.reason)

    def test_scan_output_relationship_rejects_output_nested_under_source(self):
        source = self.root / "source"
        output = source / "ready"
        output.mkdir(parents=True)

        status = self.svc.validate_scan_output_relationship(source, output)

        self.assertFalse(status.valid)
        self.assertIn("cannot be inside", status.reason)

    def test_scan_output_relationship_allows_source_nested_under_output(self):
        output = self.root / "library"
        source = output / "incoming"
        source.mkdir(parents=True)

        status = self.svc.validate_scan_output_relationship(source, output)

        self.assertTrue(status.valid)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_settings_service.py -q
```

Expected: FAIL with import/name errors for missing output destination accessors and validation helpers.

- [ ] **Step 3: Create output destination validation service**

Create `plex_renamer/app/services/output_destination_service.py`:

```python
"""Validation helpers for user-configured output destinations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class OutputDestinationStatus:
    valid: bool
    path: Path | None = None
    reason: str = ""


def validate_output_folder(path_value: str | Path | None) -> OutputDestinationStatus:
    """Validate that *path_value* names an existing directory."""
    text = str(path_value or "").strip()
    if not text:
        return OutputDestinationStatus(False, reason="Choose an output folder first.")

    path = Path(text).expanduser()
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        return OutputDestinationStatus(False, reason=f"Output folder does not exist: {path}")

    if not resolved.is_dir():
        return OutputDestinationStatus(False, reason=f"Output path is not a folder: {resolved}")

    return OutputDestinationStatus(True, path=resolved)


def validate_scan_output_relationship(
    source_folder: str | Path,
    output_folder: str | Path,
) -> OutputDestinationStatus:
    """Validate that output is not the selected scan source or nested under it."""
    source_status = validate_output_folder(source_folder)
    if not source_status.valid:
        return OutputDestinationStatus(False, reason=f"Scan source is invalid: {source_status.reason}")

    output_status = validate_output_folder(output_folder)
    if not output_status.valid:
        return output_status

    assert source_status.path is not None
    assert output_status.path is not None
    source = source_status.path
    output = output_status.path

    if _same_path(source, output):
        return OutputDestinationStatus(
            False,
            path=output,
            reason="Output folder cannot be the same as the scanned folder.",
        )

    if _is_relative_to(output, source):
        return OutputDestinationStatus(
            False,
            path=output,
            reason="Output folder cannot be inside the scanned folder.",
        )

    return OutputDestinationStatus(True, path=output)


def _same_path(left: Path, right: Path) -> bool:
    return left == right or str(left).casefold() == str(right).casefold()


def _is_relative_to(child: Path, parent: Path) -> bool:
    if _same_path(child, parent):
        return True
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False
```

- [ ] **Step 4: Add settings schema keys**

In `plex_renamer/app/services/_settings_schema.py`, add these keys to `SETTINGS_SCHEMA`:

```python
    "tv_output_folder": (str,),
    "movie_output_folder": (str,),
```

Add these defaults to `DEFAULT_SETTINGS`:

```python
    "tv_output_folder": "",
    "movie_output_folder": "",
```

- [ ] **Step 5: Add typed SettingsService accessors**

In `plex_renamer/app/services/settings_service.py`, add this import near the existing imports:

```python
from .output_destination_service import (
    OutputDestinationStatus,
    validate_output_folder,
    validate_scan_output_relationship,
)
```

Add these properties after `match_country` and before the Display section:

```python
    @property
    def tv_output_folder(self) -> str:
        """Configured output root for completed TV show jobs."""
        return str(self.get("tv_output_folder") or "")

    @tv_output_folder.setter
    def tv_output_folder(self, value: str) -> None:
        self.set("tv_output_folder", str(value or ""))

    @property
    def movie_output_folder(self) -> str:
        """Configured output root for completed movie jobs."""
        return str(self.get("movie_output_folder") or "")

    @movie_output_folder.setter
    def movie_output_folder(self, value: str) -> None:
        self.set("movie_output_folder", str(value or ""))

    @property
    def valid_tv_output_folder(self) -> Path | None:
        status = validate_output_folder(self.tv_output_folder)
        return status.path if status.valid else None

    @property
    def valid_movie_output_folder(self) -> Path | None:
        status = validate_output_folder(self.movie_output_folder)
        return status.path if status.valid else None

    def validate_output_folder(self, path_value: str | Path | None) -> OutputDestinationStatus:
        return validate_output_folder(path_value)

    def validate_tv_output_folder(self) -> OutputDestinationStatus:
        return validate_output_folder(self.tv_output_folder)

    def validate_movie_output_folder(self) -> OutputDestinationStatus:
        return validate_output_folder(self.movie_output_folder)

    def validate_scan_output_relationship(
        self,
        source_folder: str | Path,
        output_folder: str | Path,
    ) -> OutputDestinationStatus:
        return validate_scan_output_relationship(source_folder, output_folder)
```

- [ ] **Step 6: Run destination settings tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_settings_service.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add plex_renamer/app/services/output_destination_service.py plex_renamer/app/services/_settings_schema.py plex_renamer/app/services/settings_service.py tests/test_settings_service.py
git commit -m "Add output destination settings"
```

---

### Task 2: Category Settings Layout And Destination Controls

**Files:**
- Modify: `plex_renamer/gui_qt/widgets/settings_tab.py`
- Modify: `plex_renamer/gui_qt/widgets/_settings_tab_sections.py`
- Modify: `plex_renamer/gui_qt/widgets/_settings_tab_state.py`
- Modify: `plex_renamer/gui_qt/resources/theme.qss`
- Test: `tests/test_qt_main_window.py`

- [ ] **Step 1: Write failing SettingsTab UI tests**

Append these tests to `tests/test_qt_main_window.py` in the existing Qt test class that creates the main window or add a new `SettingsTabDestinationTests` class using the existing Qt fixture pattern in that file:

```python
def test_settings_tab_has_destination_category_and_controls(qtbot, tmp_path):
    from plex_renamer.app.services.settings_service import SettingsService
    from plex_renamer.gui_qt.widgets.settings_tab import SettingsTab

    settings = SettingsService(path=tmp_path / "settings.json")
    tab = SettingsTab(settings_service=settings)
    qtbot.addWidget(tab)

    self_or_qtbot = qtbot
    self_or_qtbot.wait(1)

    assert tab._settings_nav.count() >= 1
    assert tab._settings_nav.item(0).text() == "Destinations"
    assert tab._settings_stack.currentWidget() is tab._destinations_page
    assert tab._tv_output_input.text() == ""
    assert tab._movie_output_input.text() == ""


def test_settings_tab_saves_existing_destination_paths(qtbot, tmp_path):
    from plex_renamer.app.services.settings_service import SettingsService
    from plex_renamer.gui_qt.widgets.settings_tab import SettingsTab

    tv = tmp_path / "TV"
    movies = tmp_path / "Movies"
    tv.mkdir()
    movies.mkdir()
    settings = SettingsService(path=tmp_path / "settings.json")
    tab = SettingsTab(settings_service=settings)
    qtbot.addWidget(tab)

    tab._tv_output_input.setText(str(tv))
    tab._movie_output_input.setText(str(movies))
    tab._on_save_destinations()

    assert settings.tv_output_folder == str(tv)
    assert settings.movie_output_folder == str(movies)
    assert "saved" in tab._destinations_status.text().lower()


def test_settings_tab_rejects_missing_destination_path(qtbot, tmp_path):
    from plex_renamer.app.services.settings_service import SettingsService
    from plex_renamer.gui_qt.widgets.settings_tab import SettingsTab

    settings = SettingsService(path=tmp_path / "settings.json")
    tab = SettingsTab(settings_service=settings)
    qtbot.addWidget(tab)

    tab._tv_output_input.setText(str(tmp_path / "missing-tv"))
    tab._movie_output_input.setText("")
    tab._on_save_destinations()

    assert settings.tv_output_folder == ""
    assert "does not exist" in tab._destinations_status.text().lower()
```

If `tests/test_qt_main_window.py` uses `unittest.TestCase` rather than pytest-style functions in the surrounding section, convert the assertions to `self.assertEqual` and use the file's existing `QApplication` setup. Keep the method names exactly as above.

- [ ] **Step 2: Run UI tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_qt_main_window.py -q
```

Expected: FAIL with missing `_settings_nav`, `_settings_stack`, `_destinations_page`, and destination widget attributes.

- [ ] **Step 3: Change SettingsTab shell to a category layout**

In `plex_renamer/gui_qt/widgets/settings_tab.py`, update imports to include:

```python
    QHBoxLayout,
    QListWidget,
    QStackedWidget,
```

Replace the content setup in `SettingsTab.__init__` after `self.setFrameShape(QFrame.Shape.NoFrame)` with this structure:

```python
        content = QWidget()
        shell = QHBoxLayout(content)
        shell.setContentsMargins(24, 20, 24, 20)
        shell.setSpacing(16)

        self._settings_nav = QListWidget()
        self._settings_nav.setProperty("cssClass", "settings-nav")
        self._settings_nav.setFixedWidth(180)
        self._settings_nav.addItems([
            "Destinations",
            "Display",
            "Matching",
            "API Keys",
            "Cache",
            "Data",
        ])
        shell.addWidget(self._settings_nav)

        self._settings_stack = QStackedWidget()
        self._settings_stack.setProperty("cssClass", "settings-stack")
        shell.addWidget(self._settings_stack, stretch=1)

        self._build_destinations_section()
        self._build_display_section()
        self._build_matching_section()
        self._build_api_keys_section()
        self._build_cache_section()
        self._build_data_management_section()

        self._settings_nav.currentRowChanged.connect(self._settings_stack.setCurrentIndex)
        self._settings_nav.setCurrentRow(0)
        self.setWidget(content)
        self._refresh_cache_stats()
```

Add this wrapper method near the existing build wrappers:

```python
    def _build_destinations_section(self) -> None:
        self._sections_builder.build_destinations_section()
```

Add these callbacks near the other callbacks:

```python
    def _on_save_destinations(self) -> None:
        self._state_coordinator.on_save_destinations()

    def _on_browse_tv_output(self) -> None:
        self._state_coordinator.browse_output_folder("tv")

    def _on_browse_movie_output(self) -> None:
        self._state_coordinator.browse_output_folder("movie")
```

- [ ] **Step 4: Add category page helpers and destination controls**

In `plex_renamer/gui_qt/widgets/_settings_tab_sections.py`, add these imports:

```python
    QFileDialog,
```

Add this method to `SettingsSectionCard`:

```python
    @classmethod
    def page(cls, title: str) -> "SettingsSectionCard":
        card = cls(title)
        card.setProperty("sectionRole", "page")
        return card
```

Add these helper methods to `SettingsTabSectionsBuilder`:

```python
    def _add_page(self, page: QWidget) -> None:
        self._tab._settings_stack.addWidget(page)

    def _path_row(
        self,
        *,
        label: str,
        attr_name: str,
        browse_callback,
        initial_value: str,
        help_text: str,
    ) -> QVBoxLayout:
        tab = self._tab
        wrapper = QVBoxLayout()
        wrapper.setSpacing(6)

        title = QLabel(label)
        title.setProperty("cssClass", "row-title")
        wrapper.addWidget(title)

        row = QHBoxLayout()
        line_edit = QLineEdit()
        line_edit.setProperty("cssClass", "path-input")
        line_edit.setText(initial_value)
        line_edit.setPlaceholderText("Choose an existing folder...")
        setattr(tab, attr_name, line_edit)
        row.addWidget(line_edit, stretch=1)

        button = QPushButton("Browse")
        button.setProperty("cssClass", "secondary")
        button.clicked.connect(browse_callback)
        row.addWidget(button)
        wrapper.addLayout(row)

        helper = QLabel(help_text)
        helper.setProperty("cssClass", "caption")
        helper.setWordWrap(True)
        wrapper.addWidget(helper)
        return wrapper
```

Add this new section method:

```python
    def build_destinations_section(self) -> None:
        tab = self._tab
        section = SettingsSectionCard.page("Destinations")

        tv_initial = tab._settings.tv_output_folder if tab._settings else ""
        movie_initial = tab._settings.movie_output_folder if tab._settings else ""

        section.add_layout(
            self._path_row(
                label="TV Shows output folder",
                attr_name="_tv_output_input",
                browse_callback=tab._on_browse_tv_output,
                initial_value=tv_initial,
                help_text="Completed TV rename jobs create show and season folders under this existing directory.",
            )
        )
        section.add_layout(
            self._path_row(
                label="Movies output folder",
                attr_name="_movie_output_input",
                browse_callback=tab._on_browse_movie_output,
                initial_value=movie_initial,
                help_text="Completed movie rename jobs create movie folders under this existing directory.",
            )
        )

        actions = QHBoxLayout()
        tab._save_destinations_btn = QPushButton("Save Destinations")
        tab._save_destinations_btn.clicked.connect(tab._on_save_destinations)
        actions.addWidget(tab._save_destinations_btn)
        actions.addStretch()
        section.add_layout(actions)

        tab._destinations_status = QLabel("")
        tab._destinations_status.setProperty("cssClass", "caption")
        section.add_widget(tab._destinations_status)

        tab._destinations_page = section
        self._add_page(section)
```

At the end of each existing `build_*_section` method, replace `tab._layout.addWidget(section)` with `self._add_page(section)` for Display, Matching, API Keys, Cache, and Data Management. Remove use of `tab._layout` from this builder.

- [ ] **Step 5: Add destination state callbacks**

In `plex_renamer/gui_qt/widgets/_settings_tab_state.py`, add imports:

```python
from pathlib import Path
from PySide6.QtWidgets import QFileDialog
```

Add these methods to `SettingsTabStateCoordinator`:

```python
    def browse_output_folder(self, media_type: str) -> None:
        tab = self._tab
        title = "Choose TV Shows Output Folder" if media_type == "tv" else "Choose Movies Output Folder"
        selected = QFileDialog.getExistingDirectory(tab, title)
        if not selected:
            return
        if media_type == "tv":
            tab._tv_output_input.setText(selected)
        else:
            tab._movie_output_input.setText(selected)

    def on_save_destinations(self) -> None:
        tab = self._tab
        if tab._settings is None:
            return

        tv_path = tab._tv_output_input.text().strip()
        movie_path = tab._movie_output_input.text().strip()
        tv_status = tab._settings.validate_output_folder(tv_path)
        movie_status = tab._settings.validate_output_folder(movie_path)

        if tv_path and not tv_status.valid:
            tab._destinations_status.setProperty("tone", "error")
            tab._destinations_status.setText(tv_status.reason)
            _repolish(tab._destinations_status)
            return
        if movie_path and not movie_status.valid:
            tab._destinations_status.setProperty("tone", "error")
            tab._destinations_status.setText(movie_status.reason)
            _repolish(tab._destinations_status)
            return

        tab._settings.tv_output_folder = str(tv_status.path) if tv_status.path else ""
        tab._settings.movie_output_folder = str(movie_status.path) if movie_status.path else ""
        tab._destinations_status.setProperty("tone", "success")
        tab._destinations_status.setText("Output destinations saved.")
        _repolish(tab._destinations_status)
```

Add this module-level helper at the bottom:

```python
def _repolish(widget) -> None:
    style = widget.style()
    if style is None:
        return
    style.unpolish(widget)
    style.polish(widget)
    widget.update()
```

- [ ] **Step 6: Add QSS for the category layout**

Append to the Settings section of `plex_renamer/gui_qt/resources/theme.qss`:

```css
QListWidget[cssClass="settings-nav"] {
    background-color: #151515;
    border: 1px solid #2a2a2a;
    border-radius: 6px;
    padding: 6px;
}

QListWidget[cssClass="settings-nav"]::item {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    color: #777777;
    margin: 2px 0px;
    padding: 9px 10px;
    font-weight: 600;
}

QListWidget[cssClass="settings-nav"]::item:selected {
    background-color: #2a2210;
    border-color: #7a5a10;
    color: #e5a00d;
}

QStackedWidget[cssClass="settings-stack"] {
    background-color: transparent;
}

QFrame[cssClass="settings-section"][sectionRole="page"] {
    background-color: #1c1c1c;
    border: 1px solid #3a3a3a;
    border-radius: 6px;
    padding: 16px;
}

QLineEdit[cssClass="path-input"] {
    min-width: 360px;
}
```

- [ ] **Step 7: Run UI tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_qt_main_window.py -q
```

Expected: PASS for the new Settings tests. Fix constructor/test fixture friction only if it comes from the test file's existing Qt setup style.

- [ ] **Step 8: Commit**

```powershell
git add plex_renamer/gui_qt/widgets/settings_tab.py plex_renamer/gui_qt/widgets/_settings_tab_sections.py plex_renamer/gui_qt/widgets/_settings_tab_state.py plex_renamer/gui_qt/resources/theme.qss tests/test_qt_main_window.py
git commit -m "Restyle settings destinations"
```

---

### Task 3: Scan Gating Before Discovery

**Files:**
- Modify: `plex_renamer/gui_qt/_main_window_scan.py`
- Test: `tests/test_qt_main_window.py`

- [ ] **Step 1: Add failing scan gating tests**

Add these tests near existing main window scan tests in `tests/test_qt_main_window.py`:

```python
def test_tv_scan_is_blocked_without_output_folder(qtbot, tmp_path):
    from plex_renamer.gui_qt.main_window import MainWindow

    source = tmp_path / "incoming-tv"
    source.mkdir()
    window = MainWindow()
    qtbot.addWidget(window)
    window.settings_service.tv_output_folder = ""

    window._scan_coordinator.start_tv_scan(str(source))

    assert window.media_ctrl.tv_root_folder is None
    assert window._tv_workspace.is_showing_empty()


def test_movie_scan_is_blocked_when_output_is_nested_under_source(qtbot, tmp_path):
    from plex_renamer.gui_qt.main_window import MainWindow

    source = tmp_path / "incoming-movies"
    output = source / "ready"
    output.mkdir(parents=True)
    window = MainWindow()
    qtbot.addWidget(window)
    window.settings_service.movie_output_folder = str(output)

    window._scan_coordinator.start_movie_scan(str(source))

    assert window.media_ctrl.movie_folder is None
    assert window._movie_workspace.is_showing_empty()
```

If direct `MainWindow()` construction in this file requires injected services, follow the existing helper used by nearby tests and keep the assertions unchanged.

- [ ] **Step 2: Run scan gating tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_qt_main_window.py -q
```

Expected: FAIL because `_start_scan` does not yet validate output folders before scanning.

- [ ] **Step 3: Add scan destination validation helper**

In `plex_renamer/gui_qt/_main_window_scan.py`, add this method to `MainWindowScanCoordinator`:

```python
    def _validate_destination_for_scan(self, folder: Path, *, media_type: str) -> bool:
        window = self._window
        if media_type == "movie":
            output_status = window.settings_service.validate_movie_output_folder()
            workspace = window._movie_workspace
            label = "Movies"
        else:
            output_status = window.settings_service.validate_tv_output_folder()
            workspace = window._tv_workspace
            label = "TV Shows"

        if not output_status.valid or output_status.path is None:
            workspace.show_empty()
            window._show_scan_feedback(
                title=f"{label} output folder required",
                message=output_status.reason or f"Set a {label} output folder in Settings before scanning.",
                tone="error",
            )
            window.statusBar().showMessage("Set an output folder in Settings before scanning.", 5000)
            return False

        relationship = window.settings_service.validate_scan_output_relationship(folder, output_status.path)
        if not relationship.valid:
            workspace.show_empty()
            window._show_scan_feedback(
                title="Output folder cannot be inside the scan folder",
                message=relationship.reason,
                tone="error",
            )
            window.statusBar().showMessage(relationship.reason, 5000)
            return False

        return True
```

- [ ] **Step 4: Call the validator before showing scanning state**

In `_start_scan`, after `folder = Path(path)` and before `workspace.show_scanning()`, use:

```python
        folder = Path(path)
        if not self._validate_destination_for_scan(folder, media_type=media_type):
            return
        workspace.show_scanning()
```

Remove the earlier `workspace.show_scanning()` line if it appears before `folder = Path(path)`.

- [ ] **Step 5: Run scan gating tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_qt_main_window.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add plex_renamer/gui_qt/_main_window_scan.py tests/test_qt_main_window.py
git commit -m "Gate scans on output destinations"
```

---

### Task 4: Destination-Aware Scan Preview State

**Files:**
- Modify: `plex_renamer/engine/models.py`
- Modify: `plex_renamer/app/controllers/_tv_batch_helpers.py`
- Modify: `plex_renamer/app/controllers/_movie_batch_helpers.py`
- Modify: `plex_renamer/app/controllers/_controller_match_helpers.py`
- Test: `tests/test_media_controller.py`

- [ ] **Step 1: Add failing controller preview retarget tests**

Add this test class to `tests/test_media_controller.py` near other controller workflow tests:

```python
class OutputPreviewRetargetingTests(_ControllerTestCase):
    def test_tv_scan_state_preview_targets_output_root(self):
        output = self.tmp / "TV Output"
        source = self.tmp / "Incoming" / "Bleach" / "Season 01"
        output.mkdir()
        source.mkdir(parents=True)
        episode = source / "Bleach.S01E01.mkv"
        episode.write_text("x")
        self.ctrl.settings.tv_output_folder = str(output)

        state = ScanState(
            folder=self.tmp / "Incoming" / "Bleach",
            media_info={"id": 1, "name": "Bleach", "year": "2004"},
            preview_items=[
                PreviewItem(
                    original=episode,
                    new_name="Bleach (2004) - S01E01 - Pilot.mkv",
                    target_dir=source,
                    season=1,
                    episodes=[1],
                    status="OK",
                )
            ],
            scanned=True,
        )

        from plex_renamer.app.controllers._tv_batch_helpers import retarget_tv_state_to_output

        retarget_tv_state_to_output(state, output)

        self.assertEqual(state.output_root, output.resolve())
        self.assertEqual(
            state.preview_items[0].target_dir,
            output / "Bleach (2004)" / "Season 01",
        )

    def test_movie_preview_targets_movie_output_root(self):
        output = self.tmp / "Movies Output"
        source = self.tmp / "Incoming"
        output.mkdir()
        source.mkdir()
        movie = source / "Alien.1979.mkv"
        movie.write_text("x")
        self.ctrl.settings.movie_output_folder = str(output)

        item = PreviewItem(
            original=movie,
            new_name="Alien (1979).mkv",
            target_dir=source / "Alien (1979)",
            season=None,
            episodes=[],
            status="OK",
            media_type=MediaType.MOVIE,
            media_id=10,
            media_name="Alien",
        )

        from plex_renamer.app.controllers._movie_batch_helpers import retarget_movie_items_to_output

        retarget_movie_items_to_output([item], output)

        self.assertEqual(item.target_dir, output / "Alien (1979)")
```

- [ ] **Step 2: Run controller tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_media_controller.py -q
```

Expected: FAIL with missing `ScanState.output_root`, `retarget_tv_state_to_output`, and `retarget_movie_items_to_output`.

- [ ] **Step 3: Add output root to ScanState**

In `plex_renamer/engine/models.py`, add this field to `ScanState` near `relative_folder`:

```python
    output_root: Path | None = None
```

- [ ] **Step 4: Add TV retarget helper**

In `plex_renamer/app/controllers/_tv_batch_helpers.py`, add import:

```python
from ...parsing import build_show_folder_name
```

Add this function near the bottom before `_clear_plex_ready_checks`:

```python
def retarget_tv_state_to_output(state: ScanState, output_root: Path) -> None:
    """Retarget actionable TV preview items into the configured output root."""
    resolved_output = output_root.resolve()
    state.output_root = resolved_output
    show_folder = build_show_folder_name(
        state.media_info.get("name", ""),
        state.media_info.get("year", ""),
    )
    if not show_folder:
        show_folder = state.display_name

    for item in state.preview_items:
        if not item.new_name or item.season is None:
            continue
        if item.status != "OK" and not item.is_review:
            continue
        item.target_dir = resolved_output / show_folder / f"Season {item.season:02d}"
```

In `_complete_tv_batch_discovery`, after `controller._batch_states = states or []`, add:

```python
    tv_output = controller._settings.valid_tv_output_folder
    if tv_output is not None:
        for state in controller._batch_states:
            state.output_root = tv_output
```

Add `_settings: Any` to `_TVBatchController` protocol.

In `_complete_tv_bulk_scan`, before `_clear_plex_ready_checks(controller)`, add:

```python
    tv_output = controller._settings.valid_tv_output_folder
    if tv_output is not None:
        for state in controller._batch_states:
            if state.scanned:
                retarget_tv_state_to_output(state, tv_output)
```

- [ ] **Step 5: Add movie retarget helper**

In `plex_renamer/app/controllers/_movie_batch_helpers.py`, add:

```python
def retarget_movie_items_to_output(items: list[Any], output_root: Path) -> None:
    """Retarget actionable movie preview items into the configured output root."""
    resolved_output = output_root.resolve()
    for item in items:
        if not getattr(item, "new_name", None) or getattr(item, "target_dir", None) is None:
            continue
        if getattr(item, "media_type", None) != MediaType.MOVIE:
            continue
        target_name = Path(item.target_dir).name
        item.target_dir = resolved_output / target_name
```

Add `_settings: Any` to `_MovieBatchController` protocol.

In `_complete_movie_batch_scan`, before `controller._movie_preview_items = items`, add:

```python
    movie_output = controller._settings.valid_movie_output_folder
    if movie_output is not None:
        retarget_movie_items_to_output(items, movie_output)
```

In `plex_renamer/app/controllers/_controller_movie_workflows.py`, after building states in `build_library_states`, stamp each movie state:

```python
        movie_output = self._controller._settings.valid_movie_output_folder
        if movie_output is not None:
            for state in self._controller._movie_library_states:
                state.output_root = movie_output
```

- [ ] **Step 6: Retarget rematched items**

In `plex_renamer/app/controllers/_controller_match_helpers.py`, locate the movie and TV rematch paths that replace `state.preview_items`. After a TV rematch rebuilds scans, call:

```python
        from ._tv_batch_helpers import retarget_tv_state_to_output

        tv_output = controller._settings.valid_tv_output_folder
        if tv_output is not None and state.scanned:
            retarget_tv_state_to_output(state, tv_output)
```

After a movie rematch creates `new_item`, call:

```python
        from ._movie_batch_helpers import retarget_movie_items_to_output

        movie_output = controller._settings.valid_movie_output_folder
        if movie_output is not None:
            retarget_movie_items_to_output([new_item], movie_output)
            state.output_root = movie_output
```

Use the exact local variable names from the existing functions. Keep the imports inside the functions to avoid circular imports.

- [ ] **Step 7: Run controller tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_media_controller.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add plex_renamer/engine/models.py plex_renamer/app/controllers/_tv_batch_helpers.py plex_renamer/app/controllers/_movie_batch_helpers.py plex_renamer/app/controllers/_controller_movie_workflows.py plex_renamer/app/controllers/_controller_match_helpers.py tests/test_media_controller.py
git commit -m "Retarget previews to output folders"
```

---

### Task 5: Persist Output Root On Queue Jobs

**Files:**
- Modify: `plex_renamer/job_store.py`
- Modify: `plex_renamer/_job_store_db.py`
- Modify: `plex_renamer/_job_store_codec.py`
- Test: `tests/test_queue_controller.py`

- [ ] **Step 1: Add failing job store persistence tests**

Add these tests to `tests/test_queue_controller.py` near existing job store migration/round-trip tests:

```python
def test_job_store_round_trips_output_root(self):
    output = self.tmp / "Output"
    output.mkdir()
    job = RenameJob(
        library_root=str(self.tmp),
        output_root=str(output),
        source_folder="Show",
        media_name="Show",
        tmdb_id=44,
    )

    self.store.add_job(job)

    stored = self.store.get_job(job.job_id)
    self.assertEqual(stored.output_root, str(output))


def test_job_store_migrates_existing_db_to_add_output_root(self):
    db_path = self.tmp / "legacy_output_jobs.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE schema_version (version INTEGER NOT NULL);
        INSERT INTO schema_version (version) VALUES (2);
        CREATE TABLE jobs (
            job_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            media_type TEXT NOT NULL,
            tmdb_id INTEGER NOT NULL,
            media_name TEXT NOT NULL,
            poster_path TEXT,
            library_root TEXT NOT NULL,
            source_folder TEXT NOT NULL,
            show_folder_rename TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            error_message TEXT,
            position INTEGER NOT NULL DEFAULT 0,
            undo_data TEXT,
            job_kind TEXT NOT NULL DEFAULT 'rename',
            data_source TEXT NOT NULL DEFAULT 'tmdb',
            depends_on TEXT,
            rename_ops TEXT NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()

    migrated = JobStore(db_path=db_path)
    try:
        columns = {
            row[1]
            for row in migrated._get_conn().execute("PRAGMA table_info(jobs)").fetchall()
        }
        version = migrated._get_conn().execute("SELECT version FROM schema_version").fetchone()[0]
        self.assertIn("output_root", columns)
        self.assertEqual(version, 3)
    finally:
        migrated.close()
```

- [ ] **Step 2: Run queue tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_queue_controller.py -q
```

Expected: FAIL because `RenameJob` and schema do not have `output_root`.

- [ ] **Step 3: Add schema migration**

In `plex_renamer/_job_store_db.py`, change:

```python
SCHEMA_VERSION = 3
```

Add this column to `CREATE_SQL` after `library_root`:

```sql
    output_root     TEXT,
```

Extend `migrate_job_store`:

```python
    if version < 3:
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()
        }
        if "output_root" not in columns:
            conn.execute("ALTER TABLE jobs ADD COLUMN output_root TEXT")
        conn.execute("UPDATE schema_version SET version = ?", (3,))
        version = 3
```

Also set `version = 2` at the end of the version 2 branch:

```python
        version = 2
```

- [ ] **Step 4: Add output_root to RenameJob**

In `plex_renamer/job_store.py`, add field after `library_root`:

```python
    output_root: str | None = None  # Absolute configured TV/movie output root for new jobs
```

Add this property near `source_path`:

```python
    @property
    def output_path(self) -> Path | None:
        """Absolute output root for destination-aware jobs."""
        return Path(self.output_root) if self.output_root else None
```

Update the INSERT column list and values in `JobStore.add_job` to include `output_root` immediately after `library_root`.

The column section becomes:

```python
                        media_name, poster_path, library_root, output_root,
                        source_folder, show_folder_rename, status, error_message, position,
```

The values section becomes:

```python
                    job.media_name, job.poster_path, job.library_root, job.output_root,
                    job.source_folder,
```

- [ ] **Step 5: Add output_root to row codec**

In `plex_renamer/_job_store_codec.py`, add this argument to the `RenameJob` row construction after `library_root=row["library_root"],`:

```python
        output_root=row["output_root"],
```

- [ ] **Step 6: Run queue tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_queue_controller.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add plex_renamer/job_store.py plex_renamer/_job_store_db.py plex_renamer/_job_store_codec.py tests/test_queue_controller.py
git commit -m "Persist output roots on jobs"
```

---

### Task 6: Queue Creation Uses Output Roots And Ignores Unmatched Items

**Files:**
- Modify: `plex_renamer/engine/_queue_bridge.py`
- Modify: `plex_renamer/app/services/command_gating_service.py`
- Modify: `plex_renamer/app/controllers/_queue_submission_helpers.py`
- Modify: `plex_renamer/app/controllers/queue_controller.py`
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_queue_actions.py`
- Test: `tests/test_queue_controller.py`

- [ ] **Step 1: Add failing queue creation tests**

Add these tests to `tests/test_queue_controller.py`:

```python
def test_tv_batch_job_uses_output_root_relative_targets(self):
    from plex_renamer.app.services.command_gating_service import CommandGatingService

    lib_root = self.tmp / "Incoming"
    output = self.tmp / "TV Output"
    source = lib_root / "Bleach" / "Disc 01"
    source.mkdir(parents=True)
    output.mkdir()
    episode = source / "Bleach.001.mkv"
    episode.write_text("x")
    state = ScanState(
        folder=lib_root / "Bleach",
        output_root=output,
        media_info={"id": 15, "name": "Bleach", "year": "2004"},
        preview_items=[
            PreviewItem(
                original=episode,
                new_name="Bleach (2004) - S01E01.mkv",
                target_dir=output / "Bleach (2004)" / "Season 01",
                season=1,
                episodes=[1],
                status="OK",
            )
        ],
        scanned=True,
        checked=True,
        confidence=1.0,
    )

    result = self.ctrl.add_tv_batch(
        states=[state],
        library_root=lib_root,
        output_root=output,
        command_gating=CommandGatingService(),
    )

    self.assertEqual(result.added, 1)
    job = self.store.get_pending()[0]
    self.assertEqual(job.output_root, str(output))
    self.assertEqual(job.rename_ops[0].original_relative, "Bleach/Disc 01/Bleach.001.mkv")
    self.assertEqual(job.rename_ops[0].target_dir_relative, "Bleach (2004)/Season 01")


def test_unmatched_preview_items_do_not_produce_queue_ops(self):
    from plex_renamer.app.services.command_gating_service import CommandGatingService

    lib_root = self.tmp / "Incoming"
    output = self.tmp / "TV Output"
    source = lib_root / "Show"
    source.mkdir(parents=True)
    output.mkdir()
    unmatched = source / "extra.mkv"
    unmatched.write_text("x")
    state = ScanState(
        folder=source,
        output_root=output,
        media_info={"id": 17, "name": "Show", "year": "2024"},
        preview_items=[
            PreviewItem(
                original=unmatched,
                new_name="extra.mkv",
                target_dir=output / "Show (2024)" / "Unmatched",
                season=0,
                episodes=[],
                status="UNMATCHED: no TMDB special found - moving to Unmatched",
            )
        ],
        scanned=True,
        checked=True,
        confidence=1.0,
    )

    result = self.ctrl.add_tv_batch(
        states=[state],
        library_root=lib_root,
        output_root=output,
        command_gating=CommandGatingService(),
    )

    self.assertEqual(result.added, 0)
    self.assertTrue(result.blocked)
    self.assertEqual(self.store.get_pending(), [])
```

- [ ] **Step 2: Run queue tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_queue_controller.py -q
```

Expected: FAIL because queue APIs do not accept `output_root` and unmatched items are still considered actionable by `PreviewItem.is_actionable`.

- [ ] **Step 3: Make command gating ignore unmatched items**

In `plex_renamer/app/services/command_gating_service.py`, replace `is_actionable_item` with:

```python
    @staticmethod
    def is_actionable_item(item: PreviewItem) -> bool:
        """True when an item should produce a rename/move operation."""
        return item.is_actionable and not item.is_unmatched
```

In `plex_renamer/engine/_queue_bridge.py`, add:

```python
def _is_queue_actionable(item: PreviewItem) -> bool:
    return item.is_actionable and not item.is_unmatched
```

Use `_is_queue_actionable(item)` anywhere `_build_rename_ops` currently tests `item.is_actionable`.

- [ ] **Step 4: Add output-root-aware op construction**

In `plex_renamer/engine/_queue_bridge.py`, update `_build_rename_ops` signature:

```python
def _build_rename_ops(
    items: list[PreviewItem],
    checked_indices: set[int],
    source_root: Path,
    output_root: Path,
) -> list:
```

Inside `_build_rename_ops`, replace source/target relative calculations with:

```python
        try:
            original_rel = str(item.original.relative_to(source_root))
        except ValueError:
            original_rel = str(item.original)

        target_dir = item.target_dir or item.original.parent
        try:
            target_rel = str(target_dir.relative_to(output_root))
        except ValueError:
            target_rel = str(target_dir)
```

For companions, calculate `companion_rel` relative to `source_root`, and use the same `target_rel`.

- [ ] **Step 5: Update job builders**

In `plex_renamer/engine/_queue_bridge.py`, update `build_rename_job_from_state` signature:

```python
def build_rename_job_from_state(
    state: ScanState,
    library_root: Path,
    output_root: Path,
    show_folder_rename: str | None = None,
    checked_indices: set[int] | None = None,
) -> "RenameJob":
```

Call `_build_rename_ops(state.preview_items, checked_indices, library_root, output_root)`.

Set `output_root=str(output_root)` in the returned `RenameJob`.

Update `build_rename_job_from_items` signature with `output_root: Path`, pass it into `_build_rename_ops`, and set `output_root=str(output_root)` in the returned job.

- [ ] **Step 6: Update queue submission APIs**

In `plex_renamer/app/controllers/_queue_submission_helpers.py`, add `output_root: Path` parameters to:

```python
def add_single_queue_job(
    job_store: _QueueJobStore,
    *,
    items: list[PreviewItem],
    checked_indices: set[int],
    media_type: str,
    tmdb_id: int,
    media_name: str,
    library_root: Path,
    output_root: Path,
    source_folder: Path,
    show_folder_rename: str | None = None,
    poster_path: str | None = None,
) -> RenameJob:


def add_tv_batch_jobs(
    job_store: _QueueJobStore,
    *,
    states: list[ScanState],
    library_root: Path,
    output_root: Path,
    command_gating: CommandGatingService,
) -> BatchQueueResult:


def add_movie_batch_jobs(
    job_store: _QueueJobStore,
    *,
    states: list[ScanState],
    library_root: Path,
    output_root: Path,
    command_gating: CommandGatingService,
) -> BatchQueueResult:
```

Pass `output_root=output_root` to `build_rename_job_from_state` and `build_rename_job_from_items`.

In `plex_renamer/app/controllers/queue_controller.py`, add the same `output_root: Path` parameter to `add_single_job`, `add_tv_batch`, and `add_movie_batch`, and pass it through.

- [ ] **Step 7: Update workspace queue calls**

In `plex_renamer/gui_qt/widgets/_media_workspace_queue_actions.py`, inside the movie branch before `add_movie_batch`, add:

```python
            output_root = workspace._settings.valid_movie_output_folder if workspace._settings else None
            if output_root is None:
                workspace.status_message.emit("Set a Movies output folder in Settings before queueing.", 4000)
                return
```

Call:

```python
            result = workspace._queue_ctrl.add_movie_batch(
                states,
                root,
                output_root,
                workspace._media_ctrl.command_gating,
            )
```

Inside the TV branch before `add_tv_batch`, add:

```python
            output_root = workspace._settings.valid_tv_output_folder if workspace._settings else None
            if output_root is None:
                workspace.status_message.emit("Set a TV Shows output folder in Settings before queueing.", 4000)
                return
```

Call:

```python
            result = workspace._queue_ctrl.add_tv_batch(
                states,
                root,
                output_root,
                workspace._media_ctrl.command_gating,
            )
```

- [ ] **Step 8: Update existing tests for new signatures**

In `tests/test_queue_controller.py`, update existing `add_tv_batch` and `add_movie_batch` calls by adding an output root argument. Use the same `lib_root` when a test does not care about destinations, or create `output = self.tmp / "output"; output.mkdir()` for destination-specific tests.

Example replacement:

```python
result = self.ctrl.add_movie_batch(
    states=states,
    library_root=lib_root,
    output_root=lib_root,
    command_gating=CommandGatingService(),
)
```

- [ ] **Step 9: Run queue tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_queue_controller.py -q
```

Expected: PASS.

- [ ] **Step 10: Commit**

```powershell
git add plex_renamer/engine/_queue_bridge.py plex_renamer/app/services/command_gating_service.py plex_renamer/app/controllers/_queue_submission_helpers.py plex_renamer/app/controllers/queue_controller.py plex_renamer/gui_qt/widgets/_media_workspace_queue_actions.py tests/test_queue_controller.py
git commit -m "Build queue jobs with output roots"
```

---

### Task 7: Destination-Aware Execution And Collision Routing

**Files:**
- Modify: `plex_renamer/_job_execution_filesystem.py`
- Modify: `plex_renamer/job_executor.py`
- Test: `tests/test_scan_improvements.py`

- [ ] **Step 1: Add failing executor tests**

Add these tests to `tests/test_scan_improvements.py` near the existing queue execution filesystem tests:

```python
def test_destination_aware_tv_job_moves_files_to_output_and_preserves_source_dirs(self):
    from plex_renamer.constants import MediaType
    from plex_renamer.job_executor import _execute_rename
    from plex_renamer.job_store import RenameJob, RenameOp

    with TemporaryDirectory() as tmp:
        source_root = Path(tmp) / "Incoming"
        output_root = Path(tmp) / "TV Output"
        source_dir = source_root / "Bleach" / "Disc 01"
        source_dir.mkdir(parents=True)
        output_root.mkdir()
        episode = source_dir / "Bleach.001.mkv"
        note = source_dir / "notes.txt"
        episode.write_text("ep")
        note.write_text("keep")

        job = RenameJob(
            library_root=str(source_root),
            output_root=str(output_root),
            source_folder="Bleach",
            media_name="Bleach",
            media_type=MediaType.TV,
            rename_ops=[
                RenameOp(
                    original_relative="Bleach/Disc 01/Bleach.001.mkv",
                    new_name="Bleach (2004) - S01E01.mkv",
                    target_dir_relative="Bleach (2004)/Season 01",
                    status="OK",
                    selected=True,
                )
            ],
        )

        result = _execute_rename(job)

        self.assertEqual(result.errors, [])
        self.assertTrue((output_root / "Bleach (2004)" / "Season 01" / "Bleach (2004) - S01E01.mkv").exists())
        self.assertFalse(episode.exists())
        self.assertTrue(source_dir.exists())
        self.assertTrue(note.exists())
        self.assertFalse((output_root / "Bleach (2004)" / "Season 01" / "Unmatched Files").exists())


def test_destination_collision_routes_whole_job_to_numbered_top_folder(self):
    from plex_renamer.constants import MediaType
    from plex_renamer.job_executor import _execute_rename
    from plex_renamer.job_store import RenameJob, RenameOp

    with TemporaryDirectory() as tmp:
        source_root = Path(tmp) / "Incoming"
        output_root = Path(tmp) / "Movies"
        source_root.mkdir()
        output_root.mkdir()
        movie = source_root / "Toy.Story.1995.REMUX.mkv"
        movie.write_text("new")
        canonical = output_root / "Toy Story (1995)"
        canonical.mkdir()
        (canonical / "Toy Story (1995).mkv").write_text("existing")

        job = RenameJob(
            library_root=str(source_root),
            output_root=str(output_root),
            source_folder=".",
            media_name="Toy Story",
            media_type=MediaType.MOVIE,
            rename_ops=[
                RenameOp(
                    original_relative="Toy.Story.1995.REMUX.mkv",
                    new_name="Toy Story (1995).mkv",
                    target_dir_relative="Toy Story (1995)",
                    status="OK",
                    selected=True,
                )
            ],
        )

        result = _execute_rename(job)

        self.assertEqual(result.errors, [])
        self.assertTrue((output_root / "Toy Story (1995) (1)" / "Toy Story (1995).mkv").exists())
        self.assertTrue((output_root / "Toy Story (1995)" / "Toy Story (1995).mkv").exists())
```

- [ ] **Step 2: Run executor tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_scan_improvements.py -q
```

Expected: FAIL because `_execute_rename` still bases targets on `library_root`.

- [ ] **Step 3: Add output execution helpers**

In `plex_renamer/_job_execution_filesystem.py`, add:

```python
def choose_output_target_dirs(
    *,
    output_root: Path,
    planned_targets: list[tuple[Path, Path]],
) -> dict[Path, Path]:
    """Return a top-folder remap when selected output files would collide."""
    top_dirs = {
        _top_output_dir(output_root, target_dir)
        for _source, target_dir in planned_targets
    }
    if len(top_dirs) != 1:
        return {}

    top_dir = next(iter(top_dirs))
    collision = any((target_dir / source.name).exists() for source, target_dir in planned_targets)
    if not collision:
        return {}

    numbered = _next_numbered_sibling(top_dir)
    return {top_dir: numbered}


def apply_top_dir_remap(target_dir: Path, remap: dict[Path, Path]) -> Path:
    for old_top, new_top in remap.items():
        try:
            relative = target_dir.relative_to(old_top)
        except ValueError:
            continue
        return new_top / relative
    return target_dir


def output_target_collision_remap(
    *,
    output_root: Path,
    renames: list[tuple[Path, Path, Path]],
) -> dict[Path, Path]:
    """Choose a numbered top-level output folder if any selected target exists."""
    top_dirs = {
        _top_output_dir(output_root, target_dir)
        for _src, _dst, target_dir in renames
    }
    if len(top_dirs) != 1:
        return {}

    top_dir = next(iter(top_dirs))
    if not any(dst.exists() for _src, dst, _target_dir in renames):
        return {}

    return {top_dir: _next_numbered_sibling(top_dir)}


def _top_output_dir(output_root: Path, target_dir: Path) -> Path:
    relative = target_dir.relative_to(output_root)
    parts = relative.parts
    if not parts:
        return output_root
    return output_root / parts[0]


def _next_numbered_sibling(top_dir: Path) -> Path:
    parent = top_dir.parent
    base = top_dir.name
    index = 1
    while True:
        candidate = parent / f"{base} ({index})"
        if not candidate.exists():
            return candidate
        index += 1
```

- [ ] **Step 4: Add output execution path**

In `plex_renamer/job_executor.py`, import `apply_top_dir_remap` and `output_target_collision_remap` from `_job_execution_filesystem`.

Add this function above `_execute_rename`:

```python
def _execute_output_rename(job: RenameJob) -> RenameResult:
    result = RenameResult()
    result.log_entry = {
        "show": job.media_name,
        "job_id": job.job_id,
        "output_root": job.output_root,
        "renames": [],
        "created_dirs": [],
        "removed_dirs": [],
        "renamed_dirs": [],
    }

    if not job.output_root:
        result.errors.append("Legacy pending job must be recreated before execution.")
        return result

    source_root = Path(job.library_root)
    output_root = Path(job.output_root)
    if not output_root.exists() or not output_root.is_dir():
        result.errors.append(f"Output folder is not available: {output_root}")
        return result

    renames: list[tuple[Path, Path, Path]] = []
    for op in job.rename_ops:
        if not op.selected:
            continue
        if op.status != "OK" and not op.status.startswith("REVIEW"):
            continue
        if not op.new_name:
            continue

        src = source_root / op.original_relative
        target_dir = output_root / op.target_dir_relative
        dst = target_dir / op.new_name

        if not src.exists():
            result.errors.append(f"Source not found: {src.name}")
            continue
        renames.append((src, dst, target_dir))

    if not renames:
        return result

    remap = output_target_collision_remap(output_root=output_root, renames=renames)
    if remap:
        renames = [
            (
                src,
                apply_top_dir_remap(target_dir, remap) / dst.name,
                apply_top_dir_remap(target_dir, remap),
            )
            for src, dst, target_dir in renames
        ]

    for _src, dst, _target_dir in renames:
        if dst.exists():
            result.errors.append(f"Target already exists, skipped: {dst.name}")
    if result.errors:
        return result

    apply_rename_plan(renames, result)
    return result
```

At the top of `_execute_rename`, add:

```python
    if job.output_root:
        return _execute_output_rename(job)
```

- [ ] **Step 5: Block pending legacy jobs in executor**

In `QueueExecutor._execute_one`, before `result = executor_fn(job)`, add:

```python
            if job.job_kind == JobKind.RENAME and not job.output_root:
                raise ValueError("Legacy pending job must be recreated before execution.")
```

- [ ] **Step 6: Run executor tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_scan_improvements.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add plex_renamer/_job_execution_filesystem.py plex_renamer/job_executor.py tests/test_scan_improvements.py
git commit -m "Execute rename jobs into output folders"
```

---

### Task 8: Revert Destination Jobs And Clean Output Folders Only

**Files:**
- Modify: `plex_renamer/job_executor.py`
- Test: `tests/test_scan_improvements.py`
- Test: `tests/test_queue_controller.py`

- [ ] **Step 1: Add failing revert tests**

Add this test to `tests/test_scan_improvements.py`:

```python
def test_revert_destination_job_restores_files_and_removes_empty_output_dirs_only(self):
    from plex_renamer.job_executor import _execute_rename, revert_job
    from plex_renamer.job_store import RenameJob, RenameOp

    with TemporaryDirectory() as tmp:
        source_root = Path(tmp) / "Incoming"
        output_root = Path(tmp) / "TV Output"
        source_dir = source_root / "Show" / "Disc 01"
        source_dir.mkdir(parents=True)
        output_root.mkdir()
        original = source_dir / "Show.001.mkv"
        original.write_text("x")

        job = RenameJob(
            library_root=str(source_root),
            output_root=str(output_root),
            source_folder="Show",
            media_name="Show",
            rename_ops=[
                RenameOp(
                    original_relative="Show/Disc 01/Show.001.mkv",
                    new_name="Show (2024) - S01E01.mkv",
                    target_dir_relative="Show (2024)/Season 01",
                    status="OK",
                    selected=True,
                )
            ],
        )

        result = _execute_rename(job)
        job.undo_data = result.log_entry

        ok, errors = revert_job(job)

        self.assertTrue(ok, errors)
        self.assertTrue(original.exists())
        self.assertTrue(source_dir.exists())
        self.assertTrue(output_root.exists())
        self.assertFalse((output_root / "Show (2024)").exists())
```

Add this second test:

```python
def test_revert_destination_job_preserves_output_folder_with_unrelated_files(self):
    from plex_renamer.job_executor import _execute_rename, revert_job
    from plex_renamer.job_store import RenameJob, RenameOp

    with TemporaryDirectory() as tmp:
        source_root = Path(tmp) / "Incoming"
        output_root = Path(tmp) / "Movies"
        source_root.mkdir()
        output_root.mkdir()
        original = source_root / "Alien.1979.mkv"
        original.write_text("x")

        job = RenameJob(
            library_root=str(source_root),
            output_root=str(output_root),
            source_folder=".",
            media_name="Alien",
            rename_ops=[
                RenameOp(
                    original_relative="Alien.1979.mkv",
                    new_name="Alien (1979).mkv",
                    target_dir_relative="Alien (1979)",
                    status="OK",
                    selected=True,
                )
            ],
        )

        result = _execute_rename(job)
        unrelated = output_root / "Alien (1979)" / "poster.jpg"
        unrelated.write_text("keep")
        job.undo_data = result.log_entry

        ok, errors = revert_job(job)

        self.assertTrue(ok, errors)
        self.assertTrue(original.exists())
        self.assertTrue(unrelated.exists())
```

- [ ] **Step 2: Run revert tests to verify failure or source-cleanup risk**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_scan_improvements.py -q
```

Expected: FAIL if output cleanup does not walk correctly within `output_root`, or PASS if Task 7's undo data already satisfies the simple case. Continue with the implementation either way because cleanup boundary must be explicit.

- [ ] **Step 3: Add output-root cleanup helper**

In `plex_renamer/job_executor.py`, add this helper above `revert_job`:

```python
def _cleanup_empty_output_dirs(
    *,
    output_root: Path,
    created_dirs: list[str],
    moved_from_paths: list[Path],
) -> None:
    boundary = output_root.resolve()
    candidates = {Path(path) for path in created_dirs}
    candidates.update(path.parent for path in moved_from_paths)

    for candidate in sorted(candidates, key=lambda path: len(path.parts), reverse=True):
        current = candidate
        while True:
            try:
                resolved = current.resolve()
            except OSError:
                break
            if resolved == boundary:
                break
            try:
                resolved.relative_to(boundary)
            except ValueError:
                break
            try:
                if current.exists() and not any(current.iterdir()):
                    current.rmdir()
                    current = current.parent
                    continue
            except OSError:
                pass
            break
```

- [ ] **Step 4: Route revert cleanup for output jobs**

In `revert_job`, after the file-move loop and before the existing "Remove created directories if empty" block, collect moved-from output paths:

```python
    moved_from_paths: list[Path] = []
```

Inside the successful `if new_path.exists():` branch after moving/renaming back, append:

```python
                moved_from_paths.append(new_path)
```

Before the old created-dir cleanup block, add:

```python
    if job.output_root:
        _cleanup_empty_output_dirs(
            output_root=Path(job.output_root),
            created_dirs=list(undo.get("created_dirs", [])),
            moved_from_paths=moved_from_paths,
        )
        return len(errors) == 0, errors
```

This ensures destination-aware reverts never use `cleanup_boundary = library_root / source_folder.parent` to remove source-side directories.

- [ ] **Step 5: Run revert and queue controller tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_scan_improvements.py tests/test_queue_controller.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add plex_renamer/job_executor.py tests/test_scan_improvements.py tests/test_queue_controller.py
git commit -m "Constrain revert cleanup to output folders"
```

---

### Task 9: Queue And History Detail Display Output Semantics

**Files:**
- Modify: `plex_renamer/app/controllers/_job_projection_helpers.py`
- Modify: `plex_renamer/gui_qt/widgets/_job_detail_data.py`
- Modify: `plex_renamer/gui_qt/widgets/_job_detail_preview.py`
- Test: `tests/test_qt_job_detail_panel.py`
- Test: `tests/test_media_controller.py`

- [ ] **Step 1: Add failing job detail tests**

Add these tests to `tests/test_qt_job_detail_panel.py`:

```python
def test_destination_job_detail_uses_output_root_for_target_paths(self):
    from plex_renamer.gui_qt.widgets._job_detail_data import primary_target_path
    from plex_renamer.job_store import RenameJob, RenameOp

    job = RenameJob(
        library_root="C:/incoming",
        output_root="D:/TV Output",
        source_folder="Bleach",
        media_type="tv",
        media_name="Bleach",
        rename_ops=[
            RenameOp(
                original_relative="Bleach/Disc 01/Bleach.001.mkv",
                new_name="Bleach (2004) - S01E01.mkv",
                target_dir_relative="Bleach (2004)/Season 01",
                status="OK",
                selected=True,
            )
        ],
    )

    self.assertEqual(
        primary_target_path(job),
        Path("D:/TV Output") / "Bleach (2004)" / "Season 01",
    )


def test_destination_job_preview_labels_output_move(self):
    from plex_renamer.gui_qt.widgets._job_detail_preview import build_job_preview_entries
    from plex_renamer.job_store import RenameJob, RenameOp

    job = RenameJob(
        library_root="C:/incoming",
        output_root="D:/Movies",
        source_folder=".",
        media_type="movie",
        media_name="Alien",
        rename_ops=[
            RenameOp(
                original_relative="Alien.1979.mkv",
                new_name="Alien (1979).mkv",
                target_dir_relative="Alien (1979)",
                status="OK",
                selected=True,
            )
        ],
    )

    entries = build_job_preview_entries(job)

    self.assertEqual(entries[0].label, "Output Folder")
    self.assertEqual(entries[0].rows[0].before_label, "Source")
    self.assertEqual(entries[0].rows[0].after_label, "Output")
```

- [ ] **Step 2: Run Qt job detail tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_qt_job_detail_panel.py -q
```

Expected: FAIL because target paths still use `library_root`, and preview groups still say folder rename.

- [ ] **Step 3: Update target path helpers**

In `plex_renamer/gui_qt/widgets/_job_detail_data.py`, add:

```python
def job_target_root(job: RenameJob) -> Path:
    return Path(job.output_root) if job.output_root else Path(job.library_root)
```

In `target_paths`, replace:

```python
        target = Path(job.library_root) / final_target_dir_relative(job, op)
```

with:

```python
        target = job_target_root(job) / final_target_dir_relative(job, op)
```

In the fallback branch, if `job.output_root` exists, use:

```python
        fallback = Path(job.output_root) / job.show_folder_rename
```

before the legacy fallback logic.

In `build_job_fact_values`, change action value:

```python
        "action": "Move and Rename" if job.output_root and job.job_kind == "rename" else job.job_kind.title(),
```

- [ ] **Step 4: Update preview group semantics**

In `plex_renamer/gui_qt/widgets/_job_detail_preview.py`, replace the folder preview block in `build_job_preview_entries` with:

```python
    if job.output_root:
        target_name = _output_top_folder_name(job)
        source_name = Path(job.source_folder).name if job.source_folder not in {"", "."} else Path(job.library_root).name
        if target_name:
            entries.append(
                JobPreviewGroup(
                    label="Output Folder",
                    rows=[
                        JobPreviewRow(
                            before=source_name,
                            after=target_name,
                            before_label="Source",
                            after_label="Output",
                        )
                    ],
                    expanded=True,
                )
            )
    else:
        folder_preview = folder_preview_data(job)
        if folder_preview is not None:
            source_name, target_name = folder_preview
            entries.append(
                JobPreviewGroup(
                    label="Folder Rename",
                    rows=[
                        JobPreviewRow(
                            before=source_name,
                            after=target_name,
                            before_label="Source",
                            after_label="Target",
                        )
                    ],
                    expanded=True,
                )
            )
```

Add helper below `build_job_preview_entries`:

```python
def _output_top_folder_name(job: RenameJob) -> str | None:
    ops = job.selected_ops or job.rename_ops
    for op in ops:
        parts = [part for part in Path(op.target_dir_relative).parts if part not in {"", "."}]
        if parts:
            return parts[0]
    return None
```

- [ ] **Step 5: Update completed projection for output-root jobs**

In `plex_renamer/app/controllers/_job_projection_helpers.py`, update `library_root = Path(job.library_root)` block by also defining:

```python
    source_root = Path(job.library_root)
    target_root = Path(job.output_root) if getattr(job, "output_root", None) else source_root
```

Use `source_root` for `_normalized_preview_relative` and `companion_lookup`. Use `target_root` when building `final_dir`:

```python
        final_dir = target_root / Path(final_dir_relative)
```

In `_job_completed_root_relative`, if `job.output_root` is present, keep returning the first top-level target directory relative string, because `state.relative_folder` should remain useful as the output media folder name after completion.

- [ ] **Step 6: Run detail and controller tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_qt_job_detail_panel.py tests/test_media_controller.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add plex_renamer/app/controllers/_job_projection_helpers.py plex_renamer/gui_qt/widgets/_job_detail_data.py plex_renamer/gui_qt/widgets/_job_detail_preview.py tests/test_qt_job_detail_panel.py tests/test_media_controller.py
git commit -m "Show output destinations in job details"
```

---

### Task 10: Full Verification And Compatibility Sweep

**Files:**
- Modify only files needed to fix failures found by the verification commands.
- Test: full relevant suite.

- [ ] **Step 1: Run focused destination suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_settings_service.py tests/test_qt_main_window.py tests/test_media_controller.py tests/test_queue_controller.py tests/test_scan_improvements.py tests/test_qt_job_detail_panel.py -q
```

Expected: PASS.

- [ ] **Step 2: Run existing approved smoke group**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_qt_workspace_widgets.py tests/test_media_controller.py tests/test_qt_main_window.py tests/test_qt_media_workspace.py -q
```

Expected: PASS.

- [ ] **Step 3: Search for old unmatched/source cleanup behavior still active for output jobs**

Run:

```powershell
rg -n "Unmatched Files|cleanup_source_directories|show_folder_rename|output_root|target_dir_relative" plex_renamer tests
```

Expected:

- `Unmatched Files` remains only in legacy helper code or tests that intentionally cover legacy behavior.
- New destination-aware execution branches use `output_root`.
- New queue-job creation always passes `output_root`.

- [ ] **Step 4: Manual app check**

Run the Qt app:

```powershell
.\.venv\Scripts\python.exe -m plex_renamer --qt
```

Manual checks:

- Settings opens to Destinations.
- Existing TV and movie output roots can be saved.
- TV scan is blocked when the TV output folder is empty.
- Movie scan is blocked when movie output is nested inside scan source.
- A TV scan preview shows paths under the TV output root.
- A movie scan preview shows paths under the Movie output root.
- Queue detail for a pending destination-aware job shows Move and Rename.

- [ ] **Step 5: Commit verification fixes**

If Step 1 through Step 4 required code fixes:

```powershell
git add plex_renamer/app/services/output_destination_service.py plex_renamer/app/services/_settings_schema.py plex_renamer/app/services/settings_service.py plex_renamer/gui_qt/widgets/settings_tab.py plex_renamer/gui_qt/widgets/_settings_tab_sections.py plex_renamer/gui_qt/widgets/_settings_tab_state.py plex_renamer/gui_qt/resources/theme.qss plex_renamer/gui_qt/_main_window_scan.py plex_renamer/engine/models.py plex_renamer/app/controllers/_tv_batch_helpers.py plex_renamer/app/controllers/_movie_batch_helpers.py plex_renamer/app/controllers/_controller_match_helpers.py plex_renamer/engine/_queue_bridge.py plex_renamer/app/controllers/_queue_submission_helpers.py plex_renamer/app/controllers/queue_controller.py plex_renamer/gui_qt/widgets/_media_workspace_queue_actions.py plex_renamer/job_store.py plex_renamer/_job_store_db.py plex_renamer/_job_store_codec.py plex_renamer/job_executor.py plex_renamer/_job_execution_filesystem.py plex_renamer/app/controllers/_job_projection_helpers.py plex_renamer/gui_qt/widgets/_job_detail_data.py plex_renamer/gui_qt/widgets/_job_detail_preview.py tests/test_settings_service.py tests/test_qt_main_window.py tests/test_media_controller.py tests/test_queue_controller.py tests/test_scan_improvements.py tests/test_qt_job_detail_panel.py tests/test_qt_workspace_widgets.py tests/test_qt_media_workspace.py
git commit -m "Stabilize output destination workflow"
```

If no fixes were needed, do not create an empty commit.

---

## Implementation Notes

- Do not rename or delete original source folders in destination-aware execution.
- Do not add copy mode or mkvmerge controls in this plan.
- Keep completed legacy history display/revert working through stored undo data.
- Block pending legacy rename jobs without `output_root` at execution with "Legacy pending job must be recreated before execution."
- Treat `library_root` as the source root for new jobs, even though the name is historically broad.
- Treat `output_root` as the only base for target paths for new jobs.
- Keep collision numbering on the top-level output media folder only.

## Final Verification Command

After all tasks are complete, run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_settings_service.py tests/test_qt_main_window.py tests/test_media_controller.py tests/test_queue_controller.py tests/test_scan_improvements.py tests/test_qt_job_detail_panel.py tests/test_qt_workspace_widgets.py tests/test_qt_media_workspace.py -q
```

Expected: PASS.
