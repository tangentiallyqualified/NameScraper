# Settings And History Value Trust Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make settings cache numbers, cache clearing, history checked-job counts, revert counts, and job file counts reflect the exact operations the app will perform.

**Architecture:** Add namespace-prefix APIs to the persistent cache service, then consume those APIs in the Settings cache section so the label and clear action share the same scope. Tighten job-table checkability so "checked jobs" means jobs actionable for the current tab. Add selected primary/companion counters and use them in table and detail display without changing executor semantics.

**Tech Stack:** Python 3.12, PySide6, SQLite, unittest, pytest.

---

## File Structure

- Modify `plex_renamer/app/services/cache_service.py`
  - Add namespace-prefix invalidation and scoped stats.
  - Keep existing exact-namespace invalidation behavior for current callers.

- Modify `plex_renamer/gui_qt/widgets/_settings_tab_actions.py`
  - Use the same TMDB namespace prefix for displayed cache stats and the clear action.
  - Keep the existing runtime TMDB drop callback after persistent rows are deleted.

- Modify `plex_renamer/gui_qt/models/job_table_model.py`
  - Centralize which jobs are checkable in queue mode and history mode.
  - Prevent non-actionable jobs from entering the checked-job set.
  - Display primary file counts separately from companion counts.

- Modify `plex_renamer/gui_qt/widgets/_job_list_tab.py`
  - Make header select-all and tri-state calculations use only checkable visible jobs.

- Modify `plex_renamer/gui_qt/widgets/_history_tab_state.py`
  - Expose a single revertibility predicate shared by the history tab and table model.
  - Keep revert banner file counts based on undo rename records.

- Modify `plex_renamer/job_store.py`
  - Add explicit selected video and selected companion operation counters.
  - Leave `selected_count` as the total selected filesystem operations for executor and queue-removal workflows.

- Modify `plex_renamer/gui_qt/widgets/_job_detail_data.py`
  - Use selected primary and selected companion counts in compact facts.

- Modify tests:
  - `tests/test_cache_service.py`
  - `tests/test_qt_main_window.py`
  - `tests/test_qt_queue_history.py`
  - `tests/test_qt_job_detail_panel.py`

---

### Task 1: Add Cache Namespace Prefix APIs

**Files:**
- Modify: `tests/test_cache_service.py`
- Modify: `plex_renamer/app/services/cache_service.py`

- [ ] **Step 1: Write failing cache prefix tests**

Add these tests inside `CacheServiceTests` after `test_invalidate_namespace` in `tests/test_cache_service.py`:

```python
    def test_invalidate_namespace_prefix_removes_root_and_child_namespaces(self):
        self.cache.put("tmdb", "client_snapshot", {"movie_cache": {"1": {}}})
        self.cache.put("tmdb.tv_details", "1", {"name": "Bleach"})
        self.cache.put("tmdb.poster_image", "poster::200", {"png_base64": "abc"})
        self.cache.put("other", "key1", {"v": 3})

        deleted = self.cache.invalidate_namespace_prefix("tmdb")

        self.assertEqual(deleted, 3)
        self.assertFalse(self.cache.get("tmdb", "client_snapshot").is_hit)
        self.assertFalse(self.cache.get("tmdb.tv_details", "1").is_hit)
        self.assertFalse(self.cache.get("tmdb.poster_image", "poster::200").is_hit)
        self.assertTrue(self.cache.get("other", "key1").is_hit)

    def test_stats_can_be_scoped_to_namespace_prefix(self):
        self.cache.put("tmdb", "client_snapshot", {"movie_cache": {"1": {}}})
        self.cache.put("tmdb.tv_details", "1", {"name": "Bleach"})
        self.cache.put("tmdb.poster_image", "poster::200", {"png_base64": "abc"})
        self.cache.put("other", "key1", {"v": 3})

        all_stats = self.cache.stats()
        tmdb_stats = self.cache.stats(namespace_prefix="tmdb")

        self.assertEqual(all_stats["item_count"], 4)
        self.assertEqual(tmdb_stats["item_count"], 3)
        self.assertGreater(tmdb_stats["total_size_bytes"], 0)
        self.assertEqual(tmdb_stats["max_items"], 4000)
```

