"""Remove instances created by this tool, or uninstall it completely.

Removing an instance deletes its launchers, desktop shortcut and icon, and
drops it from instances.json. Its profile folder (sign-ins, local chat cache,
settings) is only deleted when asked, and then goes to the Recycle Bin / Trash
so it can be restored. Nothing outside this tool's own files is touched: the
original Claude, its profiles (Claude, Claude-3p) and the account on claude.ai
are never affected.
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Callable

from . import startup, update_check
from .asar_patch import _SIDECAR_FILENAME, _norm, claude_processes_under
from .launcher import Instance, mac_app_path
from .platform import _RESERVED, MANIFEST_FILENAME, Platform, safe_name

LogFn = Callable[[str], None]


@dataclass
class KnownInstance:
    name: str
    profile_dir: str
    files: list[str] = field(default_factory=list)  # launchers, shortcuts, icon
    color: str = ""
    badge: str = ""

    def profile_size(self) -> int:
        total = 0
        for root, _dirs, files in os.walk(self.profile_dir):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
        return total


@dataclass
class RemoveResult:
    ok: bool
    message: str
    removed: list[str] = field(default_factory=list)


def known_instances(p: Platform | None = None) -> list[KnownInstance]:
    """Every instance this tool created: from instances.json, plus launchers
    left by older versions that had no manifest."""
    p = p or Platform()
    base = p.root_install_dir()
    out: dict[str, KnownInstance] = {}
    for m in p.load_manifest():
        name = m["name"]
        inst = KnownInstance(name, m.get("profile_dir") or p.profile_dir(safe_name(name)),
                             color=m.get("color", ""), badge=m.get("badge", ""))
        inst.files += [f for f in (m.get("launcher"), m.get("icon")) if f]
        out[name.lower()] = inst
    for name in p.detect_existing_instances():
        out.setdefault(name.lower(), KnownInstance(name, p.profile_dir(safe_name(name))))
    for inst in out.values():
        inst.files = sorted({f for f in inst.files + _instance_files(p, base, inst.name) if os.path.lexists(f)})
    return list(out.values())


def _instance_files(p: Platform, base: str, name: str) -> list[str]:
    s = safe_name(name)
    desktop = p.desktop_dir()
    files = [
        os.path.join(base, f"Claude-{name}.lnk"),
        os.path.join(base, f"Claude-{name}.vbs"),  # older versions
        os.path.join(base, f"Claude-{name}.ico"),  # older versions
        os.path.join(desktop, f"Claude ({name}).lnk"),
        *([os.path.join(p.start_menu_dir(), f"Claude {name}.lnk")] if p.is_windows else []),
        os.path.join(desktop, f"Claude-{name}.command"),  # older versions
        os.path.join(desktop, f"Claude {name}"),  # macOS: Desktop shortcut to the app
        mac_app_path(p.home, name),  # macOS: ~/Applications/Claude <name>.app
        os.path.join(desktop, f"Claude-{name}.sh"),
        os.path.join(p.home, ".local", "share", "applications", f"Claude-{name}.desktop"),
    ]
    files += glob.glob(os.path.join(glob.escape(base), "icons", f"Claude-{glob.escape(s)}.*"))
    return files


def remove_launchers(name: str, p: Platform | None = None, log: LogFn | None = None) -> list[str]:
    """Delete one instance's shortcuts, launcher, icon and startup entry, but
    never its profile folder. Returns problems ([] = all removed)."""
    p = p or Platform()
    log = log or (lambda m: None)
    problems = []
    for f in _instance_files(p, p.root_install_dir(), name):
        if not os.path.lexists(f):
            continue
        try:
            if os.path.isdir(f) and not os.path.islink(f):
                shutil.rmtree(f)
            else:
                os.remove(f)
            log(f"  deleted {f}")
        except OSError as exc:
            problems.append(f"{f}: {exc}")
    if p.is_windows:
        try:
            os.rmdir(p.start_menu_dir())  # only when empty
        except OSError:
            pass
    try:
        startup.set_enabled(Instance(name, ""), False, p, log)
    except OSError as exc:
        problems.append(f"startup entry for {name}: {exc}")
    return problems


def _safe_profile(p: Platform, path: str) -> bool:
    """Only ever delete Claude-<instance> folders directly under the data root,
    never the original Claude's own profiles."""
    parent = _norm(os.path.dirname(path))
    base = os.path.basename(os.path.normpath(path))
    if parent != _norm(p.local_data_root) or not base.startswith("Claude-"):
        return False
    suffix = base[len("Claude-"):]
    return bool(suffix) and suffix.lower() not in _RESERVED


