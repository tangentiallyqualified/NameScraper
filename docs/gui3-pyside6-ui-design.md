# GUI3 PySide6 UI Design

## Design Principles

1. Information density with visual polish — every pixel communicates state,
   but spacing, color, and shape make it pleasant to read.
2. Standard Qt widgets and delegates first, custom painting only when necessary.
3. Keyboard navigable — tab order, arrow key navigation, shortcuts for common actions.
4. State-driven rendering — the UI reflects controller state, never drives it.
5. No modal dialogs for information that can be shown inline.
6. Progressive disclosure — show summary by default, detail on demand.

---

## Theme & Visual Language

### Global stylesheet

All visual styling is defined in a single `theme.qss` file loaded at app
startup. Widget code should not contain inline style — use QSS class
selectors and dynamic properties (e.g. `[status="error"]`) instead.

### Color palette

Carry forward the existing dark palette from `styles.py`:

| Token             | Hex       | Usage                                     |
|-------------------|-----------|-------------------------------------------|
| `bg_dark`         | `#0d0d0d` | Window background, deepest layer          |
| `bg_mid`          | `#151515` | Panel backgrounds                         |
| `bg_card`         | `#1c1c1c` | Card / row resting state                  |
| `bg_card_hover`   | `#242424` | Card / row hover state                    |
| `bg_card_selected`| `#1f1a0e` | Card / row selected state (warm tint)     |
| `bg_input`        | `#252525` | Text fields, dropdowns                    |
| `border`          | `#2a2a2a` | Panel dividers, card edges                |
| `border_light`    | `#3a3a3a` | Subtle separators within cards            |
| `text`            | `#e0e0e0` | Primary text                              |
| `text_dim`        | `#777777` | Secondary labels, metadata keys           |
| `text_muted`      | `#4a4a4a` | Disabled text, placeholders               |
| `accent`          | `#e5a00d` | Primary action buttons, selection borders |
| `accent_hover`    | `#f0b429` | Button hover state                        |
| `accent_dim`      | `#7a5a10` | Accent at low emphasis                    |
| `success`         | `#3ea463` | High confidence, completed jobs           |
| `error`           | `#d44040` | Low confidence, failed jobs               |
| `info`            | `#4a9eda` | Informational badges, links               |

Badge-specific colors (`badge_review_*`, `badge_movie_*`, etc.) carry
forward unchanged from `styles.py`.

### Typography

Use the system UI font stack: Segoe UI (Windows), SF Pro (macOS),
with fallback to sans-serif. Define four size stops:

| Role      | Size | Weight   | Usage                                  |
|-----------|------|----------|----------------------------------------|
| Heading   | 16px | Semibold | Detail panel title, section headers     |
| Body      | 13px | Regular  | Primary content, filenames, metadata    |
| Caption   | 11px | Regular  | Secondary info, timestamps, file counts |
| Badge     | 10px | Semibold | Status pills, tab badge counts          |

### Spacing scale

4px base grid. All margins, padding, and gaps use multiples:
4, 8, 12, 16, 24, 32. No arbitrary pixel values.

### Border radius

| Element          | Radius |
|------------------|--------|
| Cards / panels   | 6px    |
| Buttons          | 6px    |
| Status badges    | 10px (full pill) |
| Poster thumbnails| 4px    |
| Input fields     | 4px    |
| Toast notifications | 8px |

### Elevation & depth

Panels and cards use a combination of 1px `border` color borders and
subtle box shadows to create depth without hard edges:

- **Level 0** — `bg_dark`, no border. Window background.
- **Level 1** — `bg_mid`, 1px `border` edge. Panels (roster, preview, detail).
- **Level 2** — `bg_card`, 1px `border_light` edge, `0 1px 3px rgba(0,0,0,0.4)`
  shadow. Cards, roster items, preview file cards.
- **Level 3** — `bg_card`, stronger shadow `0 4px 12px rgba(0,0,0,0.5)`.
  Dropdowns, tooltips, toast notifications.

### Iconography

Use a consistent icon set throughout (Lucide or Material Symbols Outlined,
weight 300). No emoji in the UI — use icons for status indicators,
actions, and file types. Icons inherit `text_dim` color by default and
`text` on hover/active.

### Hover & focus states

Every interactive element must have visible hover and focus states:

