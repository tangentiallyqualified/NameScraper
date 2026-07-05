# GUI V4 Plan 8 — Settings Restyle + mkvmerge Seams Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land spec §12 — themed checkbox indicator with a DPI-crisp SVG check glyph, section cards with icon+title header rows, destructive actions consolidated under a "Data" section as danger-outline with confirm counts, and the hidden "Tools" section shell — plus pin the already-landed §13 expansion-card merge seams with regression tests.

**Architecture:** All changes are view-layer. The theme template gains one substitution token (`${check_svg}` → absolute posix path of a new SVG asset) so QSS can reference a resource file without hardcoded paths; `SettingsSectionCard` swaps its heading+hairline for an icon+title header row (QStyle standard icons, same illustration language as the empty states); the Cache page merges into the Data page; confirm counts flow through the existing injected-`message_box_api` pattern plus one new additive read-model callback (`history_count_callback`). No new widget files; no engine/controller/service behavior changes.

**Tech Stack:** PySide6 (QSS via `theme.qss.tmpl` tokens + `string.Template` substitution, QStyle standard icons), `_scale.px`/`_scale.icon` sizing, existing nav-list + stacked-pages settings architecture (spec §12: "Keep nav + stacked pages").

## Global Constraints

- No engine/controller/service/job-store behavior changes (spec §16). The one new callback (`history_count_callback`) is an additive read-model hook wired to `len(queue_ctrl.get_history())` — no new controller methods.
- §13 out-of-scope is absolute: **no mkvmerge invocation, no merge queueing, no new persisted fields** (spec §13). The Tools section ships hidden; the Merge… slot stays disabled.
- All colors through `gui_qt/theme.py` tokens — the Plan 1 no-hex guard scans every `gui_qt/*.py` and `theme.qss.tmpl` (`tests/test_gui_theme.py:51,81`); the new SVG asset must use **named colors only** (`stroke="white"`), never hex, so the guards stay meaningful.
- All sizing through `gui_qt/_scale.py` `px()`/`icon()` (icon tokens: sm=16, md=24, lg=32, xl=48).
- No `"Plex"` user-facing strings (AST guard); no `processEvents` in `gui_qt`; no inline `setStyleSheet`.
- Public seams unchanged: `SettingsTab` signals (`view_mode_changed`, `companion_visibility_changed`, `discovery_visibility_changed`, `language_changed`, `threshold_changed`, `episode_threshold_changed`, `api_key_saved`, `history_cleared`) and all `sync_*` methods; `EpisodeExpansionCard.action_requested`/`collapse_requested` and the `episode_row_actions` id vocabulary (frozen contract, see its docstring). `SettingsTab.__init__` gains only a keyword arg with a `None` default — every existing construction keeps working.
- Suites must pass at the end of every task: `scripts\test-fast.cmd` + `scripts\test-smoke.cmd`, zero skips. Run Python via `.venv\Scripts\python.exe`. **This plan adds no new test files** — all tests extend `tests/test_gui_theme.py` (fast), `tests/test_qt_main_window.py` (smoke), and `tests/test_episode_expansion.py` (smoke), so the runner-classification lists under `scripts/` are untouched.
- Message boxes must never `exec()` unpatched under offscreen tests (Plan 4's hang lesson) — every confirm flow keeps the injected `message_box_api` pattern and tests use fakes or `patch.object(QMessageBox, "question", ...)`.

**Recorded deviations (decided at plan time — do not silently "fix"):**
1. §12's "combo/slider/input restyle from tokens" **already landed in Plan 1** — `QLineEdit`/`QComboBox`/`QSlider` are fully token-styled (`theme.qss.tmpl:585-707`). The only real §12 indicator gap is the checkbox: no check glyph on the checked state, and the unchecked box is a filled `border_light` block instead of an input-style well. Task 1 fixes exactly that.
2. §13's expanded-row UI seams **already landed in Plan 3** — `_episode_expansion.py` lists primary + companions with type badges, reserves the disabled `Merge…` slot (pinned by `test_episode_expansion.py:26`), and carries the `_ChipStrip`/`_multi_part_chip_specs` "Part 1 · Part 2" machinery. Task 5 *pins* the unpinned parts (badges, part chips) with regression tests; it re-implements nothing.
3. §13's queue-detail per-file grouping landed in Plan 7; §13's data seam (`merge_plan`) is design-level only by the spec's own text ("no schema change ships in V4"). The **only new §13 code** in this plan is the hidden Settings Tools shell (Task 4).
4. §16's "dialogs (`match_picker_dialog.py`, `episode_assign_dialog.py`) restyle" (floated to Plan 8/9 by Plan 4's scope notes) is a **no-op**: both dialogs are already hex-free, `setStyleSheet`-free, and fully covered by the global QSS. Visual confirmation rides with Plan 9's DPI pass.
5. The checked indicator keeps its existing `${success}` fill (spec names no color; only the glyph is missing). `indicator:indeterminate` keeps its solid fill — no real tri-state `QCheckBox` exists in the app (the table master-check is delegate-painted, not QSS).
6. The "Cache" nav page **merges into "Data"** — §12 groups the destructive actions (clear cache / clear history) under one Data section, and moving the buttons would leave Cache holding a lone stats label. Stats move with them. Nav: `Destinations · Display · Matching · API Keys · Data` + hidden `Tools`.
7. Multi-part "Part" chips are a **latent seam**: today's engine policy marks every multi-claimed slot a conflict (`episode_assignments.py` docstring: "Today 2+ claims is a conflict"), so `_multi_part_chip_specs` can only fire under the future `ROLE_VERSION` policy. Task 5 pins the view contract with a future-policy stub table — that is the correct test for a seam, not a gap to "fix".

