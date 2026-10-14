"""Tests for the glass look, pomo's only one: stylesheet, ignored legacy
theme pref, settings dialog, frosting helpers.

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
        css = pomo_qt.stylesheet()
        self.assertNotIn("{{", css)
        self.assertNotIn("}}", css)
        self.assertNotIn("{t[", css)

    def test_saved_theme_key_is_ignored(self):
        legacy = "ember"
        pomo_qt.save_json(pomo_qt.PREFS_FILE, {"theme": legacy})
        win = pomo_qt.PomoWindow()
        self.assertEqual([k for k in vars(win) if "theme" in k], [])
        win._persist_prefs()
        self.assertEqual(
            pomo_qt.load_json(pomo_qt.PREFS_FILE, {})["theme"], legacy)

    def test_settings_dialog_has_no_theme_row(self):
        dlg = pomo_qt.SettingsDialog(pomo_qt.PomoWindow())
        self.assertEqual([k for k in vars(dlg) if "theme" in k], [])

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
