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


MANIFEST_FILENAME = "instances.json"

_BAD_CHARS = set('<>:"/\\|?*')
_WIN_DEVICES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                *(f"LPT{i}" for i in range(1, 10))}
# Suffixes Claude itself uses for its own profile folders (Claude-3p, ...).
_RESERVED = {"3p", "3p-dev", "dev"}
MAX_NAME_LEN = 40
# Package family names of the Microsoft Store Claude (seen in Claude's own code).
_MSIX_FAMILIES = ("Claude_pzs8sxrjxfjjc", "AnthropicPBC.Claude_fnn82j28hfe8t")


def safe_name(name: str) -> str:
    """Folder-safe form of an instance name: profile is Claude-<safe_name>."""
    return name.strip().replace(" ", "")


def validate_names(names: list[str]) -> list[str]:
    """Return human-readable problems with the chosen instance names ([] = ok)."""
    problems: list[str] = []
    seen: dict[str, str] = {}
    for raw in names:
        name = raw.strip()
        label = f'"{raw}"'
        if not name:
            problems.append("Instance names cannot be empty.")
            continue
        if len(name) > MAX_NAME_LEN:
            problems.append(f"{label} is too long (max {MAX_NAME_LEN} characters).")
        bad = sorted({c for c in name if c in _BAD_CHARS or ord(c) < 32})
        if bad:
            shown = " ".join(c if ord(c) >= 32 else "control character" for c in bad)
            problems.append(f"{label} contains characters that are not allowed: {shown}")
        if name.endswith("."):
            problems.append(f"{label} cannot end with a dot.")
        s = safe_name(name)
        if s.upper() in _WIN_DEVICES or s.split(".")[0].upper() in _WIN_DEVICES:
            problems.append(f"{label} is a reserved Windows name.")
        if s.lower() in _RESERVED:
            problems.append(f"{label} would reuse Claude's own profile folder (Claude-{s}).")
        key = s.lower()
        if key in seen:
            problems.append(f"{label} and \"{seen[key]}\" would share the same profile folder.")
        else:
            seen[key] = raw
    return list(dict.fromkeys(problems))


@dataclass
class ProfileFolder:
    """A Claude profile folder found on disk."""

    path: str
    last_used: float  # newest modification time of its top-level entries
    is_main: bool  # used by the normal (unmodified) Claude app
    third_party: bool  # set up for third-party inference (deploymentMode 3p)

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    @property
    def label(self) -> str:
        if self.is_main:
            return "Your main Claude" + (" (third-party)" if self.third_party else "")
        return self.name + (" (third-party inference)" if self.third_party else "")


def is_profile_dir(path: str) -> bool:
    """True when a folder holds Claude data (not just an empty folder)."""
    return any(os.path.exists(os.path.join(path, f)) for f in ("Local State", "config.json", "Preferences"))