- **Rows / cards**: background transitions from `bg_card` to `bg_card_hover`
  over 100ms ease.
- **Buttons**: background lightens, subtle scale (1.01x) on press.
- **Selected items**: `bg_card_selected` background + 2px `accent` left
  border.
- **Focus ring**: 2px `accent_dim` outline offset by 2px. Visible on
  keyboard navigation, hidden on mouse click (`:focus-visible` behavior).

### Transitions & animation

- State transitions (hover, selection, expand/collapse): 100–150ms ease.
- Toast slide-in: 200ms ease-out from right edge.
- Badge count pulse: 200ms scale to 1.15x then back.
- Job completion row highlight: 200ms green fade, then 300ms settle.
- Progress bar: smooth `QPropertyAnimation` on value changes.
- No animation should block interaction or exceed 300ms.

---

## Application Shell

### Window chrome

- Thin menu bar at the top: File / Edit / View / Help.
  - File: Open TV Folder, Open Movie Folder, Exit.
  - Edit: Undo Last Rename (Ctrl+Z), Settings (Ctrl+,).
  - View: Compact Mode toggle, Show Companion Files toggle.
  - Help: About, Documentation link, Report Issue link.
- Menu bar is always visible across all tabs.

### Tab bar

Horizontal tab bar immediately below the menu bar. Tabs:

1. TV Shows
2. Movies
3. Queue
4. History
5. Settings

Horizontal tabs use the widest screen axis and support text labels without
compression. Vertical tabs would add a 4th column competing with the 3-panel
layout and force icon-only labels.

Tab badges:
- Queue tab shows pending+running count: `Queue (3)`.
  Additionally, if any jobs have failed, a small red pip appears after
  the count to signal errors at a glance: `Queue (3) *` (red dot).
- History tab shows completed count: `History (12)`.
- Badges animate briefly (scale pulse, not flash) when count changes.

### Window state persistence

`SettingsService` stores across restarts:
- Window size and position.
- Splitter positions (roster/preview/detail proportions).
- Compact vs normal view preference.
- Last used TV and movie folder paths (for File menu "recent folders").
- Active view toggles (show companion files, etc.).

---

## TV and Movie Tabs — Shared Structure

Both tabs share the same layout structure and state machine. The only
differences are data source (TV vs movie) and some detail panel content.

### Tab state machine

Each tab independently tracks its session state via `MediaController`:

```
EMPTY  ──>  SCANNING  ──>  READY
  ^                          |
  +---- (clear/new folder) --+
```

The tab always renders its current state. Switching tabs preserves state
(via `snapshot_*_for_tab_switch` / `restore_*_from_tab_switch`). Clicking
back to a tab that already has scan results shows those results, not the
empty state.

### Empty state

When no folder has been selected for this tab:

- The 3-panel layout is hidden.
- A single centered panel fills the workspace.
- Large folder icon (Lucide `folder-open`, 64px, rendered at 40% opacity
  in `text_dim`) inside a rounded dashed-border drop zone (2px dashed
  `border_light`, `border-radius: 12px`, ~300x200px).
- Label inside the drop zone: "Select TV Library Folder" or
  "Select Movie Folder" in heading style.
- Below the label: brief instruction text in `text_dim`, e.g.
  "Choose the root folder, or drag and drop it here."
- **Drag-and-drop support**: the drop zone accepts a dragged folder from
  the OS file manager. On drag-over, the border color transitions to
  `accent` and the background subtly lightens. On drop, the folder path
  is used as if selected via the native directory picker.
- Clicking anywhere in the drop zone opens the native directory picker.
- Keyboard: Enter or Space activates the folder picker when focused.
- **Recent folders**: if `SettingsService` has stored previous folder
  paths, show them as a short list below the drop zone. Each entry shows
  the folder name and path in `text_dim`, and is clickable to re-scan.

### Scanning state

After a folder is selected, the empty-state panel transitions to a
structured progress view (not a spinner — structured information):

```
+----------------------------------------------+
|                                               |
|         Scanning TV Library                   |
|                                               |
|  Phase:  Matching shows on TMDB               |
|  [============================--------] 12/24 |
|  Current:   Battlestar Galactica (2004)       |
|  Elapsed:   0:42                              |
|                                               |
|  [check] Discovery complete -- 24 shows found |
|  [spin]  Matching shows... 12/24              |
|  [ ]     Episode scanning                     |
|                                               |
|                                    [Cancel]   |
|                                               |
+----------------------------------------------+
```

