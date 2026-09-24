# Claude Multi-Instance Setup

A cross-platform wizard that turns a single Claude Desktop install into several
**isolated side-by-side instances**, each with its own account, profile and
**colored icon** so you always open the right one.

- **Windows** — patches a copy (asar relocation kill + integrity fuse off) so any
  number of named instances share one binary with distinct `--user-data-dir`
  profiles. One `.lnk` shortcut per instance (desktop + install folder). Each
  instance gets its own icon color/badge, window title (`Claude — Work`) and
  taskbar button. No Node.js needed.
- **macOS / Linux** — no patching needed; generates `.command` / shell launchers
  plus desktop entries that pass a dedicated `--user-data-dir` per instance,
  with the instance's colored icon.
- **Update-aware** — the wizard remembers which Claude version the copy was built
  from. On Windows it checks at sign-in and offers to update the instances when
  Claude has been updated; profiles (chats, sign-ins) are always kept.

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
Claude-Multi-Setup.exe --cli Work,Personal  # headless, default colors
Claude-Multi-Setup.exe --cli --repair       # re-patch existing instances after an update
Claude-Multi-Setup.exe --repair             # same, detects existing instances
Claude-Multi-Setup.exe --no-update-check    # (with --cli/--repair) turn off the sign-in check
```

## How the wizard works

1. **Detect** OS + Claude Desktop install.
2. **Detect** any instances already set up — names, colors and badges are
   pre-filled and kept.
3. **Ask** how many instances, their names, and for each an **icon color**
   (palette or custom) and a **badge** of up to 2 letters (defaults to the
   name's initials), with a live preview. Names are validated: no characters
   that are invalid in folder names, no reserved Windows names, no names that
   would collide with each other or with Claude's own `Claude-3p` folder.
   The **original** Claude never gets touched; every extra instance gets its own
   profile under `Claude-<name>`.
4. **Windows only** — build a patched copy in a staging folder (`app.new`), in
   pure Python:
   - the userData relocation functions are found by their code shape (their
     minified names change every build) and made to return
     `app.getPath("userData")`;
   - the `delete process.env.CLAUDE_USER_DATA_DIR` guard is neutralized;
   - a launch shim sets `CLAUDE_USER_DATA_DIR` from `--user-data-dir` (so a
     plain shortcut is enough) and applies the instance's window title, window
     icon and taskbar identity (`--claude-instance`, `--claude-instance-icon`);
   - if Node.js happens to be installed, modified files are syntax-checked;
   - the changed files are written back into `app.asar` (the rest of the
     archive is copied byte-for-byte) and `EnableEmbeddedAsarIntegrityValidation`
     is switched off in the copied exe.
5. **Self-test** (Windows) — launch the staged copy on a throwaway profile and
   confirm it writes there and stays there. Only then is it swapped into place;
   if anything fails, the previous copy is left untouched.
6. **Create** one icon + launcher + shortcut per instance and record them in
   `instances.json`. Windows: optionally register the sign-in update check.

## After a Claude update

Claude Desktop auto-updates itself, but the extra instances run from the
patched copy, which stays on the version it was built from until you update it.
The instances keep working in the meantime.

- **Windows, automatic:** if the sign-in check is on (default), a dialog appears
  after the next sign-in: "Claude Desktop was updated… Update them now?" Yes opens
  the wizard with everything pre-filled; No is remembered for that version. The
  check is registered under `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`
  (no admin rights) and the tool copies itself to `%USERPROFILE%\ClaudeInstances`
  so the check keeps working if the download is deleted.
- **Manual:** re-run `Claude-Multi-Setup.exe` (a banner shows the version
  change) or run `Claude-Multi-Setup.exe --cli --repair`.
- Close every extra Claude instance first (the wizard refuses to repair while
  one is running from the patched copy; the original Claude can stay open).
- Profiles (`Claude-<name>`) are never deleted by the wizard — re-patching only
  refreshes the shared app copy, icons and launchers.

## Starting instances at sign-in

Each instance can open automatically when you sign in:

- in the wizard, tick **Start at sign-in** per instance (the header checkbox
  turns it on/off for all), then Install; or
- click **Startup…** for a quick screen with per-instance toggles plus
  **Enable all / Disable all** — it applies immediately, no re-install.

Windows uses a shortcut in your Startup folder, so the entries also show in
Task Manager → Startup apps (turning one off there is respected; turning it
back on in the tool clears the Task Manager switch). macOS uses a LaunchAgent
per instance, Linux an XDG autostart entry. Removing an instance also removes
its startup entry.

```bash
Claude-Multi-Setup.exe --startup-on "Work,Personal"
Claude-Multi-Setup.exe --startup-off all
Claude-Multi-Setup.exe --list                                # shows who starts at sign-in
```

Re-running Install is quick when Claude has not changed: the patched copy is
only rebuilt when the installed Claude version differs (or with `--repair`).

## Removing instances

In the wizard click **Remove instances…**, tick the instances, and choose:

- *(default)* remove the shortcuts, launchers and icons only — the profile
  folder is kept, so re-adding an instance with the same name brings its
  sign-in back;
- **Also delete their data** — the profile folder (sign-ins, local chat cache,
  settings) is moved to the Recycle Bin / Trash, so it can still be restored;
- **Full uninstall** (all instances ticked) — also removes the shared Claude
  copy, the tool's folder and the sign-in update check.

Instances that are open must be closed first. The original Claude, its profiles
(`Claude`, `Claude-3p`) and your claude.ai accounts are never touched. Taskbar
pins have to be unpinned by hand (right-click → Unpin).

```bash
Claude-Multi-Setup.exe --list
Claude-Multi-Setup.exe --remove "Work,Client"               # shortcuts only
Claude-Multi-Setup.exe --remove Work --delete-data          # + profile to Recycle Bin
Claude-Multi-Setup.exe --uninstall [--delete-data]          # everything
```

## Layout

```
app/
  main.py              # CLI / GUI entry (+ --repair, --check-update)
  gui.py               # Tkinter wizard (names, colors, badges, previews)
  core/
    platform.py        # OS detection, Claude discovery, name validation, manifest
    asar.py            # pure-Python asar reader/writer + Electron fuse flip
    asar_patch.py      # Windows patch pipeline, launch shim, self-test, safe swap
    icons.py           # per-instance icon rendering (Pillow)
    launcher.py        # .lnk / .command / .sh launcher + shortcut generation
    update_check.py    # sign-in update check (Windows Run key)
    remove.py          # remove instances / full uninstall (Recycle Bin for data)
    startup.py         # start instances at sign-in (Startup folder / LaunchAgent / autostart)
    setup.py           # orchestration (+ repair/version compare)
build/                 # PyInstaller scripts per OS
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| Second instance won't open | Use the wizard's shortcut, not the original Claude shortcut. |
| "Self-test failed" | This Claude version changed its startup code; the old copy keeps working. Update this tool. |
| "Claude process(es) are running from the patched copy" | Close all extra Claude windows (check the tray), then re-run. |
| Exit code `-36861` on Windows | Integrity fuse still on — re-run the wizard. |
| Both instances share one profile | Launcher must pass `--user-data-dir` to the patched copy exe. |
| Old taskbar pin opens the wrong thing | Unpin it and pin the new colored desktop shortcut instead. |
| Icons are plain Claude icons | Pillow was missing when the tool was built/run; rebuild with `requirements.txt`. |
