"""Setup orchestration: detect -> configure -> patch -> launchers -> verify."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Callable

from . import icons, startup, update_check
from .asar import AsarArchive
from .platform import MANIFEST_FILENAME, ClaudeInstall, Platform, safe_name, validate_names
from .asar_patch import _SHIM_MARKER, AsarPatcher, PatchResult, read_sidecar_version
from .launcher import LauncherBuilder, Instance

LogFn = Callable[[str], None]


@dataclass
class SetupConfig:
    instance_names: list[str]
    base_dir: str | None = None  # where patched copy lives (Windows). None = auto
    patch_copy: bool = True  # Windows MSIX only
    make_shortcuts: bool = True
    # When True the first name reuses the default profile (no --user-data-dir).
    # Off by default: the wizard asks for instances *besides* the original, and a
    # launcher on the default profile just focuses the already-running original.
    primary_is_own: bool = False
    # {name: {"color": "#RRGGBB", "badge": "W"}}. Missing entries keep the
    # style from the previous setup, else get a default palette color/initials.
    styles: dict[str, dict] = field(default_factory=dict)
    # Windows: check for Claude updates at sign-in and offer to update instances.
    update_check: bool = True
    # Rebuild the patched copy even when it is already up to date (--repair).
    force_patch: bool = False

    @property
    def count(self) -> int:
        return max(0, len(self.instance_names))


@dataclass
class SetupResult:
    ok: bool
    message: str = ""
    installs: list[ClaudeInstall] = field(default_factory=list)
    instances: list[Instance] = field(default_factory=list)
    copy_app_dir: str | None = None
    installed_version: str | None = None
    patched_version: str | None = None


class ClaudeSetup:
    def __init__(self, log: LogFn | None = None) -> None:
        self.log = log or (lambda m: None)
        self.platform = Platform()
        # children log through self.log even if it is reassigned later (the GUI does)
        self.launcher = LauncherBuilder(log=lambda m: self.log(m))
        self.patcher = AsarPatcher(log=lambda m: self.log(m))

    def run(self, cfg: SetupConfig) -> SetupResult:
        try:
            return self._run(cfg)
        except Exception as exc:  # noqa: BLE001
            self.log(f"ERROR: {exc}")
            return SetupResult(False, message=str(exc))

    def _run(self, cfg: SetupConfig) -> SetupResult:
        res = SetupResult(ok=True)
        p = self.platform

        self.log(f"Platform: {p.os}")
        problems = validate_names(cfg.instance_names)
        if problems:
            res.ok, res.message = False, "Please fix the instance names:\n" + "\n".join(problems)
            return res
        installs = p.find_claude()
        if not installs:
            res.ok, res.message = False, "Claude Desktop not found. Install it first."
            return res
        res.installs = installs
        for inst in installs:
            self.log(f"  found: [{inst.kind}] {inst.exe_path}")

        # ---- Windows: build one patched copy, reuse for every instance ---- #
        if p.is_windows:
            base = cfg.base_dir or p.root_install_dir()
            os.makedirs(base, exist_ok=True)
            copy_exe = installs[0].exe_path
            copied_app_dir = None
            installed_version = p.installed_version(installs[0])

            res.installs = installs
            res.installed_version = installed_version
            res.patched_version = read_sidecar_version(base)

            if cfg.patch_copy and installs[0].kind in ("msix", "standard"):
                # --- repair detection: did Claude update since last patch? ---
                if res.patched_version and installed_version and res.patched_version != installed_version:
                    self.log(
                        f"  NOTE: Claude was updated from {res.patched_version} to "
                        f"{installed_version} since the last setup. Re-patching now."
                    )
                elif res.patched_version and not installed_version:
                    self.log(f"  NOTE: previous setup tracked version {res.patched_version} (installed version unknown).")

                if not cfg.force_patch and self._copy_is_current(base, installed_version):
                    self.log(f"Patched copy is up to date ({installed_version}); not rebuilding it.")
                    copy_result = PatchResult(True, "up to date", detail=os.path.join(base, "app"))
                else:
                    self.log("Patching a dedicated copy (integrity fuse + asar relocation fix)...")
                    copy_result = self.patcher.patch_copy(
                        installs[0], base, source_version=installed_version
                    )
                if copy_result.ok:
                    copied_app_dir = copy_result.detail
                    copy_exe = os.path.join(copy_result.detail, "Claude.exe")
                    res.copy_app_dir = copied_app_dir
                    res.patched_version = installed_version
                elif copy_result.fatal:
                    res.ok, res.message = False, copy_result.message
                    return res
                else:
                    # the existing copy is untouched by a failed patch, so it is
                    # still safe to keep using it
                    fallback = os.path.join(base, "app", "Claude.exe")
                    if os.path.isfile(fallback):
                        self.log(f"  patch failed ({copy_result.message})")
                        self.log(f"  keeping the existing patched copy (built from "
                                 f"{read_sidecar_version(base) or 'an unknown version'})")
                        copy_exe = fallback
                        copied_app_dir = os.path.join(base, "app")
                        res.copy_app_dir = copied_app_dir
                    else:
                        res.ok, res.message = False, copy_result.message
                        return res

            instances = self._build_instances(cfg)
            self._merge_existing(base, instances, res)
            self._make_icons(instances, base, ".ico", installs[0])
            desktop = p.desktop_dir()
            self.launcher.build_windows(instances, copy_exe, base, desktop)
            self._apply_startup(instances)
            self._write_manifest(base, instances)
            res.instances = instances
            try:
                if cfg.update_check:
                    update_check.register(base, self.log)
                else:
                    update_check.unregister(self.log)
            except Exception as exc:  # noqa: BLE001
                self.log(f"  NOTE: could not change the sign-in update check: {exc}")

        # ---- macOS ---- #
        elif p.is_macos:
            instances = self._build_instances(cfg)
            base = cfg.base_dir or p.root_install_dir()
            self._make_icons(instances, base, ".icns", installs[0])
            if installs[0].kind == "app":
                desktop = p.desktop_dir()
                self.launcher.build_macos(instances, installs[0].exe_path or "", desktop, home=p.home)
            self._apply_startup(instances)
            self._write_manifest(base, instances)
            res.instances = instances

        # ---- Linux ---- #
        elif p.is_linux:
            instances = self._build_instances(cfg)
            base = cfg.base_dir or p.root_install_dir()
            self._make_icons(instances, base, ".png", installs[0])
            desktop = p.desktop_dir()
            applications = os.path.join(p.home, ".local", "share", "applications")
            exe = installs[0].exe_path or "claude"
            self.launcher.build_linux(instances, exe, desktop, applications)
            self._apply_startup(instances)
            self._write_manifest(base, instances)
            res.instances = instances

        self._verify_profiles(res)
        res.ok = True
        res.message = "Setup complete."
        return res

    def _build_instances(self, cfg: SetupConfig) -> list[Instance]:
        names = list(cfg.instance_names)
        if not names:
            return []
        p = self.platform
        previous = {m["name"]: m for m in p.load_manifest()}
        instances = []
        for i, raw in enumerate(names):
            n = raw.strip()
            style = cfg.styles.get(raw) or cfg.styles.get(n) or previous.get(n) or {}
            instances.append(
                Instance(
                    name=n,
                    profile_dir=p.profile_dir(safe_name(n)),
                    is_primary=(cfg.primary_is_own and i == 0),
                    color=icons.normalize_color(style.get("color", "")) or icons.default_color(i),
                    badge=(style["badge"] if "badge" in style else icons.default_badge(n))[:2],
                    # explicit choice from this run, else whatever is in effect now
                    # (the Startup screen and Task Manager can change it between runs)
                    startup=(bool(chosen["startup"]) if "startup" in (chosen := cfg.styles.get(raw)
                                                                       or cfg.styles.get(n) or {})
                             else startup.is_enabled(n, p)),
                )
            )
        return instances

    def _copy_is_current(self, base: str, installed_version: str | None) -> bool:
        """True when <base>/app was built from the installed Claude by this
        version of the tool (so rebuilding it would change nothing)."""
        asar = os.path.join(base, "app", "resources", "app.asar")
        if not installed_version or read_sidecar_version(base) != installed_version:
            return False
        if not os.path.isfile(os.path.join(base, "app", "Claude.exe")) or not os.path.isfile(asar):
            return False
        try:
            archive = AsarArchive(asar)
            main = json.loads(archive.read("package.json")).get("main") or "index.js"
            entry = main[2:] if main.startswith("./") else main
            return _SHIM_MARKER.encode() in archive.read(entry)
        except Exception:  # noqa: BLE001
            return False

    def _apply_startup(self, instances: list[Instance]) -> None:
        for inst in instances:
            try:
                startup.set_enabled(inst, inst.startup, self.platform, self.log)
            except Exception as exc:  # noqa: BLE001
                self.log(f"  NOTE: could not change startup for {inst.name}: {exc}")

    def _make_icons(self, instances: list[Instance], base: str, ext: str, install: ClaudeInstall) -> None:
        """Write one colored icon per instance into <base>/icons."""
        if not icons.available():
            self.log("  NOTE: Pillow not available; instances keep Claude's own icon")
            return
        source = icons.claude_icon_source(install.resources_dir)
        for inst in instances:
            path = os.path.join(base, "icons", f"Claude-{safe_name(inst.name)}{ext}")
            try:
                inst.icon = icons.write_icon(path, inst.color, inst.badge, source)
                self.log(f"  icon {inst.color} '{inst.badge}' -> {path}")
            except Exception as exc:  # noqa: BLE001
                self.log(f"  NOTE: icon for {inst.name} not created ({exc})")

    def _verify_profiles(self, res: SetupResult) -> None:
        for inst in res.instances:
            os.makedirs(inst.profile_dir, exist_ok=True)
            self.log(f"  profile ready: {inst.profile_dir}")

    def _merge_existing(self, base: str, instances: list[Instance], res: SetupResult) -> None:
        """Merge instance profile dirs that already exist into the fresh list.

        Re-running the wizard (e.g. after a Claude update) should re-generate
        launchers/shortcuts for instances that already have a profile instead of
        overwriting or skipping them.
        """
        existing = [i for i in instances if os.path.isdir(i.profile_dir)]
        if not existing:
            return
        self.log(
            f"  NOTE: {len(existing)} existing profile(s) detected — "
            "launchers will be refreshed, profiles preserved."
        )
        for inst in existing:
            self.log(f"    keep profile: {inst.profile_dir}")

    def _write_manifest(self, base: str, instances: list[Instance]) -> None:
        """Record the instances so a later run (repair) can find them again."""
        os.makedirs(base, exist_ok=True)
        path = os.path.join(base, MANIFEST_FILENAME)
        data = [{"name": i.name, "profile_dir": i.profile_dir, "launcher": i.launcher,
                 "color": i.color, "badge": i.badge, "icon": i.icon, "startup": i.startup}
                for i in instances]
        # Instances left out of this run keep working (their shortcuts point at
        # the same copy), so keep them listed; removal is explicit (remove.py).
        current = {i.name.lower() for i in instances}
        data += [m for m in self.platform.load_manifest() if m["name"].lower() not in current]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"instances": data}, fh, indent=2)
