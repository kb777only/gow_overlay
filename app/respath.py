"""respath.py - locate bundled asset files (icons) in every run mode:
PyInstaller onefile (sys._MEIPASS), flatpak (copied beside the modules), and
the source tree (../assets). Also the one place that applies the app icon to
tkinter windows."""
import os
import sys


def asset_path(name):
    here = os.path.dirname(os.path.abspath(__file__))
    cands = []
    mp = getattr(sys, "_MEIPASS", None)
    if mp:
        cands.append(os.path.join(mp, name))
    cands += [os.path.join(here, name),
              os.path.join(os.path.dirname(here), "assets", name)]
    for p in cands:
        if os.path.exists(p):
            return p
    return None


def set_tk_icon(root):
    """Best-effort: give a tk window (and all its future toplevels/dialogs)
    the overlay icon."""
    try:
        if sys.platform == "win32":
            ico = asset_path("gow_overlay.ico")
            if ico:
                root.iconbitmap(default=ico)
        png = asset_path("gow_overlay.png")
        if png:
            import tkinter as tk
            img = tk.PhotoImage(file=png)
            root.iconphoto(True, img)
            root._gow_icon = img        # keep a reference or tk drops it
    except Exception:
        pass
