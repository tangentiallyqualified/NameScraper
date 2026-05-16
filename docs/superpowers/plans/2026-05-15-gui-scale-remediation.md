# GUI Scale Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate hardcoded pixel values in the PySide6 GUI by introducing a central scaling helper (`plex_renamer/gui_qt/_scale.py`) and converting the Critical-list literals identified in the 2026-05-15 code review (window sizes, fixed dialogs/cards, poster widgets, button heights, sticky header). Configure HiDPI rounding policy at app startup so fractional scales (125%/150%) render cleanly.

**Architecture:**
- Introduce a single module `plex_renamer/gui_qt/_scale.py` that exposes `px(n)`, `row_height(rows=1, padding=0)`, `icon(token)`, and `margins(*tokens)` helpers. `px()` converts logical grid units (intended to match the QSS 4px grid) into physical pixels using `QGuiApplication.primaryScreen().logicalDotsPerInch() / 96.0` so the same code renders consistent visual sizes regardless of per-monitor DPI.
- Set `Qt.HighDpiScaleFactorRoundingPolicy.PassThrough` before `QApplication` is constructed in `plex_renamer/gui_qt/app.py` so fractional scales are not snapped.
- Convert Critical-list call sites to use the helpers. Each conversion is a small, independent edit verified by an existing or new Qt smoke test.

**Tech Stack:** Python 3.11, PySide6 (Qt 6), pytest + `tests/conftest_qt.py` (offscreen `QApplication`), `scripts/test-smoke.cmd` Windows wrapper.

**Scope notes:**
- This plan covers Critical-severity findings only — Important and Minor items (theme.qss px values, settings tab widths, toast manager sizes, margins/spacing sweep) are explicitly deferred to follow-on plans.
- Test infrastructure runs `QT_QPA_PLATFORM=offscreen` at DPR=1, so tests verify *call patterns* (that scale helpers are used) and *invariants* (sizes scale linearly with the helper), not specific pixel counts.

---

## File Structure

**Create:**
- `plex_renamer/gui_qt/_scale.py` — central scale helper module (~120 lines)
- `tests/test_qt_scale.py` — unit tests for the helper

**Modify (Critical list from review):**
- `plex_renamer/gui_qt/app.py` — set HiDPI rounding policy before `QApplication()`
- `plex_renamer/gui_qt/main_window.py:67` — `setMinimumSize`
- `plex_renamer/gui_qt/_main_window_shell.py:85` — `window.resize(1440, 900)`
- `plex_renamer/gui_qt/widgets/empty_state.py:121,134` — drop-zone fixed size, folder icon size
- `plex_renamer/gui_qt/widgets/scan_progress.py:69,91,96,114,126,146` — card width, progress bar height, count label width, separator height, phase icon width, cancel button width
- `plex_renamer/gui_qt/widgets/_workspace_widget_primitives.py:30,212,224` — `_INDICATOR_SIZE`, shimmer height, mini progress bar fixed size
- `plex_renamer/gui_qt/widgets/_workspace_widgets.py:123,213,377,509,523,530,549` — poster QSize, confidence width, approve/fix button heights, row height literals
- `plex_renamer/gui_qt/widgets/_media_workspace_lifecycle.py:46` — roster icon QSize
- `plex_renamer/gui_qt/widgets/_media_workspace_ui.py:148` — detail panel min width
- `plex_renamer/gui_qt/widgets/_media_workspace_preview.py:856-858` — sticky header fixed height
- `plex_renamer/gui_qt/widgets/job_detail_panel.py:181,199,237` — poster fixed size and column widths
- `plex_renamer/gui_qt/widgets/media_detail_panel.py:89-90` — `_PORTRAIT_ARTWORK_SIZE`, `_LANDSCAPE_ARTWORK_SIZE`
- `plex_renamer/gui_qt/widgets/match_picker_dialog.py:49` — dialog `resize(520, 520)`

---

## Task 1: Create the `_scale.py` helper module

