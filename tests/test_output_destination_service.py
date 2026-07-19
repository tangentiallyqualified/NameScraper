# tests/test_output_destination_service.py
"""Long-path (Windows MAX_PATH) risk predicate (S1)."""

from __future__ import annotations

from plex_renamer.app.services.output_destination_service import (
    long_path_warning_text,
    output_path_risks_long_paths,
)


def test_short_root_not_flagged():
    assert output_path_risks_long_paths(r"C:\Media\TV") is False
    assert long_path_warning_text(r"C:\Media\TV") == ""


def test_very_long_root_flagged():
    root = r"C:\Users\somebody\Videos\Archive\Television\Complete Collections\By Network" + (
        "\\deep" * 12
    )
    assert output_path_risks_long_paths(root) is True
    assert "260" in long_path_warning_text(root)
