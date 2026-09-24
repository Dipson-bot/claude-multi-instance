"""Notice Claude updates and offer to update the extra instances (Windows).

The Store updates the original Claude silently; the patched copy the extra
instances run from stays on the old build until setup runs again. Setup
registers `<tool> --check-update` under HKCU\\...\\Run (no admin needed), so on
every sign-in the tool compares the installed Claude version with the one the
copy was built from and, if they differ, asks whether to update now. "No"
is remembered per version so the user is not asked again for the same one.
"""

from __future__ import annotations

import os
import shutil
import sys
from typing import Callable

from .asar_patch import read_sidecar_version
from .platform import Platform

LogFn = Callable[[str], None]

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_VALUE = "ClaudeMultiInstanceUpdateCheck"
_DISMISSED_FILENAME = "update-dismissed.txt"
_TOOL_EXE = "Claude-Multi-Setup.exe"


def _command(base: str, log: LogFn) -> str:
    """Command line for the sign-in check. A frozen build copies itself into
    base so the check survives the user deleting their Downloads copy."""
    if getattr(sys, "frozen", False):
        dst = os.path.join(base, _TOOL_EXE)
        if os.path.normcase(os.path.abspath(sys.executable)) != os.path.normcase(dst):
            try:
                shutil.copy2(sys.executable, dst)
            except OSError as exc:
                if not os.path.isfile(dst):
                    raise
                log(f"  NOTE: kept the existing {dst} ({exc})")
        return f'"{dst}" --check-update'
    run_py = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "run.py")
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return f'"{pyw if os.path.isfile(pyw) else sys.executable}" "{run_py}" --check-update'


def register(base: str, log: LogFn) -> None:
    if os.name != "nt":
        return
    import winreg

    cmd = _command(base, log)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
        winreg.SetValueEx(key, _RUN_VALUE, 0, winreg.REG_SZ, cmd)
    log("  update check: will check for Claude updates at each sign-in")


def unregister(log: LogFn) -> None:
    if os.name != "nt":
        return
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, _RUN_VALUE)
        log("  update check: turned off")
    except FileNotFoundError:
        pass


def is_registered() -> bool:
    if os.name != "nt":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.QueryValueEx(key, _RUN_VALUE)
        return True
    except FileNotFoundError:
        return False


def pending_update(p: Platform | None = None) -> tuple[str, str] | None:
    """(built_from, installed) when the copy is older than installed Claude."""
    p = p or Platform()
    base = p.root_install_dir()
    built = read_sidecar_version(base)
    if not built:
        return None
    installs = p.find_claude()
    if not installs:
        return None
    installed = p.installed_version(installs[0])
    if not installed or installed == built:
        return None
    return built, installed


def run_check() -> int:
    """Entry point for `--check-update` (runs silently at sign-in)."""
    p = Platform()
    pending = pending_update(p)
    if not pending:
        return 0
    built, installed = pending
    dismissed = os.path.join(p.root_install_dir(), _DISMISSED_FILENAME)
    try:
        if open(dismissed, encoding="utf-8").read().strip() == installed:
            return 0
    except OSError:
        pass

    msg = (
        f"Claude Desktop was updated to {installed}.\n\n"
        f"Your extra Claude instances still run the older {built}. "
        "They keep working, but they miss the new version's fixes and features.\n\n"
        "Update them now? (Close your extra Claude windows first. "
        "Chats, sign-ins and settings are kept.)"
    )
    if not _ask_yes_no("Claude instances: update available", msg):
        try:
            with open(dismissed, "w", encoding="utf-8") as fh:
                fh.write(installed)
        except OSError:
            pass
        return 0

    from ..gui import launch

    launch()
    return 0


def _ask_yes_no(title: str, text: str) -> bool:
    if os.name == "nt":
        import ctypes

        MB_YESNO, MB_ICONINFORMATION, MB_SETFOREGROUND, MB_TOPMOST = 0x4, 0x40, 0x10000, 0x40000
        flags = MB_YESNO | MB_ICONINFORMATION | MB_SETFOREGROUND | MB_TOPMOST
        return ctypes.windll.user32.MessageBoxW(None, text, title, flags) == 6  # IDYES
    from tkinter import Tk, messagebox

    root = Tk()
    root.withdraw()
    try:
        return bool(messagebox.askyesno(title, text))
    finally:
        root.destroy()