---

### Task 1: Themed checkbox indicator — check glyph SVG + template path token

**Files:**
- Create: `plex_renamer/gui_qt/resources/check.svg`
- Modify: `plex_renamer/gui_qt/theme.py:45,65-68` (`_TEMPLATE_PATH` → `_RESOURCES_DIR`; `_mapping()` gains `check_svg`)
- Modify: `plex_renamer/gui_qt/resources/theme.qss.tmpl:681-697` (indicator base + checked rules)
- Test: `tests/test_gui_theme.py` (extend)

**Interfaces:**
- Consumes: `theme.render_template` / `theme.load_stylesheet` (existing `string.Template` substitution).
- Produces: template token `${check_svg}` (absolute posix path, always present in `_mapping()`); `resources/check.svg` asset. Task 6 verifies the glyph visually.

- [ ] **Step 1: Write the failing test** — append to `tests/test_gui_theme.py`:

```python
def test_checkbox_checked_indicator_uses_svg_check_glyph():
    # Spec §12: proper check glyph SVG, DPI-crisp at 100/150/200%.
    rendered = theme.load_stylesheet()
    match = re.search(
        r'QCheckBox::indicator:checked\s*\{[^}]*image:\s*url\("([^"]+)"\)',
        rendered,
    )
    assert match, "checked indicator has no glyph image"
    svg = Path(match.group(1))
    assert svg.exists(), svg
    text = svg.read_text(encoding="utf-8")
    assert text.lstrip().startswith("<svg")
    assert _HEX_RE.findall(text) == []  # named colors only — hex guards stay meaningful
```

(`re`, `Path`, `theme`, and `_HEX_RE` are already imported/defined at the top of the file.)

- [ ] **Step 2: Run to verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests\test_gui_theme.py -q`
Expected: FAIL — `assert match` (no `image:` in the checked-indicator rule).

- [ ] **Step 3: Create the asset** — `plex_renamer/gui_qt/resources/check.svg` (named color only, intrinsic 18px matching the QSS indicator size; Qt rasterizes SVG at the device pixel ratio, which is the §12 "crisp at 100/150/200%" mechanism):

```svg
<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 18 18">
  <path d="M4 9.5 7.5 13 14 5.5" fill="none" stroke="white" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
```

- [ ] **Step 4: Add the path token** — in `theme.py`, replace the `_TEMPLATE_PATH` line and `_mapping()`:

```python
_RESOURCES_DIR = Path(__file__).parent / "resources"
_TEMPLATE_PATH = _RESOURCES_DIR / "theme.qss.tmpl"
```

```python
def _mapping() -> dict[str, str]:
    mapping = dict(COLORS)
    mapping.update({f"radius_{key}": str(value) for key, value in RADII.items()})
    # QSS url() paths resolve against the CWD for string stylesheets, so the
    # template gets an absolute posix path (quoted in the QSS — the repo path
    # contains spaces).
    mapping["check_svg"] = (_RESOURCES_DIR / "check.svg").as_posix()
    return mapping
```

- [ ] **Step 5: Restyle the indicator** — in `theme.qss.tmpl`, replace the three rules at lines ~681-697:

```css
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 1.5px solid ${border_light};
    border-radius: ${radius_sm}px;
    background-color: ${input_bg};
}

QCheckBox::indicator:hover {
    border-color: ${text_dim};
    background-color: ${card_hover};
}

QCheckBox::indicator:checked {
    background-color: ${success};
    border-color: ${success_dim};
    image: url("${check_svg}");
}
```

(The unchecked well moves from a filled `border_light` block to `input_bg` + border — the "themed indicator" half of the §12 bullet. `indicator:indeterminate` at ~699 stays untouched — deviation 5.)

- [ ] **Step 6: Run the covering file**

Run: `.venv\Scripts\python.exe -m pytest tests\test_gui_theme.py -q`
Expected: PASS — including the pre-existing guards (`test_template_contains_no_raw_hex`, `test_render_template_unknown_token_raises`, `test_template_renders_without_unresolved_tokens`).

- [ ] **Step 7: Full suites** — `scripts\test-fast.cmd` + `scripts\test-smoke.cmd` green, zero skips.

- [ ] **Step 8: Commit**

```bash
git add plex_renamer/gui_qt/resources/check.svg plex_renamer/gui_qt/theme.py plex_renamer/gui_qt/resources/theme.qss.tmpl tests/test_gui_theme.py
git commit -m "feat(gui): themed checkbox indicator with dpi-crisp svg check glyph"
```

---

### Task 2: Settings section cards get icon+title header rows

**Files:**
- Modify: `plex_renamer/gui_qt/widgets/_settings_tab_sections.py:24-61` (`SettingsSectionCard`) and every `SettingsSectionCard.page(...)` call site (lines ~116, 155, 184, 250, 292, 322)
- Test: `tests/test_qt_main_window.py` (extend)

**Interfaces:**
- Consumes: `_scale.icon("sm")`, `QApplication.style().standardIcon` (same idiom as `_TableEmptyState` in `_job_list_tab.py`).
- Produces: `SettingsSectionCard(title, *, icon: QStyle.StandardPixmap | None = None, parent=None)` and `SettingsSectionCard.page(title, *, icon=None)`; attributes `_header_icon: QLabel`, `_heading: QLabel`. Tasks 3-4 construct pages with icons.

- [ ] **Step 1: Write the failing test** — append to the main test class in `tests/test_qt_main_window.py` (same class that holds `test_settings_tab_has_destination_category_and_controls`):

```python
    def test_settings_section_cards_use_icon_title_header_rows(self):
        from PySide6.QtWidgets import QFrame
        from plex_renamer.gui_qt.widgets.settings_tab import SettingsTab

        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
            tab = SettingsTab(settings_service=settings)
            page = tab._destinations_page
            self.assertEqual(page._heading.text(), "Destinations")
            self.assertIsNotNone(page._header_icon.pixmap())
            self.assertFalse(page._header_icon.pixmap().isNull())
            # Spec §12: header row replaces the heading+separator hairline.
            separators = [
                child for child in page.findChildren(QFrame)
                if child.property("cssClass") == "separator"
            ]
            self.assertEqual(separators, [])
            tab.close()
