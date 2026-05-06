#!/usr/bin/env bash
# Install Pomo as a desktop application
set -e

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
DESKTOP_FILE="$HOME/.local/share/applications/pomo.desktop"
ICON_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"

# Default to the Qt port; pass `tk` to install the legacy Tk version.
ENTRY="${1:-qt}"
case "$ENTRY" in
    qt) SCRIPT="pomo_qt.py" ;;
    tk) SCRIPT="pomo.py" ;;
    *) echo "Usage: $0 [qt|tk]" >&2; exit 1 ;;
esac

# Pick a venv. The per-host pattern is the default so a shared project
# folder mounted across machines keeps separate venvs (their internal
# shebangs are absolute and won't survive a host change). A plain
# $APP_DIR/venv is only honored if it actually runs on this machine —
# stale cross-host venvs would otherwise cause "bad interpreter" errors
# from baked-in shebangs.
venv_works() {
    # Probe via pip specifically: pip is a Python script with the venv
    # path baked into its shebang, so it dies with "bad interpreter" on
    # cross-host venvs. `bin/python` itself is a symlink to the system
    # interpreter and would pass a naive probe even on a stale venv.
    [ -x "$1/bin/pip" ] && "$1/bin/pip" --version >/dev/null 2>&1
}

if venv_works "$APP_DIR/venv"; then
    VENV="$APP_DIR/venv"
else
    VENV="$APP_DIR/venv-$(hostname)"
fi

if ! venv_works "$VENV"; then
    if [ -d "$VENV" ]; then
        echo "Existing $VENV is stale (likely from another machine); recreating..."
        rm -rf "$VENV"
    else
        echo "Creating virtual environment ($VENV)..."
    fi
    python3 -m venv "$VENV"
fi
# Always sync deps — pip skips already-installed packages, and this
# pulls in PySide6 when transitioning from a Tk-only setup.
echo "Syncing dependencies in $VENV..."
"$VENV/bin/pip" install -q -r "$APP_DIR/requirements.txt"

# Generate icon
echo "Generating icon..."
"$VENV/bin/python" "$APP_DIR/gen_icon.py" "$ICON_DIR/pomo.png"
# Also drop a copy next to the script so the running app finds it
# without a system install.
"$VENV/bin/python" "$APP_DIR/gen_icon.py" "$APP_DIR/pomo.png"

# Write .desktop entry
mkdir -p "$(dirname "$DESKTOP_FILE")"
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Name=Pomo
Comment=Pomodoro focus timer
Exec=$VENV/bin/python $APP_DIR/$SCRIPT
Icon=pomo
Terminal=false
Type=Application
Categories=Utility;Office;
Keywords=pomodoro;timer;focus;productivity;
StartupWMClass=Pomo
EOF

# Refresh desktop database
if command -v update-desktop-database &>/dev/null; then
    update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
fi
if command -v gtk-update-icon-cache &>/dev/null; then
    gtk-update-icon-cache -f "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
fi

echo "Installed! You can now find 'Pomo' in your application launcher."
