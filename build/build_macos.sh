#!/usr/bin/env bash
# Build the setup wizard for macOS (.app bundle via PyInstaller).
# Run from project root:  bash build/build_macos.sh
set -euo pipefail
cd "$(dirname "$0")/.."

python3 -m pip install --quiet --upgrade pyinstaller

python3 -m PyInstaller \
  --noconfirm --clean --windowed \
  --name "Claude Multi Setup" \
  --paths . \
  --icon icon.icns \
  run.py

echo "Done -> $(pwd)/dist/Claude Multi Setup.app"
