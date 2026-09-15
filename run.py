#!/usr/bin/env python3
"""PyInstaller entry point: imports the app package so relative imports resolve."""

from app.main import main

if __name__ == "__main__":
    main()