def running_instances(p: Platform, profile_dir: str) -> int:
    """How many processes are using this profile right now."""
    want = os.path.normcase(os.path.normpath(profile_dir))
    if p.is_windows:
        procs = claude_processes_under(os.path.join(p.root_install_dir(), "app"))
        return sum(1 for pr in procs if want in os.path.normcase(pr["cmd"].replace("/", "\\")))
    try:
        out = subprocess.run(["ps", "-axo", "command="], capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return 0
    return sum(1 for line in out.splitlines() if f"--user-data-dir={profile_dir}" in line
               or f'--user-data-dir="{profile_dir}"' in line)


def to_trash(path: str) -> None:
    """Move a file/folder to the Recycle Bin (Windows) or Trash (macOS/Linux)."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [("hwnd", wintypes.HWND), ("wFunc", ctypes.c_uint),
                        ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                        ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                        ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]

        FO_DELETE = 3
        # allow undo (Recycle Bin), no prompts, but warn instead of silently
        # deleting permanently when an item is too big for the Recycle Bin
        flags = 0x40 | 0x10 | 0x04 | 0x400 | 0x4000
        op = SHFILEOPSTRUCTW(None, FO_DELETE, os.path.abspath(path) + "\0", None, flags, False, None, None)
        rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        if rc != 0 or op.fAnyOperationsAborted or os.path.exists(path):
            raise OSError(f"could not move {path} to the Recycle Bin (code {rc})")
        return
    if sys.platform == "darwin":
        trash = os.path.expanduser("~/.Trash")
    else:
        trash = os.path.join(os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")), "Trash")
        os.makedirs(os.path.join(trash, "info"), exist_ok=True)
        trash = os.path.join(trash, "files")
    os.makedirs(trash, exist_ok=True)
    dst = os.path.join(trash, os.path.basename(path))
    if os.path.exists(dst):
        dst += time.strftime("-%Y%m%d-%H%M%S")
    shutil.move(path, dst)
    if sys.platform != "darwin":
        info = os.path.join(os.path.dirname(os.path.dirname(dst)), "info", os.path.basename(dst) + ".trashinfo")
        with open(info, "w", encoding="utf-8") as fh:
            fh.write(f"[Trash Info]\nPath={os.path.abspath(path)}\n"
                     f"DeletionDate={time.strftime('%Y-%m-%dT%H:%M:%S')}\n")


def remove_instances(names: list[str], delete_data: bool = False, uninstall: bool = False,
                     log: LogFn | None = None) -> RemoveResult:
    """Remove the named instances. With uninstall=True (only allowed when no
    instances would remain) also remove the patched copy and the update check."""
    log = log or (lambda m: None)
    p = Platform()
    base = p.root_install_dir()
    known = {i.name.lower(): i for i in known_instances(p)}
    targets = []
    for n in names:
        inst = known.get(n.strip().lower())
        if not inst:
            return RemoveResult(False, f'"{n}" is not an instance created by this tool.')
        targets.append(inst)
    remaining = [i for k, i in known.items() if i not in targets]
    if uninstall and remaining:
        return RemoveResult(False, "Full uninstall removes the shared Claude copy, so every instance "
                                   "must be removed. Still present: " + ", ".join(i.name for i in remaining))

    busy = [f"{i.name} ({c} process(es))" for i in targets if (c := running_instances(p, i.profile_dir))]
    if uninstall and p.is_windows:
        n_app = len(claude_processes_under(os.path.join(base, "app")))
        if n_app and not busy:
            busy.append(f"the shared Claude copy ({n_app} process(es))")
    if busy:
        return RemoveResult(False, "Close these Claude instances first (check the system tray too): "
                                   + ", ".join(busy))

    removed: list[str] = []
    problems: list[str] = []
    for inst in targets:
        log(f"Removing {inst.name}...")
        for f in inst.files:
            try:
                if os.path.isdir(f) and not os.path.islink(f):
                    shutil.rmtree(f)  # macOS launcher app
                else:
                    os.remove(f)
                log(f"  deleted {f}")
            except FileNotFoundError:
                pass
            except OSError as exc:
                problems.append(f"{f}: {exc}")
        try:
            startup.set_enabled(Instance(inst.name, inst.profile_dir), False, p, log)
        except OSError as exc:
            problems.append(f"startup entry for {inst.name}: {exc}")
        if delete_data and os.path.isdir(inst.profile_dir):
            if not _safe_profile(p, inst.profile_dir):
                problems.append(f"{inst.profile_dir}: not an instance profile folder, left alone")
            else:
                try:
                    to_trash(inst.profile_dir)
                    log(f"  moved profile to the Recycle Bin/Trash: {inst.profile_dir}")
                except OSError as exc:
                    problems.append(f"{inst.profile_dir}: {exc}")
        elif os.path.isdir(inst.profile_dir):
            log(f"  kept profile: {inst.profile_dir}")
        removed.append(inst.name)

    _rewrite_manifest(p, base, {i.name.lower() for i in targets})
    if p.is_windows:
        try:
            os.rmdir(p.start_menu_dir())  # the "Claude Instances" folder, once empty
        except OSError:
            pass

    if uninstall:
        log("Removing the shared Claude copy and the update reminder...")
        try:
            update_check.unregister(log)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"update check: {exc}")
        running_exe = os.path.normcase(os.path.abspath(sys.executable))
        for path in [os.path.join(base, "app"), *glob.glob(os.path.join(glob.escape(base), "app.old-*")),
                     os.path.join(base, "app.new"), os.path.join(base, "icons"),
                     os.path.join(base, _SIDECAR_FILENAME), os.path.join(base, "update-dismissed.txt"),
                     os.path.join(base, MANIFEST_FILENAME), os.path.join(base, update_check._TOOL_EXE)]:
            if not os.path.exists(path):
                continue
            if os.path.normcase(os.path.abspath(path)) == running_exe:
                problems.append(f"{path}: this tool is running from it; delete it afterwards")
                continue
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
                log(f"  deleted {path}")
            except OSError as exc:
                problems.append(f"{path}: {exc}")
        if p.is_windows:
            try:
                os.rmdir(p.start_menu_dir())  # only if empty
            except OSError:
                pass
        try:
            os.rmdir(base)  # only if nothing else is left in it
            log(f"  deleted {base}")
        except OSError:
            pass

    msg = f"Removed: {', '.join(removed)}." if removed else "Nothing removed."
    if uninstall:
        msg += " The shared Claude copy was removed; your original Claude is unchanged."
    if removed:
        msg += (" If you pinned one of these to the Dock, remove it there by hand."
                if p.is_macos else
                " If you pinned one of these to the taskbar, right-click the pin and choose Unpin.")
    if problems:
        msg += "\n\nSome items could not be removed:\n" + "\n".join(problems)
    return RemoveResult(not problems, msg, removed)


def _rewrite_manifest(p: Platform, base: str, drop: set[str]) -> None:
    path = os.path.join(base, MANIFEST_FILENAME)
    if not os.path.isfile(path):
        return
    keep = [m for m in p.load_manifest() if m["name"].lower() not in drop]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"instances": keep}, fh, indent=2)
