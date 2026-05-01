# Batch Layout Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the visual regressions and wasted space in batch detail, episode picker, and settings surfaces.

**Architecture:** Keep the current split-panel structure, but make sizing explicit and content-driven: fact values should occupy the card, dialogs should start at useful dimensions, settings sections should be compact rows that can grow into categories, and long text should elide or wrap without horizontal scrolling.

**Tech Stack:** Python, PySide6 layouts, QSS, pytest Qt smoke tests.

---

## File Structure

- Modify `plex_renamer/gui_qt/widgets/media_detail_panel.py`: fix fact card width and value layout.
- Modify `plex_renamer/gui_qt/widgets/_media_detail_payloads.py`: keep useful fallback rows.
- Modify `plex_renamer/gui_qt/widgets/_media_workspace_actions.py`: enlarge and structure episode picker dialog.
- Modify `plex_renamer/gui_qt/widgets/settings_tab.py`: reduce margins and support compact section grid.
- Modify `plex_renamer/gui_qt/widgets/_settings_tab_sections.py`: rebuild settings sections as compact rows.
- Modify `plex_renamer/gui_qt/resources/theme.qss`: adjust settings and detail section spacing.
- Modify `tests/test_qt_media_detail_panel.py`, `tests/test_qt_media_workspace.py`, and `tests/test_qt_main_window.py`.

### Task 1: Fact Card Width And Values

**Files:**
- Modify: `tests/test_qt_media_detail_panel.py`
- Modify: `plex_renamer/gui_qt/widgets/media_detail_panel.py`

- [ ] **Step 1: Write failing card-width regression test**

Add:

```python
    def test_media_detail_panel_facts_card_fills_summary_column(self):
        from plex_renamer.gui_qt.widgets.media_detail_panel import MediaDetailPanel

        panel = MediaDetailPanel()
        panel.resize(680, 640)
        panel.show()
        panel._current_token = "token"
        panel._apply_payload(
            {
                "title": "Arrival (2016)",
                "subtitle": "",
                "rows": [("Match", "Matched"), ("Confidence", "96%"), ("Runtime", "1h 56m")],
                "overview": "",
                "extra": "",
                "artwork_mode": "poster",
            },
            None,
            "token",
        )
        self._app.processEvents()

        summary_width = panel._summary_body.geometry().width()
        self.assertGreaterEqual(panel._facts_card.width(), summary_width - 8)
        for key_label, value_label in panel._meta_rows:
            if key_label.isVisible():
                self.assertGreater(value_label.width(), key_label.width())

        panel.close()
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
python -m pytest tests/test_qt_media_detail_panel.py::QtMediaDetailPanelTests::test_media_detail_panel_facts_card_fills_summary_column -q
```

Expected: fails because `_facts_card` has a fixed maximum width.

- [ ] **Step 3: Implement width fix**

In `media_detail_panel.py`, remove:

```python
self._facts_card.setMaximumWidth(280)
```

Set:

```python
self._facts_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
```

Keep `meta_layout.setColumnStretch(1, 1)`.

- [ ] **Step 4: Run test to verify pass**

Run the same pytest command. Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_qt_media_detail_panel.py plex_renamer/gui_qt/widgets/media_detail_panel.py
git commit -m "Let detail facts fill the summary column"
```

### Task 2: Episode Picker Dialog Size And Season Headers

**Files:**
- Modify: `tests/test_qt_media_workspace.py`
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_actions.py`

- [ ] **Step 1: Write failing dialog structure test**

Add a test that calls the exact non-exec constructor `EpisodeChoiceDialog.build_dialog(...)` and asserts:

```python
choices = [
    ("S01E01 - Pilot", 1, 1),
    ("S01E02 - Second", 1, 2),
    ("S02E01 - Return", 2, 1),
]
dialog = EpisodeChoiceDialog.build_dialog(
    parent=None,
    title="Fix Episode Match",
    prompt="Choose an episode",
    choices=choices,
    current_index=0,
)
self.assertGreaterEqual(dialog.minimumWidth(), 720)
self.assertGreaterEqual(dialog.minimumHeight(), 520)
self.assertEqual(dialog._list.horizontalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
self.assertTrue(any(dialog._list.item(row).text() == "Season 1" for row in range(dialog._list.count())))
dialog.close()
```

- [ ] **Step 2: Extract dialog builder**

Split `EpisodeChoiceDialog.pick()` into:

```python
@staticmethod
def build_dialog(parent, title, prompt, choices, current_index):
    ...
```

