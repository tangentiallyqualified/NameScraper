# Audit findings review: GUI core and early widgets

## Scope and counts

This is a curated companion to the generated `docs/audit/maps/overview.md` checklist.

Reviewed the 57 non-Radon records in `.audit/analysis.json` at commit `486aaef` whose path is either under `plex_renamer/gui_qt/` but outside `widgets/`, or is under `widgets/` with a filename lexicographically no later than `_media_helpers.py`. The selection contains 12 GUI-core records and 45 early-widget records, all emitted by Vulture. Radon complexity records were excluded.

## Methodology

Each raw record was checked at its exact source line and then against repository-wide textual references, tests, surrounding control flow, inheritance, Qt virtual dispatch and property semantics, signal connections, model/delegate and drag/drop contracts, re-exports, dynamic lookup patterns, serialization, and the apparent public or test-introspection API. Duplicate assignments reported as separate raw records remain separate rows; an overwritten initialization can therefore differ from a later, observed assignment of the same attribute.

| Source | Candidate | Verdict | Evidence | Recommendation |
|---|---|---|---|---|
| `plex_renamer/gui_qt/_scale.py:52` | `row_height` | FALSE_POSITIVE | Directly exercised by `tests/test_qt_scale.py:42-52` and `tests/test_qt_scale.py:115-116`; the module contract also advertises it at `_scale.py:11-13`. | retain/document |
| `plex_renamer/gui_qt/app.py:140` | `_popup_filter` | CONFIRMED | No read exists. The filter is already parented to `app` at `app.py:138`, installed at `app.py:139`, and the local remains live while `app.exec()` blocks at `app.py:152`; this extra attribute write adds no lifetime protection. | remove |
| `plex_renamer/gui_qt/main_window.py:167` | `_restore_tmdb_cache_snapshot` | CONFIRMED | Repository-wide search finds only this private forwarding wrapper; initialization uses the coordinator directly at `main_window.py:76-80`, and no signal/string lookup names the wrapper. | remove |
| `plex_renamer/gui_qt/main_window.py:200` | `_refresh_media_workspaces` | CONFIRMED | Only definition in the repository; the live state operations call `self._state_coordinator` directly at `main_window.py:203-219`. | remove |
| `plex_renamer/gui_qt/main_window.py:248` | `_active_media_workspace_for_shortcuts` | CONFIRMED | Only definition in the repository; shortcut entry points delegate straight to `_shortcut_coordinator` at `main_window.py:251-275`. | remove |
| `plex_renamer/gui_qt/main_window.py:257` | `_text_input_focused` | CONFIRMED | Only definition in the repository; no Qt virtual or slot contract uses this private static wrapper, while `MainWindowShortcutCoordinator.text_input_focused()` is the actual implementation at `main_window.py:260`. | remove |
| `plex_renamer/gui_qt/main_window.py:279` | `_active_workspace` | CONFIRMED | Only definition in the repository; scan callbacks delegate directly to `_scan_coordinator` at `main_window.py:283-300`. | remove |
| `plex_renamer/gui_qt/main_window.py:346` | `_capture_active_snapshot` | CONFIRMED | Only definition in the repository; tab state is handled by `_state_coordinator` through `_on_tab_changed` at `main_window.py:343-344`, with no callback or dynamic lookup for this wrapper. | remove |
| `plex_renamer/gui_qt/main_window.py:363` | `_save_window_state` | CONFIRMED | Only definition in the repository; shutdown uses `_shell_coordinator.prepare_close()` at `main_window.py:372-374`, not this wrapper. | remove |
| `plex_renamer/gui_qt/models/job_status_filter_proxy_model.py:26` | `filterAcceptsRow` | FALSE_POSITIVE | This overrides `QSortFilterProxyModel.filterAcceptsRow`; Qt calls it while filtering after `set_allowed_statuses()` triggers invalidation at `job_status_filter_proxy_model.py:18-24`. | allowlist |
| `plex_renamer/gui_qt/models/job_status_filter_proxy_model.py:26` | `source_parent` | FALSE_POSITIVE | Required second argument of the Qt `filterAcceptsRow(source_row, source_parent)` virtual signature even though this flat model does not inspect the parent. | allowlist |
| `plex_renamer/gui_qt/models/job_table_model.py:193` | `headerData` | FALSE_POSITIVE | `QAbstractTableModel` virtual queried by `QTableView`; it is also called directly in `tests/test_qt_queue_history.py:75-77`. | allowlist |
| `plex_renamer/gui_qt/widgets/_automux_tracks.py:207` | `minimumSizeHint` | FALSE_POSITIVE | `QWidget` virtual consumed by parent layouts; the sizing contract and `QWidgetItem::sizeHint()` interaction are explicit at `_automux_tracks.py:208-234`. | allowlist |
| `plex_renamer/gui_qt/widgets/_bulk_assign_panel.py:201` | `mimeTypes` | FALSE_POSITIVE | `QAbstractItemModel` drag API virtual; the model marks rows drag-enabled at `_bulk_assign_panel.py:150-157`, and `mimeData()` emits this MIME type at lines 204-213. | allowlist |
| `plex_renamer/gui_qt/widgets/_bulk_assign_panel.py:227` | `startDrag` | FALSE_POSITIVE | `QAbstractItemView` virtual invoked because dragging is enabled at `_bulk_assign_panel.py:222-223`; it constructs and executes the `QDrag` at lines 228-237. | allowlist |
| `plex_renamer/gui_qt/widgets/_bulk_assign_panel.py:227` | `supportedActions` | FALSE_POSITIVE | Framework-supplied parameter required by the `QAbstractItemView.startDrag(supportedActions)` override signature; the implementation intentionally forces copy action at line 237. | allowlist |
| `plex_renamer/gui_qt/widgets/_bulk_assign_panel.py:329` | `is_claimed` | FALSE_POSITIVE | Direct test/introspection use at `tests/test_bulk_assign_panel.py:253-255`; it exposes `_claimed_keys` populated at `_bulk_assign_panel.py:264-267`. | retain/document |
| `plex_renamer/gui_qt/widgets/_bulk_assign_panel.py:395` | `dragEnterEvent` | FALSE_POSITIVE | Qt drag/drop event override; drops are enabled at `_bulk_assign_panel.py:381-382`, and this method gates the custom MIME type before the drop handler. | allowlist |
| `plex_renamer/gui_qt/widgets/_bulk_assign_panel.py:401` | `dragMoveEvent` | FALSE_POSITIVE | Qt drag/drop event override invoked during movement over the drop-only view configured at `_bulk_assign_panel.py:381-382`. | allowlist |
| `plex_renamer/gui_qt/widgets/_bulk_assign_panel.py:407` | `dropEvent` | FALSE_POSITIVE | Qt drop event override; it decodes the custom MIME payload and emits `pair_dropped` at `_bulk_assign_panel.py:417-424`, connected at line 497. | allowlist |
| `plex_renamer/gui_qt/widgets/_bulk_assign_panel.py:442` | `_claimed_file_by_key` | CONFIRMED | This empty initialization is overwritten unconditionally by `show_state()` at `_bulk_assign_panel.py:551-555` before every observed test read; production has no read of the field. | remove |
| `plex_renamer/gui_qt/widgets/_bulk_assign_panel.py:551` | `_claimed_file_by_key` | FALSE_POSITIVE | The populated mapping is read repeatedly by tests, e.g. `tests/test_bulk_assign_panel.py:244`, `:267`, `:380`, `:484`, and `:522`; it is intentional test introspection. | retain/document |
| `plex_renamer/gui_qt/widgets/_bulk_assign_panel.py:679` | `_select_file` | FALSE_POSITIVE | Directly called at `tests/test_bulk_assign_panel.py:523`, which verifies that the claimed file selects/highlights its episode slot at lines 524-526. | retain/document |
| `plex_renamer/gui_qt/widgets/_episode_expansion.py:137` | `paintEvent` | FALSE_POSITIVE | `QWidget.paintEvent` override for `_ChipStrip`; Qt invokes it to render the chip row built at `_episode_expansion.py:125-140`. | allowlist |
| `plex_renamer/gui_qt/widgets/_episode_expansion.py:158` | `_copy_buttons` | CONFIRMED | Constructor initialization is overwritten by `_reset_content()` at `_episode_expansion.py:392` before the only read, after `show_episode()`, in `tests/test_episode_expansion.py:113-124`. | remove |
| `plex_renamer/gui_qt/widgets/_episode_expansion.py:162` | `_header_row` | CONFIRMED | The `None` initialization is overwritten synchronously during `_build_ui()` at `_episode_expansion.py:210-214`; no read can occur between those writes. | remove |
| `plex_renamer/gui_qt/widgets/_episode_expansion.py:214` | `_header_row` | FALSE_POSITIVE | The assigned layout is inspected at `tests/test_episode_expansion.py:336-339` to verify the status pill is the last header widget. | retain/document |
| `plex_renamer/gui_qt/widgets/_episode_expansion.py:322` | `header_action_buttons` | FALSE_POSITIVE | Explicit “Test/introspection accessor” (`_episode_expansion.py:320`), called at `tests/test_episode_expansion.py:326` and `:368`. | retain/document |
| `plex_renamer/gui_qt/widgets/_episode_expansion.py:327` | `action_buttons` | FALSE_POSITIVE | Explicit test/introspection accessor, called at `tests/test_episode_expansion.py:328` to verify below-fold action placement. | retain/document |
| `plex_renamer/gui_qt/widgets/_episode_expansion.py:331` | `status_pill_text` | FALSE_POSITIVE | Explicit test/introspection accessor, called at `tests/test_episode_expansion.py:335` to verify rendered status/confidence text. | retain/document |
| `plex_renamer/gui_qt/widgets/_episode_expansion.py:334` | `mux_optout_button` | FALSE_POSITIVE | Directly exercised at `tests/test_episode_expansion.py:429-455` and `tests/test_workspace_expansion.py:701-715`; exposes the control built at `_episode_expansion.py:487`. | retain/document |
| `plex_renamer/gui_qt/widgets/_episode_expansion.py:392` | `_copy_buttons` | FALSE_POSITIVE | This reset value is read by `tests/test_episode_expansion.py:124` as the regression assertion that source rows contain no copy buttons. | retain/document |
| `plex_renamer/gui_qt/widgets/_episode_table_delegate.py:92` | `expansion_requested` | CONFIRMED | Repository-wide search finds only the declaration: no emit or connection. Expansion instead flows through `EpisodeTableView` and `openPersistentEditor()` at `_media_workspace_state.py:135`. | remove |
| `plex_renamer/gui_qt/widgets/_episode_table_delegate.py:338` | `createEditor` | FALSE_POSITIVE | `QStyledItemDelegate` virtual invoked by `QListView.openPersistentEditor()` at `_media_workspace_state.py:135`; provider wiring occurs at `_media_workspace_ui.py:147`. | allowlist |
| `plex_renamer/gui_qt/widgets/_episode_table_delegate.py:350` | `updateEditorGeometry` | FALSE_POSITIVE | `QStyledItemDelegate` virtual invoked by Qt to place the persistent editor created above; it applies the view-supplied `option.rect`. | allowlist |
| `plex_renamer/gui_qt/widgets/_episode_table_model.py:123` | `collapsible` | CONFIRMED | `_Entry.collapsible` is written at `_episode_table_model.py:632` and `:774` but never read, serialized, or dynamically looked up; section behavior uses `kind`, `section_key`, and `_collapsed_sections` instead. | remove |
| `plex_renamer/gui_qt/widgets/_episode_table_model.py:246` | `filter_mode` | FALSE_POSITIVE | Direct test/introspection use at `tests/test_qt_media_workspace.py:2803` and `:2810`; the paired setter drives rebuilds at `_episode_table_model.py:240-244`. | retain/document |
| `plex_renamer/gui_qt/widgets/_episode_table_model.py:256` | `search_text` | CONFIRMED | No call or dynamic lookup exists; production only uses `set_search_text()` from `media_workspace.py:231` and reads `_search_text` internally at `_episode_table_model.py:899-902`. | remove |
| `plex_renamer/gui_qt/widgets/_episode_table_model.py:266` | `episode_search` | CONFIRMED | No call or dynamic lookup exists; production uses `set_episode_search()` at `media_workspace.py:235` and reads `_episode_search` internally at `_episode_table_model.py:906-918`. | remove |
| `plex_renamer/gui_qt/widgets/_episode_table_model.py:330` | `row_for_preview_index` | FALSE_POSITIVE | Used by Qt workspace tests and fixtures, including `tests/conftest_qt.py:133` and `tests/test_qt_media_workspace.py:1736`, `:1835`, and `:2367`. | retain/document |
| `plex_renamer/gui_qt/widgets/_episode_table_model.py:394` | `refresh_checks` | CONFIRMED | No caller exists; `_work_panel.py:385` mentions it only in a stale comment, while actual check refreshes use other model rebuild paths. | remove |
| `plex_renamer/gui_qt/widgets/_image_utils.py:104` | `ShimmerOverlay` | CONFIRMED | No import, construction, re-export, or dynamic lookup exists anywhere in production or tests. | remove |
| `plex_renamer/gui_qt/widgets/_image_utils.py:128` | `paintEvent` | FALSE_POSITIVE | This is the required `QWidget.paintEvent` override for `ShimmerOverlay`; its animation setter requests repaint at `_image_utils.py:122-124`. The enclosing class is independently confirmed dead above. | remove with class |
| `plex_renamer/gui_qt/widgets/_job_detail_poster.py:90` | `_poster_pixmap` | CONFIRMED | Repository-wide search finds declarations/writes only (`job_detail_panel.py:231`, `:432`, `:461` and this workflow); rendering uses the local `pixmap` and `QLabel.setPixmap()` at `_job_detail_poster.py:85-100`. | remove |
| `plex_renamer/gui_qt/widgets/_job_detail_poster.py:110` | `_poster_pixmap` | CONFIRMED | Clearing this write has no observer; the visible state is cleared independently with `panel._poster.setPixmap(QPixmap())` and `setText()` at `_job_detail_poster.py:111-112`. | remove |
| `plex_renamer/gui_qt/widgets/_job_list_tab.py:138` | `backgroundBrush` | FALSE_POSITIVE | `backgroundBrush` is a `QStyleOptionViewItem` data field consumed by the subsequent `super().paint(...)` call at `_job_list_tab.py:151`; setting `NoBrush` suppresses duplicate per-cell background painting. | allowlist |
| `plex_renamer/gui_qt/widgets/_job_list_tab.py:402` | `_insert_panel_before_detail` | CONFIRMED | Only definition in the repository; subclasses finish the pane through `_finish_list_pane()` at `_job_list_tab.py:405-410`, with no dynamic dispatch to this helper. | remove |
| `plex_renamer/gui_qt/widgets/_media_helpers.py:23` | `file_count_for_state` | CONFIRMED | No import, call, re-export, serializer, or dynamic lookup exists repository-wide. | remove |
| `plex_renamer/gui_qt/widgets/_media_helpers.py:192` | `state_match_summary` | CONFIRMED | No import or call exists; even its `threshold` parameter is unused in the body at `_media_helpers.py:192-204`. | remove |
| `plex_renamer/gui_qt/widgets/_media_helpers.py:230` | `roster_signature` | CONFIRMED | No import or call exists; current roster modules import other named helpers from `_media_helpers.py`, not this function. | remove |
| `plex_renamer/gui_qt/widgets/_media_helpers.py:254` | `match_label` | CONFIRMED | No import or call exists. Similarly named `fix_match_label` functions at `_media_workspace_action_state.py:26` are distinct and do not resolve dynamically to it. | remove |
| `plex_renamer/gui_qt/widgets/_media_helpers.py:295` | `preview_band` | CONFIRMED | No import or call exists; live code consumes `preview_band_name` instead, including the import in `_episode_table_model.py:17`. | remove |
| `plex_renamer/gui_qt/widgets/_media_helpers.py:307` | `preview_heading` | CONFIRMED | No import, call, re-export, or dynamic lookup exists repository-wide. | remove |
| `plex_renamer/gui_qt/widgets/_media_helpers.py:316` | `preview_target_text` | CONFIRMED | No import, call, re-export, or dynamic lookup exists repository-wide. | remove |
| `plex_renamer/gui_qt/widgets/_media_helpers.py:321` | `tv_preview_sort_key` | CONFIRMED | No import or call exists; current table/roster ordering is implemented elsewhere and no serializer references this name. | remove |
| `plex_renamer/gui_qt/widgets/_media_helpers.py:340` | `companion_summary` | CONFIRMED | No import, call, re-export, or dynamic lookup exists repository-wide. | remove |
| `plex_renamer/gui_qt/widgets/_media_helpers.py:374` | `make_section_header` | CONFIRMED | No import or call exists; the `QListWidgetItem` construction is isolated to this dead helper and widgets package `__init__.py` does not re-export it. | remove |

