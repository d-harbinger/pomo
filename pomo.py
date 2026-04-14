#!/usr/bin/env python3
"""Pomo — A clean pomodoro timer with named session planning."""

import json
import math
import os
import shutil
import struct
import subprocess
import tempfile
import wave
from datetime import date, datetime
from enum import Enum
from pathlib import Path

import customtkinter as ctk

try:
    from plyer import notification as plyer_notify
except ImportError:
    plyer_notify = None


# ── Sound ────────────────────────────────────────────────────────────────────

_SOUND_PLAYER = next((p for p in ("paplay", "aplay", "afplay", "play")
                      if shutil.which(p)), None)


def _gen_tone(path: Path, frequencies, duration_ms=400, volume=0.4):
    """Generate a short WAV chime by summing sine waves with a gentle fade-out."""
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
            sample = sum(math.sin(2 * math.pi * f * i / framerate) for f in frequencies)
            sample /= max(1, len(frequencies))
            val = int(volume * fade * 32767 * sample)
            frames.append(struct.pack("<h", val))
        w.writeframes(b"".join(frames))


class Sounds:
    """Lazy-generated chimes played via a system audio player."""

    def __init__(self):
        d = Path(tempfile.gettempdir()) / "pomo-sounds"
        self.files = {
            # Rising two-tone "done" chime for work sessions (C5 + E5 + G5 — major triad).
            "work": d / "work_done.wav",
            # Gentler single tone for end-of-break.
            "break": d / "break_done.wav",
        }
        if not self.files["work"].exists():
            _gen_tone(self.files["work"], [523.25, 659.25, 783.99], duration_ms=500)
        if not self.files["break"].exists():
            _gen_tone(self.files["break"], [880.0], duration_ms=350, volume=0.35)

    def play(self, which: str, enabled: bool = True):
        if not enabled:
            return
        path = self.files.get(which)
        if not (_SOUND_PLAYER and path and path.exists()):
            return
        try:
            subprocess.Popen([_SOUND_PLAYER, str(path)],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        except Exception:
            pass


# ── Paths ────────────────────────────────────────────────────────────────────

DATA_DIR = Path(os.environ.get("POMO_DATA_DIR", Path.home() / ".local" / "share" / "pomo"))
STATS_FILE = DATA_DIR / "stats.json"
HISTORY_FILE = DATA_DIR / "history.json"
PREFS_FILE = DATA_DIR / "prefs.json"
SESSIONS_FILE = DATA_DIR / "sessions.json"
TEMPLATES_FILE = DATA_DIR / "templates.json"
TEMPLATE_SLOTS = 5

DEFAULT_WORK = 25
DEFAULT_SHORT_BREAK = 5
DEFAULT_LONG_BREAK = 15


# ── Persistence ──────────────────────────────────────────────────────────────

def load_json(path: Path, default=None):
    if default is None:
        default = {}
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return default


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ── State enums ──────────────────────────────────────────────────────────────

class SessionType(Enum):
    WORK = "work"
    SHORT_BREAK = "short_break"
    LONG_BREAK = "long_break"


class TimerState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"


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

# Active theme dict — mutated in place so widgets look up current values
C = dict(THEMES["midnight"])


# ── Notifications ────────────────────────────────────────────────────────────

def notify(title: str, message: str):
    if plyer_notify is None:
        return
    try:
        plyer_notify.notify(title=title, message=message, app_name="Pomo", timeout=10)
    except Exception:
        pass


# ── Ring canvas ──────────────────────────────────────────────────────────────

class RingCanvas(ctk.CTkCanvas):
    def __init__(self, master, size=240, ring_width=8, **kwargs):
        super().__init__(master, width=size, height=size, bg=C["bg"],
                         highlightthickness=0, **kwargs)
        self.size = size
        self.ring_width = ring_width

    def draw(self, progress: float, time_text: str, label: str, color: str, dim: str):
        self.delete("all")
        cx = cy = self.size / 2
        r = (self.size / 2) - self.ring_width - 4
        pad = self.ring_width / 2

        self.create_oval(cx - r - pad, cy - r - pad, cx + r + pad, cy + r + pad,
                         outline=dim, width=self.ring_width)

        if progress > 0.001:
            self.create_arc(cx - r - pad, cy - r - pad, cx + r + pad, cy + r + pad,
                            start=90, extent=-360 * progress,
                            outline=color, width=self.ring_width, style="arc")

        # Scale text with ring size so compact rings don't overlap.
        time_font_size = max(14, int(self.size * 0.15))
        label_font_size = max(8, int(self.size * 0.05))
        offset = int(self.size * 0.08)
        self.create_text(cx, cy - offset / 2, text=time_text, fill=C["text"],
                         font=("JetBrains Mono", time_font_size, "bold"))
        self.create_text(cx, cy + offset + label_font_size, text=label,
                         fill=C["text_dim"], font=("Inter", label_font_size))


# ── Pipped bar (retro "health bar" timer for wide mode) ─────────────────────

class PipBar(ctk.CTkCanvas):
    """Vertical Mega Man-style health bar: thin stacked pips that drain top-down.

    Each pip = 1 minute. Draws large time readout at the top, then a single
    column of pips filling the remainder of the canvas.
    """

    def __init__(self, master, width=72, height=400, cols=1, **kwargs):
        super().__init__(master, width=width, height=height, bg=C["bg"],
                         highlightthickness=0, **kwargs)
        self.w = width
        self.h = height
        self.cols = cols

    def set_size(self, width, height):
        """Refresh internal dimensions after the canvas is resized by its layout."""
        self.w = width
        self.h = height
        self.configure(width=width, height=height)

    def draw(self, total_seconds, remaining_seconds, time_text, color, dim):
        self.delete("all")
        total_min = max(1, (total_seconds + 59) // 60)
        cols = max(1, self.cols)
        rows = (total_min + cols - 1) // cols

        # Time readout at the top. "00:00" is ~3× the font size in mono,
        # so size the font to fit the canvas width.
        time_font_size = max(12, int((self.w - 8) / 3))
        time_h = time_font_size + 14
        self.create_text(self.w / 2, time_h / 2, text=time_text,
                         fill=C["text"],
                         font=("JetBrains Mono", time_font_size, "bold"))

        # Outer bezel around the pip area.
        pad = 3
        bezel_y0 = time_h + 4
        bezel_y1 = self.h - 4
        self.create_rectangle(1, bezel_y0, self.w - 1, bezel_y1,
                              outline=C["text_muted"], width=2)
        self.create_rectangle(pad, bezel_y0 + pad - 1,
                              self.w - pad, bezel_y1 - pad + 1,
                              fill=C["bg"], outline="")

        inner_x0 = pad + 2
        inner_x1 = self.w - pad - 2
        inner_y0 = bezel_y0 + pad + 1
        inner_y1 = bezel_y1 - pad - 1
        inner_w = inner_x1 - inner_x0
        inner_h = inner_y1 - inner_y0

        gap_x = 2 if cols > 1 else 0
        gap_y = 1
        pip_w = (inner_w - (cols - 1) * gap_x) / cols
        pip_h = max(3.0, (inner_h - (rows - 1) * gap_y) / rows)

        # Pip index convention: i=0 is the BOTTOM pip (drains last),
        # i=total_min-1 is the TOP pip (drains first). That matches the
        # classic Mega Man health bar — fill shrinks from the top.
        for i in range(total_min):
            r = rows - 1 - (i // cols)  # higher i = higher visual row
            c = i % cols
            x0 = inner_x0 + c * (pip_w + gap_x)
            y0 = inner_y0 + r * (pip_h + gap_y)
            x1 = x0 + pip_w
            y1 = y0 + pip_h

            # Pip `i` is full when remaining ≥ (i+1)*60, empty when ≤ i*60.
            full_at = (i + 1) * 60
            empty_at = i * 60
            if remaining_seconds >= full_at:
                frac = 1.0
            elif remaining_seconds <= empty_at:
                frac = 0.0
            else:
                frac = (remaining_seconds - empty_at) / 60.0

            # Dim background (empty slot) then colored fill from bottom up.
            self.create_rectangle(x0, y0, x1, y1, fill=dim, outline="", width=0)
            if frac > 0:
                fy0 = y1 - (y1 - y0) * frac
                self.create_rectangle(x0, fy0, x1, y1, fill=color,
                                      outline="", width=0)


# ── Session row widget ───────────────────────────────────────────────────────

class SessionRow(ctk.CTkFrame):
    def __init__(self, master, name: str, index: int, session_type: str,
                 is_active: bool, is_done: bool, duration: int = None,
                 on_remove=None, on_duration_change=None, on_rename=None,
                 on_drag_start=None, on_drag_motion=None, on_drag_end=None,
                 **kwargs):
        super().__init__(master, fg_color="transparent", height=32, **kwargs)
        self.pack_propagate(False)

        is_break = session_type != "work"
        if session_type == "short_break":
            active_color = C["break"]
        elif session_type == "long_break":
            active_color = C["long_break"]
        else:
            active_color = C["work"]

        if is_done:
            dot_color, text_color, marker = C["done"], C["done_text"], "✓"
        elif is_active:
            dot_color, text_color, marker = active_color, C["text"], "▸"
        elif is_break:
            dot_color, text_color, marker = active_color, C["text_dim"], "·"
        else:
            dot_color, text_color, marker = C["text_muted"], C["text_dim"], "○"

        indent = 20 if is_break else 0
        # Drag handle (⋮⋮): only draggable when the row is not active/done,
        # so users can't move the in-progress item out from under the timer.
        draggable = on_drag_start and not is_done and not is_active
        handle_text = "⋮⋮" if draggable else " "
        handle = ctk.CTkLabel(self, text=handle_text, font=("Inter", 11),
                              width=14, text_color=C["text_muted"],
                              fg_color="transparent",
                              cursor="fleur" if draggable else "")
        handle.pack(side="left", padx=(2 + indent, 0))
        if draggable:
            handle.bind("<ButtonPress-1>",
                        lambda e: on_drag_start(index, e.y_root))
            handle.bind("<B1-Motion>", lambda e: on_drag_motion(e.y_root))
            handle.bind("<ButtonRelease-1>", lambda e: on_drag_end(e.y_root))

        ctk.CTkLabel(self, text=marker, font=("Inter", 14), width=20,
                     text_color=dot_color, fg_color="transparent"
                     ).pack(side="left", padx=(2, 2))

        font_spec = ("Inter", 11, "italic") if is_break else ("Inter", 13)
        name_lbl = ctk.CTkLabel(self, text=name, font=font_spec,
                                text_color=text_color, fg_color="transparent",
                                anchor="w")
        name_lbl.pack(side="left", fill="x", expand=True, padx=(4, 0))
        if on_rename and not is_done and not is_break:
            name_lbl.configure(cursor="xterm")
            name_lbl.bind("<Button-1>", lambda e: on_rename())

        if not is_done and not is_active and on_remove:
            ctk.CTkButton(self, text="×", width=22, height=22,
                          font=("Inter", 14), corner_radius=11,
                          fg_color="transparent", hover_color=C["surface_light"],
                          text_color=C["text_muted"], command=on_remove
                          ).pack(side="right", padx=(0, 4))

        # Duration stepper on every non-done row (works for both work items
        # and breaks; the active session can be shortened/extended live).
        if duration is not None:
            if not is_done and on_duration_change:
                ctk.CTkButton(self, text="+", width=18, height=18,
                              font=("Inter", 11, "bold"), corner_radius=9,
                              fg_color="transparent", hover_color=C["surface_light"],
                              text_color=active_color,
                              command=lambda: on_duration_change(1)
                              ).pack(side="right", padx=(0, 2))
                dur_lbl = ctk.CTkLabel(self, text=f"{duration}m",
                                       font=("Inter", 11, "bold"),
                                       text_color=active_color, width=30,
                                       cursor="sb_v_double_arrow",
                                       fg_color="transparent")
                dur_lbl.pack(side="right")
                self.dur_lbl = dur_lbl
                if on_duration_change is not None:
                    # Click to type; drag vertically to bump by minutes.
                    drag_state = {"y": 0, "accum": 0, "dragged": False}

                    def on_press(event):
                        drag_state["y"] = event.y_root
                        drag_state["accum"] = 0
                        drag_state["dragged"] = False

                    def on_motion(event):
                        dy = drag_state["y"] - event.y_root
                        drag_state["accum"] += dy
                        drag_state["y"] = event.y_root
                        steps = int(drag_state["accum"] / 8)
                        if steps != 0:
                            drag_state["accum"] -= steps * 8
                            drag_state["dragged"] = True
                            on_duration_change(steps)

                    def on_release(event):
                        if not drag_state["dragged"]:
                            on_duration_change("set", dur_lbl)

                    dur_lbl.bind("<ButtonPress-1>", on_press)
                    dur_lbl.bind("<B1-Motion>", on_motion)
                    dur_lbl.bind("<ButtonRelease-1>", on_release)
                ctk.CTkButton(self, text="−", width=18, height=18,
                              font=("Inter", 11, "bold"), corner_radius=9,
                              fg_color="transparent", hover_color=C["surface_light"],
                              text_color=active_color,
                              command=lambda: on_duration_change(-1)
                              ).pack(side="right", padx=(2, 0))
            else:
                ctk.CTkLabel(self, text=f"{duration}m", font=("Inter", 11),
                             text_color=C["text_muted"], width=36,
                             fg_color="transparent").pack(side="right", padx=(0, 8))


# ── Stats tracker ────────────────────────────────────────────────────────────

class Stats:
    def __init__(self):
        self.data = load_json(STATS_FILE, {"days": {}, "total_sessions": 0, "total_minutes": 0})

    def record_session(self, minutes: float, task: str):
        today = date.today().isoformat()
        if today not in self.data["days"]:
            self.data["days"][today] = {"sessions": 0, "minutes": 0}
        self.data["days"][today]["sessions"] += 1
        self.data["days"][today]["minutes"] += minutes
        self.data["total_sessions"] += 1
        self.data["total_minutes"] += minutes
        save_json(STATS_FILE, self.data)

        history = load_json(HISTORY_FILE, [])
        history.append({
            "date": today,
            "time": datetime.now().strftime("%H:%M"),
            "minutes": round(minutes, 1),
            "task": task,
        })
        save_json(HISTORY_FILE, history)

    @property
    def today(self):
        today = date.today().isoformat()
        return self.data["days"].get(today, {"sessions": 0, "minutes": 0})

    @property
    def total_sessions(self):
        return self.data["total_sessions"]

    @property
    def total_minutes(self):
        return self.data["total_minutes"]


# ── Scrollable frame with working Linux scroll ──────────────────────────────

class ScrollFrame(ctk.CTkFrame):
    """A manually-built scrollable frame that works on Linux."""

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)

        self.canvas = ctk.CTkCanvas(self, bg=C["bg"], highlightthickness=0)
        self.inner = ctk.CTkFrame(self.canvas, fg_color="transparent")

        self.canvas.pack(fill="both", expand=True)
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        # Bind scroll to canvas AND propagate from all children
        for seq in ("<Button-4>", "<Button-5>", "<MouseWheel>"):
            self.canvas.bind(seq, self._on_scroll)
            self.bind(seq, self._on_scroll)

    def _on_inner_configure(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfigure(self._window, width=event.width)

    def _on_scroll(self, event):
        # Check if content is taller than canvas
        bbox = self.canvas.bbox("all")
        if bbox and bbox[3] - bbox[1] > self.canvas.winfo_height():
            if event.num == 4 or (hasattr(event, 'delta') and event.delta > 0):
                self.canvas.yview_scroll(-3, "units")
            elif event.num == 5 or (hasattr(event, 'delta') and event.delta < 0):
                self.canvas.yview_scroll(3, "units")

    def bind_scroll_recursive(self):
        """Call after adding children to propagate scroll events."""
        def _bind(widget):
            for seq in ("<Button-4>", "<Button-5>", "<MouseWheel>"):
                widget.bind(seq, self._on_scroll, add="+")
            for child in widget.winfo_children():
                _bind(child)
        _bind(self.inner)

    def clear(self):
        for widget in self.inner.winfo_children():
            widget.destroy()


# ── Main app ─────────────────────────────────────────────────────────────────

class PomoApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.stats = Stats()
        self.sounds = Sounds()
        self._editing_index = -1
        self._undo_stack = []  # list of (sessions snapshot, current_index) tuples
        self.durations = {"work": DEFAULT_WORK, "short_break": DEFAULT_SHORT_BREAK,
                          "long_break": DEFAULT_LONG_BREAK}
        self.timer_state = TimerState.IDLE
        self.session_type = SessionType.WORK
        self.remaining_seconds = self.durations["work"] * 60
        self.total_seconds = self.remaining_seconds
        self._tick_id = None

        self.sessions = self._load_sessions()
        self.current_index = self._first_pending_index()
        if self.current_index >= 0:
            self.session_type = SessionType(self.sessions[self.current_index]["type"])
            self.remaining_seconds = self._current_session_seconds()
            self.total_seconds = self.remaining_seconds
        self._view = "sessions"  # "sessions" | "stats" | "themes"

        # Load prefs (theme + toggles).
        prefs = load_json(PREFS_FILE, {})
        theme_name = prefs.get("theme", "midnight")
        if theme_name in THEMES:
            self.theme_name = theme_name
            C.update(THEMES[theme_name])
        else:
            self.theme_name = "midnight"
        self.chain_auto_start = bool(prefs.get("chain_auto_start", False))
        self.sounds_enabled = bool(prefs.get("sounds_enabled", True))
        # mode: "full" (default), "wide" (ring left + stack right), "bar" (thin).
        self.mode = prefs.get("mode")
        if self.mode not in ("full", "wide", "bar"):
            # Migrate legacy `compact` bool.
            self.mode = "bar" if prefs.get("compact") else "full"

        self.title("Pomo")
        self.configure(fg_color=C["bg"])
        self._apply_mode_geometry()

        self._build_ui()
        self._update_display()
        self._bind_shortcuts()
        self.bind("<Configure>", self._on_window_configure)
        # Click on the root window's background dismisses any focused entry.
        self.bind("<Button-1>", self._dismiss_inline_entry, add="+")

    def _apply_mode_geometry(self):
        if self.mode == "bar":
            self.geometry("380x68")
            self.minsize(320, 64)
        elif self.mode == "wide":
            self.geometry("680x360")
            self.minsize(560, 300)
        else:
            self.geometry("380x680")
            self.minsize(340, 180)

    def _build_ui(self):
        # Reset widget handles each rebuild so stale references don't linger.
        self.compact_time = None
        self.compact_task = None
        self.compact_progress = None
        self.pipbar = None
        self.wide_time = None
        self.wide_task = None
        if self.mode == "bar":
            self._build_ui_compact()
            return
        if self.mode == "wide":
            self._build_ui_wide()
            return

        # ── Top bar ──────────────────────────────────────────────────────
        top = ctk.CTkFrame(self, fg_color="transparent", height=40)
        top.pack(fill="x", padx=16, pady=(12, 0))

        ctk.CTkLabel(top, text="pomo", font=("Inter", 20, "bold"),
                     text_color=C["text"]).pack(side="left")

        self.stats_toggle_btn = ctk.CTkButton(
            top, text="📊", width=36, height=36, font=("Inter", 16),
            fg_color="transparent", hover_color=C["surface_light"],
            text_color=C["text_dim"], command=self._toggle_stats)
        self.stats_toggle_btn.pack(side="right")

        ctk.CTkButton(
            top, text="🎨", width=36, height=36, font=("Inter", 14),
            fg_color="transparent", hover_color=C["surface_light"],
            text_color=C["text_dim"], command=self._toggle_themes
        ).pack(side="right", padx=(0, 4))

        ctk.CTkButton(
            top, text="📋", width=36, height=36, font=("Inter", 14),
            fg_color="transparent", hover_color=C["surface_light"],
            text_color=C["text_dim"], command=self._toggle_templates
        ).pack(side="right", padx=(0, 4))

        # Sound toggle.
        self.sound_btn = ctk.CTkButton(
            top, text="🔊" if self.sounds_enabled else "🔇",
            width=36, height=36, font=("Inter", 14),
            fg_color="transparent", hover_color=C["surface_light"],
            text_color=C["text_dim"], command=self._toggle_sounds)
        self.sound_btn.pack(side="right", padx=(0, 4))

        # Mode cycle: full → wide → bar → full.
        ctk.CTkButton(
            top, text="🗗", width=36, height=36, font=("Inter", 14),
            fg_color="transparent", hover_color=C["surface_light"],
            text_color=C["text_dim"], command=self._cycle_mode
        ).pack(side="right", padx=(0, 4))

        # ── Timer ────────────────────────────────────────────────────────
        self.ring = RingCanvas(self, size=240)
        self.ring.pack(pady=(16, 8))

        # ── Controls ─────────────────────────────────────────────────────
        ctrl = ctk.CTkFrame(self, fg_color="transparent")
        ctrl.pack(pady=(0, 8))

        self.start_btn = ctk.CTkButton(
            ctrl, text="Start", font=("Inter", 16, "bold"),
            width=130, height=42, corner_radius=21,
            fg_color=C["work"], hover_color=C["work_dim"],
            text_color="#ffffff", command=self._toggle_timer)
        self.start_btn.pack(side="left", padx=5)

        ctk.CTkButton(ctrl, text="Reset", font=("Inter", 13),
                      width=70, height=42, corner_radius=21,
                      fg_color=C["surface"], hover_color=C["surface_light"],
                      text_color=C["text_dim"],
                      command=self._reset_timer).pack(side="left", padx=5)

        ctk.CTkButton(ctrl, text="Skip", font=("Inter", 13),
                      width=60, height=42, corner_radius=21,
                      fg_color=C["surface"], hover_color=C["surface_light"],
                      text_color=C["text_dim"],
                      command=self._skip_session).pack(side="left", padx=5)

        # Chain toggle: auto-start the next session after a break.
        chain_row = ctk.CTkFrame(self, fg_color="transparent")
        chain_row.pack(pady=(0, 2))
        self.chain_var = ctk.BooleanVar(value=self.chain_auto_start)
        ctk.CTkCheckBox(chain_row, text="Auto-start next session",
                        font=("Inter", 10), text_color=C["text_muted"],
                        variable=self.chain_var, height=16,
                        checkbox_width=14, checkbox_height=14,
                        fg_color=C["work"], hover_color=C["work_dim"],
                        border_color=C["surface_light"],
                        command=self._toggle_chain).pack()

        # ── Duration steppers ────────────────────────────────────────────
        dur_frame = ctk.CTkFrame(self, fg_color="transparent")
        dur_frame.pack(fill="x", padx=28, pady=(4, 4))

        self.dur_labels = {}
        for label, key, color in [("Focus", "work", C["work"]),
                                   ("Short", "short_break", C["break"]),
                                   ("Long", "long_break", C["long_break"])]:
            col = ctk.CTkFrame(dur_frame, fg_color="transparent")
            col.pack(side="left", expand=True)

            ctk.CTkLabel(col, text=label, font=("Inter", 10),
                         text_color=C["text_muted"]).pack()

            row = ctk.CTkFrame(col, fg_color="transparent")
            row.pack()

            ctk.CTkButton(row, text="−", width=22, height=22, font=("Inter", 13),
                          corner_radius=11, fg_color=C["surface"],
                          hover_color=C["surface_light"], text_color=C["text_dim"],
                          command=lambda k=key: self._adjust_duration(k, -1)
                          ).pack(side="left", padx=1)

            dur_lbl = ctk.CTkLabel(row, text="", font=("Inter", 12, "bold"),
                                   text_color=color, width=36, cursor="sb_v_double_arrow")
            dur_lbl.pack(side="left", padx=2)
            self.dur_labels[key] = dur_lbl

            dur_lbl.bind("<Button-1>", lambda e, k=key: self._drag_start(e, k))
            dur_lbl.bind("<B1-Motion>", self._drag_motion)
            dur_lbl.bind("<ButtonRelease-1>", self._drag_end)
            dur_lbl.bind("<Double-Button-1>",
                         lambda e, k=key, lbl=label: self._prompt_duration(k, lbl))

            ctk.CTkButton(row, text="+", width=22, height=22, font=("Inter", 13),
                          corner_radius=11, fg_color=C["surface"],
                          hover_color=C["surface_light"], text_color=C["text_dim"],
                          command=lambda k=key: self._adjust_duration(k, 1)
                          ).pack(side="left", padx=1)

        self._update_dur_labels()

        # ── Divider ──────────────────────────────────────────────────────
        ctk.CTkFrame(self, fg_color=C["surface_light"], height=1).pack(
            fill="x", padx=24, pady=(4, 4))

        # ── Bottom container (swaps between sessions and stats) ──────────
        self.bottom = ctk.CTkFrame(self, fg_color="transparent")
        self.bottom.pack(fill="both", expand=True, padx=0, pady=0)

        self._build_session_view()

        # ── Today stats bar ──────────────────────────────────────────────
        self.stats_bar = ctk.CTkFrame(self, fg_color=C["surface"], corner_radius=12, height=40)
        self.stats_bar.pack(fill="x", padx=24, pady=(4, 12))
        self.stats_bar.pack_propagate(False)

        self.today_label = ctk.CTkLabel(self.stats_bar, text="", font=("Inter", 11),
                                        text_color=C["text_dim"])
        self.today_label.pack(expand=True)
        self._update_today_stats()

    def _build_ui_compact(self):
        """Horizontal bar layout: time · task · controls · expand."""
        bar = ctk.CTkFrame(self, fg_color=C["surface"], corner_radius=12)
        bar.pack(fill="x", padx=6, pady=(6, 2))

        # Thin progress strip below the bar, colored per session type.
        # Click or drag on it to scrub the timer position.
        self.compact_progress = ctk.CTkProgressBar(
            self, height=8, corner_radius=3,
            fg_color=C["surface"], progress_color=C["work"])
        self.compact_progress.set(0)
        self.compact_progress.pack(fill="x", padx=10, pady=(0, 6))
        self.compact_progress.configure(cursor="sb_h_double_arrow")
        self.compact_progress.bind("<Button-1>", self._seek_from_event)
        self.compact_progress.bind("<B1-Motion>", self._seek_from_event)

        # Mono time label (no ring in bar mode).
        self.compact_time = ctk.CTkLabel(
            bar, text="00:00", font=("JetBrains Mono", 22, "bold"),
            text_color=C["text"])
        self.compact_time.pack(side="left", padx=(12, 6))

        # Progress bar underneath feels cluttered; use a thin accent label
        # (session name or break type) instead.
        self.compact_task = ctk.CTkLabel(
            bar, text="", font=("Inter", 11),
            text_color=C["text_dim"], anchor="w")
        self.compact_task.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.start_btn = ctk.CTkButton(
            bar, text="Start", font=("Inter", 11, "bold"),
            width=56, height=28, corner_radius=14,
            fg_color=C["work"], hover_color=C["work_dim"],
            text_color="#ffffff", command=self._toggle_timer)
        self.start_btn.pack(side="left", padx=2)

        ctk.CTkButton(bar, text="Skip", font=("Inter", 11),
                      width=42, height=28, corner_radius=14,
                      fg_color="transparent", hover_color=C["surface_light"],
                      text_color=C["text_dim"],
                      command=self._skip_session).pack(side="left", padx=2)

        ctk.CTkButton(bar, text="🗖", width=28, height=28, font=("Inter", 11),
                      fg_color="transparent", hover_color=C["surface_light"],
                      text_color=C["text_dim"],
                      command=self._toggle_compact).pack(side="right", padx=(2, 8))

        # Stubs so non-compact code paths don't crash.
        self.ring = None
        self.dur_labels = {}
        self.bottom = None
        self.stats_bar = None
        self.today_label = None
        self.session_scroll = None

    def _build_ui_wide(self):
        """Horizontal split: [pipbar (full height)] | [session stack + controls]."""
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=10, pady=10)

        # Left: pipbar-only column. Canvas resizes to fill vertically.
        left = ctk.CTkFrame(container, fg_color="transparent", width=96)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)

        self.pipbar = PipBar(left, width=80, height=320, cols=1)
        self.pipbar.pack(fill="both", expand=True, padx=4, pady=4)
        self.ring = None
        self.wide_time = None
        self.wide_task = None

        # Keep the canvas dims in sync with the frame as it resizes.
        def _sync_pipbar(event):
            if self.pipbar is not None and self.pipbar.winfo_exists():
                self.pipbar.set_size(event.width, event.height)
                self._update_display()
        self.pipbar.bind("<Configure>", _sync_pipbar)

        # Right: top-bar + session view + task label + controls row at bottom.
        right = ctk.CTkFrame(container, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True, padx=(10, 0))

        right_top = ctk.CTkFrame(right, fg_color="transparent")
        right_top.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(right_top, text="pomo", font=("Inter", 16, "bold"),
                     text_color=C["text"]).pack(side="left", padx=4)
        ctk.CTkButton(right_top, text="🗖", width=28, height=28,
                      font=("Inter", 12),
                      fg_color="transparent", hover_color=C["surface_light"],
                      text_color=C["text_dim"],
                      command=self._cycle_mode).pack(side="right")
        self.sound_btn = ctk.CTkButton(
            right_top, text="🔊" if self.sounds_enabled else "🔇",
            width=28, height=28, font=("Inter", 12),
            fg_color="transparent", hover_color=C["surface_light"],
            text_color=C["text_dim"], command=self._toggle_sounds)
        self.sound_btn.pack(side="right", padx=(0, 2))

        # Controls pinned to the bottom of the right column.
        ctrl = ctk.CTkFrame(right, fg_color="transparent")
        ctrl.pack(side="bottom", fill="x", pady=(6, 0))
        self.start_btn = ctk.CTkButton(
            ctrl, text="Start", font=("Inter", 14, "bold"),
            height=38, corner_radius=19,
            fg_color=C["work"], hover_color=C["work_dim"],
            text_color="#ffffff", command=self._toggle_timer)
        self.start_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))
        ctk.CTkButton(ctrl, text="Reset", font=("Inter", 12),
                      width=60, height=38, corner_radius=19,
                      fg_color=C["surface"], hover_color=C["surface_light"],
                      text_color=C["text_dim"],
                      command=self._reset_timer).pack(side="left", padx=2)
        ctk.CTkButton(ctrl, text="Skip", font=("Inter", 12),
                      width=60, height=38, corner_radius=19,
                      fg_color=C["surface"], hover_color=C["surface_light"],
                      text_color=C["text_dim"],
                      command=self._skip_session).pack(side="left", padx=(2, 0))

        # Current-session label, above the controls.
        self.wide_task = ctk.CTkLabel(
            right, text="", font=("Inter", 12),
            text_color=C["text_dim"], anchor="w")
        self.wide_task.pack(side="bottom", fill="x", pady=(4, 0))

        # Session view fills the remaining space between top bar and controls.
        self.bottom = right
        self._build_session_view()

        # Stubs.
        self.dur_labels = {}
        self.stats_bar = None
        self.today_label = None

    def _cycle_mode(self):
        """full → wide → bar → full."""
        order = ["full", "wide", "bar"]
        self.mode = order[(order.index(self.mode) + 1) % len(order)]
        self._persist_prefs()
        self._apply_mode_geometry()
        for w in self.winfo_children():
            w.destroy()
        self._build_ui()
        self._update_display()

    # Legacy alias — shortcut and resize handler still call this.
    def _toggle_compact(self):
        self._cycle_mode()

    def _toggle_sounds(self):
        self.sounds_enabled = not self.sounds_enabled
        self._persist_prefs()
        if hasattr(self, "sound_btn") and self.sound_btn.winfo_exists():
            self.sound_btn.configure(text="🔊" if self.sounds_enabled else "🔇")

    def _toggle_chain(self):
        self.chain_auto_start = bool(self.chain_var.get())
        self._persist_prefs()

    def _persist_prefs(self):
        prefs = load_json(PREFS_FILE, {})
        prefs["theme"] = self.theme_name
        prefs["chain_auto_start"] = self.chain_auto_start
        prefs["sounds_enabled"] = self.sounds_enabled
        prefs["mode"] = self.mode
        prefs.pop("compact", None)
        save_json(PREFS_FILE, prefs)

    def _dismiss_inline_entry(self, event):
        """Click off an open inline entry to commit it via FocusOut."""
        focused = self.focus_get()
        if focused is None:
            return
        cls = focused.winfo_class()
        if cls not in ("Entry", "CTkEntry", "TEntry"):
            return
        # If the click target is inside the focused entry, don't steal focus.
        target = event.widget
        while target is not None:
            if target is focused:
                return
            try:
                target = target.master
            except Exception:
                break
        self.focus_set()

    def _seek_from_event(self, event):
        """Scrub current session position from a click/drag on the progress bar."""
        if self.total_seconds <= 0:
            return
        widget = event.widget
        width = widget.winfo_width()
        if width <= 1:
            return
        frac = max(0.0, min(1.0, event.x / width))
        # frac = elapsed fraction; remaining = (1 - frac) * total.
        self.remaining_seconds = int(self.total_seconds * (1 - frac))
        self._update_display()

    def _on_window_configure(self, event):
        # Only react to events on the root window itself, not children.
        if event.widget is not self:
            return
        # Debounce: wait until the user finishes dragging before swapping.
        if getattr(self, "_resize_job", None):
            self.after_cancel(self._resize_job)
        h = event.height
        self._resize_job = self.after(120, lambda h=h: self._maybe_swap_mode(h))

    def _maybe_swap_mode(self, h: int):
        self._resize_job = None
        # Height-driven fallback to bar mode when the window gets very short.
        # Only auto-swap between "full" and "bar"; "wide" is opt-in only.
        if self.mode == "full" and h <= 200:
            self.mode = "bar"
            self._persist_prefs()
            self._apply_mode_geometry()
            for w in self.winfo_children():
                w.destroy()
            self._build_ui()
            self._update_display()
        elif self.mode == "bar" and h >= 400:
            self.mode = "full"
            self._persist_prefs()
            self._apply_mode_geometry()
            for w in self.winfo_children():
                w.destroy()
            self._build_ui()
            self._update_display()

    def _bind_shortcuts(self):
        # Space: start/pause. N: add focus. S: add short break. L: add long.
        # U: undo. M: toggle compact. Shortcuts are suppressed while an
        # Entry has focus so they don't fire during inline edits.
        def guard(fn):
            def _go(event):
                focused = self.focus_get()
                cls = focused.winfo_class() if focused else ""
                if cls in ("Entry", "CTkEntry", "TEntry"):
                    return
                fn()
            return _go
        self.bind("<space>", guard(self._toggle_timer))
        for key in ("n", "N"):
            self.bind(key, guard(self._add_session_prompt))
        for key in ("s", "S"):
            self.bind(key, guard(lambda: self._add_break("short_break")))
        for key in ("l", "L"):
            self.bind(key, guard(lambda: self._add_break("long_break")))
        for key in ("u", "U"):
            self.bind(key, guard(self._undo))
        for key in ("m", "M"):
            self.bind(key, guard(self._toggle_compact))

    # ── Session view ─────────────────────────────────────────────────────

    def _build_session_view(self):
        # Header
        self.session_header = ctk.CTkFrame(self.bottom, fg_color="transparent")
        self.session_header.pack(fill="x", padx=24, pady=(4, 0))

        ctk.CTkLabel(self.session_header, text="Sessions", font=("Inter", 14, "bold"),
                     text_color=C["text"]).pack(side="left")

        # Clear: wipe the stack. Tucked next to the label so it's out of the way.
        ctk.CTkButton(self.session_header, text="Clear", width=44, height=22,
                      font=("Inter", 10), corner_radius=11,
                      fg_color="transparent", hover_color=C["surface_light"],
                      text_color=C["text_muted"],
                      command=self._clear_stack).pack(side="left", padx=(8, 0))

        # Undo: restore the previous stack state (add/remove/clear).
        ctk.CTkButton(self.session_header, text="Undo", width=44, height=22,
                      font=("Inter", 10), corner_radius=11,
                      fg_color="transparent", hover_color=C["surface_light"],
                      text_color=C["text_muted"],
                      command=self._undo).pack(side="left", padx=(4, 0))

        # Primary: add a work session (inline name entry, same as before).
        ctk.CTkButton(self.session_header, text="+", width=32, height=28,
                      font=("Inter", 16, "bold"), corner_radius=14,
                      fg_color=C["work"], hover_color=C["work_dim"],
                      text_color="#ffffff",
                      command=self._add_session_prompt).pack(side="right", padx=(4, 0))

        # Secondary: insert a long break at end with default duration.
        ctk.CTkButton(self.session_header, text="L", width=26, height=26,
                      font=("Inter", 11, "bold"), corner_radius=13,
                      fg_color=C["long_break"], hover_color=C["long_break_dim"],
                      text_color="#ffffff",
                      command=lambda: self._add_break("long_break")
                      ).pack(side="right", padx=(4, 0))

        # Secondary: insert a short break at end with default duration.
        ctk.CTkButton(self.session_header, text="S", width=26, height=26,
                      font=("Inter", 11, "bold"), corner_radius=13,
                      fg_color=C["break"], hover_color=C["break_dim"],
                      text_color="#ffffff",
                      command=lambda: self._add_break("short_break")
                      ).pack(side="right", padx=(4, 0))

        # Running-total row: sum of all pending session durations.
        total_row = ctk.CTkFrame(self.bottom, fg_color="transparent")
        total_row.pack(fill="x", padx=24, pady=(2, 0))
        self.total_label = ctk.CTkLabel(total_row, text="", font=("Inter", 10),
                                        text_color=C["text_muted"])
        self.total_label.pack(side="left")

        # Scrollable list
        self.session_scroll = ScrollFrame(self.bottom)
        self.session_scroll.pack(fill="both", expand=True, padx=20, pady=(4, 4))

        # Double-click empty space in the list area to add a new focus session.
        self.session_scroll.canvas.bind(
            "<Double-Button-1>", lambda e: self._add_session_prompt())
        self.session_scroll.inner.bind(
            "<Double-Button-1>", lambda e: self._add_session_prompt())

        # Single-click empty space takes focus away from any open inline
        # entry — triggers its FocusOut → commit/cancel behavior.
        self.session_scroll.canvas.bind(
            "<Button-1>", lambda e: self.focus_set(), add="+")
        self.session_scroll.inner.bind(
            "<Button-1>", lambda e: self.focus_set(), add="+")

        self._rebuild_session_list()

    def _clear_bottom(self):
        for widget in self.bottom.winfo_children():
            widget.destroy()

    # ── View switching ───────────────────────────────────────────────────

    def _show_view(self, view: str):
        if self.bottom is None:  # compact mode has no bottom panel
            return
        self._view = view
        self._clear_bottom()
        if view == "sessions":
            self._build_session_view()
        elif view == "stats":
            self._build_stats_view()
        elif view == "themes":
            self._build_theme_view()
        elif view == "templates":
            self._build_template_view()

    def _toggle_stats(self):
        self._show_view("sessions" if self._view == "stats" else "stats")

    def _toggle_themes(self):
        self._show_view("sessions" if self._view == "themes" else "themes")

    def _toggle_templates(self):
        self._show_view("sessions" if self._view == "templates" else "templates")

    # ── Templates ────────────────────────────────────────────────────────

    def _load_templates(self):
        data = load_json(TEMPLATES_FILE, None)
        slots = [None] * TEMPLATE_SLOTS
        if isinstance(data, list):
            for i, item in enumerate(data[:TEMPLATE_SLOTS]):
                if isinstance(item, dict) and isinstance(item.get("sessions"), list):
                    slots[i] = {
                        "name": item.get("name") or f"Template {i + 1}",
                        "sessions": item["sessions"],
                    }
        return slots

    def _save_templates(self, slots):
        save_json(TEMPLATES_FILE, slots)

    def _save_to_slot(self, slot: int):
        if not self.sessions:
            return
        slots = self._load_templates()
        template_sessions = []
        for s in self.sessions:
            item = {"type": s["type"], "name": s["name"]}
            if s["type"] != "work" and "duration" in s:
                item["duration"] = s["duration"]
            template_sessions.append(item)
        existing_name = slots[slot]["name"] if slots[slot] else f"Template {slot + 1}"
        slots[slot] = {"name": existing_name, "sessions": template_sessions}
        self._save_templates(slots)
        self._build_template_view_rebuild()

    def _load_from_slot(self, slot: int):
        slots = self._load_templates()
        if not slots[slot]:
            return
        self._push_undo()
        new_sessions = []
        for item in slots[slot]["sessions"]:
            t = item.get("type")
            if t not in ("work", "short_break", "long_break"):
                continue
            entry = {"type": t, "name": item.get("name") or "Focus", "done": False}
            if t != "work":
                entry["duration"] = item.get("duration", self.durations[t])
            new_sessions.append(entry)
        self.sessions = new_sessions
        self.current_index = self._first_pending_index()
        if self.current_index >= 0:
            self.session_type = SessionType(self.sessions[self.current_index]["type"])
            self.remaining_seconds = self._current_session_seconds()
            self.total_seconds = self.remaining_seconds
        self._save_sessions()
        self._update_button_color()
        self._show_view("sessions")

    def _delete_slot(self, slot: int):
        slots = self._load_templates()
        slots[slot] = None
        self._save_templates(slots)
        self._build_template_view_rebuild()

    def _rename_slot(self, slot: int, new_name: str):
        slots = self._load_templates()
        if slots[slot]:
            slots[slot]["name"] = new_name.strip() or f"Template {slot + 1}"
            self._save_templates(slots)
            self._build_template_view_rebuild()

    def _build_template_view_rebuild(self):
        if self._view == "templates":
            self._clear_bottom()
            self._build_template_view()

    def _build_template_view(self):
        scroll = ScrollFrame(self.bottom)
        scroll.pack(fill="both", expand=True, padx=20, pady=(4, 4))
        inner = scroll.inner

        header = ctk.CTkFrame(inner, fg_color="transparent")
        header.pack(fill="x", pady=(4, 8), padx=4)
        ctk.CTkLabel(header, text="Templates", font=("Inter", 14, "bold"),
                     text_color=C["text"]).pack(side="left")
        ctk.CTkButton(header, text="← Back", width=60, height=26, font=("Inter", 11),
                      corner_radius=13, fg_color=C["surface"],
                      hover_color=C["surface_light"], text_color=C["text_dim"],
                      command=lambda: self._show_view("sessions")).pack(side="right")

        slots = self._load_templates()
        for i in range(TEMPLATE_SLOTS):
            card = ctk.CTkFrame(inner, fg_color=C["surface"], corner_radius=10)
            card.pack(fill="x", pady=4, padx=4)

            top_row = ctk.CTkFrame(card, fg_color="transparent")
            top_row.pack(fill="x", padx=10, pady=(8, 2))

            slot_data = slots[i]
            if slot_data:
                name_lbl = ctk.CTkLabel(top_row, text=slot_data["name"],
                                        font=("Inter", 13, "bold"),
                                        text_color=C["text"], cursor="xterm")
                name_lbl.pack(side="left")
                name_lbl.bind("<Button-1>",
                              lambda e, s=i, w=name_lbl: self._edit_slot_name(s, w))

                work_n = sum(1 for x in slot_data["sessions"] if x.get("type") == "work")
                break_n = len(slot_data["sessions"]) - work_n
                detail = f"{work_n} focus · {break_n} break{'s' if break_n != 1 else ''}"
                ctk.CTkLabel(top_row, text=detail, font=("Inter", 10),
                             text_color=C["text_muted"]).pack(side="right")
            else:
                ctk.CTkLabel(top_row, text=f"Slot {i + 1}",
                             font=("Inter", 13),
                             text_color=C["text_muted"]).pack(side="left")
                ctk.CTkLabel(top_row, text="empty", font=("Inter", 10),
                             text_color=C["text_muted"]).pack(side="right")

            btn_row = ctk.CTkFrame(card, fg_color="transparent")
            btn_row.pack(fill="x", padx=10, pady=(2, 8))

            ctk.CTkButton(btn_row, text="Save current", height=26,
                          font=("Inter", 11), corner_radius=13,
                          fg_color=C["work"], hover_color=C["work_dim"],
                          text_color="#ffffff",
                          command=lambda s=i: self._save_to_slot(s)
                          ).pack(side="left", padx=(0, 4))

            if slot_data:
                ctk.CTkButton(btn_row, text="Load", height=26,
                              font=("Inter", 11), corner_radius=13,
                              fg_color=C["break"], hover_color=C["break_dim"],
                              text_color="#ffffff",
                              command=lambda s=i: self._load_from_slot(s)
                              ).pack(side="left", padx=(0, 4))
                ctk.CTkButton(btn_row, text="×", width=26, height=26,
                              font=("Inter", 12), corner_radius=13,
                              fg_color="transparent",
                              hover_color=C["surface_light"],
                              text_color=C["text_muted"],
                              command=lambda s=i: self._delete_slot(s)
                              ).pack(side="right")

        scroll.bind_scroll_recursive()

    def _edit_slot_name(self, slot: int, widget):
        current = widget.cget("text")
        parent = widget.master
        entry = ctk.CTkEntry(parent, font=("Inter", 13, "bold"),
                             width=180, height=26,
                             fg_color=C["surface_light"], text_color=C["text"],
                             border_width=1, border_color=C["work"])
        entry.place(in_=widget, x=-4, y=-4)
        entry.insert(0, current)
        entry.focus_set()
        entry.select_range(0, "end")

        closed = {"v": False}

        def close():
            if closed["v"]:
                return
            closed["v"] = True
            try:
                entry.destroy()
            except Exception:
                pass

        def commit(event=None):
            if closed["v"]:
                return
            self._rename_slot(slot, entry.get())
            close()

        def cancel(event=None):
            close()

        entry.bind("<Return>", commit)
        entry.bind("<KP_Enter>", commit)
        entry.bind("<Escape>", cancel)
        entry.bind("<FocusOut>", commit)

    # ── Theme view ───────────────────────────────────────────────────────

    def _build_theme_view(self):
        scroll = ScrollFrame(self.bottom)
        scroll.pack(fill="both", expand=True, padx=20, pady=(4, 4))
        inner = scroll.inner

        header = ctk.CTkFrame(inner, fg_color="transparent")
        header.pack(fill="x", pady=(4, 8), padx=4)
        ctk.CTkLabel(header, text="Theme", font=("Inter", 14, "bold"),
                     text_color=C["text"]).pack(side="left")
        ctk.CTkButton(header, text="← Back", width=60, height=26, font=("Inter", 11),
                      corner_radius=13, fg_color=C["surface"], hover_color=C["surface_light"],
                      text_color=C["text_dim"],
                      command=lambda: self._show_view("sessions")).pack(side="right")

        for name, theme in THEMES.items():
            card = ctk.CTkFrame(inner, fg_color=theme["surface"], corner_radius=10,
                                border_width=2,
                                border_color=theme["work"] if name == self.theme_name else theme["surface"])
            card.pack(fill="x", pady=4, padx=4)

            top_row = ctk.CTkFrame(card, fg_color="transparent")
            top_row.pack(fill="x", padx=10, pady=(8, 4))

            ctk.CTkLabel(top_row, text=name.capitalize(),
                         font=("Inter", 13, "bold"),
                         text_color=theme["text"]).pack(side="left")

            if name == self.theme_name:
                ctk.CTkLabel(top_row, text="✓ active", font=("Inter", 10),
                             text_color=theme["work"]).pack(side="right")
            else:
                ctk.CTkButton(top_row, text="Apply", width=60, height=22,
                              font=("Inter", 10),
                              corner_radius=11,
                              fg_color=theme["work"], hover_color=theme["work_dim"],
                              text_color="#ffffff",
                              command=lambda n=name: self._apply_theme(n)
                              ).pack(side="right")

            # Color swatches
            swatches = ctk.CTkFrame(card, fg_color="transparent")
            swatches.pack(fill="x", padx=10, pady=(0, 10))
            for key in ("work", "break", "long_break", "text", "surface_light"):
                sw = ctk.CTkFrame(swatches, fg_color=theme[key], width=28, height=16,
                                  corner_radius=3)
                sw.pack(side="left", padx=2)
                sw.pack_propagate(False)

        scroll.bind_scroll_recursive()

    def _apply_theme(self, name: str):
        self.theme_name = name
        C.update(THEMES[name])

        # Persist
        prefs = load_json(PREFS_FILE, {})
        prefs["theme"] = name
        save_json(PREFS_FILE, prefs)

        # Rebuild entire UI
        for widget in self.winfo_children():
            widget.destroy()
        self.configure(fg_color=C["bg"])
        self._build_ui()
        self._update_display()
        # Re-enter theme view so user sees the change
        self._show_view("themes")

    def _build_stats_view(self):
        scroll = ScrollFrame(self.bottom)
        scroll.pack(fill="both", expand=True, padx=20, pady=(4, 4))
        inner = scroll.inner

        # Header with back
        header = ctk.CTkFrame(inner, fg_color="transparent")
        header.pack(fill="x", pady=(4, 8), padx=4)
        ctk.CTkLabel(header, text="Stats", font=("Inter", 14, "bold"),
                     text_color=C["text"]).pack(side="left")
        ctk.CTkButton(header, text="← Back", width=60, height=26, font=("Inter", 11),
                      corner_radius=13, fg_color=C["surface"], hover_color=C["surface_light"],
                      text_color=C["text_dim"], command=self._toggle_stats).pack(side="right")

        # Cards
        cards = ctk.CTkFrame(inner, fg_color="transparent")
        cards.pack(fill="x", pady=(0, 8), padx=4)

        total_hrs = self.stats.total_minutes / 60
        items = [
            ("Total sessions", str(self.stats.total_sessions)),
            ("Total focus", f"{total_hrs:.1f}h"),
            ("Today sessions", str(self.stats.today["sessions"])),
            ("Today focus", f"{int(self.stats.today['minutes'])}m"),
        ]
        for i, (label, value) in enumerate(items):
            card = ctk.CTkFrame(cards, fg_color=C["surface"], corner_radius=10)
            card.grid(row=i // 2, column=i % 2, padx=4, pady=4, sticky="nsew")
            cards.grid_columnconfigure(i % 2, weight=1)
            ctk.CTkLabel(card, text=value, font=("Inter", 18, "bold"),
                         text_color=C["text"]).pack(pady=(8, 1))
            ctk.CTkLabel(card, text=label, font=("Inter", 10),
                         text_color=C["text_dim"]).pack(pady=(0, 8))

        # History
        ctk.CTkLabel(inner, text="Recent", font=("Inter", 12, "bold"),
                     text_color=C["text"]).pack(anchor="w", pady=(4, 2), padx=4)

        history = load_json(HISTORY_FILE, [])
        if not history:
            ctk.CTkLabel(inner, text="No sessions yet", font=("Inter", 11),
                         text_color=C["text_muted"]).pack(pady=8, padx=4)
        else:
            for entry in reversed(history[-20:]):
                row = ctk.CTkFrame(inner, fg_color="transparent")
                row.pack(fill="x", pady=1, padx=4)
                ctk.CTkLabel(row, text=f"{entry.get('date', '')} {entry.get('time', '')}",
                             font=("Inter", 10), text_color=C["text_muted"]).pack(side="left")
                ctk.CTkLabel(row, text=f"{entry.get('task', '')} · {entry.get('minutes', 0)}m",
                             font=("Inter", 10), text_color=C["text_dim"]).pack(side="right")

        scroll.bind_scroll_recursive()

    # ── Session queue management ─────────────────────────────────────────

    def _load_sessions(self):
        """Restore last stack template; fresh `done=False` so it's ready to run.

        Empty/missing file → empty stack (user builds it themselves)."""
        data = load_json(SESSIONS_FILE, None)
        if not isinstance(data, list):
            return []
        restored = []
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
            entry = {"type": t, "name": name, "done": False,
                     "duration": item.get("duration", self.durations[t])}
            restored.append(entry)
        return restored

    def _save_sessions(self):
        """Save stack template (type + name + per-item duration) for next run."""
        template = []
        for s in self.sessions:
            item = {"type": s["type"], "name": s["name"]}
            if "duration" in s:
                item["duration"] = s["duration"]
            template.append(item)
        save_json(SESSIONS_FILE, template)

    def _row_drag_start(self, index: int, y_root: int):
        self._drag_src = index
        self._drag_target = index
        # Dim the source row so the user knows which item is moving.
        src_row = self._row_widgets.get(index)
        if src_row is not None:
            src_row.configure(fg_color=C["surface"])

    def _row_drag_motion(self, y_root: int):
        if getattr(self, "_drag_src", None) is None:
            return
        # Find which row's midpoint the cursor is nearest.
        target = self._drag_src
        for idx, row in self._row_widgets.items():
            if self.sessions[idx]["done"] or idx == self.current_index:
                continue
            try:
                top = row.winfo_rooty()
                bot = top + row.winfo_height()
            except Exception:
                continue
            if top <= y_root <= bot:
                target = idx
                break
        if target == self._drag_target:
            return
        self._drag_target = target
        # Refresh highlight: only the target row gets an accent border; the
        # source stays dimmed so you can see both endpoints.
        for idx, row in self._row_widgets.items():
            if idx == self._drag_src:
                row.configure(fg_color=C["surface"], border_width=0)
            elif idx == target:
                row.configure(fg_color=C["surface_light"],
                              border_width=1, border_color=C["work"])
            else:
                row.configure(fg_color="transparent", border_width=0)

    def _row_drag_end(self, y_root: int):
        src = getattr(self, "_drag_src", None)
        tgt = getattr(self, "_drag_target", None)
        self._drag_src = None
        self._drag_target = None
        # Reset all highlights before any rebuild.
        for row in self._row_widgets.values():
            try:
                row.configure(fg_color="transparent", border_width=0)
            except Exception:
                pass
        if src is None or tgt is None or src == tgt:
            return
        if not (0 <= src < len(self.sessions) and 0 <= tgt < len(self.sessions)):
            return
        self._push_undo()
        item = self.sessions.pop(src)
        self.sessions.insert(tgt, item)
        # Keep current_index pointed at the same session after reorder.
        if self.current_index == src:
            self.current_index = tgt
        elif src < self.current_index <= tgt:
            self.current_index -= 1
        elif tgt <= self.current_index < src:
            self.current_index += 1
        self._save_sessions()
        self._rebuild_session_list()
        self._update_display()

    def _update_total_label(self):
        if not hasattr(self, "total_label") or self.total_label is None:
            return
        total_min = 0
        pending = 0
        for s in self.sessions:
            if s["done"]:
                continue
            pending += 1
            if s["type"] == "work":
                total_min += self.durations["work"]
            else:
                total_min += s.get("duration", self.durations[s["type"]])
        if pending == 0:
            self.total_label.configure(text="")
            return
        hrs, mins = divmod(total_min, 60)
        time_str = f"{hrs}h {mins}m" if hrs else f"{mins}m"
        self.total_label.configure(text=f"{pending} pending · {time_str} planned")

    def _begin_rename(self, index: int):
        self._editing_index = index
        self._rebuild_session_list()

    def _build_rename_row(self, parent, index: int, current_name: str):
        row = ctk.CTkFrame(parent, fg_color=C["surface_light"], corner_radius=8,
                           height=36, border_width=1, border_color=C["work"])
        row.pack(fill="x", pady=1, padx=2)
        row.pack_propagate(False)

        entry = ctk.CTkEntry(row, font=("Inter", 13), height=30,
                             fg_color=C["surface_light"],
                             text_color=C["text"], border_width=0)
        entry.insert(0, current_name)
        entry.pack(side="left", fill="x", expand=True, padx=(10, 6), pady=3)
        entry.focus_set()
        entry.select_range(0, "end")

        def commit(event=None):
            new_name = entry.get().strip() or current_name
            self.sessions[index]["name"] = new_name
            self._editing_index = -1
            self._save_sessions()
            self._rebuild_session_list()
            self._update_display()

        def cancel(event=None):
            self._editing_index = -1
            self._rebuild_session_list()

        entry.bind("<Return>", commit)
        entry.bind("<KP_Enter>", commit)
        entry.bind("<Escape>", cancel)
        entry.bind("<FocusOut>", commit)

    def _push_undo(self):
        """Snapshot the current stack so destructive actions can be undone."""
        snapshot = [dict(s) for s in self.sessions]
        self._undo_stack.append((snapshot, self.current_index))
        if len(self._undo_stack) > 20:
            self._undo_stack.pop(0)

    def _undo(self):
        if not self._undo_stack:
            return
        sessions, current_index = self._undo_stack.pop()
        self.sessions = sessions
        self.current_index = current_index
        if 0 <= current_index < len(self.sessions):
            self.session_type = SessionType(self.sessions[current_index]["type"])
            self.remaining_seconds = self._current_session_seconds()
            self.total_seconds = self.remaining_seconds
        self._save_sessions()
        self._update_button_color()
        self._rebuild_session_list()
        self._update_display()

    def _clear_stack(self):
        """Wipe all sessions and stop the timer."""
        self._push_undo()
        if self._tick_id:
            self.after_cancel(self._tick_id)
            self._tick_id = None
        self.timer_state = TimerState.IDLE
        self.sessions = []
        self.current_index = -1
        self.session_type = SessionType.WORK
        self.remaining_seconds = self.durations["work"] * 60
        self.total_seconds = self.remaining_seconds
        self._save_sessions()
        self.start_btn.configure(text="Start")
        self._update_button_color()
        self._rebuild_session_list()
        self._update_display()

    def _first_pending_index(self):
        for i, s in enumerate(self.sessions):
            if not s["done"]:
                return i
        return -1

    def _add_session_prompt(self):
        if self.session_scroll is None:
            return
        if hasattr(self, "_inline_entry") and self._inline_entry is not None:
            try:
                self._inline_entry.focus_set()
                return
            except Exception:
                self._inline_entry = None

        # If the empty-state hint is showing, remove it so the entry is visible.
        if not self.sessions:
            for w in self.session_scroll.inner.winfo_children():
                w.destroy()

        row = ctk.CTkFrame(self.session_scroll.inner, fg_color=C["surface_light"],
                           corner_radius=8, height=42, border_width=1,
                           border_color=C["work"])
        existing = self.session_scroll.inner.winfo_children()
        # Pack at top so it's always visible above the queue.
        if len(existing) > 1:
            row.pack(fill="x", pady=(6, 4), padx=2, before=existing[0])
        else:
            row.pack(fill="x", pady=(6, 4), padx=2)
        row.pack_propagate(False)

        entry = ctk.CTkEntry(
            row, placeholder_text="What's your intent?",
            font=("Inter", 13), height=34,
            fg_color=C["surface_light"], border_color=C["work"],
            text_color=C["text"], placeholder_text_color=C["text_dim"],
            border_width=0)
        entry.pack(side="left", fill="x", expand=True, padx=(10, 6), pady=4)

        # Force scroll to top so the entry is visible.
        self.session_scroll.canvas.yview_moveto(0)

        self._inline_entry = entry
        self._inline_row = row

        def submit(event=None):
            name = entry.get().strip()
            self._inline_entry = None
            self._inline_row = None
            row.destroy()
            if name:
                self._add_session(name)

        def cancel(event=None):
            self._inline_entry = None
            self._inline_row = None
            row.destroy()

        entry.bind("<Return>", submit)
        entry.bind("<KP_Enter>", submit)
        entry.bind("<Escape>", cancel)
        entry.focus_set()

    def _add_session(self, name: str, auto_start: bool = True):
        self._push_undo()
        self.sessions.append({"type": "work", "name": name, "done": False,
                              "duration": self.durations["work"]})
        self._save_sessions()
        if self.current_index == -1:
            self.current_index = len(self.sessions) - 1
            self.session_type = SessionType.WORK
            self.remaining_seconds = self.durations["work"] * 60
            self.total_seconds = self.remaining_seconds
            self._update_button_color()
            if auto_start:
                self._rebuild_session_list()
                self._update_display()
                self._start_timer()
                return
        self._rebuild_session_list()
        self._update_display()

    def _add_break(self, kind: str):
        """kind is 'short_break' or 'long_break'. Duration snapshots current default."""
        self._push_undo()
        label = "Short Break" if kind == "short_break" else "Long Break"
        self.sessions.append({"type": kind, "name": label, "done": False,
                              "duration": self.durations[kind]})
        self._save_sessions()
        if self.current_index == -1:
            self.current_index = len(self.sessions) - 1
            self.session_type = SessionType(kind)
            self.remaining_seconds = self.durations[kind] * 60
            self.total_seconds = self.remaining_seconds
            self._update_button_color()
        self._rebuild_session_list()
        self._update_display()

    def _adjust_session_duration(self, index: int, delta, widget=None):
        """delta is int minutes, or the string "set" to open inline edit on `widget`.

        Works on any session type (work/short/long). If the session is currently
        active, the new duration is applied live so remaining time updates.
        """
        if not (0 <= index < len(self.sessions)):
            return
        s = self.sessions[index]
        t = s["type"]
        current = s.get("duration", self.durations[t])
        if delta == "set":
            if widget is None:
                return
            accent = (C["work"] if t == "work"
                      else C["break"] if t == "short_break"
                      else C["long_break"])
            self._inline_edit_on(widget, initial=str(current), accent=accent,
                                 on_commit=lambda v, i=index: self._set_session_duration(i, v))
            return
        self._set_session_duration(index, max(1, current + delta))

    def _set_session_duration(self, index: int, val: int):
        if not (0 <= index < len(self.sessions)):
            return
        s = self.sessions[index]
        s["duration"] = val
        # Apply live if this is the session currently running/ready.
        if index == self.current_index:
            new_total = val * 60
            elapsed = max(0, self.total_seconds - self.remaining_seconds)
            if elapsed >= new_total:
                self.remaining_seconds = 0
            else:
                self.remaining_seconds = new_total - elapsed
            self.total_seconds = new_total
            self._update_display()
        self._save_sessions()
        # Patch the single row rather than rebuilding the whole list — avoids
        # the flash on every +/- click.
        row = self._row_widgets.get(index) if hasattr(self, "_row_widgets") else None
        dur_lbl = getattr(row, "dur_lbl", None) if row is not None else None
        if dur_lbl is not None and dur_lbl.winfo_exists():
            dur_lbl.configure(text=f"{val}m")
            self._update_total_label()
        else:
            self._rebuild_session_list()

    def _remove_session(self, index: int):
        if index < len(self.sessions):
            self._push_undo()
            self.sessions.pop(index)
            self._save_sessions()
            if len(self.sessions) == 0:
                self.current_index = -1
            elif index < self.current_index:
                self.current_index -= 1
            elif index == self.current_index:
                if self.current_index >= len(self.sessions):
                    self.current_index = len(self.sessions) - 1
                found = False
                for i in range(self.current_index, len(self.sessions)):
                    if not self.sessions[i]["done"]:
                        self.current_index = i
                        found = True
                        break
                if not found:
                    self.current_index = -1
            self._rebuild_session_list()
            self._update_display()

    def _rebuild_session_list(self):
        if self.session_scroll is None:
            return
        self._update_total_label()
        self.session_scroll.clear()
        inner = self.session_scroll.inner

        if not self.sessions:
            ctk.CTkLabel(inner, text="Add focus blocks and breaks with the buttons above",
                         font=("Inter", 12), text_color=C["text_muted"],
                         wraplength=280).pack(pady=20)
            return

        self._row_widgets = {}
        for i, session in enumerate(self.sessions):
            if i == self._editing_index and session["type"] == "work":
                self._build_rename_row(inner, i, session["name"])
                continue
            duration = session.get("duration", self.durations[session["type"]])
            row = SessionRow(inner, name=session["name"], index=i,
                             session_type=session["type"],
                             is_active=(i == self.current_index),
                             is_done=session["done"],
                             duration=duration,
                             on_remove=lambda idx=i: self._remove_session(idx),
                             on_duration_change=lambda delta, widget=None, idx=i: self._adjust_session_duration(idx, delta, widget),
                             on_rename=lambda idx=i: self._begin_rename(idx),
                             on_drag_start=self._row_drag_start,
                             on_drag_motion=self._row_drag_motion,
                             on_drag_end=self._row_drag_end,
                             )
            row.pack(fill="x", pady=0)
            self._row_widgets[i] = row

        self.session_scroll.bind_scroll_recursive()

    # ── Timer logic ──────────────────────────────────────────────────────

    def _toggle_timer(self):
        if self.timer_state == TimerState.RUNNING:
            self._pause_timer()
        else:
            self._start_timer()

    def _drag_start(self, event, key):
        self._drag_key = key
        self._drag_y = event.y_root
        self._drag_accum = 0

    def _drag_motion(self, event):
        if not hasattr(self, "_drag_key") or self._drag_key is None:
            return
        dy = self._drag_y - event.y_root
        self._drag_accum += dy
        self._drag_y = event.y_root
        steps = int(self._drag_accum / 8)
        if steps != 0:
            self._drag_accum -= steps * 8
            self._adjust_duration(self._drag_key, steps)

    def _drag_end(self, event):
        self._drag_key = None

    def _prompt_duration(self, key: str, label: str):
        """Overlay an inline entry on the global duration label."""
        dur_lbl = self.dur_labels[key]
        color = dur_lbl.cget("text_color")
        self._inline_edit_on(
            dur_lbl, initial=str(self.durations[key]), accent=color,
            on_commit=lambda v: self._set_global_duration(key, v))

    def _set_global_duration(self, key: str, val: int):
        self.durations[key] = val
        self._update_dur_labels()
        if self.timer_state == TimerState.IDLE:
            type_map = {"work": SessionType.WORK,
                        "short_break": SessionType.SHORT_BREAK,
                        "long_break": SessionType.LONG_BREAK}
            if self.session_type == type_map[key]:
                self.remaining_seconds = self._current_session_seconds()
                self.total_seconds = self.remaining_seconds
                self._update_display()

    def _inline_edit_on(self, widget, initial: str, accent: str, on_commit):
        """Overlay a short numeric entry on top of `widget` via .place()."""
        parent = widget.master
        entry = ctk.CTkEntry(parent, font=("Inter", 12, "bold"),
                             width=60, height=26,
                             fg_color=C["surface_light"], text_color=accent,
                             border_width=1, border_color=accent, justify="center")
        entry.place(in_=widget, x=-12, y=-4)
        entry.insert(0, initial)
        entry.focus_set()
        entry.select_range(0, "end")

        state = {"closed": False}

        def close():
            if state["closed"]:
                return
            state["closed"] = True
            try:
                entry.destroy()
            except Exception:
                pass

        def commit(event=None):
            if state["closed"]:
                return
            try:
                val = max(1, min(600, int(entry.get().strip())))
                on_commit(val)
            except ValueError:
                pass
            close()

        def cancel(event=None):
            close()

        entry.bind("<Return>", commit)
        entry.bind("<KP_Enter>", commit)
        entry.bind("<Escape>", cancel)
        entry.bind("<FocusOut>", commit)

    def _adjust_duration(self, key: str, delta: int):
        self.durations[key] = max(1, self.durations[key] + delta)
        self._update_dur_labels()
        if self.timer_state == TimerState.IDLE:
            type_map = {"work": SessionType.WORK, "short_break": SessionType.SHORT_BREAK,
                        "long_break": SessionType.LONG_BREAK}
            if self.session_type == type_map[key]:
                self.remaining_seconds = self.durations[key] * 60
                self.total_seconds = self.remaining_seconds
                self._update_display()

    def _update_dur_labels(self):
        if not self.dur_labels:
            return
        self.dur_labels["work"].configure(text=f"{self.durations['work']}m")
        self.dur_labels["short_break"].configure(text=f"{self.durations['short_break']}m")
        self.dur_labels["long_break"].configure(text=f"{self.durations['long_break']}m")

    def _start_timer(self):
        self.timer_state = TimerState.RUNNING
        self.start_btn.configure(text="Pause")
        self._tick()

    def _pause_timer(self):
        self.timer_state = TimerState.PAUSED
        self.start_btn.configure(text="Resume")
        if self._tick_id:
            self.after_cancel(self._tick_id)
            self._tick_id = None

    def _reset_timer(self):
        self.timer_state = TimerState.IDLE
        if self._tick_id:
            self.after_cancel(self._tick_id)
            self._tick_id = None
        self.remaining_seconds = self._current_session_seconds()
        self.total_seconds = self.remaining_seconds
        self.start_btn.configure(text="Start")
        self._update_display()

    def _current_session_seconds(self):
        """Duration of the currently-selected session in seconds."""
        if 0 <= self.current_index < len(self.sessions):
            s = self.sessions[self.current_index]
            return s.get("duration", self.durations[s["type"]]) * 60
        return self.durations[self.session_type.value] * 60

    def _skip_session(self):
        if self._tick_id:
            self.after_cancel(self._tick_id)
            self._tick_id = None
        self._session_complete()

    def _tick(self):
        if self.timer_state != TimerState.RUNNING:
            return
        self.remaining_seconds -= 1
        if self.remaining_seconds <= 0:
            self.remaining_seconds = 0
            self._update_display()
            self._session_complete()
            return
        self._update_display()
        self._tick_id = self.after(1000, self._tick)

    def _session_complete(self):
        self.timer_state = TimerState.IDLE
        self.start_btn.configure(text="Start")

        completed_type = None
        if 0 <= self.current_index < len(self.sessions):
            cur = self.sessions[self.current_index]
            cur["done"] = True
            completed_type = cur["type"]
            if completed_type == "work":
                self.stats.record_session(self.durations["work"], cur["name"])
                self._update_today_stats()
                notify("Pomo", f"Done: {cur['name']}")
                self.sounds.play("work", enabled=self.sounds_enabled)
            else:
                notify("Pomo", "Break's over — time to focus!")
                self.sounds.play("break", enabled=self.sounds_enabled)

        # After work, always chain into the next item (usually a break).
        # After a break, chain only if the user opted in.
        auto = completed_type == "work" or (
            completed_type in ("short_break", "long_break") and self.chain_auto_start)
        self._advance_to_next(auto_start=auto)

    def _advance_to_next(self, auto_start: bool = False):
        next_idx = -1
        for i in range(len(self.sessions)):
            if not self.sessions[i]["done"]:
                next_idx = i
                break

        self.current_index = next_idx
        if next_idx >= 0:
            self.session_type = SessionType(self.sessions[next_idx]["type"])
        else:
            self.session_type = SessionType.WORK
        self.remaining_seconds = self._current_session_seconds()
        self.total_seconds = self.remaining_seconds
        self.timer_state = TimerState.IDLE
        self.start_btn.configure(text="Start")

        self._rebuild_session_list()
        self._update_display()
        self._update_button_color()

        if auto_start and next_idx >= 0:
            self._start_timer()

    def _update_button_color(self):
        if self.session_type == SessionType.WORK:
            self.start_btn.configure(fg_color=C["work"], hover_color=C["work_dim"])
        elif self.session_type == SessionType.SHORT_BREAK:
            self.start_btn.configure(fg_color=C["break"], hover_color=C["break_dim"])
        else:
            self.start_btn.configure(fg_color=C["long_break"], hover_color=C["long_break_dim"])

    # ── Display ──────────────────────────────────────────────────────────

    def _update_display(self):
        progress = self.remaining_seconds / self.total_seconds if self.total_seconds else 0
        mins = self.remaining_seconds // 60
        secs = self.remaining_seconds % 60
        time_text = f"{mins:02d}:{secs:02d}"

        if self.session_type == SessionType.WORK and 0 <= self.current_index < len(self.sessions):
            label = self.sessions[self.current_index]["name"]
            if len(label) > 24:
                label = label[:22] + "…"
            color, dim = C["work"], C["work_dim"]
        elif self.session_type == SessionType.SHORT_BREAK:
            label = "Short Break"
            color, dim = C["break"], C["break_dim"]
        elif self.session_type == SessionType.LONG_BREAK:
            label = "Long Break"
            color, dim = C["long_break"], C["long_break_dim"]
        else:
            label = "Focus"
            color, dim = C["work"], C["work_dim"]

        if self.ring is not None:
            self.ring.draw(progress, time_text, label, color, dim)
        if getattr(self, "pipbar", None) is not None:
            self.pipbar.draw(self.total_seconds, self.remaining_seconds,
                             time_text, color, dim)
        if getattr(self, "wide_task", None) is not None:
            self.wide_task.configure(text=label, text_color=color)
        if getattr(self, "compact_time", None) is not None:
            self.compact_time.configure(text=time_text, text_color=color)
            self.compact_task.configure(text=label)
        if getattr(self, "compact_progress", None) is not None:
            # Progress = elapsed fraction, so the bar fills over the session.
            elapsed = 1 - progress
            self.compact_progress.set(max(0, min(1, elapsed)))
            self.compact_progress.configure(progress_color=color)

    def _update_today_stats(self):
        if self.today_label is None:
            return
        today = self.stats.today
        sessions = today["sessions"]
        minutes = int(today["minutes"])
        hrs = minutes // 60
        mins = minutes % 60
        time_str = f"{hrs}h {mins}m" if hrs else f"{mins}m"
        self.today_label.configure(
            text=f"Today:  {sessions} session{'s' if sessions != 1 else ''}  ·  {time_str} focused")


# ── Entry point ──────────────────────────────────────────────────────────────

def main():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    PomoApp().mainloop()


if __name__ == "__main__":
    main()
