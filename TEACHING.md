# TEACHING.md — pomo

Per-project audit of AI-codegen slop, taught with **this repo's own code** as the
examples, then triaged into a cleanup plan. Part of the `/mnt/Projects` library
cleanup. Pilot project for the methodology.

Each finding follows: **Tell** (what it looks like) · **Why** (why an AI does it) ·
**Detect** (a signal you can run) · **Fix** (the surgical undo).

---

## Snapshot — 2026-05-28

- **What it is:** a feature-rich pomodoro timer (sessions, stats, history, templates, patterns, custom chimes).
- **`pomo.py`** — CustomTkinter UI, **2507 LOC**. `run.sh` launches this.
- **`pomo_qt.py`** — PySide6/Qt port, **1790 LOC**. `install-desktop.sh` defaults to this.
- **~4300 LOC of app logic for a pomodoro timer**, the same app written twice.
- git: clean tree, privacy infra (`.gitleaks.toml`, pre-commit hook, audit scripts) present.
- **Runs?** Not verified — GUI app, audited inside a display-less VM. Launch must be confirmed host-side before any "works" claim.

**pomo's slop profile:** heavy on *duplication / parallel implementations / over-build*;
moderate on *silent error-swallowing*; **clean** on comment-slop and backwards-compat tombstones.

---

## Findings (ranked by leverage)

### 1. Two parallel implementations — the dual-maintenance trap  *(CRITICAL)*