- [ ] **Step 2: Run cache tests to verify failure**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_cache_service.py -q
```

Expected: FAIL because `PersistentCacheService` has no `invalidate_namespace_prefix` method and `stats()` does not accept `namespace_prefix`.

- [ ] **Step 3: Implement namespace prefix invalidation and scoped stats**

In `plex_renamer/app/services/cache_service.py`, add this method after `invalidate_namespace`:

```python
    def invalidate_namespace_prefix(self, namespace_prefix: str) -> int:
        """Delete entries in a namespace and dot-child namespaces."""
        child_pattern = f"{namespace_prefix}.%"
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM cache_entries WHERE namespace = ? OR namespace LIKE ?",
                (namespace_prefix, child_pattern),
            )
            return cursor.rowcount
```

Replace the existing `stats` method with this version:

```python
    def stats(self, *, namespace_prefix: str | None = None) -> dict[str, int]:
        """Return aggregate cache statistics for auditing and tests."""
        query = "SELECT COUNT(*) AS item_count, COALESCE(SUM(size_bytes), 0) AS total_size FROM cache_entries"
        params: tuple[object, ...] = ()
        if namespace_prefix is not None:
            query += " WHERE namespace = ? OR namespace LIKE ?"
            params = (namespace_prefix, f"{namespace_prefix}.%")

        with self._connect() as conn:
            row = conn.execute(query, params).fetchone()
            return {
                "item_count": int(row["item_count"]),
                "total_size_bytes": int(row["total_size"]),
                "max_items": self._max_items,
                "max_size_bytes": self._max_size_bytes,
            }
```

- [ ] **Step 4: Run cache tests to verify pass**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_cache_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit cache service changes**

Run:

```powershell
git add plex_renamer/app/services/cache_service.py tests/test_cache_service.py
git commit -m "Fix cache namespace prefix accounting"
```

---

### Task 2: Make Settings Cache Values Use The Same TMDB Scope

**Files:**
- Modify: `tests/test_qt_main_window.py`
- Modify: `plex_renamer/gui_qt/widgets/_settings_tab_actions.py`

- [ ] **Step 1: Write failing SettingsTab cache scope test**

Add this test inside `QtMainWindowTests` after `test_settings_tab_async_api_key_test_updates_ui_via_bridge` in `tests/test_qt_main_window.py`:

```python
    def test_settings_tab_cache_stats_and_clear_use_tmdb_namespace_prefix(self):
        from tempfile import TemporaryDirectory
        from plex_renamer.gui_qt.widgets.settings_tab import SettingsTab

        with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            cache = PersistentCacheService(db_path=Path(tmp) / "cache.db")
            cache.put("tmdb", "client_snapshot", {"movie_cache": {"1": {}}})
            cache.put("tmdb.tv_details", "1", {"name": "Bleach"})
            cache.put("tmdb.poster_image", "poster::200", {"png_base64": "abc"})
            cache.put("other", "key1", {"v": 3})
            dropped_runtime_clients: list[bool] = []

            tab = SettingsTab(
                cache_service=cache,
                clear_tmdb_callback=lambda: dropped_runtime_clients.append(True),
            )
            self._app.processEvents()

            self.assertIn("3 entries", tab._cache_stats.text())

            tab._on_clear_cache()
            self._app.processEvents()

            self.assertEqual(dropped_runtime_clients, [True])
            self.assertEqual(tab._cache_confirm.text(), "Cleared 3 TMDB cache entries.")
            self.assertIn("0 entries", tab._cache_stats.text())
            self.assertTrue(cache.get("other", "key1").is_hit)
            tab.close()
