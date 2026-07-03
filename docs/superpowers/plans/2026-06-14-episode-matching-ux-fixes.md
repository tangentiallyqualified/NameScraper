# Episode Matching UX Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix four episode-matching UX defects — missing specials not rendering, Approve All not recategorizing/checking the show, the cramped two-scrollbar assignment modal, and Reassign pre-checking the current episode.

**Architecture:** Three layers change. (1) `EpisodeMappingService` (pure service) — include specials in the missing-episode rows. (2) `MediaWorkspaceActionCoordinator` (GUI orchestration) — re-sync the roster via `refresh_from_controller()` after episode mutations, and auto-check after Approve All. (3) `EpisodeAssignDialog` (Qt widget) — rewrite around a collapsible `QTreeWidget` with DPI-aware sizing, a single scrollbar, and a caller-supplied `current_keys` tag; update the two callers in the action coordinator.

**Tech Stack:** Python 3, PySide6 (Qt), pytest + unittest, `plex_renamer.gui_qt._scale` for all sizing.

**Spec:** `docs/superpowers/specs/2026-06-14-episode-matching-ux-fixes-design.md`

**Commits:** This repo publishes via `scripts/git-publish.cmd` with chat-approved messages (see `docs/ai-publish-workflow.md`). Each commit message ends with the `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` trailer. The `git commit -m` lines below show the subject only — append the trailer when committing.

**Run tests:** Prefer `python -m pytest -q <path>` for unit/service tests; for the Qt smoke suite use `scripts/test-smoke.cmd` (writes full output to `.pytest_cache/smoke/latest.log`). Qt tests run headless via `QT_QPA_PLATFORM=offscreen` (set automatically by `conftest_qt`).

---

## File Structure

Files changed by this plan:

- `plex_renamer/app/services/episode_mapping_service.py` — Task 1. `_missing_episode_rows` appends specials.
- `tests/test_episode_mapping_projection.py` — Task 1 test.
- `plex_renamer/gui_qt/widgets/_media_workspace_actions.py` — Tasks 2 & 4. Roster re-sync + auto-check; Reassign/Assign-to-more selection.
- `plex_renamer/gui_qt/widgets/episode_assign_dialog.py` — Task 3. Full rewrite to a collapsible, DPI-sized tree.
- `tests/test_qt_media_workspace.py` — Tasks 2, 3, 4 tests (classes `QtMediaWorkspaceTests` and `TestEpisodeAssignDialog`).

No new files. No data-model changes.

---

## Task 1: Render missing specials (Issue #4)

**Files:**
- Modify: `plex_renamer/app/services/episode_mapping_service.py` (method `_missing_episode_rows`, ~lines 376-389)
- Test: `tests/test_episode_mapping_projection.py` (class `EpisodeMappingProjectionTests`)

- [ ] **Step 1: Write the failing test**

Add this method to `EpisodeMappingProjectionTests` in `tests/test_episode_mapping_projection.py`:

```python
    def test_missing_specials_render_alongside_missing_regular_episodes(self):
        completeness = CompletenessReport(
            seasons={
                1: SeasonCompleteness(
                    season=1,
                    expected=2,
                    matched=1,
                    missing=[(2, "Second")],
                    matched_episodes=[(1, "Pilot")],
                )
            },
            specials=SeasonCompleteness(
                season=0,
                expected=2,
                matched=1,
                missing=[(2, "Holiday Special")],
                matched_episodes=[(1, "Pilot Special")],
            ),
            total_expected=2,
            total_matched=1,
            total_missing=[(1, 2, "Second")],
        )
        state = ScanState(
            folder=Path("C:/library/tv/Show"),
            media_info={"id": 10, "name": "Show", "year": "2024"},
            preview_items=[_preview("Show.S01E01.mkv")],
            completeness=completeness,
            scanned=True,
        )

        guide = self.service.build_episode_guide(state)

        missing_keys = {
            (row.season, row.episode)
            for row in guide.rows
            if row.status == "Missing File"
        }
        self.assertIn((1, 2), missing_keys)
        self.assertIn((0, 2), missing_keys)
        self.assertEqual(guide.summary.missing_episodes, 2)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest -q tests/test_episode_mapping_projection.py::EpisodeMappingProjectionTests::test_missing_specials_render_alongside_missing_regular_episodes`