- **Tell:** `pomo.py` and `pomo_qt.py` are the *same app* on two GUI toolkits. Both define `Sounds`, `Stats`, `SessionType`, `TimerState`, a ring widget, a session row, a main window. Every feature must be built — and debugged — twice.
- **Why:** an AI asked to "port to Qt" or "try Qt" produces a *second* file rather than migrating, because creating is safer than deleting. `requirements.txt` then rationalizes it: `# Legacy Tk version (pomo.py) — keep available alongside the Qt port.` "Keep available alongside" is the tell of a decision nobody made.
- **Detect:** two files implementing the same class names. `grep -l 'class PomoApp\|class PomoWindow' *.py` → both.
- **Fix:** decide which UI is canonical (the Qt port reads as the intended future; it's also the cleaner of the two — see #5). Archive the loser to `/mnt/Projects/_archive/pomo/` (never `rm`), delete it from the active tree, and findings #2–#4 collapse for free. **This is your call, not mine** — picking a GUI toolkit is a taste/strategy decision.

### 2. Duplicated domain logic across the two files

- **Tell:** the non-UI core is copy-pasted. `Sounds` at `pomo.py:91` is near-verbatim with `pomo_qt.py:342` — identical chime triad `[523.25, 659.25, 783.99]`, identical `_gen_tone` calls, identical `except Exception: pass`. Same story for `Stats` (`pomo.py:520` ≈ `pomo_qt.py:386`), `load_json`/`save_json`, the `*_FILE` path constants, `SessionType`, `TimerState`.
- **Why:** when the second file was spun up (#1), shared logic got pasted instead of imported. The comment `# ── Stats (extracted) ──` at `pomo_qt.py:384` literally claims extraction that never happened — the class is still defined in both files.
- **Detect:** same class/function name defined in two files; diff the bodies — near-identical.
- **Fix:** resolved automatically by #1 (one impl ⇒ no duplication). *If* you genuinely keep both UIs, extract the non-UI core (`Sounds`, `Stats`, persistence, enums, `_gen_tone`) into `pomo_core.py` and `import` it from both — but only then. Don't build that shared module while you still have two UIs you might cut.

### 3. `requirements.txt` installs both GUI stacks

- **Tell:** a fresh install pulls `PySide6` **and** `customtkinter` (+ `Pillow`, `plyer`) — Qt *and* Tk, hundreds of MB, for an app you run one way.
- **Why:** deps accumulate per implementation; nobody prunes the path they stopped using.
- **Detect:** dependencies for a code path you don't actually run.
- **Fix:** after #1, list only the surviving toolkit's deps.

### 4. Two launchers disagree on the canonical app

- **Tell:** `run.sh` runs `python pomo.py` (Tk); `install-desktop.sh` defaults `tk|qt` toward `pomo_qt.py` (Qt). A new user gets a *different program* depending on how they start it.
- **Why:** each launcher was written for whichever impl was current at the time; neither was reconciled.
- **Detect:** entrypoint scripts pointing at different `main` files.
- **Fix:** one canonical entrypoint after #1.

### 5. Silent error-swallowing

- **Tell:** `pomo.py` has **7** `except Exception: pass` blocks (the Qt port has 2). e.g. `Sounds.play` (`pomo.py:117`) swallows every playback failure — if audio silently never plays, there's nothing to debug.
- **Why:** an AI adds blanket `try/except` to make code "robust"; bare `pass` hides the failure instead of handling it.
- **Detect:** `grep -A1 -E 'except' pomo.py | grep -c 'pass'` → 7.
- **Fix:** narrow to the expected exception (`subprocess.SubprocessError`, `OSError`) and at minimum log it; reserve broad swallows for places a failure is genuinely ignorable, with a comment saying why.

### 6. Over-build for the domain *(flag, not a defect)*

- **Tell:** ~4300 LOC and ~226 functions for a pomodoro timer; subsystems for templates (5 slots), history, patterns, custom-generated WAV chimes.
- **Why:** AI expands scope eagerly — "while I'm here, add templates/history/patterns." Often genuinely wanted in a personal tool, so this is a *question*, not an automatic cut.
- **Detect:** LOC and feature count far exceeding the core domain.
- **Fix:** judgment call — which features do you actually use? Every one you keep is one you maintain (×2 until #1 is done). Yours to decide.

---

## Triage / cleanup plan

| # | Finding | Action | Status |
|---|---------|--------|--------|
| 1 | Parallel Tk/Qt impls | **Qt chosen.** `pomo.py` archived to `_archive/pomo/` | done 2026-05-28 |
| 2 | Duplicated core | Resolved by #1 — only the Qt core remains | done 2026-05-28 |
| 3 | Both stacks in requirements | Pruned to `PySide6` + `Pillow` | done 2026-05-28 |
| 4 | Conflicting launchers | `run.sh` + `install-desktop.sh` both → `pomo_qt.py` | done 2026-05-28 |
| 5 | Silent `except: pass` | Qt's 2 narrowed to `except OSError` + reason comments | done 2026-05-28 |
| 6 | Over-build | Review which features you actually use/maintain | open — your call |

The canonical-UI decision (Qt) unblocked #1–#4, which collapsed together. #6 is a
product judgment, left to you.

## Cleanup applied — 2026-05-28

- `pomo.py` (Tk, 2507 LOC) → `/mnt/Projects/_archive/pomo/` with a provenance README.
- `run.sh`: launches `pomo_qt.py`.
- `install-desktop.sh` → renamed `install.sh`: dropped the `qt|tk` switch; hardcoded `pomo_qt.py`; trimmed a stale Tk-transition comment.
- `requirements.txt`: removed `customtkinter` + `plyer` and the "keep alongside" comment.
- `pomo_qt.py`: both `except Exception: pass` → `except OSError:` with one-line reasons.
- **Verified:** `bash -n` on both scripts, `py_compile pomo_qt.py`, no dangling `pomo.py` refs. **Not verified:** GUI launch (display-less VM) — confirm host-side before shipping.
- **Not committed** — working-tree changes left for user review.

---

## Verification gate

No "fixed/working" claim until `pomo` launches host-side (GUI; not runnable in the
audit VM) and the surviving features are exercised. Lint/import-check is necessary but
not sufficient.

---

## Qt structural & functional review — 2026-05-28

Now that Qt is canonical, `pomo_qt.py` (1790 LOC) got its own structure + function pass.

**Structure: good.** 12 classes; widgets (`RingTimer`, `SessionRow`), dialogs
(`AddSessionPopup`, `PatternPopup`, `SettingsDialog`, `TemplatesDialog`) and `Sounds`/
`Stats` are all properly separated. No ytdlp-style god-class. The one large class is
**`PomoWindow`** (~694 LOC, 47 methods) — it owns persistence + the timer state machine
+ the session-stack model + display refresh + theming. *Optional* future polish: extract
a `SessionStack` model (the `sessions` list + add/remove/reorder/persist + `current_index`)
out of the window. Not urgent — the class is readable and well-named. **Don't refactor
without a reason** (our own rule); flag, don't force.

**Function: mostly correct, with behaviors to confirm.**

- **F1 — skip counts as completion *(likely a real bug)*.** `skip_session` (1360) calls `_session_complete`, which for a work session calls `stats.record_session(...)` and notifies `"Done: {name}"` (1383). So **skipping a focus inflates your stats/history as if you'd done the work**, and pops a "Done" toast. Skipping should advance *without* recording. Confirm intent — if I'm right, the fix is to pass a `completed=False` flag (or split skip from complete) so stats only record genuine completions.
- **F2 — auto-start asymmetry *(design question)*.** After a *work* session, the next session (a break) **always** auto-starts; after a *break*, the next only auto-starts if `chain_auto_start` is on (1401–1403). Coherent ("breaks begin automatically, you consciously start each focus") — but is auto-starting the break even when auto-chain is *off* what you want?
- **F3 — dead line in `_remove` *(minor)*.** `pomo_qt.py:1315` sets `current_index = max(0, current_index - 1)` and line 1316 immediately overwrites it with `_first_pending_index()`. Line 1315 is dead — delete it. Safe, trivial.
- **F4 — `done` state not persisted *(note)*.** `_save_sessions`/`_load_sessions` drop per-session `done`, so a relaunch reloads the whole stack as pending. Fine for a pomodoro, but confirm you don't want mid-stack resume across restarts.

**Clean / correct:** timer pause/resume/reset, `_load_sessions` type validation, `_current_session_seconds` fallback, the `push_pattern` interleave.

**Resolved — 2026-05-28:**

- **F1 — fixed.** `_session_complete(completed=True)`; `skip_session` now calls it with `completed=False`, so a skipped session advances without recording stats, chiming, notifying, or auto-starting. Only genuine timer completions count.
- **F2 — improved into an explicit option.** The hardcoded asymmetry is gone. Two labeled toggles in Settings: **"Auto-start breaks after focus"** (`auto_start_breaks`, default on) and **"Auto-start next focus after a break"** (`chain_auto_start`, default off). Defaults preserve prior behavior, so the 45-10-20 template flow is unchanged — but it's now intentional, not jerry-rigged.
- **F3 — fixed.** Dead line removed from `_remove`.
- **F4 — confirmed intended** (stack reloads pending on relaunch). Left as-is.
- **`SessionStack` extraction — deferred.** Noted seam; not worth the churn now.

Verified: `py_compile` passes. **Not verified:** GUI behavior — confirm host-side that skip no longer logs a session and that the two toggles do what their labels say.

---

## Cross-distro font scaling — 2026-05-28

**Problem:** fonts rendered hugely different sizes across machines (CachyOS/Mint/Ubuntu/Arch, Plasma vs Cinnamon vs GNOME, X11 vs Wayland). Cause: every size was authored in **points**, and Qt converts `pt → px` using each desktop's **logical DPI** — which every DE/display-server reports differently. Qt6's "automatic HiDPI" only normalizes *device-pixel-ratio* (crispness), not logical DPI, so the comment in `main()` ("no setup needed") was misleading. The ring timer had a twist: a pixel-derived `time_size` was passed as a *point* size.

**Fix (A — normalize to logical pixels):**
- Added `fs(points)` / `set_ui_scale()` helpers. Sizes stay authored as points at a 96-DPI baseline and are emitted as **logical px** (`pt × 4/3 × ui_scale`). Logical px is DE-independent; Qt's HiDPI handling keeps it crisp on HiDPI screens. This is the opposite of auto-scaling by logical DPI, which would *re-create* the variance.
- Converted all ~25 `font-size: Npt` (central stylesheet + inline label/button styles) to `fs(N)`.
- Ring timer now uses `QFont.setPixelSize(time_size)` (was point size) — stays window-proportional, no longer DPI-dependent. Not multiplied by `ui_scale` (already scales with the window).

**Fix (C — per-machine override):**
- `ui_scale` pref (default 1.0), loaded in `__init__`, persisted in `prefs.json`. Since `prefs.json` lives in each machine's `~/.local/share/pomo`, the scale is naturally per-PC.
- New Settings control: **"UI scale"** spinbox (50–300%). Changing it re-applies the stylesheet live.

**Scope:** only *fonts* scale with `ui_scale`; paddings/borders/checkbox-indicator stay fixed logical px — sufficient for the reported problem, and avoids a much larger unverifiable change.

**Verified headless (offscreen PySide6, 9/9):** `fs()` math + clamp, stylesheet emits px and scales, widgets build at a non-default scale, spinner reflects + round-trips `ui_scale`. **Not verified — and only the user can:** how it actually *looks* on each of the four distros. Workflow: launch per machine, set `ui_scale` once in Settings; it persists there.

**Header responsiveness + retro pills:** the larger px fonts made the header toolbar clip in narrow/cornered windows. Fixes: removed the decorative "SESSIONS" label; added a `ui_scale`-aware minimum window size (560×300 @100%) so the header can't be squeezed until it clips; restyled the `#chip` buttons as hard-edge HUD pills (0px corners, 1px border, accent-on-hover, UPPERCASE) — first step toward an 8-bit/Mega-Man revision. Baseline scaling confirmed on host by the user; pill restyle + min-size not yet visually confirmed.
