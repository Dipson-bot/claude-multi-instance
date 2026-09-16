# Claude Multi-Instance Setup

A cross-platform wizard that turns a single Claude Desktop install into several
**isolated side-by-side instances**.

- **Windows** — patches a copy (asar relocation kill + integrity fuse off) so any
  number of named instances share one binary with distinct `--user-data-dir`
  profiles. Creates `.vbs` launchers, desktop shortcuts, and taskbar pins.
- **macOS / Linux** — no patching needed; generates `.command` / shell launchers
  plus desktop entries that pass a dedicated `--user-data-dir` per instance.
- **Update-safe** — the wizard remembers which Claude version each copy was built
  from. If Claude auto-updates and a copy breaks, re-run the wizard (or pass
  `--repair`) and it detects the version change, re-patches from the new install,
  and rebuilds launchers — while **preserving every profile** (your chats/sign-ins).

## Quick start

### Grab the prebuilt package
On Windows: `dist\Claude-Multi-Setup.exe` (built via PyInstaller onefile).
On macOS/Linux: build your own with the scripts below.

### Build from source
```bash
pip install -r requirements.txt
# Windows
powershell -ExecutionPolicy Bypass -File build\build_windows.ps1
# macOS
bash build/build_macos.sh
# Linux
bash build/build_linux.sh
```
Output lands in `dist/`.

### Run
```bash
Claude-Multi-Setup.exe                      # GUI wizard (default)
Claude-Multi-Setup.exe --cli Instance2,Instance3
Claude-Multi-Setup.exe --cli --repair       # re-patch existing instances after an update
Claude-Multi-Setup.exe --repair             # GUI-equivalent repair (headless)
```

## How the wizard works

1. **Detect** OS + Claude Desktop install.
2. **Detect** any instances already set up — they are pre-filled and kept.
3. **Ask** how many instances and what to name them (e.g. "Instance 2", "Work").
   The **original** Claude never gets touched; every extra instance gets its own
   profile under `Claude-<name>`.
4. **Windows MSIX only** — copy the app, patch the asar bundle
   (`DW()` / `Cl()` return `app.getPath("userData")`, killing the 3P relocation),
   repack with `--unpack {*.node,*.exe,*.dll}`, and flip
   `EnableEmbeddedAsarIntegrityValidation=off` with `@electron/fuses`. The build
   version is recorded so future runs can detect updates.
5. **Create** one launcher + shortcut per instance.
6. **Verify** profiles and native modules.

Requires Node.js on Windows (`npx` is used for `@electron/asar` / `@electron/fuses`).

## After a Claude update

Claude Desktop auto-updates itself. Because each extra instance runs a **patched
copy**, an update can leave those copies on an older/stale build or, if the app no
longer starts, break them. To recover:

- Re-run `Claude-Multi-Setup.exe`. If it detects a version change on the installed
  Claude, it shows a warning banner and re-patches automatically on "Install".
- Or run headless repair: `Claude-Multi-Setup.exe --cli --repair`.
- Profiles (`Claude-<name>`) are never deleted by the wizard — re-patching only
  refreshes the shared app copy and launchers, so chats and sign-ins survive.

## Layout

```
app/
  main.py              # CLI / GUI entry (+ --repair)
  gui.py               # Tkinter wizard (update banner + existing-instance prefill)
  core/
    platform.py        # OS detection + Claude discovery + existing-instance scan
    asar_patch.py      # Windows asar + fuse patching + version sidecar
    launcher.py        # VBS/.command/sh launcher + shortcut generation
    setup.py           # orchestration (+ repair/version compare)
build/                 # PyInstaller scripts per OS
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| Second instance won't open | Pin the `.vbs`/`.command` launcher, not the bare exe. |
| Exit code `-36861` on Windows | Integrity fuse still on — re-run wizard or inspect with `@electron/fuses read`. |
| Both instances share one profile | Launcher must set `CLAUDE_USER_DATA_DIR` AND pass `--user-data-dir`. |
| Copy broke after Claude auto-updated | Re-run wizard (or `--cli --repair`); it detects the new version and re-patches. |
