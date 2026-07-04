"""Theme token module and stylesheet rendering guards."""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from plex_renamer.gui_qt import theme

_GUI_ROOT = Path(__file__).resolve().parents[1] / "plex_renamer" / "gui_qt"
_HEX_RE = re.compile(r"#[0-9a-fA-F]{6}\b")


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


def test_no_hex_literals_outside_theme_module():
    offenders: list[str] = []
    for path in sorted(_GUI_ROOT.rglob("*.py")):
        if path.name == "theme.py":
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _HEX_RE.search(line):
                offenders.append(f"{path.relative_to(_GUI_ROOT)}:{lineno}: {line.strip()}")
    assert offenders == [], "\n".join(offenders)


_PLEX_ALLOWED_SUBSTRINGS = ("plex_renamer", "PLEX_RENAMER", "plex-renamer")  # package/env names, not UI copy


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


_DELETED_GUI_MODULES = (
    "_media_workspace_preview", "media_detail_panel", "_media_detail_artwork",
    "_media_detail_payloads", "_media_detail_state", "_media_detail_workflow",
    "_workspace_widgets",
)


def test_deleted_panel_modules_stay_deleted():
    present = [name for name in _DELETED_GUI_MODULES
               if (_GUI_ROOT / "widgets" / f"{name}.py").exists()]
    assert present == [], f"GUI V4 deleted these modules; they came back: {present}"