```

- [ ] **Step 2: Run SettingsTab cache test to verify failure**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_qt_main_window.py::QtMainWindowTests::test_settings_tab_cache_stats_and_clear_use_tmdb_namespace_prefix -q
```

Expected: FAIL because the Settings tab currently counts every cache row in `stats()` and only clears the exact `"tmdb"` namespace.

- [ ] **Step 3: Implement scoped Settings cache display and clearing**

At the top of `plex_renamer/gui_qt/widgets/_settings_tab_actions.py`, add this module constant below the imports:

```python
_TMDB_CACHE_NAMESPACE_PREFIX = "tmdb"
```

Replace `clear_cache` with this version:

```python
    def clear_cache(self) -> None:
        tab = self._tab
        if tab._cache_service is None:
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

Replace the `stats = ...` line in `refresh_cache_stats` with:

```python
        stats = tab._cache_service.stats(namespace_prefix=_TMDB_CACHE_NAMESPACE_PREFIX)
```

Do not change `MainWindowTabsCoordinator`; it already passes `window._drop_tmdb_client` to `SettingsTab`, which drops runtime caches without persisting the old snapshot again.

- [ ] **Step 4: Run SettingsTab cache test to verify pass**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_qt_main_window.py::QtMainWindowTests::test_settings_tab_cache_stats_and_clear_use_tmdb_namespace_prefix -q
```

Expected: PASS.

- [ ] **Step 5: Run existing TMDB lifecycle tests**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_qt_main_window.py::QtMainWindowTests::test_main_window_restores_tmdb_snapshot_when_client_is_created tests/test_qt_main_window.py::QtMainWindowTests::test_main_window_persists_tmdb_snapshot_on_invalidate -q
```

Expected: PASS. Language/API-key invalidation should still persist a snapshot before dropping the client; Settings cache clearing should not.

- [ ] **Step 6: Commit Settings cache changes**

Run:

```powershell
git add plex_renamer/gui_qt/widgets/_settings_tab_actions.py tests/test_qt_main_window.py
git commit -m "Scope settings cache values to TMDB entries"
```

---

### Task 3: Make History Checked Counts Match Revertible Jobs

**Files:**
- Modify: `tests/test_qt_queue_history.py`
- Modify: `plex_renamer/gui_qt/widgets/_history_tab_state.py`
- Modify: `plex_renamer/gui_qt/models/job_table_model.py`
- Modify: `plex_renamer/gui_qt/widgets/_job_list_tab.py`

- [ ] **Step 1: Write failing history actionability test**

Add this test inside `QtQueueHistoryTests` after `test_history_tab_revert_uses_inline_confirmation_banner` in `tests/test_qt_queue_history.py`:

```python
    def test_history_header_and_revert_use_only_revertible_checked_jobs(self):
        from plex_renamer.app.controllers.queue_controller import QueueController
        from plex_renamer.gui_qt.widgets.history_tab import HistoryTab
        from plex_renamer.job_store import JobStore, RenameJob

        with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            store = JobStore(Path(tmp) / "jobs.sqlite3")
            queue_ctrl = QueueController(store)
            revertible = RenameJob(
                library_root="C:/library",
                source_folder="Show",
                media_name="Revertible Show",
                status=JobStatus.COMPLETED,
                undo_data={"renames": [{"old": "a", "new": "b"}, {"old": "c", "new": "d"}]},
            )
            completed_without_undo = RenameJob(
                library_root="C:/library",
                source_folder="NoUndo",
                media_name="Completed Without Undo",
                status=JobStatus.COMPLETED,
                undo_data=None,
            )
            failed_with_undo = RenameJob(
                library_root="C:/library",
                source_folder="Failed",
                media_name="Failed With Undo",
                status=JobStatus.FAILED,
                undo_data={"renames": [{"old": "x", "new": "y"}]},
            )
            store.add_job(revertible)
            store.add_job(completed_without_undo)
            store.add_job(failed_with_undo)

            history_tab = HistoryTab(queue_ctrl)
            self._app.processEvents()

            history_tab._header.checkStateChanged.emit(Qt.CheckState.Checked.value)
            selected_ids = {job.job_id for job in history_tab._selected_jobs()}

            self.assertEqual(selected_ids, {revertible.job_id})
            self.assertEqual(history_tab._selection_status.text(), "1 job checked")

            def row_for(job_id: str) -> int:
                for row, job in enumerate(history_tab._model.jobs()):
                    if job.job_id == job_id:
                        return row
                self.fail(f"Missing job row for {job_id}")

            self.assertEqual(
                history_tab._model.data(
                    history_tab._model.index(row_for(revertible.job_id), 0),
                    Qt.ItemDataRole.CheckStateRole,
                ),
                Qt.CheckState.Checked,
            )
            self.assertIsNone(
                history_tab._model.data(
                    history_tab._model.index(row_for(completed_without_undo.job_id), 0),
                    Qt.ItemDataRole.CheckStateRole,
                )
            )
            self.assertIsNone(
                history_tab._model.data(
                    history_tab._model.index(row_for(failed_with_undo.job_id), 0),
                    Qt.ItemDataRole.CheckStateRole,
                )
            )

            history_tab._revert_selected()

            self.assertEqual(history_tab._pending_revert_job_ids, [revertible.job_id])
            self.assertIn("1 job, 2 files", history_tab._revert_info.text())
            history_tab.close()
            queue_ctrl.close()
