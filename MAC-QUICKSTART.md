# Claude Multi-Instance Setup on macOS: test guide

This is a test build. The Mac version has not been tried on a real Mac yet,
so please note anything odd (screenshots help).

## You need
- Claude Desktop installed in `/Applications` (or `~/Applications`).
- Python 3 with Tkinter. The installer from
  https://www.python.org/downloads/macos/ has both. (Homebrew Python needs
  `brew install python-tk`.)

## Run it
1. Unzip `Claude-Multi-Setup-v1.3-macOS.zip` (e.g. into Downloads).
2. Open **Terminal** and run:
   ```bash
   cd ~/Downloads/claude-multi-setup
   bash start-mac.sh
   ```
   The first run takes a minute (it sets up a private Python environment in
   the folder; nothing is installed system-wide).
3. The setup window opens. Pick names, colors and badges, then **Continue →
   Install**.
4. Each instance becomes its own app in your **Applications** folder, e.g.
   **Claude Work** and **Claude Personal**, with its colored icon:
   - open it with **Spotlight** (Command-Space, type "Claude Work"), Launchpad or Finder;
   - or use the shortcut on your Desktop;
   - you can drag it to the Dock to keep it there.
   The first time, macOS may ask to allow it: right-click → **Open**.

## What to check
- [ ] The setup window opens and finds Claude ("App" badge).
- [ ] Color swatches, badges and icon previews look right.
- [ ] Install finishes without errors.
- [ ] Spotlight finds "Claude Work" etc. with the colored icon, and opening it starts that instance.
- [ ] Two instances run **at the same time** with **different accounts**.
- [ ] Quit and reopen an instance: still signed in to the same account.
- [ ] **Startup…** → tick one → log out and back in: that instance opens by itself.
- [ ] **Remove instances…** removes the launcher (profile kept unless
      "Also delete their data" is ticked; then it goes to the Trash).
- [ ] The original Claude still opens normally with its own account.

## Known differences from Windows
- The Mac version doesn't modify Claude. The instance apps (Spotlight,
  Launchpad, Desktop, pinned in the Dock) have the colored icons, but a
  *running* instance shows Claude's normal icon in the Dock and window title.
- There is no sign-in update reminder on Mac. Claude updates in place and the
  instances use the updated app automatically.

## Useful commands (Terminal, in the folder)
```bash
bash start-mac.sh --list                       # instances + who starts at login
# re-run setup to update an older install: bash start-mac.sh  → Continue → Install
bash start-mac.sh --startup-off all            # stop all auto-starts
bash start-mac.sh --remove "Work"              # remove an instance (keeps data)
```

## Optional: build a double-clickable app
```bash
bash build/build_macos.sh
```
This produces `dist/Claude Multi Setup.app`. It's unsigned, so on another Mac
it needs right-click → Open the first time.

## If something goes wrong
Send the text from the Terminal window and a screenshot of the setup window's
log.
