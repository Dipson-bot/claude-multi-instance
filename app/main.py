#!/usr/bin/env python3
"""Claude Multi-Instance Setup - entry point."""

from __future__ import annotations

import argparse
import sys


def cli_setup(names: list[str], repair: bool = False, update_check: bool = True) -> None:
    from .core.platform import Platform
    from .core.setup import ClaudeSetup, SetupConfig

    printer = lambda m: print(m)  # noqa: E731
    app = ClaudeSetup(log=printer)
    if repair or not names:
        existing = Platform().detect_existing_instances()
        if existing:
            printer(f"Existing instances found: {', '.join(existing)}")
        names = names or existing or ["Instance 2"]
    cfg = SetupConfig(instance_names=names, update_check=update_check, force_patch=repair)
    result = app.run(cfg)
    print(f"\nRESULT: {result.message}")
    sys.exit(0 if result.ok else 1)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Claude Multi-Instance Setup")
    parser.add_argument("--gui", action="store_true", help="launch the graphical wizard (default)")
    parser.add_argument("--cli", metavar="NAMES", help="run headless: comma-separated instance names")
    parser.add_argument("--repair", action="store_true",
                        help="re-patch existing instances (detect + rebuild launchers)")
    parser.add_argument("--no-update-check", action="store_true",
                        help="do not check for Claude updates at Windows sign-in")
    parser.add_argument("--check-update", action="store_true",
                        help=argparse.SUPPRESS)  # run at sign-in by the Run key
    parser.add_argument("--list", action="store_true", help="list the instances this tool created")
    parser.add_argument("--remove", metavar="NAMES",
                        help="remove instances (comma-separated): shortcuts, launchers, icons")
    parser.add_argument("--delete-data", action="store_true",
                        help="with --remove/--uninstall: also move the profiles "
                             "(sign-ins, local chats, settings) to the Recycle Bin/Trash")
    parser.add_argument("--uninstall", action="store_true",
                        help="remove every instance plus the shared Claude copy and update check")
    parser.add_argument("--startup-on", metavar="NAMES",
                        help='start these instances at sign-in (comma-separated, or "all")')
    parser.add_argument("--startup-off", metavar="NAMES",
                        help='stop starting these instances at sign-in (comma-separated, or "all")')
    args = parser.parse_args(argv)

    if args.check_update:
        from .core.update_check import run_check

        sys.exit(run_check())

    if args.startup_on or args.startup_off:
        from .core import startup
        from .core.remove import known_instances

        every = [i.name for i in known_instances()]

        def pick(value: str | None) -> list[str]:
            if not value:
                return []
            return every if value.strip().lower() == "all" else [n.strip() for n in value.split(",") if n.strip()]

        choices = {n: True for n in pick(args.startup_on)}
        choices.update({n: False for n in pick(args.startup_off)})
        problems = startup.apply(choices, log=print)
        for problem in problems:
            print(f"ERROR: {problem}")
        sys.exit(1 if problems else 0)

    if args.list or args.remove or args.uninstall:
        from .core.remove import known_instances, remove_instances

        known = known_instances()
        if args.list:
            from .core import startup

            for i in known:
                when = "starts at sign-in" if startup.is_enabled(i.name) else "manual start"
                print(f"{i.name}\t{when}\t{i.profile_dir}")
            if not known:
                print("No instances found.")
            return
        names = ([i.name for i in known] if args.uninstall
                 else [n.strip() for n in args.remove.split(",") if n.strip()])
        result = remove_instances(names, delete_data=args.delete_data, uninstall=args.uninstall,
                                  log=print)
        print(f"\nRESULT: {result.message}")
        sys.exit(0 if result.ok else 1)

    if args.repair and not args.cli:
        cli_setup([], repair=True, update_check=not args.no_update_check)
        return

    if args.cli:
        names = [n.strip() for n in args.cli.split(",") if n.strip()]
        if not names and not args.repair:
            print("Provide at least one name, e.g. --cli Instance2,Instance3")
            sys.exit(2)
        cli_setup(names, repair=args.repair, update_check=not args.no_update_check)
        return

    try:
        from .gui import launch

        launch()
    except Exception as exc:  # noqa: BLE001
        # Never run a setup the user did not ask for; report and stop.
        msg = (f"The setup window could not start:\n{exc}\n\n"
               "You can run setup without a window instead, e.g.\n"
               "  Claude-Multi-Setup.exe --cli \"Work,Personal\"")
        print(msg, file=sys.stderr)
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, msg, "Claude Multi-Instance Setup", 0x10)
        sys.exit(1)


if __name__ == "__main__":
    main()