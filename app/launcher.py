"""launcher.py - friendly double-click entry point for the GoW damage overlay.

Shows a small window to pick how to run:
  * Normal / Verbose / Damage-only  -> opens a terminal with live output
  * Silent                          -> confirms, then runs hidden in the background
  * Settings                        -> opens the settings window
It also shows whether the game is detected ("Waiting for game to launch...").

Works both as a PyInstaller .exe (double-click) and from source (python launcher.py).
The same executable re-launches itself with a run-mode arg to actually start the
overlay (so one file does everything)."""
import os
import sys
import subprocess
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

CREATE_NEW_CONSOLE = 0x00000010
CREATE_NO_WINDOW = 0x08000000

VERBOSITY_FLAG = {"normal": [], "verbose": ["--verbose"], "dmg": ["--dmg"], "silent": ["--silent"]}


# ---- run-mode dispatch (so this one file is also the app entry) --------------
def _dispatch():
    args = sys.argv[1:]
    if "--setup" in args:
        import procname
        procname.set_name(procname.SETUP)
        import setup_gui
        setup_gui.main()
        return True
    if "--run" in args:
        i = args.index("--run")
        mode = args[i + 1] if i + 1 < len(args) else "normal"
        import gow_overlay
        sys.argv = [sys.argv[0]] + VERBOSITY_FLAG.get(mode, [])
        try:
            gow_overlay.main()
        except KeyboardInterrupt:
            print("\nstopped.")
        return True
    return False


def _self_cmd():
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, os.path.join(HERE, "launcher.py")]


def _terminal_candidates():
    """Terminal emulators to try on Linux: (executable, argv prefix that makes
    the rest of the command run inside it)."""
    cands = []
    term = os.environ.get("TERMINAL")
    if term:
        cands.append((term, ["-e"]))                 # the common convention
    cands += [("konsole", ["-e"]), ("gnome-terminal", ["--"]), ("xfce4-terminal", ["-x"]),
              ("kitty", []), ("alacritty", ["-e"]), ("foot", []), ("xterm", ["-e"])]
    return cands


