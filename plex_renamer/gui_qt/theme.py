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

_RESOURCES_DIR = Path(__file__).parent / "resources"
_TEMPLATE_PATH = _RESOURCES_DIR / "theme.qss.tmpl"


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
    # QSS url() paths resolve against the CWD for string stylesheets, so the
    # template gets an absolute posix path (quoted in the QSS — the repo path
    # contains spaces).
    mapping["check_svg"] = (_RESOURCES_DIR / "check.svg").as_posix()
    return mapping


def render_template(text: str) -> str:
    return Template(text).substitute(_mapping())


@lru_cache(maxsize=1)
def load_stylesheet() -> str:
    return render_template(_TEMPLATE_PATH.read_text(encoding="utf-8"))
