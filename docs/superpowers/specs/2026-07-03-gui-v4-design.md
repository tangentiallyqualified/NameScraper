# GUI V4 Design — Two-Panel Workspace, Jellyfin Theme, Performance

**Date:** 2026-07-03 · **Branch:** `dev/GUI4` · **Status:** awaiting user review
**Scope:** design only. Implementation follows in `docs/superpowers/plans/2026-07-03-gui-v4-implementation.md` after approval.

## 1. Context and goals

GUI3 is a 5-tab PySide6 shell (Settings / TV / Movies / Queue / History). The TV and Movies tabs each host a 3-panel workspace: roster (show list), preview (episode guide), detail (poster + facts + action buttons). The user's brief for V4:

1. Consolidate middle + right panels into one work panel (TV and movie modes).
2. Remove information that doesn't help renaming; keep show/episode descriptions, air date, and the detail panel's action buttons.
3. Eliminate UI lag when switching shows or rearranging content; never freeze without a visible busy indicator.
4. Make episode match auditing and bulk reassignment intuitive.
5. Replace the Plex color scheme with a Jellyfin-style dark theme; remove all "Plex" mentions ("Plex Ready" → "Fully Ready").
6. Enlarge the left panel; make posters prominent.
7. At-a-glance seasonal completeness.
8. Leave data-model and layout room for mkvmerge support (subtitle merge + multi-part merge) **without wiring it**.
9. Expandable, copyable toasts.
10. New loading screen and animation with honest progress + playful filler.
11. Remove the colored left-edge fringe from cards; use graceful shading.
12. Restyle Queue, History, and Settings.
13. Consistent corner radii; fewer crammed hairlines.
14. Keep high-DPI correctness.

Non-goals for V4: wiring mkvmerge, changing engine/controller scan or matching logic, changing the queue execution model, adding new metadata sources.

## 2. Approaches considered