def _spawn(extra, show_console):
    """Start the overlay/settings child process; returns its Popen handle."""
    env = os.environ.copy()
    # A PyInstaller one-file child must NOT inherit the parent's _MEIPASS2: if it
    # does, it reuses the launcher's temp-extract dir instead of making its own and
    # dies (or corrupts state) when the launcher exits and cleans that dir up. This
    # is what made the .exe crash on the 2nd run. Strip it so the child extracts fresh.
    for v in ("_MEIPASS2", "_PYI_ARCHIVE_FILE", "_PYI_APPLICATION_HOME_DIR", "_PYI_PARENT_PROCESS_LEVEL"):
        env.pop(v, None)
    cmd = _self_cmd() + extra
    if sys.platform == "win32":
        flags = CREATE_NEW_CONSOLE if show_console else CREATE_NO_WINDOW
        return subprocess.Popen(cmd, creationflags=flags, cwd=HERE, close_fds=True, env=env)
    if show_console:
        import shutil
        for name, prefix in _terminal_candidates():
            if shutil.which(name):
                return subprocess.Popen([name] + prefix + cmd, cwd=HERE, env=env,
                                        start_new_session=True)
        # no terminal emulator found - run anyway, just without visible logs
    return subprocess.Popen(cmd, cwd=HERE, env=env, start_new_session=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _hide_console():
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        u32 = ctypes.windll.user32
        k32.GetConsoleWindow.restype = wintypes.HWND       # 64-bit-correct handle
        u32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        hwnd = k32.GetConsoleWindow()
        if hwnd:
            u32.ShowWindow(hwnd, 0)                         # SW_HIDE
    except Exception:
        pass


# ---- the launcher window -----------------------------------------------------
class LauncherApp:
    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk
        import guifont
        self.tk = tk
        self.root = root
        self.uifont = guifont.family() or "Segoe UI"   # GoW font, else a sane default
        # NOTE: the title must NOT contain "God of War" or "PCSX2" - the window
        # matchers look for those, and this launcher stays open while they run
        root.title("GoW Damage Overlay — Launcher")
        root.geometry("520x480")        # the God of War font is wider than a UI font
        root.resizable(False, False)
        self._status_text = "Looking for the game…"
        self._detected = False
        self._poll = True
        self._child = None        # overlay process started by THIS launcher
        self._ext = False         # an overlay from elsewhere is running (Linux)
        self._theme(ttk)          # black background, God of War red text
        # closing the launcher window stops every running overlay
        root.protocol("WM_DELETE_WINDOW", self._quit_all)

        wrap = ttk.Frame(root, padding=18)
        wrap.pack(fill="both", expand=True)
        ttk.Label(wrap, text="God of War", font=(self.uifont, 18, "bold"),
                  foreground=self.RED_BRIGHT).pack(anchor="w")
        ttk.Label(wrap, text="live damage-number overlay",
                  foreground=self.DIM).pack(anchor="w")

        # game status
        st = ttk.Frame(wrap); st.pack(fill="x", pady=(16, 8))
        self.dot = tk.Label(st, text="●", font=("Segoe UI", 13),
                            foreground="#e88000", background=self.BG)
        self.dot.pack(side="left")
        self.status = tk.StringVar(value="Looking for the game…")
        ttk.Label(st, textvariable=self.status).pack(side="left", padx=6)

        ttk.Separator(wrap).pack(fill="x", pady=6)

        ttk.Label(wrap, text="How would you like to run it?",
                  font=(self.uifont, 10, "bold")).pack(anchor="w", pady=(6, 4))
        self.mode = tk.StringVar(value="normal")
        for val, label, hint in (
            ("normal", "Normal", "overlay + a terminal with basic logs"),
            ("verbose", "Verbose", "overlay + a terminal with all data"),
            ("dmg", "Damage log", "overlay + a terminal with only damage lines"),
            ("silent", "Silent (background)", "overlay only — no terminal window"),
        ):
            row = ttk.Frame(wrap); row.pack(fill="x", anchor="w")
            ttk.Radiobutton(row, text=label, value=val, variable=self.mode).pack(side="left")
            ttk.Label(row, text="– " + hint, foreground=self.DIM).pack(side="left", padx=4)

        btns = ttk.Frame(wrap); btns.pack(fill="x", pady=(18, 4))
        self.start_btn = ttk.Button(btns, text="▶  Start Overlay", command=self._start)
        self.start_btn.pack(side="left", ipadx=8, ipady=2)
        self.stop_btn = ttk.Button(btns, text="⏹  Stop", command=self._stop)
        self.stop_btn.pack(side="left", padx=6)
        ttk.Button(btns, text="⚙  Settings", command=self._settings).pack(side="left", padx=2)

        dbg = ttk.Frame(wrap); dbg.pack(fill="x", pady=(4, 0))
        ttk.Button(dbg, text="📋  Copy last log", command=self._copy_log).pack(side="left")
        ttk.Button(dbg, text="🐞  Report an issue", command=self._report).pack(side="left", padx=8)

        cl = ttk.Frame(wrap); cl.pack(fill="x", pady=(10, 0))
        ttk.Button(cl, text="✕  Close launcher, keep overlay running",
                   command=self._close_keep).pack(side="left")

        ttk.Label(wrap, text="Closing this window (✕ titlebar) stops the overlay. "
                  "It also stops when you close God of War.",
                  foreground=self.DIM, font=(self.uifont, 8),
                  wraplength=470, justify="left").pack(anchor="w", side="bottom")

        threading.Thread(target=self._poll_game, daemon=True).start()
        self._refresh()

    def _poll_game(self):
        import winutil
        try:
            import pine
            import pcsx2cfg
        except Exception:
            pine = pcsx2cfg = None
        import procname
        while self._poll:
            # an overlay may also have been started outside this launcher
            self._ext = sys.platform != "win32" and bool(procname.find_overlays())
            if self._child is not None or self._ext:
                # the overlay owns the (single-connection) PINE socket while it
                # runs - don't poke it, just report that it's going
                self._status_text, self._detected = "Overlay running", True
                time.sleep(1.5)
                continue
            text, ok = "Waiting for PCSX2 to start…", False
            hwnd = winutil.find_pcsx2_window()
            title = None
            if pine is not None:
                try:
                    pc = pine.PineClient(timeout=0.6).connect()
                    title = pc.title(); pc.close()
                except Exception:
                    title = None
            if title:
                if hwnd:
                    text, ok = f"{title} detected", True
                else:
                    text = f"{title} found — window not trackable yet"
            elif title == "":
                text = "Waiting for a game to load…"
            elif hwnd:
                if pcsx2cfg and pcsx2cfg.pine_state()[1] is False:
                    text = "PCSX2 found — turn on PINE (Settings > Advanced)"
                else:
                    text = "PCSX2 found — waiting for its PINE server…"
            elif pcsx2cfg:
                # PCSX2 closed: quietly make sure PINE will be on when it starts
                pcsx2cfg.enable_pine()
            self._status_text, self._detected = text, ok
            time.sleep(1.5)

    def _refresh(self):
        self.status.set(self._status_text)
        self.dot.config(foreground="#33aa44" if self._detected else "#e88000")
        if self._child is not None and self._child.poll() is not None:
            self._child = None                      # overlay exited (or crashed)
        running = self._child is not None or self._ext
        if running and str(self.start_btn["state"]) != "disabled":
            self.start_btn.config(state="disabled", text="Overlay running…")
        elif not running and str(self.start_btn["state"]) == "disabled":
            self.start_btn.config(state="normal", text="▶  Start Overlay")
        if self._poll:
            self.root.after(400, self._refresh)

    def _start(self):
        from tkinter import messagebox
        mode = self.mode.get()
        self._child = _spawn(["--run", mode], show_console=(mode != "silent"))
        # stay open: live-tweak via Settings while playing; Start re-arms when
        # the overlay exits
        self.start_btn.config(state="disabled", text="Overlay running…")
        if mode == "silent":
            messagebox.showinfo("Damage overlay",
                                "The overlay is now running in the background.\n\n"
                                "Damage numbers will appear over enemies in-game.\n"
                                "Keep this window open to tweak Settings live,\n"
                                "or close it - the overlay keeps running.")

    def _theme(self, ttk):
        """God of War black/red theme, shared with the settings window."""
        import guifont
        p = guifont.dark_theme(self.root)
        self.BG = p["BG"]; self.RED = p["RED"]
        self.RED_BRIGHT = p["RED_BRIGHT"]; self.DIM = p["DIM"]

    def _stop_overlays(self):
        """Terminate the overlay this launcher started AND any other running
        overlay (e.g. a silent one from an earlier session). Returns how many
        were stopped. No UI - safe to call on window close."""
        import procname
        found = 0
        if self._child is not None and self._child.poll() is None:
            try:
                self._child.terminate()
                found += 1
            except Exception:
                pass
        return found + procname.stop_overlays()

    def _stop(self):
        from tkinter import messagebox
        if not self._stop_overlays():
            messagebox.showinfo("Stop overlay", "No running overlay found.",
                                parent=self.root)

    def _quit_all(self):
        """Closing the launcher window stops every running overlay, then exits."""
        self._poll = False
        try:
            self._stop_overlays()
        except Exception:
            pass
        self.root.destroy()

    def _close_keep(self):
        """Close just the launcher; leave the overlay running in the background
        (it was started in its own session, so it survives)."""
        self._poll = False
        self.root.destroy()

    def _settings(self):
        _spawn(["--setup"], show_console=False)

    def _copy_log(self):
        from tkinter import messagebox
        import applog
        path, text = applog.read_latest()
        if not text:
            messagebox.showinfo("No log yet",
                                "No overlay log found — start the overlay once first.",
                                parent=self.root)
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        messagebox.showinfo("Log copied",
                            f"Copied {os.path.basename(path)} to the clipboard "
                            f"({len(text.splitlines())} lines).\n\n"
                            "Paste it into a GitHub issue:\n"
                            "github.com/kb777only/gow_overlay/issues",
                            parent=self.root)

    def _report(self):
        import webbrowser
        webbrowser.open("https://github.com/kb777only/gow_overlay/issues/new")


def main():
    if _dispatch():
        return
    if getattr(sys, "frozen", False):
        _hide_console()
    import procname
    procname.set_name(procname.LAUNCHER)
    import tkinter as tk
    import respath
    import guifont
    guifont.setup()                 # before tk.Tk(): on Linux this sets FONTCONFIG_FILE
    # className -> WM_CLASS "gow_overlay*", which every window matcher excludes
    root = tk.Tk(className="gow_overlay-launcher")
    guifont.apply(root)             # retarget Tk's named fonts to the GoW family
    respath.set_tk_icon(root)
    LauncherApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
