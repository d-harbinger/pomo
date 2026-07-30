"""Characterization tests for TemplatesDialog.

The dialog's slot rows are produced on two paths: the initial build and the
rebuild that runs after a slot changes. These tests pin down the visible
structure both paths produce — one saved slot shows its name plus
Save current / Load / Rename / delete, empty slots show only Save current —
so the row construction can be restructured without changing behavior.

Run headless (no display needed):
    venv/bin/python -m unittest discover tests
"""

import json
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

from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QHBoxLayout, QPushButton,
)

import pomo_qt


def _row_button_texts(layout):
    """Button labels per slot row, in layout order."""
    rows = []
    for i in range(layout.count()):
        sub = layout.itemAt(i).layout()
        if not isinstance(sub, QHBoxLayout):
            continue
        texts = []
        for j in range(sub.count()):
            w = sub.itemAt(j).widget()
            if isinstance(w, QPushButton):
                texts.append(w.text())
        rows.append(texts)
    return rows


class TemplatesDialogStructure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QApplication.instance() or QApplication([])

    def setUp(self):
        # One saved template in slot 0, the remaining slots empty.
        (Path(_TMP) / "templates.json").write_text(json.dumps([
            {"name": "Morning", "sessions": [
                {"type": "work", "name": "Focus", "duration": 45},
                {"type": "short_break", "name": "Short Break", "duration": 10},
            ]},
        ]))
        self.win = pomo_qt.PomoWindow()

    def tearDown(self):
        self.win.close()

    def assert_structure(self, dlg):
        layout = dlg.layout()
        # One row per slot, plus the closing button box.
        self.assertEqual(layout.count(), pomo_qt.TEMPLATE_SLOTS + 1)
        rows = _row_button_texts(layout)
        self.assertEqual(len(rows), pomo_qt.TEMPLATE_SLOTS)
        # The saved slot offers the full action set; empty slots only Save.
        self.assertEqual(rows[0], ["Save current", "Load", "Rename", "×"])
        for texts in rows[1:]:
            self.assertEqual(texts, ["Save current"])

    def test_initial_build_structure(self):
        dlg = pomo_qt.TemplatesDialog(self.win)
        self.assert_structure(dlg)

    def test_rebuild_produces_same_structure(self):
        dlg = pomo_qt.TemplatesDialog(self.win)
        dlg._rebuild()
        self.assert_structure(dlg)

    def assert_close_rejects(self, dlg):
        # Behavior, not wiring: whatever the button box connects
        # internally, pressing Close must dismiss the dialog as rejected.
        bb = dlg.findChildren(QDialogButtonBox)[-1]
        bb.button(QDialogButtonBox.Close).click()
        self.assertEqual(dlg.result(), QDialog.Rejected)

    def test_close_button_rejects_after_build(self):
        self.assert_close_rejects(pomo_qt.TemplatesDialog(self.win))

    def test_close_button_rejects_after_rebuild(self):
        dlg = pomo_qt.TemplatesDialog(self.win)
        dlg._rebuild()
        self.assert_close_rejects(dlg)


if __name__ == "__main__":
    unittest.main()