**Files:**
- Create: `plex_renamer/gui_qt/_scale.py`
- Test: `tests/test_qt_scale.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_qt_scale.py`:
```python
"""Unit tests for the gui_qt scaling helper."""
from __future__ import annotations

import importlib.util
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@unittest.skipUnless(importlib.util.find_spec("PySide6"), "PySide6 is not installed")
class ScaleHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def test_px_is_linear_in_input(self):
        from plex_renamer.gui_qt import _scale

        eight = _scale.px(8)
        sixteen = _scale.px(16)
        self.assertGreater(eight, 0)
        self.assertEqual(sixteen, eight * 2)

    def test_px_zero_returns_zero(self):
        from plex_renamer.gui_qt import _scale

        self.assertEqual(_scale.px(0), 0)

    def test_px_negative_propagates_sign(self):
        from plex_renamer.gui_qt import _scale

        self.assertEqual(_scale.px(-8), -_scale.px(8))

    def test_row_height_uses_font_metrics(self):
        from PySide6.QtGui import QFont, QFontMetrics
        from plex_renamer.gui_qt import _scale

        expected_single = QFontMetrics(QFont()).lineSpacing()
        self.assertGreaterEqual(_scale.row_height(rows=1, padding=0), expected_single)
        self.assertEqual(
            _scale.row_height(rows=2, padding=0),
            _scale.row_height(rows=1, padding=0) * 2,
        )

    def test_row_height_padding_adds(self):
        from plex_renamer.gui_qt import _scale

        bare = _scale.row_height(rows=1, padding=0)
        padded = _scale.row_height(rows=1, padding=8)
        self.assertEqual(padded, bare + _scale.px(8))

    def test_icon_tokens_return_qsize(self):
        from PySide6.QtCore import QSize
        from plex_renamer.gui_qt import _scale

        for token in ("sm", "md", "lg", "xl"):
            size = _scale.icon(token)
            self.assertIsInstance(size, QSize)
            self.assertGreater(size.width(), 0)
            self.assertEqual(size.width(), size.height())

    def test_icon_lg_is_larger_than_sm(self):
        from plex_renamer.gui_qt import _scale

        self.assertGreater(_scale.icon("lg").width(), _scale.icon("sm").width())

    def test_icon_unknown_token_raises(self):
        from plex_renamer.gui_qt import _scale

        with self.assertRaises(KeyError):
            _scale.icon("titanic")

    def test_margins_scales_each_value(self):
        from PySide6.QtCore import QMargins
        from plex_renamer.gui_qt import _scale

        m = _scale.margins(8, 12, 8, 12)
        self.assertIsInstance(m, QMargins)
        self.assertEqual(m.left(), _scale.px(8))
        self.assertEqual(m.top(), _scale.px(12))
        self.assertEqual(m.right(), _scale.px(8))
        self.assertEqual(m.bottom(), _scale.px(12))

    def test_margins_single_value_uniform(self):
        from plex_renamer.gui_qt import _scale

        m = _scale.margins(8)
        self.assertEqual(m.left(), m.top())
        self.assertEqual(m.top(), m.right())
        self.assertEqual(m.right(), m.bottom())
        self.assertEqual(m.left(), _scale.px(8))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_qt_scale.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'plex_renamer.gui_qt._scale'`

- [ ] **Step 3: Implement the helper**

`plex_renamer/gui_qt/_scale.py`:
```python
"""Centralized scale helpers for the PySide6 GUI.

All sizing constants in widget code should flow through this module rather
than appearing as bare integer literals.  ``px(n)`` converts logical 4px-grid
values into physical pixels using the primary screen's logical DPI; the
returned values match the visual sizes intended by the original literals when
the screen is at 96 DPI (100% scale) and grow proportionally on HiDPI.

Tokens:
    px(n)              -> int       physical pixels for a logical grid unit
    row_height(rows,   -> int       font-metric-derived row height in physical
                padding)            pixels, with optional padding (in grid units)
    icon(token)        -> QSize     named icon sizes ("sm"=16, "md"=24, "lg"=32, "xl"=48)
    margins(*tokens)   -> QMargins  1, 2, or 4 grid-unit tokens
"""
from __future__ import annotations

from typing import Mapping

from PySide6.QtCore import QMargins, QSize
from PySide6.QtGui import QFont, QFontMetrics, QGuiApplication

_LOGICAL_DPI_BASE = 96.0

_ICON_TOKENS: Mapping[str, int] = {
    "sm": 16,
    "md": 24,
    "lg": 32,
    "xl": 48,
}


def _dpi_scale() -> float:
    screen = QGuiApplication.primaryScreen() if QGuiApplication.instance() else None
    if screen is None:
        return 1.0
    dpi = screen.logicalDotsPerInch()
    if dpi <= 0:
        return 1.0
    return dpi / _LOGICAL_DPI_BASE


def px(n: int) -> int:
    """Convert logical 4px-grid units to physical pixels."""
    if n == 0:
        return 0
    return int(round(n * _dpi_scale()))


def row_height(rows: int = 1, padding: int = 0) -> int:
    """Return a row height derived from the application font's line spacing.

    ``rows`` is a multiplier; ``padding`` is in grid units (passed through ``px``).
    """
    metrics = QFontMetrics(QFont())
    return metrics.lineSpacing() * max(1, rows) + px(padding)


def icon(token: str) -> QSize:
    """Return a named, DPI-scaled icon size as a ``QSize``."""
    base = _ICON_TOKENS[token]
    side = px(base)
    return QSize(side, side)


def margins(*tokens: int) -> QMargins:
    """Build a ``QMargins`` from 1, 2, or 4 grid-unit tokens.

    - ``margins(8)``               -> uniform 8 on all sides
    - ``margins(8, 12)``           -> vertical 8, horizontal 12
    - ``margins(l, t, r, b)``      -> left, top, right, bottom
    """
    if len(tokens) == 1:
        v = px(tokens[0])
        return QMargins(v, v, v, v)
    if len(tokens) == 2:
        vert = px(tokens[0])
        horz = px(tokens[1])
        return QMargins(horz, vert, horz, vert)
    if len(tokens) == 4:
        return QMargins(px(tokens[0]), px(tokens[1]), px(tokens[2]), px(tokens[3]))
    raise ValueError(f"margins() expects 1, 2, or 4 tokens; got {len(tokens)}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_qt_scale.py -v`
