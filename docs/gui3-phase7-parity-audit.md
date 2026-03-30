# GUI3 Phase 7 Parity Audit

Date: 2026-03-29
Branch reviewed: `dev/GUI3`
Implementation range reviewed: `008662a` → `fb49779`

## Scope

This audit covers the PySide6 work delivered across:

1. Phase 3: shell skeleton
2. Phase 4: queue and history tabs
3. Phase 5: roster and preview workflow
4. Phase 6: detail panel and related media workflows

Reference documents:

- `docs/gui3-pyside6-migration-plan revised.md`
- `docs/gui3-pyside6-ui-design.md`

## Review Findings

### 1. Scan cancel in Qt is still a fake cancel

Severity: High

The scan progress widget exposes a Cancel button, but the Qt handler only hides the scanning page and never tells the controller or engine to stop work.

Current behavior:

- `MediaWorkspace._on_cancel_scan()` calls `show_empty()` only.
- Background discovery or scanning continues to run.
- The UI can return to READY later with updated state even though the user believes the scan was cancelled.

Relevant files:

- `plex_renamer/gui_qt/widgets/media_workspace.py`

Why this matters:

- It breaks user trust in progress feedback.
- It is worse than a missing cancel button because the UI implies cancellation happened.
- It fails the Phase 7 audit category for trustworthiness of progress feedback.

Recommended fix:

1. Add a real cancellation hook in `MediaController`.
2. Route the Qt cancel signal through that hook.
3. Reflect cancelled state back through `ScanProgress` instead of just swapping pages locally.

### 2. Runtime settings do not fully affect the active Qt session

Severity: Medium

The Qt shell persists several settings changes, but some of them do not update the live session after the shell has already created its shared TMDB client or rendered current views.

Current behavior:

- `MainWindow._ensure_tmdb()` caches a single `TMDBClient` instance.
- `SettingsTab._on_language()` updates `SettingsService.match_language`, but the existing `_tmdb` client is reused with the old language.
- `MainWindow._on_compact_toggled()` and `SettingsTab._on_view_mode()` persist the preference, but the media widgets do not re-render into a compact presentation.
- `MainWindow._on_companion_toggled()` and `SettingsTab._on_companion()` persist the preference, but the preview widget does not use it to render companion-file rows.

Relevant files:

- `plex_renamer/gui_qt/main_window.py`
- `plex_renamer/gui_qt/widgets/settings_tab.py`
- `plex_renamer/gui_qt/widgets/media_workspace.py`

Why this matters:

- The shell advertises settings that appear live but behave like restart-only toggles.
- This creates a mismatch between the UI design document and the actual widget behavior.

Recommended fix:

1. Invalidate and recreate the shared TMDB client when API key or language changes.
2. Emit a settings-changed event or callback from the settings tab.
3. Rebuild the roster/preview presentation when view mode or companion visibility changes.

### 3. Queue activity triggers expensive full roster rebuilds in both media tabs

Severity: Medium

Every queue state change refreshes both media workspaces, and each workspace fully clears and rebuilds its roster. During rebuild, each uncached roster item can start a new poster-fetch thread.

Current behavior:

- `MainWindow._on_queue_changed()` calls `refresh_from_controller()` on both media workspaces unconditionally.
- `MediaWorkspace.refresh_from_controller()` clears the entire `QListWidget` and recreates every header and row.
- `_request_roster_poster()` starts a new daemon thread per uncached poster request.

Relevant files:

- `plex_renamer/gui_qt/main_window.py`
- `plex_renamer/gui_qt/widgets/media_workspace.py`

Why this matters:

- Queue state transitions can cause unnecessary UI churn even when the user is not on a media tab.
- Repeated refreshes before poster threads complete can trigger duplicate in-flight fetch work.
- This is acceptable for small libraries but scales poorly for larger ones.

Recommended fix:

1. Limit queue-driven media refreshes to the active media workspace, or only when queue status actually changes a visible state.
2. Replace `QListWidget` full rebuilds with a model-driven list or incremental diff updates.
3. Deduplicate poster fetches with an in-flight key set or a shared thread pool.

