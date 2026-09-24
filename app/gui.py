"""Stylish, modern welcome + setup wizard GUI (Tkinter)."""

from __future__ import annotations

import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from .core import icons, startup
from .core.platform import Platform, safe_name, validate_names
from .core.setup import ClaudeSetup, SetupConfig

BG = "#0f1115"
PANEL = "#161a22"
ACCENT = "#d97757"
ACCENT_DK = "#b25e41"
TEXT = "#e8e6e3"
MUTED = "#9aa3b2"
BORDER = "#232a35"
GOOD = "#7ed491"
BAD = "#e5484d"

MAX_INSTANCES = 10


class _Tooltip:
    """Minimal hover tooltip."""

    def __init__(self, widget: tk.Widget, text: str) -> None:
        self.widget, self.text, self.tip = widget, text, None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def _show(self, _e=None) -> None:
        x = self.widget.winfo_rootx() + 10
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        tk.Label(self.tip, text=self.text, bg="#242b38", fg=TEXT, padx=6, pady=2,
                 font=("Segoe UI", 8)).pack()

    def _hide(self, _e=None) -> None:
        if self.tip:
            self.tip.destroy()
            self.tip = None


def _swatch(parent, color: str, command, width: int = 4, height: int = 1) -> tk.Label:
    """A clickable color square. A Label, not a Button: macOS ignores the
    background color of tk.Button, which would show every swatch as white."""
    sw = tk.Label(parent, bg=color, width=width, height=height, cursor="hand2",
                  highlightthickness=1, highlightbackground=BORDER)
    sw.bind("<Button-1>", lambda _e: command())
    return sw


