"""Start instances automatically at sign-in.

Windows: a shortcut in the user's Startup folder (the same kind of entry
Task Manager > Startup apps lists; if the user disables it there, it is
reported as off here). macOS: a LaunchAgent per instance. Linux: an XDG
autostart entry. No admin rights needed anywhere.
"""

from __future__ import annotations

import os
import plistlib
from typing import Callable

from .launcher import Instance, LauncherBuilder, mac_app_path, mac_bundle_id, windows_args
from .platform import Platform, safe_name

LogFn = Callable[[str], None]

# Task Manager's on/off switch for Startup-folder items (first byte 2 = on, 3 = off)
_APPROVED_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder"
_MAC_LABEL = "com.claude-multi-setup.{}"


def _win_startup_dir() -> str:
    import ctypes

    buf = ctypes.create_unicode_buffer(260)
    if ctypes.windll.shell32.SHGetFolderPathW(None, 0x07, None, 0, buf) == 0 and buf.value:  # CSIDL_STARTUP
        return buf.value
    return os.path.join(os.environ["APPDATA"], "Microsoft", "Windows", "Start Menu", "Programs", "Startup")


def entry_path(p: Platform, name: str) -> str:
    if p.is_windows:
        return os.path.join(_win_startup_dir(), f"Claude ({name}).lnk")
    if p.is_macos:
        return os.path.join(p.home, "Library", "LaunchAgents", _MAC_LABEL.format(safe_name(name)) + ".plist")
    return os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.join(p.home, ".config")),
                        "autostart", f"Claude-{safe_name(name)}.desktop")


def _win_disabled_in_task_manager(lnk_name: str) -> bool:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _APPROVED_KEY) as key:
            data, _ = winreg.QueryValueEx(key, lnk_name)
        return bool(data) and data[0] % 2 == 1  # 3 (and other odd values) = disabled
    except OSError:
        return False


def _win_clear_task_manager_flag(lnk_name: str) -> None:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _APPROVED_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, lnk_name)
    except OSError:
        pass


def is_enabled(name: str, p: Platform | None = None) -> bool:
    p = p or Platform()
    path = entry_path(p, name)
    if not os.path.isfile(path):
        return False
    if p.is_windows:
        return not _win_disabled_in_task_manager(os.path.basename(path))
    return True


def set_enabled(inst: Instance, enabled: bool, p: Platform | None = None,
                log: LogFn | None = None) -> None:
    """Turn starting at sign-in on or off for one instance."""
    p = p or Platform()
    log = log or (lambda m: None)
    path = entry_path(p, inst.name)
    if not enabled:
        if os.path.exists(path):
            os.remove(path)
            log(f"  startup off: {inst.name}")
        if p.is_windows:
            _win_clear_task_manager_flag(os.path.basename(path))
        return

    os.makedirs(os.path.dirname(path), exist_ok=True)
    if p.is_windows:
        exe = os.path.join(p.root_install_dir(), "app", "Claude.exe")
        if not os.path.isfile(exe):
            raise FileNotFoundError("the patched Claude copy is missing; run setup first")
        LauncherBuilder()._win_shortcut(path, exe, windows_args(inst), inst.icon or exe)
        # re-enabling here must also undo a "Disabled" set in Task Manager
        _win_clear_task_manager_flag(os.path.basename(path))
    elif p.is_macos:
        app = mac_app_path(p.home, inst.name)
        launch = os.path.join(app, "Contents", "MacOS", "launch")
        agent = {
            "Label": _MAC_LABEL.format(safe_name(inst.name)),
            # the instance's own launcher app, so System Settings > Login Items
            # lists it as "Claude <name>" rather than as "open"
            "ProgramArguments": [launch] if os.path.isfile(launch) else
            ["/usr/bin/open", "-na", "Claude", "--args", f"--user-data-dir={inst.profile_dir}"],
            "AssociatedBundleIdentifiers": [mac_bundle_id(inst.name)],
            "RunAtLoad": True,
        }
        with open(path, "wb") as fh:
            plistlib.dump(agent, fh)
    else:
        launcher = inst.launcher or os.path.join(p.desktop_dir(), f"Claude-{inst.name}.sh")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("[Desktop Entry]\nType=Application\n"
                     f"Name=Claude ({inst.name})\nExec={launcher}\n"
                     + (f"Icon={inst.icon}\n" if inst.icon else "")
                     + "X-GNOME-Autostart-enabled=true\n")
    log(f"  startup on: {inst.name}")


def instance_from_manifest(entry: dict, p: Platform) -> Instance:
    name = entry["name"]
    return Instance(name=name, profile_dir=entry.get("profile_dir") or p.profile_dir(safe_name(name)),
                    launcher=entry.get("launcher"), icon=entry.get("icon"),
                    color=entry.get("color", ""), badge=entry.get("badge", ""))


def apply(choices: dict[str, bool], log: LogFn | None = None) -> list[str]:
    """Set startup on/off for existing instances ({name: enabled}).
    Returns problems ([] = all applied)."""
    p = Platform()
    known = {m["name"].lower(): m for m in p.load_manifest()}
    # instances from older versions (no manifest entry) still get a usable record
    for name in p.detect_existing_instances():
        known.setdefault(name.lower(), {"name": name})
    problems = []
    for name, enabled in choices.items():
        entry = known.get(name.lower())
        if not entry:
            problems.append(f'"{name}" is not an instance created by this tool.')
            continue
        try:
            set_enabled(instance_from_manifest(entry, p), enabled, p, log)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{name}: {exc}")
    return problems