### 4. Undo is exposed in the Qt shell but not actually implemented

Severity: Medium

The menu bar and shortcut wiring expose `Undo Last Rename`, but the action only posts a status-bar message.

Current behavior:

- `MainWindow._on_undo()` calls `QueueController.get_latest_revertible_job()`.
- If a revertible job exists, the UI reports `Undo not yet wired` instead of executing or presenting a real revert flow.

Relevant files:

- `plex_renamer/gui_qt/main_window.py`

Why this matters:

- It is a visible command with no operational behavior.
- The tkinter shell already has a working undo path.
- At Phase 7, this keeps tkinter as the safer shell for recovery workflows.

Recommended fix:

1. Wire Ctrl+Z to the queue/history revert flow.
2. Reuse the queue controller and a Qt confirmation surface.
3. Remove or hide the action until it works if implementation is deferred.

## Redundancies and Implementation Notes

These are lower-severity issues, but they are worth cleaning up before any retirement decision:

1. `MediaWorkspace` is carrying controller-sync logic, grouping logic, preview rendering, queue button state, and poster loading in a single widget class. It works, but it is accumulating responsibility quickly.
2. The queue/history widgets are intentionally model-based, but the roster/preview widgets are still imperative list rebuilds. That mixed approach is fine for the migration stage, but it creates two different UI architectures inside the same shell.
3. `SettingsTab` still uses a few inline `setStyleSheet()` calls for key-test status instead of the QSS-driven styling model described in the design doc.

## Phase 7 Assessment

### Overall status

The Qt shell is now genuinely usable for:

1. launching the app
2. scanning TV and movie libraries
3. reviewing rename previews
4. queueing jobs
5. executing and inspecting queue/history jobs
6. viewing posters and metadata for selected media

That is a meaningful milestone. The shell is no longer just a skeleton.

However, it is not yet ready for a tkinter retirement decision.

Reason:

The Qt shell still has a mix of unfinished operational features and trust issues that matter more than visual polish:

1. fake cancel
2. incomplete undo/revert access from the main shell
3. runtime settings that do not fully affect the live UI
4. missing rematch/manual correction flows

### Stability and trustworthiness

Current judgment: usable for active development, not yet the safer operational choice.

Why:

1. Queue/history basics are solid.
2. Media scanning and preview flows are largely functional.
3. But the progress/cancel story is still weaker than it appears.
4. Manual correction workflows are still materially behind tkinter.

## Qt vs tkinter Capability Comparison

### Qt is already stronger than tkinter in these areas

1. Shell structure is cleaner and more maintainable.
2. Queue and history are controller-backed and visually clearer.
3. Window geometry, splitter positions, recent folders, and tab persistence are better organized.
4. The scanning state machine is more explicit.
5. The settings surface is more coherent than the legacy settings flow.

### tkinter is still stronger than Qt in these operational areas

1. Manual rematch and correction workflows are already real.
2. Undo is actually implemented.
3. Preview interactions are richer for power-user correction flows.
4. Some recovery paths are operationally complete rather than placeholder-backed.

### Current recommendation

Keep tkinter as the safer shell for normal operation today.

Keep driving GUI3 forward, but do not retire tkinter until:

1. cancel is real
2. rematch/fix-match flows are real
3. undo/revert is accessible from the Qt shell
4. runtime settings visibly affect the active UI

## March 29 2026 Addendum

This audit predates the latest stabilization pass. The following findings are now partially or fully resolved in the working tree on `dev/GUI3`:

