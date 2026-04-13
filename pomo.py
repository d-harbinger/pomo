#!/usr/bin/env python3
"""Pomo — A clean pomodoro timer with named session planning."""

import json
import os
from datetime import date, datetime
from enum import Enum
from pathlib import Path

import customtkinter as ctk

try:
    from plyer import notification as plyer_notify
except ImportError:
    plyer_notify = None


# ── Paths ────────────────────────────────────────────────────────────────────

DATA_DIR = Path(os.environ.get("POMO_DATA_DIR", Path.home() / ".local" / "share" / "pomo"))
STATS_FILE = DATA_DIR / "stats.json"
HISTORY_FILE = DATA_DIR / "history.json"

DEFAULT_WORK = 25
DEFAULT_SHORT_BREAK = 5
DEFAULT_LONG_BREAK = 15
LONG_BREAK_EVERY = 4


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


# ── Colors ───────────────────────────────────────────────────────────────────

C = {
    "bg": "#1a1a2e",
    "surface": "#16213e",
    "surface_light": "#1f3056",
    "work": "#e94560",
    "work_dim": "#8b2a3a",
    "break": "#0f9b58",
    "break_dim": "#0a6b3d",
    "long_break": "#4a90d9",
    "long_break_dim": "#2d5a8a",
    "text": "#eaeaea",
    "text_dim": "#8892a0",
    "text_muted": "#5a6474",
    "done": "#3a4a5a",
    "done_text": "#6a7a8a",
}


# ── Notifications ────────────────────────────────────────────────────────────

def notify(title: str, message: str):
    if plyer_notify is None:
        return
    try:
        plyer_notify.notify(title=title, message=message, app_name="Pomo", timeout=10)
    except Exception:
        pass


# ── Scroll fix for Linux ────────────────────────────────────────────────────

def _bind_mousewheel(scrollable_frame):
    """Bind mousewheel to a CTkScrollableFrame so scrolling works on Linux."""
    parent = scrollable_frame._parent_canvas

    def _on_wheel(event):
        parent.yview_scroll(-1 if event.delta > 0 or event.num == 4 else 1, "units")

    def _bind_recursive(widget):
        widget.bind("<Button-4>", _on_wheel, add="+")
        widget.bind("<Button-5>", _on_wheel, add="+")
        widget.bind("<MouseWheel>", _on_wheel, add="+")
        for child in widget.winfo_children():
            _bind_recursive(child)

    _bind_recursive(scrollable_frame)

    # Also bind new children as they appear
    orig_pack = scrollable_frame._scrollbar.pack_info  # just a marker that it's built
    scrollable_frame._mousewheel_hook = (_on_wheel, _bind_recursive)


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

        self.create_text(cx, cy - 10, text=time_text, fill=C["text"],
                         font=("JetBrains Mono", 36, "bold"))
        self.create_text(cx, cy + 28, text=label, fill=C["text_dim"],
                         font=("Inter", 12))


# ── Session row widget ───────────────────────────────────────────────────────

class SessionRow(ctk.CTkFrame):
    """A single row in the session queue."""

    def __init__(self, master, name: str, index: int, is_active: bool, is_done: bool,
                 on_remove=None, **kwargs):
        super().__init__(master, fg_color="transparent", height=36, **kwargs)
        self.pack_propagate(False)

        if is_done:
            dot_color = C["done"]
            text_color = C["done_text"]
            marker = "✓"
        elif is_active:
            dot_color = C["work"]
            text_color = C["text"]
            marker = "▸"
        else:
            dot_color = C["text_muted"]
            text_color = C["text_dim"]
            marker = "○"

        # Status marker
        ctk.CTkLabel(self, text=marker, font=("Inter", 14), width=24,
                     text_color=dot_color, fg_color="transparent").pack(side="left", padx=(4, 2))

        # Session number
        ctk.CTkLabel(self, text=f"{index + 1}.", font=("Inter", 12), width=24,
                     text_color=C["text_muted"], fg_color="transparent").pack(side="left")

        # Name
        ctk.CTkLabel(self, text=name, font=("Inter", 13),
                     text_color=text_color, fg_color="transparent",
                     anchor="w").pack(side="left", fill="x", expand=True, padx=(4, 0))

        # Remove button (only for pending sessions)
        if not is_done and not is_active and on_remove:
            btn = ctk.CTkButton(self, text="×", width=24, height=24,
                                font=("Inter", 14), corner_radius=12,
                                fg_color="transparent", hover_color=C["surface_light"],
                                text_color=C["text_muted"], command=on_remove)
            btn.pack(side="right", padx=(0, 4))


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