Elements:
- Phase name (Discovery / Matching / Scanning / Cache Lookup).
- `QProgressBar` styled with `accent` fill color and rounded ends,
  with numeric N/M count to the right.
- Current item name in `text` color.
- Elapsed time counter (updates every second).
- Phase checklist with animated state transitions:
  - Completed phases: `success` colored check icon, fades in on completion.
  - Active phase: animated spinner icon in `accent` color.
  - Pending phases: hollow circle in `text_muted`.
- Cancel button (sets `CANCEL_SCAN` flag), styled as a secondary
  (outline) button.

Data source: `MediaController.scan_progress` provides lifecycle, phase,
done, total, current_item, and message. No new backend work needed.

### Ready state — 3-panel layout

When scanning completes, the progress view is replaced by the 3-panel
workspace. The panels are separated by `QSplitter` handles for user resizing.

```
+---------------+--------------------------+---------------+
|               |                          |               |
|   Roster      |     Preview              |   Detail      |
|   Panel       |     Panel                |   Panel       |
|               |                          |               |
|  (left)       |   (center)               |  (right)      |
|               |                          |               |
+---------------+--------------------------+---------------+
```

### Bottom action bar

A persistent thin toolbar is pinned to the bottom of the TV/Movie tab
workspace, spanning the full width below the 3-panel layout:

```
+------------------------------------------------------------------+
| [check] 3 of 24 shows checked   [Check All] [Uncheck All]       |
|                                              [Add 3 to Queue]   |
+------------------------------------------------------------------+
```

Elements:
- **Selection summary** (left): "3 of 24 shows checked" in body text.
- **Check All / Uncheck All** buttons: secondary (outline) style.
- **Add to Queue button** (right): primary `accent` button, prominent.
  Disabled with tooltip when nothing is eligible.
  Label shows count: "Add 3 to Queue" or "Add to Queue" for single items.
- **Warning text**: if items need review or are already queued, a line
  of `text_dim` text appears: "2 shows need review - 1 already queued".

This replaces the queue action area that was previously in the detail
panel, keeping the primary action always visible regardless of what is
selected.

---

## Left Panel — Roster

### Content

Lists all discovered media entities (TV shows or movies) with their
scan status.

### View modes

Toggle via View menu or toolbar button:

- **Normal**: Poster thumbnail (40x60, 4px border-radius, 1px
  `border_light` border), title, year, status badge, match confidence
  indicator. Row height ~70px.
- **Compact**: No poster. Title, year, status badge on a single row.
  Row height ~28px.

### Per-item display

Each roster item is rendered as a Level 2 card with 8px vertical gap
between items. Each item shows:

- **Confidence left-border**: a 3px left edge colored by confidence
  level (green / yellow / red), visible in both normal and compact modes.
  This provides an at-a-glance scannable signal down the full roster.
- Title and year in body text.
- **Status badge**: pill-shaped (`border-radius: 10px`, 6px horizontal
  padding) using the existing badge color tokens. One of: Scanning,
  Ready, Queued, Needs Review, Duplicate, Plex-Ready, Error.
- Checkbox for batch queue selection, styled with `accent` fill when
  checked.
- File count (e.g., "12 files") in caption style, `text_dim` color.
- Hover: background transitions to `bg_card_hover`.
- Selected: background transitions to `bg_card_selected`, left border
  widens to 4px and uses `accent` color.

### Needs Review — inline alternative matches

When a show or movie has `confidence < AUTO_ACCEPT_THRESHOLD`, the roster
item expands to show the top 2 alternative matches from
`ScanState.alternate_matches` as indented sub-rows:

```
+-----------------------------------------+
| [_] [yellow border] Battlestar Galactica (2003)
|     [NEEDS REVIEW] - 2 episodes
|       |- Battlestar Galactica (2004)      <- alt 1 (clickable)
|       +- BSG: The Plan (2009)             <- alt 2 (clickable)
+-----------------------------------------+
```

Sub-rows use caption-size text and `text_dim` color. On hover, the
alternative text brightens to `text` and shows an underline to indicate
clickability.

