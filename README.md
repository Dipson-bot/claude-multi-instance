# Claude Multi-Instance Setup

A cross-platform wizard that turns a single Claude Desktop install into several
**isolated side-by-side instances** (e.g. "Company", "Personal", "Agent Router").

- **Windows** — patches a copy (asar relocation kill + integrity fuse off) so any
  number of named instances share one binary with distinct `--user-data-dir`
  profiles. Creates `.vbs` launchers, desktop shortcuts, and taskbar pins.
- **macOS / Linux** — no patching needed; generates `.command` / shell launchers
  plus desktop entries that pass a dedicated `--user-data-dir` per instance.

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
Claude-Multi-Setup.exe            # GUI wizard (default)
Claude-Multi-Setup.exe --cli Company,Personal,Work
```

## How the wizard works

1. **Detect** OS + Claude Desktop install.
2. **Ask** how many instances and what to name them.
3. **Windows MSIX only** — copy the app, patch the asar bundle
   (`DW()` / `Cl()` return `app.getPath("userData")`, killing the 3P relocation),
   repack with `--unpack {*.node,*.exe,*.dll}`, and flip
   `EnableEmbeddedAsarIntegrityValidation=off` with `@electron/fuses`.
4. **Create** one launcher + shortcut per instance.
5. **Verify** profiles and native modules.

Requires Node.js on Windows (`npx` is used for `@electron/asar` / `@electron/fuses`).

## Layout

```
app/
  main.py              # CLI / GUI entry
  gui.py               # Tkinter wizard
  core/
    platform.py        # OS detection + Claude discovery
    asar_patch.py      # Windows asar + fuse patching
    launcher.py        # VBS/.command/sh launcher + shortcut generation
    setup.py           # orchestration
build/                 # PyInstaller scripts per OS
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| Second instance won't open | Pin the `.vbs`/`.command` launcher, not the bare exe. |
| Exit code `-36861` on Windows | Integrity fuse still on — re-run wizard or inspect with `@electron/fuses read`. |
| Both instances share one profile | Launcher must set `CLAUDE_USER_DATA_DIR` AND pass `--user-data-dir`. |