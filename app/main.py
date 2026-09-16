#!/usr/bin/env python3
"""Claude Multi-Instance Setup - entry point."""

from __future__ import annotations

import argparse
import sys


def cli_setup(names: list[str], repair: bool = False) -> None:
    from .core.platform import Platform
    from .core.setup import ClaudeSetup, SetupConfig

    printer = lambda m: print(m)  # noqa: E731
    app = ClaudeSetup(log=printer)
    if repair or not names:
        existing = Platform().detect_existing_instances()
        if existing:
            printer(f"Existing instances found: {', '.join(existing)}")
        names = names or existing or ["Instance 2"]
    cfg = SetupConfig(instance_names=names)
    result = app.run(cfg)
    print(f"\nRESULT: {result.message}")
    sys.exit(0 if result.ok else 1)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Claude Multi-Instance Setup")
    parser.add_argument("--gui", action="store_true", help="launch the graphical wizard (default)")
    parser.add_argument("--cli", metavar="NAMES", help="run headless: comma-separated instance names")
    parser.add_argument("--repair", action="store_true",
                        help="re-patch existing instances (detect + rebuild launchers)")
    args = parser.parse_args(argv)

    if args.repair and not args.cli:
        cli_setup([], repair=True)
        return

    if args.cli:
        names = [n.strip() for n in args.cli.split(",") if n.strip()]
        if not names and not args.repair:
            print("Provide at least one name, e.g. --cli Instance2,Instance3")
            sys.exit(2)
        cli_setup(names, repair=args.repair)
        return

    try:
        from .gui import launch

        launch()
    except Exception as exc:  # noqa: BLE001
        print(f"GUI failed to start: {exc}", file=sys.stderr)
        # fail soft into CLI mode
        names = ["Instance 2"]
        print("Falling back to headless setup with names: " + ", ".join(names))
        cli_setup(names)


if __name__ == "__main__":
    main()