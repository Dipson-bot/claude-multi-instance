"""Setup orchestration: detect -> configure -> patch -> launchers -> verify."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from typing import Callable

from .platform import Platform, ClaudeInstall
from .asar_patch import AsarPatcher, read_sidecar_version
from .launcher import LauncherBuilder, Instance

LogFn = Callable[[str], None]


@dataclass
class SetupConfig:
    instance_names: list[str]
    base_dir: str | None = None  # where patched copy lives (Windows). None = auto
    patch_copy: bool = True  # Windows MSIX only
    make_shortcuts: bool = True
    primary_is_own: bool = True  # first named instance keeps the default profile/install

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
        self.launcher = LauncherBuilder(log=self.log)
        self.patcher = AsarPatcher(log=self.log)

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

                self.log("Patching a dedicated copy (integrity fuse + asar relocation fix)...")
                copy_result = self.patcher.patch_copy(
                    installs[0], base, source_version=installed_version
                )
                if copy_result.ok:
                    copied_app_dir = copy_result.detail
                    copy_exe = os.path.join(copy_result.detail, "Claude.exe")
                    res.copy_app_dir = copied_app_dir
                    res.patched_version = installed_version
                else:
                    # try fallback: use an existing patched copy if present
                    fallback = os.path.join(base, "app", "Claude.exe")
                    if os.path.isfile(fallback):
                        self.log(f"  patch failed ({copy_result.message}), using existing patched copy")
                        copy_exe = fallback
                        copied_app_dir = os.path.join(base, "app")
                        res.copy_app_dir = copied_app_dir
                    else:
                        res.ok, res.message = False, copy_result.message
                        return res

            instances = self._build_instances(cfg)
            self._merge_existing(base, instances, res)
            desktop = os.path.join(os.environ.get("USERPROFILE", p.home), "Desktop")
            self.launcher.build_windows(instances, copy_exe, base, desktop)
            res.instances = instances

        # ---- macOS ---- #
        elif p.is_macos:
            instances = self._build_instances(cfg)
            if installs[0].kind == "app":
                desktop = os.path.join(p.home, "Desktop")
                self.launcher.build_macos(instances, installs[0].app_dir or "", desktop)
            res.instances = instances

        # ---- Linux ---- #
        elif p.is_linux:
            instances = self._build_instances(cfg)
            desktop = os.path.join(p.home, "Desktop")
            applications = os.path.join(p.home, ".local", "share", "applications")
            exe = installs[0].exe_path or "claude"
            self.launcher.build_linux(instances, exe, desktop, applications)
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
        instances = []
        for i, n in enumerate(names):
            safe = n.replace(" ", "")
            instances.append(
                Instance(
                    name=n,
                    profile_dir=p.profile_dir(safe),
                    is_primary=(cfg.primary_is_own and i == 0),
                )
            )
        return instances

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