Clicking an alternative:
1. Inline confirmation prompt (not a modal): "Switch match to
   Battlestar Galactica (2004)?" with Accept / Cancel buttons that
   replace the sub-row temporarily.
2. On accept: re-run episode matching against the new TMDB ID.
3. Roster item updates to reflect the new match.

### Force rematch

Right-click context menu on any roster item includes "Force Rematch..."
which opens the TMDB search dialog regardless of current confidence.
Also accessible via a small refresh icon (Lucide `refresh-cw`, caption
size) that appears on hover at the right edge of the roster item row.

### Implementation

- `QListView` with a custom `QStyledItemDelegate`.
- Model backed by `MediaController.library_states`.
- Selection drives `MediaController.select_show()` which updates the
  preview and detail panels.

---

## Center Panel — Preview

### TV show preview

Each file rename is rendered as a discrete card (`QFrame`) inside a
`QScrollArea`, rather than rows in a `QTreeView`. Cards use Level 2
elevation with 8px gaps between them. Season headers group the cards.

Season headers:

- Styled as a sticky bar that pins to the top of the scroll area when
  scrolling past. Background: `bg_mid` with 90% opacity for a subtle
  translucency effect. Falls back to solid `bg_mid` if opacity is not
  performant.
- Text: "Season 1" in heading style, with a thin progress bar underneath
  (3px height, `accent` fill) showing the season match ratio (e.g.,
  12/13 = 92% filled).
- Collapse/expand chevron icon on the right. Collapsed state hides all
  cards for that season.

Per-file card layout:

```
+-------------------------------------------------------+
| [check]  Naruto - S01E01.mkv                          |
|          Naruto (2002) - S01E01 - Enter Naruto...mkv  |
|          [companion-icon] .srt  ->  ...srt            |
|          [confidence-bar 92%]                         |
+-------------------------------------------------------+
```

Card elements:
- Checkbox on the left edge for selection.
- **Original filename** in body text.
- **Target filename** on the next line, in `accent` color to visually
  distinguish it from the original. Preceded by a small right-arrow
  icon (Lucide `arrow-right`, 12px) in `text_muted`.
- **Status badge** (pill): OK, NEEDS REVIEW, UNMATCHED, SKIP, CONFLICT.
  Positioned at the top-right corner of the card.
- **Confidence bar**: thin (3px height, full card width minus padding),
  rounded, using gradient fill — `success` for the filled portion when
  >= 0.85, `accent` for 0.50–0.84, `error` for < 0.50. Percentage text
  in caption style at the right end of the bar.
- **Companion files**: listed below the main file in caption style,
  indented with a thin vertical connector line (1px `border_light`) on
  the left. Each shows a small file-type icon and its own
  original -> target mapping. Only shown when "Show Companion Files"
  is enabled in View menu.

### Fix Match control

For items with low confidence or UNMATCHED status, a "Fix Match" dropdown
button appears on the card. Clicking it shows:
- A season/episode picker: two dropdowns (Season, Episode) populated
  from the TMDB episode list for this show.
- "Mark as Special" option for files that belong in Season 00.
- "Exclude from rename" option to mark as SKIP.
- Selecting a season/episode immediately updates the preview to show
  the corrected target filename.

### Movie preview

Movies typically have 1 file per entity, so the per-file card layout
wastes vertical space. The movie preview uses a denser card layout:

```
+----------------------------------------------------------+
| [check]  Dune.2021.2160p.WEB-DL.mkv                     |
|          Dune (2021) / Dune (2021).mkv                   |
|          [companion-icon] .srt  ->  Dune (2021).srt      |
|                                                          |
|          2160p  -  14.2 GB  -  HEVC                      |
|          /movies/incoming/  ->  /movies/Dune (2021)/     |
+----------------------------------------------------------+
```

Metadata line (resolution, size, codec) in caption style, `text_dim`.
Folder path line uses the same arrow-icon treatment as filenames.

### Implementation

- Season headers: `QFrame` widgets set as sticky headers in the scroll
  area layout (using `QVBoxLayout` with header frames and card frames).
- File cards: `QFrame` subclass with internal layout. Styled via QSS
  class selector `.preview-card`.
- Companion files: child widgets within the card frame, toggled by
  the companion visibility setting.

---

## Right Panel — Detail

### Poster hero area

