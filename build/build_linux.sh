#!/usr/bin/env bash
# Build the setup wizard for Linux (single-file binary via PyInstaller).
# Run from project root:  bash build/build_linux.sh
set -euo pipefail
cd "$(dirname "$0")/.."

python3 -m pip install --quiet --upgrade pyinstaller

python3 -m PyInstaller \
  --noconfirm --clean --onefile \
  --name "claude-multi-setup" \
  --collect-submodules app \
  app/main.py

echo "Done -> $(pwd)/dist/claude-multi-setup"