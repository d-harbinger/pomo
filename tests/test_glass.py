"""Tests for the glass theme: stylesheet, theme table, default, frosting helpers.

Run headless (no display needed):
    venv/bin/python -m unittest discover tests
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

# Point the app at a throwaway data dir BEFORE importing it — pomo_qt
# resolves POMO_DATA_DIR at import time. The offscreen platform lets Qt
# construct real widgets without a display server.
_TMP = tempfile.mkdtemp(prefix="pomo-test-")
os.environ["POMO_DATA_DIR"] = _TMP
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication

# pomo_qt is imported in setUpClass, not here: discovery imports this file
# before test_templates_dialog, and the first import of pomo_qt fixes its
# data directory for the whole run. Importing late lets the other module's
# directory win, so its fixtures keep working.
pomo_qt = None


class GlassTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global pomo_qt
        import pomo_qt as module
        pomo_qt = module
        cls.qapp = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls):
        if pomo_qt.PREFS_FILE.exists():
            pomo_qt.PREFS_FILE.unlink()

    def setUp(self):
        prefs = pomo_qt.PREFS_FILE
        if prefs.exists():
            prefs.unlink()

    def test_stylesheet_builds_without_unformatted_braces(self):
        css = pomo_qt.stylesheet(pomo_qt.THEMES["glass"])
        self.assertNotIn("{{", css)
        self.assertNotIn("}}", css)
        self.assertNotIn("{t[", css)

    def test_every_theme_has_every_midnight_key(self):
        keys = set(pomo_qt.THEMES["midnight"])
        for name, theme in pomo_qt.THEMES.items():
            self.assertFalse(keys - set(theme), name)

    def test_glass_listed_first_and_flagged(self):
        self.assertEqual(next(iter(pomo_qt.THEMES)), "glass")
        self.assertTrue(pomo_qt.THEMES["glass"]["glass"])

    def test_window_builds_and_switches_theme(self):
        win = pomo_qt.PomoWindow()
        self.assertEqual(win.theme_name, "glass")
        win.set_theme("midnight")
        win.set_theme("glass")
        self.assertEqual(win.theme_name, "glass")

    def test_saved_theme_is_kept(self):
        pomo_qt.save_json(pomo_qt.PREFS_FILE, {"theme": "ember"})
        self.assertEqual(pomo_qt.PomoWindow().theme_name, "ember")

    def test_unknown_theme_falls_back_to_glass(self):
        pomo_qt.save_json(pomo_qt.PREFS_FILE, {"theme": "nope"})
        self.assertEqual(pomo_qt.PomoWindow().theme_name, "glass")

    def test_fehbg_parser(self):
        parse = pomo_qt.parse_fehbg
        self.assertEqual(
            parse("#!/bin/sh\nfeh --no-fehbg --bg-fill '/tmp/a b.jpg'\n"),
            "/tmp/a b.jpg")
        self.assertEqual(parse('feh --bg-scale "/x/y.png"'), "/x/y.png")
        self.assertIsNone(parse(""))

    def test_compositor_check_returns_bool(self):
        self.assertIsInstance(pomo_qt.compositor_running(), bool)
        self.assertIn(pomo_qt.frost_mode(), ("compositor", "wayland", "fake"))


if __name__ == "__main__":
    unittest.main()
