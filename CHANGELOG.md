# Changelog

## v1.5 (2026-09-24)

### New
- **Pinned instances keep their colored icon on the taskbar.** Each shortcut
  now carries the same taskbar identity (AppUserModelID) as its running
  window, so a pinned instance and its window share one taskbar button.
- **Start menu entries**: each instance gets a Start menu shortcut
  ("Claude Instances" folder), so you can open it by typing its name in
  Windows search. "Pin to taskbar" on a running instance pins this shortcut,
  so the pin opens the right instance with its colored icon.
- **Switch folders between instances**: in **Profile…**, a folder used by
  another instance can now be chosen; the two instances swap folders.
  **Start fresh** (a new, empty folder) is always offered, and **Browse…**
  picks any location.

### Changed
- Windows now shows each running instance's name and colored icon when you
  right-click its taskbar button.

## v1.4 (2026-09-24)

### New
- **Continue an existing Claude**: each instance shows whether it continues an
  existing profile (with its sign-in, local chats and sessions) or starts fresh.
  **Profile…** lets you pick any existing Claude folder, or browse for one.
- **Renaming keeps data**: a renamed instance keeps its profile folder, and the
  old name's shortcuts and startup entry are cleaned up. Previously a new name
  meant a new, empty folder.

### Fixed
- The Microsoft Store Claude keeps its data inside its package folder
  (`…\Packages\Claude_…\LocalCache\Roaming\Claude`). The tool now
  recognizes it as your main Claude's folder and never assigns it to an instance.
- Two instances can no longer be set to the same folder.

## v1.3 (2026-09-24)

### macOS
- Each instance is now its own app in `~/Applications` (e.g. **Claude Work.app**)
  with its colored icon. Open it with Spotlight, Launchpad or Finder, or pin it
  to the Dock. This replaces the Desktop `.command` files, which are removed
  automatically.
- Start at login now runs the instance's own app, so System Settings → Login
  Items shows "Claude Work" rather than "open".

### Fixes
- The "starts at sign-in" label on the review screen was nearly unreadable.

## v1.2 (2026-09-24)

A large rework that fixes the problems in v1.1 and adds new features.

### New
- **Colored icons with badges** per instance, with a palette or custom color and a live preview. On Windows they're also used for the window and taskbar button.
- **Instance name in the window title** (`Claude — Work`) and a separate taskbar button per instance (Windows).
- **Start at sign-in**, per instance or all at once, plus a quick **Startup…** screen. It's respected by Task Manager → Startup apps.
- **Remove instances / full uninstall**, with optional data deletion to the Recycle Bin/Trash.
- **Update reminder at sign-in** (Windows) when Claude has been updated.
- **Name validation**: rejects invalid characters, reserved names, and names that clash with another instance or with Claude's own folders.
- Command-line options: `--list`, `--remove`, `--delete-data`, `--uninstall`, `--startup-on/--startup-off`, `--no-update-check`.
- macOS: `start-mac.sh` one-command start and `MAC-QUICKSTART.md`.

### Changed
- **Node.js is no longer required.** Asar patching and the fuse flip are done in pure Python.
- The patch now finds Claude's relocation code by its shape rather than its minified name (`DW`/`Cl`/`FJ` → `Nu`/`GY` in Claude 2.7x), and changed files are syntax-checked.
- **Self-test and safe swap**: the new copy is test-launched on a throwaway profile before it replaces the old one; a failed update leaves the working copy untouched. Repair refuses to run while instances are open.
- Windows launchers are plain `.lnk` shortcuts instead of VBScript.
- Install skips rebuilding the patched copy when it is already up to date.
- Shortcuts go to the real Desktop folder (which can be redirected by OneDrive).

### Fixed
- **The setup window crashed on launch** (invalid progress-bar style), and the tool then silently ran a setup that created "Instance 2".
- With one extra instance requested, no isolated instance was created (the first name was treated as the original).
- Setup progress and failure reasons were missing from the setup window's log.
- Linux support called a function that didn't exist.
- The macOS build failed (missing `icon.icns`); color swatches were blank on macOS.

## v1.1 (2026-09-16)

- Windows: repair after Claude updates (`--repair`), with a version check and an update banner.
- Pre-fills existing instances when the tool is run again.
- Patch recognizes the `FJ` relocation function of Claude 2.x.
- Known issues (fixed in v1.2): the setup window crashes on current Python/Tk, and the tool then silently creates "Instance 2"; requires Node.js.

## v1.0 (2026-09-15)

- First version. Windows: patched copy of the Store build with `.vbs` launchers;
  macOS/Linux: `.command` / shell launchers.
- Known issues (fixed in v1.2): same setup window crash as v1.1; `run.py` was missing from the source package.
