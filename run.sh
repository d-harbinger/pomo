#!/usr/bin/env bash
# Launch Pomo timer
cd "$(dirname "$0")"

VENV="venv-$(uname -n)"

if [ ! -d "$VENV" ]; then
    echo "Creating virtual environment ($VENV)..."
    python3 -m venv "$VENV"
    source "$VENV/bin/activate"
    pip install -r requirements.txt
else
    source "$VENV/bin/activate"
fi

python pomo_qt.py "$@"
