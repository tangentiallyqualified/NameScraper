# GUI V4 Plan 6 — Toasts + Loading Screen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the toast card (clamp/expand/copy/sticky/hover-pause on theme QSS) and the scanning progress screen (poster-card conveyor + phase stepper + single-source status lines + filler quips), and close Plan 5's deferred async-polish items (guide-failure error row, loading footer, queue-failure wording, bulk-toolbar gating).

**Architecture:** All changes are view-layer only. `toast_manager.py` and `scan_progress.py` keep their public APIs and are rebuilt internally (spec §16). The async guide pipeline gains a failure path through the existing `_GuideBridge` (new `guide_failed` signal), reusing the section-label row pattern that `scan_error` states already use. No new files except one new test module.

**Tech Stack:** PySide6 (QPainter widgets, QSS via `theme.qss.tmpl` tokens), existing `_scale.px` sizing, existing thread-pool bridge pattern.

## Global Constraints

- No engine/controller/service behavior changes (spec §16); the only service-layer edit permitted by this plan is **additive signals on the GUI-side `_GuideBridge`** (which lives in `gui_qt`, not the service layer).
- All colors through `gui_qt/theme.py` tokens — the Plan 1 no-hex guard runs repo-wide. The **only** hex literal this plan may add is the new `"accent_alt": "#aa5cc3"` palette entry **inside `theme.py`** (Jellyfin gradient purple).
- The rebuilt `_ToastCard` uses **no inline `setStyleSheet`** (spec §9) — all styling via `theme.qss.tmpl` selectors. (Other files keep their current styling approach.)
- All sizing through `gui_qt/_scale.py` `px()`.
- No `"Plex"` user-facing strings (AST guard); no `processEvents` in `gui_qt` (Plan 5 sweep guard); no GUI-thread guide builds (Plan 5 deterministic guard patches `_submit_bg`).
- `ScanProgressWidget` public API unchanged (spec §16): `__init__(media_type, parent)`, `start()`, `stop()`, `update_progress(lifecycle, phase, done, total, current_item, message)`, `finish()`, `cancel_requested` signal, `scan_progress_widget` property on the workspace.
- Toast copy uses the **full original text** even when the display is clamped (spec §17): clipboard gets `title + "\n" + message`.
- Errors default to sticky — `duration_ms 0` — when the caller does not pass an explicit duration (spec §9). Explicit durations are always honored.
- Toast expand cap: ~40% of the toast's `window()` height, with internal scroll (spec §9).
- Filler quips appear **only** on the secondary line and only after a phase runs >4s without item changes; the primary line always shows the honest lifecycle phase (spec §10).
- `Spinner` (`widgets/busy_overlay.py`) stays the shared spinner primitive — do not fork a second spinner. The loading screen's animation is the conveyor, not a spinner; "looks related" is satisfied by shared tokens (`accent`, `accent_alt`, `text_dim`) and shared `_scale` sizing. (Recorded interpretation of spec line 192.)
- Suites must pass at the end of every task: `scripts\test-fast.cmd` + `scripts\test-smoke.cmd`, zero skips. Run Python via `.venv\Scripts\python.exe`.

**Recorded deviations (decided at plan time — do not silently "fix"):**
1. Spec §17 says bulk-apply per-file failures "leave the mode open with failed rows still listed". Plan 4 landed apply-exits-mode as the approved §15.7 MVP boundary, and `EpisodeMappingService.apply_assignments` returns `(applied, skipped)` **counts** only. This plan upgrades the failure *toast* (error tone + sticky + counts + reason phrase, expandable by Task 1); keeping the mode open and enumerating rows would need a service signature change (§16 conflict) — recorded for the user as an open question, not implemented.
2. Spec §17's "scan_error pill in roster" for guide-build failures: the roster pill is driven by `state.scan_error`, which the view layer must not write (§16). Guide-build failure (a view-side computation failure) gets the inline error row + footer text only; the roster pill continues to reflect engine scan errors as today.
3. The phase stepper's active-dot color moves from `warning` (old checklist QSS) to `accent` — intentional restyle to the Jellyfin look; `done` stays `success`, pending uses `text_muted`.

---

### Task 1: Toast card rebuild — QSS styling, tone icon, 3-line clamp, Show more expand

