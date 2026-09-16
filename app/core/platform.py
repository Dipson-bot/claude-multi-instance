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
                    "Select-Object -First 1 | Select-Object InstallLocation,Version | ConvertTo-Json",
                ],
                capture_output=True,
                text=True,
                timeout=60,
                creationflags=self._hide_window(),
            )
            data = json.loads(result.stdout.strip() or "{}")
            loc = data.get("InstallLocation", "") if isinstance(data, dict) else ""
            if not loc and isinstance(data, dict):
                loc = ""
            if loc:
                exe = os.path.join(loc, "app", "Claude.exe")
                if os.path.isfile(exe):
                    out.append(
                        ClaudeInstall(
                            kind="msix",
                            exe_path=exe,
                            app_dir=os.path.dirname(exe),
                            resources_dir=os.path.join(os.path.dirname(exe), "resources"),
                            version=data.get("Version") if isinstance(data, dict) else None,
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

    def installed_version(self, inst: ClaudeInstall) -> str | None:
        """Best-effort full version string for an install.

        MSIX carries it in the package; standalone/copy installs carry it in the
        asar copy or the app bundle. Falls back to reading package.json from the
        asar (works when @electron/asar is available).
        """
        if inst.version:
            return inst.version
        # macOS: Info.plist
        if self.is_macos and inst.app_dir:
            plist = inst.app_dir.replace("Contents/MacOS/Claude", "Contents/Info.plist")
            if plist.endswith("Info.plist") and os.path.isfile(plist):
                try:
                    import plistlib

                    with open(plist, "rb") as fh:
                        info = plistlib.load(fh)
                    ver = info.get("CFBundleShortVersionString") or info.get("CFBundleVersion")
                    if ver:
                        return str(ver)
                except Exception:
                    pass
        # generic: read resources.pak-named version marker from asar is heavy;
        # instead read version from a sidecar we wrote at patch time
        if inst.resources_dir:
            sidecar = os.path.join(inst.resources_dir, "..", "..", "claude-setup-version.txt")
            sidecar = os.path.abspath(sidecar)
            if os.path.isfile(sidecar):
                try:
                    return open(sidecar, encoding="utf-8").read().strip() or None
                except Exception:
                    return None
        return None

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

    # ---- misc helpers ---- #

    def detect_existing_instances(self) -> list[str]:
        """Return the names of instances already set up by this wizard.

        Scans launchers on disk (the same files we create). Used to prefill the
        wizard after a Claude update so the user can simply re-run to repair.
        """
        names: list[str] = []
        root = self.root_install_dir()
        if not os.path.isdir(root):
            return names

        if self.is_windows:
            import glob

            for vbs in glob.glob(os.path.join(root, "Claude-*.vbs")):
                base = os.path.basename(vbs)
                if base.lower().startswith("claude-") and base.lower().endswith(".vbs"):
                    names.append(base[len("Claude-"):-len(".vbs")])
        elif self.is_macos:
            desktop = os.path.join(self.home, "Desktop")
            for fn in sorted(os.listdir(desktop)) if os.path.isdir(desktop) else []:
                if fn.startswith("Claude-") and fn.endswith(".command"):
                    names.append(fn[len("Claude-"):-len(".command")])
        elif self.is_linux:
            desktop = os.path.join(self.home, "Desktop")
            for fn in sorted(os.listdir(desktop)) if os.path.isdir(desktop) else []:
                if fn.startswith("Claude-") and fn.endswith(".sh"):
                    names.append(fn[len("Claude-"):-len(".sh")])
        return [n for n in names if n]

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
        """Default base folder to place the patched install cluster.

        Prefers an existing cluster under the user home (`~/ClaudeInstances`),
        which is what setups created so far use, falling back to a system-local
        default when no cluster exists yet.
        """
        home_cluster = os.path.join(self.home, "ClaudeInstances")
        if os.path.isdir(home_cluster):
            return home_cluster
        if self.is_windows:
            return os.path.join(os.environ.get("LOCALAPPDATA", self.home), "ClaudeInstances")
        return home_cluster