```

- [ ] **Step 2: Run history actionability test to verify failure**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_qt_queue_history.py::QtQueueHistoryTests::test_history_header_and_revert_use_only_revertible_checked_jobs -q
```

Expected: FAIL because header select-all currently checks every visible history row except reverted/revert-failed rows.

- [ ] **Step 3: Add shared history revertibility predicate**

In `plex_renamer/gui_qt/widgets/_history_tab_state.py`, add this function above `completed_revertible_jobs`:

```python
def is_revertible_job(job) -> bool:
    return job.status == JobStatus.COMPLETED and bool(job.undo_data)
```

Replace `completed_revertible_jobs` with:

```python
def completed_revertible_jobs(jobs: list) -> list:
    return [job for job in jobs if is_revertible_job(job)]
```

- [ ] **Step 4: Make table model checkability mode-aware**

In `plex_renamer/gui_qt/models/job_table_model.py`, add this public method after `checked_jobs`:

```python
    def is_checkable_job(self, job: RenameJob) -> bool:
        if self._history:
            return job.status == JobStatus.COMPLETED and bool(job.undo_data)
        return job.status == JobStatus.PENDING
```

Replace `set_checked_job_ids` with:

```python
    def set_checked_job_ids(self, job_ids: set[str]) -> None:
        valid_ids = {
            job.job_id
            for job in self._jobs
            if self.is_checkable_job(job)
        }
        normalized = set(job_ids) & valid_ids
        if normalized == self._checked_job_ids:
            return
        self._checked_job_ids = normalized
        self._emit_check_state_changed()
```

Replace the first two lines of `set_jobs_checked` with:

```python
        valid_ids = {
            job.job_id
            for job in self._jobs
            if self.is_checkable_job(job)
        }
        target_ids = set(job_ids) & valid_ids
```

Replace the `CheckStateRole` block in `data` with:

```python
        if role == Qt.ItemDataRole.CheckStateRole and column == 0:
            if not self.is_checkable_job(job):
                return None
            return Qt.CheckState.Checked if job.job_id in self._checked_job_ids else Qt.CheckState.Unchecked
```

Replace the body of the `if index.column() == 0:` block in `flags` with:

```python
            job = self._jobs[index.row()]
            if not self.is_checkable_job(job):
                return base
            return base | Qt.ItemFlag.ItemIsUserCheckable
```

