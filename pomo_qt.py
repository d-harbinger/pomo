#!/usr/bin/env python3
"""Pomo (Qt) — PySide6 port of the pomodoro timer.

First cut focused on showing what the toolkit gets us:
  - Real font rendering, real DPI, real animations.
  - Stylesheet-based theming (no manual color math).
  - Settings dialog instead of cluttered top bar.
  - Animated cross-fade between mode swaps.
  - Reuses the existing JSON files in $POMO_DATA_DIR (or ~/.local/share/pomo)
    so templates/sessions/stats/prefs round-trip with the Tk version.
"""

from __future__ import annotations

import ctypes
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import wave
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor, QFont, QGuiApplication, QIcon, QImage,
    QKeySequence, QPainter, QPainterPath, QPen, QPixmap, QShortcut,
)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox,
    QFormLayout, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox,
    QPushButton, QSizePolicy, QSpinBox, QToolButton,
    QVBoxLayout, QWidget,
)


# ── Paths ────────────────────────────────────────────────────────────────────

DATA_DIR = Path(os.environ.get(
    "POMO_DATA_DIR", Path.home() / ".local" / "share" / "pomo"))
STATS_FILE = DATA_DIR / "stats.json"
HISTORY_FILE = DATA_DIR / "history.json"
PREFS_FILE = DATA_DIR / "prefs.json"
SESSIONS_FILE = DATA_DIR / "sessions.json"
TEMPLATES_FILE = DATA_DIR / "templates.json"
TEMPLATE_SLOTS = 5

DEFAULT_WORK = 45
DEFAULT_SHORT_BREAK = 10
DEFAULT_LONG_BREAK = 20


# ── Persistence ──────────────────────────────────────────────────────────────

def load_json(path: Path, default=None):
    if default is None:
        default = {}
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return default
    return default


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ── Look ─────────────────────────────────────────────────────────────────────

# Frosted glass, the one look. The window background is a translucent dark
# tint (see "Glass frosting" below); every accent is white, so session types
# are told apart by label. Colours with alpha are #AARRGGBB.
THEME = {
    "bg": "#8c12161c", "surface": "#14ffffff", "surface_light": "#1fffffff",
    "work": "#ffffff", "work_dim": "#1fffffff",
    "break": "#ffffff", "break_dim": "#1fffffff",
    "long_break": "#ffffff", "long_break_dim": "#1fffffff",
    "text": "#ffffff", "text_dim": "#80ffffff", "text_muted": "#59ffffff",
    "done_text": "#59ffffff", "dialog_bg": "#171b21", "border": "#17ffffff",
    "minutes": "#73ffffff", "radius": 22,
}


UI_SCALE = 1.0


def set_ui_scale(scale: float):
    """Set the per-machine UI multiplier (clamped to a sane range)."""
    global UI_SCALE
    UI_SCALE = max(0.5, min(3.0, float(scale)))


def fs(points: float) -> str:
    # Sizes are authored as points at a 96-DPI baseline and emitted as logical
    # pixels, so the UI renders at a consistent size regardless of the DPI each
    # desktop reports (the cause of the cross-distro big/small fonts). Qt's
    # high-DPI handling keeps it crisp on HiDPI screens; UI_SCALE is the user knob.
    return f"{max(1, round(points * 4 / 3 * UI_SCALE))}px"


def stylesheet() -> str:
    """Translate THEME into a Qt stylesheet.

    Qt's stylesheet engine is CSS-like — one place sets every widget's look.
    """
    t = THEME
    css = f"""
    QWidget {{
        background-color: {t['bg']};
        color: {t['text']};
        font-family: "Inter", "Cantarell", "Ubuntu", "Noto Sans",
                     "Liberation Sans", "Segoe UI", system-ui, sans-serif;
        font-size: {fs(10)};
    }}
    QFrame#card, QFrame#bar {{
        background-color: {t['surface']};
        border-radius: 3px;
    }}
    QFrame#popupCard {{
        background-color: {t['surface']};
        border: 1px solid {t['surface_light']};
        border-radius: 3px;
    }}
    QPushButton {{
        background: transparent;
        color: {t['text_dim']};
        border: none;
        border-radius: 3px;
        padding: 4px 10px;
        font-size: {fs(10)};
    }}
    QPushButton:hover {{ color: {t['text']}; background-color: {t['surface']}; }}
    /* Primary action: outline + accent color, bigger glyph for icon mode. */
    QPushButton#primary {{
        background: transparent;
        color: {t['work']};
        font-size: {fs(14)};
        padding: 0px;
        border: 1px solid {t['work']};
        border-radius: 3px;
    }}
    QPushButton#primary:hover {{
        background-color: {t['work']}; color: white;
    }}
    QPushButton#breakPrimary {{
        background: transparent; color: {t['break']};
        font-size: {fs(14)}; padding: 0px;
        border: 1px solid {t['break']}; border-radius: 3px;
    }}
    QPushButton#breakPrimary:hover {{
        background-color: {t['break']}; color: white;
    }}
    QPushButton#longPrimary {{
        background: transparent; color: {t['long_break']};
        font-size: {fs(14)}; padding: 0px;
        border: 1px solid {t['long_break']}; border-radius: 3px;
    }}
    QPushButton#longPrimary:hover {{
        background-color: {t['long_break']}; color: white;
    }}
    /* Secondary icon controls (reset, skip): no border, hover-fill only. */
    QPushButton#iconControl {{
        background: transparent;
        color: {t['text_dim']};
        border: none;
        border-radius: 3px;
        font-size: {fs(13)};
        padding: 0px;
    }}
    QPushButton#iconControl:hover {{
        background-color: {t['surface']};
        color: {t['text']};
    }}
    QPushButton#chip {{
        background: transparent;
        color: {t['text_muted']};
        padding: 4px 11px;
        font-size: {fs(9)};
        border: 1px solid {t['surface_light']};
        border-radius: 0px;
    }}
    QPushButton#chip:hover {{
        color: {t['text']};
        border-color: {t['work']};
        background-color: {t['surface']};
    }}
    QPushButton#rowChip {{
        background: transparent;
        color: {t['text_muted']};
        padding: 0px;
        font-size: {fs(11)};
        border-radius: 3px;
    }}
    QPushButton#rowChip:hover {{
        background-color: {t['surface_light']};
        color: {t['text']};
    }}
    QListWidget::item {{
        background-color: {t['surface']};
        border-radius: 3px;
        margin: 1px 0px;
        padding: 0px;
    }}
    QListWidget::item:selected {{
        background-color: {t['surface_light']};
    }}
    QWidget#sessionRowCurrent {{
        background-color: {t['surface_light']};
        border-radius: 3px;
    }}
    QWidget#sessionRow {{
        background: transparent;
    }}
    QPushButton#icon {{
        background: transparent; padding: 4px; font-size: {fs(12)};
        color: {t['text_dim']};
        border-radius: 3px;
    }}
    QPushButton#icon:hover {{
        background-color: {t['surface']};
        color: {t['text']};
    }}
    QLabel#title {{
        font-size: {fs(13)}; font-weight: 600; color: {t['text']};
        letter-spacing: 0.5px;
    }}
    QPushButton#addRow {{
        background: transparent;
        color: {t['text_muted']};
        border: 1px dashed {t['surface_light']};
        border-radius: 3px;
        padding: 6px 8px;
        font-size: {fs(10)};
        text-align: left;
    }}
    QPushButton#addRow:hover {{
        color: {t['text']};
        border-color: {t['text_muted']};
        background-color: {t['surface']};
    }}
    QLabel#muted {{ color: {t['text_muted']}; font-size: {fs(9)}; }}
    QLabel#dim {{ color: {t['text_dim']}; font-size: {fs(10)}; }}
    QListWidget {{
        background: transparent; border: none; outline: none;
        font-size: {fs(10)};
    }}
    QLineEdit, QSpinBox, QComboBox {{
        background-color: {t['surface']};
        border: 1px solid {t['surface_light']};
        border-radius: 3px;
        padding: 3px 6px;
        color: {t['text']};
        selection-background-color: {t['work']};
    }}
    QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
        border-color: {t['work']};
    }}
    QCheckBox {{ color: {t['text_dim']}; spacing: 8px; }}
    QCheckBox::indicator {{
        width: 16px; height: 16px;
        border-radius: 4px;
        border: 1px solid {t['surface_light']};
        background: {t['surface']};
    }}
    QCheckBox::indicator:checked {{
        background: {t['work']}; border-color: {t['work']};
    }}
    QDialog {{ background-color: {t['bg']}; }}
    QMenu {{
        background-color: {t['surface']};
        color: {t['text']};
        border: 1px solid {t['surface_light']};
        padding: 4px;
    }}
    QMenu::item {{ padding: 6px 18px; border-radius: 4px; }}
    QMenu::item:selected {{ background-color: {t['surface_light']}; }}
    """
    d = t["dialog_bg"]
    css += f"""
    /* Glass: the main window paints its own frosted tint, so widgets are
       see-through; dialogs and popups stay solid. */
    QWidget {{ background-color: transparent; }}
    QDialog, QMenu, QToolTip, QComboBox QAbstractItemView {{
        background-color: {d}; color: {t['text']};
    }}
    QPushButton:hover {{ background-color: transparent; color: {t['text']}; }}
    QPushButton#chip {{
        color: {t['text_dim']}; border: none; border-radius: 0px;
        padding: 4px 6px; font-size: {fs(8)}; font-weight: 600;
    }}
    QPushButton#chip:hover {{
        color: {t['text']}; border: none; background-color: transparent;
    }}
    QPushButton#primary, QPushButton#breakPrimary, QPushButton#longPrimary {{
        background-color: {t['surface_light']}; color: {t['text']};
        border: none; border-radius: 22px;
    }}
    QPushButton#primary:hover, QPushButton#breakPrimary:hover,
    QPushButton#longPrimary:hover {{
        background-color: #33ffffff; color: {t['text']};
    }}
    QPushButton#iconControl {{ color: {t['text_dim']}; }}
    QPushButton#iconControl:hover {{
        background-color: transparent; color: {t['text']};
    }}
    QPushButton#icon:hover {{ background-color: transparent; }}
    QToolButton#icon {{ border: none; color: {t['text_dim']}; }}
    QToolButton#icon:hover {{ color: {t['text']}; }}
    QPushButton#rowChip:hover {{
        background-color: transparent; color: {t['text']};
    }}
    QListWidget::item, QListWidget::item:selected {{
        background-color: transparent; margin: 0px;
    }}
    QWidget#sessionRowCurrent, QWidget#sessionRow {{
        background-color: transparent;
    }}
    QLabel#title {{
        font-size: {fs(8)}; font-weight: 600; color: {t['text_dim']};
    }}
    QLabel#muted {{
        font-size: {fs(8)}; font-weight: 600; color: {t['text_dim']};
    }}
    QPushButton#addRow {{
        color: {t['text_muted']}; border: none; padding: 9px 0px;
        font-size: {fs(11)}; font-weight: 300;
    }}
    QPushButton#addRow:hover {{
        color: {t['text_dim']}; border: none; background-color: transparent;
    }}
    QFrame#card, QFrame#bar {{ background-color: {t['surface']}; }}
    QFrame#popupCard {{ background-color: {t['surface']}; }}
    QLineEdit, QSpinBox, QComboBox {{ background-color: {t['surface']}; }}
    QCheckBox::indicator {{ background-color: {t['surface']}; }}
    QCheckBox::indicator:checked {{ background-color: {t['work_dim']}; }}
    """
    return css


