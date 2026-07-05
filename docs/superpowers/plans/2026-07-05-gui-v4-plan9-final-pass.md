# GUI V4 Plan 9 — Final Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close out GUI V4 — land every carried polish minor from Plans 6–8, tighten the two release guards (broadened hex regex per the user's 2026-07-05 decision; spec §18's 500-episode populate+first-paint gate), and run the §18 release gates (DPI 100/150/200% visual pass, real-library validation, sweep re-confirmation) so `dev/GUI4` is merge-ready.

**Architecture:** Three small view-layer polish waves (job-detail/history, settings, toasts/progress) — each a handful of surgical fixes with the accumulated reviewer prescriptions applied verbatim where they were probe-verified; one guard-tightening task (regex + perf gate, both in existing test files); one controller task running the release gates and writing the V4 close-out bookkeeping. No new files anywhere; no engine/controller/service changes.

**Tech Stack:** PySide6 (QSS tokens, `_scale.px`, offscreen grabs at `QT_SCALE_FACTOR` 1.0/1.5/2.0), existing fast/smoke suites, `scripts/scan_real_library.py` for the real-library gate.

## Global Constraints

- No engine/controller/service/job-store behavior changes (spec §16). Every change in Tasks 1–4 is view-layer or test-layer.
- All colors through `gui_qt/theme.py` tokens; all sizing through `_scale.px()`/`icon()`; no inline `setStyleSheet`; no `processEvents` in `gui_qt`; no `"Plex"` user-facing strings.
- Public seams unchanged: `SettingsTab` signals + `sync_*`; `JobDetailPanel.set_job/clear/set_history_mode`; `ScanProgressWidget.start/stop/update_progress/finish` (public API frozen since Plan 6); `ToastManager` API. `SettingsTab.__init__` may add `*` markers but every existing call site is keyword-based (verified: `_main_window_tabs.py:65-71` + all tests) — no caller breaks.
- **No new test files** — tests extend `tests/test_job_preview_grouping.py` (fast), `tests/test_gui_theme.py` (fast), `tests/test_qt_job_detail_panel.py`, `tests/test_qt_main_window.py`, `tests/test_qt_media_workspace.py`, `tests/test_qt_workspace_widgets.py`, `tests/test_qt_toasts.py`, `tests/test_qt_perf_guards.py` (all smoke-classified). Runner lists under `scripts/` untouched.
- Suites green at the end of every task: `scripts\test-fast.cmd` + `scripts\test-smoke.cmd`, zero skips. Python via `.venv\Scripts\python.exe`.
- Real-library gate protocol (CLAUDE.md): `scripts/scan_real_library.py` needs the `P:` drive and exits cleanly (code 2) when it is missing — if so, **report validation as blocked; never substitute another directory**.
- Pin-test protocol (same as Plan 8 Task 5): tests marked "expected PASS" pin already-landed behavior — a failure is a **finding to report before touching anything**, not a test to adapt.

**Recorded dispositions (decided at plan time — the V4 close-out list):**
1. Plan 6 M6 (conftest pool drain is not a strict barrier) — **leave**; the `threading.Barrier(9)` hardening recipe stays on record only if the interpreter-exit crash ever recurs.
2. Plan 5 carried notes (duplicate skeleton build is waste-only; scan-error re-show token corner; sweep needles don't cover `time.sleep` variants; "force rescan" overlay site doesn't exist; collapse/expand <50ms unguarded) — **accepted for V4**; none escalated across four subsequent plans.
3. Plan 4 staleness boundary (bulk-assign pins its entry state; empty-roster refresh orphan) — the handoff note **is** the fix, by that review's own ruling.
4. Plan 8 packaging observation (wheels would omit `resources/*`) — **out of V4 scope**; packaging was never part of this redesign. Belongs to a future packaging task.
5. §16 "dialogs restyle" — already token-clean (Plan 8 deviation 4); Task 5's DPI pass supplies the promised visual confirmation. No code task.
6. Spec §18 names a **500**-episode perf state; the existing 300-episode guards stay untouched (they pin the async/no-GUI-build invariants) — Task 4 **adds** the 500-episode populate+first-paint gate beside them.
7. Hex-guard broadening to 3/8-digit forms was **approved by the user 2026-07-05**, closing Plan 1's last open item.
8. Plan 7's recorded deviations (heuristic companion pairing etc.) and Plan 8's (checked fill stays `${success}`, Cache→Data merge, latent Part-chips policy) remain on record unchanged — they are design decisions, not debts.