Expected: PASS, 10 tests.

- [ ] **Step 5: Commit**

```bash
git add plex_renamer/gui_qt/_scale.py tests/test_qt_scale.py
git commit -m "Add gui_qt _scale module for DPI-aware sizing"
```

---

## Task 2: Set HiDPI rounding policy at QApplication startup

**Files:**
- Modify: `plex_renamer/gui_qt/app.py:117-130` (the `run()` function before `QApplication(sys.argv)`)

The fractional-scale rounding gap from the review: `Qt.HighDpiScaleFactorRoundingPolicy.PassThrough` must be set *before* the `QApplication` is constructed, otherwise it has no effect.

- [ ] **Step 1: Verify nothing currently sets the policy**

Run: `python -c "import ast, pathlib; [print(p) for p in pathlib.Path('plex_renamer').rglob('*.py') if 'HighDpiScaleFactorRoundingPolicy' in p.read_text(encoding='utf-8')]"`
Expected: no output (no existing call sites).

- [ ] **Step 2: Modify `plex_renamer/gui_qt/app.py`**

Replace the body of `run()` from the start through `app = QApplication(sys.argv)` so the rounding policy is set first.

Find the existing block at `plex_renamer/gui_qt/app.py:117-130`:
```python
def run() -> None:
    """Create the QApplication, main window, and enter the event loop."""
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        _log.error(
            "PySide6 is not installed.  Install with:  pip install plex-renamer[qt]"
        )
        sys.exit(1)

    from .main_window import MainWindow

    app = QApplication(sys.argv)
```

Replace with:
```python
def run() -> None:
    """Create the QApplication, main window, and enter the event loop."""
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtWidgets import QApplication
    except ImportError:
        _log.error(
            "PySide6 is not installed.  Install with:  pip install plex-renamer[qt]"
        )
        sys.exit(1)

    from .main_window import MainWindow

    # Must be called BEFORE QApplication is constructed; ensures fractional
    # screen scales (125%, 150%) are not snapped to the nearest integer.
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
```

- [ ] **Step 3: Run the Qt smoke suite**

Run: `scripts/test-smoke.cmd`
Expected: exit code 0; the smoke runner reuses an existing `QApplication.instance()` so the policy call is a no-op in tests, but the app still boots.

- [ ] **Step 4: Commit**

```bash
git add plex_renamer/gui_qt/app.py
git commit -m "Set HiDPI PassThrough rounding policy before QApplication"
```

---

## Task 3: Convert main window startup sizes

**Files:**
- Modify: `plex_renamer/gui_qt/main_window.py:67`
- Modify: `plex_renamer/gui_qt/_main_window_shell.py:85`
- Test: extend `tests/test_qt_main_window.py` with a regression assertion

- [ ] **Step 1: Write the failing test**

Find an appropriate test class in `tests/test_qt_main_window.py` (it uses `QtSmokeBase`). Add a new test method:
```python
    def test_main_window_minimum_size_scales_with_helper(self):
        from plex_renamer.gui_qt import _scale
        from plex_renamer.gui_qt.main_window import MainWindow

        window = self._make_window(MainWindow)
        # MainWindow.setMinimumSize(960, 600) historically.  Now scaled via _scale.px().
        self.assertEqual(window.minimumWidth(), _scale.px(960))
        self.assertEqual(window.minimumHeight(), _scale.px(600))
```