# ── Glass frosting ───────────────────────────────────────────────────────────
#
# Three ways to get a frosted window, picked once per window (see
# PomoWindow._apply_frost):
#   "compositor"  X11 with a compositor: translucent window, the compositor
#                 blurs what is behind it.
#   "wayland"     Wayland: translucent window, the compositor decides on blur.
#   "fake"        anything else (X11 without a compositor, offscreen): draw
#                 the feh wallpaper, blurred, under the tint.

_FEHBG_RE = re.compile(
    r"--bg-(?:fill|scale|center|max)\s+(?:'([^']*)'|\"([^\"]*)\"|(\S+))")
_BLUR_SCALE = 12
_FALLBACK_BG = "#11151b"
_wallpaper_cache: dict = {}


def compositor_running() -> bool:
    """True when a compositor owns the _NET_WM_CM_S0 selection (X11 only).

    Any failure — no libX11, no display — counts as "no compositor".
    """
    try:
        x11 = ctypes.CDLL("libX11.so.6")
        x11.XOpenDisplay.restype = ctypes.c_void_p
        x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x11.XInternAtom.restype = ctypes.c_ulong
        x11.XInternAtom.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        x11.XGetSelectionOwner.restype = ctypes.c_ulong
        x11.XGetSelectionOwner.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        dpy = x11.XOpenDisplay(None)
        if not dpy:
            return False
        try:
            atom = x11.XInternAtom(dpy, b"_NET_WM_CM_S0", False)
            return bool(x11.XGetSelectionOwner(dpy, atom) != 0)
        finally:
            x11.XCloseDisplay(dpy)
    except Exception:
        return False


def frost_mode() -> str:
    """Pick "compositor", "wayland" or "fake" for the current platform."""
    platform = QGuiApplication.platformName()
    if platform == "xcb" and compositor_running():
        return "compositor"
    if platform.startswith("wayland"):
        return "wayland"
    return "fake"


def parse_fehbg(text: str):
    """Wallpaper path from the contents of a ~/.fehbg script, or None."""
    m = _FEHBG_RE.search(text)
    if not m:
        return None
    path = next((g for g in m.groups() if g), None)
    return os.path.expanduser(path) if path else None


