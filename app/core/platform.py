"""Platform detection and Claude Desktop discovery."""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field


@dataclass
class ClaudeInstall:
    """A detectable Claude Desktop installation."""

    kind: str  # "msix" | "copy" | "standard" | "app" | "unknown"
    exe_path: str | None = None
    app_dir: str | None = None
    resources_dir: str | None = None
    asar_path: str | None = None
    version: str | None = None
    notes: list[str] = field(default_factory=list)


class Platform:
    """Holds OS-aware paths and helpers."""

    def __init__(self) -> None:
        self.os = platform.system().lower()  # windows / darwin / linux
        self.is_windows = self.os == "windows"
        self.is_macos = self.os == "darwin"
        self.is_linux = self.os == "linux"
        self.home = os.path.expanduser("~")

    # ---- data dir ---- #

    @property
    def local_data_root(self) -> str:
        if self.is_windows:
            return os.environ.get("LOCALAPPDATA", os.path.join(self.home, "AppData", "Local"))
        if self.is_macos:
            return os.path.join(self.home, "Library", "Application Support")
        return os.path.join(self.home, ".config")

    @property
    def roaming_data_root(self) -> str:
        if self.is_windows:
            return os.environ.get("APPDATA", os.path.join(self.home, "AppData", "Roaming"))
        return self.local_data_root

    def profile_dir(self, name: str) -> str:
        """Default profile location for an instance named `name`."""
        return os.path.join(self.local_data_root, f"Claude-{name}")

    @property
    def default_3p_profile(self) -> str:
        """The built-in 3P profile directory."""
        if self.is_windows:
            return os.path.join(self.local_data_root, "Claude-3p")
        if self.is_macos:
            return os.path.join(self.home, "Library", "Application Support", "Claude-3p")
        return os.path.join(self.home, ".config", "Claude-3p")

    # ---- executable discovery ---- #

    def find_claude(self, prefer_copy_from: str | None = None) -> list[ClaudeInstall]:
        """Discover installed Claude Desktop executables."""
        found: list[ClaudeInstall] = []

        if self.is_windows:
            found.extend(self._find_windows_msix())
            found.extend(self._find_windows_standalone())
        elif self.is_macos:
            found.extend(self._find_macos())
        elif self.is_linux:
            found.extend(self._find_linux())

        # de-dupe on exe_path
        seen = set()
        unique = []
        for inst in found:
            if inst.exe_path and inst.exe_path in seen:
                continue
            if inst.exe_path:
                seen.add(inst.exe_path)
            unique.append(inst)
        return unique

    def _find_windows_msix(self) -> list[ClaudeInstall]:
        out: list[ClaudeInstall] = []
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-AppxPackage -Name 'Claude' | Sort-Object Version -Descending | "
                    "Select-Object -First 1 | Select-Object -ExpandProperty InstallLocation",
                ],
                capture_output=True,
                text=True,
                timeout=60,
                creationflags=self._hide_window(),
            )
            loc = result.stdout.strip()
            if loc:
                exe = os.path.join(loc, "app", "Claude.exe")
                if os.path.isfile(exe):
                    out.append(
                        ClaudeInstall(
                            kind="msix",
                            exe_path=exe,
                            app_dir=os.path.dirname(exe),
                            resources_dir=os.path.join(os.path.dirname(exe), "resources"),
                        )
                    )
        except Exception:
            pass
        return out

    def _find_windows_standalone(self) -> list[ClaudeInstall]:
        out: list[ClaudeInstall] = []
        # typical standalone installs
        candidates = [
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Claude", "Claude.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "AnthropicClaude", "Claude.exe"),
        ]
        for exe in candidates:
            if exe and os.path.isfile(exe):
                app_dir = os.path.dirname(exe)
                res = os.path.join(app_dir, "resources")
                out.append(
                    ClaudeInstall(kind="standard", exe_path=exe, app_dir=app_dir, resources_dir=res)
                )
        return out

    def _find_macos(self) -> list[ClaudeInstall]:
        out: list[ClaudeInstall] = []
        for path in [
            "/Applications/Claude.app",
            os.path.join(self.home, "Applications", "Claude.app"),
        ]:
            if os.path.isdir(path):
                exe = os.path.join(path, "Contents", "MacOS", "Claude")
                res = os.path.join(path, "Contents", "Resources")
                if os.path.isfile(exe):
                    out.append(
                        ClaudeInstall(
                            kind="app", exe_path=exe, app_dir=exe, resources_dir=res
                        )
                    )
        return out

    def _find_linux(self) -> list[ClaudeInstall]:
        out: list[ClaudeInstall] = []
        for name in ["claude", "Claude"]:
            exe = shutil.which(name)
            if exe:
                app_dir = os.path.dirname(exe)
                out.append(
                    ClaudeInstall(
                        kind="standard", exe_path=exe, app_dir=app_dir, resources_dir=None
                    )
                )
        return out

    # ---- misc helpers ---- #

    @staticmethod
    def _hide_window() -> int:
        if os.name == "nt":
            return 0x08000000  # CREATE_NO_WINDOW
        return 0

    def ensure_node(self) -> tuple[bool, str]:
        """Check node/npx availability (needed for MSIX asar patching)."""
        exe = shutil.which("node")
        if not exe:
            return False, "Node.js not found. Install from https://nodejs.org"
        return True, exe

    def root_install_dir(self) -> str:
        """Default base folder to place the patched install cluster."""
        if self.is_windows:
            return os.path.join(os.environ.get("LOCALAPPDATA", self.home), "ClaudeInstances")
        if self.is_macos:
            return os.path.join(self.home, "ClaudeInstances")
        return os.path.join(self.home, "ClaudeInstances")