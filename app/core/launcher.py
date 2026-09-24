"""Generate per-instance launchers and desktop shortcuts for each OS."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

LogFn = Callable[[str], None]


@dataclass
class Instance:
    """One named Claude instance."""

    name: str  # display name, e.g. "Company"
    profile_dir: str
    launcher: str | None = None  # path to generated launcher file
    shortcut: str | None = None  # path to desktop shortcut
    exe_target: str | None = None
    is_primary: bool = False  # primary = the unmodified MSIX/app install
    color: str = ""  # icon tile color, e.g. "#2F6FEB"
    badge: str = ""  # 0-2 letters shown on the icon
    icon: str | None = None  # generated .ico/.png for this instance
    startup: bool = False  # start automatically at sign-in


def windows_args(inst: Instance) -> str:
    """Command-line arguments for launching an instance from the patched copy."""
    from .asar_patch import INSTANCE_ARG, INSTANCE_ICON_ARG

    args = [] if inst.is_primary else [f'--user-data-dir="{inst.profile_dir}"']
    # read by the launch shim: window title suffix, taskbar group, window icon
    args.append(f'{INSTANCE_ARG}="{inst.name}"')
    if inst.icon:
        args.append(f'{INSTANCE_ICON_ARG}="{inst.icon}"')
    return " ".join(args)


class LauncherBuilder:
    def __init__(self, log: LogFn | None = None) -> None:
        self.log = log or (lambda msg: None)

    # ---- Windows ---- #

    def build_windows(self, instances: list[Instance], copy_exe: str, launcher_dir: str, desktop: str) -> None:
        """One .lnk per instance: the patched copy + --user-data-dir.

        The patched bundle derives CLAUDE_USER_DATA_DIR from --user-data-dir, so
        a plain shortcut is enough (no VBScript, which Windows is phasing out).
        A canonical copy lives in launcher_dir (safe to pin), another on the
        desktop. Legacy Claude-<name>.vbs launchers are left in place so
        existing taskbar pins keep working; they target the same copy exe.
        """
        os.makedirs(launcher_dir, exist_ok=True)
        for inst in instances:
            args = windows_args(inst)
            icon = inst.icon or copy_exe
            launcher = os.path.join(launcher_dir, f"Claude-{inst.name}.lnk")
            shortcut = os.path.join(desktop, f"Claude ({inst.name}).lnk")
            self._win_shortcut(launcher, copy_exe, args, icon)
            self._win_shortcut(shortcut, copy_exe, args, icon)
            inst.launcher = launcher
            inst.shortcut = shortcut
            inst.exe_target = copy_exe
            self.log(f"  + launcher {launcher}")

    def _win_shortcut(self, lnk: str, target: str, args: str, icon: str) -> None:
        """Create/overwrite a .lnk via the WScript.Shell COM object."""
        if os.name != "nt":
            return
        import subprocess

        def q(s: str) -> str:  # PowerShell single-quoted literal
            return "'" + s.replace("'", "''") + "'"

        ps = (
            "$ws=New-Object -ComObject WScript.Shell;"
            f"$l=$ws.CreateShortcut({q(lnk)});"
            f"$l.TargetPath={q(target)};"
            f"$l.Arguments={q(args)};"
            f"$l.WorkingDirectory={q(os.path.dirname(target))};"
            f"$l.IconLocation={q(icon + ',0')};"
            "$l.Save()"
        )
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=60,
            creationflags=0x08000000,
        )
        if proc.returncode != 0 or not os.path.isfile(lnk):
            raise RuntimeError(f"Could not create shortcut {lnk}: {proc.stderr.strip()[-500:]}")

    # ---- macOS ---- #

    def build_macos(self, instances: list[Instance], app_bundle: str, desktop: str) -> None:
        os.makedirs(desktop, exist_ok=True)
        for inst in instances:
            sh_path = os.path.join(desktop, f"Claude-{inst.name}.command")
            if inst.is_primary:
                cmd = f'open -a "Claude"\n'
            else:
                cmd = (
                    f'CLAUDE_USER_DATA_DIR="{inst.profile_dir}"\n'
                    f'open -na "Claude" --args --user-data-dir="{inst.profile_dir}"\n'
                )
            script = "#!/bin/bash\n" + cmd
            with open(sh_path, "w", encoding="utf-8") as fh:
                fh.write(script)
            os.chmod(sh_path, 0o755)
            inst.launcher = sh_path
            if inst.icon:
                self._mac_set_file_icon(sh_path, inst.icon)
            self.log(f"  + launcher {sh_path}")

    def _mac_set_file_icon(self, path: str, image: str) -> None:
        """Give a Finder file a custom icon (NSWorkspace setIcon:forFile:)."""
        import subprocess

        def lit(s: str) -> str:  # AppleScript string literal
            return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'

        script = (
            'use framework "AppKit"\n'
            f"set img to current application's NSImage's alloc()'s initWithContentsOfFile:{lit(image)}\n"
            "current application's NSWorkspace's sharedWorkspace()'s "
            f"setIcon:img forFile:{lit(path)} options:0\n"
        )
        try:
            proc = subprocess.run(["osascript", "-"], input=script, capture_output=True,
                                  text=True, timeout=60)
            if proc.returncode != 0:
                self.log(f"  NOTE: could not set icon on {path}: {proc.stderr.strip()[-200:]}")
        except Exception as exc:  # noqa: BLE001
            self.log(f"  NOTE: could not set icon on {path}: {exc}")

    # ---- Linux ---- #

    def build_linux(self, instances: list[Instance], claude_exe: str, desktop: str, applications: str) -> None:
        os.makedirs(desktop, exist_ok=True)
        os.makedirs(applications, exist_ok=True)
        for inst in instances:
            if inst.is_primary:
                lines = [f'exec "{claude_exe}" "$@"']
            else:
                lines = [
                    f'export CLAUDE_USER_DATA_DIR="{inst.profile_dir}"',
                    f'exec "{claude_exe}" --user-data-dir="{inst.profile_dir}" "$@"',
                ]
            sh_path = os.path.join(desktop, f"Claude-{inst.name}.sh")
            with open(sh_path, "w", encoding="utf-8") as fh:
                fh.write("#!/usr/bin/env bash\n" + "\n".join(lines) + "\n")
            os.chmod(sh_path, 0o755)
            inst.launcher = sh_path
            # desktop entry
            desktop_entry = os.path.join(applications, f"Claude-{inst.name}.desktop")
            with open(desktop_entry, "w", encoding="utf-8") as fh:
                fh.write(
                    "[Desktop Entry]\n"
                    "Type=Application\n"
                    f"Name=Claude ({inst.name})\n"
                    f"Exec={sh_path}\n"
                    + (f"Icon={inst.icon}\n" if inst.icon else "")
                    + "Terminal=false\n"
                    "Categories=Utility;\n"
                )
            inst.shortcut = desktop_entry
            self.log(f"  + launcher {sh_path}")
