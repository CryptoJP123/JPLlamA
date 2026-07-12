#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/../.venv/bin/python}"
ASSETS_DIR="$ROOT_DIR/app/gui/assets"
ICON_FILE="$ASSETS_DIR/jpllama-logo.icns"
PNG_FILE="$ASSETS_DIR/jpllama-logo-1024.png"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python executable not found at: $PYTHON_BIN"
  exit 1
fi

if [[ -f "$ICON_FILE" && -f "$PNG_FILE" ]]; then
  echo "Using existing branding assets: $ICON_FILE"
else
  "$PYTHON_BIN" scripts/generate_desktop_branding_assets.py
fi
"$PYTHON_BIN" -m pip install pyinstaller
"$PYTHON_BIN" -m PyInstaller --noconfirm packaging/pyinstaller/jpllama_gui.spec

echo "Build complete: dist/JPLlamA.app"
