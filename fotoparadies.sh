#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

# Create venv and install dependencies if not present
if [[ ! -f "$VENV_DIR/bin/python3" ]]; then
    echo "Setting up virtual environment..."
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install --quiet playwright
    "$VENV_DIR/bin/python3" -m playwright install chromium
    sudo apt-get install -y --no-install-recommends \
        libatk-bridge2.0-0 libatk1.0-0 libcups2 libdrm2 \
        libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
        libxrandr2 libgbm1 libasound2 libpango-1.0-0 libcairo2 2>/dev/null || true
    echo "Setup complete."
    echo
fi

exec "$VENV_DIR/bin/python3" "$SCRIPT_DIR/fotoparadies_status.py" "$@"
