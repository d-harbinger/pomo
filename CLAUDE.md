# CLAUDE.md — pomo

A pomodoro focus timer for the Linux desktop: sessions, stats, history,
saved templates, custom chimes. One PySide6 application, one file.

## Project at a glance

- **Stack**: Python 3 + PySide6 (`>=6.7`) for the whole UI; Pillow only for
  icon generation. No framework, no packaging, no test runner beyond the
  standard library.
- **Layout**: `pomo_qt.py` (~1.8k lines) is the entire app. `gen_icon.py`
  renders the app icon. `tests/` holds characterization tests.
- **Data**: five JSON files under `$POMO_DATA_DIR`, defaulting to
  `~/.local/share/pomo` — `stats.json`, `history.json`, `prefs.json`,
  `sessions.json`, `templates.json` (`pomo_qt.py` resolves the directory
  once, at import time).
- **No README.** This file and the audit record below are the entry points.

## Run, install, test

| Task | Command |
|---|---|
| Launch | `./run.sh` — creates `venv-<hostname>` on first run, installs `requirements.txt`, starts the app |
| Install as a desktop app | `bash install.sh` — syncs the venv, generates the icon, writes `~/.local/share/applications/pomo.desktop` |
| Tests | `venv/bin/python -m unittest discover tests` |

The tests run headless: the module sets `POMO_DATA_DIR` to a temp directory
and `QT_QPA_PLATFORM=offscreen` **before** importing the app, so real
widgets are constructed without a display server. Keep that ordering in any
new test file — the app reads its data directory at import.

## Verification boundary

Everything except those headless tests is host-verified. This environment
has no display, so no change to layout, animation, theming, DPI behaviour,
or sound can be claimed as working from here. Say what was run and leave
the visual check to the owner.

## Gotchas

- **Per-host virtual environments.** `run.sh` and `install.sh` build
  `venv-<hostname>` because a checkout is shared across machines and a
  venv's `bin/` shebangs are absolute. `install.sh` probes `bin/pip`
  (not `bin/python`, which is a symlink and passes even when stale) and
  rebuilds a cross-machine venv rather than failing on "bad interpreter".
  Every venv name is gitignored; a venv must never be committed — the
  account name is baked into `pyvenv.cfg` and the shebangs.
- **`pomo.png` is generated, not source.** `gen_icon.py` is the single
  source of truth and both the installer and the app regenerate the bitmap;
  it is gitignored because it changes byte-for-byte on every regen. Do not
  hand-edit or commit it.
- **One look, Glass, frosted three ways.** There is no theme setting: `THEME`
  holds the glass values and `Central.paintEvent` paints the tint. The way it
  frosts is decided once, before first show: with a compositor on X11, and on
  Wayland, the window is translucent and the compositor does the blur; on X11
  without one (and offscreen) the wallpaper named in `~/.fehbg` is blurred and
  drawn under the tint. A `"theme"` key left in `prefs.json` by older versions
  is ignored, neither migrated nor deleted.
- **One toolkit, on purpose.** A parallel CustomTkinter implementation
  (`pomo.py`) was deleted in `60aa29e`, "drop legacy Tk implementation, make
  Qt canonical". Do not reintroduce a second UI toolkit or a second entry
  point.

## Audit and teaching record

The slop audit and the reasoning behind past decisions live at
`~/Projects/claude-settings/workspace/audits/pomo/TEACHING.md` — the
canonical example of the format. Read it before restructuring `pomo_qt.py`,
and record new decisions there. Do **not** create a `TEACHING.md` at this
repo's root; pipeline docs stay out of product repos.
