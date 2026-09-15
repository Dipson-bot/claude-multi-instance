"""Windows MSIX asar patching + Electron fuse flip.

Encapsulates the exact, verified fix from the research session:
  1. Copy app from WindowsApps out to a working dir.
  2. Extract app.asar (npx @electron/asar).
  3. Patch DW()/Cl() in the main bundle so --user-data-dir is honored
     (3P relocation block becomes a no-op).
  4. Repack with native files left unpacked.
  5. Disable EnableEmbeddedAsarIntegrityValidation fuse on the copy exe.

Requires Node.js (npx) on Windows. Non-Windows installs do NOT need this.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable

from .platform import ClaudeInstall

LogFn = Callable[[str], None]

_UNPACK_GLOB = r"{*.node,*.exe,*.dll}"

# Files that must remain unpacked inside app.asar.unpacked/
_NATIVE_SUFFIXES = (".node", ".exe", ".dll", ".pak")


@dataclass
class PatchResult:
    ok: bool
    message: str
    detail: str = ""


class AsarPatcher:
    def __init__(self, node_exe: str | None = None, log: LogFn | None = None) -> None:
        self.node_exe = node_exe
        self.log = log or (lambda msg: None)

    # ---- process helpers ---- #

    def _run(self, cmd: list[str], cwd: str, check: bool = True) -> subprocess.CompletedProcess:
        self.log(f"  CMD: {' '.join(cmd)}")
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=600,
            creationflags=0x08000000 if os.name == "nt" else 0,
        )
        if check and proc.returncode != 0:
            raise RuntimeError(
                f"Command failed ({proc.returncode}): {' '.join(cmd)}\n"
                f"stdout: {proc.stdout[-2000:]}\nstderr: {proc.stderr[-2000:]}"
            )
        return proc

    def _npx(self, pkg: str, args: list[str], cwd: str) -> subprocess.CompletedProcess:
        """Run a tool through npx --yes so it self-installs when needed.

        npx/npm are .cmd shims on Windows and cannot be spawned directly by
        CreateProcess, so they are wrapped through cmd.exe here.
        """
        if os.name == "nt":
            cmd = ["cmd", "/c"] + ["npx", "--yes"] + pkg.split() + args
        else:
            cmd = ["npx", "--yes"] + pkg.split() + args
        return self._run(cmd, cwd=cwd)

    # ---- main entry ---- #

    def patch_copy(
        self,
        source: ClaudeInstall,
        dest_root: str,
        app_name: str = "app",
    ) -> PatchResult:
        """Create a patched copy of a Claude install under dest_root/app.

        Returns PatchResult; on success dest_root/app contains:
          Claude.exe (fuse disabled) + resources/app.asar (patched) +
          resources/app.asar.unpacked/ (native files) + extra resources.
        """
        try:
            if not self.node_exe:
                self.log("  -> checking Node.js")
                import shutil as _sh

                self.node_exe = _sh.which("node")
                if not self.node_exe:
                    return PatchResult(
                        False,
                        "Node.js is required to patch the MSIX copy.\n"
                        "Install it from https://nodejs.org then re-run.",
                    )

            app_dir = os.path.join(dest_root, app_name)
            if os.path.isdir(app_dir):
                shutil.rmtree(app_dir)

            self.log("  -> copying app files (this can take a minute)...")
            src_resources = source.resources_dir
            dst_resources = os.path.join(app_dir, "resources")
            # copy the whole resources tree (asar, locale, icon, etc.)
            shutil.copytree(src_resources, dst_resources, ignore=shutil.ignore_patterns("*.asar.bak"))
            shutil.copytree(source.app_dir, app_dir, dirs_exist_ok=True)

            asar = os.path.join(dst_resources, "app.asar")
            if not os.path.isfile(asar):
                return PatchResult(False, f"app.asar not found at {asar}")

            self.log("  -> extracting app.asar...")
            extract_dir = os.path.join(dest_root, "_extracted")
            if os.path.isdir(extract_dir):
                shutil.rmtree(extract_dir)
            self._npx("@electron/asar", ["extract", asar, extract_dir], cwd=dest_root)

            self.log("  -> patching main bundle (DW/Cl relocation kill)...")
            patched_any = self._patch_bundles(extract_dir)
            if not patched_any:
                return PatchResult(
                    False,
                    "Could not locate the relocation code in the bundle. "
                    "Claude may have updated; check the app version.",
                )

            self.log("  -> repacking app.asar with native files unpacked...")
            asar_tmp = asar + ".new"
            self._npx(
                "@electron/asar",
                [
                    "pack",
                    extract_dir,
                    asar_tmp,
                    "--unpack",
                    _UNPACK_GLOB,
                ],
                cwd=dest_root,
            )
            # ensure the unpacked dir lands correctly
            src_unpacked = os.path.join(dest_root, "app.asar.new.unpacked")
            dst_unpacked = os.path.join(dst_resources, "app.asar.unpacked")
            if os.path.isdir(src_unpacked):
                if os.path.isdir(dst_unpacked):
                    shutil.rmtree(dst_unpacked)
                shutil.move(src_unpacked, dst_unpacked)

            os.replace(asar_tmp, asar)
            shutil.rmtree(extract_dir, ignore_errors=True)

            self.log("  -> disabling asar integrity fuse on copy exe...")
            exe = os.path.join(app_dir, "Claude.exe")
            if os.name == "nt" and os.path.isfile(exe):
                self._npx(
                    "@electron/fuses",
                    ["write", "--app", exe, "EnableEmbeddedAsarIntegrityValidation=off"],
                    cwd=dest_root,
                )
            elif os.name != "nt":
                self.log("  (non-Windows: no fuse patching needed)")

            if not self._verify_patch(app_dir):
                return PatchResult(False, "Post-patch verification failed.")

            return PatchResult(True, "Patched copy ready.", detail=app_dir)

        except Exception as exc:  # noqa: BLE001
            return PatchResult(False, f"Patch failed: {exc}")

    # ---- bundle patching ---- #

    def _patch_bundles(self, extract_dir: str) -> bool:
        """Replace the bodies of DW() and Cl() so relocation to Claude-3p never runs."""
        build_dir = os.path.join(extract_dir, ".vite", "build")
        if not os.path.isdir(build_dir):
            return False

        hits = 0
        funcs = {
            "DW": r"function DW\(\)\{[^}]*(?:return[a-zA-Z$]{1,3}\(\s*\)[^}]*)?\}",  # placeholder
            "Cl": r"function Cl\(\)\{[^}]*\}",
        }

        for fname in os.listdir(build_dir):
            fpath = os.path.join(build_dir, fname)
            if not os.path.isfile(fpath) or not fname.endswith(".js"):
                continue
            try:
                data = open(fpath, encoding="utf-8", errors="replace").read()
            except Exception:
                continue
            orig = data
            if "function DW(){" in data:
                # Replace whole function with a body that returns the real userData.
                data = re.sub(
                    r"function DW\(\)\{[^}]*\}",
                    'function DW(){return app.getPath("userData")}',
                    data,
                    count=1,
                )
            if "function Cl(){" in data:
                data = re.sub(
                    r"function Cl\(\)\{[^}]*\}",
                    'function Cl(){return app.getPath("userData")}',
                    data,
                    count=1,
                )
            if data != orig:
                with open(fpath, "w", encoding="utf-8") as fh:
                    fh.write(data)
                self.log(f"  patched {fname}")
                hits += 1

        return hits > 0

    # ---- verification ---- #

    def _verify_patch(self, app_dir: str) -> bool:
        res = os.path.join(app_dir, "resources")
        asar = os.path.join(res, "app.asar")
        unpacked = os.path.join(res, "app.asar.unpacked")
        if not os.path.isfile(asar):
            self.log("  ERROR: patched app.asar missing")
            return False
        if not os.path.isdir(unpacked):
            self.log("  WARNING: app.asar.unpacked missing (native modules may break app)")
        # verify native files present in unpacked dir
        missing = []
        if os.path.isdir(unpacked):
            for root, _dirs, files in os.walk(unpacked):
                for fn in files:
                    if fn.endswith(_NATIVE_SUFFIXES):
                        break
                else:
                    continue
                break
            else:
                self.log("  WARNING: no native modules unpacked")
        else:
            missing.append("app.asar.unpacked")
        if missing:
            self.log(f"  ERROR: {', '.join(missing)}")
            return False
        self.log("  verification OK: asar + unpacked native files present")
        return True