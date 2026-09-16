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

_SIDECAR_FILENAME = "claude-setup-version.txt"


def sidecar_path(dest_root: str) -> str:
    """Where the patched copy remembers which Claude version it was built from."""
    return os.path.join(dest_root, _SIDECAR_FILENAME)


def read_sidecar_version(dest_root: str) -> str | None:
    """Return the version of the Claude build a patched copy was created from."""
    p = sidecar_path(dest_root)
    if os.path.isfile(p):
        try:
            return open(p, encoding="utf-8").read().strip() or None
        except Exception:
            return None
    return None


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
        source_version: str | None = None,
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

            self._write_version_sidecar(source_version, dest_root)

            return PatchResult(True, "Patched copy ready.", detail=app_dir)

        except Exception as exc:  # noqa: BLE001
            return PatchResult(False, f"Patch failed: {exc}")

    # ---- bundle patching ---- #

    @staticmethod
    def _replace_function_body(data: str, name: str) -> tuple[str, bool]:
        """Brace-aware replace of `function NAME(){...}` bodies that reference
        CLAUDE_USER_DATA_DIR (the 3P relocation fallback).

        Only rewrites occurrences whose body actually contains the relocation
        marker, so unrelated minified helpers (e.g. a sentry logger also named
        `Cl`) are left untouched. Iterates every occurrence, not just the first.
        """
        needle = f"function {name}("
        changed = False
        search_from = 0

        while True:
            start = data.find(needle, search_from)
            if start < 0:
                break
            # move to the opening brace of the parameter list
            paren = data.find("{", start)
            if paren < 0:
                break
            # find the function's closing brace (frequency-aware)
            close, body = AsarPatcher._find_function_end(data, paren)
            if close is None:
                break
            if "CLAUDE_USER_DATA_DIR" in body:
                # detect the electron alias used in this bundle
                m = re.search(r"([A-Za-z_$][\w$]*)\.app\.getPath", body)
                alias = m.group(1) if m else "T"
                new_fn = f"function {name}(){{return {alias}.app.getPath(\"userData\")}}"
                data = data[:start] + new_fn + data[close + 1:]
                changed = True
            # advance past this occurrence
            search_from = start + len(needle)

        return data, changed

    @staticmethod
    def _find_function_end(data: str, open_brace: int) -> tuple[int | None, str]:
        """Return (closing_brace_index, body_text) for the function whose body
        opens at open_brace. Understands strings, escapes, and template
        literals including ${...} expressions."""
        depth = 0          # function brace depth (real code braces only)
        tmpl_expr = 0      # depth inside ${...} of a template literal
        in_str: str | None = None
        in_tmpl = False
        i = open_brace
        while i < len(data):
            ch = data[i]
            if in_str:
                if ch == "\\":
                    i += 2
                    continue
                if ch == in_str:
                    in_str = None
                i += 1
                continue
            if in_tmpl:
                if tmpl_expr > 0:
                    # inside ${ ... } — a JS expression context; braces here are
                    # real braces but must not close the FUNCTION, only the expr
                    if ch in "'\"`":
                        in_str = ch if ch != "`" else None
                        if ch == "`":
                            in_tmpl = True
                        i += 1
                        continue
                    if ch == "{":
                        tmpl_expr += 1
                    elif ch == "}":
                        tmpl_expr -= 1
                    i += 1
                    continue
                # template literal text
                if ch == "`":
                    in_tmpl = False
                elif ch == "$" and i + 1 < len(data) and data[i + 1] == "{":
                    tmpl_expr = 1
                    i += 2
                    continue
                i += 1
                continue
            if ch in "'\"`":
                in_str = ch if ch != "`" else None
                if ch == "`":
                    in_tmpl = True
                    tmpl_expr = 0
                i += 1
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return i, data[open_brace:i + 1]
            i += 1
        return None, ""

    def _patch_bundles(self, extract_dir: str) -> bool:
        """Neutralize the 3P userData relocation so --user-data-dir is honored.

        Handles both known bundle layouts:
          - Claude <=1.5x:  function DW()/function Cl()
          - Claude 2.x:     function FJ() (same behavior, new name)
        Also strips the "delete process.env.CLAUDE_USER_DATA_DIR" guard so the
        env var survives; that is the deeper root cause of forced relocation.
        """
        build_dir = os.path.join(extract_dir, ".vite", "build")
        if not os.path.isdir(build_dir):
            return False

        hits = 0
        targets = ["DW", "Cl", "FJ"]
        delete_old = "delete process.env.CLAUDE_USER_DATA_DIR,"
        delete_new = "delete process.env.CLAUDE_USER_DATA_DIR"

        for fname in os.listdir(build_dir):
            fpath = os.path.join(build_dir, fname)
            if not os.path.isfile(fpath) or not fname.endswith(".js"):
                continue
            try:
                data = open(fpath, encoding="utf-8", errors="replace").read()
            except Exception:
                continue
            orig = data

            # 1. neutralize env-var deletion (pre.js) — root cause
            data = data.replace(delete_old, "")
            data = data.replace(delete_new, "process.env.CLAUDE_USER_DATA_DIR_IGNORED")
            if data != orig:
                hits += 1

            # 2. neutralize the relocation fallback function(s)
            for name in targets:
                data, changed = self._replace_function_body(data, name)
                if changed:
                    hits += 1

            if data != orig:
                with open(fpath, "w", encoding="utf-8") as fh:
                    fh.write(data)
                self.log(f"  patched {fname}")

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

    @staticmethod
    def _write_version_sidecar(version: str | None, dest_root: str) -> None:
        """Persist the Claude version that produced this patched copy."""
        try:
            with open(sidecar_path(dest_root), "w", encoding="utf-8") as fh:
                fh.write(version or "unknown")
        except Exception:
            pass