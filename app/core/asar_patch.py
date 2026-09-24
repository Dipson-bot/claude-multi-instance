"""Windows asar patching + Electron fuse flip (pure Python, no Node.js).

Builds a patched copy of Claude that honors --user-data-dir:
  1. Refuse to run while instances of the existing copy are open.
  2. Copy the installed app into a staging dir (<base>/app.new).
  3. Patch the bundle inside app.asar, located by content rather than by
     minified names:
       - userData relocation functions always return app.getPath("userData")
       - the `delete process.env.CLAUDE_USER_DATA_DIR` guard is neutralized
       - a launch shim derives CLAUDE_USER_DATA_DIR from --user-data-dir, so a
         plain .lnk is enough to launch an instance; it also applies the
         per-instance window title, window icon and taskbar identity
     If Node.js happens to be installed, modified files are syntax-checked.
  4. Disable the asar integrity fuse on the copied exe.
  5. Self-test: launch the staged exe on a throwaway profile and confirm the
     app really writes there and stays there.
  6. Swap staging into place; the old copy is only removed once the new one
     passed. A failed run leaves the existing copy untouched.

Non-Windows installs do NOT need this.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from typing import Callable

from .asar import FUSE_ASAR_INTEGRITY, AsarArchive, set_fuse
from .platform import ClaudeInstall

LogFn = Callable[[str], None]

# Files that must remain unpacked inside app.asar.unpacked/
_NATIVE_SUFFIXES = (".node", ".exe", ".dll", ".pak")

_SIDECAR_FILENAME = "claude-setup-version.txt"

_BUILD_DIR = ".vite/build/"

# `function Nu(){if(process.env.CLAUDE_USER_DATA_DIR)return a.app.getPath("userData");
#   if(win32&&LOCALAPPDATA)return join(LOCALAPPDATA,"Claude-3p"); ...}`
# The name changes every build (DW, Cl, FJ, Nu, GY, ...); the shape does not.
_RELOCATION_RX = re.compile(
    r'function ([\w$]+)\(\)\{if\(process\.env\.CLAUDE_USER_DATA_DIR\)'
    r'return ([\w$]+)\.app\.getPath\("userData"\)'
)
# Names used by older builds whose relocation function had a different shape.
_LEGACY_NAMES = ("DW", "Cl", "FJ")

_ENV_DELETE_RX = re.compile(r"delete process\.env\.CLAUDE_USER_DATA_DIR\b")

# Launch arguments read by the shim (added by the .lnk launchers).
INSTANCE_ARG = "--claude-instance"
INSTANCE_ICON_ARG = "--claude-instance-icon"

_SHIM_MARKER = "/*claude-multi-setup:env-shim*/"
# 1. CLAUDE_USER_DATA_DIR <- --user-data-dir (what the old VBS launchers set)
# 2. --claude-instance=<name>: own taskbar group (AppUserModelID) and
#    "<title> — <name>" window titles
# 3. --claude-instance-icon=<ico>: window/taskbar icon
# Everything is wrapped in try/catch: a failure here must never stop Claude.
_ENV_SHIM = _SHIM_MARKER + (
    ';(()=>{try{'
    'const A=process.argv,g=k=>{const p="--"+k+"=",a=A.find(x=>x.startsWith(p));'
    'return a?a.slice(p.length).replace(/^"|"$/g,""):null};'
    'if(!process.env.CLAUDE_USER_DATA_DIR){const u=g("user-data-dir");'
    'if(u)process.env.CLAUDE_USER_DATA_DIR=u}'
    'const n=g("claude-instance"),i=g("claude-instance-icon");if(!n&&!i)return;'
    'const E=require("electron"),P=E.app;'
    'if(n&&process.platform==="win32"){'
    'const id="Claude.Instance."+n.replace(/[^A-Za-z0-9]/g,""),s=P.setAppUserModelId.bind(P);'
    'P.setAppUserModelId=()=>s(id);s(id)}'
    # Titles change three ways: Claude calls win.setTitle() itself (wrapped
    # below), Electron applies the page <title> (page-title-updated listener),
    # and Electron resets it natively right after the window is created
    # (re-applied on show/focus and by a cheap 2s check).
    'const S=n?" \\u2014 "+n:"";'
    'if(n){const f=t=>{t=String(t||"Claude");return t.endsWith(S)?t:t+S};'
    'for(const C of[E.BaseWindow,E.BrowserWindow]){const q=C&&C.prototype;'
    'if(q&&Object.prototype.hasOwnProperty.call(q,"setTitle")){const o=q.setTitle;'
    'q.setTitle=function(t){return o.call(this,f(t))}}}}'
    'const img=i?E.nativeImage.createFromPath(i):null;'
    'P.on("browser-window-created",(e,w)=>{try{'
    'if(img&&!img.isEmpty())w.setIcon(img);'
    'if(n){w.on("page-title-updated",(ev,t)=>{ev.preventDefault();w.setTitle(t)});'
    'const fix=()=>{try{if(!w.isDestroyed()&&!w.getTitle().endsWith(S))w.setTitle(w.getTitle())}catch(e){}};'
    'fix();setTimeout(fix,0);w.on("show",fix);w.on("focus",fix);'
    'const iv=setInterval(()=>{w.isDestroyed()?clearInterval(iv):fix()},2000)}'
    '}catch(e){}})'
    '}catch(e){}})();\n'
)

_SELFTEST_TIMEOUT = 60  # seconds to wait for the app to write its log
_SELFTEST_GRACE = 6  # seconds the app must stay put after that
_SELFTEST_NAME = "SelfTest"


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


def _norm(path: str) -> str:
    return os.path.normcase(os.path.abspath(path)).rstrip("\\/")


def claude_processes_under(app_dir: str) -> list[dict]:
    """Claude.exe processes whose executable lives inside app_dir.

    Returns [{"pid": int, "cmd": str}]. Windows only; [] elsewhere.
    """
    if os.name != "nt":
        return []
    ps = (
        "Get-CimInstance Win32_Process -Filter \"Name='Claude.exe'\" | "
        "Select-Object ProcessId,ExecutablePath,CommandLine | ConvertTo-Json -Compress"
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, timeout=60, creationflags=0x08000000,
        ).stdout.strip()
        data = json.loads(out) if out else []
    except Exception:
        return []
    if isinstance(data, dict):
        data = [data]
    root = _norm(app_dir) + os.sep
    procs = []
    for row in data:
        exe = row.get("ExecutablePath") or ""
        if exe and _norm(exe).startswith(root):
            procs.append({"pid": int(row["ProcessId"]), "cmd": row.get("CommandLine") or ""})
    return procs


def _kill(pids: list[int]) -> None:
    if not pids:
        return
    args = ["taskkill", "/F", "/T"]
    for pid in pids:
        args += ["/PID", str(pid)]
    subprocess.run(args, capture_output=True, timeout=60, creationflags=0x08000000)


def _kill_all_under(app_dir: str, timeout: float = 20) -> None:
    """Kill every Claude process running from app_dir and wait until they're gone."""
    deadline = time.time() + timeout
    while True:
        procs = claude_processes_under(app_dir)
        if not procs or time.time() > deadline:
            return
        _kill([p["pid"] for p in procs])
        time.sleep(1)


