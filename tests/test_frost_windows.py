"""Every window pomo opens follows the main window's frosting decision.

The main window decides once, before first show, whether it is translucent
(compositor on X11, or Wayland) or paints its own frosted background (X11
without a compositor, offscreen). Each popup, dialog, message box, input
dialog and menu the app opens must be translucent exactly when the main
window is, and paint an opaque THEME background otherwise.

The windows are opened through the app's own code paths; a short poll
records each one as it appears and closes it, so modal exec() returns.

Run headless (no display needed):
    "venv-$(uname -n)/bin/python" -m unittest discover tests
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Point the app at a throwaway data dir BEFORE importing it — pomo_qt
# resolves POMO_DATA_DIR at import time. The offscreen platform lets Qt
# construct real widgets without a display server.
_TMP = tempfile.mkdtemp(prefix="pomo-test-")
os.environ["POMO_DATA_DIR"] = _TMP
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QPushButton

# pomo_qt is imported in setUpClass, not here, for the same reason as in
# test_glass: the first import fixes the data directory for the whole run,
# and test_templates_dialog's fixtures need its own directory to win.
pomo_qt = None

TRANSLUCENT = Qt.WA_TranslucentBackground


class FrostFollowsMainWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global pomo_qt
        import pomo_qt as module
        pomo_qt = module
        cls.qapp = QApplication.instance() or QApplication([])

    def make_window(self, mode):
        with mock.patch.object(pomo_qt, "frost_mode", return_value=mode):
            win = pomo_qt.PomoWindow()
        win.sessions = [pomo_qt.Session(type="work", name="Focus",
                                        duration=25)]
        win.current_index = 0
        win._refresh_all()
        win.show()
        self.qapp.processEvents()
        self.addCleanup(win.close)
        return win

    def opened_by(self, action):
        """Run `action`; return (is_window, translucent, background alpha)
        of the window it opens.

        Modal windows (exec) and menus block, so a timer polls for the
        active modal or popup window, records it and closes it. Non-modal
        popups are still open when `action` returns and are closed here.
        Recording happens at capture: a window may be deleted on close.
        """
        seen = []

        def poll():
            w = (QApplication.activeModalWidget()
                 or QApplication.activePopupWidget())
            if w is not None and not seen:
                seen.append((w.isWindow(), w.testAttribute(TRANSLUCENT),
                             w.palette().color(QPalette.Window).alpha()))
                w.close()

        timer = QTimer()
        timer.setInterval(10)
        timer.timeout.connect(poll)
        timer.start()
        try:
            action()
            self.qapp.processEvents()
            poll()
        finally:
            timer.stop()
        self.assertTrue(seen, "the action opened no window")
        return seen[0]

    def actions(self, win):
        add_btn = next(b for b in win.findChildren(QPushButton)
                       if "Add session" in b.text())
        pattern_btn = next(b for b in win.findChildren(QPushButton)
                           if b.text() == "PATTERN")
        lst = win.session_list
        row_pt = lst.visualItemRect(lst.item(0)).center()

        def templates():
            return pomo_qt.TemplatesDialog(win, win)

        def saved_box():
            templates()._save_to(0)

        def empty_box():
            sessions, win.sessions = win.sessions, []
            try:
                templates()._save_to(1)
            finally:
                win.sessions = sessions

        def rename_template():
            dlg = templates()
            pomo_qt.save_json(pomo_qt.TEMPLATES_FILE, [
                {"name": "T", "sessions": [{"type": "work"}]}])
            dlg._rename(0)

        return {
            "add popup": lambda: win._open_add_popup(add_btn),
            "pattern popup": lambda: win._open_pattern_popup(pattern_btn),
            "settings": win.open_settings,
            "templates": win.open_templates,
            "saved message": saved_box,
            "empty message": empty_box,
            "rename template": rename_template,
            "rename session": lambda: win._rename_index(0),
            "set duration": lambda: win._prompt_duration(0),
            "add focus": win.prompt_add_focus,
            "row menu": lambda: win._session_context_menu(row_pt, lst),
        }

    def check_mode(self, mode):
        win = self.make_window(mode)
        main_translucent = win.testAttribute(TRANSLUCENT)
        self.assertEqual(main_translucent, mode in ("compositor", "wayland"))
        for name, action in self.actions(win).items():
            with self.subTest(mode=mode, window=name):
                is_window, translucent, alpha = self.opened_by(action)
                self.assertTrue(is_window)
                self.assertEqual(translucent, main_translucent)
                if not main_translucent:
                    self.assertEqual(alpha, 255)

    def test_no_compositor_every_window_opaque(self):
        self.check_mode("fake")

    def test_compositor_every_window_translucent(self):
        self.check_mode("wayland")


if __name__ == "__main__":
    unittest.main()