The top of the detail panel features a poster hero treatment:

- **Background gradient**: a blurred, darkened version of the poster
  image is rendered as a gradient background behind the metadata area.
  This creates a warm, media-app feel (similar to Plex, Jellyfin, or
  Spotify artist pages). Implemented as a `QLabel` with a `QPixmap`
  that is Gaussian-blurred (radius ~20px), darkened to ~30% opacity,
  and scaled to fill the panel width. Falls back to a solid `bg_mid`
  gradient if no poster is available.
- **Poster image**: full-width poster scaled to panel width, with
  8px border-radius and a subtle shadow
  (`0 4px 12px rgba(0,0,0,0.5)`). Overlaid on the blurred background.
- **Title and year**: large heading text, rendered over the gradient
  area in white with a subtle text shadow for legibility.

### TV show detail (when a show is selected in roster)

Below the poster hero:

- **Match confidence**: thin horizontal bar (4px height, full width)
  colored by confidence level, with percentage and text label
  (High / Moderate / Low / Needs Review) to the right in caption style.
- **TMDB metadata** — displayed as a 2-column key/value grid. Keys in
  `text_dim` (caption style), values in `text` (body style). Thin 1px
  `border_light` separator between sections:
  - Rating (stars + vote count).
  - Status (Returning Series / Ended / Cancelled / etc.).
  - Network.
  - Genres (as pills, using `badge_other_*` colors).
  - Creators.
  - Overview/synopsis (full-width, below the grid).
- **Completeness report** — per-season breakdown using mini progress
  bars (3px height, `success` fill) with count overlaid in caption text:
  - `[===========-] Season 1: 12/13` — scannable at a glance.
  - Missing episodes listed below in `text_dim`:
    "Missing: S01E07 'The Chunin Exam'".
  - Collapsible per-season, expanded by default for incomplete seasons.
- **Discovery info** (collapsible, collapsed by default):
  - How discovered: `discovery_reason` value.
  - Relative folder path.
  - Whether discovered via symlink.
  - Direct video file count, season subdir count.

### TV episode detail (when a file is selected in preview)

When clicking a specific episode card in the preview panel, the detail
panel adds episode-specific information below the show info, separated
by a `border_light` divider:

- **Episode title** in heading style.
- **Air date**.
- **Runtime**.
- **Rating** (episode-level).
- **Synopsis**.
- **Guest stars** (up to 4).
- **Directors and writers**.
- **Match confidence** — episode-level confidence with explanation:
  - "Strong match — S01E01 pattern found in filename."
  - "Weak match — episode number inferred from position in folder."
- **Original filename** and **target filename** repeated for reference.

### Movie detail (when a movie is selected)

Uses the same poster hero treatment, then:

- **Title, year, tagline** (tagline in `text_dim`, italic).
- **Rating** (stars + vote count).
- **Genres** (as pills).
- **Runtime**.
- **Release date**.
- **Production companies**.
- **Overview/synopsis**.
- **File info**: resolution, size, codec (parsed from filename).
- **Folder rename plan**: source folder -> target folder, using the
  arrow-icon treatment.

---

## Queue Tab

### Layout

Single panel, full width. Split vertically:
- Top: queue/pending jobs.
- Bottom: currently executing job detail (if any).

### Empty state

When the queue is empty, show a centered message: "No jobs queued" in
heading style with "Scan a library and add items to get started" in
`text_dim` below. Include a button or link for each media tab:
"Go to TV Shows" / "Go to Movies".

### Job list

Jobs are rendered as thin cards (Level 2 elevation) with a status-colored
left border (3px):

- `accent` — pending.
- `info` — running (with a subtle pulse animation on the border).
- `success` — completed.
- `error` — failed.
- `text_muted` — reverted / cancelled.

Card columns:
- Status icon (Lucide icons: `clock` pending, `loader` running,
  `check-circle` completed, `x-circle` failed, `undo` reverted).
- Media name in body text.
- Type badge (TV / Movie) as a small pill.
- File count in caption style.
- Added timestamp in caption style, `text_dim`.

### Companion file grouping

Each job is expandable. Companion file ops are children, indented with
a thin vertical connector line (1px `border_light`):

```
> [pending] Naruto (2002)       [TV]  12 files    Mar 27, 14:30
    |- S01E01.srt               subtitle
    |- S01E02.srt               subtitle
    +- S01E03.srt               subtitle
```