If `tests/test_qt_main_window.py` does not already expose a `_make_window` helper, use whichever pattern the existing tests use to construct the window (search the file for `MainWindow(` and copy the construction). Place this new test next to existing geometry-related tests.

- [ ] **Step 2: Run test to verify failure**

Run: `python -m pytest tests/test_qt_main_window.py -k minimum_size_scales -v`
Expected: FAIL — `minimumWidth()` returns `960`, helper returns `_scale.px(960)` which on offscreen DPR=1 is also `960`, so on `QT_QPA_PLATFORM=offscreen` this test *will pass* without the change. To make it a real regression check, also assert that the call site uses `_scale` — skip the assertion approach and instead use a source-level check:

Replace the test body with:
```python
    def test_main_window_minimum_size_uses_scale_helper(self):
        from pathlib import Path

        source = Path(
            "plex_renamer/gui_qt/main_window.py"
        ).read_text(encoding="utf-8")
        self.assertIn("_scale.px(960)", source)
        self.assertIn("_scale.px(600)", source)
        self.assertNotIn("setMinimumSize(960, 600)", source)
```

Run again. Expected: FAIL — source still contains `setMinimumSize(960, 600)`.

- [ ] **Step 3: Modify `plex_renamer/gui_qt/main_window.py`**

At the top of the file, add the import after the existing relative imports:
```python
from . import _scale
```

Replace line 67:
```python
        self.setMinimumSize(960, 600)
```
with:
```python
        self.setMinimumSize(_scale.px(960), _scale.px(600))
```

- [ ] **Step 4: Add the same source-level test for the shell coordinator**

In the same `tests/test_qt_main_window.py` file (or `tests/test_qt_workspace_widgets.py` — whichever already tests `_main_window_shell`), add:
```python
    def test_main_window_shell_resize_uses_scale_helper(self):
        from pathlib import Path

        source = Path(
            "plex_renamer/gui_qt/_main_window_shell.py"
        ).read_text(encoding="utf-8")
        self.assertIn("_scale.px(1440)", source)
        self.assertIn("_scale.px(900)", source)
        self.assertNotIn("window.resize(1440, 900)", source)
```

Run: `python -m pytest tests/test_qt_main_window.py -k scale_helper -v`
Expected: the new shell test FAILS.

- [ ] **Step 5: Modify `plex_renamer/gui_qt/_main_window_shell.py`**

At the top of the file (after existing imports), add:
```python
from . import _scale
```

Find line 85:
```python
        window.resize(1440, 900)
```
Replace with:
```python
        window.resize(_scale.px(1440), _scale.px(900))
```

- [ ] **Step 6: Run all main-window tests**

Run: `python -m pytest tests/test_qt_main_window.py -v`
Expected: PASS, including the two new source-level tests.

- [ ] **Step 7: Commit**

```bash
git add plex_renamer/gui_qt/main_window.py plex_renamer/gui_qt/_main_window_shell.py tests/test_qt_main_window.py
git commit -m "Scale main window startup and minimum sizes"
```

---

## Task 4: Convert empty_state and scan_progress fixed sizes

**Files:**
- Modify: `plex_renamer/gui_qt/widgets/empty_state.py:121,134`
- Modify: `plex_renamer/gui_qt/widgets/scan_progress.py:69,91,96,114,126,146`
- Test: `tests/test_qt_workspace_widgets.py` (or add `tests/test_qt_empty_state.py` if no fitting file exists — check first)

- [ ] **Step 1: Write the failing source-level tests**

Add to `tests/test_qt_workspace_widgets.py` (or a new file if none fit):
```python
    def test_empty_state_uses_scale_helper(self):
        from pathlib import Path

        source = Path(
            "plex_renamer/gui_qt/widgets/empty_state.py"
        ).read_text(encoding="utf-8")
        self.assertIn("_scale", source)
        self.assertNotIn("setFixedSize(360, 220)", source)
        self.assertNotIn("QSize(48, 48)", source)

    def test_scan_progress_uses_scale_helper(self):
        from pathlib import Path

        source = Path(
            "plex_renamer/gui_qt/widgets/scan_progress.py"
        ).read_text(encoding="utf-8")
        self.assertIn("_scale", source)
        for literal in (
            "setFixedWidth(480)",
            "setFixedHeight(8)",
            "setFixedWidth(56)",
            "setFixedHeight(1)",
            "setFixedWidth(16)",
            "setFixedWidth(100)",
        ):
            self.assertNotIn(literal, source)
```

- [ ] **Step 2: Run tests to confirm failure**

Run: `python -m pytest tests/test_qt_workspace_widgets.py -k "uses_scale_helper" -v`
Expected: both new tests FAIL.