---

### Task 1: Job-detail + history polish (Plan 7 leftovers)

**Files:**
- Modify: `plex_renamer/gui_qt/widgets/_job_detail_preview.py:157-171` (singular season/other-files label)
- Modify: `plex_renamer/gui_qt/widgets/job_detail_panel.py:229-232,529-530` (empty-card message clip)
- Modify: `plex_renamer/gui_qt/widgets/history_tab.py:8-15` (missing `QWidget` import)
- Test: `tests/test_job_preview_grouping.py`, `tests/test_qt_job_detail_panel.py`

**Interfaces:**
- Consumes: `build_job_preview_entries` / `JobPreviewGroup.label` (existing); `job_detail_empty_message(history_mode=...)` from `_job_detail_tree.py:9-12` (unchanged); `JobDetailPanel._empty_card` (max width `_scale.px(380)`, 28px content margins) and `_empty_message` (word-wrapped QLabel).
- Produces: module helper `_files_label(count: int) -> str` in `_job_detail_preview.py`; `_update_empty_message` re-pins the message label's minimum height on every text change. No signature changes anywhere.

- [ ] **Step 1: Write the failing label test** — append to `PreviewEntriesGroupingTests` in `tests/test_job_preview_grouping.py`:

```python
    def test_single_file_season_group_label_is_singular(self):
        from plex_renamer.gui_qt.widgets._job_detail_preview import (
            JobPreviewGroup,
            build_job_preview_entries,
        )

        video = _video("Show - S01E01 - Pilot")
        video.season = 1
        entries = build_job_preview_entries(self._job([video]))
        labels = [e.label for e in entries if isinstance(e, JobPreviewGroup)]
        self.assertIn("Season 01 (1 file)", labels)
        self.assertNotIn("Season 01 (1 files)", labels)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests\test_job_preview_grouping.py -q`
Expected: FAIL — label renders "Season 01 (1 files)".

- [ ] **Step 3: Implement the noun helper** — in `_job_detail_preview.py`, add directly above `_build_video_preview_entries`:

```python
def _files_label(count: int) -> str:
    noun = "file" if count == 1 else "files"
    return f"{count} {noun}"
```

and replace the two label lines (currently 162 and 164):

```python
                label = f"Season {season_num:02d} ({_files_label(len(season_ops))})"
            else:
                label = f"Other Files ({_files_label(len(season_ops))})"
```

- [ ] **Step 4: Run to verify pass** — same command → PASS (all existing multi-file fixtures still say "(2 files)"/"(3 files)").

- [ ] **Step 5: Write the failing clip test** — append to the test class in `tests/test_qt_job_detail_panel.py` (it extends `QtSmokeBase`, so `self._app` exists):

```python
    def test_empty_card_message_is_not_clipped_in_either_mode(self):
        from plex_renamer.gui_qt.widgets.job_detail_panel import JobDetailPanel

        panel = JobDetailPanel()
        panel.resize(520, 760)
        panel.show()
        for history_mode in (False, True):
            panel.set_history_mode(history_mode)
            self._app.processEvents()
            message = panel._empty_message
            needed = message.heightForWidth(message.width())
            self.assertGreaterEqual(
                message.height(), needed,
                f"empty-card message clipped in history_mode={history_mode}: "
                f"{message.height()}px shown, {needed}px needed",
            )
        panel.close()
```

- [ ] **Step 6: Run to verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests\test_qt_job_detail_panel.py -q`
Expected: FAIL — the message wraps to more lines than the hard-coded 3-line minimum covers (observed clipping the last line at default sizes; Plan 7's grab pass first spotted it).

- [ ] **Step 7: Fix the clip** — in `job_detail_panel.py`:
  - Delete the static band-aid at line ~232: `self._empty_message.setMinimumHeight((self._empty_message.fontMetrics().lineSpacing() * 3) + 12)` (keep the title's 2-line minimum at ~223 — the title is one short line).
  - Replace `_update_empty_message` (lines 529-530):

```python
    def _update_empty_message(self) -> None:
        self._empty_message.setText(job_detail_empty_message(history_mode=self._history_mode))
        # Word-wrapped labels under a Maximum-height card get no
        # height-for-width pass from the layout; pin the minimum to the
        # wrapped height at the card's content width so the last line
        # cannot clip.
        margins = self._empty_card.layout().contentsMargins()
        content_width = self._empty_card.maximumWidth() - margins.left() - margins.right()
        self._empty_message.setMinimumHeight(
            self._empty_message.heightForWidth(content_width)
        )