def _blurred_wallpaper(size: QSize):
    """Blurred, aspect-filled wallpaper for a screen of `size`, or None.

    Cached per screen size; None (cached too) means paint the solid fallback.
    """
    key = (size.width(), size.height())
    if key in _wallpaper_cache:
        return _wallpaper_cache[key]
    pix = None
    try:
        text = (Path.home() / ".fehbg").read_text()
    except OSError:
        text = ""
    path = parse_fehbg(text)
    img = QImage(path) if path else QImage()
    if not img.isNull() and size.width() > 0 and size.height() > 0:
        # Aspect-fill, centred crop — what `feh --bg-fill` does.
        img = img.scaled(size, Qt.KeepAspectRatioByExpanding,
                         Qt.SmoothTransformation)
        img = img.copy((img.width() - size.width()) // 2,
                       (img.height() - size.height()) // 2,
                       size.width(), size.height())
        small = QSize(max(1, size.width() // _BLUR_SCALE),
                      max(1, size.height() // _BLUR_SCALE))
        for _ in range(2):
            img = img.scaled(small, Qt.IgnoreAspectRatio,
                             Qt.SmoothTransformation)
            img = img.scaled(size, Qt.IgnoreAspectRatio,
                             Qt.SmoothTransformation)
        pix = QPixmap.fromImage(img)
    _wallpaper_cache[key] = pix
    return pix


class Central(QWidget):
    """Central widget. Paints the glass tint."""

    def __init__(self, win: "PomoWindow"):
        super().__init__()
        self._win = win
        self.setAttribute(Qt.WA_StyledBackground, True)

    def paintEvent(self, event):
        self._win.paint_glass(self)


# ── Sounds ───────────────────────────────────────────────────────────────────

_SOUND_PLAYER = next((p for p in ("paplay", "aplay", "afplay", "play")
                      if shutil.which(p)), None)


def _gen_tone(path: Path, frequencies, duration_ms=400, volume=0.4):
    framerate = 44100
    n = int(framerate * duration_ms / 1000)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(framerate)
        frames = []
        for i in range(n):
            fade = 1.0 if i < n * 0.1 else max(0.0, (n - i) / (n * 0.9))
            sample = sum(math.sin(2 * math.pi * f * i / framerate)
                         for f in frequencies)
            sample /= max(1, len(frequencies))
            val = int(volume * fade * 32767 * sample)
            frames.append(struct.pack("<h", val))
        w.writeframes(b"".join(frames))


class Sounds:
    def __init__(self):
        d = Path(tempfile.gettempdir()) / "pomo-sounds"
        self.files = {
            "work": d / "work_done.wav",
            "break": d / "break_done.wav",
        }
        if not self.files["work"].exists():
            _gen_tone(self.files["work"],
                      [523.25, 659.25, 783.99], duration_ms=500)
        if not self.files["break"].exists():
            _gen_tone(self.files["break"],
                      [880.0], duration_ms=350, volume=0.35)

    def play(self, which: str, enabled: bool = True):
        if not enabled:
            return
        path = self.files.get(which)
        if not (_SOUND_PLAYER and path and path.exists()):
            return
        try:
            subprocess.Popen(
                [_SOUND_PLAYER, str(path)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass  # chime is best-effort; a missing player must not break the timer


# ── Notifications ────────────────────────────────────────────────────────────

def notify(title: str, message: str, enabled: bool = True):
    if not enabled:
        return
    if shutil.which("notify-send"):
        try:
            subprocess.Popen(
                ["notify-send", "-a", "Pomo", "-t", "6000", title, message],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass  # notification is best-effort


# ── Stats ────────────────────────────────────────────────────────

class Stats:
    def __init__(self):
        self.data = load_json(
            STATS_FILE,
            {"days": {}, "total_sessions": 0, "total_minutes": 0})

    @property
    def today(self):
        key = date.today().isoformat()
        return self.data["days"].setdefault(
            key, {"sessions": 0, "minutes": 0})

    def record_session(self, minutes, task_name):
        t = self.today
        t["sessions"] += 1
        t["minutes"] += minutes
        self.data["total_sessions"] += 1
        self.data["total_minutes"] += minutes
        save_json(STATS_FILE, self.data)
        history = load_json(HISTORY_FILE, [])
        history.append({
            "date": date.today().isoformat(),
            "task": task_name,
            "minutes": minutes,
        })
        save_json(HISTORY_FILE, history)


# ── Domain types ─────────────────────────────────────────────────────────────

class SessionType(Enum):
    WORK = "work"
    SHORT_BREAK = "short_break"
    LONG_BREAK = "long_break"


class TimerState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"


@dataclass
class Session:
    type: str  # "work" | "short_break" | "long_break"
    name: str
    duration: int  # minutes
    done: bool = False


# ── Ring widget ──────────────────────────────────────────────────────────────

class RingTimer(QWidget):
    """Circular progress ring with time + task label centered.

    QPainter handles antialiasing automatically — none of the manual
    rounding the Tk Canvas needed."""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        # Tiny floor so the ring can shrink with the window instead of
        # overflowing its parent at small sizes.
        self.setMinimumSize(60, 60)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._progress = 0.0  # 0..1, 0 = full, 1 = empty
        self._time_text = "00:00"
        self._label = "Focus"
        self._color = QColor("#e94560")
        self._dim = QColor("#8b2a3a")
        self._text_color = QColor("#eaeaea")
        self._text_dim = QColor("#8892a0")

    def set_state(self, progress, time_text, label, color, dim,
                  text, text_dim):
        self._progress = max(0.0, min(1.0, progress))
        self._time_text = time_text
        self._label = label
        self._color = QColor(color)
        self._dim = QColor(dim)
        self._text_color = QColor(text)
        self._text_dim = QColor(text_dim)
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def paintEvent(self, _event):
        """Thin ring, small-caps label above light tabular digits."""
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        size = min(self.width(), self.height())
        # Thin at every size: a full-screen window would otherwise draw it
        # as a heavy band.
        ring_w = max(2, min(5, size // 48))
        cx, cy = self.width() / 2, self.height() / 2
        r = max(8, (size / 2) - ring_w - 4)
        rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)

        p.setPen(QPen(self._dim, ring_w, Qt.SolidLine, Qt.FlatCap))
        p.drawEllipse(rect)
        if self._progress > 0.001:
            p.setPen(QPen(self._color, ring_w, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(rect, 90 * 16, -int(360 * self._progress * 16))

        time_size = max(8, int(size * 0.24))
        f = QFont(self.font())
        f.setPixelSize(time_size)
        f.setWeight(QFont.Light)
        f.setLetterSpacing(QFont.PercentageSpacing, 98)
        try:  # tabular figures, Qt >= 6.7; harmless where the font lacks them
            f.setFeature(QFont.Tag("tnum"), 1)
        except (AttributeError, TypeError, ValueError):
            pass
        p.setFont(f)
        p.setPen(self._text_color)
        p.drawText(QRect(0, int(cy - time_size * 0.5), self.width(),
                         int(time_size * 1.2)),
                   Qt.AlignHCenter | Qt.AlignVCenter, self._time_text)

        if size >= 130:
            label_size = max(7, int(size * 0.058))
            lf = QFont(self.font())
            lf.setPixelSize(label_size)
            lf.setWeight(QFont.DemiBold)
            lf.setCapitalization(QFont.AllUppercase)
            lf.setLetterSpacing(QFont.AbsoluteSpacing,
                                max(1.0, label_size * 0.18))
            p.setFont(lf)
            p.setPen(self._text_dim)
            p.drawText(QRect(0, int(cy - time_size * 0.5 - label_size * 2.2),
                             self.width(), int(label_size * 2)),
                       Qt.AlignHCenter | Qt.AlignBottom, self._label)

# ── Session row widget ──────────────────────────────────────────────────────

class SessionRow(QWidget):
    """Row for a single session.

    Drag handle · colored type stripe (thicker for the active row) ·
    name · duration with ± · delete. The current row gets a subtly
    tinted background so the running session is unmistakable.
    """

    def __init__(self, app, index: int, session: "Session", is_current: bool,
                 parent=None):
        super().__init__(parent)
        self.app = app
        self.index = index
        self.session = session
        self.setObjectName("sessionRowCurrent" if is_current else "sessionRow")

        self._build(THEME, is_current)

    def _build(self, t: dict, is_current: bool):
        """Row: dot, light name, minutes at the right. The ±/× chips
        keep their actions but only show while the pointer is on the row."""
        session = self.session
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 5, 0, 5)
        h.setSpacing(10)

        # A 16px halo cell holding an 8px dot: the current row's dot is
        # white inside a faint ring, the others a dim dot.
        halo = QFrame()
        halo.setFixedSize(16, 16)
        halo.setStyleSheet(
            f"background: {t['surface_light'] if is_current else 'transparent'};"
            "border: none; border-radius: 8px;")
        hl = QHBoxLayout(halo)
        hl.setContentsMargins(4, 4, 4, 4)
        dot = QFrame()
        dot.setStyleSheet(
            f"background: {t['text'] if is_current else t['text_muted']};"
            "border: none; border-radius: 4px;")
        hl.addWidget(dot)
        h.addWidget(halo)

        self.name_lbl = QLabel(session.name)
        self.name_lbl.setStyleSheet(
            f"color: {t['done_text'] if session.done else t['text']}; "
            f"font-size: {fs(11)}; font-weight: 300; background: transparent;")
        self.name_lbl.setCursor(Qt.IBeamCursor)
        self.name_lbl.mouseDoubleClickEvent = (
            lambda _e: self.app._rename_index(self.index))
        h.addWidget(self.name_lbl, 1)

        self._chips = []
        for glyph, tip, action in (
                ("−", None, lambda: self.app._adjust_duration(self.index, -1)),
                ("+", None, lambda: self.app._adjust_duration(self.index, +1))):
            chip = QPushButton(glyph)
            chip.setObjectName("rowChip")
            chip.setFixedSize(18, 18)
            chip.setFlat(True)
            chip.clicked.connect(action)
            self._chips.append(chip)

        self.dur_lbl = QLabel(f"{session.duration}m")
        self.dur_lbl.setStyleSheet(
            f"color: {t['minutes']}; font-size: {fs(10)}; "
            "background: transparent;")
        self.dur_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.dur_lbl.setCursor(Qt.PointingHandCursor)
        self.dur_lbl.mouseDoubleClickEvent = (
            lambda _e: self.app._prompt_duration(self.index))

        delete = QPushButton("×")
        delete.setObjectName("rowChip")
        delete.setFixedSize(18, 18)
        delete.setFlat(True)
        delete.setToolTip("Remove")
        delete.clicked.connect(lambda: self.app._remove(self.index))
        self._chips.append(delete)

        h.addWidget(self._chips[0])
        h.addWidget(self.dur_lbl)
        h.addWidget(self._chips[1])
        h.addWidget(delete)
        self._show_chips(False)

    def _show_chips(self, shown: bool):
        for chip in getattr(self, "_chips", ()):
            chip.setVisible(shown)

    def enterEvent(self, event):
        self._show_chips(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._show_chips(False)
        super().leaveEvent(event)


# ── Add session popup ───────────────────────────────────────────────────────

class AddSessionPopup(QDialog):
    """Tiny inline popup for adding a custom session.

    Pick a type (F/S/L), optionally type a name, hit Add. Default type is
    Focus; default names match the session type if left blank. Closes on
    add or click-away.
    """

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setWindowFlags(
            Qt.Popup | Qt.FramelessWindowHint
            | Qt.NoDropShadowWindowHint)
        self._type = "work"  # default

        wrap = QFrame(self)
        wrap.setObjectName("popupCard")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(wrap)

        col = QVBoxLayout(wrap)
        col.setContentsMargins(10, 8, 10, 8)
        col.setSpacing(6)

        # Type picker — three small toggle buttons.
        type_row = QHBoxLayout()
        type_row.setSpacing(4)
        t = THEME
        self._type_buttons = {}
        for key, label, color in (
            ("work", "Focus", t["work"]),
            ("short_break", "Short", t["break"]),
            ("long_break", "Long", t["long_break"]),
        ):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setObjectName("typePick")
            b.setProperty("accent", color)
            b.setStyleSheet(self._type_button_style(color, False))
            b.clicked.connect(lambda _=False, k=key: self._select_type(k))
            type_row.addWidget(b)
            self._type_buttons[key] = b
        self._select_type("work")
        col.addLayout(type_row)

        # Name field with Add inline.
        name_row = QHBoxLayout()
        name_row.setSpacing(6)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Name (optional)")
        self.name_edit.setMinimumWidth(180)
        self.name_edit.returnPressed.connect(self._submit)
        name_row.addWidget(self.name_edit, 1)

        add = QPushButton("Add")
        add.setObjectName("primary")
        add.clicked.connect(self._submit)
        name_row.addWidget(add)
        col.addLayout(name_row)

    def _type_button_style(self, color: str, selected: bool) -> str:
        if selected:
            return (
                f"background-color: {color}; color: white; "
                "border-radius: 3px; padding: 4px 10px; "
                f"font-weight: 600; font-size: {fs(9)};")
        return (
            f"background: transparent; color: {color}; "
            f"border: 1px solid {color}; border-radius: 3px; "
            f"padding: 4px 10px; font-weight: 500; font-size: {fs(9)};")

    def _select_type(self, key: str):
        self._type = key
        for k, b in self._type_buttons.items():
            color = b.property("accent")
            b.setStyleSheet(self._type_button_style(color, k == key))
            b.setChecked(k == key)

    def _submit(self):
        name = self.name_edit.text().strip()
        if self._type == "work":
            self.app.add_focus(name or "Focus")
        else:
            self.app.add_break(self._type, name=name)
        self.close()

    def show_at(self, anchor: QWidget):
        """Position the popup just above the anchor button."""
        self.adjustSize()
        gp = anchor.mapToGlobal(anchor.rect().topLeft())
        self.move(gp.x(), gp.y() - self.height() - 4)
        self.show()
        self.name_edit.setFocus()


# ── Pattern popup ────────────────────────────────────────────────────────────

class PatternPopup(QDialog):
    """Tiny inline popup for the Pattern button.

    Shows F/S/L spinboxes plus a Push button so you can tweak counts and
    push in one place — no Settings round-trip. Closes on push or click-away.
    """

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setWindowFlags(
            Qt.Popup | Qt.FramelessWindowHint
            | Qt.NoDropShadowWindowHint)
        self.setObjectName("popup")

        wrap = QFrame(self)
        wrap.setObjectName("popupCard")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(wrap)

        h = QHBoxLayout(wrap)
        h.setContentsMargins(10, 8, 10, 8)
        h.setSpacing(6)

        # Three spinboxes labeled F/S/L. The labels echo the accent colors
        # for instant scanability (focus / short / long).
        t = THEME
        for label_text, key, color in (
            ("F", "focus", t["work"]),
            ("S", "short", t["break"]),
            ("L", "long", t["long_break"]),
        ):
            lbl = QLabel(label_text)
            lbl.setStyleSheet(
                f"color: {color}; font-weight: 700; font-size: {fs(10)};")
            h.addWidget(lbl)
            spin = QSpinBox()
            spin.setRange(0, 99)
            spin.setValue(app.pattern_counts[key])
            spin.setFixedWidth(54)
            setattr(self, f"_{key}_spin", spin)
            h.addWidget(spin)
            h.addSpacing(4)

        push = QPushButton("Push")
        push.setObjectName("primary")
        push.clicked.connect(self._push)
        h.addWidget(push)

    def _push(self):
        f = self._focus_spin.value()
        s = self._short_spin.value()
        l = self._long_spin.value()
        if f + s + l == 0:
            self.close()
            return
        self.app.pattern_counts = {"focus": f, "short": s, "long": l}
        self.app._persist_prefs()
        self.app.push_pattern(f, s, l)
        self.close()

    def show_at(self, anchor: QWidget):
        """Position the popup just below the given widget."""
        self.adjustSize()
        gp = anchor.mapToGlobal(anchor.rect().bottomLeft())
        # Nudge down 4px so the popup doesn't touch the button.
        self.move(gp.x(), gp.y() + 4)
        self.show()


# ── Settings dialog ──────────────────────────────────────────────────────────

class SettingsDialog(QDialog):
    """One stop for durations / sounds / notifications."""

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Pomo Settings")
        self.setMinimumWidth(360)
        self.app = app

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignRight)

        self.work_spin = QSpinBox(); self.work_spin.setRange(1, 600)
        self.work_spin.setValue(app.durations["work"])
        self.work_spin.setSuffix(" min")
        form.addRow("Focus", self.work_spin)

        self.short_spin = QSpinBox(); self.short_spin.setRange(1, 600)
        self.short_spin.setValue(app.durations["short_break"])
        self.short_spin.setSuffix(" min")
        form.addRow("Short break", self.short_spin)

        self.long_spin = QSpinBox(); self.long_spin.setRange(1, 600)
        self.long_spin.setValue(app.durations["long_break"])
        self.long_spin.setSuffix(" min")
        form.addRow("Long break", self.long_spin)

        self.f_spin = QSpinBox(); self.f_spin.setRange(0, 99)
        self.f_spin.setValue(app.pattern_counts["focus"])
        form.addRow("Pattern · Focus count", self.f_spin)

        self.s_spin = QSpinBox(); self.s_spin.setRange(0, 99)
        self.s_spin.setValue(app.pattern_counts["short"])
        form.addRow("Pattern · Short count", self.s_spin)

        self.l_spin = QSpinBox(); self.l_spin.setRange(0, 99)
        self.l_spin.setValue(app.pattern_counts["long"])
        form.addRow("Pattern · Long count", self.l_spin)

        self.scale_spin = QSpinBox(); self.scale_spin.setRange(50, 300)
        self.scale_spin.setSingleStep(5)
        self.scale_spin.setValue(round(app.ui_scale * 100))
        self.scale_spin.setSuffix(" %")
        form.addRow("UI scale", self.scale_spin)

        layout.addLayout(form)

        self.breaks_box = QCheckBox("Auto-start breaks after focus")
        self.breaks_box.setChecked(app.auto_start_breaks)
        layout.addWidget(self.breaks_box)

        self.chain_box = QCheckBox("Auto-start next focus after a break")
        self.chain_box.setChecked(app.chain_auto_start)
        layout.addWidget(self.chain_box)

        self.sounds_box = QCheckBox("Play chimes")
        self.sounds_box.setChecked(app.sounds_enabled)
        layout.addWidget(self.sounds_box)

        self.notif_box = QCheckBox("Desktop notifications")
        self.notif_box.setChecked(app.notifications_enabled)
        layout.addWidget(self.notif_box)

        bb = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)


# ── Main window ──────────────────────────────────────────────────────────────

class PomoWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pomo")

        self.stats = Stats()
        self.sounds = Sounds()

        prefs = load_json(PREFS_FILE, {})
        self.durations = {
            "work": int(prefs.get("dur_work", DEFAULT_WORK)),
            "short_break": int(prefs.get("dur_short_break", DEFAULT_SHORT_BREAK)),
            "long_break": int(prefs.get("dur_long_break", DEFAULT_LONG_BREAK)),
        }
        self.pattern_counts = {
            "focus": int(prefs.get("pattern_focus", 4)),
            "short": int(prefs.get("pattern_short", 3)),
            "long": int(prefs.get("pattern_long", 1)),
        }
        self.chain_auto_start = bool(prefs.get("chain_auto_start", False))
        self.auto_start_breaks = bool(prefs.get("auto_start_breaks", True))
        self.sounds_enabled = bool(prefs.get("sounds_enabled", True))
        self.notifications_enabled = bool(prefs.get("notifications_enabled", True))
        self.ui_scale = float(prefs.get("ui_scale", 1.0))
        set_ui_scale(self.ui_scale)

        self.timer_state = TimerState.IDLE
        self.session_type = SessionType.WORK
        self.sessions: list[Session] = self._load_sessions()
        self.current_index = self._first_pending_index()
        self.remaining_seconds = self._current_session_seconds()
        self.total_seconds = self.remaining_seconds

        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._on_tick)

        self._build_ui()
        self._apply_frost()
        QApplication.instance().setStyleSheet(stylesheet())
        self._arrange_chrome()
        # Floor the window so the header row can't shrink until its labels
        # clip; scales with the UI multiplier.
        self.setMinimumSize(QSize(round(560 * UI_SCALE), round(300 * UI_SCALE)))
        self.resize(QSize(640, 360))
        self._refresh_all()
        self._bind_shortcuts()

    def _bind_shortcuts(self):
        """Global keyboard shortcuts.

        Skipped while a popup/dialog is open — Qt's focus tree handles
        that naturally; shortcuts only fire when the main window has
        keyboard focus.
        """
        QShortcut(QKeySequence(Qt.Key_Space), self,
                  activated=self.toggle_timer)
        QShortcut(QKeySequence("R"), self, activated=self.reset_timer)
        QShortcut(QKeySequence("S"), self, activated=self.skip_session)
        QShortcut(QKeySequence("Ctrl+,"), self, activated=self.open_settings)

    # ── Persistence helpers ──────────────────────────────────────────────

    def _load_sessions(self):
        data = load_json(SESSIONS_FILE, None)
        if not isinstance(data, list):
            return []
        out = []
        for item in data:
            if not isinstance(item, dict):
                continue
            t = item.get("type")
            if t not in ("work", "short_break", "long_break"):
                continue
            name = item.get("name") or (
                "Short Break" if t == "short_break"
                else "Long Break" if t == "long_break"
                else "Focus")
            out.append(Session(
                type=t, name=name, done=False,
                duration=int(item.get("duration", self.durations[t]))))
        return out

    def _save_sessions(self):
        data = [
            {"type": s.type, "name": s.name, "duration": s.duration}
            for s in self.sessions
        ]
        save_json(SESSIONS_FILE, data)

    def _persist_prefs(self):
        prefs = load_json(PREFS_FILE, {})
        prefs.update({
            "chain_auto_start": self.chain_auto_start,
            "auto_start_breaks": self.auto_start_breaks,
            "ui_scale": self.ui_scale,
            "sounds_enabled": self.sounds_enabled,
            "notifications_enabled": self.notifications_enabled,
            "dur_work": self.durations["work"],
            "dur_short_break": self.durations["short_break"],
            "dur_long_break": self.durations["long_break"],
            "pattern_focus": self.pattern_counts["focus"],
            "pattern_short": self.pattern_counts["short"],
            "pattern_long": self.pattern_counts["long"],
        })
        save_json(PREFS_FILE, prefs)

    # ── UI build ─────────────────────────────────────────────────────────

    def _build_ui(self):
        central = Central(self)
        self.setCentralWidget(central)
        root = self._root = QVBoxLayout(central)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)

        # Top bar — title, the header chips, settings.
        top = QHBoxLayout()
        top.setSpacing(4)
        title = QLabel("pomo")
        title.setObjectName("title")
        top.addWidget(title)
        top.addStretch()
        self._top_chips = QHBoxLayout()
        top.addLayout(self._top_chips)

        self.settings_btn = QToolButton()
        self.settings_btn.setText("⚙")
        self.settings_btn.setObjectName("icon")
        self.settings_btn.setToolTip("Settings")
        self.settings_btn.clicked.connect(self.open_settings)
        top.addWidget(self.settings_btn)
        root.addLayout(top)

        # Body: ring + controls on the left, sessions on the right.
        body = QHBoxLayout()
        body.setSpacing(12)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(8)
        self.ring = RingTimer()
        self.ring.clicked.connect(self.toggle_timer)
        lv.addWidget(self.ring, 1)
        lv.addLayout(self._build_controls_row())
        body.addWidget(left, 3)

        self.session_panel, self.session_list = self._build_session_panel()
        body.addWidget(self.session_panel, 4)
        root.addLayout(body, 1)

        # Today's stats (small footer)
        self.today_label = QLabel("")
        self.today_label.setObjectName("muted")
        self.today_label.setAlignment(Qt.AlignCenter)
        root.addWidget(self.today_label)

    def _build_session_panel(self):
        """Session list + add row. Returns (wrap, list); the header chips
        are built here and placed in the top bar by _arrange_chrome."""
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        restart = QPushButton("RESTART"); restart.setObjectName("chip")
        restart.clicked.connect(self.restart_stack)
        clear = QPushButton("CLEAR"); clear.setObjectName("chip")
        clear.clicked.connect(self.clear_stack)
        templates = QPushButton("TEMPLATES"); templates.setObjectName("chip")
        templates.clicked.connect(self.open_templates)
        push_pat = QPushButton("PATTERN"); push_pat.setObjectName("chip")
        push_pat.setToolTip("Edit F/S/L counts and push")
        push_pat.clicked.connect(
            lambda: self._open_pattern_popup(push_pat))

        self._chips = (restart, clear, templates, push_pat)

        lst = QListWidget()
        lst.setSelectionMode(QListWidget.SingleSelection)
        lst.setDragDropMode(QListWidget.InternalMove)
        lst.setDefaultDropAction(Qt.MoveAction)
        lst.setMovement(QListWidget.Snap)
        lst.setSpacing(2)
        lst.setContextMenuPolicy(Qt.CustomContextMenu)
        lst.customContextMenuRequested.connect(
            lambda pt, l=lst: self._session_context_menu(pt, l))
        lst.currentRowChanged.connect(self._on_row_selected)
        # rowsMoved fires after a successful internal drop; sync the
        # underlying session list to the new visual order.
        lst.model().rowsMoved.connect(self._on_rows_moved)
        v.addWidget(lst, 1)

        # Add affordance — single, low-weight, lives under the list.
        add_btn = QPushButton("+  Add session")
        add_btn.setObjectName("addRow")
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.clicked.connect(lambda: self._open_add_popup(add_btn))
        v.addWidget(add_btn)

        return wrap, lst

    def _build_controls_row(self):
        row = self._ctl_row = QHBoxLayout()
        row.setSpacing(6)

        # Icon-only controls. Glyphs come from the Unicode media-control
        # block so we don't need bundled SVGs.
        self.start_btn = QPushButton("▶")
        self.start_btn.setObjectName("primary")
        self.start_btn.setToolTip("Start (Space)")
        # Fixed size keeps the button stable when the glyph swaps
        # between ▶ and ⏸ — otherwise the layout reflows and the WM
        # bumps the window.
        self.start_btn.setFixedSize(56, 32)
        self.start_btn.clicked.connect(self.toggle_timer)
        self._start_btn_obj = "primary"
        row.addWidget(self.start_btn)

        reset = QPushButton("↺")
        reset.setObjectName("iconControl")
        reset.setToolTip("Reset (R)")
        reset.setFixedSize(34, 32)
        reset.clicked.connect(self.reset_timer)
        self._reset_btn = reset
        row.addWidget(reset)

        skip = QPushButton("⏭")
        skip.setObjectName("iconControl")
        skip.setToolTip("Skip (S)")
        skip.setFixedSize(34, 32)
        skip.clicked.connect(self.skip_session)
        self._skip_btn = skip
        row.addWidget(skip)

        row.addStretch()
        return row

    # ── Look ─────────────────────────────────────────────────────────────

    def _apply_frost(self):
        """Decide translucency, once, before the window is first shown.

        WA_TranslucentBackground only takes effect when set before the
        window is first shown, so it is applied at start.
        """
        translucent = frost_mode() in ("compositor", "wayland")
        self.setAttribute(Qt.WA_TranslucentBackground, translucent)

    def paint_glass(self, widget: QWidget):
        """Paint the frosted tint on the central widget."""
        t = THEME
        translucent = self.testAttribute(Qt.WA_TranslucentBackground)
        radius = t["radius"] if translucent else 0
        rect = QRectF(widget.rect())
        p = QPainter(widget)
        p.setRenderHint(QPainter.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(rect, radius, radius)
        p.setClipPath(clip)
        if not translucent:
            # Nothing to see through: fake it with the blurred wallpaper.
            screen = self.screen()
            pix = _blurred_wallpaper(screen.size()) if screen else None
            if pix is not None:
                origin = (widget.mapToGlobal(QPoint(0, 0))
                          - screen.geometry().topLeft())
                p.drawPixmap(QPoint(0, 0), pix,
                             QRect(origin, widget.size()))
            else:
                p.fillRect(rect, QColor(_FALLBACK_BG))
        p.fillRect(rect, QColor(t["bg"]))
        p.setClipping(False)
        p.setPen(QPen(QColor(t["border"]), 1))
        p.setBrush(Qt.NoBrush)
        edge = QPainterPath()
        edge.addRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5),
                            max(0, radius - 0.5), max(0, radius - 0.5))
        p.drawPath(edge)
        p.end()

    def moveEvent(self, event):
        super().moveEvent(event)
        central = self.centralWidget()
        if (central is not None
                and not self.testAttribute(Qt.WA_TranslucentBackground)):
            central.update()

    def _arrange_chrome(self):
        """Pack the chips into the top bar and center the controls."""
        for lay in (self._top_chips, self._ctl_row):
            while lay.count():
                lay.takeAt(0)

        for btn in self._chips:
            self._top_chips.addWidget(btn)
        self._top_chips.setSpacing(10)
        self._top_chips.setContentsMargins(0, 0, 12, 0)
        self._ctl_row.setSpacing(22)
        self._ctl_row.addStretch()
        for w in (self._reset_btn, self.start_btn, self._skip_btn):
            self._ctl_row.addWidget(w)
        self._ctl_row.addStretch()
        self.start_btn.setFixedSize(44, 44)
        self._root.setContentsMargins(22, 18, 22, 16)
        self._root.setSpacing(8)

        for w in (*self._chips, self.today_label,
                  self.findChild(QLabel, "title")):
            f = w.font()
            f.setCapitalization(QFont.AllUppercase)
            f.setLetterSpacing(QFont.AbsoluteSpacing, 2.0 * UI_SCALE)
            w.setFont(f)

    # ── Settings dialog ──────────────────────────────────────────────────

    def open_settings(self):
        dlg = SettingsDialog(self, self)
        if dlg.exec() == QDialog.Accepted:
            self.durations["work"] = dlg.work_spin.value()
            self.durations["short_break"] = dlg.short_spin.value()
            self.durations["long_break"] = dlg.long_spin.value()
            self.pattern_counts["focus"] = dlg.f_spin.value()
            self.pattern_counts["short"] = dlg.s_spin.value()
            self.pattern_counts["long"] = dlg.l_spin.value()
            self.auto_start_breaks = dlg.breaks_box.isChecked()
            self.chain_auto_start = dlg.chain_box.isChecked()
            self.sounds_enabled = dlg.sounds_box.isChecked()
            self.notifications_enabled = dlg.notif_box.isChecked()
            self.ui_scale = dlg.scale_spin.value() / 100.0
            set_ui_scale(self.ui_scale)
            self._persist_prefs()
            QApplication.instance().setStyleSheet(stylesheet())
            if self.timer_state == TimerState.IDLE:
                self.remaining_seconds = self._current_session_seconds()
                self.total_seconds = self.remaining_seconds
            self._refresh_all()

    # ── Session ops ──────────────────────────────────────────────────────

    def _first_pending_index(self):
        for i, s in enumerate(self.sessions):
            if not s.done:
                return i
        return -1

    def _current_session_seconds(self):
        if 0 <= self.current_index < len(self.sessions):
            return self.sessions[self.current_index].duration * 60
        return self.durations[self.session_type.value] * 60

    def prompt_add_focus(self):
        text, ok = QInputDialog.getText(
            self, "Add Focus", "What's your intent?")
        if ok and text.strip():
            self.add_focus(text.strip())

    def add_focus(self, name: str):
        self.sessions.append(Session(
            type="work", name=name,
            duration=self.durations["work"]))
        if self.current_index == -1:
            self.current_index = len(self.sessions) - 1
            self.session_type = SessionType.WORK
            self.remaining_seconds = self._current_session_seconds()
            self.total_seconds = self.remaining_seconds
        self._save_sessions()
        self._refresh_all()

    def add_break(self, kind: str, name: str = ""):
        default_label = ("Short Break" if kind == "short_break"
                         else "Long Break")
        self.sessions.append(Session(
            type=kind, name=name.strip() or default_label,
            duration=self.durations[kind]))
        if self.current_index == -1:
            self.current_index = len(self.sessions) - 1
            self.session_type = SessionType(kind)
            self.remaining_seconds = self._current_session_seconds()
            self.total_seconds = self.remaining_seconds
        self._save_sessions()
        self._refresh_all()

    def push_pattern(self, f: int, s: int, l: int):
        if f + s + l == 0:
            return
        for i in range(f):
            self.sessions.append(Session(
                type="work", name="Focus",
                duration=self.durations["work"]))
            if i < f - 1 and i < s:
                self.sessions.append(Session(
                    type="short_break", name="Short Break",
                    duration=self.durations["short_break"]))
        for _ in range(l):
            self.sessions.append(Session(
                type="long_break", name="Long Break",
                duration=self.durations["long_break"]))
        if self.current_index == -1:
            self.current_index = self._first_pending_index()
            if self.current_index >= 0:
                self.session_type = SessionType(
                    self.sessions[self.current_index].type)
                self.remaining_seconds = self._current_session_seconds()
                self.total_seconds = self.remaining_seconds
        self._save_sessions()
        self._refresh_all()

    def _open_pattern_popup(self, anchor: QPushButton):
        popup = PatternPopup(self, self)
        popup.show_at(anchor)

    def _open_add_popup(self, anchor: QPushButton):
        popup = AddSessionPopup(self, self)
        popup.show_at(anchor)

    def clear_stack(self):
        self._tick.stop()
        self.timer_state = TimerState.IDLE
        self.sessions.clear()
        self.current_index = -1
        self.session_type = SessionType.WORK
        self.remaining_seconds = self.durations["work"] * 60
        self.total_seconds = self.remaining_seconds
        self._save_sessions()
        self._refresh_all()

    def restart_stack(self):
        if not self.sessions:
            return
        self._tick.stop()
        self.timer_state = TimerState.IDLE
        for s in self.sessions:
            s.done = False
        self.current_index = 0
        self.session_type = SessionType(self.sessions[0].type)
        self.remaining_seconds = self._current_session_seconds()
        self.total_seconds = self.remaining_seconds
        self._save_sessions()
        self._refresh_all()

    def _on_row_selected(self, row: int):
        if 0 <= row < len(self.sessions) and self.timer_state == TimerState.IDLE:
            # Switch the running pointer if user clicks a not-done row.
            if not self.sessions[row].done:
                self.current_index = row
                self.session_type = SessionType(self.sessions[row].type)
                self.remaining_seconds = self._current_session_seconds()
                self.total_seconds = self.remaining_seconds
                self._refresh_display()

    def _session_context_menu(self, pt, list_widget=None):
        if list_widget is None:
            list_widget = self.session_list
        item = list_widget.itemAt(pt)
        if item is None:
            return
        idx = list_widget.row(item)
        menu = QMenu(self)
        menu.addAction("Rename").triggered.connect(
            lambda: self._rename_index(idx))
        menu.addAction("Delete").triggered.connect(
            lambda: self._remove(idx))
        menu.addAction("Set duration…").triggered.connect(
            lambda: self._prompt_duration(idx))
        menu.exec(list_widget.viewport().mapToGlobal(pt))

    def _remove(self, idx: int):
        if not (0 <= idx < len(self.sessions)):
            return
        self.sessions.pop(idx)
        if not self.sessions:
            self.current_index = -1
        elif idx <= self.current_index:
            self.current_index = self._first_pending_index()
        self._save_sessions()
        self._refresh_all()

    def _prompt_duration(self, idx: int):
        if not (0 <= idx < len(self.sessions)):
            return
        s = self.sessions[idx]
        val, ok = QInputDialog.getInt(
            self, "Duration", "Minutes", s.duration, 1, 600)
        if ok:
            s.duration = val
            if idx == self.current_index:
                self.total_seconds = val * 60
                self.remaining_seconds = val * 60
            self._save_sessions()
            self._refresh_all()

    # ── Templates ────────────────────────────────────────────────────────

    def open_templates(self):
        dlg = TemplatesDialog(self, self)
        dlg.exec()

    # ── Timer ────────────────────────────────────────────────────────────

    def toggle_timer(self):
        if self.timer_state == TimerState.RUNNING:
            self.timer_state = TimerState.PAUSED
            self._tick.stop()
        else:
            if self.current_index < 0:
                return
            self.timer_state = TimerState.RUNNING
            self._tick.start()
        self._refresh_buttons()

    def reset_timer(self):
        self._tick.stop()
        self.timer_state = TimerState.IDLE
        self.remaining_seconds = self._current_session_seconds()
        self.total_seconds = self.remaining_seconds
        self._refresh_all()

    def skip_session(self):
        self._tick.stop()
        self._session_complete(completed=False)

    def _on_tick(self):
        if self.timer_state != TimerState.RUNNING:
            return
        self.remaining_seconds -= 1
        if self.remaining_seconds <= 0:
            self.remaining_seconds = 0
            self._refresh_display()
            self._session_complete()
            return
        self._refresh_display()

    def _session_complete(self, completed=True):
        # completed=False means the user skipped: advance past the session
        # but don't record it as work done, and don't chime/notify/auto-start.
        self.timer_state = TimerState.IDLE
        completed_type = None
        if 0 <= self.current_index < len(self.sessions):
            cur = self.sessions[self.current_index]
            cur.done = True
            completed_type = cur.type
            if completed and completed_type == "work":
                self.stats.record_session(cur.duration, cur.name)
                notify("Pomo", f"Done: {cur.name}",
                       enabled=self.notifications_enabled)
                self.sounds.play("work", enabled=self.sounds_enabled)
            elif completed:
                notify("Pomo", "Break's over — time to focus!",
                       enabled=self.notifications_enabled)
                self.sounds.play("break", enabled=self.sounds_enabled)

        next_idx = self._first_pending_index()
        self.current_index = next_idx
        if next_idx >= 0:
            self.session_type = SessionType(self.sessions[next_idx].type)
        else:
            self.session_type = SessionType.WORK
        self.remaining_seconds = self._current_session_seconds()
        self.total_seconds = self.remaining_seconds

        if not completed:
            auto = False
        elif completed_type == "work":
            auto = self.auto_start_breaks
        elif completed_type in ("short_break", "long_break"):
            auto = self.chain_auto_start
        else:
            auto = False
        self._save_sessions()
        self._refresh_all()
        if auto and next_idx >= 0:
            self.timer_state = TimerState.RUNNING
            self._tick.start()
            self._refresh_buttons()

    # ── Display ──────────────────────────────────────────────────────────

    def _palette_for_session(self):
        t = THEME
        if self.session_type == SessionType.WORK:
            return t["work"], t["work_dim"]
        if self.session_type == SessionType.SHORT_BREAK:
            return t["break"], t["break_dim"]
        return t["long_break"], t["long_break_dim"]

    def _label_for_session(self):
        if (self.session_type == SessionType.WORK
                and 0 <= self.current_index < len(self.sessions)):
            return self.sessions[self.current_index].name
        if self.session_type == SessionType.SHORT_BREAK:
            return "Short Break"
        if self.session_type == SessionType.LONG_BREAK:
            return "Long Break"
        return "Focus"

    def _refresh_display(self):
        progress = (self.remaining_seconds / self.total_seconds
                    if self.total_seconds else 0)
        mins = self.remaining_seconds // 60
        secs = self.remaining_seconds % 60
        time_text = f"{mins:02d}:{secs:02d}"
        color, dim = self._palette_for_session()
        label = self._label_for_session()
        t = THEME
        self.ring.set_state(
            progress, time_text, label, color, dim,
            t["text"], t["text_dim"])
        self._refresh_buttons()

    def _refresh_buttons(self):
        # Glyph + tooltip swap with state. ▶ for idle/paused (start/resume),
        # ⏸ for running.
        if self.timer_state == TimerState.RUNNING:
            glyph, tip = "⏸", "Pause (Space)"
        elif self.timer_state == TimerState.PAUSED:
            glyph, tip = "▶", "Resume (Space)"
        else:
            glyph, tip = "▶", "Start (Space)"
        if self.start_btn.text() != glyph:
            self.start_btn.setText(glyph)
        if self.start_btn.toolTip() != tip:
            self.start_btn.setToolTip(tip)
        names = {
            SessionType.WORK: "primary",
            SessionType.SHORT_BREAK: "breakPrimary",
            SessionType.LONG_BREAK: "longPrimary",
        }
        obj = names[self.session_type]
        # Only re-poll the stylesheet when the variant actually changed —
        # _refresh_buttons fires every tick, so unconditional restyling
        # would invalidate the layout once a second.
        if obj != self._start_btn_obj:
            self.start_btn.setObjectName(obj)
            self.start_btn.style().unpolish(self.start_btn)
            self.start_btn.style().polish(self.start_btn)
            self._start_btn_obj = obj

    def _refresh_lists(self):
        lst = self.session_list
        lst.blockSignals(True)
        try:
            lst.clear()
            for i, s in enumerate(self.sessions):
                item = QListWidgetItem()
                row_widget = SessionRow(
                    self, i, s, is_current=(i == self.current_index))
                item.setSizeHint(row_widget.sizeHint())
                # Done rows can't be dropped onto / dragged — keeps the
                # active queue navigable without reordering completed work.
                if s.done:
                    item.setFlags(item.flags() & ~Qt.ItemIsDragEnabled)
                lst.addItem(item)
                lst.setItemWidget(item, row_widget)
            if 0 <= self.current_index < len(self.sessions):
                lst.setCurrentRow(self.current_index)
        finally:
            lst.blockSignals(False)

    def _on_rows_moved(self, _parent, src_start, src_end, _dst_parent,
                       dst_row):
        """Sync `self.sessions` to the visual order after a drop.

        Qt has already moved rows in the list model; we mirror that by
        moving the same slice in our domain list. `current_index` is
        adjusted so the running pointer follows its session.
        """
        if src_start != src_end:
            # We don't multi-select, but be safe.
            return
        src = src_start
        dst = dst_row
        # Qt's dst_row is the post-removal target. Translate to a stable
        # post-move index in our list.
        if dst > src:
            dst -= 1
        if src == dst or not (0 <= src < len(self.sessions)):
            return
        item = self.sessions.pop(src)
        self.sessions.insert(dst, item)
        # Adjust current_index.
        if self.current_index == src:
            self.current_index = dst
        elif src < self.current_index <= dst:
            self.current_index -= 1
        elif dst <= self.current_index < src:
            self.current_index += 1
        self._save_sessions()
        # A full refresh re-binds the row widgets to their new indices.
        self._refresh_all()

    def _rename_index(self, idx: int):
        if not (0 <= idx < len(self.sessions)):
            return
        text, ok = QInputDialog.getText(
            self, "Rename", "Name", text=self.sessions[idx].name)
        if ok and text.strip():
            self.sessions[idx].name = text.strip()
            self._save_sessions()
            self._refresh_all()

    def _adjust_duration(self, idx: int, delta: int):
        if not (0 <= idx < len(self.sessions)):
            return
        s = self.sessions[idx]
        s.duration = max(1, s.duration + delta)
        if idx == self.current_index and self.timer_state == TimerState.IDLE:
            self.total_seconds = s.duration * 60
            self.remaining_seconds = self.total_seconds
        self._save_sessions()
        self._refresh_all()

    def _refresh_today(self):
        td = self.stats.today
        sessions = td["sessions"]
        minutes = int(td["minutes"])
        hrs, mins = divmod(minutes, 60)
        time_str = f"{hrs}h {mins}m" if hrs else f"{mins}m"
        plural = "s" if sessions != 1 else ""
        self.today_label.setText(
            f"Today · {sessions} session{plural} · {time_str} focused")

    def _refresh_all(self):
        self._refresh_display()
        self._refresh_lists()
        self._refresh_today()


# ── Templates dialog ─────────────────────────────────────────────────────────

class TemplatesDialog(QDialog):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Templates")
        self.setMinimumWidth(420)
        self.app = app
        self._build()

    def _load(self):
        data = load_json(TEMPLATES_FILE, None)
        slots = [None] * TEMPLATE_SLOTS
        if isinstance(data, list):
            for i, item in enumerate(data[:TEMPLATE_SLOTS]):
                if isinstance(item, dict) and isinstance(
                        item.get("sessions"), list):
                    slots[i] = {
                        "name": item.get("name") or f"Template {i + 1}",
                        "sessions": item["sessions"],
                    }
        return slots

    def _save(self, slots):
        save_json(TEMPLATES_FILE, slots)

    def _build(self):
        v = QVBoxLayout(self)
        v.setSpacing(8)
        self._populate(v)

    def _populate(self, layout):
        """Fill the dialog body: one row per template slot, then Close.

        The single source for the slot-row structure — used by the
        initial build and by _rebuild after any slot changes.
        """
        slots = self._load()
        for i in range(TEMPLATE_SLOTS):
            row = QHBoxLayout()
            slot = slots[i]
            label = QLabel(slot["name"] if slot else f"Slot {i + 1}")
            label.setMinimumWidth(160)
            row.addWidget(label)
            summary = QLabel(
                self._summarize(slot["sessions"]) if slot else "empty")
            summary.setObjectName("muted")
            row.addWidget(summary, 1)

            save_btn = QPushButton("Save current")
            save_btn.setObjectName("chip")
            save_btn.clicked.connect(lambda _=False, idx=i: self._save_to(idx))
            row.addWidget(save_btn)
            if slot:
                load_btn = QPushButton("Load")
                load_btn.setObjectName("chip")
                load_btn.clicked.connect(
                    lambda _=False, idx=i: self._load_from(idx))
                row.addWidget(load_btn)
                rename_btn = QPushButton("Rename")
                rename_btn.setObjectName("chip")
                rename_btn.clicked.connect(
                    lambda _=False, idx=i: self._rename(idx))
                row.addWidget(rename_btn)
                del_btn = QPushButton("×")
                del_btn.setObjectName("chip")
                del_btn.clicked.connect(
                    lambda _=False, idx=i: self._delete(idx))
                row.addWidget(del_btn)
            layout.addLayout(row)

        # Close is the box's only button; it carries the reject role, so
        # no accepted wiring exists (Esc rejects as well).
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

    def _summarize(self, sessions):
        work = sum(1 for s in sessions if s.get("type") == "work")
        breaks = len(sessions) - work
        return (f"{work} focus · {breaks} "
                f"break{'s' if breaks != 1 else ''}")

    def _save_to(self, slot: int):
        if not self.app.sessions:
            QMessageBox.information(
                self, "Empty", "Stack is empty — add a session first.")
            return
        slots = self._load()
        existing_name = (slots[slot]["name"] if slots[slot]
                         else f"Template {slot + 1}")
        ts = []
        for s in self.app.sessions:
            ts.append({"type": s.type, "name": s.name,
                       "duration": s.duration})
        slots[slot] = {"name": existing_name, "sessions": ts}
        self._save(slots)
        QMessageBox.information(
            self, "Saved", f"Saved to {existing_name}.")
        self._rebuild()

    def _load_from(self, slot: int):
        slots = self._load()
        if not slots[slot]:
            return
        new = []
        for item in slots[slot]["sessions"]:
            t = item.get("type")
            if t not in ("work", "short_break", "long_break"):
                continue
            new.append(Session(
                type=t,
                name=item.get("name") or "Focus",
                duration=int(item.get("duration",
                                      self.app.durations[t]))))
        self.app.sessions = new
        self.app.current_index = self.app._first_pending_index()
        if self.app.current_index >= 0:
            self.app.session_type = SessionType(
                self.app.sessions[self.app.current_index].type)
            self.app.remaining_seconds = self.app._current_session_seconds()
            self.app.total_seconds = self.app.remaining_seconds
        self.app._save_sessions()
        self.app._refresh_all()
        self.accept()

    def _rename(self, slot: int):
        slots = self._load()
        if not slots[slot]:
            return
        text, ok = QInputDialog.getText(
            self, "Rename Template", "Name", text=slots[slot]["name"])
        if ok and text.strip():
            slots[slot]["name"] = text.strip()
            self._save(slots)
            self._rebuild()

    def _delete(self, slot: int):
        slots = self._load()
        slots[slot] = None
        self._save(slots)
        self._rebuild()

    def _rebuild(self):
        # Tear down the dialog body, then refill it from the same
        # _populate the initial build uses. Keeps state in sync.
        layout = self.layout()
        while layout.count():
            it = layout.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
            else:
                sub = it.layout()
                if sub is not None:
                    while sub.count():
                        sub_it = sub.takeAt(0)
                        if sub_it.widget():
                            sub_it.widget().deleteLater()
        self._populate(layout)


# ── Entry point ──────────────────────────────────────────────────────────────

def main():
    # Qt 6 enables HiDPI scaling automatically; no setup needed.
    app = QApplication(sys.argv)
    app.setApplicationName("Pomo")
    app.setApplicationDisplayName("Pomo")
    # Match StartupWMClass in the .desktop file so the running window
    # groups under the Pomo icon instead of "python3".
    app.setDesktopFileName("pomo")
    # Look up the icon next to this script. Skip if missing — keeps
    # `python pomo_qt.py` working before `gen_icon.py` has been run.
    icon_path = Path(__file__).resolve().parent / "pomo.png"
    if icon_path.exists():
        icon = QIcon(str(icon_path))
        app.setWindowIcon(icon)
    win = PomoWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
