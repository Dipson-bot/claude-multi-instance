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


class LauncherBuilder:
    def __init__(self, log: LogFn | None = None) -> None:
        self.log = log or (lambda msg: None)

    # ---- Windows ---- #

    def build_windows(self, instances: list[Instance], copy_exe: str, vbs_dir: str, desktop: str) -> None:
        os.makedirs(vbs_dir, exist_ok=True)
        for inst in instances:
            vbs_path = os.path.join(vbs_dir, f"Claude-{inst.name}.vbs")
            if inst.is_primary:
                # primary uses the ORIGINAL (patched) app copy's exe, default profile
                target = copy_exe
                args = ""
                env_extra = ""
            else:
                target = copy_exe
                args = f' --user-data-dir="{inst.profile_dir}"'
                env_extra = (
                    f'CreateObject("WScript.Shell").Environment("PROCESS")("CLAUDE_USER_DATA_DIR") '
                    f'= "{inst.profile_dir}"'
                )
            content = self._win_vbs(target, args, env_extra)
            with open(vbs_path, "w", encoding="utf-8") as fh:
                fh.write(content)
            inst.launcher = vbs_path
            inst.exe_target = target
            self._win_shortcut(vbs_path, os.path.join(desktop, f"Claude ({inst.name}).lnk"))
            inst.shortcut = os.path.join(desktop, f"Claude ({inst.name}).lnk")
            self.log(f"  + launcher {vbs_path}")

    @staticmethod
    def _win_vbs(exe: str, args: str, env_extra: str) -> str:
        """Build a VBS launcher.

        exe is the full path; args is already prepared (may contain quoted paths).
        VBS-escape: every double-quote in a string literal is written as two.
        """
        lines = [
            "Option Explicit",
            "Dim shell",
            "Set shell = CreateObject(\"WScript.Shell\")",
        ]
        if env_extra:
            lines.append(env_extra)
        full_cmd = f'"{exe}"{args}'
        vbs_escaped = full_cmd.replace('"', '""')
        lines.append(f'shell.Run "{vbs_escaped}", 0, False')
        return "\r\n".join(lines) + "\r\n"

    @staticmethod
    def _win_shortcut(launcher: str, lnk: str) -> None:
        """Create a .lnk pointing at a .vbs via WScript.exe so the icon stays clean."""
        if os.name != "nt":
            return
        import subprocess

        ps = (
            "$ws=New-Object -ComObject WScript.Shell;"
            f"$lnk=$ws.CreateShortcut('{lnk}');"
            f"$lnk.TargetPath='{launcher}';"
            f"$lnk.IconLocation='wscript.exe, 0';"
            "$lnk.Save()"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            timeout=60,
            creationflags=0x08000000,
        )

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
            self.log(f"  + launcher {sh_path}")

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
                    "Terminal=false\n"
                    "Categories=Utility;\n"
                )
            inst.shortcut = desktop_entry
            self.log(f"  + launcher {sh_path}")


def build_instances(names: list[str], profile_meta: dict, platform_obj, primary: bool = True) -> list[Instance]:
    """Create Instance records from user-chosen names."""
    out: list[Instance] = []
    for i, n in enumerate(names):
        safe = n.replace(" ", "") or f"Instance{i+1}"
        out.append(
            Instance(
                name=n,
                profile_dir=platform_obj.profile_dir(safe),
                is_primary=(primary and i == 0),
            )
        )
    return out