```

    (`_update_empty_message` already runs at construction and on every `set_history_mode` — both call sites unchanged.) If GREEN needs a different mechanism (Qt height-for-width quirks vary), the Step-5 test is the acceptance bar — keep it verbatim, adjust the mechanism, and record the deviation in your report.

- [ ] **Step 8: The one-token import fix** — in `history_tab.py`, add `QWidget` to the QtWidgets import list (the `parent: QWidget | None` annotation at line 50 currently references an unimported name; harmless under `from __future__ import annotations`, a `NameError` only if the annotation is ever evaluated):

```python
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QMenu,
    QPushButton,
    QWidget,
)
```

- [ ] **Step 9: Run the covering files** — `.venv\Scripts\python.exe -m pytest tests\test_job_preview_grouping.py tests\test_qt_job_detail_panel.py tests\test_qt_queue_history.py -q` → PASS.

- [ ] **Step 10: Full suites** — green, zero skips.

- [ ] **Step 11: Commit**

```bash
git add plex_renamer/gui_qt/widgets/_job_detail_preview.py plex_renamer/gui_qt/widgets/job_detail_panel.py plex_renamer/gui_qt/widgets/history_tab.py tests/test_job_preview_grouping.py tests/test_qt_job_detail_panel.py
git commit -m "fix(gui): singular season label, unclipped empty-card message, history QWidget import"
```

---

### Task 2: Settings polish (Plan 8 leftovers)

**Files:**
- Modify: `plex_renamer/gui_qt/widgets/settings_tab.py:1-6,80-93` (docstring; keyword-only callbacks)
- Modify: `plex_renamer/gui_qt/widgets/_settings_tab_actions.py` (decline clears captions)
- Test: `tests/test_qt_main_window.py` (extend)

**Interfaces:**
- Consumes: Plan 8's `SettingsTab(..., history_count_callback=...)` + coordinator `clear_cache/clear_history(*, message_box_api)`; every existing construction is keyword-based.
- Produces: `SettingsTab.__init__(self, settings_service=None, cache_service=None, *, clear_tmdb_callback=None, clear_history_callback=None, history_count_callback=None, parent=None)` — the `*` is the only signature change. Declined confirms clear `_cache_confirm`/`_history_confirm`.

- [ ] **Step 1: Write the failing tests** — append to `QtMainWindowTests` in `tests/test_qt_main_window.py`:

```python
    def test_settings_tab_callbacks_are_keyword_only(self):
        import inspect

        from plex_renamer.gui_qt.widgets.settings_tab import SettingsTab

        params = inspect.signature(SettingsTab.__init__).parameters
        for name in (
            "clear_tmdb_callback",
            "clear_history_callback",
            "history_count_callback",
            "parent",
        ):
            self.assertEqual(
                params[name].kind, inspect.Parameter.KEYWORD_ONLY, name
            )

    def test_every_settings_page_carries_a_header_icon(self):
        from plex_renamer.gui_qt.widgets.settings_tab import SettingsTab

        tab = SettingsTab()
        nav = tab._settings_nav
        for row in range(nav.count()):
            page = tab._settings_stack.widget(row)
            pixmap = page._header_icon.pixmap()
            self.assertIsNotNone(pixmap, nav.item(row).text())
            self.assertFalse(pixmap.isNull(), nav.item(row).text())
        tab.close()

    def test_declined_confirms_clear_stale_captions(self):
        from plex_renamer.gui_qt.widgets.settings_tab import SettingsTab

        with TemporaryDirectory() as tmp:
            cache = PersistentCacheService(Path(tmp) / "cache.db")
            cache.put("tmdb.tv_details", "1", {"name": "Bleach"})
            tab = SettingsTab(
                cache_service=cache,
                clear_history_callback=lambda: (0, 0),
                history_count_callback=lambda: 3,
            )
            try:
                tab._cache_confirm.setText("Cleared 3 TMDB cache entries.")
                tab._history_confirm.setText("Cleared 2 history entries.")

                class _NoBox:
                    class StandardButton:
                        Yes = "yes"

                    @classmethod
                    def question(cls, parent, title, text):
                        return "no"

                tab._actions_coordinator.clear_cache(message_box_api=_NoBox)
                tab._actions_coordinator.clear_history(message_box_api=_NoBox)
                self.assertEqual(tab._cache_confirm.text(), "")
                self.assertEqual(tab._history_confirm.text(), "")
            finally:
                tab.close()
