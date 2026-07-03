# GUI V4 Plan 1: Theme Foundation, De-Plex, Chrome Safety Fixes

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Plex color scheme with a token-driven Jellyfin dark theme (single source of truth in `gui_qt/theme.py`), remove every user-facing "Plex" string ("Plex Ready" → "Fully Ready", app → "NameScraper"), kill the colored left-edge card fringe, normalize corner radii, remove the dangerous Ctrl+Z undo, and fix recent-folder menus loading into a hidden tab.

**Architecture:** A Python token module (`theme.py`) renders `resources/theme.qss.tmpl` (a `string.Template` of today's `theme.qss`) at startup and exposes the same tokens to painting code. Guard tests enforce "no raw hex outside theme.py" and "no Plex string literals" permanently. No layout changes in this plan — the 3-panel workspace still stands until Plans 2–3.

**Tech Stack:** PySide6, `string.Template`, pytest (+ existing Qt smoke harness via `scripts\test-smoke.cmd`).

## Global Constraints

- Run Python/pytest through the venv: `.venv\Scripts\python.exe -m pytest …` (Windows).
- Fast sweep `scripts\test-fast.cmd` and Qt smoke `scripts\test-smoke.cmd` must pass at the end of every task.
- No hardcoded `P:\` paths in tests (use `tmp_path`/synthetic fixtures).
- All sizes through `gui_qt/_scale.py`; all colors/radii through `gui_qt/theme.py` after this plan.
- Exact label change: "Plex Ready" → **"Fully Ready"**; group key `plex-ready` → `fully-ready`; app display name → **"NameScraper"** (spec §15 open question — if the user supplies a different name before execution, substitute it everywhere "NameScraper" appears here).
- Engine and controllers unchanged (`PLEX_READY_EPISODE_FLOOR` in `engine/_episode_resolution.py` is an internal constant — leave it).
- Commit after every task with the messages given (append the repo's standard `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` trailer).

---

## Canonical color mapping (used by Tasks 2 and 3)

New palette (spec §8). `theme.py` is the only place these hex values may appear:

| Token | Value | | Token | Value |
|---|---|---|---|---|
| `bg` | `#101010` | | `accent` | `#00a4dc` |
| `surface` | `#181818` | | `accent_hover` | `#1cb8ef` |
| `card` | `#202020` | | `accent_pressed` | `#0d8fc0` |
| `card_hover` | `#282828` | | `accent_dim` | `#0a5f7d` |
| `input_bg` | `#262626` | | `accent_alt` | `#aa5cc3` |
| `selection_bg` | `#1c2a33` | | `success` | `#3fb950` |
| `section_header_bg` | `#14232c` | | `success_dim` | `#2b7a39` |
| `border` | `#2e2e2e` | | `warning` | `#d29922` |
| `border_light` | `#3d3d3d` | | `error` | `#e5534b` |
| `text` | `#f0f0f0` | | `error_hover` | `#ef6660` |
| `text_dim` | `#9b9b9b` | | `info` | `#58a6ff` |
| `text_muted` | `#5c5c5c` | | `on_accent` | `#ffffff` |

Radii: `radius_sm=4`, `radius_md=8`, `radius_lg=12`, `radius_pill=10`.

Old value → token (blind substitution unless a semantic row below overrides):

| Old | Token | Old | Token |
|---|---|---|---|
| `#0d0d0d` | `bg` | `#4a4a4a` | `text_muted` |
| `#151515` | `surface` | `#777777`, `#888888`, `#8d8d8d` | `text_dim` |
| `#181818` | `surface` | `#e0e0e0` | `text` |
| `#1c1c1c`, `#1e1e1e` | `card` | `#ffffff` | `on_accent` |
| `#242424`, `#262626` (gradient) | `card_hover` | `#e5a00d`, `rgb(229,160,13)` | `accent` |
| `#252525` | `input_bg` | `#f0b429` | `accent_hover` |
| `#1f1a0e`, `rgb(31,26,14)` | `selection_bg` | `#c88a0a` | `accent_pressed` |
| `#2a2110`, `rgba(42,33,16,230)` | `section_header_bg` | `#7a5a10` | `accent_dim` |
| `#2a2410`, `#2a2210` | `selection_bg` | `#3ea463` | `success` |
| `#1a3328` | `rgba(success, 0.12)` | `#2d7a4a` | `success_dim` |
| `#2d1414` | `rgba(error, 0.12)` | `#d44040` | `error` |
| `#142030` | `rgba(info, 0.12)` | `#e05050` | `error_hover` |
| `#2a2a2a`, `#292929` | `border` | `#4a9eda` | `info` |
| `#3a3a3a`, `#444444`, `#505050`, `#555555` | `border_light` | `#323232` | `card_hover` |

Semantic overrides (do NOT blind-map these — Plex amber served two meanings; V4 separates them):

- Confidence band **"medium"** and every *status* colored amber today (`Scanning`, `Review Match`, `Review Episode Matching`, `NEEDS REVIEW` pill tone `accent`) → **`warning`**, not `accent`.
- `job_table_model.py` status colors: PENDING→`text_dim`, RUNNING→`accent`, COMPLETED→`success`, FAILED/REVERT_FAILED→`error`, CANCELLED→`text_muted`, REVERTED→`info`.
- Section headers (`make_section_header`, sticky header): fg `accent`, bg `section_header_bg`.

---

### Task 1: `gui_qt/theme.py` token module

**Files:**
- Create: `plex_renamer/gui_qt/theme.py`
- Test: `tests/test_gui_theme.py`

**Interfaces:**
- Consumes: nothing (stdlib + PySide6.QtGui.QColor only).
- Produces: `COLORS: dict[str,str]`, `RADII: dict[str,int]`, `color(name)->str`, `qcolor(name)->QColor`, `radius(name)->int`, `rgba(name, alpha: float)->str`, `render_template(text)->str` (raises `KeyError` on unknown token), `load_stylesheet()->str`. Every later plan imports these.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_gui_theme.py
"""Theme token module and stylesheet rendering guards."""
from __future__ import annotations

import pytest

from plex_renamer.gui_qt import theme


def test_color_returns_hex():
    assert theme.color("accent") == "#00a4dc"
    assert theme.color("bg") == "#101010"


def test_color_unknown_token_raises():
    with pytest.raises(KeyError):
        theme.color("nope")


def test_qcolor_matches_color():
    assert theme.qcolor("error").name() == theme.color("error")


def test_radius_tokens():
    assert theme.radius("sm") == 4
    assert theme.radius("md") == 8
    assert theme.radius("lg") == 12
    assert theme.radius("pill") == 10


def test_rgba_renders_qss_rgba():
    assert theme.rgba("success", 0.12) == "rgba(63, 185, 80, 0.12)"


def test_render_template_substitutes_colors_and_radii():
    rendered = theme.render_template("a ${accent} b ${radius_md}px")
    assert rendered == "a #00a4dc b 8px"


def test_render_template_unknown_token_raises():
    with pytest.raises(KeyError):
        theme.render_template("${not_a_token}")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests\test_gui_theme.py -q`
Expected: FAIL — `ImportError: cannot import name 'theme'` (module doesn't exist yet).

- [ ] **Step 3: Implement `theme.py`**

```python
# plex_renamer/gui_qt/theme.py
"""GUI V4 design tokens — the single source of truth for color and shape.

QSS gets these via ``load_stylesheet()`` (rendering resources/theme.qss.tmpl);
painting code imports ``color``/``qcolor``/``radius`` directly.  No other
module in ``gui_qt`` may contain a hex color literal (tests enforce this).
Palette follows the Jellyfin dark reference (spec 2026-07-03-gui-v4-design §8).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from string import Template

from PySide6.QtGui import QColor

COLORS: dict[str, str] = {
    "bg": "#101010",
    "surface": "#181818",
    "card": "#202020",
    "card_hover": "#282828",
    "input_bg": "#262626",
    "selection_bg": "#1c2a33",
    "section_header_bg": "#14232c",
    "border": "#2e2e2e",
    "border_light": "#3d3d3d",
    "text": "#f0f0f0",
    "text_dim": "#9b9b9b",
    "text_muted": "#5c5c5c",
    "on_accent": "#ffffff",
    "accent": "#00a4dc",
    "accent_hover": "#1cb8ef",
    "accent_pressed": "#0d8fc0",
    "accent_dim": "#0a5f7d",
    "accent_alt": "#aa5cc3",
    "success": "#3fb950",
    "success_dim": "#2b7a39",
    "warning": "#d29922",
    "error": "#e5534b",
    "error_hover": "#ef6660",
    "info": "#58a6ff",
}

RADII: dict[str, int] = {"sm": 4, "md": 8, "lg": 12, "pill": 10}

_TEMPLATE_PATH = Path(__file__).parent / "resources" / "theme.qss.tmpl"


def color(name: str) -> str:
    return COLORS[name]


def qcolor(name: str) -> QColor:
    return QColor(COLORS[name])


def radius(name: str) -> int:
    return RADII[name]


def rgba(name: str, alpha: float) -> str:
    c = qcolor(name)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha:g})"


def _mapping() -> dict[str, str]:
    mapping = dict(COLORS)
    mapping.update({f"radius_{key}": str(value) for key, value in RADII.items()})
    return mapping


def render_template(text: str) -> str:
    return Template(text).substitute(_mapping())


@lru_cache(maxsize=1)
def load_stylesheet() -> str:
    return render_template(_TEMPLATE_PATH.read_text(encoding="utf-8"))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests\test_gui_theme.py -q`
Expected: 7 passed. (`load_stylesheet` is exercised in Task 2 once the template exists.)

- [ ] **Step 5: Commit**

```bash
git add plex_renamer/gui_qt/theme.py tests/test_gui_theme.py
git commit -m "feat(gui): add theme token module (Jellyfin dark palette)"
```

---

### Task 2: Convert `theme.qss` to a token template with the new palette

**Files:**
- Create: `plex_renamer/gui_qt/resources/theme.qss.tmpl` (from `theme.qss`)
- Delete: `plex_renamer/gui_qt/resources/theme.qss` (after app.py switches)
- Modify: `plex_renamer/gui_qt/app.py:18,142-146`
- Test: `tests/test_gui_theme.py` (extend)

**Interfaces:**
- Consumes: `theme.render_template`, `theme.load_stylesheet` (Task 1).
- Produces: rendered stylesheet with zero raw hex in the template; `app.py` uses `theme.load_stylesheet()`.

- [ ] **Step 1: Write the failing guard tests (extend `tests/test_gui_theme.py`)**

```python
import re
from pathlib import Path

_GUI_ROOT = Path(__file__).resolve().parents[1] / "plex_renamer" / "gui_qt"
_HEX_RE = re.compile(r"#[0-9a-fA-F]{6}\b")


def test_template_contains_no_raw_hex():
    text = (_GUI_ROOT / "resources" / "theme.qss.tmpl").read_text(encoding="utf-8")
    assert _HEX_RE.findall(text) == []


def test_template_renders_without_unresolved_tokens():
    rendered = theme.load_stylesheet()
    assert "${" not in rendered
    assert theme.color("bg") in rendered          # palette actually applied
    assert "#e5a00d" not in rendered              # Plex amber is gone


def test_template_has_no_left_fringe_rules():
    text = (_GUI_ROOT / "resources" / "theme.qss.tmpl").read_text(encoding="utf-8")
    # The only border-left allowed is the QComboBox arrow shape hack (transparent).
    for line in text.splitlines():
        if "border-left" in line and "transparent" not in line:
            raise AssertionError(f"left-fringe rule survived: {line.strip()}")
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests\test_gui_theme.py -q`
Expected: FAIL — `FileNotFoundError` for `theme.qss.tmpl`.

- [ ] **Step 3: Create the template**

`git mv plex_renamer/gui_qt/resources/theme.qss plex_renamer/gui_qt/resources/theme.qss.tmpl`, then edit it top to bottom:

1. **Header comment** — replace the whole token block at the top with:

```css
/* ─── NameScraper — Jellyfin-inspired dark theme ─────────────────────
   TEMPLATE: rendered by gui_qt/theme.py (string.Template).  Do not put
   raw hex here — use ${token} / ${radius_*}px from theme.COLORS/RADII.
   rgba(...) washes below are hand-derived from token RGB values (QSS
   cannot compute alpha from a hex token) — update them if the palette
   in theme.py changes.  success=63,185,80  warning=210,153,34
   error=229,83,75  info=88,166,255  accent=0,164,220.
   Spacing: 4px grid.  Typography: Segoe UI / SF Pro / sans-serif.
   ─────────────────────────────────────────────────────────────────── */
```

2. **Color substitution** — apply the canonical mapping table (top of this plan) to every color literal in the file, e.g. `#0d0d0d`→`${bg}`, `#151515`→`${surface}`, `#1c1c1c`→`${card}`, `#e5a00d`→`${accent}`, `#f0b429`→`${accent_hover}`, `#1f1a0e`→`${selection_bg}`, `#3ea463`→`${success}`, `#d44040`→`${error}`, `#4a9eda`→`${info}`, `#777777`→`${text_dim}`, `#e0e0e0`→`${text}`, `#2a2a2a`→`${border}`, `#3a3a3a`→`${border_light}`, `#4a4a4a`→`${text_muted}`, etc. Status-pill tone backgrounds become washes: `#1a3328`→`rgba(63, 185, 80, 0.12)`, `#2a2210`→`rgba(210, 153, 34, 0.12)` with `color/border` `${warning}` (pill tone `accent` = review/warning semantics), `#2d1414`→`rgba(229, 83, 75, 0.12)`, `#142030`→`rgba(88, 166, 255, 0.12)`. `QLineEdit selection-background-color: #7a5a10`→`${accent_dim}`. Drop-zone `rgba(229, 160, 13, 0.05)`→`rgba(0, 164, 220, 0.06)`.

3. **Radius normalization** — replace every `border-radius` per this table (all others → `${radius_md}px`):

| Selector(s) | Radius |
|---|---|
| `QMenu`, `QFrame[cssClass="drop-zone"]`, `QFrame[cssClass="media-detail-content-surface"]`, `QFrame[cssClass="settings-section"]`, `QGroupBox` | `${radius_lg}px` |
| `QLabel[cssClass="status-pill"]`, `QLabel[cssClass="tab-badge-count"]` | `${radius_pill}px` |
| `QScrollBar::handle:*`, `QToolTip`, `QMenuBar::item`, `[sizeVariant="inline"]` buttons, `QComboBox`, `QLineEdit`, `QCheckBox::indicator`, `settings-nav::item`, `QProgressBar` (3px→`${radius_sm}px`), tab-badge-pip (4px→`${radius_sm}px`) | `${radius_sm}px` |
| Everything else (buttons, cards, panels, lists, list items, tables, segments…) | `${radius_md}px` |

Keep `QFrame[cssClass="panel"][panelVariant="square"] { border-radius: 0px; }` — the 3-panel workspace still needs flush panels until Plan 3 deletes the variant.

4. **Fringe removal + card shading** — replace the `roster-row-card` / `preview-row-card` blocks entirely with:

```css
QFrame[cssClass="roster-row-card"],
QFrame[cssClass="preview-row-card"] {
    background-color: ${card};
    border: 1px solid transparent;
    border-radius: ${radius_md}px;
}

QFrame[cssClass="roster-row-card"]:hover,
QFrame[cssClass="preview-row-card"]:hover {
    background-color: ${card_hover};
}

QFrame[cssClass="roster-row-card"][selectionState="selected"],
QFrame[cssClass="preview-row-card"][selectionState="selected"] {
    background-color: ${selection_bg};
    border: 1px solid ${accent};
}

/* Graceful status shading (replaces the left-edge fringe) */
QFrame[cssClass="roster-row-card"][band="high"],
QFrame[cssClass="preview-row-card"][band="high"] { background-color: rgba(63, 185, 80, 0.05); }
QFrame[cssClass="roster-row-card"][band="medium"],
QFrame[cssClass="preview-row-card"][band="medium"] { background-color: rgba(210, 153, 34, 0.05); }
QFrame[cssClass="roster-row-card"][band="low"],
QFrame[cssClass="preview-row-card"][band="low"],
QFrame[cssClass="preview-row-card"][band="error"] { background-color: rgba(229, 83, 75, 0.06); }
QFrame[cssClass="roster-row-card"][band="muted"],
QFrame[cssClass="preview-row-card"][band="muted"] { background-color: ${card}; }
```

(Selected beats band because it comes later in the sheet — keep this order.) In `QFrame[cssClass="callout-banner"]` delete the `border-left: 4px solid …;` line, keep the rest.

5. **Sticky header** — `QLabel[cssClass="sticky-season-header"]`: `background-color: ${section_header_bg}; color: ${accent};` (drop the rgba amber), border-bottom `${border_light}`.

- [ ] **Step 4: Switch `app.py` to the renderer**

Replace lines 18 and 142–146:

```python
# line 18 area — delete: _THEME_PATH = Path(__file__).parent / "resources" / "theme.qss"
```

```python
    # Load the global theme stylesheet (rendered from theme.qss.tmpl)
    from . import theme as _theme
    try:
        app.setStyleSheet(_theme.load_stylesheet())
    except (OSError, KeyError) as exc:
        _log.warning("Theme stylesheet failed to load: %s", exc)
```

(`Path` import in app.py becomes unused — remove it.)

- [ ] **Step 5: Run guard tests + fast sweep + smoke**

Run: `.venv\Scripts\python.exe -m pytest tests\test_gui_theme.py -q` → all pass.
Run: `scripts\test-fast.cmd` then `scripts\test-smoke.cmd` → pass. If smoke asserts old colors (grep first: `.venv\Scripts\python.exe -m pytest --collect-only -q tests\test_gui_qt_smoke.py` and `grep -rn "#e5a00d\|#1f1a0e\|#0d0d0d\|#f0b429" tests\`), update those assertions to `theme.color(...)` lookups instead of literals.

- [ ] **Step 6: Commit**

```bash
git add -A plex_renamer/gui_qt/resources plex_renamer/gui_qt/app.py tests
git commit -m "feat(gui): render QSS from Jellyfin token template; remove card fringe, normalize radii"
```

---

### Task 3: Replace hex literals in widget code with theme tokens

**Files:**
- Modify: `plex_renamer/gui_qt/widgets/_media_helpers.py:44-60,63-82,355-356` · `_workspace_widget_primitives.py:39-44,94,168-173,246` · `models/job_table_model.py:35-41` · `widgets/toast_manager.py:25-29,54-58,96-99` · `widgets/scan_progress.py:93-116` · `widgets/_image_utils.py:52,70-92` · `widgets/_job_list_tab.py:31-33,112-121` · `widgets/tab_badge.py:57` · `widgets/job_detail_panel.py:408` · `widgets/_match_picker_selection.py:16` · `widgets/_media_detail_artwork.py:90`
- Test: `tests/test_gui_theme.py` (extend)

**Interfaces:**
- Consumes: `theme.color/qcolor/rgba` (Task 1).
- Produces: `_media_helpers.confidence_fill_color/band_color` now return warning for medium (later plans rely on `warning` ≠ `accent`); a permanent no-hex guard over `gui_qt`.

- [ ] **Step 1: Write the failing guard test (extend `tests/test_gui_theme.py`)**

```python
def test_no_hex_literals_outside_theme_module():
    offenders: list[str] = []
    for path in sorted(_GUI_ROOT.rglob("*.py")):
        if path.name == "theme.py":
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _HEX_RE.search(line):
                offenders.append(f"{path.relative_to(_GUI_ROOT)}:{lineno}: {line.strip()}")
    assert offenders == [], "\n".join(offenders)
```

Run: `.venv\Scripts\python.exe -m pytest tests\test_gui_theme.py::test_no_hex_literals_outside_theme_module -q`
Expected: FAIL listing ~65 offender lines across 11 files (the worklist).

- [ ] **Step 2: Convert the two semantic hubs (exact code)**

`_media_helpers.py` — add `from .. import theme` and replace:

```python
def confidence_fill_color(score: float, *, state: ScanState | None = None, media_type: str = "tv") -> str:
    return band_color(confidence_band(score, state=state, media_type=media_type))


def band_color(band: str) -> str:
    return {
        "high": theme.color("success"),
        "medium": theme.color("warning"),
        "low": theme.color("error"),
        "muted": theme.color("text_dim"),
        "error": theme.color("error"),
    }[band]
```

`state_status` tones (same file): Queued→`theme.qcolor("info")`, Scanning→`theme.qcolor("warning")`, Scan Failed→`theme.qcolor("error")`, Duplicate→`theme.qcolor("text_dim")`, No Match Found→`theme.qcolor("error")`, Review Match / Review Episode Matching→`theme.qcolor("warning")`, Approved→`theme.qcolor("info")`, Fully Ready (Task 4 renames the string)→`theme.qcolor("success")`, Matched→`theme.qcolor("info")`. `make_section_header`: `header.setForeground(theme.qcolor("accent"))`, `header.setBackground(theme.qcolor("section_header_bg"))`.

`models/job_table_model.py`:

```python
from ..theme import qcolor as _theme_qcolor

_STATUS_COLORS = {
    JobStatus.PENDING: _theme_qcolor("text_dim"),
    JobStatus.RUNNING: _theme_qcolor("accent"),
    JobStatus.COMPLETED: _theme_qcolor("success"),
    JobStatus.FAILED: _theme_qcolor("error"),
    JobStatus.CANCELLED: _theme_qcolor("text_muted"),
    JobStatus.REVERTED: _theme_qcolor("info"),
    JobStatus.REVERT_FAILED: _theme_qcolor("error"),
}
```

- [ ] **Step 3: Convert the remaining files (mechanical, mapping table)**

Import `from .. import theme` (or `from . import theme` relative to location) and swap per the canonical table. Notables:

- `_workspace_widget_primitives.py` (both widget classes): `_BG_OFF=theme.qcolor("border_light")`, `_BG_ON=theme.qcolor("success")`, `_BG_PARTIAL=theme.qcolor("info")`, `_BORDER_OFF=theme.qcolor("border_light")`, `_BORDER_ON=theme.qcolor("success_dim")`, `_CHECK_COLOR=theme.qcolor("on_accent")`; line 94 disabled/enabled pen → `theme.qcolor("text_dim")`/`theme.qcolor("text")`; line 246 track → `theme.qcolor("border")`.
- `toast_manager.py`: `_BORDER_COLORS = {"success": theme.color("success"), "error": theme.color("error"), "accent": theme.color("info")}`; card stylesheet → `f"background-color: {theme.color('surface')}; border: 1px solid {theme.color('border')}; border-radius: {theme.radius('lg')}px;"` (**drop the `border-left` fragment — fringe removal**; the tone still colors the countdown bar); progress bar stylesheet → `theme.color("border")` background.
- `_job_list_tab.py`: `_HOVER_COLOR = theme.qcolor("card_hover")`, `_SELECTED_ROW_COLOR = theme.qcolor("selection_bg")`; **delete `_ROW_ACCENT_COLOR` and the `if index.column() == 0: painter.fillRect(QRect(...4px...))` stripe block** in `_HoverRowDelegate.paint` (fringe removal).
- `scan_progress.py` animation: ring `theme.qcolor("border_light")`, accent `theme.qcolor("accent")`, idle dot `theme.qcolor("card_hover")`, core `theme.qcolor("selection_bg")`.
- `_image_utils.py`: default `accent: str | None = None` → resolve `accent = accent or theme.color("accent")` inside; gradient stops `theme.qcolor("card_hover")`/`theme.qcolor("surface")`; border `theme.qcolor("border")`; title `theme.qcolor("text")`; subtitle `theme.qcolor("text_dim")`.
- `tab_badge.py:57` → `f"background-color: {theme.color('error')}; color: {theme.color('on_accent')}; border-color: {theme.color('error')};"`.
- `job_detail_panel.py:408` → `self._error.setStyleSheet(f"color: {theme.color('error')};")`.
- `_match_picker_selection.py:16` → `_SUCCESS_COLOR = theme.qcolor("success")`.
- `_media_detail_artwork.py:90` → `accent=theme.color("info") if mode == "still" else theme.color("accent")`.

- [ ] **Step 4: Run the guard + suites**

Run: `.venv\Scripts\python.exe -m pytest tests\test_gui_theme.py -q` → all pass (offender list empty).
Run: `scripts\test-fast.cmd` and `scripts\test-smoke.cmd` → pass; fix any test asserting old literals by importing `theme` (search: `grep -rn "#3ea463\|#d44040\|#4a9eda\|#e5a00d" tests\`).

- [ ] **Step 5: Commit**

```bash
git add -A plex_renamer/gui_qt tests
git commit -m "refactor(gui): route all widget colors through theme tokens"
```

---

### Task 4: De-Plex all user-facing strings

**Files:**
- Modify: `plex_renamer/gui_qt/main_window.py:67` · `gui_qt/app.py:137` · `gui_qt/_main_window_shell.py:71-79` · `gui_qt/__init__.py:1` · `widgets/_media_helpers.py:81,156` · `widgets/media_workspace.py:75` · `widgets/_media_workspace_roster.py:221` · `widgets/_media_workspace_queue_actions.py:91` · `app/services/command_gating_service.py:17` (docstring) · `app/services/settings_service.py:71` (docstring)
- Modify tests: `tests/test_qt_queue_history.py:612`, `tests/test_qt_media_workspace.py:3716` (group key)
- Test: `tests/test_gui_theme.py` (extend)

**Interfaces:**
- Consumes: nothing new.
- Produces: status string **"Fully Ready"**, roster group key **"fully-ready"** (Plans 2+ build their grouping on these exact values); app name "NameScraper".

- [ ] **Step 1: Write the failing string-sweep test (extend `tests/test_gui_theme.py`)**

```python
import ast

_PLEX_ALLOWED_SUBSTRINGS = ("plex_renamer", "PLEX_RENAMER")  # package/env names, not UI copy


def _plex_literals(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value
            if "plex" not in text.lower():
                continue
            cleaned = text
            for allowed in _PLEX_ALLOWED_SUBSTRINGS:
                cleaned = cleaned.replace(allowed, "")
            if "plex" in cleaned.lower():
                hits.append(f"{path.name}:{node.lineno}: {text!r}")
    return hits


def test_no_plex_string_literals_in_gui():
    offenders: list[str] = []
    for path in sorted(_GUI_ROOT.rglob("*.py")):
        offenders.extend(_plex_literals(path))
    assert offenders == [], "\n".join(offenders)
```

Run: `.venv\Scripts\python.exe -m pytest tests\test_gui_theme.py::test_no_plex_string_literals_in_gui -q`
Expected: FAIL listing the window title, About text, "Plex Ready", "plex-ready", "already Plex-ready".

- [ ] **Step 2: Apply the renames (exact replacements)**

- `main_window.py:67` → `self.setWindowTitle("NameScraper")`
- `app.py:137` → `app.setApplicationName("NameScraper")`
- `_main_window_shell.py` About block →

```python
        message_box_api.about(
            self._window,
            "About NameScraper",
            "NameScraper — GUI4 (PySide6)\n\n"
            "Rename and organize media files into clean,\n"
            "server-friendly naming conventions.\n\n"
            "Metadata provided by TMDB.",
        )
```

- `gui_qt/__init__.py` docstring: `"""PySide6 shell for NameScraper. …`
- `_media_helpers.py:81` → `return "Fully Ready", theme.qcolor("success")`; `:156` → `return "fully-ready"`
- `media_workspace.py:75` → `self._roster_collapsed: dict[str, bool] = {"fully-ready": True}`
- `_media_workspace_roster.py:221` → `("fully-ready", "Fully Ready"),`
- `_media_workspace_queue_actions.py:91` → `reasons["already fully ready"] = reasons.get("already fully ready", 0) + 1`
- `command_gating_service.py:17` docstring → `"""True when a scanned entry is already fully organized and non-queueable."""` (method *name* `is_plex_ready_state` is internal API used across helpers/tests — rename lands in Plan 2 when the grouping code is rewritten anyway; the AST sweep only checks `gui_qt`.)
- `settings_service.py:71` docstring → `"""Whether to hide fully-ready items from the library roster."""`
- Tests: `test_qt_queue_history.py:612` and `test_qt_media_workspace.py:3716` → `_roster_collapsed["fully-ready"] = False`. Then sweep for stragglers: `grep -rn "plex-ready\|Plex Ready\|Plex-ready" plex_renamer tests` — expect only `command_gating_service.py` method-name hits and engine `PLEX_READY_EPISODE_FLOOR` (both allowed, non-GUI).

- [ ] **Step 3: Run suites**

Run: `.venv\Scripts\python.exe -m pytest tests\test_gui_theme.py -q` → pass.
Run: `scripts\test-fast.cmd` and `scripts\test-smoke.cmd` → pass; fix any test asserting the old window title or "Plex Ready" status text (`grep -rn "Plex Renamer\|Plex Ready" tests\`).

- [ ] **Step 4: Commit**

```bash
git add -A plex_renamer tests
git commit -m "feat(gui): de-Plex UI strings - NameScraper title, Fully Ready status/group"
```

---

### Task 5: Remove the Ctrl+Z undo shortcut and menu action

**Files:**
- Modify: `plex_renamer/gui_qt/_main_window_chrome.py:41-47` · `gui_qt/main_window.py:342-343` · `gui_qt/_main_window_shell.py:34-69`
- Test: `tests/test_qt_chrome.py` (create)

**Interfaces:**
- Consumes: nothing new.
- Produces: Edit menu = Settings only; no Ctrl+Z anywhere. History-tab revert is untouched and remains the only undo path.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_qt_chrome.py
"""Menu-bar and shortcut safety checks (GUI V4 §14)."""
from __future__ import annotations

from PySide6.QtGui import QKeySequence


def _all_actions(window):
    actions = list(window.actions())
    for menu_action in window.menuBar().actions():
        menu = menu_action.menu()
        if menu is not None:
            actions.extend(menu.actions())
    return actions


def test_no_ctrl_z_shortcut_registered(qt_main_window):
    ctrl_z = QKeySequence("Ctrl+Z")
    for action in _all_actions(qt_main_window):
        assert action.shortcut() != ctrl_z, f"Ctrl+Z still bound to {action.text()!r}"


def test_edit_menu_has_no_undo_entry(qt_main_window):
    edit_menu = next(
        a.menu() for a in qt_main_window.menuBar().actions() if "Edit" in a.text()
    )
    labels = [a.text() for a in edit_menu.actions() if a.text()]
    assert not any("undo" in label.lower() for label in labels)
```

Reuse the existing smoke-suite MainWindow fixture: check `tests/test_gui_qt_smoke.py` / `tests/conftest.py` for the fixture that constructs `MainWindow` (search `grep -rn "MainWindow(" tests\conftest.py tests\test_gui_qt_smoke.py`) and use its name in place of `qt_main_window` if it differs.

Run: `.venv\Scripts\python.exe -m pytest tests\test_qt_chrome.py -q`
Expected: FAIL — Ctrl+Z is bound to "Undo Last Rename".

- [ ] **Step 2: Remove the action and dead code**

In `_main_window_chrome.py` replace the Edit-menu block with:

```python
        edit_menu = menu_bar.addMenu("&Edit")

        settings_action = edit_menu.addAction("&Settings")
        settings_action.setShortcut(QKeySequence("Ctrl+,"))
        settings_action.triggered.connect(
            lambda: window._tabs.setCurrentIndex(self._settings_index)
        )
```

Delete `MainWindow._on_undo` (main_window.py:342-343) and `MainWindowShellCoordinator.undo_last_rename` (_main_window_shell.py:34-69). Verify nothing else calls them: `grep -rn "_on_undo\|undo_last_rename" plex_renamer tests` → expect zero hits after deletion (`queue_ctrl.revert_job` / `get_latest_revertible_job` usages elsewhere stay).

- [ ] **Step 3: Run suites**

Run: `.venv\Scripts\python.exe -m pytest tests\test_qt_chrome.py -q` → pass.
Run: `scripts\test-fast.cmd` and `scripts\test-smoke.cmd` → pass (remove/adjust any smoke test exercising the undo menu; find with `grep -rn "Undo Last\|_on_undo" tests\`).

- [ ] **Step 4: Commit**

```bash
git add -A plex_renamer/gui_qt tests
git commit -m "feat(gui): remove dangerous Ctrl+Z undo shortcut and Edit-menu action"
```

---

### Task 6: Recent-folder menus switch to the owning tab

**Files:**
- Modify: `plex_renamer/gui_qt/_main_window_state.py:86-105`
- Test: `tests/test_qt_chrome.py` (extend)

**Interfaces:**
- Consumes: `MainWindowStateCoordinator._tv_index/_movies_index` (already in ctor), `window._switch_to_tab`, workspace `load_folder`.
- Produces: `rebuild_recent_menus` whose actions always land the user on the tab that owns the folder.

- [ ] **Step 1: Write the failing test (extend `tests/test_qt_chrome.py`)**

```python
def test_recent_movie_folder_switches_to_movies_tab(qt_main_window, monkeypatch, tmp_path):
    window = qt_main_window
    folder = str(tmp_path / "Movies")
    window.settings_service.add_recent_movie_folder(folder)
    window._rebuild_recent_menus()

    loaded: list[str] = []
    monkeypatch.setattr(window._movie_workspace, "load_folder", loaded.append)

    window._tabs.setCurrentIndex(1)  # TV tab active
    window._recent_movie_menu.actions()[0].trigger()

    assert window._tabs.currentIndex() == 2, "movie folder must switch to Movies tab"
    assert loaded == [folder]
```

Run: `.venv\Scripts\python.exe -m pytest tests\test_qt_chrome.py::test_recent_movie_folder_switches_to_movies_tab -q`
Expected: FAIL — current index stays 1.

- [ ] **Step 2: Implement**

In `_main_window_state.py`, replace `rebuild_recent_menus` internals:

```python
    def rebuild_recent_menus(self) -> None:
        window = self._window

        window._recent_tv_menu.clear()
        for folder in window.settings_service.recent_tv_folders:
            path = Path(folder)
            action = window._recent_tv_menu.addAction(f"{path.name}  ({path})")
            action.triggered.connect(
                lambda _=False, selected=folder: self._load_recent(selected, media_type="tv")
            )
        window._recent_tv_menu.setEnabled(bool(window.settings_service.recent_tv_folders))

        window._recent_movie_menu.clear()
        for folder in window.settings_service.recent_movie_folders:
            path = Path(folder)
            action = window._recent_movie_menu.addAction(f"{path.name}  ({path})")
            action.triggered.connect(
                lambda _=False, selected=folder: self._load_recent(selected, media_type="movie")
            )
        window._recent_movie_menu.setEnabled(bool(window.settings_service.recent_movie_folders))

    def _load_recent(self, folder: str, *, media_type: str) -> None:
        """Recent-folder click: land on the owning tab, then load (GUI V4 §14)."""
        window = self._window
        if media_type == "tv":
            self.switch_to_tab(self._tv_index)
            window._tv_workspace.load_folder(folder)
            return
        self.switch_to_tab(self._movies_index)
        window._movie_workspace.load_folder(folder)
```

- [ ] **Step 3: Run suites**

Run: `.venv\Scripts\python.exe -m pytest tests\test_qt_chrome.py -q` → pass.
Run: `scripts\test-fast.cmd` and `scripts\test-smoke.cmd` → pass.

- [ ] **Step 4: Commit**

```bash
git add plex_renamer/gui_qt/_main_window_state.py tests/test_qt_chrome.py
git commit -m "fix(gui): recent-folder menu actions switch to the owning tab before loading"
```

---

### Task 7: Full-suite verification + roadmap/handoff bookkeeping

**Files:**
- Modify: `docs/superpowers/plans/2026-07-03-gui-v4-implementation.md` (Plan 1 status → landed), `docs/superpowers/plans/2026-07-03-gui-v4-handoff.md` (status + next step → write Plan 2)

- [ ] **Step 1: Run everything**

Run: `scripts\test-fast.cmd` → expected: pass, 0 failures.
Run: `scripts\test-smoke.cmd` → expected: pass; skim `.pytest_cache/smoke/latest.log` for warnings.
Run: `.venv\Scripts\python.exe -m pytest tests\test_gui_theme.py tests\test_qt_chrome.py -q` → all pass.

- [ ] **Step 2: Manual sanity launch (visual)**

Run: `.venv\Scripts\python.exe -m plex_renamer --qt`
Check: window titled "NameScraper"; Jellyfin blue accents (tabs, buttons, selection); no amber anywhere; no colored left edge on cards or toasts; "Fully Ready" group header; Edit menu has only Settings; a recent movie folder opened from the TV tab lands on Movies. Close.

- [ ] **Step 3: Update roadmap + handoff, commit**

Mark Plan 1 landed in the roadmap table; set handoff "Next step" to "write Plan 2 (roster) via superpowers:writing-plans".

```bash
git add docs/superpowers/plans
git commit -m "docs: mark GUI V4 plan 1 landed; next up plan 2 (roster)"
```