class SetupWizard(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Claude Multi-Instance Setup")
        self.geometry("820x660")
        self.minsize(760, 600)
        self.configure(bg=BG)
        self.app = ClaudeSetup()
        self._style()
        self._busy = False
        self.installs = []

        self._build_header()
        self._container = ttk.Frame(self, style="Panel.TFrame")
        self._container.pack(fill="both", expand=True, padx=18, pady=(0, 14))
        self._show_scan()

    # ------------------------------------------------------------------ UI -- #

    def _style(self) -> None:
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("Panel.TFrame", background=PANEL)
        s.configure("Card.TFrame", background="#1b212c", relief="flat")
        s.configure(
            "TButton",
            background=ACCENT,
            foreground="#1a1410",
            font=("Segoe UI", 10, "bold"),
            padding=(18, 9),
            borderwidth=0,
            focuscolor=ACCENT,
        )
        s.map("TButton", background=[("active", ACCENT_DK)])
        s.configure("Ghost.TButton", background="#242b38", foreground=TEXT)
        s.map("Ghost.TButton", background=[("active", "#2d3544")])
        s.configure("Danger.TButton", background=BAD, foreground="#ffffff")
        s.map("Danger.TButton", background=[("disabled", "#3a2a2d"), ("active", "#c93b40")],
              foreground=[("disabled", "#7d6a6c")])
        s.configure(
            "TEntry",
            fieldbackground="#12161d",
            foreground=TEXT,
            insertcolor=TEXT,
            bordercolor=BORDER,
            padding=8,
        )
        s.configure("TLabel", background=PANEL, foreground=TEXT, font=("Segoe UI", 10))
        s.configure("Title.TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 17, "bold"))
        s.configure("Sub.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 10))
        s.configure("Accent.TLabel", background=ACCENT, foreground="#1a1410", font=("Segoe UI", 9, "bold"))
        s.configure("Good.TLabel", background=PANEL, foreground=GOOD)
        s.configure("Bad.TLabel", background=PANEL, foreground=BAD)
        s.configure("Log.TLabel", background="#0c0f13", foreground="#a8b3c2", font=("Cascadia Mono", 9))
        s.configure("Metal.Horizontal.TProgressbar", troughcolor="#0c0f13", background=ACCENT, bordercolor=BG)

    def _build_header(self) -> None:
        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", padx=20, pady=(18, 4))
        tk.Label(head, text="Claude Instance Setup", bg=BG, fg=TEXT,
                 font=("Segoe UI", 18, "bold")).pack(anchor="w")
        tk.Label(head, text="Run multiple isolated Claude Desktop profiles side-by-side.",
                 bg=BG, fg=MUTED, font=("Segoe UI", 10)).pack(anchor="w")

    def _clear(self) -> None:
        for w in self._container.winfo_children():
            w.destroy()

    def _badge(self, parent, text: str, color: str = GOOD, fg: str = "#11151c") -> tk.Label:
        return tk.Label(parent, text=f"  {text}  ", bg=color, fg=fg,
                        font=("Segoe UI", 9, "bold"))

    # ------------------------------------------------------------- screens -- #

    def _show_scan(self) -> None:
        self._clear()
        self._busy = True
        tk.Label(self._container, text="Detecting your system...", bg=PANEL, fg=TEXT,
                 font=("Segoe UI", 13)).pack(pady=(10, 6))
        prog = ttk.Progressbar(self._container, style="Metal.Horizontal.TProgressbar", mode="indeterminate", length=320)
        prog.pack(pady=12)
        prog.start(14)

        def scan() -> None:
            try:
                installs = self.app.platform.find_claude()
                self.after(0, lambda: self._after_scan(installs))
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda e=str(exc): self._after_scan([], e))

        threading.Thread(target=scan, daemon=True).start()

    def _after_scan(self, installs, error: str = "") -> None:
        self._busy = False
        self.installs = installs
        if error:
            self._clear()
            tk.Label(self._container, text="Scan failed", bg=PANEL, fg=BAD,
                     font=("Segoe UI", 14, "bold")).pack(pady=20)
            tk.Label(self._container, text=error, bg=PANEL, fg=MUTED).pack()
            return
        if not installs:
            self._clear()
            tk.Label(self._container, text="Claude Desktop not found", bg=PANEL, fg=BAD,
                     font=("Segoe UI", 14, "bold")).pack(pady=20)
            tk.Label(self._container, text="Install Claude Desktop first, then re-run this wizard.",
                     bg=PANEL, fg=MUTED).pack()
            return
        self.existing_names = self.app.platform.detect_existing_instances()
        self.saved_styles = {m["name"]: m for m in self.app.platform.load_manifest()}
        self._show_configure()

    # ------------------------------------------------------------- config -- #

    def _show_configure(self) -> None:
        self._clear()
        p = self.app.platform

        # --- Claude update / repair banner ----------------------------------
        if p.is_windows and self.installs:
            try:
                from .core.update_check import pending_update

                pending = pending_update(p)
                if pending:
                    warn = tk.Label(
                        self._container,
                        text=(f"Claude was updated: {pending[0]} -> {pending[1]}.\n"
                              "Your existing instances still run the older build. "
                              "Close them, then click Continue and Install to update them."),
                        bg="#21170f", fg="#e0b98f", wraplength=660, justify="left",
                        font=("Segoe UI", 9, "bold"))
                    warn.pack(fill="x", pady=(0, 8))
            except Exception:
                pass

        tk.Label(self._container, text=f"{p.os.title()} detected",
                 bg=PANEL, fg=TEXT, font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(4, 2))
        for inst in self.installs[:1]:
            row = tk.Frame(self._container, bg=PANEL)
            row.pack(fill="x", pady=2)
            self._badge(row, inst.kind.upper(), GOOD if inst.kind in ("msix", "app") else MUTED).pack(side="left")
            tk.Label(row, text=inst.exe_path or inst.app_dir, bg=PANEL, fg=MUTED,
                     wraplength=560, justify="left").pack(side="left", padx=10)

        # --- existing instances hint ------------------------------------------
        existing = getattr(self, "existing_names", [])
        if existing:
            hint = tk.Frame(self._container, bg=PANEL)
            hint.pack(fill="x", pady=(6, 0))
            tk.Label(hint, text="Found existing instances:", bg=PANEL, fg=GOOD,
                     font=("Segoe UI", 9, "bold")).pack(side="left")
            tk.Label(hint, text=", ".join(existing), bg=PANEL, fg=TEXT,
                     font=("Segoe UI", 9)).pack(side="left", padx=8)

        tk.Label(self._container, text="How many instances do you want (besides the original)?",
                 bg=PANEL, fg=TEXT, font=("Segoe UI", 11)).pack(anchor="w", pady=(12, 2))
        tk.Label(self._container,
                 text="Original Claude stays on its default profile. Each extra one gets an isolated "
                      "profile and its own icon color, so you can tell them apart.",
                 bg=PANEL, fg=MUTED, wraplength=660, justify="left").pack(anchor="w")

        if not hasattr(self, "count_var"):
            self.count_var = tk.IntVar(value=max(1, len(existing)))
        counter = tk.Frame(self._container, bg=PANEL)
        counter.pack(anchor="w", pady=8)
        ttk.Button(counter, text="−", style="Ghost.TButton", width=3,
                   command=lambda: self.count_var.set(max(1, self.count_var.get() - 1))).pack(side="left", padx=2)
        ttk.Spinbox(counter, from_=1, to=MAX_INSTANCES, textvariable=self.count_var, width=5,
                    font=("Segoe UI", 12)).pack(side="left", padx=4)
        ttk.Button(counter, text="+", style="Ghost.TButton", width=3,
                   command=lambda: self.count_var.set(min(MAX_INSTANCES, self.count_var.get() + 1))).pack(side="left", padx=2)

        head = tk.Frame(self._container, bg=PANEL)
        head.pack(fill="x", pady=(6, 0))
        for text, width in (("", 11), ("Name", 30), ("Color", 7), ("Badge", 7), ("Icon", 7)):
            tk.Label(head, text=text, bg=PANEL, fg=MUTED, width=width, anchor="w",
                     font=("Segoe UI", 8, "bold")).pack(side="left")
        self.all_startup_var = tk.BooleanVar(value=False)
        tk.Checkbutton(head, text="Start at sign-in", variable=self.all_startup_var, bg=PANEL, fg=MUTED,
                       selectcolor="#12161d", activebackground=PANEL, activeforeground=TEXT,
                       font=("Segoe UI", 8, "bold"), command=self._toggle_all_startup).pack(side="left")

        self.name_frame = self._scroll_area(self._container, height=250)
        self.rows: list[dict] = []
        self._rebuild_names()
        if not getattr(self, "_count_traced", False):
            self.count_var.trace_add("write", lambda *_: self._on_count_change())
            self._count_traced = True

        foot = tk.Frame(self._container, bg=PANEL)
        foot.pack(fill="x", side="bottom", pady=10)
        ttk.Button(foot, text="Back", style="Ghost.TButton", command=self._show_scan).pack(side="left")
        ttk.Button(foot, text="Continue", command=self._continue).pack(side="right")
        if existing:
            ttk.Button(foot, text="Remove instances…", style="Ghost.TButton",
                       command=self._show_remove).pack(side="right", padx=8)
            ttk.Button(foot, text="Startup…", style="Ghost.TButton",
                       command=self._show_startup).pack(side="right")

    def _scroll_area(self, parent, height: int) -> tk.Frame:
        """A vertically scrollable frame (instance rows can outgrow the window)."""
        outer = tk.Frame(parent, bg=PANEL)
        outer.pack(fill="both", expand=True, pady=4)
        canvas = tk.Canvas(outer, bg=PANEL, highlightthickness=0, height=height)
        bar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=PANEL)
        inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        def wheel(e):
            if canvas.winfo_exists():
                # Windows reports multiples of 120 per notch, macOS small raw deltas
                step = -e.delta if sys.platform == "darwin" else int(-e.delta / 120)
                canvas.yview_scroll(step, "units")

        canvas.bind_all("<MouseWheel>", wheel)
        return inner

    def _on_count_change(self) -> None:
        try:
            self.count_var.get()
        except tk.TclError:
            return  # spinbox is mid-edit
        if getattr(self, "name_frame", None) is not None and self.name_frame.winfo_exists():
            self._rebuild_names()

    def _row_states(self) -> list[dict]:
        """Current (or initial) name/color/badge for each row."""
        if getattr(self, "rows", None):
            return [{"name": r["name"].get(), "color": r["color"], "badge": r["badge"].get(),
                     "badge_custom": r["badge_custom"], "startup": r["startup"].get()} for r in self.rows]
        states = []
        for i, name in enumerate(getattr(self, "existing_names", [])):
            st = self.saved_styles.get(name, {})
            states.append({"name": name, "color": st.get("color") or icons.default_color(i),
                           "badge": st.get("badge", icons.default_badge(name)),
                           "badge_custom": "badge" in st,
                           "startup": startup.is_enabled(name, self.app.platform)})
        return states

    def _rebuild_names(self) -> None:
        states = self._row_states()
        for w in self.name_frame.winfo_children():
            w.destroy()
        self.rows = []
        n = max(1, min(MAX_INSTANCES, self.count_var.get()))
        used = {s["name"].strip().lower() for s in states}
        k = 2
        while len(states) < n:
            while f"instance {k}" in used:
                k += 1
            name = f"Instance {k}"
            used.add(name.lower())
            states.append({"name": name, "color": icons.default_color(len(states)),
                           "badge": icons.default_badge(name), "badge_custom": False, "startup": False})
        for i, st in enumerate(states[:n]):
            self._add_row(i, st)
        self._sync_all_startup()

    def _add_row(self, i: int, st: dict) -> None:
        row = tk.Frame(self.name_frame, bg=PANEL)
        row.pack(fill="x", pady=3)
        tk.Label(row, text=f"Instance {i + 1}:", bg=PANEL, fg=MUTED, width=11,
                 anchor="w").pack(side="left")
        name_var = tk.StringVar(value=st["name"])
        tk.Entry(row, textvariable=name_var, bg="#12161d", fg=TEXT, insertbackground=TEXT,
                 relief="flat", font=("Segoe UI", 10), highlightthickness=1, width=28,
                 highlightbackground=BORDER, highlightcolor=ACCENT).pack(side="left", ipady=4)
        state = {"name": name_var, "color": st["color"], "badge_custom": st["badge_custom"]}

        swatch = _swatch(row, st["color"], lambda: self._pick_color(state))
        swatch.pack(side="left", padx=(14, 0), ipady=3)
        state["swatch"] = swatch

        badge_var = tk.StringVar(value=st["badge"])
        badge_entry = tk.Entry(row, textvariable=badge_var, width=4, justify="center",
                               bg="#12161d", fg=TEXT, insertbackground=TEXT, relief="flat",
                               font=("Segoe UI", 10, "bold"), highlightthickness=1,
                               highlightbackground=BORDER, highlightcolor=ACCENT)
        badge_entry.pack(side="left", padx=(26, 0), ipady=4)
        state["badge"] = badge_var

        preview = tk.Label(row, bg=PANEL)
        preview.pack(side="left", padx=(24, 0))
        state["preview"] = preview

        startup_var = tk.BooleanVar(value=st.get("startup", False))
        tk.Checkbutton(row, variable=startup_var, bg=PANEL, fg=TEXT, selectcolor="#12161d",
                       activebackground=PANEL, command=self._sync_all_startup).pack(side="left", padx=(38, 0))
        state["startup"] = startup_var

        def on_name(*_):
            if not state["badge_custom"]:
                state["_sync"] = True
                badge_var.set(icons.default_badge(name_var.get()))
                state["_sync"] = False
            self._refresh_preview(state)

        def on_badge(*_):
            if len(badge_var.get()) > 2:
                badge_var.set(badge_var.get()[:2])
                return
            if not state.get("_sync"):
                state["badge_custom"] = True
            self._refresh_preview(state)

        name_var.trace_add("write", on_name)
        badge_var.trace_add("write", on_badge)
        self.rows.append(state)
        self._refresh_preview(state)

    def _refresh_preview(self, state: dict) -> None:
        state["swatch"].configure(bg=state["color"])
        if not icons.available():
            state["preview"].configure(text="", image="")
            return
        from PIL import ImageTk

        img = icons.render(state["color"], state["badge"].get(), 36, self._icon_source())
        state["photo"] = ImageTk.PhotoImage(img)  # keep a reference
        state["preview"].configure(image=state["photo"])

    def _icon_source(self) -> str | None:
        inst = self.installs[0] if self.installs else None
        return icons.claude_icon_source(inst.resources_dir if inst else None)

    def _pick_color(self, state: dict) -> None:
        pop = tk.Toplevel(self)
        pop.title("Pick a color")
        pop.configure(bg=PANEL)
        pop.transient(self)
        pop.resizable(False, False)
        tk.Label(pop, text="Icon color", bg=PANEL, fg=TEXT,
                 font=("Segoe UI", 10, "bold")).grid(row=0, column=0, columnspan=6, pady=(10, 6))

        def choose(color: str) -> None:
            state["color"] = color
            self._refresh_preview(state)
            pop.destroy()

        for k, (label, color) in enumerate(icons.PALETTE):
            b = _swatch(pop, color, lambda c=color: choose(c), height=2)
            b.grid(row=1 + k // 6, column=k % 6, padx=4, pady=4)
            _Tooltip(b, label)

        def custom() -> None:
            from tkinter import colorchooser

            _rgb, hex_color = colorchooser.askcolor(state["color"], parent=pop, title="Custom color")
            if hex_color:
                choose(icons.normalize_color(hex_color) or state["color"])

        ttk.Button(pop, text="Custom…", style="Ghost.TButton", command=custom).grid(
            row=3, column=0, columnspan=6, pady=(6, 10))
        pop.grab_set()

    def _continue(self) -> None:
        names = [r["name"].get().strip() for r in self.rows]
        problems = validate_names(names)
        if problems:
            messagebox.showerror("Check the instance names", "\n".join(problems))
            return
        self.names = names
        self.styles = {r["name"].get().strip(): {"color": r["color"], "badge": r["badge"].get().strip(),
                                                 "startup": r["startup"].get()}
                       for r in self.rows}
        self._show_review()

    def _toggle_all_startup(self) -> None:
        for r in self.rows:
            r["startup"].set(self.all_startup_var.get())

    def _sync_all_startup(self) -> None:
        if getattr(self, "all_startup_var", None) is not None:
            self.all_startup_var.set(bool(self.rows) and all(r["startup"].get() for r in self.rows))

    # -------------------------------------------------------------- startup -- #

    def _show_startup(self) -> None:
        """Turn start-at-sign-in on/off for existing instances; applies at once."""
        from .core.remove import known_instances

        self._clear()
        tk.Label(self._container, text="Start at sign-in", bg=PANEL, fg=TEXT,
                 font=("Segoe UI", 13, "bold")).pack(anchor="w", pady=(4, 2))
        tk.Label(self._container,
                 text="Ticked instances open automatically when you sign in to "
                      + ("Windows. They also appear in Task Manager > Startup apps."
                         if self.app.platform.is_windows else "your computer."),
                 bg=PANEL, fg=MUTED, wraplength=660, justify="left").pack(anchor="w", pady=(0, 8))

        bar = tk.Frame(self._container, bg=PANEL)
        bar.pack(fill="x", pady=(0, 4))
        ttk.Button(bar, text="Enable all", style="Ghost.TButton",
                   command=lambda: [v.set(True) for _i, v in self._startup_rows]).pack(side="left")
        ttk.Button(bar, text="Disable all", style="Ghost.TButton",
                   command=lambda: [v.set(False) for _i, v in self._startup_rows]).pack(side="left", padx=8)

        area = self._scroll_area(self._container, height=260)
        self._startup_rows = []
        self._review_photos = []
        for k, inst in enumerate(known_instances(self.app.platform)):
            row = tk.Frame(area, bg=PANEL)
            row.pack(fill="x", pady=3)
            var = tk.BooleanVar(value=startup.is_enabled(inst.name, self.app.platform))
            tk.Checkbutton(row, variable=var, bg=PANEL, fg=TEXT, activebackground=PANEL,
                           selectcolor="#12161d").pack(side="left")
            if icons.available():
                from PIL import ImageTk

                photo = ImageTk.PhotoImage(icons.render(inst.color or icons.default_color(k),
                                                        inst.badge, 28, self._icon_source()))
                self._review_photos.append(photo)
                tk.Label(row, image=photo, bg=PANEL).pack(side="left", padx=(2, 8))
            tk.Label(row, text=inst.name, bg=PANEL, fg=TEXT, anchor="w",
                     font=("Segoe UI", 10, "bold")).pack(side="left")
            self._startup_rows.append((inst, var))

        foot = tk.Frame(self._container, bg=PANEL)
        foot.pack(fill="x", side="bottom", pady=8)
        ttk.Button(foot, text="Back", style="Ghost.TButton", command=self._show_configure).pack(side="left")
        ttk.Button(foot, text="Save", command=self._save_startup).pack(side="right")

    def _save_startup(self) -> None:
        choices = {inst.name: var.get() for inst, var in self._startup_rows}
        problems = startup.apply(choices)
        if problems:
            messagebox.showerror("Startup", "Some changes could not be applied:\n" + "\n".join(problems))
        else:
            on = [n for n, v in choices.items() if v]
            messagebox.showinfo("Startup", ("These instances will start at sign-in: " + ", ".join(on))
                                if on else "No instances will start at sign-in.")
        # row states on the main screen should reflect the change
        self.rows = []
        self._show_configure()

    # --------------------------------------------------------------- review -- #

    def _show_review(self) -> None:
        names = self.names
        self._clear()

        tk.Label(self._container, text="Review your setup", bg=PANEL, fg=TEXT,
                 font=("Segoe UI", 13, "bold")).pack(anchor="w", pady=(4, 6))
        p = self.app.platform
        row = tk.Frame(self._container, bg=PANEL)
        row.pack(fill="x", pady=2)
        tk.Label(row, text="Platform", bg=PANEL, fg=MUTED, width=12, anchor="w").pack(side="left")
        tk.Label(row, text=p.os.title(), bg=PANEL, fg=TEXT, anchor="w").pack(side="left")

        tk.Label(self._container, text="Instances", bg=PANEL, fg=MUTED, anchor="w").pack(fill="x", pady=(8, 2))
        self._review_photos = []
        for n in names:
            r = tk.Frame(self._container, bg=PANEL)
            r.pack(fill="x", pady=2)
            st = self.styles.get(n, {})
            if icons.available():
                from PIL import ImageTk

                photo = ImageTk.PhotoImage(icons.render(st.get("color", ""), st.get("badge", ""), 28,
                                                        self._icon_source()))
                self._review_photos.append(photo)
                tk.Label(r, image=photo, bg=PANEL).pack(side="left", padx=(0, 8))
            tk.Label(r, text=n, bg=PANEL, fg=TEXT, width=20, anchor="w",
                     font=("Segoe UI", 10, "bold")).pack(side="left")
            tk.Label(r, text=p.profile_dir(safe_name(n)), bg=PANEL, fg=MUTED, anchor="w",
                     font=("Cascadia Mono", 9)).pack(side="left")
            if st.get("startup"):
                self._badge(r, "starts at sign-in", "#3b4a63", fg=TEXT).pack(side="right", padx=8)

        if p.is_windows:
            from .core import update_check

            self.update_var = tk.BooleanVar(value=True)
            tk.Checkbutton(self._container, variable=self.update_var, bg=PANEL, fg=TEXT,
                           selectcolor="#12161d", activebackground=PANEL, activeforeground=TEXT,
                           text="When Claude updates, remind me at sign-in to update these instances",
                           font=("Segoe UI", 9)).pack(anchor="w", pady=(10, 0))
            warn = tk.Label(self._container,
                            text="Windows: a patched copy of Claude is created for the extra instances. "
                                 "The original Claude is not modified.",
                            bg="#21170f", fg="#e0b98f", wraplength=660, justify="left",
                            font=("Segoe UI", 9))
            warn.pack(fill="x", pady=8)

        foot = tk.Frame(self._container, bg=PANEL)
        foot.pack(fill="x", side="bottom", pady=8)
        ttk.Button(foot, text="Back", style="Ghost.TButton", command=self._show_configure).pack(side="left")
        ttk.Button(foot, text="Install", command=self._run_setup).pack(side="right")

    # --------------------------------------------------------------- remove -- #

    def _show_remove(self) -> None:
        from .core.remove import known_instances

        self._clear()
        tk.Label(self._container, text="Remove instances", bg=PANEL, fg=TEXT,
                 font=("Segoe UI", 13, "bold")).pack(anchor="w", pady=(4, 2))
        tk.Label(self._container,
                 text="Removes the selected instances' shortcuts, launchers and icons. "
                      "Your original Claude is never touched. Close the instances first.",
                 bg=PANEL, fg=MUTED, wraplength=660, justify="left").pack(anchor="w", pady=(0, 8))

        known = known_instances(self.app.platform)
        if not known:
            tk.Label(self._container, text="No instances found.", bg=PANEL, fg=TEXT).pack(anchor="w")
        area = self._scroll_area(self._container, height=200)
        self._remove_rows = []
        self._review_photos = []
        for k, inst in enumerate(known):
            row = tk.Frame(area, bg=PANEL)
            row.pack(fill="x", pady=3)
            var = tk.BooleanVar(value=False)
            tk.Checkbutton(row, variable=var, bg=PANEL, fg=TEXT, activebackground=PANEL, selectcolor="#12161d",
                           command=self._update_remove_options).pack(side="left")
            if icons.available():
                from PIL import ImageTk

                photo = ImageTk.PhotoImage(icons.render(inst.color or icons.default_color(k),
                                                        inst.badge, 28, self._icon_source()))
                self._review_photos.append(photo)
                tk.Label(row, image=photo, bg=PANEL).pack(side="left", padx=(2, 8))
            tk.Label(row, text=inst.name, bg=PANEL, fg=TEXT, width=18, anchor="w",
                     font=("Segoe UI", 10, "bold")).pack(side="left")
            size = tk.Label(row, text="…", bg=PANEL, fg=MUTED, width=10, anchor="e")
            size.pack(side="right", padx=8)
            tk.Label(row, text=inst.profile_dir, bg=PANEL, fg=MUTED, anchor="w",
                     font=("Cascadia Mono", 8)).pack(side="left")
            self._remove_rows.append((inst, var))
            self._measure_async(inst, size)

        self.delete_data_var = tk.BooleanVar(value=False)
        tk.Checkbutton(self._container, variable=self.delete_data_var, bg=PANEL, fg=TEXT,
                       selectcolor="#12161d", activebackground=PANEL, activeforeground=TEXT,
                       text="Also delete their data (sign-ins, local chat cache, settings). "
                            "It goes to the Recycle Bin, so it can be restored.",
                       font=("Segoe UI", 9), wraplength=660, justify="left").pack(anchor="w", pady=(10, 0))
        tk.Label(self._container, text="Your claude.ai accounts and the chats stored in them are not affected.",
                 bg=PANEL, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w", padx=24)
        self.uninstall_var = tk.BooleanVar(value=False)
        self._uninstall_cb = tk.Checkbutton(
            self._container, variable=self.uninstall_var, bg=PANEL, fg=TEXT, selectcolor="#12161d",
            activebackground=PANEL, activeforeground=TEXT, disabledforeground="#566070",
            text="Full uninstall: also remove the shared Claude copy and the update reminder "
                 "(select all instances to enable)",
            font=("Segoe UI", 9), wraplength=660, justify="left", state="disabled")
        self._uninstall_cb.pack(anchor="w", pady=(6, 0))

        foot = tk.Frame(self._container, bg=PANEL)
        foot.pack(fill="x", side="bottom", pady=8)
        ttk.Button(foot, text="Back", style="Ghost.TButton", command=self._show_configure).pack(side="left")
        self._remove_btn = ttk.Button(foot, text="Remove selected", style="Danger.TButton",
                                      command=self._confirm_remove, state="disabled")
        self._remove_btn.pack(side="right")

    def _measure_async(self, inst, label: tk.Label) -> None:
        def work() -> None:
            n = inst.profile_size() if os.path.isdir(inst.profile_dir) else 0
            text = "no data" if not n else (f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB")
            self.after(0, lambda: label.winfo_exists() and label.configure(text=text))

        threading.Thread(target=work, daemon=True).start()

    def _update_remove_options(self) -> None:
        chosen = [i for i, v in self._remove_rows if v.get()]
        everything = bool(chosen) and len(chosen) == len(self._remove_rows)
        self._uninstall_cb.configure(state="normal" if everything else "disabled")
        if not everything:
            self.uninstall_var.set(False)
        self._remove_btn.configure(state="normal" if chosen else "disabled")

    def _confirm_remove(self) -> None:
        chosen = [i for i, v in self._remove_rows if v.get()]
        if not chosen:
            return
        lines = [f"Remove {len(chosen)} instance(s): {', '.join(i.name for i in chosen)}?", ""]
        lines.append("Their desktop shortcuts, launchers and icons will be deleted.")
        if self.delete_data_var.get():
            lines.append("Their profiles (sign-ins, local chat cache, settings) will be moved to "
                         "the Recycle Bin.")
        else:
            lines.append("Their profile folders are kept, so re-adding an instance with the same "
                         "name brings its sign-in back.")
        if self.uninstall_var.get():
            lines.append("The shared Claude copy and the update reminder will be removed.")
        if not messagebox.askyesno("Remove instances", "\n".join(lines), icon="warning"):
            return
        names = [i.name for i in chosen]
        delete_data, uninstall = self.delete_data_var.get(), self.uninstall_var.get()
        def task(log):
            from .core.remove import remove_instances

            return remove_instances(names, delete_data=delete_data, uninstall=uninstall, log=log)

        self._run_task(task, "Removal")

    # --------------------------------------------------------------- install -- #

    def _run_setup(self) -> None:
        cfg = SetupConfig(instance_names=self.names, make_shortcuts=True, styles=self.styles,
                          update_check=bool(getattr(self, "update_var", None) and self.update_var.get()))

        def task(log):
            self.app.log = log
            return self.app.run(cfg)

        self._run_task(task, "Setup")

    def _run_task(self, fn, title: str) -> None:
        """Run fn(log) -> result(.ok, .message) off the UI thread with a live log."""
        self._clear()
        self._busy = True
        log_box = tk.Text(self._container, bg="#0c0f13", fg="#a8b3c2", relief="flat",
                          font=("Cascadia Mono", 9), state="disabled", wrap="word",
                          insertbackground=TEXT)
        log_box.pack(fill="both", expand=True, pady=(6, 10))

        bar = ttk.Progressbar(self._container, style="Metal.Horizontal.TProgressbar", mode="indeterminate")
        bar.pack(fill="x")
        bar.start(16)

        q: "queue.Queue[tuple[str, object]]" = queue.Queue()

        def log(msg: str) -> None:
            q.put(("msg", msg))

        def worker() -> None:
            try:
                result = fn(log)
            except Exception as exc:  # noqa: BLE001
                result = type("R", (), {"ok": False, "message": str(exc)})()
            if not result.ok:
                log(f"ERROR: {result.message}")
            log(f"=== {title} finished: " + ("OK" if result.ok else "FAILED") + " ===")
            q.put(("done", result))

        threading.Thread(target=worker, daemon=True).start()

        def pump() -> None:
            try:
                while True:
                    kind, payload = q.get_nowait()
                    if kind == "done":
                        bar.stop()
                        self._finish_task(title, payload)
                        return
                    log_box.configure(state="normal")
                    log_box.insert("end", f"{payload}\n")
                    log_box.see("end")
                    log_box.configure(state="disabled")
            except queue.Empty:
                pass
            self.after(120, pump)

        self.after(120, pump)

    def _finish_task(self, title: str, result) -> None:
        self._busy = False
        if title == "Setup" and result.ok:
            messagebox.showinfo("Done", "Setup complete.\n\n"
                                "Open each colored desktop shortcut and sign in. Each instance keeps "
                                "its own profile, and its window title shows the instance name.\n\n"
                                "When Claude updates, re-run this wizard (or accept the sign-in "
                                "reminder) to update the instances.")
        elif result.ok:
            messagebox.showinfo("Done", result.message)
        else:
            messagebox.showerror(f"{title} failed", result.message)
        # forget the rows so the next screen reflects what is on disk now
        self.rows = []
        if hasattr(self, "count_var"):
            del self.count_var
            self._count_traced = False
        self._show_scan()


def launch() -> None:
    app = SetupWizard()
    app.mainloop()