Expected: FAIL — `(0, 2)` not in `missing_keys` (the early `return list(completeness.total_missing)` drops specials).

- [ ] **Step 3: Implement the fix**

In `plex_renamer/app/services/episode_mapping_service.py`, replace the body of `_missing_episode_rows`:

```python
    @staticmethod
    def _missing_episode_rows(state: ScanState) -> list[tuple[int, int, str]]:
        completeness = state.completeness
        if completeness is None:
            return []
        # total_missing covers regular seasons only (specials are excluded from
        # the completeness %); always append specials so missing S0 rows render.
        rows: list[tuple[int, int, str]] = list(completeness.total_missing)
        if completeness.specials is not None:
            rows.extend(
                (0, episode, title)
                for episode, title in completeness.specials.missing
            )
        return rows
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest -q tests/test_episode_mapping_projection.py`
Expected: PASS (new test plus the existing projection tests stay green).

- [ ] **Step 5: Commit**

```bash
git add plex_renamer/app/services/episode_mapping_service.py tests/test_episode_mapping_projection.py
git commit -m "fix: render missing specials in the episode guide"
```

---

## Task 2: Approve All recategorizes + auto-checks; single-row actions re-sync (Issue #2)

**Files:**
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_actions.py` (method `approve_all_episode_mappings` ~lines 121-148; end of `handle_episode_row_action` ~lines 263-267; add helper `_auto_check_for_queue`)
- Test: `tests/test_qt_media_workspace.py` (class `QtMediaWorkspaceTests`)

- [ ] **Step 1: Write the failing test**

Add this method to `QtMediaWorkspaceTests` in `tests/test_qt_media_workspace.py` (it reuses the existing `_make_episode_table_state` / `_make_fake_media_ctrl` helpers on that class):

```python
    def test_approve_all_recategorizes_and_auto_checks_show(self):
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace
        from plex_renamer.gui_qt.widgets._media_helpers import (
            is_state_queue_approvable,
            roster_group,
        )

        # _make_episode_table_state assigns the only file at confidence 0.5,
        # so the show starts under "review-episodes".
        state, _table, _file_id = self._make_episode_table_state()
        workspace = MediaWorkspace(
            media_type="tv",
            media_controller=self._make_fake_media_ctrl(state),
        )
        workspace.show_ready()

        self.assertEqual(roster_group(state, media_type="tv"), "review-episodes")
        self.assertFalse(is_state_queue_approvable(state, media_type="tv"))

        workspace._approve_all_episode_mappings()
        self._app.processEvents()

        self.assertEqual(roster_group(state, media_type="tv"), "matched")
        self.assertTrue(is_state_queue_approvable(state, media_type="tv"))
        self.assertTrue(state.checked)

        workspace.close()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest -q tests/test_qt_media_workspace.py::QtMediaWorkspaceTests::test_approve_all_recategorizes_and_auto_checks_show`
Expected: FAIL — `state.checked` is False (Approve All never auto-checks; roster is not re-synced).

- [ ] **Step 3: Add the auto-check helper**

In `plex_renamer/gui_qt/widgets/_media_workspace_actions.py`, add this method to `MediaWorkspaceActionCoordinator` (place it directly above `approve_all_episode_mappings`):

```python
    def _auto_check_for_queue(self, state: ScanState) -> None:
        """Pre-tick a show for queueing after Approve All.

        Sets every actionable item's check binding and the state-level checked
        flag. refresh_from_controller's normalize_queue_selection keeps these
        when the state is queue-approvable, or clears them if a conflict or
        unmapped file still blocks it (the show then stays in review).
        """
        workspace = self._workspace
        workspace._ensure_check_bindings(state)
        for index, item in enumerate(state.preview_items):
            binding = state.check_vars.get(str(index))
            if binding is not None and item.is_actionable:
                binding.set(True)
        state.checked = True