```

- [ ] **Step 2: Run to verify failure** — `.venv\Scripts\python.exe -m pytest tests\test_qt_main_window.py -q`
Expected: FAIL — `AttributeError: ... has no attribute '_header_icon'`.

- [ ] **Step 3: Rebuild the card header** — in `_settings_tab_sections.py`:
  - Extend the QtWidgets import list with `QApplication` and `QStyle`.
  - Replace `SettingsSectionCard.__init__` and `page`:

```python
class SettingsSectionCard(QFrame):
    """A settings section card with an icon+title header row and content area."""

    def __init__(
        self,
        title: str,
        *,
        icon: QStyle.StandardPixmap | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("cssClass", "settings-section")

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(
            _scale.px(16),
            _scale.px(16),
            _scale.px(16),
            _scale.px(16),
        )
        self._layout.setSpacing(_scale.px(12))
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        header_row = QHBoxLayout()
        header_row.setSpacing(_scale.px(8))

        self._header_icon = QLabel()
        style = QApplication.style()
        if icon is not None and style is not None:
            self._header_icon.setPixmap(
                style.standardIcon(icon).pixmap(_scale.icon("sm"))
            )
        else:
            self._header_icon.hide()
        header_row.addWidget(self._header_icon)

        self._heading = QLabel(title)
        self._heading.setProperty("cssClass", "heading")
        header_row.addWidget(self._heading)
        header_row.addStretch()
        self._layout.addLayout(header_row)

    def add_widget(self, widget: QWidget) -> None:
        self._layout.addWidget(widget)

    def add_layout(self, layout) -> None:
        self._layout.addLayout(layout)

    @classmethod
    def page(
        cls,
        title: str,
        *,
        icon: QStyle.StandardPixmap | None = None,
    ) -> "SettingsSectionCard":
        card = cls(title, icon=icon)
        card.setProperty("sectionRole", "page")
        return card
```

    (The heading `QLabel` + `separator` `QFrame` block is gone; nothing else in the class changes. The QSS `separator` rule stays — other widgets may use it.)
  - Give every existing page its icon (six call sites):

```python
        section = SettingsSectionCard.page("Destinations", icon=QStyle.StandardPixmap.SP_DirIcon)
```
```python
        section = SettingsSectionCard.page("Display", icon=QStyle.StandardPixmap.SP_DesktopIcon)
```
```python
        section = SettingsSectionCard.page("Matching", icon=QStyle.StandardPixmap.SP_FileDialogContentsView)
```
```python
        section = SettingsSectionCard.page("API Keys", icon=QStyle.StandardPixmap.SP_DriveNetIcon)
```
```python
        section = SettingsSectionCard.page("Cache", icon=QStyle.StandardPixmap.SP_DriveHDIcon)
```
```python
        section = SettingsSectionCard.page("Data Management", icon=QStyle.StandardPixmap.SP_TrashIcon)
```

    (The Cache/Data Management pages are reshaped in Task 3; giving them icons keeps every commit coherent.)

- [ ] **Step 4: Run the covering file** — `.venv\Scripts\python.exe -m pytest tests\test_qt_main_window.py -q`
Expected: PASS — `test_settings_tab_category_page_controls_stay_top_aligned` still passes (the "Display" heading label survives inside the header row; only the hairline died).

- [ ] **Step 5: Full suites** — green, zero skips.

- [ ] **Step 6: Commit**

```bash
git add plex_renamer/gui_qt/widgets/_settings_tab_sections.py tests/test_qt_main_window.py
git commit -m "feat(gui): settings section cards swap hairline headings for icon+title header rows"
```

---

### Task 3: Destructive actions consolidate under Data — danger-outline + confirm counts

**Files:**
- Modify: `plex_renamer/gui_qt/widgets/_settings_tab_sections.py` (`build_cache_section` + `build_data_management_section` → one `build_data_section`)
- Modify: `plex_renamer/gui_qt/widgets/settings_tab.py` (nav items, section-build calls, `history_count_callback` kwarg, `_on_clear_cache` passes the box)
- Modify: `plex_renamer/gui_qt/widgets/_settings_tab_actions.py` (`clear_cache` gains confirm-with-count; `clear_history` confirm gains count)
- Modify: `plex_renamer/gui_qt/main_window.py:179` area (add `_history_count_for_settings`)
- Modify: `plex_renamer/gui_qt/_main_window_tabs.py:65-70` (wire the new callback)
- Test: `tests/test_qt_main_window.py` (adapt one, extend)

**Interfaces:**
- Consumes: Task 2's `SettingsSectionCard.page(title, icon=...)`; existing `PersistentCacheService.stats(namespace_prefix=...)` → `{"item_count": int, ...}`; existing injected `message_box_api` pattern from `clear_history`.
- Produces: `SettingsTab(..., history_count_callback: Callable[[], int] | None = None)`; coordinator signatures `clear_cache(*, message_box_api)` and `clear_history(*, message_box_api)` (unchanged name, richer prompt); builder method `build_data_section` (replaces both old builders); `MainWindow._history_count_for_settings() -> int`. Task 4 appends the Tools page after Data.

- [ ] **Step 1: Adapt + write the failing tests** — in `tests/test_qt_main_window.py`:
  - **Adapt** `test_settings_tab_cache_stats_and_clear_use_tmdb_namespace_prefix` (line ~388): the clear now confirms first. Replace the two lines `tab._on_clear_cache()` / `self._app.processEvents()` with a fake-box coordinator call that also proves the count reaches the prompt:

```python
                class _YesBox:
                    class StandardButton:
                        Yes = "yes"

                    prompts: list[str] = []

                    @classmethod
                    def question(cls, parent, title, text):
                        cls.prompts.append(text)
                        return cls.StandardButton.Yes

                tab._actions_coordinator.clear_cache(message_box_api=_YesBox)
                self._app.processEvents()
                self.assertIn("3 cached TMDB entries", _YesBox.prompts[0])
```

    (Everything else in the test — the `dropped_runtime_clients`, `"Cleared 3 TMDB cache entries."`, `"0 entries"`, the `other` namespace survivor — stays byte-identical.)
  - **Append** three new tests to the same class:

```python
    def test_settings_destructive_buttons_are_danger_outline_on_the_data_page(self):
        from plex_renamer.gui_qt.widgets.settings_tab import SettingsTab

        tab = SettingsTab()
        self.assertEqual(tab._clear_cache_btn.property("cssClass"), "danger-outline")
        self.assertEqual(tab._clear_history_btn.property("cssClass"), "danger-outline")
        nav_texts = [tab._settings_nav.item(i).text() for i in range(tab._settings_nav.count())]
        self.assertNotIn("Cache", nav_texts)
        self.assertIn("Data", nav_texts)
        self.assertEqual(tab._settings_nav.count(), tab._settings_stack.count())
        # Stats + both destructive actions live on the same (Data) page.
        data_page = tab._settings_stack.widget(nav_texts.index("Data"))
        self.assertTrue(tab._cache_stats in data_page.findChildren(type(tab._cache_stats)))
        self.assertTrue(tab._clear_history_btn in data_page.findChildren(type(tab._clear_history_btn)))
        tab.close()

    def test_clear_cache_confirm_declined_leaves_cache_intact(self):
        from plex_renamer.gui_qt.widgets.settings_tab import SettingsTab

        with TemporaryDirectory() as tmp:
            cache = PersistentCacheService(Path(tmp) / "cache.db")
            cache.put("tmdb.tv_details", "1", {"name": "Bleach"})
            tab = SettingsTab(cache_service=cache)
            try:
                class _NoBox:
                    class StandardButton:
                        Yes = "yes"

                    @classmethod
                    def question(cls, parent, title, text):
                        return "no"

                tab._actions_coordinator.clear_cache(message_box_api=_NoBox)
                self.assertTrue(cache.get("tmdb.tv_details", "1").is_hit)
                self.assertIn("1 entries", tab._cache_stats.text())
            finally:
                tab.close()

    def test_clear_history_confirm_carries_the_pending_count(self):
        from plex_renamer.gui_qt.widgets.settings_tab import SettingsTab

        cleared: list[bool] = []

        def _clear() -> tuple[int, int]:
            cleared.append(True)
            return (2, 1)

        tab = SettingsTab(
            clear_history_callback=_clear,
            history_count_callback=lambda: 2,
        )
        emitted: list[bool] = []
        tab.history_cleared.connect(lambda: emitted.append(True))

        class _YesBox:
            class StandardButton:
                Yes = "yes"

            prompts: list[str] = []

            @classmethod
            def question(cls, parent, title, text):
                cls.prompts.append(text)
                return cls.StandardButton.Yes

        tab._actions_coordinator.clear_history(message_box_api=_YesBox)
        self.assertIn("2 job history entries", _YesBox.prompts[0])
        self.assertIn("undo data", _YesBox.prompts[0])
        self.assertEqual(cleared, [True])
        self.assertEqual(tab._history_confirm.text(), "Cleared 2 history entries.")
        self.assertEqual(emitted, [True])
        tab.close()
```

- [ ] **Step 2: Run to verify failures** — `.venv\Scripts\python.exe -m pytest tests\test_qt_main_window.py -q`
Expected: FAIL — `clear_cache()` rejects the `message_box_api` kwarg; cssClass is `"secondary"`/`"danger"`; "Cache" still in the nav; `SettingsTab` rejects `history_count_callback`.

- [ ] **Step 3: Merge the pages** — in `_settings_tab_sections.py`, delete `build_cache_section` and replace `build_data_management_section` with:

```python
    def build_data_section(self) -> None:
        tab = self._tab
        section = SettingsSectionCard.page("Data", icon=QStyle.StandardPixmap.SP_TrashIcon)

        tab._cache_stats = QLabel("Cache statistics will appear here after first scan.")
        tab._cache_stats.setProperty("cssClass", "text-dim")
        section.add_widget(tab._cache_stats)

        cache_row = QHBoxLayout()
        tab._clear_cache_btn = QPushButton("Clear TMDB Cache")
        tab._clear_cache_btn.setProperty("cssClass", "danger-outline")
        tab._clear_cache_btn.setEnabled(tab._cache_service is not None)
        tab._clear_cache_btn.clicked.connect(tab._on_clear_cache)
        if tab._cache_service is None:
            tab._clear_cache_btn.setToolTip("Cache actions are not available yet.")
        cache_row.addWidget(tab._clear_cache_btn)

        tab._clear_all_btn = QPushButton("Clear All Data")
        tab._clear_all_btn.setProperty("cssClass", "danger")
        tab._clear_all_btn.hide()
        cache_row.addWidget(tab._clear_all_btn)
        cache_row.addStretch()
        section.add_layout(cache_row)

        tab._cache_confirm = QLabel("")
        tab._cache_confirm.setProperty("cssClass", "caption")
        section.add_widget(tab._cache_confirm)

        history_row = QHBoxLayout()
        tab._clear_history_btn = QPushButton("Clear Job History")
        tab._clear_history_btn.setProperty("cssClass", "danger-outline")
        tab._clear_history_btn.setEnabled(tab._clear_history_callback is not None)
        tab._clear_history_btn.clicked.connect(tab._on_clear_history)
        history_row.addWidget(tab._clear_history_btn)
        history_row.addStretch()
        section.add_layout(history_row)

        tab._history_confirm = QLabel("")
        tab._history_confirm.setProperty("cssClass", "caption")
        section.add_widget(tab._history_confirm)

        self._add_page(section)
```

    (`_clear_all_btn` keeps existing — `test_settings_tab_async_api_key_test_updates_ui_via_bridge` pins it hidden.)

- [ ] **Step 4: Rewire the tab** — in `settings_tab.py`:
  - Constructor signature gains the callback (after `clear_history_callback`):

```python
        clear_history_callback: Callable[[], tuple[int, int]] | None = None,
        history_count_callback: Callable[[], int] | None = None,
```
```python
        self._clear_history_callback = clear_history_callback
        self._history_count_callback = history_count_callback
```
  - Nav list: `addItems(["Destinations", "Display", "Matching", "API Keys", "Data"])` (Cache row gone).
  - Build calls: delete `self._build_cache_section()`; rename `self._build_data_management_section()` → `self._build_data_section()` and its method body to `self._sections_builder.build_data_section()` (delete the old `_build_cache_section` method and the `# ── Cache ──` comment block).
  - `_on_clear_cache` becomes:

```python
    def _on_clear_cache(self) -> None:
        self._actions_coordinator.clear_cache(message_box_api=QMessageBox)
```

- [ ] **Step 5: Confirm counts in the coordinator** — in `_settings_tab_actions.py`, replace `clear_history` and `clear_cache`:

```python
    def clear_history(self, *, message_box_api: Any) -> None:
        tab = self._tab
        if tab._clear_history_callback is None:
            return
        pending = (
            tab._history_count_callback()
            if tab._history_count_callback is not None
            else None
        )
        if pending == 0:
            tab._history_confirm.setProperty("tone", "success")
            tab._history_confirm.setText("History is already empty.")
            repolish_widget(tab._history_confirm)
            return
        if pending is None:
            prompt = "Delete all job history entries?"
        else:
            noun = "entry" if pending == 1 else "entries"
            prompt = f"Delete {pending} job history {noun}?"
        if message_box_api.question(
            tab,
            "Clear Job History",
            prompt + "\n\nStored undo data for revertible jobs will be lost.",
        ) != message_box_api.StandardButton.Yes:
            return

        count, _revertible = tab._clear_history_callback()
        noun = "entry" if count == 1 else "entries"
        tab._history_confirm.setProperty("tone", "success")
        tab._history_confirm.setText(f"Cleared {count} history {noun}.")
        repolish_widget(tab._history_confirm)
        tab.history_cleared.emit()
```

```python
    def clear_cache(self, *, message_box_api: Any) -> None:
        tab = self._tab
        if tab._cache_service is None:
            return
        stats = tab._cache_service.stats(namespace_prefix=_TMDB_CACHE_NAMESPACE_PREFIX)
        pending = int(stats["item_count"])
        if pending == 0:
            tab._cache_confirm.setProperty("tone", "success")
            tab._cache_confirm.setText("TMDB cache is already empty.")
            repolish_widget(tab._cache_confirm)
            return
        noun = "entry" if pending == 1 else "entries"
        if message_box_api.question(
            tab,
            "Clear TMDB Cache",
            f"Delete {pending} cached TMDB {noun}?\n\n"
            "Posters and show details will be re-fetched on the next scan.",
        ) != message_box_api.StandardButton.Yes:
            return

        removed = tab._cache_service.invalidate_namespace_prefix(_TMDB_CACHE_NAMESPACE_PREFIX)
        if tab._clear_tmdb_callback is not None:
            tab._clear_tmdb_callback()
        noun = "entry" if removed == 1 else "entries"
        tab._cache_confirm.setProperty("tone", "success")
        tab._cache_confirm.setText(f"Cleared {removed} TMDB cache {noun}.")
        repolish_widget(tab._cache_confirm)
        self.refresh_cache_stats()
```

- [ ] **Step 6: Wire the count callback** — in `main_window.py`, directly under `_clear_history_from_settings`:

```python
    def _history_count_for_settings(self) -> int:
        return len(self.queue_ctrl.get_history())
```

    and in `_main_window_tabs.py` the `SettingsTab(` construction gains:

```python
            history_count_callback=window._history_count_for_settings,
```

- [ ] **Step 7: Sweep for stale references** — run `grep -rn "build_cache_section\|_build_cache_section\|Data Management" plex_renamer tests` and fix any survivor (expected: none in `plex_renamer`; docs/plans hits are historical and stay).

- [ ] **Step 8: Run the covering file** — `.venv\Scripts\python.exe -m pytest tests\test_qt_main_window.py -q` → PASS.

- [ ] **Step 9: Full suites** — green, zero skips.

- [ ] **Step 10: Commit**

```bash
git add plex_renamer/gui_qt/widgets/_settings_tab_sections.py plex_renamer/gui_qt/widgets/settings_tab.py plex_renamer/gui_qt/widgets/_settings_tab_actions.py plex_renamer/gui_qt/main_window.py plex_renamer/gui_qt/_main_window_tabs.py tests/test_qt_main_window.py
git commit -m "feat(gui): settings destructive actions group under Data as danger-outline with confirm counts"
```

---

### Task 4: Hidden "Tools" section shell (§13 settings seam)

**Files:**
- Modify: `plex_renamer/gui_qt/widgets/_settings_tab_sections.py` (new `build_tools_section`)
- Modify: `plex_renamer/gui_qt/widgets/settings_tab.py` (nav item + build call + hide)
- Test: `tests/test_qt_main_window.py` (extend)

**Interfaces:**
- Consumes: Task 2's `SettingsSectionCard.page(title, icon=...)`; Task 3's five-item nav layout.
- Produces: `SettingsTab._tools_page` (a `SettingsSectionCard`), nav row "Tools" appended last and hidden. When mkvmerge lands, revealing is one `setHidden(False)`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_qt_main_window.py`:

```python
    def test_settings_tab_reserves_hidden_tools_section(self):
        from plex_renamer.gui_qt.widgets.settings_tab import SettingsTab

        tab = SettingsTab()
        nav = tab._settings_nav
        self.assertEqual(nav.count(), tab._settings_stack.count())
        tools_row = nav.count() - 1
        self.assertEqual(nav.item(tools_row).text(), "Tools")
        self.assertTrue(nav.item(tools_row).isHidden())      # §13: hidden until the feature lands
        # The seam is live: revealing the row selects the reserved page.
        nav.item(tools_row).setHidden(False)
        nav.setCurrentRow(tools_row)
        self.assertIs(tab._settings_stack.currentWidget(), tab._tools_page)
        self.assertEqual(tab._tools_page._heading.text(), "Tools")
        tab.close()
```

- [ ] **Step 2: Run to verify failure** — `.venv\Scripts\python.exe -m pytest tests\test_qt_main_window.py -q`
Expected: FAIL — last nav item is "Data", `_tools_page` missing.

- [ ] **Step 3: Implement** —
  - `_settings_tab_sections.py`, after `build_data_section`:

```python
    def build_tools_section(self) -> None:
        tab = self._tab
        section = SettingsSectionCard.page("Tools", icon=QStyle.StandardPixmap.SP_ComputerIcon)
        tab._tools_page = section

        placeholder = QLabel(
            "External tool integrations (mkvmerge) will appear here when the merge feature lands."
        )
        placeholder.setProperty("cssClass", "text-dim")
        placeholder.setWordWrap(True)
        section.add_widget(placeholder)

        self._add_page(section)
```

  - `settings_tab.py`: nav list becomes `["Destinations", "Display", "Matching", "API Keys", "Data", "Tools"]`; after `self._build_data_section()` add `self._build_tools_section()` (+ the one-line wrapper method beside the other `_build_*` wrappers:)

```python
    def _build_tools_section(self) -> None:
        self._sections_builder.build_tools_section()
```

    and directly after the `addItems(...)` call hide the reserved row:

```python
        tools_item = self._settings_nav.item(self._settings_nav.count() - 1)
        if tools_item is not None:
            tools_item.setHidden(True)  # §13 seam: hidden until mkvmerge lands
```

- [ ] **Step 4: Run the covering file** — `.venv\Scripts\python.exe -m pytest tests\test_qt_main_window.py -q` → PASS (Task 3's `assertNotIn("Cache", ...)` / count-parity test still green — Tools adds one row AND one page).

- [ ] **Step 5: Full suites** — green, zero skips.

- [ ] **Step 6: Commit**

```bash
git add plex_renamer/gui_qt/widgets/_settings_tab_sections.py plex_renamer/gui_qt/widgets/settings_tab.py tests/test_qt_main_window.py
git commit -m "feat(gui): settings reserves hidden Tools section (mkvmerge seam)"
```

---

### Task 5: Pin the Plan-3 expansion-card merge seams (test-only)

**Files:**
- Test: `tests/test_episode_expansion.py` (extend; add `from pathlib import Path` to its imports)

**Interfaces:**
- Consumes: `EpisodeExpansionCard.show_episode(state, row)`, `_ChipStrip._specs` (list of `ChipSpec(text, tone)`), `CompanionFile(original, new_name, file_type)` from `plex_renamer.engine`, `Assignment` from `plex_renamer.engine.episode_assignments`, the `_guide_state()` fixture from `test_episode_table_model`.
- Produces: regression pins only. **No production code.** If any of these tests fail, that is a real §13 seam defect — report it for adjudication before changing anything (the fix would live in `_episode_expansion.py`, still view-side).

- [ ] **Step 1: Write the pinning tests** — append to `EpisodeExpansionCardTests`:

```python
    def test_companion_rows_carry_type_badges(self):
        from PySide6.QtWidgets import QLabel
        from plex_renamer.engine import CompanionFile
        from plex_renamer.gui_qt.widgets._episode_expansion import EpisodeExpansionCard

        state, guide = _guide_state()
        row = guide.rows[0]
        row.companions = [
            CompanionFile(
                original=Path("C:/lib/Show/s01e01.eng.srt"),
                new_name="Show - S01E01 - One.eng.srt",
                file_type="subtitle",
            )
        ]
        card = EpisodeExpansionCard()
        card.show_episode(state, row)
        badges = [
            label.text()
            for label in card.findChildren(QLabel)
            if label.property("cssClass") == "badge"
        ]
        self.assertEqual(badges, ["SUB"])

    def test_multi_part_claims_render_part_chips(self):
        # §13 seam: today's engine marks every multi-claimed slot a conflict,
        # so this exercises the view contract under the future ROLE_VERSION
        # policy (2 claims, neither conflicted) via a stub table.
        from plex_renamer.engine.episode_assignments import Assignment
        from plex_renamer.gui_qt.widgets._episode_expansion import (
            EpisodeExpansionCard,
            _ChipStrip,
        )

        state, guide = _guide_state()

        class _VersionPolicyTable:
            def claims(self, season, episode):
                if (season, episode) == (1, 1):
                    return [
                        Assignment(file_id=1, season=1, episodes=(1,),
                                   origin="manual", confidence=1.0),
                        Assignment(file_id=2, season=1, episodes=(1,),
                                   origin="manual", confidence=1.0),
                    ]
                return []

            def conflicted_file_ids(self):
                return set()

        state.assignments = _VersionPolicyTable()
        card = EpisodeExpansionCard()
        card.show_episode(state, guide.rows[0])
        strips = card.findChildren(_ChipStrip)
        self.assertEqual(len(strips), 1)
        self.assertEqual([spec.text for spec in strips[0]._specs], ["Part 1", "Part 2"])
        self.assertEqual({spec.tone for spec in strips[0]._specs}, {"muted"})

    def test_conflicted_claims_do_not_render_part_chips(self):
        from plex_renamer.engine.episode_assignments import Assignment
        from plex_renamer.gui_qt.widgets._episode_expansion import (
            EpisodeExpansionCard,
            _ChipStrip,
        )

        state, guide = _guide_state()

        class _ConflictTable:
            def claims(self, season, episode):
                if (season, episode) == (1, 1):
                    return [
                        Assignment(file_id=1, season=1, episodes=(1,),
                                   origin="auto", confidence=0.9),
                        Assignment(file_id=2, season=1, episodes=(1,),
                                   origin="auto", confidence=0.8),
                    ]
                return []

            def conflicted_file_ids(self):
                return {1, 2}   # today's real policy: both claimants conflicted

        state.assignments = _ConflictTable()
        card = EpisodeExpansionCard()
        card.show_episode(state, guide.rows[0])
        self.assertEqual(card.findChildren(_ChipStrip), [])
```

    Add `from pathlib import Path` to the file's import block.

- [ ] **Step 2: Run them**

Run: `.venv\Scripts\python.exe -m pytest tests\test_episode_expansion.py -q`
Expected: **PASS** — these pin behavior Plan 3 landed. A failure here is a finding (a defective seam), not a test to adapt: stop and report it with the failure output before touching production code.

- [ ] **Step 3: Full suites** — green, zero skips.

- [ ] **Step 4: Commit**

```bash
git add tests/test_episode_expansion.py
git commit -m "test(gui): pin expansion-card merge seams (type badges, part chips, conflict guard)"
```

---

### Task 6: Verification + bookkeeping (controller)

**Files:**
- Modify: `docs/superpowers/plans/2026-07-03-gui-v4-implementation.md`, `docs/superpowers/plans/2026-07-03-gui-v4-handoff.md`

- [ ] **Step 1: Full suites** — `scripts\test-fast.cmd` + `scripts\test-smoke.cmd` → pass, zero new skips; skim `.pytest_cache/smoke/latest.log`.

- [ ] **Step 2: Visual sanity** — throwaway offscreen grab script (scratchpad; `QT_QPA_PLATFORM=offscreen`, `QT_QPA_FONTDIR=C:\Windows\Fonts`, real app QSS via `theme.load_stylesheet()`). Grabs: (a) Settings **Display** page with one checkbox checked and one unchecked — the SVG check glyph must be visible inside the checked well (this is the §12 headline; also eyeball combo + both sliders); (b) Settings **Data** page — icon+title header, stats line, two danger-outline buttons; (c) Settings nav — five visible rows, then `tools_item.setHidden(False)` + select and grab the revealed **Tools** page; (d) `EpisodeExpansionCard` with a SUB-badged companion row, the disabled `Merge…` button, and (via the Task 5 stub table) the "Part 1 · Part 2" chip strip. Sample grab pixels on a full-width/height grid (corners + midpoints — sparse scenes false-flag as blank otherwise), assert parentage while grabbing (no stray visible top-levels — Plan 3's lesson), and give any job-store fixtures distinct `tmdb_id`s (dedupe constraint). Keep the script in the scratchpad only.

- [ ] **Step 3: Update roadmap + handoff, commit** — roadmap row 8 → Landed (commit range); handoff status/current + "next step: write Plan 9 (final pass — DPI 100/150/200% visual pass, real-library validation, string/perf sweep re-run, spec §18)" + session log entry; carry forward the still-deferred items (Plan 6 minors M1-M6 — none taken this plan; Plan 5 carried items; Plan 7 leftovers incl. the `history_tab.py` `QWidget` import, the "(1 files)" season label, and the clipped "No Job Selected" hint; this plan's recorded deviations 1-7, esp. the latent Part-chips policy and the merged Cache→Data nav).

```bash
git add docs/superpowers/plans
git commit -m "docs: mark GUI V4 plan 8 landed; next up plan 9 (final pass)"
```

---

## Self-review notes (kept for the record)

- **Spec §12 coverage:** themed checkbox indicator + DPI-crisp glyph → Task 1 (SVG rasterized at DPR; unchecked well moves to `input_bg`); combo/slider/input restyle → deviation 1 (landed Plan 1, verified at `theme.qss.tmpl:585-707`); section cards `radius_lg` → already true (`settings-section` rule), header row (icon + title) replacing heading+hairline → Task 2; destructive actions under "Data" as danger-outline with confirm counts → Task 3 (cache count from `stats()["item_count"]` pre-clear; history count via the additive `history_count_callback`; zero-count paths short-circuit with a caption instead of a dialog); reserved hidden Tools shell → Task 4.
- **Spec §13 coverage:** Settings Tools seam → Task 4; expanded-row Files/badges/Merge…/Part-chips → landed Plan 3, pinned in Task 5 (deviation 2, latent-policy note in deviation 7); queue grouping → landed Plan 7 (deviation 3); data seam → design-level only, no code by spec text; out-of-scope items (invocation/queueing/persisted fields) remain out.
- **Guard interactions:** the SVG uses `stroke="white"` (named color) so `test_template_contains_no_raw_hex` and `test_no_hex_literals_outside_theme_module` stay meaningful and Task 1's new test additionally pins the asset hex-free; `${check_svg}` joins `_mapping()` so `test_render_template_unknown_token_raises` (strict `substitute`) and `test_template_renders_without_unresolved_tokens` keep passing; "mkvmerge"/"Tools" strings contain no "Plex" (AST guard unaffected).
- **Offscreen-modal discipline:** every confirm path keeps the injected `message_box_api`; the adapted cache test and both new confirm tests use fake box classes — nothing calls a real `QMessageBox` under offscreen (Plan 4's hang lesson).
- **Type-consistency pass:** `SettingsSectionCard(title, *, icon, parent)` + `page(title, *, icon)` defined Task 2, consumed Tasks 3-4 (`build_data_section`, `build_tools_section`); `clear_cache(*, message_box_api)` defined Task 3, called by `_on_clear_cache` with `QMessageBox` and by tests with fakes; `history_count_callback` stored as `self._history_count_callback`, read in `clear_history`, wired in `_main_window_tabs.py` to `_history_count_for_settings` (defined Task 3 Step 6); `_tools_page` set by the builder (Task 4) and read by its test; `ChipSpec.text`/`.tone` field names verified against `status_chip.py:27-30`; `Assignment(file_id, season, episodes, origin, confidence)` matches `episode_assignments.py:81-92`; `CompanionFile(original, new_name, file_type)` matches `engine/models.py:58-60`.
- **Known test-plumbing risks:** `test_settings_tab_async_api_key_test_updates_ui_via_bridge` pins `_clear_cache_btn.text()` and hidden `_clear_all_btn`/`_advanced_group` — the Data merge keeps all three attributes alive (the advanced group stays a constructed, never-added hidden orphan; out of scope to remove); `test_settings_tab_category_page_controls_stay_top_aligned` reads the "Display" heading label — it survives inside the header row; nothing in the suite pins nav count or the "Cache" text (verified: only `count >= 1` and `item(0) == "Destinations"`).
- **Nav/stack index discipline:** nav rows and stack pages are appended in the same order in one place (`settings_tab.py`); Tasks 3-4 keep them in lockstep (5 visible + hidden Tools ↔ 6 pages) and the Task 4 test pins `nav.count() == stack.count()` permanently.
