# tests/test_gui_perf_guards.py
"""Spec §7 standing guards: the GUI package must never block-and-pump."""
import unittest
from pathlib import Path

_GUI_ROOT = Path(__file__).resolve().parent.parent / "plex_renamer" / "gui_qt"
_FORBIDDEN = ("processEvents(", "time.sleep(")


class GuiEventLoopGuards(unittest.TestCase):
    def test_gui_package_never_pumps_or_sleeps(self):
        offenders: list[str] = []
        for source in sorted(_GUI_ROOT.rglob("*.py")):
            text = source.read_text(encoding="utf-8")
            for needle in _FORBIDDEN:
                if needle in text:
                    offenders.append(f"{source.relative_to(_GUI_ROOT)}: {needle}")
        self.assertEqual(
            offenders, [],
            "processEvents/time.sleep are banned in gui_qt (spec §7); "
            "move the work to plex_renamer.thread_pool.submit or use BusyOverlay.",
        )
