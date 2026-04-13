#!/usr/bin/env python3
"""Pomo — A clean pomodoro timer with task tracking and stats."""

import json
import math
import os
import sys
import time
from datetime import date, datetime
from enum import Enum
from pathlib import Path

import customtkinter as ctk
from PIL import Image, ImageDraw

try:
    from plyer import notification as plyer_notify
except ImportError:
    plyer_notify = None


# ── Paths ────────────────────────────────────────────────────────────────────

DATA_DIR = Path(os.environ.get("POMO_DATA_DIR", Path.home() / ".local" / "share" / "pomo"))
STATS_FILE = DATA_DIR / "stats.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
HISTORY_FILE = DATA_DIR / "history.json"


# ── Defaults ─────────────────────────────────────────────────────────────────

DEFAULT_SETTINGS = {
    "work_minutes": 25,
    "short_break_minutes": 5,
    "long_break_minutes": 15,
    "sessions_before_long_break": 4,
    "auto_start_breaks": True,
    "auto_start_work": False,
    "sound_enabled": True,
}


# ── Persistence helpers ──────────────────────────────────────────────────────

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


# ── Timer state ──────────────────────────────────────────────────────────────

class SessionType(Enum):
    WORK = "work"
    SHORT_BREAK = "short_break"
    LONG_BREAK = "long_break"


class TimerState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"


# ── Color palette ────────────────────────────────────────────────────────────

COLORS = {
    "bg": "#1a1a2e",
    "surface": "#16213e",
    "surface_light": "#1f3056",
    "work": "#e94560",
    "work_dim": "#8b2a3a",
    "short_break": "#0f9b58",
    "short_break_dim": "#0a6b3d",
    "long_break": "#4a90d9",
    "long_break_dim": "#2d5a8a",
    "text": "#eaeaea",
    "text_dim": "#8892a0",
    "text_muted": "#5a6474",
    "accent": "#e94560",
}

SESSION_COLORS = {
    SessionType.WORK: (COLORS["work"], COLORS["work_dim"]),
    SessionType.SHORT_BREAK: (COLORS["short_break"], COLORS["short_break_dim"]),
    SessionType.LONG_BREAK: (COLORS["long_break"], COLORS["long_break_dim"]),
}

SESSION_LABELS = {
    SessionType.WORK: "Focus",
    SessionType.SHORT_BREAK: "Short Break",
    SessionType.LONG_BREAK: "Long Break",
}


# ── Notifications ────────────────────────────────────────────────────────────

def notify(title: str, message: str):
    if plyer_notify is None:
        return
    try:
        plyer_notify.notify(
            title=title,
            message=message,
            app_name="Pomo",
            timeout=10,
        )
    except Exception:
        pass


# ── Ring canvas (circular progress) ─────────────────────────────────────────

class RingCanvas(ctk.CTkCanvas):
    """Draws a circular progress ring with a time display in the center."""

    def __init__(self, master, size=280, ring_width=10, **kwargs):
        super().__init__(
            master,
            width=size,
            height=size,
            bg=COLORS["bg"],
            highlightthickness=0,
            **kwargs,
        )
        self.size = size
        self.ring_width = ring_width
        self.progress = 1.0
        self.color = COLORS["work"]
        self.dim_color = COLORS["work_dim"]
        self.time_text = "25:00"
        self.label_text = "Focus"

    def set_progress(self, progress: float, time_text: str, label_text: str,
                     color: str, dim_color: str):
        self.progress = max(0.0, min(1.0, progress))
        self.time_text = time_text
        self.label_text = label_text
        self.color = color
        self.dim_color = dim_color
        self.redraw()

    def redraw(self):
        self.delete("all")
        cx = self.size / 2
        cy = self.size / 2
        r = (self.size / 2) - self.ring_width - 4
        pad = self.ring_width / 2

        # Background ring
        self.create_oval(
            cx - r - pad, cy - r - pad,
            cx + r + pad, cy + r + pad,
            outline=self.dim_color,
            width=self.ring_width,
        )

        # Progress arc
        if self.progress > 0.001:
            start = 90
            extent = -360 * self.progress
            self.create_arc(
                cx - r - pad, cy - r - pad,
                cx + r + pad, cy + r + pad,
                start=start,
                extent=extent,
                outline=self.color,
                width=self.ring_width,
                style="arc",
            )

        # Time text
        self.create_text(
            cx, cy - 8,
            text=self.time_text,
            fill=COLORS["text"],
            font=("JetBrains Mono", 42, "bold"),
        )

        # Label
        self.create_text(
            cx, cy + 34,
            text=self.label_text,
            fill=COLORS["text_dim"],
            font=("Inter", 14),
        )