```

- [ ] **Step 2: Run to verify failures** — `.venv\Scripts\python.exe -m pytest tests\test_qt_main_window.py -q`
Expected: FAIL — params are `POSITIONAL_OR_KEYWORD`; captions keep their stale text on decline. (The icon-loop test passes already — it is the durable pin the Plan 8 review asked for; keep it.)

- [ ] **Step 3: Implement** —
  - `settings_tab.py` constructor — insert the `*` after `cache_service`:

```python
    def __init__(
        self,
        settings_service: "SettingsService | None" = None,
        cache_service=None,
        *,
        clear_tmdb_callback: Callable[[], None] | None = None,
        clear_history_callback: Callable[[], tuple[int, int]] | None = None,
        history_count_callback: Callable[[], int] | None = None,
        parent: QWidget | None = None,
    ) -> None:
```

  - `settings_tab.py` module docstring (lines 1-6) becomes:

```python
"""Settings tab.

Nav list + stacked section-card pages (Destinations, Display, Matching,
API Keys, Data, and the hidden Tools shell reserved for mkvmerge).  All
state goes through SettingsService.
"""
```

  - `_settings_tab_actions.py` — in `clear_history`, the declined branch becomes:

```python
        ) != message_box_api.StandardButton.Yes:
            tab._history_confirm.setText("")
            return
```

    and in `clear_cache`, the declined branch becomes:

```python
        ) != message_box_api.StandardButton.Yes:
            tab._cache_confirm.setText("")
            return
```

    (The zero-count early paths keep setting their "already empty" captions — only a declined question clears.)

- [ ] **Step 4: Run the covering file** — `.venv\Scripts\python.exe -m pytest tests\test_qt_main_window.py -q` → PASS.

- [ ] **Step 5: Full suites** — green, zero skips.

- [ ] **Step 6: Commit**

```bash
git add plex_renamer/gui_qt/widgets/settings_tab.py plex_renamer/gui_qt/widgets/_settings_tab_actions.py tests/test_qt_main_window.py
git commit -m "fix(gui): settings polish - kw-only callbacks, decline clears captions, icon pins, docstring"
```

---

### Task 3: Toasts/progress polish (Plan 6 M1–M5)

**Files:**
- Modify: `plex_renamer/gui_qt/widgets/scan_progress.py:388-391` (M3 filler gate)
- Modify: `plex_renamer/gui_qt/widgets/toast_manager.py:142,180` (M4 px tokens; `_scale` already imported at line 20)
- Test: `tests/test_qt_media_workspace.py` (M1), `tests/test_qt_workspace_widgets.py` (M2 pin + M3 test + M5 rename), `tests/test_qt_toasts.py` (M4 source pin)

**Interfaces:**
- Consumes: the queue-envelope flow in `_media_workspace_queue_actions.py` (`add_batch` raises → `warning_box.warning(workspace, "Queue Failed", str(exc))` + return before `queue_changed.emit()`, line 159); `ScanProgressWidget.update_progress(total=0)` → `_count_label` shows `"Working"` (scan_progress.py:377); `stop()` stops `_filler_timer` (line 350).
- Produces: test pins only, plus the M3 gate and M4 token migration. No API changes.

- [ ] **Step 1: M1 — write the "Queue Failed" companion test** — append to the test class in `tests/test_qt_media_workspace.py`, directly after `test_queue_post_success_sync_failure_reports_queued_with_warnings` (same fixture shapes, standalone copies):

```python
    def test_queue_batch_failure_reports_queue_failed_without_queue_changed(self):
        """add_tv_batch itself raised: box titled 'Queue Failed', and
        queue_changed must NOT be emitted (no jobs exist to learn about)."""
        from plex_renamer.gui_qt.widgets.media_workspace import MediaWorkspace

        class _ExplodingQueueController:
            def __init__(self):
                self.called = False

            def add_tv_batch(self, states, root, output_root, gating):
                self.called = True
                raise RuntimeError("queue boom")

        class _FakeMediaController:
            def __init__(self):
                self.command_gating = CommandGatingService()
                self.batch_states = []
                self.movie_library_states = []
                self.library_selected_index = None
                self.movie_folder = Path("C:/library/movies")
                self.tv_root_folder = Path("C:/library/tv")

            def select_show(self, index):
                self.library_selected_index = index
                if 0 <= index < len(self.batch_states):
                    return self.batch_states[index]
                return None

            def sync_queued_states(self):
                return None

        def _make_state(name: str, tmdb_id: int) -> ScanState:
            return ScanState(
                folder=Path(f"C:/library/tv/{name}"),
                media_info={"id": tmdb_id, "name": name, "year": "2024"},
                preview_items=[
                    PreviewItem(
                        original=Path(f"C:/library/tv/{name}/Season 01/{name}.S01E01.mkv"),
                        new_name=f"{name} (2024) - S01E01 - Pilot.mkv",
                        target_dir=Path(f"C:/library/tv/{name}/Season 01"),
                        season=1,
                        episodes=[1],
                        status="OK",
                    )
                ],
                scanned=True,
                checked=True,
                confidence=1.0,
            )

        with TemporaryDirectory() as tmp:
            settings = SettingsService(path=Path(tmp) / "settings.json")
            output = Path(tmp) / "tv-output"
            output.mkdir()
            settings.tv_output_folder = str(output)
            media_ctrl = _FakeMediaController()
            media_ctrl.batch_states = [_make_state("Show.One.2024", 101)]
            queue_ctrl = _ExplodingQueueController()

            workspace = MediaWorkspace(
                media_type="tv",
                media_controller=media_ctrl,
                queue_controller=queue_ctrl,
                settings_service=settings,
            )
            workspace.show_ready()

            calls = []

            class _Box:
                @staticmethod
                def warning(parent, title, text):
                    calls.append((title, text))

            fired = []
            workspace.queue_changed.connect(lambda: fired.append(True))
            workspace._action_coordinator.queue_states(
                media_ctrl.batch_states,
                empty_message="Select at least one actionable item before queueing.",
                warning_box=_Box,
            )
            self._app.processEvents()

            self.assertTrue(queue_ctrl.called)
            self.assertEqual(calls[0][0], "Queue Failed")
            self.assertIn("queue boom", calls[0][1])
            self.assertEqual(fired, [])                       # nothing queued, nothing to learn
            workspace.close()