Companion rows use caption style and `text_dim` color. Collapsed by
default.

### View modes

- **Normal**: full card height with type badge and timestamp.
- **Compact**: single-line rows, name and status icon only.

Toggle via View menu or toolbar button. Preference persisted in settings.

### Filtering

Toolbar segmented control (not a dropdown — all options visible):
- All
- Pending
- Running
- Completed
- Failed

Uses `QSortFilterProxyModel` on the underlying job model. Filter state
does not affect the actual queue — it is purely visual.

### Per-job execution

Right-click context menu: "Execute Now". Calls
`QueueController.execute_single(job_id)`. Also available as a toolbar
button when a single pending job is selected.

### Drag-and-drop reorder

Pending jobs can be drag-reordered within the queue. A grip handle icon
(Lucide `grip-vertical`) appears on hover at the left edge of pending
job cards. Reorder updates `RenameJob.position` values via a new
`JobStore.reorder(job_ids)` method. Running/completed jobs are not
draggable and do not show the grip handle.

**Backend prerequisite**: Add `JobStore.reorder(job_ids: list[str])` method
that bulk-updates position values in a single transaction.

### Actions dropdown

Toolbar dropdown with selection presets:
- Select All Pending
- Select All TV Jobs
- Select All Movie Jobs
- Deselect All

Multi-select enables bulk actions: Execute Selected, Remove Selected,
Cancel Selected.

### Job completion animation

When a job transitions from running to completed:
- Left border color transitions from `info` to `success`.
- Card background briefly tints `success_dim` (200ms fade), then
  settles to normal.
- If the queue filter hides completed jobs, the card fades out (300ms)
  and collapses height rather than snapping away.

When a job fails:
- Left border transitions to `error`.
- Card background briefly tints `error_dim`, then settles to normal
  with persistent `error` left border.
- Badge on Queue tab updates (count + red error pip).

---

## History Tab

### Layout

Same structure as Queue tab but read-only. Shows completed, failed,
reverted, and cancelled jobs. Uses the same card style and
status-colored left borders.

### Filtering

Toolbar segmented control:
- All History
- Completed
- Failed
- Reverted

### Actions dropdown

Selection presets:
- Select All Completed TV Renames
- Select All Completed Movie Renames
- Select All Failed Jobs
- Select All

Bulk actions: Revert Selected, Clear Selected from History.

### Revert flow

Select one or more completed jobs -> "Revert Selected" button or
right-click -> "Revert". Inline confirmation banner at the top of the
panel (not a modal dialog):

```
+-------------------------------------------------------+
|  [undo-icon] Revert 3 jobs? This will move 47 files   |
|  back to their original locations. [Revert] [Cancel]   |
+-------------------------------------------------------+
```

Banner uses `bg_card` background with `accent` left border (4px).
Revert calls `QueueController.revert_job()` for each selected job.

---

## Settings Tab

### Layout

Settings are organized in a single scrollable column with section
cards (Level 2 elevation, full width, 16px padding). Each section
has a heading-style title and a thin `border_light` bottom separator.

### Sections

**Display**
- View mode default: Compact / Normal (dropdown).
- Show companion files in preview: toggle switch.
- Show discovery info in detail panel: toggle switch.

**Matching**
- Match language: dropdown (existing 25-language list).
- Auto-accept confidence threshold: styled `QSlider` with `accent`
  fill, 0.50-1.00, default 0.85. Current value shown in a small
  label to the right. Affects `AUTO_ACCEPT_THRESHOLD`.
- Episode confidence display: toggle switch (show/hide confidence
  bars in preview).

**API Keys**
- TMDB API key: text field with Save and Test buttons.
  Test button queries TMDB and shows inline success/failure message
  (green check or red X icon + text).

**Cache**
- TMDB cache statistics: item count, total size, oldest entry age.
  Displayed as a small 3-column stat row.
- "Clear TMDB Cache" button with inline confirmation.
- "Clear All Data" button (cache + job history) with stronger
  confirmation (must type "DELETE" or similar).

**Advanced** (collapsible, collapsed by default)
- Log level: dropdown (Normal / Verbose / Debug).
- Export diagnostic log: button that saves recent log entries to a file.

---

