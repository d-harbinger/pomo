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
- `install-desktop.sh`: dropped the `qt|tk` switch; hardcoded `pomo_qt.py`; trimmed a stale Tk-transition comment.
- `requirements.txt`: removed `customtkinter` + `plyer` and the "keep alongside" comment.
- `pomo_qt.py`: both `except Exception: pass` → `except OSError:` with one-line reasons.
- **Verified:** `bash -n` on both scripts, `py_compile pomo_qt.py`, no dangling `pomo.py` refs. **Not verified:** GUI launch (display-less VM) — confirm host-side before shipping.
- **Not committed** — working-tree changes left for user review.

---

## Verification gate

No "fixed/working" claim until `pomo` launches host-side (GUI; not runnable in the
audit VM) and the surviving features are exercised. Lint/import-check is necessary but
not sufficient.