Replace the beginning of `setData` after the index/role guard with:

```python
        job = self._jobs[index.row()]
        if not self.is_checkable_job(job):
            return False
        checked = value == Qt.CheckState.Checked
```

- [ ] **Step 5: Make header select-all operate on visible checkable rows**

In `plex_renamer/gui_qt/widgets/_job_list_tab.py`, replace `_select_all` with:

```python
    def _select_all(self) -> None:
        self._model.set_jobs_checked(self._visible_job_ids(checkable_only=True), True)
```

Replace `_visible_job_ids` with:

```python
    def _visible_job_ids(self, *, checkable_only: bool = False) -> set[str]:
        job_ids: set[str] = set()
        for row in range(self._proxy.rowCount()):
            proxy_index = self._proxy.index(row, 0)
            source_index = self._proxy.mapToSource(proxy_index)
            if not source_index.isValid():
                continue
            job = self._model.job_at(source_index.row())
            if job is None:
                continue
            if checkable_only and not self._model.is_checkable_job(job):
                continue
            job_ids.add(job.job_id)
        return job_ids
```

Replace the first line of `_sync_selection_widgets` with:

```python
        visible_ids = self._visible_job_ids(checkable_only=True)
```

- [ ] **Step 6: Run history actionability test to verify pass**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_qt_queue_history.py::QtQueueHistoryTests::test_history_header_and_revert_use_only_revertible_checked_jobs -q
```

Expected: PASS.

- [ ] **Step 7: Run queue/history smoke tests**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_qt_queue_history.py -q
```

Expected: PASS. Queue header selection should still select pending jobs; history header selection should select only completed jobs with undo data.

- [ ] **Step 8: Commit history actionability changes**

Run:

```powershell
git add plex_renamer/gui_qt/widgets/_history_tab_state.py plex_renamer/gui_qt/models/job_table_model.py plex_renamer/gui_qt/widgets/_job_list_tab.py tests/test_qt_queue_history.py
git commit -m "Align history selection with revertible jobs"
```

---

### Task 4: Separate Primary File Counts From Companion Counts

**Files:**
- Modify: `tests/test_qt_queue_history.py`
- Modify: `tests/test_qt_job_detail_panel.py`
- Modify: `plex_renamer/job_store.py`
- Modify: `plex_renamer/gui_qt/models/job_table_model.py`
- Modify: `plex_renamer/gui_qt/widgets/_job_detail_data.py`

- [ ] **Step 1: Write failing table count test**

Add this test inside `QtQueueHistoryTests` in `tests/test_qt_queue_history.py`:

```python
    def test_job_table_file_and_companion_columns_do_not_double_count(self):
        from plex_renamer.gui_qt.models.job_table_model import JobTableModel
        from plex_renamer.job_store import RenameJob, RenameOp

        model = JobTableModel(history=False)
        job = RenameJob(
            library_root="C:/library",
            source_folder="Show",
            media_name="Example Show",
            rename_ops=[
                RenameOp(
                    original_relative="Show/S01E01.mkv",
                    new_name="Example Show - S01E01.mkv",
                    target_dir_relative="Example Show/Season 01",
                    status="OK",
                    selected=True,
                    file_type="video",
                ),
                RenameOp(
                    original_relative="Show/S01E01.eng.srt",
                    new_name="Example Show - S01E01.eng.srt",
                    target_dir_relative="Example Show/Season 01",
                    status="OK",
                    selected=True,
                    file_type="subtitle",
                ),
                RenameOp(
                    original_relative="Show/S01E02.mkv",
                    new_name="Example Show - S01E02.mkv",
                    target_dir_relative="Example Show/Season 01",
                    status="OK",
                    selected=False,
                    file_type="video",
                ),
            ],
        )

        model.set_jobs([job])

        self.assertEqual(model.data(model.index(0, 5), Qt.ItemDataRole.DisplayRole), "1")
        self.assertEqual(model.data(model.index(0, 6), Qt.ItemDataRole.DisplayRole), "1")
```

