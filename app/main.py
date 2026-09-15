#!/usr/bin/env python3
"""Claude Multi-Instance Setup - entry point."""

from __future__ import annotations

import argparse
import sys


def cli_setup(names: list[str]) -> None:
    from .core.setup import ClaudeSetup, SetupConfig

    printer = lambda m: print(m)  # noqa: E731
    app = ClaudeSetup(log=printer)
    cfg = SetupConfig(instance_names=names)
    result = app.run(cfg)
    print(f"\nRESULT: {result.message}")
    sys.exit(0 if result.ok else 1)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Claude Multi-Instance Setup")
    parser.add_argument("--gui", action="store_true", help="launch the graphical wizard (default)")
    parser.add_argument("--cli", metavar="NAMES", help="run headless: comma-separated instance names")
    args = parser.parse_args(argv)

    if args.cli:
        names = [n.strip() for n in args.cli.split(",") if n.strip()]
        if not names:
            print("Provide at least one name, e.g. --cli Company,Personal")
            sys.exit(2)
        cli_setup(names)
        return

    try:
        from .gui import launch

        launch()
    except Exception as exc:  # noqa: BLE001
        print(f"GUI failed to start: {exc}", file=sys.stderr)
        # fail soft into CLI mode
        names = ["Company", "Personal"]
        print("Falling back to headless setup with names: " + ", ".join(names))
        cli_setup(names)


if __name__ == "__main__":
    main()