## Verdict totals

- FALSE_POSITIVE: 27
- CONFIRMED: 30
- UNCERTAIN: 0
- Total: 57

## Cross-cutting patterns

- Qt dispatch accounts for 15 false positives: model/delegate/view/widget virtuals, required callback parameters, drag/drop event hooks, and the `QStyleOptionViewItem.backgroundBrush` field are reached or consumed by Qt rather than by an ordinary Python name reference.
- Test and introspection contracts account for 12 false positives, including scale behavior, bulk-assignment helpers, expansion-card accessors, and model lookup/getter APIs.
- The confirmed findings cluster into seven unused `MainWindow` forwarding wrappers, ten orphaned `_media_helpers` presentation functions, stale getters/signals/helpers, and write-only legacy fields.
- Duplicate attribute findings need write-level treatment: the constructor writes at `_bulk_assign_panel.py:442`, `_episode_expansion.py:158`, and `_episode_expansion.py:162` are overwritten before observation, while their later assignments are test-observed and therefore separate false positives.
- `ShimmerOverlay` is dead as a class, but its `paintEvent` is still a genuine Qt override if the class were retained; remove the method only as part of removing the class.

## 2026-07-17 postscript

This partition's 30 `CONFIRMED` records are part of the review's 108-record total remediated on `dev/audit-debt3` (PRs #20-#23); see [findings-review.md](findings-review.md) for the full outcome (including the two confirmed layer-contract violations, both in the Non-GUI partition). The generated checklist ([maps/overview.md](maps/overview.md)) has been regenerated since; these verdicts remain the unmodified historical record of the original triage and are not rewritten.