- [ ] **Step 3: Modify `plex_renamer/gui_qt/widgets/empty_state.py`**

Add at the top (with other intra-package imports):
```python
from .. import _scale
```

Replace line 121:
```python
        self.setFixedSize(360, 220)
```
with:
```python
        self.setFixedSize(_scale.px(360), _scale.px(220))
```

Replace line 134:
```python
            icon_label.setPixmap(folder_icon.pixmap(QSize(48, 48)))
```
with:
```python
            icon_label.setPixmap(folder_icon.pixmap(_scale.icon("xl")))
```

(`xl` token is 48 grid units — matches the original visual size exactly.)

- [ ] **Step 4: Modify `plex_renamer/gui_qt/widgets/scan_progress.py`**

Add at the top:
```python
from .. import _scale
```

Replace each literal:
- Line 69: `card.setFixedWidth(480)` → `card.setFixedWidth(_scale.px(480))`
- Line 72: `card_layout.setContentsMargins(32, 24, 32, 24)` → `card_layout.setContentsMargins(_scale.margins(24, 32))` then call `.left()/.top()/.right()/.bottom()` — but `setContentsMargins` accepts ints. Use: `card_layout.setContentsMargins(_scale.px(32), _scale.px(24), _scale.px(32), _scale.px(24))`
- Line 91: `self._progress_bar.setFixedHeight(8)` → `self._progress_bar.setFixedHeight(_scale.px(8))`
- Line 96: `self._count_label.setFixedWidth(56)` → `self._count_label.setFixedWidth(_scale.px(56))`
- Line 114: `sep.setFixedHeight(1)` → `sep.setFixedHeight(_scale.px(1))` (px(1) preserves a hairline; on HiDPI this becomes 2px which is the correct visual hairline)
- Line 126: `icon.setFixedWidth(16)` → `icon.setFixedWidth(_scale.px(16))`
- Line 146: `self._cancel_btn.setFixedWidth(100)` → `self._cancel_btn.setFixedWidth(_scale.px(100))`

- [ ] **Step 5: Run tests**

Run: `scripts/test-smoke.cmd` (covers Qt smoke including the workspace widget tests).
Expected: exit code 0.

Run: `python -m pytest tests/test_qt_workspace_widgets.py -v`
Expected: PASS, including the new `uses_scale_helper` tests.

- [ ] **Step 6: Commit**

```bash
git add plex_renamer/gui_qt/widgets/empty_state.py plex_renamer/gui_qt/widgets/scan_progress.py tests/test_qt_workspace_widgets.py
git commit -m "Scale empty state and scan progress widget sizes"
```

---

## Task 5: Convert workspace widget primitives

**Files:**
- Modify: `plex_renamer/gui_qt/widgets/_workspace_widget_primitives.py:30,212,224`

The `_INDICATOR_SIZE = 18` class constant is referenced inside `MasterCheckBox.sizeHint()` and the painter. Other class-level constants in this file (`_RADIUS`, color tuples) are not pixel sizes and stay.

- [ ] **Step 1: Read the full file to confirm all hardcoded sizes**

Run: `python -m pytest tests/test_qt_workspace_widgets.py -v` first to confirm a green baseline.

- [ ] **Step 2: Write source-level test**

Append to `tests/test_qt_workspace_widgets.py`:
```python
    def test_workspace_widget_primitives_use_scale_helper(self):
        from pathlib import Path

        source = Path(
            "plex_renamer/gui_qt/widgets/_workspace_widget_primitives.py"
        ).read_text(encoding="utf-8")
        self.assertIn("_scale", source)
        # _INDICATOR_SIZE = 18 must no longer be a bare literal
        self.assertNotIn("_INDICATOR_SIZE = 18", source)
```

Run the test. Expected: FAIL.

- [ ] **Step 3: Modify the primitives module**

Add at the top:
```python
from .. import _scale
```

Replace the class-level constant at line 30:
```python
    _INDICATOR_SIZE = 18
```
with a class-level property pattern — class constants cannot call `_scale.px()` at import time because `QGuiApplication` may not exist yet. Use a class attribute initialized lazily:
```python
    _INDICATOR_GRID_UNITS = 18

    @property
    def _INDICATOR_SIZE(self) -> int:  # noqa: N802 — preserves original API
        return _scale.px(self._INDICATOR_GRID_UNITS)
```

Verify every reference to `self._INDICATOR_SIZE` in the file still works (it does — `sizeHint()` uses `self._INDICATOR_SIZE` and the painter uses `self._INDICATOR_SIZE`, both via instance access).

