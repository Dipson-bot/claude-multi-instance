"""Stylish, modern welcome + setup wizard GUI (Tkinter)."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from .core.platform import Platform
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


class SetupWizard(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Claude Multi-Instance Setup")
        self.geometry("760x560")
        self.minsize(700, 520)
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
        s.configure("Metal.TProgressbar", troughcolor="#0c0f13", background=ACCENT, bordercolor=BG)

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

    def _badge(self, parent, text: str, color: str = GOOD) -> tk.Label:
        return tk.Label(parent, text=f"  {text}  ", bg=color, fg="#11151c",
                        font=("Segoe UI", 9, "bold"))

    # ------------------------------------------------------------- screens -- #

    def _show_scan(self) -> None:
        self._clear()
        self._busy = True
        tk.Label(self._container, text="Detecting your system...", bg=PANEL, fg=TEXT,
                 font=("Segoe UI", 13)).pack(pady=(10, 6))
        prog = ttk.Progressbar(self._container, style="Metal.TProgressbar", mode="indeterminate", length=320)
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
        self._show_configure()

    # ------------------------------------------------------------- config -- #

    def _show_configure(self) -> None:
        self._clear()
        p = self.app.platform

        tk.Label(self._container, text=f"{p.os.title()} detected",
                 bg=PANEL, fg=TEXT, font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(4, 2))
        for inst in self.installs[:1]:
            row = tk.Frame(self._container, bg=PANEL)
            row.pack(fill="x", pady=2)
            self._badge(row, inst.kind.upper(), GOOD if inst.kind in ("msix", "app") else MUTED).pack(side="left")
            tk.Label(row, text=inst.exe_path or inst.app_dir, bg=PANEL, fg=MUTED,
                     wraplength=520, justify="left").pack(side="left", padx=10)

        tk.Label(self._container, text="", bg=PANEL).pack()
        tk.Label(self._container, text="How many instances do you want (besides the original) ?",
                 bg=PANEL, fg=TEXT, font=("Segoe UI", 11)).pack(anchor="w", pady=(10, 2))
        tk.Label(self._container,
                 text="Original Claude stays on its default profile. Each extra one gets an isolated profile.",
                 bg=PANEL, fg=MUTED).pack(anchor="w")

        self.count_var = tk.IntVar(value=2)
        counter = tk.Frame(self._container, bg=PANEL)
        counter.pack(anchor="w", pady=8)
        ttk.Button(counter, text="−", style="Ghost.TButton", width=3,
                   command=lambda: self.count_var.set(max(0, self.count_var.get() - 1))).pack(side="left", padx=2)
        ttk.Spinbox(counter, from_=0, to=10, textvariable=self.count_var, width=5,
                    font=("Segoe UI", 12)).pack(side="left", padx=4)
        ttk.Button(counter, text="+", style="Ghost.TButton", width=3,
                   command=lambda: self.count_var.set(min(10, self.count_var.get() + 1))).pack(side="left", padx=2)

        self.name_frame = tk.Frame(self._container, bg=PANEL)
        self.name_frame.pack(fill="x", pady=10)
        self.name_entries: list[tk.Entry] = []
        self._rebuild_names()

        self.count_var.trace_add("write", lambda *_: self._rebuild_names())

        foot = tk.Frame(self._container, bg=PANEL)
        foot.pack(fill="x", side="bottom", pady=10)
        ttk.Button(foot, text="Back", style="Ghost.TButton", command=self._show_scan).pack(side="left")
        ttk.Button(foot, text="Continue", command=self._show_review).pack(side="right")

    def _rebuild_names(self) -> None:
        for w in self.name_frame.winfo_children():
            w.destroy()
        self.name_entries.clear()
        defaults = ["Company", "Personal", "Work", "School", "Side"]
        n = self.count_var.get()
        for i in range(n):
            row = tk.Frame(self.name_frame, bg=PANEL)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=f"Instance {i + 1}:", bg=PANEL, fg=MUTED, width=11,
                     anchor="w").pack(side="left")
            ent = tk.Entry(row, bg="#12161d", fg=TEXT, insertbackground=TEXT, relief="flat",
                           font=("Segoe UI", 10), highlightthickness=1,
                           highlightbackground=BORDER, highlightcolor=ACCENT)
            ent.pack(side="left", fill="x", expand=True, ipady=4)
            ent.insert(0, defaults[i % len(defaults)])
            self.name_entries.append(ent)

    # --------------------------------------------------------------- review -- #

    def _show_review(self) -> None:
        names = [e.get().strip() for e in self.name_entries]
        names = [n for n in names if n]
        if not names:
            names = [f"Instance{i+1}" for i in range(self.count_var.get())]
        self.names = names
        self._clear()

        tk.Label(self._container, text="Review your setup", bg=PANEL, fg=TEXT,
                 font=("Segoe UI", 13, "bold")).pack(anchor="w", pady=(4, 6))
        p = self.app.platform
        rows = [
            ("Platform", p.os.title()),
            ("Instances", ", ".join(names)),
        ]
        for k, v in rows:
            row = tk.Frame(self._container, bg=PANEL)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=k, bg=PANEL, fg=MUTED, width=12, anchor="w").pack(side="left")
            tk.Label(row, text=v, bg=PANEL, fg=TEXT, anchor="w", wraplength=480, justify="left").pack(side="left")

        profiles = tk.Frame(self._container, bg=PANEL)
        profiles.pack(fill="x", pady=6)
        tk.Label(profiles, text="Profiles", bg=PANEL, fg=MUTED, width=12, anchor="w").pack(side="left")
        prof_col = tk.Frame(profiles, bg=PANEL)
        prof_col.pack(side="left", fill="x")
        for n in names:
            tk.Label(prof_col, text=p.profile_dir(n), bg=PANEL, fg=TEXT, anchor="w",
                     font=("Cascadia Mono", 9)).pack(fill="x")

        if p.is_windows:
            tk.Label(self._container, text="",
                     bg=PANEL).pack()
            warn = tk.Label(self._container,
                            text="Windows MSIX build: a patched copy will be created and the "
                                 "integrity fuse disabled so all instances can share the same binary.",
                            bg="#21170f", fg="#e0b98f", wraplength=600, justify="left",
                            font=("Segoe UI", 9))
            warn.pack(fill="x", pady=8)

        foot = tk.Frame(self._container, bg=PANEL)
        foot.pack(fill="x", side="bottom", pady=8)
        ttk.Button(foot, text="Back", style="Ghost.TButton", command=self._show_configure).pack(side="left")
        ttk.Button(foot, text="Install", command=self._run_setup).pack(side="right")

    # --------------------------------------------------------------- install -- #

    def _run_setup(self) -> None:
        self._clear()
        self._busy = True
        cfg = SetupConfig(instance_names=self.names, make_shortcuts=True)
        log_box = tk.Text(self._container, bg="#0c0f13", fg="#a8b3c2", relief="flat",
                          font=("Cascadia Mono", 9), state="disabled", wrap="word",
                          insertbackground=TEXT)
        log_box.pack(fill="both", expand=True, pady=(6, 10))

        bar = ttk.Progressbar(self._container, style="Metal.TProgressbar", mode="indeterminate")
        bar.pack(fill="x")
        bar.start(16)

        q: "queue.Queue[object]" = queue.Queue()
        done = threading.Event()

        def worker() -> None:
            result = self.app.run(cfg)
            q.put(("__msg__", "=== Setup finished: " + ("OK" if result.ok else "FAILED") + " ==="))
            q.put(("__done__", result.ok))
            done.set()

        threading.Thread(target=worker, daemon=True).start()

        def sink(msg: str) -> None:
            q.put(("__msg__", msg))

        self.app.log = sink

        def pump() -> None:
            try:
                while True:
                    kind, payload = q.get_nowait()  # type: ignore[misc]
                    if kind == "__done__":
                        self._finish_setup(bool(payload))
                        return
                    log_box.configure(state="normal")
                    log_box.insert("end", payload + "\n")
                    log_box.see("end")
                    log_box.configure(state="disabled")
            except queue.Empty:
                pass
            self.after(120, pump)

        self.after(120, pump)

    def _finish_setup(self, ok: bool) -> None:
        self._busy = False
        if ok:
            messagebox.showinfo("Done", "Setup complete.\n\n"
                                "Open each shortcut and sign in. Each instance keeps its own profile.")
        else:
            messagebox.showerror("Setup failed", "See the log above for details.")
        self._show_scan()


def launch() -> None:
    app = SetupWizard()
    app.mainloop()