```

- [ ] **Step 2: Run it** — `.venv\Scripts\python.exe -m pytest tests\test_qt_media_workspace.py -q -k queue_batch_failure`
Expected: **PASS** (this pins the landed failure side of the split envelope — a failure here is a finding; report it before changing anything).

- [ ] **Step 3: M2 — re-add the "Working" pin** — in `tests/test_qt_workspace_widgets.py`, inside `test_scan_progress_completes_prior_phases_when_lifecycle_skips_ahead` (line ~131), add one assertion after the `update_progress` call (that call passes no `done`/`total`, so `total=0` drives the `"Working"` branch at `scan_progress.py:377`):

```python
        self.assertEqual(widget._count_label.text(), "Working")
```

Run: `.venv\Scripts\python.exe -m pytest tests\test_qt_workspace_widgets.py -q` → **PASS** expected (pin; failure = finding).

- [ ] **Step 4: M3 — write the failing filler-gate test** — append to the same file's test class:

```python
    def test_straggler_update_after_stop_does_not_restart_filler_timer(self):
        from plex_renamer.app.models import ScanLifecycle
        from plex_renamer.gui_qt.widgets.scan_progress import ScanProgressWidget

        widget = ScanProgressWidget(media_type="tv")
        widget.start()
        widget.stop()
        widget.update_progress(
            lifecycle=ScanLifecycle.BUILDING_PREVIEWS,
            phase="straggler",
            current_item="Show Z",
            message="straggler",
        )
        self.assertFalse(widget._filler_timer.isActive())
        widget.close()
```

- [ ] **Step 5: Run to verify failure** — same command.
Expected: FAIL — the text block restarts `_filler_timer` unconditionally (`scan_progress.py:391`), leaving a perpetual no-op timer after `stop()`.

- [ ] **Step 6: M3 fix** — gate the restart on an active scan (`scan_progress.py:388-391`):

```python
            if item_text:
                self._set_item_text(item_text)
                self._filler_index = 0
                if self._elapsed_timer.isActive():
                    self._filler_timer.start()   # restart the 4s no-change window