**A. Model/View rebuild of the workspace (recommended).** Replace the `QListWidget` + per-row live widget architecture with `QAbstractItemModel`s + `QStyledItemDelegate`-painted views (the Queue/History tabs already work this way and don't lag). Consolidate panels while we're inside the workspace anyway. Theme becomes token-driven.
*Trade-off:* the workspace view layer is rewritten (roster + preview + detail widgets), so workspace GUI tests need migration. Controllers, services, and engine stay untouched — the blast radius is contained to `gui_qt/widgets`.

**B. Restyle-only.** Keep widget-per-row lists; merge panels by moving detail content into the preview header; restyle everything. Lower effort, but the lag has structural causes (thousands of live widgets, synchronous cache warming — see §7) that styling cannot fix. Fails goal 3 at scale.

**C. Qt Quick/QML rewrite.** Best animation ceiling, but a full-shell rewrite in a new technology, throwing away a working widgets stack and its test suite. Disproportionate to the goals.

**Recommendation: A.** B fails the performance goal; C is unjustified risk. A reuses the pattern already proven in this codebase.

## 3. Two-panel workspace layout

The workspace keeps its EMPTY → SCANNING → READY state machine. READY becomes a two-panel splitter:

```
┌────────────────────────┬──────────────────────────────────────────────┐
│  ROSTER (left, ~380px) │  WORK PANEL (right, rest)                    │
│                        │                                              │
│  ▼ NEEDS REVIEW (2)    │  ┌ Show header ──────────────────────────┐   │
│  ┌──────────────────┐  │  │ Frieren: Beyond Journey's End (2023)  │   │
│  │ [poster] Title   │  │  │ TMDB · 96% · [status pill]            │   │
│  │  96% ▮▮▮▮▮▮▮▮▯   │  │  │ Overview text, 2-line clamp… [more]   │   │
│  │  S1 ✓  S2 9/10   │  │  └───────────────────────────────────────┘   │
│  └──────────────────┘  │  Season strip: [S1 ✓28] [S2 9/10] [SP 0/3]   │
│  ▼ SPECIALS/EXTRAS (1) │  Toolbar: [All|Problems|Unmapped] [search]   │
│  ▼ FULLY READY (12) ▸  │           Approve All · ⚠Unassign All        │
│  ▼ QUEUED (3)          │  ┌ Episode table (virtualized) ─────────┐    │
│  …                     │  │ ▸ Season 1 — 28/28 ✓                 │    │
│                        │  │ ▾ Season 2 — 9/10 · 1 missing        │    │
│  [Select all] [Queue]  │  │   S02E01 · Title        [Mapped]     │    │
│                        │  │   S02E02 · Title        [Review]     │    │
│                        │  │   ▾ (expanded row: full filenames,   │    │
│                        │  │      target, overview, air date,     │    │
│                        │  │      companions, actions)            │    │
│                        │  │   S02E03 · — missing —               │    │
│                        │  └──────────────────────────────────────┘    │
│                        │  Footer: file breakdown + [Fix Match]        │
│                        │          [Queue Show] (primary)              │
└────────────────────────┴──────────────────────────────────────────────┘
```

### 3.1 Roster (left panel)

- **Wider default** (~380px logical vs 320) and poster-forward rows: poster ~64×94 normal mode (up from 48×70), title on top, then one confidence row, then a **season chip row** (§4). Compact mode keeps a slim poster-less row.
- **Removed from rows:** the "N file(s)" count and the meta clutter ("TMDB - 93% - needs review" collapses into the confidence bar + status pill). File-level truth moves to the work panel footer.
- **Kept:** match confidence (bar + %), status pill, toggle check for queueing.
- **Group taxonomy** (order): `Queued` · `Needs Review — Match` · `Needs Review — Episodes` · `Specials & Unmapped Only` *(new)* · `Matched` · `Fully Ready` *(renamed, collapsed by default)* · `No Match Found` · `Duplicates`.
  - `Specials & Unmapped Only`: all *regular* (season ≥ 1) episodes are mapped cleanly; only specials, extras, or unmapped non-regular files need review. Derived from `CompletenessReport` + `EpisodeGuide` — no engine change; classification lives in `_media_helpers.roster_group`.
  - Review groups float to the top so work-to-do is above the fold; Fully Ready stays collapsed.
- Selection = accent border + raised surface; no left fringe (§8).

### 3.2 Work panel (right panel)

One panel, five zones, top to bottom:

1. **Show header:** title + year, source/confidence pill, status pill, show overview clamped to 2 lines with "more" expander. No poster here — the roster carries the artwork; header stays compact. (Movie mode: movie title + overview.)
2. **Season strip:** horizontal chip per season (§4). Clicking a chip scrolls to and flash-highlights that season's header in the table; chips for fully-missing seasons jump to the missing block.
3. **Toolbar:** view filters (All / Problems / Unmapped) as a segmented control, a filename search box (filters rows live — the fastest way to audit a specific file), `Approve All` (visible only when review rows exist), and `Unassign All` restyled as a **danger-outline button, right-aligned, with a confirmation dialog** stating the count and offering "Unassign and open Bulk Assign" (§6).
4. **Episode table** (the workhorse): virtualized tree view. Season headers are branch rows showing `Season N — matched/expected` plus missing-episode summary. Episode rows are single-line: `S02E04 · Episode Title · [status pill]`, with a subtle two-line variant when filenames are shown inline (view option). **Missing episodes render as ghost rows in place** — the user sees gaps in sequence without scrolling to a separate section. Row click selects; second click (or chevron / Enter) **expands the row in place** to a detail card:
   - full source filename(s), path-wrapped, never elided, with a copy button
   - full target filename, same treatment
   - episode overview + air date (the old right panel's useful content, now contextual)
   - companion files listed by name with type badges (sub/nfo/artwork)
   - actions: Approve · Reassign… · Assign to more… · Unassign · (Conflict rows: Keep this file) — plus a reserved, disabled `Merge…` slot (§13)
   Only one expanded row at a time; expansion uses a persistent editor widget so exactly one live widget exists regardless of list size.
5. **Footer / action bar:** the accurate file breakdown the user asked to relocate — `42 files · 38 mapped · 2 companions · 1 unmapped · 1 duplicate` (from `EpisodeGuideSummary`) — plus the two buttons inherited from the old detail panel: `Fix Match` (secondary) and the primary queue action. Queue-preflight blockers surface as a single line above the buttons.

Unmapped primary files, duplicates, and orphan companions remain sections in the table (after seasons), same as today, but rendered by the same delegate and included in Problems filter.

### 3.3 Movie mode parity

Movies get the same shell with the season strip hidden: header (title/overview/confidence), toolbar (master check + summary replaces episode filters), file table (delegate-painted rows: source → target, status pill, companions), expandable rows with full filenames + copy, footer breakdown + same buttons. `MediaDetailPanel` is deleted for both modes.

## 4. Seasonal completeness UX

Data already exists (`CompletenessReport.seasons[n] = {expected, matched, missing[]}` + specials). Two surfaces:

- **Roster chip row (glanceable):** compact chips `S1 ✓ · S2 9/10 · SP 2/12`. Complete seasons render dim/success; incomplete render warning with the ratio; fully-missing render muted. More than ~5 seasons: collapse complete runs (`S1–S4 ✓`) and always show problem seasons explicitly. Tooltip lists missing episode numbers.
- **Work panel season strip (actionable):** same chips, larger, clickable (scroll-to-season), with counts always visible. Season header rows in the table repeat `matched/expected` and name missing episodes (`missing E03, E07`) so nothing requires scrolling hunting.

## 5. Information removed (goal 2)

- Detail panel facts grid (6-row key/value table): folder paths, discovery info, etc. → gone. Discovery info remains available via the existing settings toggle but renders as one caption line in the show header, not a grid.
- Roster meta line ("N file(s) · TMDB - 93% - needs review · Season 2 · 2 alternatives") → replaced by pill + confidence bar + chips.
- Preview summary sentence ("12 mapped - 14 files incl. companions - …") → replaced by footer breakdown with real numbers, styled, not a prose string.
- Backdrop/landscape artwork mode in detail panel → gone with the panel.
- Status pill duplication (roster row pill hidden today but code keeps it) → one pill, actually shown.

## 6. Episode audit and bulk reassignment

**Single-row fixes** stay on the row (expanded card actions; ⋯ menu equivalents), using the existing `EpisodeAssignDialog` / `pick_file` flows — but those dialogs get restyled and gain full-filename display.

**Bulk Assign mode** (new) replaces the unmap-then-modal-grind:

- Entry points: toolbar overflow "Bulk Assign…", the post-Unassign-All offer, and the Problems filter empty-state hint when many rows are unmapped.
- The episode table swaps to a two-pane assignment surface (still inside the work panel): left = ordered unassigned files (checkboxes, shift-range select, search), right = episode slot list (season-grouped, shows current claims and missing slots).
- Primary interaction: check N files, click a starting slot, press **Assign in order** → files map to contiguous slots from there (existing contiguity rules validate). Secondary: **Auto-map remaining** (filename-order → remaining-slot-order, preview before apply), and drag a file onto a slot for one-off pairs.
- Nothing touches the controller until **Apply** — one batched assignment call, one table refresh, one toast. Cancel discards. This also makes the operation cheap to render (§7).
- Movie mode: not applicable (no slots); button hidden.

**Unassign All** becomes visibly destructive: danger-outline style, physically separated from filters, confirm dialog with exact count, and the bulk-assign offer so the user is never stranded.

## 7. Performance architecture

Root causes found in GUI3 (all in `gui_qt/widgets`):

1. Every roster/preview row is a live `QWidget` via `setItemWidget` — construction, layout, and destruction dominate show switches.
2. `QApplication.processEvents()` inside sync loops (roster every 25 rows, guide every 30) — a reentrancy hazard that still doesn't remove the freeze.
3. `warm_preview_cache` synchronously pre-builds row widgets for **every scanned show** into the shared `QListWidget`; hidden items accumulate per `id(state)` render keys.
4. Any structural change rebuilds the whole list.

V4 design:

- **Models:** `RosterModel` (flat list + group headers as rows, or `QListView` with sections painted by delegate) and `EpisodeTableModel` (tree: season → episode/ghost/unmapped/duplicate/orphan rows) as `QAbstractItemModel`s over `ScanState`/`EpisodeGuide`. Show switches = `beginResetModel` on a model already holding plain dataclasses — no widget churn. In-place changes (approve, assign) emit `dataChanged` on affected rows only.
- **Delegates:** one delegate per view paints title, pills, confidence bar, chips, and ghost rows from theme tokens. Hit-testing handles chevron and check clicks; the expanded row is the only live widget (persistent editor), so worst case = 1 widget vs today's thousands.
- **Async guide building:** `EpisodeMappingService.build_episode_guide` and completeness digests run on the existing thread pool with a generation token per state; the table shows instantly with a skeleton row set if the guide isn't cached (cache service `episode_projection_cache` already exists), then fills in. Poster fetching stays async as-is.
- **Delete** `warm_preview_cache`, the render-key retention machinery, and every `processEvents` call in the workspace.
- **BusyOverlay** (new reusable widget): translucent scrim + spinner + label over any panel; a `busy_scope()` context manager shows it if an operation exceeds ~120ms and guarantees removal. Used for: bulk apply, queue-all, force rescan, tab-restore. Complements, not replaces, doing the work off-thread.
- **Budget:** switching to a 300-episode show must render < 100ms on the reference machine; group collapse/expand < 50ms; no interaction may block the event loop > 200ms without the overlay visible.

## 8. Theme system (Jellyfin dark)

**Token module** `gui_qt/theme.py`: one Python source of truth for color/radius/spacing tokens. `theme.qss` becomes a template (`theme.qss.tmpl`) rendered with tokens at startup; painting code (delegates, animation, placeholder pixmaps) imports the same constants. This retires the ~285 hex literals spread across 12 widget files. A unit test asserts the rendered QSS contains no unknown `$tokens` and the py files contain no raw hex (allowlist for theme.py itself).

**Palette** (Jellyfin dark reference):

| Token | Value | Replaces |
|---|---|---|
| `bg` | `#101010` | `#0d0d0d` |
| `surface` | `#181818` | `#151515` |
| `card` | `#202020` | `#1c1c1c` |
| `card_hover` | `#282828` | `#242424` |
| `selection_bg` | `#1c2a33` (accent-tinted) | amber `#1f1a0e` |
| `border` / `border_light` | `#2e2e2e` / `#3d3d3d` | `#2a2a2a` / `#3a3a3a` |
| `text` / `text_dim` / `text_muted` | `#f0f0f0` / `#9b9b9b` / `#5c5c5c` | ≈same grays |
| `accent` | `#00a4dc` (Jellyfin blue) | Plex amber `#e5a00d` |
| `accent_hover` / `accent_dim` | `#1cb8ef` / `#0a5f7d` | `#f0b429` / `#7a5a10` |
| `accent_alt` | `#aa5cc3` (Jellyfin purple; hero gradients only: loading, empty state) | — |
| `success` / `warning` / `error` / `info` | `#3fb950` / `#d29922` / `#e5534b` / `#58a6ff` | `#3ea463` / amber / `#d44040` / `#4a9eda` |

Warning stays distinct from accent (in GUI3 "accent" doubled as the warning tone — that ambiguity goes away).

**Shape scale:** `radius_sm=4` (inline pills, tiny controls), `radius_md=8` (rows, cards, buttons, inputs), `radius_lg=12` (panels, dialogs, toasts). The `panelVariant="square"` hack and the 0/4/5/6/8/10/12 mix disappear.

**Card shading instead of fringe:** all `border-left` accents go (roster cards, preview cards, callout banner, toast, table selected-row stripe). Status is conveyed by the status pill plus a *graceful* treatment: card background gets a ≤6%-alpha wash of the status tone; selection gets `selection_bg` + 1px accent border. Hover lightens the surface. Hairline reduction: row cards drop their 1px borders entirely (spacing + contrast separate them); borders remain only on panel boundaries and inputs.

**De-Plex strings:** window title + `setApplicationName` → **"NameScraper"** (open question §15), About text rewritten, "Plex Ready" status + group → **"Fully Ready"**, skip reason "already Plex-ready" → "already fully ready", `plex-ready` group key → `fully-ready` (settings-persisted collapse state migrates on load), theme.qss header comment updated.

## 9. Toasts

Rebuilt `_ToastCard` on theme tokens (no inline stylesheet, no fringe): surface card, tone icon + title, message clamped to 3 lines. New behaviors:

- **Expand:** "Show more" appears when text is clamped; expands in place up to ~40% of window height with internal scroll.
- **Copy:** a copy button on every toast copies title + full untruncated message (crucial for long error traces).
- Errors default to sticky (duration 0); hover pauses any countdown; countdown bar kept.
- Overflow summary card behavior kept.

## 10. Loading screen and progress

Replace `_ScannerAnimation` and the duplicated text rows:

- **Animation:** a poster-card conveyor — 5 stylized blank media cards sliding horizontally, each swept by a Jellyfin blue→purple gradient scan beam and flipping to a "filled" state; subtle, GPU-cheap (QPainter transforms, one repaint timer). It visually *is* the product: cards being identified.
- **Status (single source each):** phase stepper (slim horizontal dots+connector line replacing the 2×3 checklist grid) · one primary line = current lifecycle phase · one secondary line = current item (elide-middle + tooltip) · progress bar + `done/total` · elapsed · Cancel.
- **Filler messages:** when a phase runs >4s without item changes, the secondary line rotates curated quips ("Politely interrogating TMDB…", "Counting specials twice, just in case…", "Untangling Season 0…") — honest phase text stays on the primary line at all times.
- The same stepper/label components back the **BusyOverlay** (§7) so in-panel waits look related, and movie/TV scans share the widget as today.

## 11. Queue and History restyle

Architecture (table + model/proxy + detail splitter) is already right; this is a facelift plus companion-file visibility:

- Delegate restyle: drop the 4px selected-row stripe; selection = `selection_bg` full-row + accent text on title cell; status column becomes a painted pill matching workspace pills; row height up slightly for readability; alternating rows off in favor of hover.
- Toolbar: segmented filters restyled per theme; Start/Run/Remove buttons follow the primary/secondary/danger scheme (`Remove Selected` becomes danger-outline).
- **Companion surfacing:** `JobTableModel` gains a Files column rendering `3 files (2 comp.)`; the job detail tree (`_job_detail_tree`) groups each rename with its companion children by type badge instead of burying them as flat rows; history revert banner restyled.
- Empty states get the illustration treatment consistent with the workspace empty state.

## 12. Settings restyle

Keep nav + stacked pages. Facelift: checkboxes get the themed indicator (proper check glyph SVG at 100/150/200% DPI — today's are barely styled), combo/slider/input restyle from tokens, section cards use `radius_lg` with a header row (icon + title) instead of heading+separator hairline, destructive actions (clear cache/history) grouped under a "Data" section as danger-outline with confirm counts, and a reserved **"Tools"** section shell for the future mkvmerge path setting (§13) — hidden until the feature lands.

## 13. mkvmerge groundwork (explicitly not wired)

What V4 *does*: reserve seams so the merge feature drops in without another redesign.

- **Data seam:** design-level contract only — an episode row may later carry a `merge_plan` (ordered source parts + subtitle-merge flags). `EpisodeGuideRow.companions` and the assignment table's multi-file episode support already model the inputs; no schema change ships in V4.
- **UI seams:** expanded episode row's Files section lists primary + companions with type badges and reserves a disabled `Merge…` action slot; multi-part episodes (one episode, several files via assign-to-more) render as "Part 1 · Part 2" chips in the expanded card, proving the layout can host merge grouping; queue job detail tree's per-file grouping (§11) is the same structure a merge job will need; Settings reserves the Tools section.
- **Out of scope:** any mkvmerge invocation, merge queueing, or new persisted fields.

## 14. Menus, shortcuts, misc fixes

- **Remove** Ctrl+Z and the `Edit → Undo Last Rename` action. Reverting stays available per-job in History (explicit, visible, confirmable). Revisit shortcuts after mkvmerge lands.
- Keep: Ctrl+O, Ctrl+Q / Ctrl+Shift+Q, Space, Esc, F5, Del/Enter (queue), Ctrl+1..5.
- **Recent-folders fix:** recent-folder actions switch to the owning tab before calling `load_folder`, exactly like `File → Open` already does — pick a folder, land on the right tab. Menus stay enabled from anywhere.
- About dialog: new app name, no Plex phrasing ("Rename and organize media into clean, server-friendly naming conventions").

## 15. Assumptions and open questions

1. **App display name** — brief says remove Plex mentions but doesn't name a successor. Assumed **"NameScraper"** (repo name) for window title/app name/About. *Please confirm or supply the preferred name.*
2. "Fully Ready" is the exact label for the old "Plex Ready" (per brief).
3. Episode description + air date live in the expanded episode row; show overview in the work panel header. (Brief said keep them; this is the proposed placement.)
4. Roster poster size ~64×94 logical (2-line row); tunable constant, compact mode unchanged.
5. Non-undo shortcuts stay (only undo was flagged dangerous).
6. `Matched` and `Fully Ready` remain distinct groups (actionable vs already-organized).
7. Bulk Assign MVP = check-files + assign-in-order + auto-map-remaining + drag single pairs; no undo stack inside the mode (Apply/Cancel is the boundary).
8. Filler-message tone: playful but dry; no pop-culture references that date badly.

## 16. Component boundaries (new / changed / deleted)

**New:** `gui_qt/theme.py` (+ `resources/theme.qss.tmpl`) · `widgets/_roster_model.py` + `_roster_delegate.py` · `widgets/_episode_table_model.py` + `_episode_table_delegate.py` + `_episode_expansion.py` (persistent-editor card) · `widgets/_work_panel.py` (header/strip/toolbar/table/footer assembly) · `widgets/_bulk_assign_panel.py` · `widgets/busy_overlay.py` · `widgets/status_chip.py` (season/status chips shared by roster + strip).
**Changed:** `media_workspace.py` (+ its coordinators) to host two panels and the new models; `_media_helpers.py` (groups incl. `fully-ready` + specials-only classification, label changes, colors → tokens); `scan_progress.py` (rebuilt internals, same public API); `toast_manager.py`; `_job_list_tab.py` / `job_table_model.py` / `_job_detail_tree.py`; `settings_tab.py` sections; `_main_window_chrome.py` / `_main_window_state.py` (shortcuts, recent menus, titles); `empty_state.py`, dialogs (`match_picker_dialog.py`, `episode_assign_dialog.py`) restyle.
**Deleted:** `media_detail_panel.py` + `_media_detail_*.py` · `_media_workspace_preview.py` (replaced by episode table) · the row-widget classes in `_workspace_widgets.py` (`RosterRowWidget`, `PreviewRowWidget`, `EpisodeGuideRowWidget`, `FolderPreviewRowWidget`); shared primitives in `_workspace_widget_primitives.py` (ElidedLabel, ToggleSwitch, MiniProgressBar, shimmer) are kept and reused by delegates/expansion card · warm-cache/render-key machinery in `_media_workspace_state.py`.

Controllers (`app/controllers/*`), services, engine, job store: **no behavioral changes**; only additive read-model helpers if the models need pre-digested rows.

## 17. Error handling

- Guide build failures per show → inline error row in the episode table + `scan_error` pill in roster (exists today) — never a silent empty table.
- Bulk Assign apply validates via existing assignment service; per-file failures report in one expandable toast (§9) and leave the mode open with failed rows still listed.
- BusyOverlay always removed via context-manager finally; a stuck overlay is impossible by construction.
- Toast copy uses the full original text even when the display is clamped.

## 18. Testing strategy

- **Unit (fast sweep, `scripts/test-fast.cmd`):** roster grouping incl. new `specials-unmapped-only` + `fully-ready` migration; season-chip text builder (runs collapse, tooltips); `EpisodeTableModel` row composition (ghost rows, sections, filters, dataChanged granularity); bulk-assign pairing logic (in-order, contiguity, auto-map preview); theme rendering (no unresolved tokens; no stray hex in widgets); string sweep test (no "Plex" in user-facing strings); shortcut table (no Ctrl+Z); recent-menu handlers switch tabs.
- **Qt smoke (`scripts/test-smoke.cmd`):** existing suite migrates from 3-panel attribute names to the new panels — a dedicated migration step in the plan; add smoke for expand-row editor lifecycle, BusyOverlay show/hide, toast expand/copy (clipboard), loading-screen update path.
- **Perf guard:** a smoke-level timing test builds a synthetic 500-episode state and asserts model population + first paint stays under budget (generous CI multiplier).
- **Manual/real-library:** `scripts/scan_real_library.py` unchanged; a visual pass at 100%/150%/200% scaling before merge.

## 19. Suggested milestone slicing (input to the implementation plan)

1. Theme tokens + QSS template + de-Plex strings (ships standalone, everything else builds on tokens).
2. Roster model/delegate + new grouping (3-panel still standing).
3. Episode table model/delegate + expansion card; delete preview panel; work panel assembly; detail panel removal (the big cutover).
4. Season chips/strip + footer breakdown.
5. Bulk Assign mode + Unassign All treatment.
6. BusyOverlay + async guide plumbing + warm-cache deletion + perf test.
7. Toasts, loading screen.
8. Queue/History restyle + companion surfacing.
9. Settings restyle + menu/shortcut fixes + About.
10. Test migration sweeps ride along inside each step; final DPI + real-library pass.