1. The Qt shell now shows the TV ready workspace before background batch episode scanning proceeds, which fixes the earlier problem where reviewable TV items could be hidden behind the scanning screen.
2. TV inline alternate-match suggestions now follow the same practical behavior as movie review suggestions: the top runner-up matches are preserved even when the review case is low-confidence.
3. TV batch discovery was hardened for release-style show roots containing `S01` in the folder name but real nested season directories underneath, fixing the Akiba Maid War style misclassification case.
4. The left roster review-card interaction is now tighter and clearer: alternate buttons collapse into a dedicated accept/cancel confirmation row instead of competing for the same vertical space.
5. The Qt batch-TV loading flow no longer lets the user drop into the ready workspace before background episode scanning is actually complete.
6. Qt roster status grouping now uses the real command-gating rule, so items that still need rename work remain under `Matched` instead of incorrectly presenting as `Plex Ready`.
7. The toast system is now real and stacked wrapped toast messages no longer clip.
8. Queue/history poster loading is materially stronger than this audit originally captured: TMDB metadata snapshots now persist across restarts, poster images and source images persist in the cache service, and queued/history jobs persist `poster_path` directly with lazy and startup backfill for older jobs.
9. TMDB session pool sizing was increased to reduce `urllib3` connection-pool warnings during concurrent poster loads without changing the request-rate ceiling.

What this changes in the assessment:

1. The earlier statement that rematch/manual correction flows are materially behind tkinter is no longer accurate for the core Fix Match path.
2. The earlier toast-related design-doc gap should now be treated as implemented with remaining polish work, not as a missing feature.
3. Queue/history poster persistence is no longer a material parity gap for repeat viewing across sessions; the remaining issues are more about operational controls than cache reuse.
4. The remaining retirement blockers are now more concentrated around real cancel, undo/revert access, live settings application, and broader operational trust rather than the basic TV review workflow itself.
5. GUI3 is closer to the Phase 7 exit gate than this audit originally recorded, but tkinter remains the safer operational shell until the remaining recovery and polish gaps are closed.

## UI Design Document Assessment

The UI design doc includes two kinds of features:

1. parity features that Qt still needs in order to match or exceed tkinter
2. intentionally new GUI3 features that were not visually present in tkinter and are meant to make the new shell better than a straight port

### Intended GUI3 features not visually present in tkinter

These were called for by `docs/gui3-pyside6-ui-design.md` as improvements, not as strict legacy parity items:

1. tab badges with queue/history counts and failure signaling
2. toast notifications for queue/job events
3. poster hero treatment with blurred/gradient backdrop
4. sticky season headers with progress bars in the preview panel
5. segmented visual filters in queue/history
6. inline revert confirmation banner instead of modal-first behavior
7. richer status-badge and confidence-bar presentation throughout the roster and preview cards
8. compact versus normal roster rendering as a true visual mode switch

These are important because the success condition for GUI3 is not just `same as tkinter`; the design doc explicitly expects the new shell to improve information clarity and future extensibility.

### Design-doc features already visible in Qt

1. top-level tab shell
2. empty-state folder selection with recent folders
3. structured scanning screen
4. bottom queue action bar for media tabs
5. roster poster thumbnails
6. grouped season preview presentation
7. right-side metadata panel with posters
8. settings tab sections
9. toast notifications for queue/job events
10. inline revert confirmation banner in queue/history

### Design-doc features still missing or only partially implemented in Qt

1. force rematch from the roster
2. fix-match controls in the preview cards
3. full companion-file rendering in preview cards
4. queue/history filter controls
5. richer toast semantics and notification policy tuning
6. tab badge failure pip / richer badge behavior
7. cache freshness presentation and refresh/cooldown visibility
8. poster hero background treatment
9. completeness report presentation matching the design intent

## Phase 7 Conclusion

### Current migration position

Phases 3-6 have produced a credible, increasingly usable Qt shell.

That shell is:

- beyond prototype status
- suitable for continued dogfooding
- structurally cleaner than the legacy UI

But it is not yet at the Phase 7 exit criteria where tkinter is no longer the safer operational choice.

### Recommended next focus

If the goal is to reach a real retirement decision, the next work should prioritize:

1. real cancel support
2. Qt undo/revert access from the main shell
3. live application of settings that are already exposed in the UI
4. queue/history polish required by the design doc that improves operational clarity, especially filtering and badge behavior
5. refresh-efficiency cleanup such as smarter roster refresh scope and poster-fetch deduplication once the operational blockers are closed