```

Run the file again → PASS (the quips tests still pass: during a live scan `_elapsed_timer` is active).

- [ ] **Step 7: M4 — write the failing source pin** — append to the test class in `tests/test_qt_toasts.py` (mirrors the repo's source-pin idiom, e.g. `test_main_window_shell_resize_uses_scale_helper`):

```python
    def test_toast_card_sizing_routes_through_scale(self):
        from pathlib import Path

        source = Path("plex_renamer/gui_qt/widgets/toast_manager.py").read_text(encoding="utf-8")
        self.assertNotIn("setFixedHeight(3)", source)
        self.assertIn("setFixedHeight(_scale.px(3))", source)
        self.assertIn("+ _scale.px(4)", source)
```

- [ ] **Step 8: Run to verify failure** — `.venv\Scripts\python.exe -m pytest tests\test_qt_toasts.py -q` → FAIL.

- [ ] **Step 9: M4 fix** — in `toast_manager.py`: line 142 `self._progress.setFixedHeight(3)` → `self._progress.setFixedHeight(_scale.px(3))`; line 180 `collapsed = self._line_height() * _CLAMP_LINES + 4` → `collapsed = self._line_height() * _CLAMP_LINES + _scale.px(4)`. Run the file → PASS.

- [ ] **Step 10: M5 — rename the conveyor test** — in `tests/test_qt_workspace_widgets.py:220`, `test_scan_progress_conveyor_fills_cards_behind_the_beam` → `test_scan_progress_conveyor_advances_only_while_active` (body unchanged; the name now matches what it asserts — fill-behind-beam stays covered by Plan 6's recorded visual grabs).

- [ ] **Step 11: Run the covering files** — `.venv\Scripts\python.exe -m pytest tests\test_qt_media_workspace.py tests\test_qt_workspace_widgets.py tests\test_qt_toasts.py -q` → PASS.

- [ ] **Step 12: Full suites** — green, zero skips.

- [ ] **Step 13: Commit**

```bash
git add plex_renamer/gui_qt/widgets/scan_progress.py plex_renamer/gui_qt/widgets/toast_manager.py tests/test_qt_media_workspace.py tests/test_qt_workspace_widgets.py tests/test_qt_toasts.py
git commit -m "fix(gui): close plan-6 minors - queue-failed pin, working pin, filler gate, toast px tokens"
```

---

### Task 4: Guard tightening — broadened hex regex + 500-episode first-paint gate

**Files:**
- Modify: `tests/test_gui_theme.py:13` (`_HEX_RE`)
- Modify: `tests/test_qt_perf_guards.py` (extend)

**Interfaces:**
- Consumes: `_big_state(name, *, seasons, per_season)` (existing fixture, `test_qt_perf_guards.py:14`); `EpisodeTableView` + `EpisodeTableDelegate(view, media_type=...)` from `plex_renamer/gui_qt/widgets/_episode_table_delegate.py:41,357`; the wiring idiom at `_work_panel.py:323-324`.
- Produces: `_HEX_RE` catching 3/6/8-digit forms (used by both the tmpl scan and the repo-wide py scan); one new perf gate test. No production code changes.

- [ ] **Step 1: Write the failing regex test** — append to `tests/test_gui_theme.py`:

```python
def test_hex_guard_regex_catches_short_and_alpha_forms():
    # User-approved 2026-07-05 (Plan 1's open item): the guard covers all
    # QSS-legal hex literal widths, not just #rrggbb.
    assert _HEX_RE.search("#a1b2c3")
    assert _HEX_RE.search("#abc")            # 3-digit shorthand
    assert _HEX_RE.search("#a1b2c3ff")       # 8-digit with alpha
    assert not _HEX_RE.search("# a comment with hex words like abc")
    assert not _HEX_RE.search("#define")     # 'def' + word char = no boundary
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests\test_gui_theme.py -q`
Expected: FAIL — `#abc` and `#a1b2c3ff` don't match the 6-digit-only pattern.