## Notification Model

### Tab badges

- Queue tab: `Queue (N)` where N = pending + running count.
  If any jobs have failed, a small red dot (6px circle, `error` color)
  appears after the count to signal errors without switching tabs.
- History tab: `History (N)` where N = total history count.
- Badges update on any job state transition.
- Badge count change triggers a brief scale-pulse animation (not a flash).

### Toast notifications

Non-blocking, auto-dismissing notifications that slide in from the
bottom-right of the window. Styled as Level 3 cards (8px border-radius,
strong shadow) with a colored left border matching the notification type:

- `success` border: "Job completed: Naruto (2002) - 12 files renamed."
  (3 second auto-dismiss)
- `error` border: "Job failed: Dune (2021) - permission denied."
  (persistent until dismissed)
- `accent` border: "Queue finished - 5 jobs completed, 1 failed."
  (5 second auto-dismiss)

Toast features:
- Slide-in animation: 200ms ease-out from right edge.
- Auto-dismiss timer shown as a thin progress bar (2px height) at the
  bottom of the toast that depletes over the dismiss duration.
- Dismiss button (Lucide `x`, caption size) at top-right corner.
- Failed job toasts are persistent (user must dismiss) and include a
  "Show in History" text link in `info` color that switches to the
  History tab and selects the failed job.
- Multiple toasts stack vertically with 8px gaps, newest on top.

### Inline status

The scan progress area, queue eligibility summary, and job detail panels
all show status inline rather than via dialogs. Modal dialogs are reserved
for destructive confirmations only (revert, clear history, clear cache).

### Error aggregation

Failed jobs in the queue/history show their error message in the detail
panel when selected. No separate error log window — the history tab IS
the error log. Filter to "Failed Only" to see all failures.

---

## Keyboard Shortcuts

| Shortcut       | Action                                          |
|----------------|-------------------------------------------------|
| Ctrl+O         | Open folder (TV or Movie depending on active tab) |
| Ctrl+Z         | Undo last rename                                |
| Ctrl+,         | Open Settings                                   |
| Ctrl+Q         | Add selected to queue                           |
| Ctrl+Shift+Q   | Add all checked to queue                        |
| Space          | Toggle checkbox on selected item                |
| Enter          | Execute selected queue job                      |
| Delete         | Remove selected from queue (pending only)       |
| Ctrl+A         | Select all in current list                      |
| F5             | Force rematch on selected roster item           |
| Ctrl+1..5      | Switch to tab 1-5                               |
| Escape         | Cancel current scan / dismiss toast             |

---

## Backend Prerequisites

### Complete — ready for Phase 3

1. **`JobStore.reorder_job()` / `move_jobs()`** — Position management
   for drag-and-drop queue reordering. Already implemented in
   `job_store.py`.

2. **`SettingsService` extensions** — Typed accessors for window
   geometry, splitter positions, view mode, confidence threshold,
   companion file visibility, discovery info visibility, confidence bar
   visibility, and recent TV/movie folder MRU lists. All persisted to
   `~/.plex_renamer/settings.json` with validation and defaults.

### Needed before Phase 5

3. **Filename metadata parsing** — Extract resolution, codec, and file
   size from filenames for movie preview cards. May be a utility function
   in `parsing.py` or computed at scan time and stored on `PreviewItem`.
   The `RELEASE_NOISE` regex in `constants.py` already identifies these
   tokens but strips them rather than capturing them.

### Needed before Phase 6

4. **Episode fix/reassign in engine** — A method to reassign a
   `PreviewItem` to a different season/episode and recompute its target
   filename. May live on `TVScanner` or as a standalone function.

---

## Implementation Order

This design should be built in the order defined by the migration plan:

1. **Phase 3**: Application shell, tab bar, `theme.qss` stylesheet,
   empty states (with drag-and-drop), settings tab.
2. **Phase 4**: Queue and History tabs (card-based job list, toast
   notifications, validates controller integration).
3. **Phase 5**: Roster and preview panels (card-based layouts, sticky
   season headers, bottom action bar).
4. **Phase 6**: Detail panel (poster hero area, metadata grid, rematch
   dialogs, fix-match controls).

Each phase should be usable independently — Phase 3 launches and
navigates, Phase 4 manages the queue, etc. Full integration happens
when all phases complete.