# ── Main app ─────────────────────────────────────────────────────────────────

class PomoApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.stats = Stats()
        self.durations = {"work": DEFAULT_WORK, "short_break": DEFAULT_SHORT_BREAK,
                          "long_break": DEFAULT_LONG_BREAK}
        self.timer_state = TimerState.IDLE
        self.session_type = SessionType.WORK
        self.remaining_seconds = self.durations["work"] * 60
        self.total_seconds = self.remaining_seconds
        self._tick_id = None

        # Session queue: list of {"name": str, "done": bool}
        self.sessions = []
        self.current_index = -1  # -1 = no sessions queued
        self.work_sessions_completed = 0
        self._showing_stats = False

        self.title("Pomo")
        self.configure(fg_color=C["bg"])
        self.geometry("380x680")
        self.minsize(340, 600)

        self._build_ui()
        self._update_display()

    def _build_ui(self):
        # ── Top bar ──────────────────────────────────────────────────────
        top = ctk.CTkFrame(self, fg_color="transparent", height=40)
        top.pack(fill="x", padx=16, pady=(12, 0))

        ctk.CTkLabel(top, text="pomo", font=("Inter", 20, "bold"),
                     text_color=C["text"]).pack(side="left")

        ctk.CTkButton(top, text="📊", width=36, height=36, font=("Inter", 16),
                      fg_color="transparent", hover_color=C["surface_light"],
                      text_color=C["text_dim"],
                      command=self._open_stats).pack(side="right")

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

        # ── Duration steppers ─────────────────────────────────────────────
        dur_frame = ctk.CTkFrame(self, fg_color="transparent")
        dur_frame.pack(fill="x", padx=28, pady=(4, 4))

        self.dur_labels = {}
        steppers = [
            ("Focus", "work", C["work"]),
            ("Short", "short_break", C["break"]),
            ("Long", "long_break", C["long_break"]),
        ]
        for label, key, color in steppers:
            col = ctk.CTkFrame(dur_frame, fg_color="transparent")
            col.pack(side="left", expand=True)

            ctk.CTkLabel(col, text=label, font=("Inter", 10),
                         text_color=C["text_muted"]).pack()

            row = ctk.CTkFrame(col, fg_color="transparent")
            row.pack()

            ctk.CTkButton(row, text="−", width=22, height=22, font=("Inter", 13),
                          corner_radius=11, fg_color=C["surface"],
                          hover_color=C["surface_light"], text_color=C["text_dim"],
                          command=lambda k=key: self._adjust_duration(k, -5)).pack(side="left", padx=1)

            dur_lbl = ctk.CTkLabel(row, text="", font=("Inter", 12, "bold"),
                                   text_color=color, width=36, cursor="sb_v_double_arrow")
            dur_lbl.pack(side="left", padx=2)
            self.dur_labels[key] = dur_lbl

            # Drag to adjust: up = increase, down = decrease, 5m per 30px
            dur_lbl.bind("<Button-1>", lambda e, k=key: self._drag_start(e, k))
            dur_lbl.bind("<B1-Motion>", self._drag_motion)
            dur_lbl.bind("<ButtonRelease-1>", self._drag_end)

            ctk.CTkButton(row, text="+", width=22, height=22, font=("Inter", 13),
                          corner_radius=11, fg_color=C["surface"],
                          hover_color=C["surface_light"], text_color=C["text_dim"],
                          command=lambda k=key: self._adjust_duration(k, 5)).pack(side="left", padx=1)

        self._update_dur_labels()

        # ── Divider ──────────────────────────────────────────────────────
        ctk.CTkFrame(self, fg_color=C["surface_light"], height=1).pack(
            fill="x", padx=24, pady=(4, 4))

        # ── Session queue header ─────────────────────────────────────────
        self.session_header = ctk.CTkFrame(self, fg_color="transparent")
        self.session_header.pack(fill="x", padx=24, pady=(4, 0))

        ctk.CTkLabel(self.session_header, text="Sessions", font=("Inter", 14, "bold"),
                     text_color=C["text"]).pack(side="left")

        ctk.CTkButton(self.session_header, text="+", width=32, height=28,
                      font=("Inter", 16, "bold"), corner_radius=14,
                      fg_color=C["work"], hover_color=C["work_dim"],
                      text_color="#ffffff",
                      command=self._add_session_prompt).pack(side="right")

        # ── Session list ─────────────────────────────────────────────────
        self.session_list = ctk.CTkScrollableFrame(
            self, fg_color="transparent", height=160)
        self.session_list.pack(fill="both", expand=True, padx=20, pady=(4, 4))
        _bind_mousewheel(self.session_list)

        # Empty state message
        self.empty_label = ctk.CTkLabel(
            self.session_list,
            text="Press + to plan your sessions",
            font=("Inter", 12),
            text_color=C["text_muted"],
        )
        self.empty_label.pack(pady=20)

        # ── Today stats ──────────────────────────────────────────────────
        self.stats_bar = ctk.CTkFrame(self, fg_color=C["surface"], corner_radius=12, height=40)
        self.stats_bar.pack(fill="x", padx=24, pady=(4, 12))
        self.stats_bar.pack_propagate(False)

        self.today_label = ctk.CTkLabel(self.stats_bar, text="", font=("Inter", 11),
                                        text_color=C["text_dim"])
        self.today_label.pack(expand=True)
        self._update_today_stats()

    # ── Session queue management ─────────────────────────────────────────

    def _add_session_prompt(self):
        # If an inline entry already exists, focus it instead of creating another
        if hasattr(self, "_inline_entry") and self._inline_entry is not None:
            try:
                self._inline_entry.focus_set()
                return
            except Exception:
                self._inline_entry = None

        # Create inline entry row at the bottom of the session list
        row = ctk.CTkFrame(self.session_list, fg_color=C["surface"], corner_radius=8, height=36)
        row.pack(fill="x", pady=(4, 2), padx=2)
        row.pack_propagate(False)

        entry = ctk.CTkEntry(
            row, placeholder_text="What's your intent?",
            font=("Inter", 13), height=32,
            fg_color=C["surface"], border_color=C["surface_light"],
            text_color=C["text"], placeholder_text_color=C["text_muted"],
            border_width=0)
        entry.pack(side="left", fill="x", expand=True, padx=(8, 4))

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
        entry.bind("<Escape>", cancel)
        entry.focus_set()

    def _add_session(self, name: str, auto_start: bool = True):
        self.sessions.append({"name": name, "done": False})
        # If this is the first session and we're idle, activate and start it
        if self.current_index == -1:
            self.current_index = 0
            self.session_type = SessionType.WORK
            self.remaining_seconds = self.durations["work"] * 60
            self.total_seconds = self.remaining_seconds
            if auto_start:
                self._rebuild_session_list()
                self._update_display()
                self._start_timer()
                return
        self._rebuild_session_list()
        self._update_display()

    def _remove_session(self, index: int):
        if index < len(self.sessions):
            self.sessions.pop(index)
            # Adjust current_index
            if len(self.sessions) == 0:
                self.current_index = -1
            elif index < self.current_index:
                self.current_index -= 1
            elif index == self.current_index:
                # Removed the active one — clamp to valid or -1
                if self.current_index >= len(self.sessions):
                    self.current_index = len(self.sessions) - 1
                # Find next undone session
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
        for widget in self.session_list.winfo_children():
            widget.destroy()

        if not self.sessions:
            self.empty_label = ctk.CTkLabel(
                self.session_list,
                text="Press + to plan your sessions",
                font=("Inter", 12),
                text_color=C["text_muted"],
            )
            self.empty_label.pack(pady=20)
            return

        for i, session in enumerate(self.sessions):
            is_active = (i == self.current_index)
            is_done = session["done"]

            # Show break indicator between work sessions
            if i > 0 and not self.sessions[i - 1]["done"] and not is_done:
                break_label = "Long Break" if (self._count_done_before(i) + 1) % LONG_BREAK_EVERY == 0 else "Short Break"
                brk = ctk.CTkFrame(self.session_list, fg_color="transparent", height=20)
                brk.pack(fill="x")
                brk.pack_propagate(False)
                color = C["long_break"] if "Long" in break_label else C["break"]
                ctk.CTkLabel(brk, text=f"  ╴ {break_label}", font=("Inter", 10),
                             text_color=color, fg_color="transparent").pack(side="left", padx=(20, 0))
            elif i > 0 and self.sessions[i - 1]["done"] and is_active:
                # Break between last done and current active
                break_label = "Short Break"
                if self.session_type in (SessionType.SHORT_BREAK, SessionType.LONG_BREAK):
                    break_label = "Long Break" if self.session_type == SessionType.LONG_BREAK else "Short Break"
                    brk = ctk.CTkFrame(self.session_list, fg_color="transparent", height=20)
                    brk.pack(fill="x")
                    brk.pack_propagate(False)
                    color = C["long_break"] if "Long" in break_label else C["break"]
                    ctk.CTkLabel(brk, text=f"  ╴ {break_label} ◂", font=("Inter", 10),
                                 text_color=color, fg_color="transparent").pack(side="left", padx=(20, 0))

            row = SessionRow(
                self.session_list,
                name=session["name"],
                index=i,
                is_active=is_active,
                is_done=is_done,
                on_remove=lambda idx=i: self._remove_session(idx),
            )
            row.pack(fill="x", pady=1)

        _bind_mousewheel(self.session_list)

    def _count_done_before(self, index: int) -> int:
        return sum(1 for s in self.sessions[:index] if s["done"])

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
        dy = self._drag_y - event.y_root  # up = positive
        self._drag_accum += dy
        self._drag_y = event.y_root
        # Every 30px of drag = 5 minutes
        steps = int(self._drag_accum / 30)
        if steps != 0:
            self._drag_accum -= steps * 30
            self._adjust_duration(self._drag_key, steps * 5)

    def _drag_end(self, event):
        self._drag_key = None

    def _adjust_duration(self, key: str, delta: int):
        self.durations[key] = max(5, self.durations[key] + delta)
        self._update_dur_labels()
        # If we're idle on this type, update the timer to match
        if self.timer_state == TimerState.IDLE:
            type_key = {"work": SessionType.WORK, "short_break": SessionType.SHORT_BREAK,
                        "long_break": SessionType.LONG_BREAK}
            if self.session_type == type_key[key]:
                self.remaining_seconds = self.durations[key] * 60
                self.total_seconds = self.remaining_seconds
                self._update_display()

    def _update_dur_labels(self):
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
        if self.session_type == SessionType.WORK:
            self.remaining_seconds = self.durations["work"] * 60
        elif self.session_type == SessionType.SHORT_BREAK:
            self.remaining_seconds = self.durations["short_break"] * 60
        else:
            self.remaining_seconds = self.durations["long_break"] * 60
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
            # Mark current session done (if queued) or record standalone
            if 0 <= self.current_index < len(self.sessions):
                task_name = self.sessions[self.current_index]["name"]
                self.sessions[self.current_index]["done"] = True
            else:
                task_name = "Focus"
            self.stats.record_session(self.durations["work"], task_name)
            self._update_today_stats()
            self.work_sessions_completed += 1

            notify("Pomo", f"Done: {task_name}")

            # Transition to break
            if self.work_sessions_completed % LONG_BREAK_EVERY == 0:
                self.session_type = SessionType.LONG_BREAK
                self.remaining_seconds = self.durations["long_break"] * 60
            else:
                self.session_type = SessionType.SHORT_BREAK
                self.remaining_seconds = self.durations["short_break"] * 60
            self.total_seconds = self.remaining_seconds

            self._rebuild_session_list()
            self._update_display()
            self._update_button_color()

            # Auto-start break
            self._start_timer()

        else:
            # Break finished — advance to next session
            notify("Pomo", "Break's over — time to focus!")
            self._advance_to_next()

    def _advance_to_next(self):
        # Find next undone session
        next_idx = -1
        for i in range(len(self.sessions)):
            if not self.sessions[i]["done"]:
                next_idx = i
                break

        self.current_index = next_idx
        self.session_type = SessionType.WORK
        self.remaining_seconds = self.durations["work"] * 60
        self.total_seconds = self.remaining_seconds
        self.timer_state = TimerState.IDLE
        self.start_btn.configure(text="Start")

        self._rebuild_session_list()
        self._update_display()
        self._update_button_color()

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
            # Truncate long names for the ring
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

        self.ring.draw(progress, time_text, label, color, dim)

    def _update_today_stats(self):
        today = self.stats.today
        sessions = today["sessions"]
        minutes = int(today["minutes"])
        hrs = minutes // 60
        mins = minutes % 60
        time_str = f"{hrs}h {mins}m" if hrs else f"{mins}m"
        self.today_label.configure(
            text=f"Today:  {sessions} session{'s' if sessions != 1 else ''}  ·  {time_str} focused")

    # ── Stats view (inline toggle) ──────────────────────────────────────

    def _open_stats(self):
        if self._showing_stats:
            self._hide_stats()
            return

        self._showing_stats = True
        # Hide session UI
        self.session_header.pack_forget()
        self.session_list.pack_forget()

        # Build stats panel in the same area
        self.stats_panel = ctk.CTkScrollableFrame(self, fg_color="transparent", height=200)
        self.stats_panel.pack(fill="both", expand=True, padx=20, pady=(4, 4),
                              before=self.stats_bar)
        _bind_mousewheel(self.stats_panel)

        # Back button row
        back_row = ctk.CTkFrame(self.stats_panel, fg_color="transparent")
        back_row.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(back_row, text="Stats", font=("Inter", 14, "bold"),
                     text_color=C["text"]).pack(side="left")
        ctk.CTkButton(back_row, text="← Back", width=60, height=26, font=("Inter", 11),
                      corner_radius=13, fg_color=C["surface"], hover_color=C["surface_light"],
                      text_color=C["text_dim"], command=self._hide_stats).pack(side="right")

        # Stat cards
        cards = ctk.CTkFrame(self.stats_panel, fg_color="transparent")
        cards.pack(fill="x", pady=(0, 8))

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

        # Recent history
        ctk.CTkLabel(self.stats_panel, text="Recent", font=("Inter", 12, "bold"),
                     text_color=C["text"]).pack(anchor="w", pady=(4, 2))

        for entry in reversed(load_json(HISTORY_FILE, [])[-15:]):
            row = ctk.CTkFrame(self.stats_panel, fg_color="transparent")
            row.pack(fill="x", pady=1)
            ctk.CTkLabel(row, text=f"{entry.get('date', '')} {entry.get('time', '')}",
                         font=("Inter", 10), text_color=C["text_muted"]).pack(side="left")
            ctk.CTkLabel(row, text=f"{entry.get('task', '')} · {entry.get('minutes', 0)}m",
                         font=("Inter", 10), text_color=C["text_dim"]).pack(side="right")

    def _hide_stats(self):
        self._showing_stats = False
        if hasattr(self, "stats_panel"):
            self.stats_panel.destroy()
        # Restore session UI
        self.session_header.pack(fill="x", padx=24, pady=(4, 0), before=self.stats_bar)
        self.session_list.pack(fill="both", expand=True, padx=20, pady=(4, 4),
                               before=self.stats_bar)


# ── Entry point ──────────────────────────────────────────────────────────────

def main():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    PomoApp().mainloop()


if __name__ == "__main__":
    main()