# ── Session dot indicators ──────────────────────────────────────────────────

class SessionDots(ctk.CTkFrame):
    """Shows completed/remaining session dots."""

    def __init__(self, master, total=4, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.total = total
        self.completed = 0
        self.dots = []
        self._build()

    def _build(self):
        for w in self.dots:
            w.destroy()
        self.dots.clear()
        for i in range(self.total):
            dot = ctk.CTkLabel(
                self,
                text="●" if i < self.completed else "○",
                font=("Inter", 16),
                text_color=COLORS["work"] if i < self.completed else COLORS["text_muted"],
                fg_color="transparent",
            )
            dot.pack(side="left", padx=4)
            self.dots.append(dot)

    def set_state(self, completed: int, total: int):
        if completed != self.completed or total != self.total:
            self.completed = completed
            self.total = total
            self._build()


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

        # Also append to history
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


# ── Main app ─────────────────────────────────────────────────────────────────

class PomoApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # ── Settings & state ─────────────────────────────────────────────
        self.settings = {**DEFAULT_SETTINGS, **load_json(SETTINGS_FILE)}
        self.stats = Stats()
        self.timer_state = TimerState.IDLE
        self.session_type = SessionType.WORK
        self.completed_sessions = 0
        self.remaining_seconds = self._session_seconds()
        self.total_seconds = self.remaining_seconds
        self._tick_id = None

        # ── Window ───────────────────────────────────────────────────────
        self.title("Pomo")
        self.configure(fg_color=COLORS["bg"])
        self.geometry("380x620")
        self.minsize(340, 580)
        self.resizable(True, True)

        # ── Layout ───────────────────────────────────────────────────────
        self._build_ui()
        self._update_display()

    # ── UI construction ──────────────────────────────────────────────────

    def _build_ui(self):
        # Top bar with settings gear
        top_bar = ctk.CTkFrame(self, fg_color="transparent", height=40)
        top_bar.pack(fill="x", padx=16, pady=(12, 0))

        self.title_label = ctk.CTkLabel(
            top_bar, text="pomo", font=("Inter", 20, "bold"),
            text_color=COLORS["text"],
        )
        self.title_label.pack(side="left")

        self.settings_btn = ctk.CTkButton(
            top_bar, text="⚙", width=36, height=36,
            font=("Inter", 18),
            fg_color="transparent", hover_color=COLORS["surface_light"],
            text_color=COLORS["text_dim"],
            command=self._open_settings,
        )
        self.settings_btn.pack(side="right")

        self.stats_btn = ctk.CTkButton(
            top_bar, text="📊", width=36, height=36,
            font=("Inter", 16),
            fg_color="transparent", hover_color=COLORS["surface_light"],
            text_color=COLORS["text_dim"],
            command=self._open_stats,
        )
        self.stats_btn.pack(side="right", padx=(0, 4))

        # Session type selector
        type_frame = ctk.CTkFrame(self, fg_color="transparent")
        type_frame.pack(pady=(16, 8))

        self.type_buttons = {}
        for stype in SessionType:
            color, _ = SESSION_COLORS[stype]
            btn = ctk.CTkButton(
                type_frame,
                text=SESSION_LABELS[stype],
                font=("Inter", 13),
                width=100, height=30,
                corner_radius=15,
                fg_color=COLORS["surface"] if stype != self.session_type else color,
                hover_color=color,
                text_color=COLORS["text"],
                command=lambda s=stype: self._switch_session(s),
            )
            btn.pack(side="left", padx=4)
            self.type_buttons[stype] = btn

        # Ring timer
        self.ring = RingCanvas(self, size=280)
        self.ring.pack(pady=(12, 8))

        # Session dots
        self.dots = SessionDots(self, total=self.settings["sessions_before_long_break"])
        self.dots.pack(pady=(0, 12))

        # Task entry
        task_frame = ctk.CTkFrame(self, fg_color="transparent")
        task_frame.pack(fill="x", padx=32, pady=(0, 16))

        self.task_entry = ctk.CTkEntry(
            task_frame,
            placeholder_text="What are you working on?",
            font=("Inter", 13),
            height=38,
            fg_color=COLORS["surface"],
            border_color=COLORS["surface_light"],
            text_color=COLORS["text"],
            placeholder_text_color=COLORS["text_muted"],
        )
        self.task_entry.pack(fill="x")

        # Control buttons
        ctrl_frame = ctk.CTkFrame(self, fg_color="transparent")
        ctrl_frame.pack(pady=(0, 8))

        self.start_btn = ctk.CTkButton(
            ctrl_frame,
            text="Start",
            font=("Inter", 16, "bold"),
            width=140, height=44,
            corner_radius=22,
            fg_color=COLORS["work"],
            hover_color=COLORS["work_dim"],
            text_color="#ffffff",
            command=self._toggle_timer,
        )
        self.start_btn.pack(side="left", padx=6)

        self.reset_btn = ctk.CTkButton(
            ctrl_frame,
            text="Reset",
            font=("Inter", 14),
            width=80, height=44,
            corner_radius=22,
            fg_color=COLORS["surface"],
            hover_color=COLORS["surface_light"],
            text_color=COLORS["text_dim"],
            command=self._reset_timer,
        )
        self.reset_btn.pack(side="left", padx=6)

        self.skip_btn = ctk.CTkButton(
            ctrl_frame,
            text="Skip",
            font=("Inter", 14),
            width=70, height=44,
            corner_radius=22,
            fg_color=COLORS["surface"],
            hover_color=COLORS["surface_light"],
            text_color=COLORS["text_dim"],
            command=self._skip_session,
        )
        self.skip_btn.pack(side="left", padx=6)

        # Today's stats bar
        stats_bar = ctk.CTkFrame(self, fg_color=COLORS["surface"], corner_radius=12, height=48)
        stats_bar.pack(fill="x", padx=24, pady=(8, 16))
        stats_bar.pack_propagate(False)

        self.today_label = ctk.CTkLabel(
            stats_bar, text="", font=("Inter", 12),
            text_color=COLORS["text_dim"],
        )
        self.today_label.pack(expand=True)

        self._update_today_stats()

    # ── Timer logic ──────────────────────────────────────────────────────

    def _session_seconds(self):
        key = {
            SessionType.WORK: "work_minutes",
            SessionType.SHORT_BREAK: "short_break_minutes",
            SessionType.LONG_BREAK: "long_break_minutes",
        }[self.session_type]
        return self.settings[key] * 60

    def _toggle_timer(self):
        if self.timer_state == TimerState.RUNNING:
            self._pause_timer()
        else:
            self._start_timer()

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
        self.remaining_seconds = self._session_seconds()
        self.total_seconds = self.remaining_seconds
        self.start_btn.configure(text="Start")
        self._update_display()

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

        if self.session_type == SessionType.WORK:
            # Record stats
            minutes = self.total_seconds / 60
            task = self.task_entry.get().strip() or "Untitled"
            self.stats.record_session(minutes, task)
            self.completed_sessions += 1
            self._update_today_stats()

            notify("Pomo", f"Focus session complete! ({task})")

            # Decide next session
            if self.completed_sessions % self.settings["sessions_before_long_break"] == 0:
                self._switch_session(SessionType.LONG_BREAK)
            else:
                self._switch_session(SessionType.SHORT_BREAK)

            if self.settings["auto_start_breaks"]:
                self._start_timer()
        else:
            notify("Pomo", "Break's over — time to focus!")
            self._switch_session(SessionType.WORK)

            if self.settings["auto_start_work"]:
                self._start_timer()

    def _switch_session(self, session_type: SessionType):
        was_running = self.timer_state == TimerState.RUNNING
        if was_running and self._tick_id:
            self.after_cancel(self._tick_id)
            self._tick_id = None

        self.session_type = session_type
        self.timer_state = TimerState.IDLE
        self.remaining_seconds = self._session_seconds()
        self.total_seconds = self.remaining_seconds
        self.start_btn.configure(text="Start")

        # Update button styles
        for stype, btn in self.type_buttons.items():
            color, _ = SESSION_COLORS[stype]
            btn.configure(
                fg_color=color if stype == session_type else COLORS["surface"],
            )

        # Update start button color
        color, dim = SESSION_COLORS[session_type]
        self.start_btn.configure(fg_color=color, hover_color=dim)

        self._update_display()

    # ── Display ──────────────────────────────────────────────────────────

    def _update_display(self):
        progress = self.remaining_seconds / self.total_seconds if self.total_seconds else 0
        mins = self.remaining_seconds // 60
        secs = self.remaining_seconds % 60
        time_text = f"{mins:02d}:{secs:02d}"
        label = SESSION_LABELS[self.session_type]
        color, dim = SESSION_COLORS[self.session_type]

        self.ring.set_progress(progress, time_text, label, color, dim)
        self.dots.set_state(
            self.completed_sessions % self.settings["sessions_before_long_break"],
            self.settings["sessions_before_long_break"],
        )

    def _update_today_stats(self):
        today = self.stats.today
        sessions = today["sessions"]
        minutes = int(today["minutes"])
        hrs = minutes // 60
        mins = minutes % 60
        time_str = f"{hrs}h {mins}m" if hrs else f"{mins}m"
        self.today_label.configure(
            text=f"Today:  {sessions} session{'s' if sessions != 1 else ''}  ·  {time_str} focused"
        )

    # ── Settings dialog ──────────────────────────────────────────────────

    def _open_settings(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Settings")
        dialog.geometry("320x420")
        dialog.configure(fg_color=COLORS["bg"])
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        ctk.CTkLabel(
            dialog, text="Settings", font=("Inter", 18, "bold"),
            text_color=COLORS["text"],
        ).pack(pady=(16, 12))

        entries = {}
        fields = [
            ("Work (minutes)", "work_minutes"),
            ("Short break (minutes)", "short_break_minutes"),
            ("Long break (minutes)", "long_break_minutes"),
            ("Sessions before long break", "sessions_before_long_break"),
        ]

        for label, key in fields:
            frame = ctk.CTkFrame(dialog, fg_color="transparent")
            frame.pack(fill="x", padx=24, pady=4)
            ctk.CTkLabel(
                frame, text=label, font=("Inter", 12),
                text_color=COLORS["text_dim"],
            ).pack(anchor="w")
            entry = ctk.CTkEntry(
                frame, font=("Inter", 13), height=34,
                fg_color=COLORS["surface"], border_color=COLORS["surface_light"],
                text_color=COLORS["text"],
            )
            entry.insert(0, str(self.settings[key]))
            entry.pack(fill="x", pady=(2, 0))
            entries[key] = entry

        # Toggles
        toggles = {}
        toggle_fields = [
            ("Auto-start breaks", "auto_start_breaks"),
            ("Auto-start work", "auto_start_work"),
        ]
        for label, key in toggle_fields:
            frame = ctk.CTkFrame(dialog, fg_color="transparent")
            frame.pack(fill="x", padx=24, pady=4)
            var = ctk.BooleanVar(value=self.settings[key])
            sw = ctk.CTkSwitch(
                frame, text=label, font=("Inter", 12),
                text_color=COLORS["text_dim"],
                variable=var,
                progress_color=COLORS["accent"],
            )
            sw.pack(anchor="w")
            toggles[key] = var

        def save():
            for key, entry in entries.items():
                try:
                    val = int(entry.get())
                    if val > 0:
                        self.settings[key] = val
                except ValueError:
                    pass
            for key, var in toggles.items():
                self.settings[key] = var.get()
            save_json(SETTINGS_FILE, self.settings)
            self._reset_timer()
            self.dots.set_state(
                self.completed_sessions % self.settings["sessions_before_long_break"],
                self.settings["sessions_before_long_break"],
            )
            dialog.destroy()

        ctk.CTkButton(
            dialog, text="Save", font=("Inter", 14, "bold"),
            width=120, height=38, corner_radius=19,
            fg_color=COLORS["accent"], hover_color=COLORS["work_dim"],
            text_color="#ffffff",
            command=save,
        ).pack(pady=(16, 12))

    # ── Stats dialog ─────────────────────────────────────────────────────

    def _open_stats(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Stats")
        dialog.geometry("360x400")
        dialog.configure(fg_color=COLORS["bg"])
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        ctk.CTkLabel(
            dialog, text="Stats", font=("Inter", 18, "bold"),
            text_color=COLORS["text"],
        ).pack(pady=(16, 12))

        # Summary cards
        cards_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        cards_frame.pack(fill="x", padx=24, pady=8)

        total_hrs = self.stats.total_minutes / 60
        stats_items = [
            ("Total sessions", str(self.stats.total_sessions)),
            ("Total focus time", f"{total_hrs:.1f} hours"),
            ("Today sessions", str(self.stats.today["sessions"])),
            ("Today focus", f"{int(self.stats.today['minutes'])} min"),
        ]

        for i, (label, value) in enumerate(stats_items):
            card = ctk.CTkFrame(cards_frame, fg_color=COLORS["surface"], corner_radius=10)
            card.grid(row=i // 2, column=i % 2, padx=6, pady=6, sticky="nsew")
            cards_frame.grid_columnconfigure(i % 2, weight=1)
            ctk.CTkLabel(
                card, text=value, font=("Inter", 22, "bold"),
                text_color=COLORS["text"],
            ).pack(pady=(12, 2))
            ctk.CTkLabel(
                card, text=label, font=("Inter", 11),
                text_color=COLORS["text_dim"],
            ).pack(pady=(0, 12))

        # Recent history
        ctk.CTkLabel(
            dialog, text="Recent Sessions", font=("Inter", 14, "bold"),
            text_color=COLORS["text"],
        ).pack(pady=(12, 4), padx=24, anchor="w")

        history_frame = ctk.CTkScrollableFrame(
            dialog, fg_color=COLORS["surface"], corner_radius=10,
            height=140,
        )
        history_frame.pack(fill="x", padx=24, pady=(0, 16))

        history = load_json(HISTORY_FILE, [])
        for entry in reversed(history[-20:]):
            row = ctk.CTkFrame(history_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(
                row, text=f"{entry.get('date', '')} {entry.get('time', '')}",
                font=("Inter", 11), text_color=COLORS["text_muted"],
            ).pack(side="left")
            ctk.CTkLabel(
                row,
                text=f"{entry.get('task', 'Untitled')} · {entry.get('minutes', 0)}m",
                font=("Inter", 11), text_color=COLORS["text_dim"],
            ).pack(side="right")


# ── Entry point ──────────────────────────────────────────────────────────────

def main():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    app = PomoApp()
    app.mainloop()


if __name__ == "__main__":
    main()