- [ ] **Step 3: Broaden the regex** — `tests/test_gui_theme.py:13` (longest alternative first so 8-digit isn't half-matched as 6):

```python
_HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
```

- [ ] **Step 4: Run the whole guard file + fast suite** — `.venv\Scripts\python.exe -m pytest tests\test_gui_theme.py -q`, then `scripts\test-fast.cmd`.
Expected: PASS. If the broadened repo-wide scan now flags a comment (a `#`-word of 3 hex letters with no trailing word char — e.g. `#fee` inside prose), that is a **false positive to resolve by rewording the comment** (note it in your report) — never by narrowing the regex back.

- [ ] **Step 5: Write the 500-episode gate** — append to `PerfGuardTests` in `tests/test_qt_perf_guards.py`:

```python
    def test_cached_500_episode_populate_and_first_paint_under_budget(self):
        """Spec §18: synthetic 500-episode state; model population plus the
        first full paint pass stay under budget (generous offscreen margin).
        The 300-episode tests above pin the async invariants; this one is
        the release gate at the spec's stated size."""
        from PySide6.QtCore import QElapsedTimer

        from plex_renamer.app.services.episode_projection_cache import (
            EpisodeProjectionCacheService,
        )
        from plex_renamer.gui_qt.widgets._episode_table_delegate import (
            EpisodeTableDelegate,
            EpisodeTableView,
        )

        cache = EpisodeProjectionCacheService()
        state = _big_state("Huge Show", seasons=20, per_season=25)   # 500 eps
        cache.prepare_state(state)
        model = self._async_model(cache)
        view = EpisodeTableView()
        view.setItemDelegate(EpisodeTableDelegate(view, media_type="tv"))
        view.setModel(model)
        view.resize(900, 700)
        view.show()
        timer = QElapsedTimer()
        timer.start()
        model.show_state(state, collapsed_sections=set())
        pixmap = view.grab()                 # forces the first full paint pass
        elapsed_ms = timer.elapsed()
        self.assertIn("episode", {e.kind for e in model._entries})
        self.assertFalse(pixmap.isNull())
        self.assertLess(
            elapsed_ms, 1000,
            f"cached 500-episode populate + first paint took {elapsed_ms}ms "
            "offscreen (reference budget 200ms; 5x margin)",
        )
        view.close()
```

- [ ] **Step 6: Run it** — `.venv\Scripts\python.exe -m pytest tests\test_qt_perf_guards.py -q`
Expected: **PASS** with wide headroom (the cached 300-ep populate measured ~18ms in Plan 5; the paint pass only renders the visible viewport). A budget miss is a finding — report the measured time, do not raise the cap.

- [ ] **Step 7: Full suites** — green, zero skips.

- [ ] **Step 8: Commit**

```bash
git add tests/test_gui_theme.py tests/test_qt_perf_guards.py
git commit -m "test(gui): hex guard covers 3/8-digit forms; 500-episode first-paint perf gate"
```

---

### Task 5: Release gates + V4 close-out (controller)

**Files:**
- Modify: `docs/superpowers/plans/2026-07-03-gui-v4-implementation.md`, `docs/superpowers/plans/2026-07-03-gui-v4-handoff.md`

- [ ] **Step 1: Full suites** — `scripts\test-fast.cmd` + `scripts\test-smoke.cmd` → pass, zero skips. This re-runs every §18 sweep by construction (no-hex incl. broadened forms, no-Plex AST, no-processEvents, tone vocabulary, perf gates incl. the new 500-ep one); skim `.pytest_cache/smoke/latest.log`.

- [ ] **Step 2: DPI visual pass (§18: 100/150/200%)** — throwaway scratchpad script driven three times with `QT_SCALE_FACTOR` ∈ {1.0, 1.5, 2.0} (fresh process per factor — Qt reads it at init; set it in the env before launching, alongside `QT_QPA_PLATFORM=offscreen` and `QT_QPA_FONTDIR=C:\Windows\Fonts`; apply the real QSS via `theme.load_stylesheet()`). Scenes per factor, saved as `<scene>@<factor>.png`:
  (a) Settings **Display** page with one checked + one unchecked checkbox — the SVG check glyph must stay crisp and centered at every factor (the §12 DPI claim; this is what no automated test can see);
  (b) **QueueTab** with a pending + a running job (distinct `tmdb_id`s per job — the store's dedupe constraint) — painted status pills stay capsule-shaped with intact padding;
  (c) **EpisodeExpansionCard** with a SUB-badged companion, Part chips (future-policy stub table from Plan 8 Task 5's idiom), and the disabled `Merge…`;
  (d) a **toast card** (construct via the fixture idiom in `tests/test_qt_toasts.py` — grep `_ToastCard(` there and reuse the neighboring test's construction);
  (e) the **match picker dialog** (deviation 5's promised §16 visual confirmation — construct via the existing fixture idiom: grep `MatchPickerDialog(` under `tests/` and reuse that construction verbatim; if its fixture proves heavier than one test method, grab the episode assign dialog by the same rule instead and record which).
  Programmatic checks per grab: pixmap device size ≈ logical size × factor (DPR applied), wide-grid non-blank sampling (corners + midpoints — sparse scenes false-flag otherwise), no stray visible top-levels. Then read the saved images at 1.5 and 2.0 and verify by eye: no clipped glyphs, no half-pixel pill borders, no blurry check glyph. Any defect found is a fix-before-close finding.

- [ ] **Step 3: Real-library gate** — run `.venv\Scripts\python.exe scripts\scan_real_library.py` (full target set; several minutes of live TMDB calls). Protocol: exit 2 (P: drive absent) → record **"real-library validation blocked: P: not mounted"** in the handoff close-out and leave that gate's checkbox open for the user — never substitute another directory. If it runs: read `discovery.txt` + per-show dumps and compare against the round-5 baseline (the engine is untouched since — expect parity; any delta is a finding).

- [ ] **Step 4: Roadmap + handoff close-out, commit** — roadmap row 9 → Landed (commit range); handoff: status header → "V4 COMPLETE (pending merge decision)", check off Plan 9, collapse the "How to resume" list into a final-disposition block (fixed in Plan 9 / accepted-for-V4 per the plan's Recorded dispositions / blocked gates if any), session log entry.

```bash
git add docs/superpowers/plans
git commit -m "docs: mark GUI V4 plan 9 landed; V4 complete pending merge decision"
```

- [ ] **Step 5: Branch decision** — invoke `superpowers:finishing-a-development-branch` and present the merge/PR/keep options for `dev/GUI4` to the user. **Do not merge or push without their explicit choice.**

---

## Self-review notes (kept for the record)

- **§18 coverage:** unit + smoke sweep items all landed in Plans 1–8 and re-run in Task 5 Step 1; perf guard at the spec's stated 500-episode size + first paint → Task 4 (existing 300-ep async-invariant guards retained, disposition 6); DPI 100/150/200% → Task 5 Step 2 with per-factor scenes incl. the two surfaces only eyes can judge (SVG glyph, painted pills); real-library validation → Task 5 Step 3 with the P:-absent protocol from CLAUDE.md; `scripts/scan_real_library.py` itself stays unchanged per spec.
- **Carried-minor coverage:** Plan 7 leftovers → Task 1 (all three); Plan 8 leftovers → Task 2 (docstring, kw-only, decline captions, icon loop-pin) with packaging deferred by disposition 4 and the amended reveal-seam note already recorded in the handoff; Plan 6 M1–M5 → Task 3 (M1/M2 as pins, M3/M4 TDD'd, M5 rename), M6 by disposition 1; Plan 1's hex item → Task 4 per the user's approval (disposition 7).
- **Pin-vs-TDD honesty:** M1, M2, the icon loop-pin, and the 500-ep gate are labeled expected-PASS pins with the failure-is-a-finding protocol; genuine RED→GREEN cycles exist for the singular label, the clip fix, kw-only params, decline captions, the filler gate, the toast source pin, and the regex broadening.
- **Type consistency:** `_files_label` defined and consumed only in `_job_detail_preview.py`; `_update_empty_message` keeps its zero-arg signature (both call sites unchanged); the `*` insertion matches every verified keyword-based call site; `_HEX_RE` is module-level in `test_gui_theme.py` and both existing scans pick up the broadened pattern automatically; `EpisodeTableDelegate(view, media_type="tv")` matches `_episode_table_delegate.py:44` and the `_work_panel.py:323` wiring idiom; `_big_state("Huge Show", seasons=20, per_season=25)` matches the fixture's keyword-only signature.
- **Known risks:** the empty-card fix depends on Qt height-for-width behavior — the rendered-height test is the acceptance bar and the plan grants mechanism latitude with a recorded deviation; the broadened hex scan could flag a 3-hex comment word (explicit reword-don't-narrow instruction); `view.grab()` on the 500-ep view paints only the visible viewport by design — the budget line documents that this is a first-paint gate, not a full-scroll render.
