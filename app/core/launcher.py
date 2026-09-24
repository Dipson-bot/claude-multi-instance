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


def mac_app_path(home: str, name: str) -> str:
    """The per-instance launcher app, e.g. ~/Applications/Claude Work.app."""
    return os.path.join(home, "Applications", f"Claude {name}.app")


def mac_bundle_id(name: str) -> str:
    safe = "".join(c for c in name if c.isalnum()) or "Instance"
    return f"com.claude-multi-setup.{safe}"


def mac_claude_bundle(claude_exe: str) -> str:
    """/Applications/Claude.app from .../Claude.app/Contents/MacOS/Claude."""
    i = claude_exe.find(".app/")
    return claude_exe[:i + 4] if i >= 0 else "/Applications/Claude.app"


def _sh_quote(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


def _mac_register(app: str) -> None:
    """Tell Launch Services / Spotlight about a new app right away."""
    import subprocess

    lsregister = ("/System/Library/Frameworks/CoreServices.framework/Frameworks/"
                  "LaunchServices.framework/Support/lsregister")
    try:
        subprocess.run([lsregister, "-f", app], capture_output=True, timeout=60)
        subprocess.run(["touch", app], capture_output=True, timeout=30)
    except Exception:  # noqa: BLE001
        pass


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

    def build_macos(self, instances: list[Instance], claude_exe: str, desktop: str,
                    home: str | None = None) -> None:
        """One small app per instance in ~/Applications ("Claude Work.app").

        Each has its own name and colored icon, so it can be found with
        Spotlight / Launchpad / Finder and pinned to the Dock; opening it starts
        Claude on that instance's profile. A shortcut is put on the Desktop.
        Claude itself is not modified, so a *running* instance shows Claude's
        own Dock icon.
        """
        import shutil

        home = home or os.path.expanduser("~")
        claude_app = mac_claude_bundle(claude_exe)
        apps_dir = os.path.join(home, "Applications")
        os.makedirs(apps_dir, exist_ok=True)
        os.makedirs(desktop, exist_ok=True)
        for inst in instances:
            app = mac_app_path(home, inst.name)
            if os.path.isdir(app):
                shutil.rmtree(app)
            macos_dir = os.path.join(app, "Contents", "MacOS")
            res_dir = os.path.join(app, "Contents", "Resources")
            os.makedirs(macos_dir)
            os.makedirs(res_dir)

            args = "" if inst.is_primary else f' --args --user-data-dir={_sh_quote(inst.profile_dir)}'
            script = os.path.join(macos_dir, "launch")
            with open(script, "w", encoding="utf-8", newline="\n") as fh:
                fh.write("#!/bin/bash\n"
                         f"# Opens Claude on the '{inst.name}' profile (Claude Multi-Instance Setup)\n"
                         f"exec /usr/bin/open -na {_sh_quote(claude_app)}{args}\n")
            os.chmod(script, 0o755)

            plist = {
                "CFBundleName": f"Claude {inst.name}",
                "CFBundleDisplayName": f"Claude {inst.name}",
                "CFBundleIdentifier": mac_bundle_id(inst.name),
                "CFBundleExecutable": "launch",
                "CFBundlePackageType": "APPL",
                "CFBundleShortVersionString": "1.0",
                "CFBundleVersion": "1",
                "LSUIElement": True,  # the launcher itself never shows in the Dock
                "NSHighResolutionCapable": True,
            }
            if inst.icon and os.path.isfile(inst.icon):
                shutil.copyfile(inst.icon, os.path.join(res_dir, "AppIcon.icns"))
                plist["CFBundleIconFile"] = "AppIcon"
            import plistlib

            with open(os.path.join(app, "Contents", "Info.plist"), "wb") as fh:
                plistlib.dump(plist, fh)

            # Desktop shortcut (replaces the .command files of earlier versions)
            legacy = os.path.join(desktop, f"Claude-{inst.name}.command")
            if os.path.isfile(legacy):
                os.remove(legacy)
            link = os.path.join(desktop, f"Claude {inst.name}")
            if os.path.islink(link) or os.path.isfile(link):
                os.remove(link)
            try:
                os.symlink(app, link)
            except OSError as exc:
                self.log(f"  NOTE: no Desktop shortcut for {inst.name}: {exc}")

            _mac_register(app)
            inst.launcher = app
            inst.shortcut = link
            self.log(f"  + app {app}")

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