def same_path(a: str, b: str) -> bool:
    return os.path.normcase(os.path.abspath(a)).rstrip("\\/") == os.path.normcase(os.path.abspath(b)).rstrip("\\/")


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

    def main_profiles(self) -> list[str]:
        """Folders the normal Claude app uses itself (never given to an instance:
        two Claudes cannot open the same folder at once)."""
        if self.is_windows:
            mains = [os.path.join(self.roaming_data_root, "Claude"), self.default_3p_profile]
            # The Microsoft Store Claude is sandboxed: Windows stores what it
            # writes to AppData inside its package folder instead.
            for family in _MSIX_FAMILIES:
                cache = os.path.join(self.local_data_root, "Packages", family, "LocalCache")
                mains += [os.path.join(cache, "Roaming", "Claude"), os.path.join(cache, "Local", "Claude-3p")]
            return mains
        return [os.path.join(self.local_data_root, "Claude"), self.default_3p_profile]

    def profile_folders(self) -> list[ProfileFolder]:
        """Claude folders that hold data, newest first."""
        mains = self.main_profiles()
        candidates = list(mains)
        if os.path.isdir(self.local_data_root):
            candidates += [os.path.join(self.local_data_root, d) for d in os.listdir(self.local_data_root)
                           if d.lower().startswith("claude")]
        out: list[ProfileFolder] = []
        seen: set[str] = set()
        for path in candidates:
            key = os.path.normcase(os.path.abspath(path))
            if key in seen or not os.path.isdir(path) or not is_profile_dir(path):
                continue
            seen.add(key)
            # top-level entries plus folders Claude writes to on every run
            # (folder times alone miss activity deeper down)
            last = 0.0
            for sub in [path] + [os.path.join(path, d) for d in ("logs", "Logs", "Network", "Session Storage", "sentry")]:
                try:
                    last = max([last] + [e.stat().st_mtime for e in os.scandir(sub)])
                except OSError:
                    pass
            third = False
            try:
                with open(os.path.join(path, "claude_desktop_config.json"), encoding="utf-8") as fh:
                    third = json.load(fh).get("deploymentMode") == "3p"
            except Exception:
                pass
            out.append(ProfileFolder(path, last, any(same_path(path, m) for m in mains), third))
        return sorted(out, key=lambda f: f.last_used, reverse=True)

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

    def _find_linux(self) -> list[ClaudeInstall]:
        """Community Linux builds (there is no official one); best effort."""
        out: list[ClaudeInstall] = []
        for exe in [shutil.which("claude-desktop"), "/usr/bin/claude-desktop",
                    "/opt/Claude/claude", "/usr/lib/claude-desktop/claude-desktop"]:
            if exe and os.path.isfile(exe):
                out.append(ClaudeInstall(kind="standard", exe_path=exe, app_dir=os.path.dirname(exe)))
        return out

    # ---- misc helpers ---- #

    def detect_existing_instances(self) -> list[str]:
        """Return the names of instances already set up by this wizard.

        Scans launchers on disk (the same files we create). Used to prefill the
        wizard after a Claude update so the user can simply re-run to repair.
        """
        names: list[str] = [i["name"] for i in self.load_manifest()]
        root = self.root_install_dir()

        # launchers from older versions of this tool (no manifest)
        if self.is_windows and os.path.isdir(root):
            import glob

            for vbs in glob.glob(os.path.join(root, "Claude-*.vbs")):
                base = os.path.basename(vbs)
                if base.lower().startswith("claude-") and base.lower().endswith(".vbs"):
                    names.append(base[len("Claude-"):-len(".vbs")])
        elif self.is_macos:
            desktop = self.desktop_dir()
            for fn in sorted(os.listdir(desktop)) if os.path.isdir(desktop) else []:
                if fn.startswith("Claude-") and fn.endswith(".command"):
                    names.append(fn[len("Claude-"):-len(".command")])
        elif self.is_linux:
            desktop = self.desktop_dir()
            for fn in sorted(os.listdir(desktop)) if os.path.isdir(desktop) else []:
                if fn.startswith("Claude-") and fn.endswith(".sh"):
                    names.append(fn[len("Claude-"):-len(".sh")])
        return list(dict.fromkeys(n for n in names if n))

    def desktop_dir(self) -> str:
        """The user's real Desktop folder (OneDrive can redirect it on Windows)."""
        if self.is_windows:
            try:
                import ctypes

                buf = ctypes.create_unicode_buffer(260)
                # CSIDL_DESKTOPDIRECTORY = 0x10
                if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0 and buf.value:
                    return buf.value
            except Exception:
                pass
            return os.path.join(os.environ.get("USERPROFILE", self.home), "Desktop")
        return os.path.join(self.home, "Desktop")

    def load_manifest(self) -> list[dict]:
        """Instances recorded by the last setup: [{name, profile_dir, color, badge, ...}]."""
        try:
            with open(os.path.join(self.root_install_dir(), MANIFEST_FILENAME), encoding="utf-8") as fh:
                items = json.load(fh).get("instances", [])
            return [i for i in items if isinstance(i, dict) and i.get("name")]
        except Exception:
            return []

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