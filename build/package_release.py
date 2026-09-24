"""Build the release zips from a built Windows exe and the source tree.

Usage (from the project root, after build/build_windows.ps1):
    python build/package_release.py v1.3

Creates release/Claude-Multi-Setup-<ver>-Windows.zip (exe + install notes +
README) and release/Claude-Multi-Setup-<ver>-macOS.zip (source + start-mac.sh;
a Mac app can only be built on a Mac).
"""

import os
import sys
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def add(z: zipfile.ZipFile, path: str, arc: str, mode: int = 0o644) -> None:
    info = zipfile.ZipInfo(arc, date_time=time.localtime(os.path.getmtime(path))[:6])
    info.external_attr = (0o100000 | mode) << 16  # keep unix permissions (Mac/Linux)
    info.create_system = 3
    info.compress_type = zipfile.ZIP_DEFLATED
    with open(path, "rb") as fh:
        z.writestr(info, fh.read())


def main(ver: str) -> None:
    out = os.path.join(ROOT, "release")
    os.makedirs(out, exist_ok=True)

    exe = os.path.join(ROOT, "dist", "Claude-Multi-Setup.exe")
    if os.path.isfile(exe):
        win = os.path.join(out, f"Claude-Multi-Setup-{ver}-Windows.zip")
        with zipfile.ZipFile(win, "w") as z:
            add(z, exe, f"Claude-Multi-Setup-{ver}/Claude-Multi-Setup.exe")
            add(z, os.path.join(ROOT, "docs", "INSTALL-NOTES.txt"), f"Claude-Multi-Setup-{ver}/INSTALL-NOTES.txt")
            add(z, os.path.join(ROOT, "README.md"), f"Claude-Multi-Setup-{ver}/README.md")
        print("created", win)
    else:
        print("skipped Windows zip: build dist/Claude-Multi-Setup.exe first")

    files = []
    for d, _dirs, fs in os.walk(os.path.join(ROOT, "app")):
        if "__pycache__" not in d:
            files += [os.path.join(d, f) for f in fs if f.endswith(".py")]
    files += [os.path.join(ROOT, "build", f) for f in
              ("build_macos.sh", "build_linux.sh", "build_windows.ps1", "make_icon.py")]
    files += [os.path.join(ROOT, f) for f in
              ("run.py", "requirements.txt", "README.md", "MAC-QUICKSTART.md", "start-mac.sh",
               "icon.icns", "icon.png", "icon.ico")]
    mac = os.path.join(out, f"Claude-Multi-Setup-{ver}-macOS.zip")
    with zipfile.ZipFile(mac, "w") as z:
        for f in files:
            rel = os.path.relpath(f, ROOT).replace("\\", "/")
            add(z, f, f"claude-multi-setup/{rel}", 0o755 if f.endswith(".sh") else 0o644)
    print("created", mac)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python build/package_release.py v1.3")
    main(sys.argv[1])
