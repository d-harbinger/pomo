#!/usr/bin/env bash
# Install Pomo as a desktop application
set -e

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
DESKTOP_FILE="$HOME/.local/share/applications/pomo.desktop"
ICON_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"

# Ensure venv exists
if [ ! -d "$APP_DIR/venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$APP_DIR/venv"
    "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"
fi

# Generate icon
echo "Generating icon..."
"$APP_DIR/venv/bin/python" "$APP_DIR/gen_icon.py" "$ICON_DIR/pomo.png"

# Write .desktop entry
mkdir -p "$(dirname "$DESKTOP_FILE")"
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Name=Pomo
Comment=Pomodoro focus timer
Exec=$APP_DIR/venv/bin/python $APP_DIR/pomo.py
Icon=pomo
Terminal=false
Type=Application
Categories=Utility;Office;
Keywords=pomodoro;timer;focus;productivity;
EOF

# Refresh desktop database
if command -v update-desktop-database &>/dev/null; then
    update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
fi
if command -v gtk-update-icon-cache &>/dev/null; then
    gtk-update-icon-cache -f "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
fi

echo "Installed! You can now find 'Pomo' in your application launcher."