def _retry(fn, attempts: int = 20, delay: float = 1.0):
    """Retry a filesystem op that can briefly fail while Windows (or antivirus)
    still holds handles on files of a just-exited process."""
    for i in range(attempts):
        try:
            return fn()
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(delay)


def _window_titles(pids: list[int]) -> list[str]:
    """Main window titles of the given processes (Windows only)."""
    if os.name != "nt" or not pids:
        return []
    ps = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
          "Get-Process -Id " + ",".join(map(str, pids)) +
          " -ErrorAction SilentlyContinue | Where-Object MainWindowTitle | "
          "ForEach-Object MainWindowTitle")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True,
                             text=True, encoding="utf-8", timeout=60, creationflags=0x08000000).stdout
        return [t.strip() for t in out.splitlines() if t.strip()]
    except Exception:
        return []


@dataclass
class PatchResult:
    ok: bool
    message: str
    detail: str = ""
    # True when the failure must stop setup (e.g. copies still running), rather
    # than falling back to an existing copy.
    fatal: bool = False


class AsarPatcher:
    def __init__(self, log: LogFn | None = None) -> None:
        self.log = log or (lambda msg: None)
        self.node_exe = shutil.which("node")  # optional: extra syntax check only

    # ---- main entry ---- #

    def patch_copy(
        self,
        source: ClaudeInstall,
        dest_root: str,
        app_name: str = "app",
        source_version: str | None = None,
    ) -> PatchResult:
        """Build, self-test and install a patched copy at dest_root/app_name.

        On success dest_root/app_name contains Claude.exe (fuse disabled) +
        resources/app.asar (patched) + resources/app.asar.unpacked/. On failure
        any existing copy at that path is left exactly as it was.
        """
        final_dir = os.path.join(dest_root, app_name)
        staging = final_dir + ".new"
        try:
            running = claude_processes_under(final_dir)
            if running:
                return PatchResult(
                    False,
                    f"{len(running)} Claude process(es) are running from the patched copy "
                    f"({final_dir}).\nClose every extra Claude instance, then re-run.",
                    fatal=True,
                )

            if os.path.isdir(staging):
                _kill_all_under(staging)
                _retry(lambda: shutil.rmtree(staging))

            self.log("  -> copying app files into staging (this can take a minute)...")
            shutil.copytree(source.app_dir, staging, ignore=shutil.ignore_patterns("*.asar.bak"))

            asar = os.path.join(staging, "resources", "app.asar")
            if not os.path.isfile(asar):
                return PatchResult(False, f"app.asar not found at {asar}")

            self.log("  -> patching bundle (userData relocation + env guard + launch shim)...")
            archive = AsarArchive(asar)
            replacements, err = self._patch_bundles(archive)
            if err:
                return PatchResult(False, err)
            asar_tmp = asar + ".new"
            archive.write_patched(asar_tmp, replacements)
            os.replace(asar_tmp, asar)

            exe = os.path.join(staging, "Claude.exe")
            if os.name == "nt":
                self.log("  -> disabling asar integrity fuse on copy exe...")
                if not set_fuse(exe, FUSE_ASAR_INTEGRITY, False):
                    self.log("  NOTE: no asar integrity fuse in this exe (nothing to disable)")

            if not self._verify_patch(staging):
                return PatchResult(False, "Post-patch verification failed.")

            if os.name == "nt":
                ok, why = self.self_test(exe, dest_root)
                if not ok:
                    return PatchResult(False, f"Self-test failed: {why}")

            self._swap_into_place(staging, final_dir)
            self._write_version_sidecar(source_version, dest_root)

            return PatchResult(True, "Patched copy ready.", detail=final_dir)

        except Exception as exc:  # noqa: BLE001
            return PatchResult(False, f"Patch failed: {exc}")
        finally:
            if os.path.isdir(staging):
                _kill_all_under(staging)
                shutil.rmtree(staging, ignore_errors=True)

    def _swap_into_place(self, staging: str, final_dir: str) -> None:
        """Replace final_dir with staging; roll back if the second rename fails."""
        old = None
        if os.path.isdir(final_dir):
            old = f"{final_dir}.old-{int(time.time())}"
            _retry(lambda: os.rename(final_dir, old))
        try:
            _retry(lambda: os.rename(staging, final_dir))
        except Exception:
            if old:
                _retry(lambda: os.rename(old, final_dir))
            raise
        if old:
            shutil.rmtree(old, ignore_errors=True)
            if os.path.isdir(old):
                self.log(f"  NOTE: could not fully remove {old}; delete it manually later.")
        self.log(f"  installed patched copy at {final_dir}")

    # ---- self-test ---- #

    def self_test(self, exe: str, work_root: str) -> tuple[bool, str]:
        """Launch exe on a throwaway profile, exactly as the .lnk launchers do
        (--user-data-dir + instance name, no env var), and check the app
        really uses it.

        Passes when the app writes logs/main.log into the test profile, is still
        running a few seconds later, and none of its processes point at another
        profile (that would mean the relocation-and-relaunch still happens).
        """
        app_dir = os.path.dirname(exe)
        profile = os.path.join(work_root, "_selftest-profile")
        shutil.rmtree(profile, ignore_errors=True)
        env = os.environ.copy()
        env.pop("CLAUDE_USER_DATA_DIR", None)
        self.log("  -> self-test: launching the patched copy on a test profile "
                 "(a Claude window may appear briefly)...")
        try:
            proc = subprocess.Popen(
                [exe, f"--user-data-dir={profile}", f"{INSTANCE_ARG}={_SELFTEST_NAME}"],
                cwd=app_dir, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            deadline = time.time() + _SELFTEST_TIMEOUT
            logged = False
            while time.time() < deadline:
                time.sleep(1)
                logged = any(
                    os.path.isfile(os.path.join(profile, d, "main.log")) for d in ("logs", "Logs")
                )
                if logged:
                    break
                if proc.poll() is not None and not claude_processes_under(app_dir):
                    code = proc.returncode
                    hint = " (asar integrity fuse still on)" if code in (-36861, 4294930435) else ""
                    return False, f"the app exited immediately with code {code}{hint}"
            if not logged:
                return False, (f"no logs/main.log in the test profile after {_SELFTEST_TIMEOUT}s; "
                               "the app is not using --user-data-dir")

            time.sleep(_SELFTEST_GRACE)
            procs = claude_processes_under(app_dir)
            if not procs:
                return False, "the app exited after starting (likely relocated to the shared profile)"
            want = _norm(profile)
            for p in procs:
                cmd = os.path.normcase(p["cmd"].replace("/", "\\"))
                if "--user-data-dir" in cmd and want not in cmd:
                    return False, f"a child process uses another profile: {p['cmd'][:300]}"
            self.log("  self-test OK: the copy stays on its own profile")

            titles = _window_titles([p["pid"] for p in procs])
            if any(t.endswith(f" — {_SELFTEST_NAME}") for t in titles):
                self.log("  self-test OK: window title shows the instance name")
            else:
                self.log(f"  NOTE: could not confirm the instance window title ({titles or 'no window'})")
            return True, ""
        finally:
            _kill_all_under(app_dir)
            for _ in range(10):
                shutil.rmtree(profile, ignore_errors=True)
                if not os.path.isdir(profile):
                    break
                time.sleep(1)

    @staticmethod
    def _replace_function_body(data: str, name: str) -> tuple[str, bool]:
        """Brace-aware replace of `function NAME(){...}` bodies that reference
        CLAUDE_USER_DATA_DIR (the 3P relocation fallback).

        Only rewrites occurrences whose body actually contains the relocation
        marker, so unrelated minified helpers with the same name are left
        untouched. Iterates every occurrence, not just the first.
        """
        needle = f"function {name}("
        changed = False
        search_from = 0

        while True:
            start = data.find(needle, search_from)
            if start < 0:
                break
            # move to the opening brace of the function body
            paren = data.find("{", start)
            if paren < 0:
                break
            close, body = AsarPatcher._find_function_end(data, paren)
            if close is None:
                break
            if "CLAUDE_USER_DATA_DIR" in body and "userData" in body:
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

    def _patch_relocation(self, data: str) -> tuple[str, list[str]]:
        """Make every userData relocation function return app.getPath("userData")."""
        names: list[str] = []
        for name in dict.fromkeys(m.group(1) for m in _RELOCATION_RX.finditer(data)):
            data, changed = self._replace_function_body(data, name)
            if changed:
                names.append(name)
        if not names:
            for name in _LEGACY_NAMES:
                data, changed = self._replace_function_body(data, name)
                if changed:
                    names.append(name)
        return data, names

    def _patch_bundles(self, archive: AsarArchive) -> tuple[dict[str, bytes], str | None]:
        """Patch the main-process bundle. Returns ({path: new_bytes}, error)."""
        try:
            pkg = json.loads(archive.read("package.json").decode("utf-8"))
        except Exception:
            pkg = {}
        entry = re.sub(r"^\./", "", pkg.get("main") or "index.js")

        targets = [
            p for p, e in archive.files()
            if p.startswith(_BUILD_DIR) and p.endswith(".js") and "/" not in p[len(_BUILD_DIR):]
            and "link" not in e and not e.get("unpacked")
        ]
        if not targets:
            return {}, f"Unexpected bundle layout: no {_BUILD_DIR}*.js. Claude may have changed its build."

        relocations: list[str] = []
        guards = 0
        originals: dict[str, str] = {}
        patched: dict[str, str] = {}

        for path in targets:
            try:
                data = archive.read(path).decode("utf-8")
            except Exception:
                continue
            orig = data

            # 1. keep the env var alive (the packaged app deletes it at startup)
            data, n = _ENV_DELETE_RX.subn("void 0", data)
            guards += n

            # 2. neutralize the relocation-to-Claude-3p fallback
            data, names = self._patch_relocation(data)
            short = path[len(_BUILD_DIR):]
            relocations += [f"{short}:{fn}" for fn in names]

            if data != orig:
                originals[path] = orig
                patched[path] = data
                self.log(f"  patched {short}")

        if not relocations:
            return {}, ("Could not locate the userData relocation code in the bundle. "
                        "This Claude version needs an updated version of this tool.")
        self.log(f"  relocation functions patched: {', '.join(relocations)}")
        if not guards:
            self.log("  NOTE: no env-var delete guard found (fine if this build no longer has one)")

        # 3. launch shim at the very top of the entry file
        try:
            if entry not in patched:
                originals[entry] = archive.read(entry).decode("utf-8")
            data = patched.get(entry, originals[entry])
            if _SHIM_MARKER not in data:
                m = re.match(r"""\s*(['"])use strict\1;?""", data)
                at = m.end() if m else 0
                patched[entry] = data[:at] + ("\n" if at else "") + _ENV_SHIM + data[at:]
                self.log(f"  launch shim added to {entry}")
        except Exception as exc:  # noqa: BLE001
            self.log(f"  WARNING: entry file {entry} not patched ({exc}); "
                     "launchers may need CLAUDE_USER_DATA_DIR set")

        err = self._syntax_check(originals, patched)
        return {p: d.encode("utf-8") for p, d in patched.items()}, err

    def _syntax_check(self, originals: dict[str, str], patched: dict[str, str]) -> str | None:
        """Optional: `node --check` each modified file when Node.js is present.
        A file that parsed before patching must still parse afterwards. The
        self-test is the real gate; this only gives a clearer error."""
        if not self.node_exe:
            return None
        tmp = tempfile.mkdtemp(prefix="claude-setup-syntax-")
        try:
            probe = os.path.join(tmp, "probe.js")
            for path, data in patched.items():
                with open(probe, "w", encoding="utf-8") as fh:
                    fh.write(data)
                if self._node_check(probe):
                    continue
                with open(probe, "w", encoding="utf-8") as fh:
                    fh.write(originals.get(path, ""))
                if self._node_check(probe):
                    return (f"Patching broke the JavaScript syntax of {path}. "
                            "This Claude version needs an updated version of this tool.")
            self.log("  syntax check OK")
            return None
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _node_check(self, path: str) -> bool:
        proc = subprocess.run(
            [self.node_exe or "node", "--check", path],
            capture_output=True, text=True, timeout=120,
            creationflags=0x08000000 if os.name == "nt" else 0,
        )
        return proc.returncode == 0

    # ---- verification ---- #

    def _verify_patch(self, app_dir: str) -> bool:
        res = os.path.join(app_dir, "resources")
        asar = os.path.join(res, "app.asar")
        unpacked = os.path.join(res, "app.asar.unpacked")
        if not os.path.isfile(asar):
            self.log("  ERROR: patched app.asar missing")
            return False
        if not os.path.isdir(unpacked):
            self.log("  ERROR: app.asar.unpacked missing (native modules would break the app)")
            return False
        has_native = any(
            fn.endswith(_NATIVE_SUFFIXES)
            for _root, _dirs, files in os.walk(unpacked)
            for fn in files
        )
        if not has_native:
            self.log("  WARNING: no native modules unpacked")
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
