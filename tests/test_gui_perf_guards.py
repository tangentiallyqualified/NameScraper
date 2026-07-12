# tests/test_gui_perf_guards.py
"""Spec §7 standing guards: the GUI package must never block-and-pump."""
import unittest
from pathlib import Path

_GUI_ROOT = Path(__file__).resolve().parent.parent / "plex_renamer" / "gui_qt"
_FORBIDDEN = ("processEvents(", "time.sleep(")


class GuiEventLoopGuards(unittest.TestCase):
    def test_gui_package_never_pumps_or_sleeps(self):
        offenders: list[str] = []
        files_scanned = 0
        for source in sorted(_GUI_ROOT.rglob("*.py")):
            files_scanned += 1
            text = source.read_text(encoding="utf-8")
            for needle in _FORBIDDEN:
                if needle in text:
                    offenders.append(f"{source.relative_to(_GUI_ROOT)}: {needle}")
        self.assertGreater(
            files_scanned, 20,
            "gui_qt sweep saw almost no files — the guard would pass vacuously "
            "(package moved/renamed?)",
        )
        self.assertEqual(
            offenders, [],
            "processEvents/time.sleep are banned in gui_qt (spec §7); "
            "move the work to plex_renamer.thread_pool.submit or use BusyOverlay.",
        )
