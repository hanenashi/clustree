#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

VENV_DIR=".venv"
PYTHON_BIN="python3"

if [ ! -d "$VENV_DIR" ]; then
  echo "[INFO] Creating local virtual environment: $VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

VENV_PYTHON="$VENV_DIR/bin/python"

if [ ! -x "$VENV_PYTHON" ]; then
  echo "[ERROR] Virtualenv python not found at: $VENV_PYTHON"
  echo "[HINT] Delete .venv and run again:"
  echo "       rm -rf .venv"
  echo "       ./run.sh"
  exit 1
fi

echo "[INFO] Checking dependencies..."
"$VENV_PYTHON" -m pip install --disable-pip-version-check -q --upgrade pip
"$VENV_PYTHON" -m pip install --disable-pip-version-check -q -r requirements.txt

echo "[INFO] Starting Clustree..."
"$VENV_PYTHON" main.py