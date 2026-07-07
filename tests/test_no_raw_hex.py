# tests/test_no_raw_hex.py
"""No raw hex color literals in gui_qt Python (theme tokens only) — GUI-V4 R2 G6.

``theme.py`` is the single source of truth for color tokens (``COLORS``); all
other ``gui_qt`` modules must reference colors via ``theme.color(...)`` /
``theme.qcolor(...)`` rather than inlining hex literals.

The guard matches QUOTED hex literals (e.g. ``"#1c2a33"``) rather than a
whole-line scan, so it does not false-positive on comments that mention a
color in prose, or on issue/PR references like ``#123``.
"""
from __future__ import annotations

import re
from pathlib import Path

_HEX = re.compile(
    r"""["']#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3}(?:[0-9a-fA-F]{2})?)?["']"""
)
_ALLOWED = {"theme.py"}  # the single source of truth for tokens


def _gui_py_files():
    root = Path(__file__).resolve().parent.parent / "plex_renamer" / "gui_qt"
    return [p for p in root.rglob("*.py") if p.name not in _ALLOWED]


def test_no_raw_hex_in_gui_qt():
    offenders = []
    for path in _gui_py_files():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _HEX.search(line) and "noqa: hex" not in line:
                offenders.append(f"{path.name}:{lineno}: {line.strip()}")
    assert not offenders, "Raw hex found (use theme tokens):\n" + "\n".join(offenders)