Set:

```python
dialog.setMinimumSize(720, 520)
list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
```

- [ ] **Step 3: Add season headers**

When choices move from season `n` to season `m`, insert a disabled header item:

```python
header = QListWidgetItem("Specials" if season == 0 else f"Season {season}")
header.setFlags(Qt.ItemFlag.NoItemFlags)
```

Do not count header rows when mapping `current_index`.

- [ ] **Step 4: Run test**

Run:

```bash
python -m pytest tests/test_qt_media_workspace.py::QtMediaWorkspaceTests::test_episode_choice_dialog_is_large_and_groups_by_season -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add plex_renamer/gui_qt/widgets/_media_workspace_actions.py tests/test_qt_media_workspace.py
git commit -m "Improve episode choice dialog layout"
```

### Task 3: Compact Settings Tab

**Files:**
- Modify: `tests/test_qt_main_window.py`
- Modify: `plex_renamer/gui_qt/widgets/settings_tab.py`
- Modify: `plex_renamer/gui_qt/widgets/_settings_tab_sections.py`
- Modify: `plex_renamer/gui_qt/resources/theme.qss`

- [ ] **Step 1: Write failing settings density test**

Add:

```python
    def test_settings_tab_uses_compact_expandable_sections(self):
        from plex_renamer.gui_qt.widgets.settings_tab import SettingsTab

        tab = SettingsTab()
        tab.resize(900, 700)
        tab.show()
        self._app.processEvents()

        self.assertLessEqual(tab._layout.contentsMargins().left(), 20)
        self.assertLessEqual(tab._layout.spacing(), 10)
        self.assertTrue(hasattr(tab, "_settings_sections"))
        self.assertGreaterEqual(len(tab._settings_sections), 5)
        first_section = tab._settings_sections[0]
        self.assertLessEqual(first_section.layout().contentsMargins().top(), 10)
        self.assertLess(first_section.sizeHint().height(), 150)

        tab.close()
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
python -m pytest tests/test_qt_main_window.py::QtMainWindowTests::test_settings_tab_uses_compact_expandable_sections -q
```

Expected: fails because settings use large margins and section padding.

- [ ] **Step 3: Implement compact section cards**

In `SettingsTab.__init__`, change:

```python
self._layout.setContentsMargins(16, 14, 16, 14)
self._layout.setSpacing(8)
self._settings_sections = []
```

In `SettingsSectionCard`, use:

```python
self._layout.setContentsMargins(10, 8, 10, 10)
self._layout.setSpacing(8)
```

Append each section to `tab._settings_sections`.

- [ ] **Step 4: Simplify QSS padding**

Change `QFrame[cssClass="settings-section"]` padding from `16px` to `8px`.

- [ ] **Step 5: Run test**

Run the same pytest command. Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add tests/test_qt_main_window.py plex_renamer/gui_qt/widgets/settings_tab.py plex_renamer/gui_qt/widgets/_settings_tab_sections.py plex_renamer/gui_qt/resources/theme.qss
git commit -m "Compact the settings tab layout"
```

### Task 4: Focused Layout Regression Suite

**Files:**
- Modify: `tests/test_qt_media_detail_panel.py`
- Modify: `tests/test_qt_media_workspace.py`
- Modify: `tests/test_qt_main_window.py`

- [ ] **Step 1: Run focused layout suite**

Run:

```bash
python -m pytest tests/test_qt_media_detail_panel.py tests/test_qt_media_workspace.py tests/test_qt_main_window.py -q
```

Expected: pass.

- [ ] **Step 2: Add deterministic horizontal-scrollbar smoke**

Add `test_batch_middle_panels_hide_horizontal_scrollbars_at_1280px` in `tests/test_qt_media_workspace.py`. Instantiate TV and movie `MediaWorkspace` fixtures with long episode/movie names, resize each workspace to `1280x720`, call `show_ready()`, process events, and assert:

```python
self.assertEqual(workspace._preview_list.horizontalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
self.assertFalse(workspace._preview_list.horizontalScrollBar().isVisible())
```

For Settings, add a `SettingsTab` assertion in `tests/test_qt_main_window.py` that no direct child `QScrollArea` horizontal scrollbar is visible at `1280x720`.

- [ ] **Step 3: Commit**

```bash
git add tests/test_qt_media_detail_panel.py tests/test_qt_media_workspace.py tests/test_qt_main_window.py
git commit -m "Add layout regression coverage"
```