- [ ] **Step 2: Write failing detail fact count test**

Add this test inside `QtJobDetailPanelTests` after `test_job_detail_panel_populates_compact_facts_card_without_duplicate_summary` in `tests/test_qt_job_detail_panel.py`:

```python
    def test_job_detail_panel_counts_primary_and_companion_files_separately(self):
        from plex_renamer.gui_qt.widgets.job_detail_panel import JobDetailPanel
        from plex_renamer.job_store import RenameJob, RenameOp

        panel = JobDetailPanel()
        panel.set_history_mode(True)
        job = RenameJob(
            library_root="C:/library",
            source_folder="Show",
            media_type="tv",
            media_name="Example Show",
            rename_ops=[
                RenameOp(
                    original_relative="Show/S01E01.mkv",
                    new_name="Example Show - S01E01.mkv",
                    target_dir_relative="Example Show/Season 01",
                    status="OK",
                    selected=True,
                    file_type="video",
                ),
                RenameOp(
                    original_relative="Show/S01E01.eng.srt",
                    new_name="Example Show - S01E01.eng.srt",
                    target_dir_relative="Example Show/Season 01",
                    status="OK",
                    selected=True,
                    file_type="subtitle",
                ),
            ],
        )

        panel.set_job(job)

        self.assertEqual(panel._fact_values["files"].text(), "1 selected")
        self.assertEqual(panel._fact_values["companions"].text(), "1")
        panel.close()
```

- [ ] **Step 3: Run count tests to verify failure**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_qt_queue_history.py::QtQueueHistoryTests::test_job_table_file_and_companion_columns_do_not_double_count tests/test_qt_job_detail_panel.py::QtJobDetailPanelTests::test_job_detail_panel_counts_primary_and_companion_files_separately -q
```

Expected: FAIL because both table and detail currently use `selected_count`, which includes companion operations.

- [ ] **Step 4: Add explicit selected primary and companion counters**

In `plex_renamer/job_store.py`, add these properties after `selected_count`:

```python
    @property
    def selected_video_ops(self) -> list[RenameOp]:
        """Selected primary media-file operations."""
        return [op for op in self.selected_ops if op.file_type == "video"]

    @property
    def selected_video_count(self) -> int:
        return len(self.selected_video_ops)

    @property
    def selected_companion_ops(self) -> list[RenameOp]:
        """Selected companion operations such as subtitle files."""
        return [op for op in self.selected_ops if op.file_type != "video"]

    @property
    def selected_companion_count(self) -> int:
        return len(self.selected_companion_ops)
```

- [ ] **Step 5: Use separated counts in table display and sorting**

In `plex_renamer/gui_qt/models/job_table_model.py`, replace the `DisplayRole` branch for `value_column == 4` with:

```python
            if value_column == 4:
                return str(job.selected_video_count)
```

Replace the `DisplayRole` branch for `value_column == 5` with:

```python
            if value_column == 5:
                comp = job.selected_companion_count
                return str(comp) if comp else ""
```

Replace the `SORT_ROLE` branch for `value_column == 4` with:

```python
            if value_column == 4:
                return int(job.selected_video_count or 0)
```

Replace the `SORT_ROLE` branch for `value_column == 5` with:

```python
            if value_column == 5:
                return int(job.selected_companion_count or 0)
```

- [ ] **Step 6: Use separated counts in job detail facts**

In `plex_renamer/gui_qt/widgets/_job_detail_data.py`, replace the first three lines of `build_job_fact_values` with:

```python
    companions = job.selected_companion_count
    files_text = f"{job.selected_video_count} selected"
    companions_text = str(companions) if companions else "None"
```

In `build_job_summary`, replace `companion = len(job.companion_ops)` with:

```python
    companion = job.selected_companion_count