For lines 212 and 224 (shimmer/mini-progress widgets later in the file), read those sections and convert the literals there using the same pattern. Specifically:
- Look for `setFixedHeight(4)` and `QSize(120, 4)` (shimmer / mini progress bar). Replace with `setFixedHeight(_scale.px(4))` and `QSize(_scale.px(120), _scale.px(4))`.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_qt_workspace_widgets.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plex_renamer/gui_qt/widgets/_workspace_widget_primitives.py tests/test_qt_workspace_widgets.py
git commit -m "Scale workspace widget primitive sizes"
```

---

## Task 6: Convert _workspace_widgets poster/confidence/button sizes

**Files:**
- Modify: `plex_renamer/gui_qt/widgets/_workspace_widgets.py` (lines ~123, 213, 377, 509, 523, 530, 549)

The compact/non-compact split at line 123 — `QSize(34, 50) if compact else QSize(48, 70)` — is a visual variant, not a scale axis. Keep the conditional but wrap each side in `_scale.px()`.

- [ ] **Step 1: Read the file to find all targeted lines**

Read `plex_renamer/gui_qt/widgets/_workspace_widgets.py`. Identify every `setFixed*` / `QSize(` literal in production paths. The known set from the review:
- Line ~123: `QSize(34, 50) if compact else QSize(48, 70)` (poster)
- Line ~213: roster icon size (similar conditional)
- Line ~377: another fixed width (confidence column, ~96)
- Line ~509: `self._confidence.setFixedWidth(96)`
- Line ~523: `self._approve_button.setFixedHeight(24)`
- Line ~530: `self._fix_button.setFixedHeight(24)`
- Line ~549: `self.setFixedHeight(self._row_height)` — `_row_height` is computed by `_preferred_row_height()`; convert *that* method to derive from `_scale.row_height()` rather than hardcoding.

Also note line 133 uses `layout.setContentsMargins(8, 8, 8, 8)` and `layout.setSpacing(8)` — those are MARGINS/SPACING and explicitly deferred to a later plan. Do NOT change them in this task.

- [ ] **Step 2: Write source-level test**

Append to `tests/test_qt_workspace_widgets.py`:
```python
    def test_workspace_widgets_use_scale_helper(self):
        from pathlib import Path

        source = Path(
            "plex_renamer/gui_qt/widgets/_workspace_widgets.py"
        ).read_text(encoding="utf-8")
        self.assertIn("_scale", source)
        for literal in (
            "setFixedWidth(96)",
            "setFixedHeight(24)",
            "QSize(34, 50)",
            "QSize(48, 70)",
        ):
            self.assertNotIn(literal, source)
```

Run. Expected: FAIL.

- [ ] **Step 3: Modify `_workspace_widgets.py`**

Add at the top:
```python
from .. import _scale
```

For the conditional poster size at line ~123:
```python
        self._poster_size = QSize(34, 50) if compact else QSize(48, 70)
```
Replace with:
```python
        self._poster_size = (
            QSize(_scale.px(34), _scale.px(50))
            if compact
            else QSize(_scale.px(48), _scale.px(70))
        )
```

For confidence width at line ~509:
```python
        self._confidence.setFixedWidth(96)
```
Replace with:
```python
        self._confidence.setFixedWidth(_scale.px(96))
```

For approve/fix button heights at lines ~523, ~530:
```python
        self._approve_button.setFixedHeight(24)
```
→ Use `_scale.row_height(rows=1, padding=2)` instead of a hardcoded value, because button heights must scale with font size, not just DPI. Replace with:
```python
        self._approve_button.setFixedHeight(_scale.row_height(rows=1, padding=2))
```
Apply the same change to `self._fix_button.setFixedHeight(24)`.

For the `_preferred_row_height` helper (find with grep), if it returns hardcoded integers based on `show_actions`, replace those literals with `_scale.row_height(rows=N, padding=K)` calls. If you cannot identify how the method computes its return value with confidence, leave the helper unchanged and only convert the `setFixedHeight(self._row_height)` call site — `_row_height` is now expected to be a `_scale.row_height(...)` result.

For line ~213 (roster icon QSize variant): apply the same conditional-wrap pattern as line ~123.

For line ~377 (other fixed width): wrap in `_scale.px(...)`.

- [ ] **Step 4: Run the Qt smoke suite**

Run: `scripts/test-smoke.cmd`
Expected: exit code 0.

Run: `python -m pytest tests/test_qt_workspace_widgets.py tests/test_qt_media_workspace.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plex_renamer/gui_qt/widgets/_workspace_widgets.py tests/test_qt_workspace_widgets.py
git commit -m "Scale workspace widget poster, confidence, and button sizes"
```

---

## Task 7: Convert job_detail_panel and media_detail_panel sizes

**Files:**
- Modify: `plex_renamer/gui_qt/widgets/job_detail_panel.py:181,199,237`
- Modify: `plex_renamer/gui_qt/widgets/media_detail_panel.py:89-90,392`
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_lifecycle.py:46`
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_ui.py:148`

- [ ] **Step 1: Write source-level tests**

Append to `tests/test_qt_workspace_widgets.py` (or split into the matching `tests/test_qt_*` files — `test_qt_job_detail_panel.py` and `test_qt_media_detail_panel.py` exist):
```python
# In tests/test_qt_job_detail_panel.py:
    def test_job_detail_panel_uses_scale_helper(self):
        from pathlib import Path

        source = Path(
            "plex_renamer/gui_qt/widgets/job_detail_panel.py"
        ).read_text(encoding="utf-8")
        self.assertIn("_scale", source)
        for literal in ("setMinimumWidth(400)", "setMaximumWidth(380)", "setFixedSize(160, 240)"):
            self.assertNotIn(literal, source)

# In tests/test_qt_media_detail_panel.py:
    def test_media_detail_panel_uses_scale_helper(self):
        from pathlib import Path

        source = Path(
            "plex_renamer/gui_qt/widgets/media_detail_panel.py"
        ).read_text(encoding="utf-8")
        self.assertIn("_scale", source)
        for literal in ("QSize(148, 222)", "QSize(220, 124)"):
            self.assertNotIn(literal, source)
```

Run both. Expected: FAIL.

- [ ] **Step 2: Modify `plex_renamer/gui_qt/widgets/job_detail_panel.py`**

Add at the top:
```python
from .. import _scale
```

At line 181:
```python
        self.setMinimumWidth(400)
```
→
```python
        self.setMinimumWidth(_scale.px(400))
```

At line 199:
```python
        ...setMaximumWidth(380)
```
→ wrap in `_scale.px(380)`.

At line 237:
```python
        self._poster.setFixedSize(160, 240)
```
→
```python
        self._poster.setFixedSize(_scale.px(160), _scale.px(240))
```

- [ ] **Step 3: Modify `plex_renamer/gui_qt/widgets/media_detail_panel.py`**

These are class-level constants (lines 89-90):
```python
    _PORTRAIT_ARTWORK_SIZE = QSize(148, 222)
    _LANDSCAPE_ARTWORK_SIZE = QSize(220, 124)
```

Class constants cannot call `_scale.px()` at module import (no QApplication yet). Convert to lazy methods on the class. Add at the top:
```python
from .. import _scale
```

Replace the two class constants with grid-unit constants plus methods:
```python
    _PORTRAIT_ARTWORK_GRID = (148, 222)
    _LANDSCAPE_ARTWORK_GRID = (220, 124)

    @classmethod
    def _portrait_artwork_size(cls) -> QSize:
        return QSize(_scale.px(cls._PORTRAIT_ARTWORK_GRID[0]), _scale.px(cls._PORTRAIT_ARTWORK_GRID[1]))

    @classmethod
    def _landscape_artwork_size(cls) -> QSize:
        return QSize(_scale.px(cls._LANDSCAPE_ARTWORK_GRID[0]), _scale.px(cls._LANDSCAPE_ARTWORK_GRID[1]))
```

Then find every reference to `_PORTRAIT_ARTWORK_SIZE` / `_LANDSCAPE_ARTWORK_SIZE` in the file (grep within the file) and replace with `self._portrait_artwork_size()` / `self._landscape_artwork_size()` (or `cls.` for classmethods).

- [ ] **Step 4: Modify `_media_workspace_lifecycle.py` and `_media_workspace_ui.py`**

`_media_workspace_lifecycle.py:46` — the roster icon `QSize(32, 46) if compact else QSize(42, 60)` — apply the same conditional-wrap pattern as Task 6 (add `from .. import _scale`, wrap each int in `_scale.px(...)`).

`_media_workspace_ui.py:148` — `setMinimumWidth(340)` → `setMinimumWidth(_scale.px(340))`. Add the `_scale` import.

- [ ] **Step 5: Run tests**

Run: `scripts/test-smoke.cmd`
Expected: exit code 0.

Run: `python -m pytest tests/test_qt_job_detail_panel.py tests/test_qt_media_detail_panel.py tests/test_qt_media_workspace.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add plex_renamer/gui_qt/widgets/job_detail_panel.py plex_renamer/gui_qt/widgets/media_detail_panel.py plex_renamer/gui_qt/widgets/_media_workspace_lifecycle.py plex_renamer/gui_qt/widgets/_media_workspace_ui.py tests/test_qt_job_detail_panel.py tests/test_qt_media_detail_panel.py
git commit -m "Scale detail panel and roster icon sizes"
```

---

## Task 8: Convert remaining Critical sites (match picker, preview sticky header)

**Files:**
- Modify: `plex_renamer/gui_qt/widgets/match_picker_dialog.py:49`
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_preview.py:856-858`

- [ ] **Step 1: Write source-level tests**

Add to `tests/test_qt_workspace_widgets.py`:
```python
    def test_match_picker_dialog_uses_scale_helper(self):
        from pathlib import Path

        source = Path(
            "plex_renamer/gui_qt/widgets/match_picker_dialog.py"
        ).read_text(encoding="utf-8")
        self.assertIn("_scale", source)
        self.assertNotIn("resize(520, 520)", source)

    def test_media_workspace_preview_sticky_header_uses_scale_helper(self):
        from pathlib import Path

        source = Path(
            "plex_renamer/gui_qt/widgets/_media_workspace_preview.py"
        ).read_text(encoding="utf-8")
        self.assertIn("_scale", source)
        self.assertNotIn("setFixedHeight(30)", source)
```

Run. Expected: FAIL.

- [ ] **Step 2: Modify `match_picker_dialog.py`**

Add at the top:
```python
from .. import _scale
```

At line 49:
```python
        self.resize(520, 520)
```
→
```python
        self.resize(_scale.px(520), _scale.px(520))
```

- [ ] **Step 3: Modify `_media_workspace_preview.py`**

Add at the top:
```python
from .. import _scale
```

At lines 856-858 (sticky header):
```python
            sticky_header.setFixedWidth(viewport.width())
            sticky_header.setFixedHeight(30)
            sticky_header.move(0, 0)
```
The width is already dynamic (`viewport.width()`). Only the height needs scaling. Replace `setFixedHeight(30)` with:
```python
            sticky_header.setFixedHeight(_scale.row_height(rows=1, padding=2))
```

(This derives from font metrics — the correct pattern for header rows that must read text.)

- [ ] **Step 4: Run tests**

Run: `scripts/test-smoke.cmd`
Expected: exit code 0.

Run: `python -m pytest tests/test_qt_workspace_widgets.py tests/test_qt_media_workspace.py -v`
Expected: PASS.

- [ ] **Step 5: Final sweep — verify no Critical-list literal remains**

Run from a fresh PowerShell session:
```powershell
$patterns = @(
    'setMinimumSize\(960, 600\)',
    'resize\(1440, 900\)',
    'setFixedSize\(360, 220\)',
    'QSize\(48, 48\)',
    'setFixedWidth\(480\)',
    'setFixedWidth\(56\)',
    'setFixedWidth\(100\)',
    'setFixedWidth\(96\)',
    'setFixedHeight\(24\)',
    'QSize\(34, 50\)',
    'QSize\(48, 70\)',
    'setMinimumWidth\(400\)',
    'setMaximumWidth\(380\)',
    'setFixedSize\(160, 240\)',
    'QSize\(148, 222\)',
    'QSize\(220, 124\)',
    'setMinimumWidth\(340\)',
    'QSize\(32, 46\)',
    'QSize\(42, 60\)',
    'resize\(520, 520\)',
    'setFixedHeight\(30\)'
)
foreach ($p in $patterns) {
    $hits = Select-String -Path plex_renamer\gui_qt\**\*.py -Pattern $p
    if ($hits) { Write-Output "STILL PRESENT: $p"; $hits }
}
```
Expected: no "STILL PRESENT" lines.

- [ ] **Step 6: Commit**

```bash
git add plex_renamer/gui_qt/widgets/match_picker_dialog.py plex_renamer/gui_qt/widgets/_media_workspace_preview.py tests/test_qt_workspace_widgets.py
git commit -m "Scale match picker dialog and preview sticky header"
```

---

## Out of scope (deferred to follow-on plans)

- The 132 `*px` literals in `plex_renamer/gui_qt/resources/theme.qss` — needs a QSS preprocessor pass at theme load time.
- `setContentsMargins` / `setSpacing` literals across ~18 files (~55 sites) — large-but-mechanical sweep.
- `_settings_tab_sections.py` widths (Important severity, ~10 sites).
- `toast_manager.py` close button / progress strip / toast width literals.
- Tab badge indicator pip, `_media_helpers.py:340` header row sizeHint, `_media_workspace_preview.py:922` padding-of-6 literal.

These will be addressed in a separate plan once the Critical list is verified working on real HiDPI hardware.
