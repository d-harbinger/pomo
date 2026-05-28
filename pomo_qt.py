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

import json
import math
import os
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

from PySide6.QtCore import QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor, QFont, QFontDatabase, QIcon, QKeySequence, QPainter, QPen,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox,
    QPushButton, QSizePolicy, QSpinBox, QToolButton, QVBoxLayout, QWidget,
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


# ── Themes ───────────────────────────────────────────────────────────────────

THEMES = {
    "midnight": {
        "bg": "#1a1a2e", "surface": "#16213e", "surface_light": "#1f3056",
        "work": "#e94560", "work_dim": "#8b2a3a",
        "break": "#0f9b58", "break_dim": "#0a6b3d",
        "long_break": "#4a90d9", "long_break_dim": "#2d5a8a",
        "text": "#eaeaea", "text_dim": "#8892a0", "text_muted": "#5a6474",
        "done": "#3a4a5a", "done_text": "#6a7a8a",
    },
    "ember": {
        "bg": "#1a1614", "surface": "#2a211c", "surface_light": "#3a2d24",
        "work": "#ff7a45", "work_dim": "#a04828",
        "break": "#d4a574", "break_dim": "#8a6b4a",
        "long_break": "#c69a5e", "long_break_dim": "#7d6140",
        "text": "#f4ecd8", "text_dim": "#a8998a", "text_muted": "#6a5d50",
        "done": "#3a312a", "done_text": "#7a6d60",
    },
    "forest": {
        "bg": "#0f1a14", "surface": "#17271e", "surface_light": "#20362a",
        "work": "#5cc78a", "work_dim": "#2f7a4f",
        "break": "#8fb48d", "break_dim": "#5a7759",
        "long_break": "#6fb8c9", "long_break_dim": "#417480",
        "text": "#e8f0e4", "text_dim": "#8fa598", "text_muted": "#566b5f",
        "done": "#2a3a30", "done_text": "#6a8576",
    },
    "ocean": {
        "bg": "#0d1b2a", "surface": "#1b2a3c", "surface_light": "#2a3d52",
        "work": "#5eb3ff", "work_dim": "#2d6a9e",
        "break": "#76d5c7", "break_dim": "#3e8a80",
        "long_break": "#a78bfa", "long_break_dim": "#6b52a8",
        "text": "#e4ecf5", "text_dim": "#8ea0b4", "text_muted": "#546578",
        "done": "#2a3a4a", "done_text": "#6b7e92",
    },
    "mono": {
        "bg": "#141414", "surface": "#1f1f1f", "surface_light": "#2a2a2a",
        "work": "#e8e8e8", "work_dim": "#8a8a8a",
        "break": "#a8a8a8", "break_dim": "#6a6a6a",
        "long_break": "#888888", "long_break_dim": "#555555",
        "text": "#f0f0f0", "text_dim": "#a0a0a0", "text_muted": "#606060",
        "done": "#333333", "done_text": "#707070",
    },
    "plum": {
        "bg": "#1a1320", "surface": "#271d33", "surface_light": "#362a48",
        "work": "#d070d0", "work_dim": "#803a80",
        "break": "#9b5fc9", "break_dim": "#5e3a80",
        "long_break": "#ef8fa8", "long_break_dim": "#95546a",
        "text": "#efe4f5", "text_dim": "#a598b4", "text_muted": "#655878",
        "done": "#322a3f", "done_text": "#7d6e90",
    },
}


