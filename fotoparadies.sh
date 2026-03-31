#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

# Create venv and install dependencies if not present
if [[ ! -f "$VENV_DIR/bin/python3" ]]; then
    echo "Setting up virtual environment..."
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install --quiet playwright
    "$VENV_DIR/bin/python3" -m playwright install --with-deps chromium
    echo "Setup complete."
    echo
fi

exec "$VENV_DIR/bin/python3" "$SCRIPT_DIR/fotoparadies_status.py" "$@"