```

- [ ] **Step 4: Re-sync + auto-check in `approve_all_episode_mappings`**

Replace the tail of `approve_all_episode_mappings` (the block from `workspace._ensure_check_bindings(state)` through the `status_message.emit`) with:

```python
        _refresh_episode_projection(workspace, state)
        self._auto_check_for_queue(state)
        workspace.refresh_from_controller()
        workspace.status_message.emit(f"Approved {count} episode mapping(s).", 3000)
```

(The earlier part of the method — selecting the state, calling `service.approve_all(state)` or the legacy status mutation, and the `count == 0` early returns — is unchanged.)

- [ ] **Step 5: Re-sync after single-row actions in `handle_episode_row_action`**

At the end of `handle_episode_row_action`, replace:

```python
        workspace._ensure_check_bindings(state)
        _refresh_episode_projection(workspace, state)
        workspace._populate_preview(state)
        workspace._update_action_bar()
        workspace.status_message.emit(message, 3000)
```

with:

```python
        _refresh_episode_projection(workspace, state)
        workspace.refresh_from_controller()
        workspace.status_message.emit(message, 3000)
```

(No auto-check here — single-row actions only keep the roster grouping and checkbox state accurate. `refresh_from_controller` calls `ensure_check_bindings`, `_populate_preview`, and `_update_action_bar` internally.)

- [ ] **Step 6: Run the test to verify it passes**

Run: `python -m pytest -q tests/test_qt_media_workspace.py::QtMediaWorkspaceTests::test_approve_all_recategorizes_and_auto_checks_show`
Expected: PASS.

- [ ] **Step 7: Run the row-action regression tests**

Run: `python -m pytest -q tests/test_qt_media_workspace.py -k "episode_row_action or approve_all or assign_file"`
Expected: PASS (existing unassign/reassign/assign_file/keep_this dispatch tests still pass with the added `refresh_from_controller`).

- [ ] **Step 8: Commit**

```bash
git add plex_renamer/gui_qt/widgets/_media_workspace_actions.py tests/test_qt_media_workspace.py
git commit -m "fix: recategorize and auto-check shows after Approve All"
```

---

## Task 3: Collapsible, DPI-aware assignment dialog with `current_keys` (Issues #3 & #1 dialog-side)

**Files:**
- Modify (full rewrite): `plex_renamer/gui_qt/widgets/episode_assign_dialog.py`
- Test: `tests/test_qt_media_workspace.py` (class `TestEpisodeAssignDialog`)

- [ ] **Step 1: Write the failing tests**

Add these methods to `TestEpisodeAssignDialog` in `tests/test_qt_media_workspace.py`:

```python
    def test_current_slot_tagged_current_not_claimed(self):
        slots = [
            EpisodeSlotChoice(season=2, episode=5, title="Goodbye", claimed_by="file.mkv"),
        ]
        dialog = EpisodeAssignDialog(slots=slots, current_keys={(2, 5)})
        text = dialog.slot_row_text(2, 5)
        self.assertIn("[current]", text)
        self.assertNotIn("claimed by", text)
        dialog.close()

    def test_focus_season_expanded_others_collapsed(self):
        slots = [
            EpisodeSlotChoice(season=0, episode=1, title="Special"),
            EpisodeSlotChoice(season=1, episode=1, title="Pilot"),
            EpisodeSlotChoice(season=2, episode=5, title="Goodbye"),
        ]
        dialog = EpisodeAssignDialog(slots=slots, current_keys={(2, 5)})
        self.assertTrue(dialog.is_season_expanded(2))
        self.assertFalse(dialog.is_season_expanded(0))
        self.assertFalse(dialog.is_season_expanded(1))
        dialog.close()

    def test_preselected_keys_start_checked(self):
        dialog = EpisodeAssignDialog(slots=_slot_choices(), preselected=[(1, 2)])
        self.assertEqual(dialog.selected_episodes(), [(1, 2)])
        dialog.close()

    def test_dialog_is_dpi_sized_with_no_horizontal_scrollbar(self):
        from plex_renamer.gui_qt import _scale

        dialog = EpisodeAssignDialog(slots=_slot_choices())
        self.assertGreaterEqual(dialog.minimumWidth(), _scale.px(460))
        self.assertGreaterEqual(dialog.minimumHeight(), _scale.px(420))
        self.assertGreaterEqual(dialog.width(), dialog.minimumWidth())
        self.assertEqual(
            dialog._tree.horizontalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        )
        dialog.close()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest -q "tests/test_qt_media_workspace.py::TestEpisodeAssignDialog"`
Expected: FAIL — `current_keys` is not a constructor argument; `is_season_expanded` and `_tree` do not exist.

- [ ] **Step 3: Rewrite the dialog**

Replace the entire contents of `plex_renamer/gui_qt/widgets/episode_assign_dialog.py` with:

```python
"""Episode assignment dialog: multi-select slots or pick a file.

Both directions of the fix flow share this module:
  - ``EpisodeAssignDialog`` (file -> episodes, multi-select, contiguity-gated)
  - ``EpisodeAssignDialog.pick_file`` (episode -> file, single-select)

Season groups are collapsible (``QTreeWidget``). All sizing flows through
gui_qt._scale (HiDPI requirement); long rows elide (no horizontal scrollbar).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from .. import _scale
from ...app.models.state_models import EpisodeSlotChoice

_SLOT_ROLE = Qt.ItemDataRole.UserRole
_MIN_W = 460
_MIN_H = 420


def _dialog_size() -> tuple[int, int]:
    """Comfortable, DPI-aware (width, height) capped to the screen."""
    min_w, min_h = _scale.px(_MIN_W), _scale.px(_MIN_H)
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return min_w, min_h
    avail = screen.availableGeometry()
    width = min(int(avail.width() * 0.5), _scale.px(620))
    height = min(int(avail.height() * 0.6), _scale.px(640))
    return max(width, min_w), max(height, min_h)


def _season_header(season: int, count: int) -> str:
    label = "Specials" if season == 0 else f"Season {season:02d}"
    return f"{label} ({count})"


def _configure_tree(tree: QTreeWidget) -> None:
    tree.setColumnCount(1)
    tree.setHeaderHidden(True)
    tree.setUniformRowHeights(True)
    tree.setIndentation(_scale.px(12))
    tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    tree.setTextElideMode(Qt.TextElideMode.ElideMiddle)


def _file_name_label(file_label: str, parent) -> QLabel:
    label = QLabel(parent)
    label.setProperty("cssClass", "caption")
    label.setToolTip(file_label)
    metrics = label.fontMetrics()
    label.setText(
        metrics.elidedText(file_label, Qt.TextElideMode.ElideMiddle, _scale.px(560))
    )
    return label


class EpisodeAssignDialog(QDialog):
    """Season-grouped, collapsible multi-select episode picker."""

    def __init__(
        self,
        *,
        slots: list[EpisodeSlotChoice],
        parent=None,
        title: str = "Assign Episodes",
        file_label: str = "",
        current_keys: set[tuple[int, int]] | None = None,
        preselected: list[tuple[int, int]] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        current = set(current_keys or set())
        preselect = set(preselected or set())

        self.setMinimumSize(_scale.px(_MIN_W), _scale.px(_MIN_H))
        width, height = _dialog_size()
        self.resize(width, height)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(_scale.margins(12))
        layout.setSpacing(_scale.px(6))

        instruction = QLabel(
            "Assign this file to one or more contiguous episodes:", self
        )
        instruction.setWordWrap(True)
        layout.addWidget(instruction)
        if file_label:
            layout.addWidget(_file_name_label(file_label, self))

        self._tree = QTreeWidget(self)
        _configure_tree(self._tree)

        seasons: dict[int, list[EpisodeSlotChoice]] = {}
        for choice in slots:
            seasons.setdefault(choice.season, []).append(choice)

        # Expand the seasons holding a preselected/current key; if none, expand all.
        focus = {season for season, _episode in (preselect | current)}
        expand_all = not focus

        self._season_items: dict[int, QTreeWidgetItem] = {}
        self._leaf_items: list[QTreeWidgetItem] = []
        for season in sorted(seasons):
            choices = seasons[season]
            parent_item = QTreeWidgetItem([_season_header(season, len(choices))])
            parent_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            parent_item.setData(0, _SLOT_ROLE, None)
            self._tree.addTopLevelItem(parent_item)
            parent_item.setExpanded(expand_all or season in focus)
            self._season_items[season] = parent_item
            for choice in choices:
                key = (choice.season, choice.episode)
                if key in current:
                    suffix = "[current]"
                elif choice.claimed_by:
                    suffix = f"[claimed by {choice.claimed_by}]"
                else:
                    suffix = "[missing]"
                text = f"{choice.label}    {suffix}"
                leaf = QTreeWidgetItem([text])
                leaf.setFlags(
                    Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsUserCheckable
                )
                leaf.setData(0, _SLOT_ROLE, key)
                leaf.setToolTip(0, text)
                leaf.setCheckState(
                    0,
                    Qt.CheckState.Checked
                    if key in preselect
                    else Qt.CheckState.Unchecked,
                )
                parent_item.addChild(leaf)
                self._leaf_items.append(leaf)

        self._tree.itemChanged.connect(lambda *_args: self._revalidate())
        layout.addWidget(self._tree, stretch=1)

        self._validation = QLabel("", self)
        self._validation.setProperty("cssClass", "caption")
        self._validation.setWordWrap(True)
        layout.addWidget(self._validation)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)
        self._revalidate()

    # ── selection state ─────────────────────────────────────────────

    def _checked_keys(self) -> list[tuple[int, int]]:
        keys: list[tuple[int, int]] = []
        for leaf in self._leaf_items:
            key = leaf.data(0, _SLOT_ROLE)
            if key is not None and leaf.checkState(0) == Qt.CheckState.Checked:
                keys.append(tuple(key))
        return sorted(keys)

    def selected_episodes(self) -> list[tuple[int, int]]:
        return self._checked_keys()

    def set_checked(self, keys: list[tuple[int, int]]) -> None:
        wanted = set(keys)
        for leaf in self._leaf_items:
            key = leaf.data(0, _SLOT_ROLE)
            if key is None:
                continue
            leaf.setCheckState(
                0,
                Qt.CheckState.Checked
                if tuple(key) in wanted
                else Qt.CheckState.Unchecked,
            )
        self._revalidate()

    def is_season_expanded(self, season: int) -> bool:
        item = self._season_items.get(season)
        return bool(item is not None and item.isExpanded())

    def _validate(self) -> str:
        keys = self._checked_keys()
        if not keys:
            return "Select at least one episode."
        seasons = {season for season, _episode in keys}
        if len(seasons) > 1:
            return "All selected episodes must be in the same season."
        episodes = [episode for _season, episode in keys]
        if any(b - a != 1 for a, b in zip(episodes, episodes[1:])):
            return "Selected episodes must be a contiguous run."
        return ""

    def is_selection_valid(self) -> bool:
        return self._validate() == ""

    def validation_text(self) -> str:
        return self._validation.text()

    def slot_row_text(self, season: int, episode: int) -> str:
        for leaf in self._leaf_items:
            if leaf.data(0, _SLOT_ROLE) == (season, episode):
                return leaf.text(0)
        return ""

    def _revalidate(self) -> None:
        message = self._validate()
        self._validation.setText(message)
        ok = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok is not None:
            ok.setEnabled(message == "")

    # ── entry points ────────────────────────────────────────────────

    @classmethod
    def pick_episodes(
        cls,
        *,
        parent,
        title: str,
        slots: list[EpisodeSlotChoice],
        preselected: list[tuple[int, int]] | None = None,
        current_keys: set[tuple[int, int]] | None = None,
        file_label: str = "",
    ) -> list[tuple[int, int]] | None:
        dialog = cls(
            slots=slots,
            parent=parent,
            title=title,
            file_label=file_label,
            current_keys=current_keys,
            preselected=preselected,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        selection = dialog.selected_episodes()
        return selection or None

    @staticmethod
    def pick_file(
        *,
        parent,
        title: str,
        unassigned: list[tuple[int, str]],
        assigned: list[tuple[int, str]],
        shareable: list[tuple[int, str]] | None = None,
    ) -> int | None:
        """Single-select file picker; returns the chosen file_id."""
        dialog = QDialog(parent)
        dialog.setWindowTitle(title)
        dialog.setMinimumSize(_scale.px(_MIN_W), _scale.px(_MIN_H))
        width, height = _dialog_size()
        dialog.resize(width, height)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(_scale.margins(12))
        layout.setSpacing(_scale.px(6))

        tree = QTreeWidget(dialog)
        _configure_tree(tree)

        def add_group(header_text: str, entries: list[tuple[int, str]]) -> None:
            if not entries:
                return
            group = QTreeWidgetItem([f"{header_text} ({len(entries)})"])
            group.setFlags(Qt.ItemFlag.ItemIsEnabled)
            group.setData(0, _SLOT_ROLE, None)
            tree.addTopLevelItem(group)
            group.setExpanded(True)
            for file_id, label in entries:
                leaf = QTreeWidgetItem([label])
                leaf.setFlags(
                    Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                )
                leaf.setData(0, _SLOT_ROLE, file_id)
                leaf.setToolTip(0, label)
                group.addChild(leaf)

        add_group("Unassigned files", unassigned)
        add_group("Share / extend (keeps current episode)", shareable or [])
        add_group("Already assigned (will be reassigned)", assigned)

        def _accept_if_file(item: QTreeWidgetItem, _column: int) -> None:
            if item is not None and item.data(0, _SLOT_ROLE) is not None:
                dialog.accept()

        tree.itemDoubleClicked.connect(_accept_if_file)
        layout.addWidget(tree, stretch=1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)

        def _update_ok() -> None:
            current = tree.currentItem()
            enabled = current is not None and current.data(0, _SLOT_ROLE) is not None
            if ok_btn is not None:
                ok_btn.setEnabled(enabled)

        tree.currentItemChanged.connect(lambda _cur, _prev: _update_ok())
        _update_ok()

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        item = tree.currentItem()
        if item is None:
            return None
        file_id = item.data(0, _SLOT_ROLE)
        return int(file_id) if file_id is not None else None
```

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `python -m pytest -q "tests/test_qt_media_workspace.py::TestEpisodeAssignDialog"`
Expected: PASS (new tests plus the 5 existing dialog tests — contiguous/non-contiguous/cross-season/claimant/selected — stay green, since the public API is preserved).

- [ ] **Step 5: Commit**

```bash
git add plex_renamer/gui_qt/widgets/episode_assign_dialog.py tests/test_qt_media_workspace.py
git commit -m "feat: redesign episode-assign dialog with collapsible seasons"
```

---

## Task 4: Reassign opens empty; Assign-to-more pre-checks current run (Issue #1 caller-side)

**Files:**
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_actions.py` (`handle_episode_row_action`, the `reassign` branch ~lines 177-198 and the `assign_to_more` branch ~lines 199-223)
- Test: `tests/test_qt_media_workspace.py` (class `QtMediaWorkspaceTests`)

- [ ] **Step 1: Write the failing tests**

Add these methods to `QtMediaWorkspaceTests` in `tests/test_qt_media_workspace.py`:

```python
    def test_reassign_opens_empty_with_current_tagged(self):
        from plex_renamer.app.models.state_models import EpisodeGuideRow
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        state, _table, file_id = self._make_episode_table_state()
        workspace = MediaWorkspace(
            media_type="tv",
            media_controller=self._make_fake_media_ctrl(state),
        )
        workspace.show_ready()

        preview = next(p for p in state.preview_items if p.file_id == file_id)
        row = EpisodeGuideRow(season=1, episode=1, title="Pilot", primary_file=preview)

        captured: dict = {}

        class _CapturingDialog:
            @staticmethod
            def pick_episodes(**kwargs):
                captured.update(kwargs)
                return None  # cancel

        workspace._action_coordinator.handle_episode_row_action(
            state, row, "reassign", assign_dialog=_CapturingDialog,
        )

        self.assertIsNone(captured.get("preselected"))
        self.assertEqual(set(captured.get("current_keys") or set()), {(1, 1)})
        workspace.close()

    def test_assign_to_more_preselects_current_run(self):
        from plex_renamer.app.models.state_models import EpisodeGuideRow
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        # _make_episode_table_state has slots E01 and E02; the file is at E01.
        state, _table, file_id = self._make_episode_table_state()
        workspace = MediaWorkspace(
            media_type="tv",
            media_controller=self._make_fake_media_ctrl(state),
        )
        workspace.show_ready()

        preview = next(p for p in state.preview_items if p.file_id == file_id)
        row = EpisodeGuideRow(season=1, episode=1, title="Pilot", primary_file=preview)

        captured: dict = {}

        class _CapturingDialog:
            @staticmethod
            def pick_episodes(**kwargs):
                captured.update(kwargs)
                return None  # cancel

        workspace._action_coordinator.handle_episode_row_action(
            state, row, "assign_to_more", assign_dialog=_CapturingDialog,
        )

        self.assertEqual(set(captured.get("preselected") or set()), {(1, 1)})
        self.assertEqual(set(captured.get("current_keys") or set()), {(1, 1)})
        slot_keys = {(c.season, c.episode) for c in captured.get("slots", [])}
        self.assertIn((1, 1), slot_keys)
        self.assertIn((1, 2), slot_keys)
        workspace.close()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest -q tests/test_qt_media_workspace.py -k "reassign_opens_empty or assign_to_more_preselects"`
Expected: FAIL — current `reassign` passes a non-None `preselected` and no `current_keys`; current `assign_to_more` passes neither `preselected` nor `current_keys` and offers neighbor-only slots (so `(1, 1)` is missing from `slots`).

- [ ] **Step 3: Rewrite the `reassign` branch**

In `plex_renamer/gui_qt/widgets/_media_workspace_actions.py`, replace the `reassign` branch of `handle_episode_row_action`:

```python
            elif action_id == "reassign" and preview is not None:
                slots = service.episode_slot_choices(state)
                if not slots:
                    workspace.status_message.emit("No episode choices are available.", 4000)
                    return
                current_keys = {
                    (preview.season, episode)
                    for episode in preview.episodes
                    if preview.season is not None
                }
                selection = assign_dialog.pick_episodes(
                    parent=workspace,
                    title="Reassign Episode",
                    slots=slots,
                    preselected=None,
                    current_keys=current_keys or None,
                    file_label=preview.original.name,
                )
                if selection is None:
                    return
                season = selection[0][0]
                episodes = [episode for _season, episode in selection]
                service.assign_file(state, preview, season=season, episodes=episodes)
                message = "Episode mapping updated."
```

- [ ] **Step 4: Rewrite the `assign_to_more` branch**

Replace the `assign_to_more` branch of `handle_episode_row_action`:

```python
            elif action_id == "assign_to_more" and preview is not None:
                if preview.season is None or not preview.episodes:
                    return
                season = preview.season
                run = sorted(preview.episodes)
                relevant = set(run) | {run[0] - 1, run[-1] + 1}
                slots = [
                    choice for choice in service.episode_slot_choices(state)
                    if choice.season == season and choice.episode in relevant
                ]
                # slots always includes the run itself; need a neighbor to extend into.
                if len(slots) <= len(run):
                    workspace.status_message.emit(
                        "No adjacent episode to extend into.", 4000,
                    )
                    return
                current_keys = {(season, episode) for episode in run}
                selection = assign_dialog.pick_episodes(
                    parent=workspace,
                    title="Assign to More Episodes",
                    slots=slots,
                    preselected=[(season, episode) for episode in run],
                    current_keys=current_keys,
                    file_label=preview.original.name,
                )
                if selection is None:
                    return
                episodes = sorted(set(run) | {episode for _season, episode in selection})
                service.assign_file(state, preview, season=season, episodes=episodes)
                message = "File extended to additional episode(s)."
```

- [ ] **Step 5: Run the new tests to verify they pass**

Run: `python -m pytest -q tests/test_qt_media_workspace.py -k "reassign_opens_empty or assign_to_more_preselects"`
Expected: PASS.

- [ ] **Step 6: Run the reassign regression test**

Run: `python -m pytest -q "tests/test_qt_media_workspace.py::QtMediaWorkspaceTests::test_episode_row_action_reassign_calls_dialog_and_moves_file"`
Expected: PASS (the stub returns `[(1, 2)]`; the file still moves to episode 2).

- [ ] **Step 7: Commit**

```bash
git add plex_renamer/gui_qt/widgets/_media_workspace_actions.py tests/test_qt_media_workspace.py
git commit -m "fix: reassign opens empty; assign-to-more pre-checks current run"
```

---

## Task 5: Full verification

**Files:** none (verification only).

- [ ] **Step 1: Run the full unit suite**

Run: `python -m pytest -q`
Expected: PASS (no regressions across engine, services, and Qt tests).

- [ ] **Step 2: Run the Qt smoke harness**

Run: `scripts/test-smoke.cmd`
Expected: Summary reports success; exit code 0. Full log at `.pytest_cache/smoke/latest.log`.

- [ ] **Step 3: Manual spot-check (optional but recommended)**

Launch the app, open a multi-season TV show that has both missing specials and missing regular episodes, and confirm:
- The center panel shows a *Specials* section with the missing special row(s) (Issue #4).
- *Approve All* moves the show out of *Review Episode Matching* and ticks its roster checkbox (Issue #2).
- *Reassign* on a mapped episode opens the dialog with nothing checked, only the file's season expanded, and the current slot tagged `[current]`; *Assign to more…* opens with the current run checked (Issue #1).
- The dialog opens at a comfortable size with a single (vertical) scrollbar and collapsible season headers (Issue #3).

---

## Self-Review

**Spec coverage:**
- Issue 4 (Part A1) → Task 1. ✓
- Issue 2 (Parts B1, B2) → Task 2 (approve-all auto-check + roster re-sync; single-row re-sync). ✓
- Issue 3 (Parts D1, D2) → Task 3 (QTreeWidget collapsible, focus expansion, single scrollbar, DPI sizing; both `pick_episodes` and `pick_file`). ✓
- Issue 1 (Parts C1, C2) → Task 3 (dialog `current_keys`/expansion) + Task 4 (caller reassign/assign-to-more). ✓

**Type/name consistency:** `current_keys` is a `set[tuple[int, int]]` everywhere; callers pass `current_keys or None` (reassign) / a non-empty set (assign-to-more), and the dialog normalizes with `set(current_keys or set())`. `preselected` stays `list[tuple[int, int]] | None`. `pick_episodes` / `pick_file` / `set_checked` / `selected_episodes` / `is_selection_valid` / `validation_text` / `slot_row_text` signatures are preserved; `is_season_expanded` and `_tree` are the only new public-ish surface (used by tests). `_auto_check_for_queue` is the only new coordinator method.

**Placeholder scan:** No TBD/TODO; every code step shows complete code; every run step shows the command and expected result.