**Files:**
- Modify: `plex_renamer/gui_qt/widgets/toast_manager.py` (replace `_ToastCard`; `ToastManager` gains one connection)
- Modify: `plex_renamer/gui_qt/resources/theme.qss.tmpl` (new toast selectors, near the `scan-phase` block ~line 344)
- Create: `tests/test_qt_toasts.py`
- Modify: the two smoke-runner classification lists under `scripts/` (grep `test_qt_busy_overlay` in `scripts\` and add `test_qt_toasts.py` beside it in both lists, same format as those lines)

**Interfaces:**
- Consumes: `theme.color/qcolor/radius`, `_scale.px`, existing `ToastManager` layout planner (`_toast_manager_layout.py`, unchanged).
- Produces: `_ToastCard` with `duration_ms: int | None = None` ctor param; attributes used by Task 2 and tests: `_title_label`, `_message_label`, `_body` (QScrollArea), `_show_more_btn`, `_copy_btn`, `_progress`, `_timer` (only when counting down), `_expanded: bool`, `full_message() -> str`, `set_expanded(bool)`, signal `layout_changed = Signal()`. Tone property values: `"success" | "error" | "accent"` (unknown tones normalize to `"accent"`).

- [ ] **Step 1: Write the failing tests** — create `tests/test_qt_toasts.py`:

```python
# tests/test_qt_toasts.py
"""Rebuilt toast card: clamp/expand, copy, sticky errors, hover pause (Plan 6)."""
from conftest_qt import QtSmokeBase

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

_LONG = "line one is quite long and wraps. " * 12
_SHORT = "All done."


def _make_card(**kwargs):
    from plex_renamer.gui_qt.widgets.toast_manager import _ToastCard

    defaults = dict(title="Title", message=_SHORT, tone="accent", duration_ms=None)
    defaults.update(kwargs)
    return _ToastCard(**defaults)


class ToastCardClampTests(QtSmokeBase):
    def _host(self, card, height=600):
        host = QWidget()
        host.resize(500, height)
        card.setParent(host)
        card.setFixedWidth(360)
        host.show()
        card.show()
        card.updateGeometry()
        self._app.processEvents()
        return host

    def test_short_message_has_no_show_more(self):
        card = _make_card(message=_SHORT)
        host = self._host(card)
        self.assertFalse(card._show_more_btn.isVisible())
        host.close()

    def test_long_message_clamps_to_three_lines_and_offers_show_more(self):
        card = _make_card(message=_LONG)
        host = self._host(card)
        self.assertTrue(card._show_more_btn.isVisible())
        line = card._message_label.fontMetrics().lineSpacing()
        self.assertLessEqual(card._body.height(), line * 3 + 8)
        self.assertEqual(card._show_more_btn.text(), "Show more")
        host.close()

    def test_expand_caps_at_forty_percent_of_window_and_scrolls(self):
        card = _make_card(message=_LONG * 6)
        host = self._host(card, height=400)
        card._show_more_btn.click()
        self._app.processEvents()
        self.assertTrue(card._expanded)
        self.assertLessEqual(card._body.height(), int(host.height() * 0.4) + 2)
        self.assertEqual(
            card._body.verticalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAsNeeded,
        )
        self.assertEqual(card._show_more_btn.text(), "Show less")
        host.close()

    def test_update_message_collapses_expansion(self):
        card = _make_card(message=_LONG)
        host = self._host(card)
        card.set_expanded(True)
        card.update_message(title="T2", message=_LONG)
        self.assertFalse(card._expanded)
        host.close()


class ToastCardStyleTests(QtSmokeBase):
    def test_card_has_no_inline_stylesheet(self):
        card = _make_card()
        self.assertEqual(card.styleSheet(), "")
        self.assertEqual(card._progress.styleSheet(), "")

    def test_unknown_tone_normalizes_to_accent(self):
        card = _make_card(tone="mystery")
        self.assertEqual(card.property("tone"), "accent")
        self.assertEqual(card._icon_label.property("tone"), "accent")

    def test_tone_icon_glyphs(self):
        for tone, glyph in (("success", "✓"), ("error", "!"), ("accent", "i")):
            card = _make_card(tone=tone)
            self.assertEqual(card._icon_label.text(), glyph)
```

- [ ] **Step 2: Run the new file to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests\test_qt_toasts.py -q`
Expected: FAIL — `AttributeError` (`_show_more_btn` / `_icon_label` don't exist) and the inline-stylesheet assertion fails against the current card.

- [ ] **Step 3: Add QSS selectors** — in `theme.qss.tmpl`, insert directly after the `scan-phase` block (after the `phaseState="done"` rule ~line 361):

```css
/* Toasts (spec §9) — card styling lives here, not inline. */
QFrame#toastCard {
    background-color: ${surface};
    border: 1px solid ${border};
    border-radius: ${radius_lg}px;
}
QLabel[cssClass="toast-icon"] {
    font-weight: 600;
}
QLabel[cssClass="toast-icon"][tone="success"] { color: ${success}; }
QLabel[cssClass="toast-icon"][tone="error"] { color: ${error}; }
QLabel[cssClass="toast-icon"][tone="accent"] { color: ${info}; }
QScrollArea[cssClass="toast-body"] {
    background: transparent;
    border: 0;
}
QScrollArea[cssClass="toast-body"] > QWidget > QWidget {
    background: transparent;
}
QProgressBar[cssClass="toast-countdown"] {
    background: ${border};
    border: 0;
    border-radius: 1px;
}
QProgressBar[cssClass="toast-countdown"][tone="success"]::chunk { background: ${success}; border-radius: 1px; }
QProgressBar[cssClass="toast-countdown"][tone="error"]::chunk { background: ${error}; border-radius: 1px; }
QProgressBar[cssClass="toast-countdown"][tone="accent"]::chunk { background: ${info}; border-radius: 1px; }
```

- [ ] **Step 4: Replace `_ToastCard`** in `toast_manager.py`. Replace the `_BORDER_COLORS` dict and the whole `_ToastCard` class with:

```python
_TONES = ("success", "error", "accent")
_TONE_ICONS = {"success": "✓", "error": "!", "accent": "i"}
_CLAMP_LINES = 3
_EXPAND_WINDOW_FRACTION = 0.4
_DEFAULT_DURATION_MS = 3000
_MAX_VISIBLE_TOASTS = 4
_MAX_DIRECT_TOASTS = 3


def _normalize_tone(tone: str) -> str:
    return tone if tone in _TONES else "accent"


def _default_duration(tone: str, duration_ms: int | None) -> int:
    if duration_ms is not None:
        return max(0, duration_ms)
    return 0 if tone == "error" else _DEFAULT_DURATION_MS


class _ToastCard(QFrame):
    dismissed = Signal(object)
    layout_changed = Signal()

    def __init__(
        self,
        *,
        title: str,
        message: str,
        tone: str,
        duration_ms: int | None = None,
        action_text: str | None = None,
        action_callback: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        tone = _normalize_tone(tone)
        self._duration_ms = _default_duration(tone, duration_ms)
        self._remaining_ms = self._duration_ms
        self._action_callback = action_callback
        self._full_message = message
        self._title_text = title
        self._expanded = False
        self.setObjectName("toastCard")
        self.setProperty("tone", tone)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

        root = QVBoxLayout(self)
        pad = _scale.px(12)
        root.setContentsMargins(pad, _scale.px(10), pad, _scale.px(10))
        root.setSpacing(_scale.px(8))

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(_scale.px(8))

        self._icon_label = QLabel(_TONE_ICONS[tone])
        self._icon_label.setProperty("cssClass", "toast-icon")
        self._icon_label.setProperty("tone", tone)
        self._icon_label.setFixedWidth(_scale.px(16))
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        header.addWidget(self._icon_label)

        self._title_label = QLabel(title)
        self._title_label.setProperty("cssClass", "heading")
        self._title_label.setWordWrap(True)
        self._title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        header.addWidget(self._title_label, stretch=1)

        self._copy_btn = QPushButton("Copy")
        self._copy_btn.setProperty("cssClass", "secondary")
        self._copy_btn.setFixedHeight(_scale.px(24))
        self._copy_btn.clicked.connect(self._copy_to_clipboard)
        header.addWidget(self._copy_btn)

        close_btn = QPushButton("x")
        close_btn.setProperty("cssClass", "secondary")
        close_btn.setFixedSize(_scale.px(24), _scale.px(24))
        close_btn.clicked.connect(self.dismiss)
        header.addWidget(close_btn)
        root.addLayout(header)

        self._message_label = QLabel(message)
        self._message_label.setWordWrap(True)
        self._message_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._message_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self._body = QScrollArea()
        self._body.setProperty("cssClass", "toast-body")
        self._body.setWidgetResizable(True)
        self._body.setFrameShape(QFrame.Shape.NoFrame)
        self._body.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._body.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._body.setWidget(self._message_label)
        root.addWidget(self._body)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        self._show_more_btn = QPushButton("Show more")
        self._show_more_btn.setProperty("cssClass", "secondary")
        self._show_more_btn.setFixedHeight(_scale.px(24))
        self._show_more_btn.clicked.connect(self._toggle_expanded)
        self._show_more_btn.hide()
        controls.addWidget(self._show_more_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        if action_text and action_callback is not None:
            action_btn = QPushButton(action_text)
            action_btn.setProperty("cssClass", "secondary")
            action_btn.clicked.connect(self._run_action)
            controls.addWidget(action_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        controls.addStretch()
        root.addLayout(controls)

        self._progress = QProgressBar()
        self._progress.setProperty("cssClass", "toast-countdown")
        self._progress.setProperty("tone", tone)
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(3)
        if self._duration_ms > 0:
            self._progress.setRange(0, self._duration_ms)
            self._progress.setValue(self._duration_ms)
            root.addWidget(self._progress)
            self._timer = QTimer(self)
            self._timer.setInterval(50)
            self._timer.timeout.connect(self._tick)
            self._timer.start()
        else:
            self._progress.hide()

    # -- clamp / expand ----------------------------------------------------

    def full_message(self) -> str:
        return self._full_message

    def set_expanded(self, expanded: bool) -> None:
        if self._expanded == expanded:
            return
        self._expanded = expanded
        self._show_more_btn.setText("Show less" if expanded else "Show more")
        self._sync_clamp()
        self.layout_changed.emit()

    def _toggle_expanded(self) -> None:
        self.set_expanded(not self._expanded)

    def _line_height(self) -> int:
        return max(1, self._message_label.fontMetrics().lineSpacing())

    def _full_text_height(self) -> int:
        width = self._message_label.width()
        if width <= 1:
            width = max(1, self._body.viewport().width())
        return max(self._line_height(), self._message_label.heightForWidth(width))

    def _sync_clamp(self) -> None:
        collapsed = self._line_height() * _CLAMP_LINES + 4
        full = self._full_text_height()
        needs_clamp = full > collapsed
        self._show_more_btn.setVisible(needs_clamp)
        if not needs_clamp:
            self._expanded = False
            self._show_more_btn.setText("Show more")
            self._body.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self._body.setFixedHeight(full)
            return
        if self._expanded:
            window = self.window()
            cap = full
            if window is not None and window is not self:
                cap = max(collapsed, int(window.height() * _EXPAND_WINDOW_FRACTION))
            self._body.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self._body.setFixedHeight(min(full, cap))
        else:
            self._body.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self._body.setFixedHeight(collapsed)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._sync_clamp()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._sync_clamp()

    # -- actions / countdown -------------------------------------------------

    def _copy_to_clipboard(self) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(f"{self._title_text}\n{self._full_message}")

    def _run_action(self) -> None:
        if self._action_callback is not None:
            self._action_callback()
        self.dismiss()

    def _tick(self) -> None:
        self._remaining_ms -= self._timer.interval()
        if self._remaining_ms <= 0:
            self.dismiss()
            return
        self._progress.setValue(self._remaining_ms)

    def dismiss(self) -> None:
        timer = getattr(self, "_timer", None)
        if timer is not None:
            timer.stop()
        self.dismissed.emit(self)

    def update_message(self, *, title: str, message: str) -> None:
        self._title_text = title
        self._full_message = message
        self._title_label.setText(title)
        self._message_label.setText(message)
        self._expanded = False
        self._show_more_btn.setText("Show more")
        self._sync_clamp()
        self.layout_changed.emit()
```

Add the imports this needs at the top of the file: `QScrollArea` joins the existing `QtWidgets` import list. Remove the now-unused `_BORDER_COLORS` dict and the `from .. import theme` import **only if** nothing else in the file still uses `theme` (the manager doesn't — verify with a grep in-file).

- [ ] **Step 5: Manager reflows on card expansion** — in all three places `ToastManager` creates a `_ToastCard` (`show_toast`, `show_or_update_toast`, `_show_or_update_summary`), connect the new signal right after `toast.dismissed.connect(self._remove_toast)`:

```python
        toast.layout_changed.connect(self._reposition)
```

(In `_show_or_update_summary` the variable is `self._summary_toast`.)

- [ ] **Step 6: Run the new tests + the existing toast tests**

Run: `.venv\Scripts\python.exe -m pytest tests\test_qt_toasts.py tests\test_qt_main_window.py -q`
Expected: all PASS (the two manager-geometry tests at `test_qt_main_window.py:796/:825` must keep passing — the card API they construct through `show_toast` is unchanged).

- [ ] **Step 7: Add `tests\test_qt_toasts.py` to both smoke-runner classification lists** (grep `test_qt_busy_overlay` under `scripts\`, add the new file beside it in the same format in both lists). Run `scripts\test-fast.cmd` and `scripts\test-smoke.cmd` — both green, zero skips, smoke count grows by exactly the new file's test count.

- [ ] **Step 8: Commit**

```bash
git add plex_renamer/gui_qt/widgets/toast_manager.py plex_renamer/gui_qt/resources/theme.qss.tmpl tests/test_qt_toasts.py scripts
git commit -m "feat(gui): toast card rebuild - QSS tokens, tone icon, 3-line clamp, expand-in-place"
```

---

### Task 2: Toast copy/sticky/hover behaviors + caller duration audit

**Files:**
- Modify: `plex_renamer/gui_qt/widgets/toast_manager.py` (hover pause; `show_toast`/`show_or_update_toast` duration defaults)
- Modify: `plex_renamer/gui_qt/_main_window_tabs.py:91-95` (workspace toast lambda drops the hardcoded 4000)
- Modify: `plex_renamer/gui_qt/_main_window_feedback.py` (`show_scan_feedback` drops its hardcoded 4000)
- Test: `tests/test_qt_toasts.py` (extend)

**Interfaces:**
- Consumes: Task 1's `_ToastCard` (`_timer`, `_progress`, `_remaining_ms`, `full_message()`).
- Produces: `ToastManager.show_toast(..., duration_ms: int | None = None)` and `show_or_update_toast(..., duration_ms: int | None = None)` — `None` means tone default (error → 0/sticky, else 3000). All existing explicit callers keep their values.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_qt_toasts.py`:

```python
class ToastCardBehaviorTests(QtSmokeBase):
    def test_copy_puts_title_and_full_message_on_clipboard(self):
        from PySide6.QtWidgets import QApplication

        card = _make_card(title="Job failed", message=_LONG)
        card._copy_btn.click()
        self.assertEqual(QApplication.clipboard().text(), "Job failed\n" + _LONG)

    def test_error_tone_defaults_sticky(self):
        card = _make_card(tone="error", duration_ms=None)
        self.assertIsNone(getattr(card, "_timer", None))
        self.assertFalse(card._progress.isVisibleTo(card))

    def test_non_error_tone_defaults_to_countdown(self):
        card = _make_card(tone="success", duration_ms=None)
        self.assertIsNotNone(getattr(card, "_timer", None))
        self.assertEqual(card._duration_ms, 3000)

    def test_explicit_duration_wins_over_tone_default(self):
        card = _make_card(tone="error", duration_ms=1500)
        self.assertEqual(card._duration_ms, 1500)

    def test_hover_pauses_and_resumes_countdown(self):
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QEnterEvent
        from PySide6.QtCore import QPointF

        card = _make_card(tone="success", duration_ms=5000)
        self.assertTrue(card._timer.isActive())
        enter = QEnterEvent(QPointF(1, 1), QPointF(1, 1), QPointF(1, 1))
        card.enterEvent(enter)
        self.assertFalse(card._timer.isActive())
        remaining = card._remaining_ms
        card.leaveEvent(QEvent(QEvent.Type.Leave))
        self.assertTrue(card._timer.isActive())
        self.assertEqual(card._remaining_ms, remaining)


class ToastManagerDefaultTests(QtSmokeBase):
    def test_manager_error_toast_defaults_sticky(self):
        from plex_renamer.gui_qt.widgets.toast_manager import ToastManager

        host = QWidget()
        host.resize(800, 600)
        manager = ToastManager(host)
        host.show()
        manager.show_toast(title="Boom", message="bad", tone="error")
        card = manager._toast_widgets()[0]
        self.assertEqual(card._duration_ms, 0)
        host.close()
```

- [ ] **Step 2: Run to verify failures**

Run: `.venv\Scripts\python.exe -m pytest tests\test_qt_toasts.py -q`
Expected: the new tests FAIL — `_ToastCard.__init__` already takes `duration_ms=None` (Task 1) so sticky-default tests pass at card level, but `show_toast` still has `duration_ms: int = 3000` (manager test fails) and hover events do nothing yet (hover test fails).

- [ ] **Step 3: Implement hover pause** — add to `_ToastCard`:

```python
    def enterEvent(self, event) -> None:  # noqa: N802
        timer = getattr(self, "_timer", None)
        if timer is not None:
            timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        timer = getattr(self, "_timer", None)
        if timer is not None and self._remaining_ms > 0:
            timer.start()
        super().leaveEvent(event)
```

- [ ] **Step 4: Manager duration defaults** — change both signatures in `ToastManager`:

```python
    def show_toast(
        self,
        *,
        title: str,
        message: str,
        tone: str = "accent",
        duration_ms: int | None = None,
        action_text: str | None = None,
        action_callback: Callable[[], None] | None = None,
    ) -> None:
```

and identically for `show_or_update_toast` (its old default was `0`; pass-through of `None` now yields the tone rule — the only existing keyed caller, `_show_queue_progress_toast`, passes an explicit `duration_ms=0` and is unaffected). The card resolves `None` via `_default_duration` (Task 1). No other body changes.

- [ ] **Step 5: Caller audit** — exactly two call sites drop hardcoded durations so error tones become sticky:
  - `_main_window_tabs.py:91-95`: the lambda becomes `window._toast_manager.show_toast(title=title, message=message, tone=tone)` (no `duration_ms`).
  - `_main_window_feedback.py` `show_scan_feedback`: remove `duration_ms=4000` from its `show_toast` call.
  All other `show_toast` callers keep their explicit durations (`on_job_completed` 3000, `flush_success_toast_batch` 3000, `on_job_failed` 0, `on_queue_finished` 5000, `_show_queue_progress_toast` keyed 0).

- [ ] **Step 6: Run the file + the two suites that cover callers**

Run: `.venv\Scripts\python.exe -m pytest tests\test_qt_toasts.py tests\test_qt_main_window.py tests\test_qt_media_workspace.py -q`
Expected: PASS. (`test_main_window_queue_events_create_toasts` and friends drive explicit-duration paths — unchanged.)

- [ ] **Step 7: Full suites** — `scripts\test-fast.cmd` + `scripts\test-smoke.cmd` green, zero skips.

- [ ] **Step 8: Commit**

```bash
git add plex_renamer/gui_qt/widgets/toast_manager.py plex_renamer/gui_qt/_main_window_tabs.py plex_renamer/gui_qt/_main_window_feedback.py tests/test_qt_toasts.py
git commit -m "feat(gui): toast copy button, sticky errors by default, hover pauses countdown"
```

---

### Task 3: Phase stepper + poster-card conveyor (scan_progress internals)

**Files:**
- Modify: `plex_renamer/gui_qt/theme.py` (palette gains `"accent_alt": "#aa5cc3"` — place it directly under the `"accent"` entry)
- Modify: `plex_renamer/gui_qt/widgets/scan_progress.py` (replace `_ScannerAnimation` with `_ConveyorAnimation`; replace the checklist grid with `_PhaseStepper`)
- Modify: `plex_renamer/gui_qt/resources/theme.qss.tmpl` (DELETE the four `scan-phase-icon`/`scan-phase-label` rule blocks ~lines 344-361 — the stepper paints itself)
- Test: `tests/test_qt_workspace_widgets.py` (adapt the checklist/animation tests)

**Interfaces:**
- Consumes: `theme.qcolor` (incl. new `accent_alt`), `_scale.px`, existing `_animation_timer` (90ms) and `_checklist`/`_LIFECYCLE_LABELS` tables.
- Produces: `ScanProgressWidget._stepper` (`_PhaseStepper` with `set_progress(*, active_index, done)`, `_active_index`, `_done`); `ScanProgressWidget._animation` (`_ConveyorAnimation` with the same `set_active/set_lifecycle/advance` API `_ScannerAnimation` had — Task 4 and existing tests rely on these names). Public widget API unchanged (Global Constraints).

- [ ] **Step 1: Write the failing tests** — in `tests/test_qt_workspace_widgets.py`, replace the body of `test_scan_progress_checklist_matches_media_type` (line ~190) and `test_scan_progress_completes_prior_phases_when_lifecycle_skips_ahead` (line ~131) with stepper-based assertions, and add one conveyor test to the same class:

```python
    def test_scan_progress_checklist_matches_media_type(self):
        from plex_renamer.gui_qt.widgets.scan_progress import ScanProgressWidget

        tv_widget = ScanProgressWidget(media_type="tv")
        movie_widget = ScanProgressWidget(media_type="movie")
        self.assertEqual(len(tv_widget._stepper._labels), 5)
        self.assertEqual(len(movie_widget._stepper._labels), 4)

    def test_scan_progress_completes_prior_phases_when_lifecycle_skips_ahead(self):
        from plex_renamer.app.models import ScanLifecycle
        from plex_renamer.gui_qt.widgets.scan_progress import ScanProgressWidget

        widget = ScanProgressWidget(media_type="movie")
        widget.start()
        widget.update_progress(lifecycle=ScanLifecycle.PREPARING_REVIEW.value, phase="Preparing")
        # movie checklist: DISCOVERING, MATCHING, BUILDING_PREVIEWS, PREPARING_REVIEW
        self.assertEqual(widget._stepper._active_index, 3)
        self.assertEqual(widget._stepper._done, {0, 1, 2})
        widget.stop()

    def test_scan_progress_conveyor_fills_cards_behind_the_beam(self):
        from plex_renamer.gui_qt.widgets.scan_progress import _ConveyorAnimation

        animation = _ConveyorAnimation()
        animation.resize(600, 200)
        animation.set_active(True)
        for _ in range(10):
            animation.advance()
        self.assertEqual(animation._tick, 10)
        animation.set_active(False)
        animation.advance()
        self.assertEqual(animation._tick, 10)   # inactive: no motion
```

- [ ] **Step 2: Run to verify failures**

Run: `.venv\Scripts\python.exe -m pytest tests\test_qt_workspace_widgets.py -q`
Expected: FAIL — `_stepper` and `_ConveyorAnimation` don't exist.

- [ ] **Step 3: Add the palette token** — in `theme.py`'s palette dict, directly under `"accent": "#00a4dc",` add:

```python
    "accent_alt": "#aa5cc3",
```

- [ ] **Step 4: Implement `_PhaseStepper` and `_ConveyorAnimation`** in `scan_progress.py`. Add `QRectF, QLinearGradient` to imports (`QRectF` from `QtCore`, `QLinearGradient` from `QtGui`). Replace the entire `_ScannerAnimation` class with:

```python
_CARD_COUNT = 5
_CYCLE_TICKS = 120


class _ConveyorAnimation(QWidget):
    """Poster-card conveyor (spec §10): blank cards slide left through a fixed
    center beam; cards left of the beam render 'filled'.  One repaint timer
    (the widget's owner drives ``advance()``), QPainter only."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tick = 0
        self._active = False
        self.setMinimumHeight(_scale.px(180))

    def set_active(self, active: bool) -> None:
        if self._active == active:
            return
        self._active = active
        self.update()

    def set_lifecycle(self, lifecycle: ScanLifecycle | None) -> None:
        del lifecycle
        self.update()

    def advance(self) -> None:
        if not self._active:
            return
        self._tick = (self._tick + 1) % _CYCLE_TICKS
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(_scale.px(12), _scale.px(12), -_scale.px(12), -_scale.px(12))
        if rect.width() <= 0 or rect.height() <= 0:
            return
        slot_w = max(1, rect.width() // _CARD_COUNT)
        card_h = min(rect.height(), int(slot_w * 1.4))
        card_w = max(_scale.px(24), int(card_h * 2 / 3))
        y = rect.center().y() - card_h // 2
        offset = (self._tick % _CYCLE_TICKS) / _CYCLE_TICKS * slot_w
        beam_x = rect.center().x()
        radius = _scale.px(6)

        blank = theme.qcolor("surface")
        border = theme.qcolor("border_light")
        filled_wash = theme.qcolor("accent_alt")
        filled_wash.setAlpha(36)

        for index in range(_CARD_COUNT + 2):
            slot_x = rect.left() + int(index * slot_w - offset)
            card_x = slot_x + (slot_w - card_w) // 2
            if card_x + card_w < rect.left() or card_x > rect.right():
                continue
            card = QRectF(card_x, y, card_w, card_h)
            center_x = card.center().x()
            painter.setPen(QPen(border, max(1, _scale.px(1))))
            painter.setBrush(blank)
            painter.drawRoundedRect(card, radius, radius)
            if self._active and center_x < beam_x - slot_w * 0.5:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(filled_wash)
                painter.drawRoundedRect(card, radius, radius)
                painter.setBrush(border)
                line_w = card_w - _scale.px(12)
                painter.drawRoundedRect(
                    QRectF(card.left() + _scale.px(6), card.bottom() - _scale.px(18), line_w, _scale.px(4)), 2, 2
                )
                painter.drawRoundedRect(
                    QRectF(card.left() + _scale.px(6), card.bottom() - _scale.px(10), line_w * 0.6, _scale.px(4)), 2, 2
                )
            if self._active and abs(center_x - beam_x) <= slot_w * 0.5:
                sweep = (beam_x - (center_x - slot_w * 0.5)) / slot_w
                beam_pos = card.left() + card.width() * max(0.0, min(1.0, sweep))
                gradient = QLinearGradient(beam_pos - _scale.px(10), 0.0, beam_pos + _scale.px(10), 0.0)
                lead = theme.qcolor("accent")
                lead.setAlpha(0)
                core = theme.qcolor("accent")
                core.setAlpha(150)
                trail = theme.qcolor("accent_alt")
                trail.setAlpha(0)
                gradient.setColorAt(0.0, lead)
                gradient.setColorAt(0.5, core)
                gradient.setColorAt(1.0, trail)
                painter.fillRect(
                    QRectF(beam_pos - _scale.px(10), card.top(), _scale.px(20), card.height()), gradient
                )


class _PhaseStepper(QWidget):
    """Slim horizontal dots + connector line (spec §10) replacing the 2×N
    checklist grid.  Dot states: pending (muted) / active (accent) /
    done (success).  Tooltip carries the full phase list."""

    def __init__(self, labels: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._labels = labels
        self._active_index: int | None = None
        self._done: set[int] = set()
        self.setFixedHeight(_scale.px(24))
        self.setMinimumWidth(_scale.px(40) * max(1, len(labels)))
        self._sync_tooltip()

    def set_progress(self, *, active_index: int | None, done: set[int]) -> None:
        if active_index == self._active_index and done == self._done:
            return
        self._active_index = active_index
        self._done = set(done)
        self._sync_tooltip()
        self.update()

    def _sync_tooltip(self) -> None:
        parts = []
        for index, label in enumerate(self._labels):
            if index == self._active_index:
                marker = "●"
            elif index in self._done:
                marker = "✓"
            else:
                marker = "○"
            parts.append(f"{marker} {label}")
        self.setToolTip("\n".join(parts))

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        count = len(self._labels)
        if count == 0:
            return
        margin = _scale.px(10)
        y = self.height() / 2
        span = max(1, self.width() - 2 * margin)
        if count > 1:
            xs = [margin + span * index / (count - 1) for index in range(count)]
        else:
            xs = [self.width() / 2]
        painter.setPen(QPen(theme.qcolor("border_light"), max(1, _scale.px(2))))
        if count > 1:
            painter.drawLine(QPointF(xs[0], y), QPointF(xs[-1], y))
        base_radius = _scale.px(4)
        for index, x in enumerate(xs):
            if index == self._active_index:
                color = theme.qcolor("accent")
                dot_radius = base_radius + _scale.px(2)
            elif index in self._done:
                color = theme.qcolor("success")
                dot_radius = base_radius
            else:
                color = theme.qcolor("text_muted")
                dot_radius = base_radius
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(QPointF(x, y), dot_radius, dot_radius)
```

- [ ] **Step 5: Rewire `ScanProgressWidget`** —
  - In `_build_ui`: `self._animation = _ConveyorAnimation()` (keep the `setFixedHeight(_scale.px(260))` line but change it to `_scale.px(200)` — the conveyor is shorter than the orbit animation).
  - Replace the whole checklist-grid block (the `self._phase_rows`/`self._phase_labels`/`checklist_grid` construction) with:

```python
        self._stepper = _PhaseStepper(
            [_LIFECYCLE_LABELS.get(lifecycle, str(lifecycle)) for lifecycle in self._checklist]
        )
        card_layout.addWidget(self._stepper)
```

  - Replace `_reset_checklist` and `_update_checklist` with:

```python
    def _reset_checklist(self) -> None:
        self._stepper.set_progress(active_index=None, done=set())

    def _update_checklist(self) -> None:
        done = {
            index
            for index, lifecycle in enumerate(self._checklist)
            if lifecycle in self._completed_lifecycles
        }
        active = None
        if self._current_lifecycle in self._checklist:
            active = self._checklist.index(self._current_lifecycle)
        self._stepper.set_progress(active_index=active, done=done)
```

  - Delete `_set_phase_state` and the now-unused `_repolish` helper (nothing else in the file uses it), and drop `self._phase_rows`/`self._phase_labels` everywhere.
- [ ] **Step 6: Delete the four `scan-phase-*` QSS blocks** from `theme.qss.tmpl` (~lines 344-361 — the `font-size`, `pending`, `active`, `done` rules). Nothing else references those cssClasses after Step 5 (verify: `grep -r "scan-phase" plex_renamer`).

- [ ] **Step 7: Run the adapted file**

Run: `.venv\Scripts\python.exe -m pytest tests\test_qt_workspace_widgets.py -q`
Expected: PASS — including the untouched `test_scan_progress_uses_scale_helper`, `test_scan_progress_resets_phase_local_progress_between_lifecycles`, `test_scan_progress_terminal_state_stops_animation` (the conveyor keeps the `_animation` attr name and `set_active` API), and `test_scan_progress_throttles_fast_text_updates_but_keeps_count_current` (text pipeline untouched until Task 4).

- [ ] **Step 8: Full suites** — `scripts\test-fast.cmd` + `scripts\test-smoke.cmd` green, zero skips.

- [ ] **Step 9: Commit**

```bash
git add plex_renamer/gui_qt/theme.py plex_renamer/gui_qt/widgets/scan_progress.py plex_renamer/gui_qt/resources/theme.qss.tmpl tests/test_qt_workspace_widgets.py
git commit -m "feat(gui): loading screen gets poster-card conveyor + phase stepper (spec s10)"
```

---

### Task 4: Single-source status lines + filler quips

**Files:**
- Modify: `plex_renamer/gui_qt/widgets/scan_progress.py`
- Test: `tests/test_qt_workspace_widgets.py`

**Interfaces:**
- Consumes: Task 3's widget layout; `ElidedLabel` from `._workspace_widget_primitives` (defaults to `ElideMiddle` — exactly spec §10's requirement).
- Produces: `ScanProgressWidget._item_label` (`ElidedLabel`, the single secondary line), `_filler_timer` (QTimer, 4000ms), `_rotate_filler()` (test seam). `_message_label` and `_current_label` are **deleted**. `update_progress` signature unchanged.

- [ ] **Step 1: Write the failing tests** — in `tests/test_qt_workspace_widgets.py`, replace the body of `test_scan_progress_throttles_fast_text_updates_but_keeps_count_current` so its label assertions read `widget._item_label` instead of the deleted labels (keep its throttle structure and count assertions identical — only the attribute name and expected text change: the secondary line shows the item text without the `"Current: "` prefix), and add:

```python
    def test_scan_progress_single_secondary_line_elides_middle_with_tooltip(self):
        from plex_renamer.gui_qt.widgets.scan_progress import ScanProgressWidget

        widget = ScanProgressWidget(media_type="tv")
        widget.resize(700, 500)
        widget.start()
        long_item = "S01E01 - " + ("x" * 200) + ".mkv"
        widget.update_progress(
            lifecycle="matching", phase="Matching", done=1, total=10, current_item=long_item
        )
        self.assertEqual(widget._item_label.text(), long_item)     # ElidedLabel.text() returns full text
        self.assertEqual(widget._item_label.toolTip(), long_item)
        widget.stop()

    def test_scan_progress_filler_quip_rotates_and_item_update_resets(self):
        from plex_renamer.gui_qt.widgets.scan_progress import ScanProgressWidget

        widget = ScanProgressWidget(media_type="tv")
        widget.start()
        widget.update_progress(lifecycle="matching", phase="Matching", current_item="a.mkv")
        self.assertEqual(widget._filler_timer.interval(), 4000)
        self.assertTrue(widget._filler_timer.isActive())
        widget._rotate_filler()
        first_quip = widget._item_label.text()
        self.assertNotEqual(first_quip, "a.mkv")
        widget._rotate_filler()
        self.assertNotEqual(widget._item_label.text(), first_quip)   # rotates through the list
        widget.update_progress(lifecycle="matching", phase="Matching", current_item="b.mkv")
        self.assertEqual(widget._item_label.text(), "b.mkv")         # honest item resets the line
        widget.stop()
        self.assertFalse(widget._filler_timer.isActive())

    def test_scan_progress_primary_line_always_shows_phase_not_quips(self):
        from plex_renamer.gui_qt.widgets.scan_progress import ScanProgressWidget

        widget = ScanProgressWidget(media_type="tv")
        widget.start()
        widget.update_progress(lifecycle="matching", phase="Matching on TMDB", current_item="a.mkv")
        widget._rotate_filler()
        self.assertEqual(widget._phase_label.text(), "Matching on TMDB")
        widget.stop()
```

- [ ] **Step 2: Run to verify failures** — `.venv\Scripts\python.exe -m pytest tests\test_qt_workspace_widgets.py -q` → FAIL (`_item_label`, `_filler_timer`, `_rotate_filler` missing).

- [ ] **Step 3: Implement.** In `scan_progress.py`:
  - Add module constants after `_TERMINAL`:

```python
_FILLER_DELAY_MS = 4000
_TV_FILLERS = (
    "Politely interrogating TMDB…",
    "Counting specials twice, just in case…",
    "Untangling Season 0…",
    "Cross-checking absolute numbering…",
    "Politely disagreeing with filenames…",
)
_MOVIE_FILLERS = (
    "Politely interrogating TMDB…",
    "Comparing runtimes and vibes…",
    "Squinting at release years…",
    "Sorting sequels from remakes…",
)
```

  - Import `ElidedLabel`: `from ._workspace_widget_primitives import ElidedLabel`.
  - In `__init__`, after `_animation_timer` setup:

```python
        self._filler_timer = QTimer(self)
        self._filler_timer.setInterval(_FILLER_DELAY_MS)
        self._filler_timer.timeout.connect(self._rotate_filler)
        self._fillers = _TV_FILLERS if media_type == "tv" else _MOVIE_FILLERS
        self._filler_index = 0
```

  - In `_build_ui`, DELETE the `self._message_label` block and the `details` grid block, replacing both with a single secondary row directly under `self._phase_label`:

```python
        secondary_row = QHBoxLayout()
        self._item_label = ElidedLabel("")
        self._item_label.setProperty("cssClass", "text-dim")
        self._item_label.setFixedHeight(_scale.px(22))
        secondary_row.addWidget(self._item_label, stretch=1)
        self._elapsed_label = QLabel("Elapsed: 0:00")
        self._elapsed_label.setProperty("cssClass", "text-dim")
        self._elapsed_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        secondary_row.addWidget(self._elapsed_label, alignment=Qt.AlignmentFlag.AlignRight)
        card_layout.addLayout(secondary_row)
```

    Final card order top-to-bottom after this step: title → animation → `_phase_label` (primary) → `secondary_row` (item + elapsed) → `bar_row` (progress + count) → `sep` → stepper → Cancel row. (Move the existing `bar_row` block below the new `secondary_row` to match; the separator `sep` block stays where it is.)
  - Add the secondary-line setter + rotation:

```python
    def _set_item_text(self, text: str) -> None:
        self._item_label.setText(text)
        self._item_label.setToolTip(text)

    def _rotate_filler(self) -> None:
        if not self._fillers or not self._elapsed_timer.isActive():
            return
        quip = self._fillers[self._filler_index % len(self._fillers)]
        self._filler_index += 1
        self._item_label.setText(quip)
        self._item_label.setToolTip("")
```

  - In `start()`: replace `self._message_label.setText("Preparing the scanner.")` and `self._current_label.setText("Current: -")` with `self._set_item_text("Preparing the scanner…")`, and add `self._filler_index = 0` and `self._filler_timer.start()`.
  - In `stop()`: add `self._filler_timer.stop()`.
  - In `update_progress`, replace the text-update block inside `if self._should_update_text(...):` with:

```python
            if phase:
                self._phase_label.setText(phase)
            item_text = current_item or message
            if item_text:
                self._set_item_text(item_text)
                self._filler_index = 0
                self._filler_timer.start()   # restart the 4s no-change window
            self._text_update_timer.restart()
```

  - Delete `_set_elided_text` and the module helpers `_label_text_width`/`_elided_text` (ElidedLabel owns elision now; verify nothing else in the file uses them).

- [ ] **Step 4: Run the file** — `.venv\Scripts\python.exe -m pytest tests\test_qt_workspace_widgets.py -q` → PASS.

- [ ] **Step 5: Grep for stale attribute users** — `grep -rn "_message_label\|_current_label" plex_renamer tests` must show no `scan_progress` hits (the toast card's `_message_label` in `toast_manager.py`/`test_qt_toasts.py` is a different widget and stays).

- [ ] **Step 6: Full suites** — `scripts\test-fast.cmd` + `scripts\test-smoke.cmd` green, zero skips.

- [ ] **Step 7: Commit**

```bash
git add plex_renamer/gui_qt/widgets/scan_progress.py tests/test_qt_workspace_widgets.py
git commit -m "feat(gui): loading screen single-source status lines + filler quips (spec s10)"
```

---

### Task 5: Async polish — guide-failure error row, loading/error footer, queue sync-failure wording, bulk failure toast tone

**Files:**
- Modify: `plex_renamer/gui_qt/widgets/_episode_table_model.py`
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_queue_actions.py:141-159`
- Modify: `plex_renamer/gui_qt/widgets/_media_workspace_actions.py:256-259` (bulk-apply toast tone/message)
- Test: `tests/test_qt_async_guide.py`, `tests/test_qt_media_workspace.py`

**Interfaces:**
- Consumes: `_GuideBridge` (in `_episode_table_model.py` — has `guide_ready = Signal(object, object, object, int)`), skeleton/section-label entry shapes, `busy_scope` queue envelope from Plan 5.
- Produces: `_GuideBridge.guide_failed = Signal(object, int)`; model attr `_guide_error: bool`; footer strings `"Loading episodes…"` (guide pending) and `"Guide unavailable"` (build failed); error-row title `"Episode guide failed to load — select the show again to retry"`; queue warning-box title `"Queued With Warnings"`.

- [ ] **Step 1: Write the failing model tests** — append to `AsyncGuideModelTests` in `tests/test_qt_async_guide.py`:

```python
    def test_failed_build_renders_error_row_not_permanent_skeleton(self):
        state = _table_state("Show A")
        self.model._guide_builder = lambda s: (_ for _ in ()).throw(RuntimeError("boom"))
        self.model.show_state(state, collapsed_sections=set())
        self.pending.pop()()                        # worker runs, builder raises
        self._app.processEvents()
        kinds = [entry.kind for entry in self.model._entries]
        self.assertNotIn("skeleton", kinds)
        self.assertEqual(kinds, ["section-label"])
        row = self.model._entries[0].row_data
        self.assertIn("failed", row.title)
        self.assertIn("retry", row.title)
        self.assertEqual(row.status_tone, "error")
        self.assertEqual(self.model.summary_text(), "Guide unavailable")

    def test_reselect_after_failure_schedules_a_fresh_build(self):
        state = _table_state("Show A")
        self.model._guide_builder = lambda s: (_ for _ in ()).throw(RuntimeError("boom"))
        self.model.show_state(state, collapsed_sections=set())
        self.pending.pop()()
        self._app.processEvents()

        def working_builder(s):
            self.build_calls.append(s)
            return self.cache.build_guide_with_signature(s)

        self.model._guide_builder = working_builder
        self.model.show_state(state, collapsed_sections=set())   # user reselects
        self.assertEqual(len(self.pending), 1)                   # fresh build scheduled
        self.pending.pop()()
        self._app.processEvents()
        self.assertIn("episode", {entry.kind for entry in self.model._entries})
        self.assertNotEqual(self.model.summary_text(), "Guide unavailable")

    def test_summary_text_says_loading_while_skeleton_is_up(self):
        state = _table_state("Show A")
        self.model.show_state(state, collapsed_sections=set())
        self.assertEqual(self.model.summary_text(), "Loading episodes…")
        self.pending.pop()()
        self._app.processEvents()
        self.assertTrue(self.model.summary_text().startswith("4 files"))
```

Note: `AsyncGuideModelTests.setUp` stores the builder on the model as `counting_builder` via ctor; these tests overwrite the private `_guide_builder` — check the actual attribute name in the model ctor and use that name (it is the ctor kwarg stored privately; grep `guide_builder` in `_episode_table_model.py` first and keep the test consistent with reality).

- [ ] **Step 2: Write the failing queue/workspace tests** — in `tests/test_qt_media_workspace.py`, locate the existing queue-failure test that patches `warning_box` (grep `Queue Failed` in the file) and add beside it, using the same fixture idioms:

```python
    def test_queue_post_success_sync_failure_reports_queued_with_warnings(self):
        # Arrange exactly like the existing Queue Failed test, but make
        # add_batch succeed and sync_queued_states raise.
        workspace = self._make_ready_workspace()          # use the file's existing fixture helper
        calls = []

        class _Box:
            @staticmethod
            def warning(parent, title, text):
                calls.append((title, text))

        workspace._media_ctrl.sync_queued_states = lambda: (_ for _ in ()).throw(RuntimeError("sync boom"))
        fired = []
        workspace.queue_changed.connect(lambda: fired.append(True))
        # Drive the same entry point the existing test drives, passing warning_box=_Box.
        ...
        self.assertEqual(calls[0][0], "Queued With Warnings")
        self.assertIn("queued", calls[0][1])
        self.assertEqual(fired, [True])                   # jobs exist; queue tab must learn
```

**The `...` is fixture plumbing copied verbatim from the neighboring `Queue Failed` test** — same states, same `queue_states(...)` call shape, only the two overrides above differ. The implementer copies that body rather than inventing one (the plan cannot reproduce it here without drift; the neighboring test is the source of truth). Also add the bulk-toast assertion beside `test_apply_lands_assignments_and_exits_with_one_toast` (line ~4404): a variant where one staged pair targets an already-claimed slot asserts the toast tone argument is `"error"` and the message contains `"skipped (slot already claimed or no longer valid)"` — again reusing that test's staging fixture.

- [ ] **Step 3: Run to verify failures** — both new test groups FAIL (no `guide_failed` signal → skeleton persists; queue path emits `"Queue Failed"`; bulk toast tone is `"success"`).

- [ ] **Step 4: Implement the model failure path** in `_episode_table_model.py`:
  - `_GuideBridge` gains `guide_failed = Signal(object, int)` next to `guide_ready`, and the model ctor connects it: `self._guide_bridge.guide_failed.connect(self._on_guide_failed)` right where `guide_ready` is connected.
  - Add `self._guide_error = False` to the ctor near `_guide_token`.
  - In `_resolve_guide_or_schedule`, add `self._guide_error = False` immediately after the token bump line.
  - In the `_worker` except-branch, after the `_log.exception(...)` line, emit the failure (same RuntimeError guard as `guide_ready`):

```python
            except Exception:
                _log.exception("episode guide build failed for %s", state.folder)
                try:
                    bridge.guide_failed.emit(state, token)
                except RuntimeError:
                    pass    # bridge destroyed during shutdown
                return
```

  - Add the handler + error entry beside `_on_guide_ready`:

```python
    def _on_guide_failed(self, state, token: int) -> None:
        if token != self._guide_token or state is not self._state:
            return    # stale failure: a newer resolve superseded it
        self._guide_error = True
        self.beginResetModel()
        self._entries = [self._guide_error_entry()]
        self.endResetModel()
        self.guide_loaded.emit()    # footer/toolbar refresh path (guide stays None)

    def _guide_error_entry(self) -> _Entry:
        title = "Episode guide failed to load — select the show again to retry"
        row_data = EpisodeRowData(
            kind="section-label", title=title,
            status_text=title, status_tone="error",
        )
        return _Entry("section-label", None, title, None, None, row_data)
```

    (Mirror the exact `_Entry` construction arity used by `_scan_error_entry` — check it in-file and match.)
  - In `summary_text`, replace the `elif self._guide is None:` branch:

```python
        elif self._guide is None:
            if self._state is not None and self._guide_error:
                return "Guide unavailable"
            if self._state is not None:
                return "Loading episodes…"
            total = mapped = companions = unmapped = duplicates = 0
```

- [ ] **Step 5: Implement the queue envelope split** in `_media_workspace_queue_actions.py` — replace lines 141-159 with:

```python
    sync_error: Exception | None = None
    try:
        # An exception unwinds through the scope (dismissing the overlay)
        # before any box appears — never a scrim under a modal.
        with busy_scope(workspace, "Queueing…", immediate=True):
            result = add_batch(
                states,
                root,
                output_root,
                workspace._media_ctrl.command_gating,
            )
            try:
                workspace._media_ctrl.sync_queued_states()
                workspace.refresh_from_controller()
                workspace._restore_roster_selection_by_key(selected_key)
            except Exception as exc:    # batch queued; only the view refresh failed
                sync_error = exc
    except Exception as exc:
        warning_box.warning(workspace, "Queue Failed", str(exc))
        return

    workspace.queue_changed.emit()
    if sync_error is not None:
        warning_box.warning(
            workspace,
            "Queued With Warnings",
            f"The items were queued, but the view failed to refresh.\n\n{sync_error}",
        )
        return
    workspace.status_message.emit(_format_batch_result(result), 5000)
```

- [ ] **Step 6: Bulk-apply failure toast** in `_media_workspace_actions.py` (lines 256-259):

```python
        tone = "error" if skipped else "success"
        message = f"Assigned {applied} file(s)."
        if skipped:
            message += f" {skipped} skipped (slot already claimed or no longer valid)."
        workspace.toast_requested.emit("Bulk Assign", message, tone)
```

- [ ] **Step 7: Run the covering files**

Run: `.venv\Scripts\python.exe -m pytest tests\test_qt_async_guide.py tests\test_qt_media_workspace.py tests\test_work_panel.py -q`
Expected: PASS, including Plan 5's pinned async tests (the failure path never touches the success path; `test_stale_delivery_is_dropped_after_state_switch` and the I1 orphan test stay green).

- [ ] **Step 8: Full suites** — green, zero skips.

- [ ] **Step 9: Commit**

```bash
git add plex_renamer/gui_qt/widgets/_episode_table_model.py plex_renamer/gui_qt/widgets/_media_workspace_queue_actions.py plex_renamer/gui_qt/widgets/_media_workspace_actions.py tests/test_qt_async_guide.py tests/test_qt_media_workspace.py
git commit -m "fix(gui): guide-build failure renders retryable error row; truthful loading footer; queued-with-warnings envelope; bulk failure toast tone"
```

---

### Task 6: Bulk toolbar gating consolidated inside update_toolbar (re-review M6)

**Files:**
- Modify: `plex_renamer/gui_qt/widgets/_work_panel.py` (`update_toolbar` ~line 477, `_on_guide_loaded` ~line 470)
- Test: `tests/test_qt_async_guide.py`

**Interfaces:**
- Consumes: `bulk_assign_active()`, `enter_bulk_assign`/`exit_bulk_assign` (unchanged), Plan 5's `test_mid_bulk_delivery_keeps_hidden_toolbar_and_bulk_mode` (must stay green).
- Produces: `update_toolbar` is the single owner of bulk-mode button hiding; every caller (including `show_state` during a same-state repopulate) is safe mid-bulk.

- [ ] **Step 1: Write the failing test** — append to `AsyncGuideWorkPanelTests` in `tests/test_qt_async_guide.py`:

```python
    def test_same_state_repopulate_mid_bulk_keeps_buttons_hidden(self):
        """Re-review M6: refresh_from_controller repopulates the panel with the
        same state during bulk; show_state's unconditional update_toolbar must
        not re-show the hidden Approve All / Unassign All buttons."""
        from plex_renamer.app.services.episode_projection_cache import (
            EpisodeProjectionCacheService,
        )
        from plex_renamer.gui_qt.widgets._work_panel import MediaWorkPanel

        cache = EpisodeProjectionCacheService()
        panel = MediaWorkPanel(
            media_type="tv",
            cached_guide_provider=cache.cached_guide_for_state,
            guide_builder=cache.build_guide_with_signature,
            guide_store=cache.store_guide,
        )
        panel.resize(760, 640)
        panel.show()
        state = _table_state("Show A")
        cache.prepare_state(state)                       # cached: sync render
        panel.show_state(state, collapsed_sections=set())
        self.assertTrue(panel.unassign_all_button.isVisible())
        panel.enter_bulk_assign()
        self.assertFalse(panel.unassign_all_button.isVisible())
        panel.show_state(state, collapsed_sections=set())   # same-state repopulate
        self.assertTrue(panel.bulk_assign_active())
        self.assertFalse(panel.approve_all_button.isVisible())
        self.assertFalse(panel.unassign_all_button.isVisible())
        panel.exit_bulk_assign()
        self.assertTrue(panel.unassign_all_button.isVisible())
        panel.close()
```

- [ ] **Step 2: Run to verify it fails** — `.venv\Scripts\python.exe -m pytest tests\test_qt_async_guide.py -q` → the new test FAILS at the post-repopulate `assertFalse(panel.unassign_all_button.isVisible())` (`show_state` → `update_toolbar` re-shows it).

- [ ] **Step 3: Implement** — in `_work_panel.py`:
  - `update_toolbar` gains the bulk gate as the single owner:

```python
    def update_toolbar(self, state: ScanState | None) -> None:
        bulk_active = self.bulk_assign_active()
        if self._media_type != "movie":
            self._overflow_button.setVisible(not bulk_active)
        is_movie = self._media_type == "movie"
        self._segmented_filter.setVisible(not is_movie)
        self._search_box.setVisible(not is_movie)
        if is_movie or state is None or bulk_active:
            self._approve_all_button.hide()
            self._unassign_all_button.hide()
            return
        guide = self._model.guide()
        has_review = guide is not None and any(row.status == "Review" for row in guide.rows)
        self._approve_all_button.setVisible(has_review)
        self._sync_unassign_all_button(state)
```

  - `_on_guide_loaded` simplifies to (the early-return guard moves into `update_toolbar`):

```python
    def _on_guide_loaded(self) -> None:
        """Async guide arrived: summary + toolbar depend on model.guide()."""
        self.update_footer()
        self.update_toolbar(self._state)
```

  - `enter_bulk_assign`'s explicit `hide()` calls stay (harmless, and they cover the pre-`update_toolbar` instant).

- [ ] **Step 4: Run the async file + work-panel + bulk tests**

Run: `.venv\Scripts\python.exe -m pytest tests\test_qt_async_guide.py tests\test_work_panel.py tests\test_qt_media_workspace.py -q`
Expected: PASS — including Plan 5's `test_mid_bulk_delivery_keeps_hidden_toolbar_and_bulk_mode` (the delivery path now flows through the gated `update_toolbar` and still keeps buttons hidden) and Plan 4's bulk-mode pins.

- [ ] **Step 5: Full suites** — green, zero skips.

- [ ] **Step 6: Commit**

```bash
git add plex_renamer/gui_qt/widgets/_work_panel.py tests/test_qt_async_guide.py
git commit -m "fix(gui): update_toolbar owns bulk-mode button gating (re-review M6)"
```

---

### Task 7: Verification + bookkeeping (controller)

**Files:**
- Modify: `docs/superpowers/plans/2026-07-03-gui-v4-implementation.md`, `docs/superpowers/plans/2026-07-03-gui-v4-handoff.md`

- [ ] **Step 1: Full suites** — `scripts\test-fast.cmd` + `scripts\test-smoke.cmd` → pass, zero new skips; skim `.pytest_cache/smoke/latest.log`.

- [ ] **Step 2: Visual sanity** — throwaway offscreen grab script (scratchpad; `QT_QPA_PLATFORM=offscreen`, `QT_QPA_FONTDIR=C:\Windows\Fonts`, theme QSS applied). Grabs: (a) a `ToastManager` host with one clamped long-error toast (Show more visible, countdown absent because error = sticky) and the same toast expanded (scroll area at cap); (b) `ScanProgressWidget` mid-scan — conveyor with filled+blank cards and beam, stepper with done/active/pending dots, primary phase line + secondary quip line after calling `_rotate_filler()`; (c) work panel with a failed guide build — error section-label row + `"Guide unavailable"` footer. Assert parentage while grabbing (no stray visible top-levels — Plan 3's lesson). Keep script in scratchpad only.

- [ ] **Step 3: Update roadmap + handoff, commit** — roadmap row 6 → Landed (commit range); handoff status/current + "next step: write Plan 7 (queue/history restyle, spec §11)" + session log entry; carry forward the still-deferred items (duplicate in-flight builds waste note; scan-error re-show token corner; sweep-needle import-evasion gaps; spec-deviation record for bulk mode-open-on-failure and roster pill scope from this plan's Recorded Deviations).

```bash
git add docs/superpowers/plans
git commit -m "docs: mark GUI V4 plan 6 landed; next up plan 7 (queue/history restyle)"
```

---

## Self-review notes (kept for the record)

- **Spec §9 coverage:** QSS-token card with tone icon + clamped message (Task 1), Show more expand-in-place with 40%-window cap + internal scroll (Task 1), copy button with full untruncated text (Tasks 1-2, §17 rule), errors sticky by default + hover pause + countdown bar kept (Task 2), overflow summary untouched (existing `_show_or_update_summary` path keeps working — Task 1 only swaps the card internals).
- **Spec §10 coverage:** conveyor animation (Task 3, 5 cards + beam + filled flip, one existing 90ms timer), phase stepper dots+connector (Task 3), single primary/secondary lines with ElideMiddle + tooltip (Task 4), progress bar + done/total + elapsed + Cancel all pre-existing and untouched, filler quips (Task 4, >4s rotation, honest primary). BusyOverlay/Spinner sharing: recorded interpretation in Global Constraints (no second spinner; shared tokens) — reviewer may challenge.
- **Deferred-item coverage:** permanent-skeleton failure → §17-mandated error row + retry-on-reselect (Task 5, the retry works because every resolve bumps the token and reschedules on miss); footer loading/error truth (Task 5); Queued-With-Warnings envelope incl. the previously-skipped `queue_changed.emit()` on sync-failure (Task 5 — jobs exist, the queue tab must learn); M6 gating single-owner (Task 6). NOT taken: sweep-needle import-evasion hardening (still deferred — guard design choice, unchanged); duplicate in-flight build dedup (waste-only, unchanged).
- **Plan-defect guard:** Tasks 5-6 edit `_on_guide_*` — the landed 3765d5a shapes (unconditional bump; gated toolbar) are preserved verbatim in the code shown here; no plan text reintroduces the I1/I2 patterns.
- **Type-consistency pass:** `_ToastCard` kwargs identical across `show_toast`/`show_or_update_toast`/`_show_or_update_summary` call sites; `duration_ms: int | None = None` in card + both manager methods; `guide_failed = Signal(object, int)` matches `_on_guide_failed(state, token)` and the worker emit; `_stepper._labels/_active_index/_done` names match Task 3 tests; `_item_label`/`_filler_timer`/`_rotate_filler` match Task 4 tests; `accent_alt` used only via `theme.qcolor` in painted widgets.
- **Known test-plumbing risk:** Task 5 Step 2's two workspace tests intentionally splice into existing fixture bodies (`Queue Failed` neighbor, bulk-apply toast neighbor) — the implementer must copy the neighboring fixture code, not invent parallel fixtures. Task 1/4 adapt named existing tests; the plan lists exactly which.