def stylesheet(theme: dict) -> str:
    """Translate the theme dict into a Qt stylesheet.

    Qt's stylesheet engine is CSS-like — one place sets every widget's look.
    """
    t = theme
    return f"""
    QWidget {{
        background-color: {t['bg']};
        color: {t['text']};
        font-family: "Inter", "Cantarell", "Ubuntu", "Noto Sans",
                     "Liberation Sans", "Segoe UI", system-ui, sans-serif;
        font-size: 10pt;
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
        font-size: 10pt;
    }}
    QPushButton:hover {{ color: {t['text']}; background-color: {t['surface']}; }}
    /* Primary action: outline + accent color, bigger glyph for icon mode. */
    QPushButton#primary {{
        background: transparent;
        color: {t['work']};
        font-size: 14pt;
        padding: 0px;
        border: 1px solid {t['work']};
        border-radius: 3px;
    }}
    QPushButton#primary:hover {{
        background-color: {t['work']}; color: white;
    }}
    QPushButton#breakPrimary {{
        background: transparent; color: {t['break']};
        font-size: 14pt; padding: 0px;
        border: 1px solid {t['break']}; border-radius: 3px;
    }}
    QPushButton#breakPrimary:hover {{
        background-color: {t['break']}; color: white;
    }}
    QPushButton#longPrimary {{
        background: transparent; color: {t['long_break']};
        font-size: 14pt; padding: 0px;
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
        font-size: 13pt;
        padding: 0px;
    }}
    QPushButton#iconControl:hover {{
        background-color: {t['surface']};
        color: {t['text']};
    }}
    QPushButton#chip {{
        background: transparent;
        color: {t['text_muted']};
        padding: 3px 8px;
        font-size: 9pt;
        border-radius: 3px;
    }}
    QPushButton#chip:hover {{
        color: {t['text']};
        background-color: {t['surface']};
    }}
    QPushButton#rowChip {{
        background: transparent;
        color: {t['text_muted']};
        padding: 0px;
        font-size: 11pt;
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
        background: transparent; padding: 4px; font-size: 12pt;
        color: {t['text_dim']};
        border-radius: 3px;
    }}
    QPushButton#icon:hover {{
        background-color: {t['surface']};
        color: {t['text']};
    }}
    QLabel#title {{
        font-size: 13pt; font-weight: 600; color: {t['text']};
        letter-spacing: 0.5px;
    }}
    QLabel#titleDot {{
        color: {t['work']}; font-size: 14pt; padding-bottom: 2px;
    }}
    QFrame#hairline {{
        background-color: {t['surface_light']};
        border: none;
        max-height: 1px;
    }}
    QPushButton#addRow {{
        background: transparent;
        color: {t['text_muted']};
        border: 1px dashed {t['surface_light']};
        border-radius: 3px;
        padding: 6px 8px;
        font-size: 10pt;
        text-align: left;
    }}
    QPushButton#addRow:hover {{
        color: {t['text']};
        border-color: {t['text_muted']};
        background-color: {t['surface']};
    }}
    QLabel#muted {{ color: {t['text_muted']}; font-size: 9pt; }}
    QLabel#dim {{ color: {t['text_dim']}; font-size: 10pt; }}
    QListWidget {{
        background: transparent; border: none; outline: none;
        font-size: 10pt;
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


# ── Stats (extracted) ────────────────────────────────────────────────────────

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
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        size = min(self.width(), self.height())
        ring_w = max(2, size // 28)
        cx, cy = self.width() / 2, self.height() / 2
        r = max(8, (size / 2) - ring_w - 4)
        rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)

        # Track
        pen = QPen(self._dim, ring_w, Qt.SolidLine, Qt.FlatCap)
        p.setPen(pen)
        p.drawEllipse(rect)

        # Progress arc — Qt angles are in 1/16ths of a degree.
        if self._progress > 0.001:
            pen = QPen(self._color, ring_w, Qt.SolidLine, Qt.RoundCap)
            p.setPen(pen)
            start = 90 * 16
            span = -int(360 * self._progress * 16)
            p.drawArc(rect, start, span)

        # Time text — scale with the inner diameter so it always fits
        # inside the ring (no min-clamp; ring shrinks freely with window).
        time_size = max(8, int(size * 0.16))
        f = QFont("JetBrains Mono", time_size)
        if not f.exactMatch():
            f = QFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
            f.setPointSize(time_size)
        f.setBold(True)
        p.setFont(f)
        p.setPen(self._text_color)
        time_rect = QRect(0, int(cy - time_size), self.width(), time_size * 2)
        p.drawText(time_rect, Qt.AlignCenter, self._time_text)

        # Label below — hide it once the ring is too small to fit cleanly.
        if size >= 130:
            label_size = max(7, int(size * 0.052))
            lf = QFont()
            lf.setPointSize(label_size)
            p.setFont(lf)
            p.setPen(self._text_dim)
            label_rect = QRect(
                0, int(cy + time_size * 0.6),
                self.width(), label_size * 3)
            p.drawText(label_rect, Qt.AlignHCenter | Qt.AlignTop, self._label)


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

        t = THEMES[app.theme_name]
        accent = (t["work"] if session.type == "work"
                  else t["break"] if session.type == "short_break"
                  else t["long_break"])
        muted = t["text_muted"]
        text_color = t["done_text"] if session.done else t["text"]

        h = QHBoxLayout(self)
        h.setContentsMargins(0, 3, 6, 3)
        h.setSpacing(8)

        # Drag handle — visible affordance that rows are reorderable.
        handle = QLabel("⠿")
        handle.setStyleSheet(
            f"color: {muted}; font-size: 12pt; padding: 0 2px;")
        handle.setFixedWidth(16)
        handle.setAlignment(Qt.AlignCenter)
        handle.setCursor(Qt.SizeAllCursor)
        handle.setToolTip("Drag to reorder")
        h.addWidget(handle)

        # Colored type stripe. Active row gets a thicker stripe so it
        # reads as the focal point of the queue.
        stripe = QFrame()
        stripe.setFixedWidth(5 if is_current else 2)
        stripe.setStyleSheet(
            f"background: {accent if not session.done else muted};"
            "border: none;")
        h.addWidget(stripe)

        # Status marker — only present for done/current.
        marker_text = ("✓" if session.done
                       else "▸" if is_current
                       else "")
        marker_color = (muted if session.done
                        else accent if is_current
                        else muted)
        marker = QLabel(marker_text)
        marker.setStyleSheet(
            f"color: {marker_color}; font-size: 11pt; "
            "background: transparent;")
        marker.setFixedWidth(12)
        marker.setAlignment(Qt.AlignCenter)
        h.addWidget(marker)

        # Name — heavier on the current row to anchor the eye.
        self.name_lbl = QLabel(session.name)
        weight = ("normal" if session.done
                  else "600" if is_current
                  else "500")
        self.name_lbl.setStyleSheet(
            f"color: {text_color}; font-size: 10pt; "
            f"font-weight: {weight}; background: transparent;")
        self.name_lbl.setCursor(Qt.IBeamCursor)
        self.name_lbl.mouseDoubleClickEvent = (
            lambda _e: self.app._rename_index(self.index))
        h.addWidget(self.name_lbl, 1)

        # Duration ± — current row's duration picks up the accent so
        # you instantly see what's about to run.
        minus = QPushButton("−"); minus.setObjectName("rowChip")
        minus.setFixedSize(18, 18)
        minus.setFlat(True)
        minus.clicked.connect(lambda: self.app._adjust_duration(self.index, -1))
        h.addWidget(minus)

        dur_color = (accent if is_current and not session.done
                     else muted)
        self.dur_lbl = QLabel(f"{session.duration}m")
        self.dur_lbl.setStyleSheet(
            f"color: {dur_color}; font-size: 9pt; "
            f"font-weight: {'600' if is_current else 'normal'}; "
            "background: transparent;")
        self.dur_lbl.setMinimumWidth(32)
        self.dur_lbl.setAlignment(Qt.AlignCenter)
        self.dur_lbl.setCursor(Qt.PointingHandCursor)
        self.dur_lbl.mouseDoubleClickEvent = (
            lambda _e: self.app._prompt_duration(self.index))
        h.addWidget(self.dur_lbl)

        plus = QPushButton("+"); plus.setObjectName("rowChip")
        plus.setFixedSize(18, 18)
        plus.setFlat(True)
        plus.clicked.connect(lambda: self.app._adjust_duration(self.index, +1))
        h.addWidget(plus)

        delete = QPushButton("×"); delete.setObjectName("rowChip")
        delete.setFixedSize(18, 18)
        delete.setFlat(True)
        delete.setToolTip("Remove")
        delete.clicked.connect(lambda: self.app._remove(self.index))
        h.addWidget(delete)


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
        t = THEMES[app.theme_name]
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
                "font-weight: 600; font-size: 9pt;")
        return (
            f"background: transparent; color: {color}; "
            f"border: 1px solid {color}; border-radius: 3px; "
            "padding: 4px 10px; font-weight: 500; font-size: 9pt;")

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

        # Three spinboxes labeled F/S/L. The labels echo the theme colors
        # for instant scanability (focus / short / long).
        t = THEMES[app.theme_name]
        for label_text, key, color in (
            ("F", "focus", t["work"]),
            ("S", "short", t["break"]),
            ("L", "long", t["long_break"]),
        ):
            lbl = QLabel(label_text)
            lbl.setStyleSheet(
                f"color: {color}; font-weight: 700; font-size: 10pt;")
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
    """One stop for theme / durations / sounds / notifications."""

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

        self.theme_combo = QComboBox()
        for name in THEMES.keys():
            self.theme_combo.addItem(name.capitalize(), name)
        idx = self.theme_combo.findData(app.theme_name)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
        self.theme_combo.currentIndexChanged.connect(self._apply_theme)
        form.addRow("Theme", self.theme_combo)

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

    def _apply_theme(self, _idx):
        name = self.theme_combo.currentData()
        self.app.set_theme(name)


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
        self.theme_name = prefs.get("theme", "midnight")
        if self.theme_name not in THEMES:
            self.theme_name = "midnight"
        self.chain_auto_start = bool(prefs.get("chain_auto_start", False))
        self.auto_start_breaks = bool(prefs.get("auto_start_breaks", True))
        self.sounds_enabled = bool(prefs.get("sounds_enabled", True))
        self.notifications_enabled = bool(prefs.get("notifications_enabled", True))

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
        self.set_theme(self.theme_name)
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
            "theme": self.theme_name,
            "chain_auto_start": self.chain_auto_start,
            "auto_start_breaks": self.auto_start_breaks,
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
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)

        # Top bar — title with an accent dot for identity.
        top = QHBoxLayout()
        top.setSpacing(4)
        self.title_dot = QLabel("●")
        self.title_dot.setObjectName("titleDot")
        top.addWidget(self.title_dot)
        title = QLabel("pomo")
        title.setObjectName("title")
        top.addWidget(title)
        top.addStretch()

        self.settings_btn = QToolButton()
        self.settings_btn.setText("⚙")
        self.settings_btn.setObjectName("icon")
        self.settings_btn.setToolTip("Settings")
        self.settings_btn.clicked.connect(self.open_settings)
        top.addWidget(self.settings_btn)
        root.addLayout(top)

        # Hairline separator under the top bar.
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setObjectName("hairline")
        sep.setFixedHeight(1)
        root.addWidget(sep)

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

        self.session_panel, self.session_list, self.total_label = \
            self._build_session_panel()
        body.addWidget(self.session_panel, 4)
        root.addLayout(body, 1)

        # Today's stats (small footer)
        self.today_label = QLabel("")
        self.today_label.setObjectName("muted")
        self.today_label.setAlignment(Qt.AlignCenter)
        root.addWidget(self.today_label)

    def _build_session_panel(self):
        """Session list + add/manage row. Returns (wrap, list, total_label)."""
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(4)
        head_label = QLabel("SESSIONS")
        head_label.setStyleSheet(
            "font-size: 9pt; letter-spacing: 1.5px; "
            f"color: {THEMES[self.theme_name]['text_muted']};")
        head.addWidget(head_label)

        restart = QPushButton("Restart"); restart.setObjectName("chip")
        restart.clicked.connect(self.restart_stack)
        head.addWidget(restart)
        clear = QPushButton("Clear"); clear.setObjectName("chip")
        clear.clicked.connect(self.clear_stack)
        head.addWidget(clear)
        head.addStretch()

        templates = QPushButton("Templates"); templates.setObjectName("chip")
        templates.clicked.connect(self.open_templates)
        head.addWidget(templates)

        push_pat = QPushButton("Pattern"); push_pat.setObjectName("chip")
        push_pat.setToolTip("Edit F/S/L counts and push")
        push_pat.clicked.connect(
            lambda: self._open_pattern_popup(push_pat))
        head.addWidget(push_pat)
        v.addLayout(head)

        total = QLabel(""); total.setObjectName("muted")
        v.addWidget(total)

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

        return wrap, lst, total

    def _build_controls_row(self):
        row = QHBoxLayout()
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
        row.addWidget(reset)

        skip = QPushButton("⏭")
        skip.setObjectName("iconControl")
        skip.setToolTip("Skip (S)")
        skip.setFixedSize(34, 32)
        skip.clicked.connect(self.skip_session)
        row.addWidget(skip)

        row.addStretch()
        return row

    # ── Theme ────────────────────────────────────────────────────────────

    def set_theme(self, name: str):
        if name not in THEMES:
            return
        self.theme_name = name
        QApplication.instance().setStyleSheet(stylesheet(THEMES[name]))
        self._persist_prefs()
        self._refresh_all()

    # ── Settings dialog ──────────────────────────────────────────────────

    def open_settings(self):
        dlg = SettingsDialog(self, self)
        before_theme = self.theme_name
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
            self._persist_prefs()
            if self.timer_state == TimerState.IDLE:
                self.remaining_seconds = self._current_session_seconds()
                self.total_seconds = self.remaining_seconds
            self._refresh_all()
        else:
            if self.theme_name != before_theme:
                self.set_theme(before_theme)

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

    def _theme(self):
        return THEMES[self.theme_name]

    def _palette_for_session(self):
        t = self._theme()
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
        t = self._theme()
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

        total_min = 0
        pending = 0
        for s in self.sessions:
            if s.done:
                continue
            pending += 1
            total_min += s.duration
        if pending == 0:
            self.total_label.setText("")
        else:
            hrs, mins = divmod(total_min, 60)
            time_str = f"{hrs}h {mins}m" if hrs else f"{mins}m"
            self.total_label.setText(
                f"{pending} pending · {time_str} planned")

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
        self.today_label.setText(
            f"Today:  {sessions} session{'s' if sessions != 1 else ''}  ·  "
            f"{time_str} focused")

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
        slots = self._load()
        for i in range(TEMPLATE_SLOTS):
            row = QHBoxLayout()
            slot = slots[i]
            label = QLabel(slot["name"] if slot else f"Slot {i + 1}")
            label.setMinimumWidth(160)
            row.addWidget(label)
            if slot:
                summary = QLabel(self._summarize(slot["sessions"]))
                summary.setObjectName("muted")
                row.addWidget(summary, 1)
            else:
                empty = QLabel("empty")
                empty.setObjectName("muted")
                row.addWidget(empty, 1)

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
            v.addLayout(row)

        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        v.addWidget(bb)

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
        # Tear down and rebuild dialog body. Keeps state in sync.
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
        # Re-populate.
        slots = self._load()
        for i in range(TEMPLATE_SLOTS):
            row = QHBoxLayout()
            slot = slots[i]
            label = QLabel(slot["name"] if slot else f"Slot {i + 1}")
            label.setMinimumWidth(160)
            row.addWidget(label)
            if slot:
                summary = QLabel(self._summarize(slot["sessions"]))
                summary.setObjectName("muted")
                row.addWidget(summary, 1)
            else:
                empty = QLabel("empty"); empty.setObjectName("muted")
                row.addWidget(empty, 1)
            save_btn = QPushButton("Save current"); save_btn.setObjectName("chip")
            save_btn.clicked.connect(lambda _=False, idx=i: self._save_to(idx))
            row.addWidget(save_btn)
            if slot:
                lb = QPushButton("Load"); lb.setObjectName("chip")
                lb.clicked.connect(lambda _=False, idx=i: self._load_from(idx))
                row.addWidget(lb)
                rb = QPushButton("Rename"); rb.setObjectName("chip")
                rb.clicked.connect(lambda _=False, idx=i: self._rename(idx))
                row.addWidget(rb)
                db = QPushButton("×"); db.setObjectName("chip")
                db.clicked.connect(lambda _=False, idx=i: self._delete(idx))
                row.addWidget(db)
            self.layout().addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        self.layout().addWidget(bb)


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