```

- [ ] **Step 7: Run count tests to verify pass**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_qt_queue_history.py::QtQueueHistoryTests::test_job_table_file_and_companion_columns_do_not_double_count tests/test_qt_job_detail_panel.py::QtJobDetailPanelTests::test_job_detail_panel_counts_primary_and_companion_files_separately -q
```

Expected: PASS.

- [ ] **Step 8: Run broader queue/detail tests**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_qt_queue_history.py tests/test_qt_job_detail_panel.py tests/test_queue_controller.py -q
```

Expected: PASS. `selected_count` remains total selected operations, so executor and queue submission behavior should not change.

- [ ] **Step 9: Commit count display changes**

Run:

```powershell
git add plex_renamer/job_store.py plex_renamer/gui_qt/models/job_table_model.py plex_renamer/gui_qt/widgets/_job_detail_data.py tests/test_qt_queue_history.py tests/test_qt_job_detail_panel.py
git commit -m "Separate primary and companion job counts"
```

---

### Task 5: Final Verification

**Files:**
- Verify: `tests/test_cache_service.py`
- Verify: `tests/test_qt_main_window.py`
- Verify: `tests/test_qt_queue_history.py`
- Verify: `tests/test_qt_job_detail_panel.py`
- Verify: `tests/test_queue_controller.py`

- [ ] **Step 1: Run the focused regression suite**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_cache_service.py tests/test_qt_main_window.py tests/test_qt_queue_history.py tests/test_qt_job_detail_panel.py tests/test_queue_controller.py -q
```

Expected: PASS.

- [ ] **Step 2: Run the existing approved Qt/controller smoke subset**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_qt_workspace_widgets.py tests/test_media_controller.py tests/test_qt_main_window.py tests/test_tmdb.py
```

Expected: PASS.

- [ ] **Step 3: Inspect git diff for value-copy regressions**

Run:

```powershell
git diff -- plex_renamer/app/services/cache_service.py plex_renamer/gui_qt/widgets/_settings_tab_actions.py plex_renamer/gui_qt/models/job_table_model.py plex_renamer/gui_qt/widgets/_job_list_tab.py plex_renamer/gui_qt/widgets/_history_tab_state.py plex_renamer/job_store.py plex_renamer/gui_qt/widgets/_job_detail_data.py tests/test_cache_service.py tests/test_qt_main_window.py tests/test_qt_queue_history.py tests/test_qt_job_detail_panel.py
```

Expected:
- Settings cache stats call `stats(namespace_prefix="tmdb")`.
- Settings clear action calls `invalidate_namespace_prefix("tmdb")`.
- History checkboxes appear only for completed jobs with undo data.
- Header select-all uses visible checkable jobs.
- Files column uses selected primary video count.
- Companions column uses selected companion count.

- [ ] **Step 4: Commit final verification note if any test-only adjustment was needed**

If Task 5 required a test command fix or a small test cleanup, commit that isolated cleanup:

```powershell
git add tests/test_cache_service.py tests/test_qt_main_window.py tests/test_qt_queue_history.py tests/test_qt_job_detail_panel.py
git commit -m "Stabilize value trust regression tests"
```

If Task 5 made no file changes, do not create a commit.

---

## Self-Review

- Spec coverage: Task 1 and Task 2 cover inaccurate Settings cache values and clearing. Task 3 covers checked history jobs versus actionable revert jobs. Task 4 covers selected file counts versus companion counts. Task 5 covers regression verification.
- Concrete-content scan: The plan contains concrete file paths, method names, test code, implementation code, commands, and expected results.
- Type consistency: New APIs are `invalidate_namespace_prefix(namespace_prefix: str)`, `stats(namespace_prefix: str | None = None)`, `JobTableModel.is_checkable_job(job)`, `RenameJob.selected_video_count`, and `RenameJob.selected_companion_count`; later tasks use those same names.
