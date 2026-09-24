#!/usr/bin/env bash
# Run Claude Multi-Instance Setup on macOS straight from this folder.
# Usage (in Terminal):  bash start-mac.sh        (extra options are passed on, e.g. --list)
# First run creates a private Python environment in .venv (nothing is
# installed system-wide) and installs Pillow for the colored icons.
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is not installed. Get it from https://www.python.org/downloads/macos/ and run this again."
  exit 1
fi
if ! python3 -c "import tkinter" 2>/dev/null; then
  echo "This Python has no Tkinter (needed for the setup window)."
  echo "Install Python from https://www.python.org/downloads/macos/ (includes Tkinter),"
  echo "or with Homebrew:  brew install python-tk"
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "First run: setting up a private Python environment..."
  python3 -m venv .venv
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet "pillow>=10.1"
fi

exec .venv/bin/python run.py "$@"
