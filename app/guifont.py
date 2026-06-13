"""guifont.py - make the bundled God of War TTF usable by tkinter WITHOUT
installing it on the user's machine.

  Windows : AddFontResourceExW(path, FR_PRIVATE) - private, process-scoped.
  Linux   : a private fontconfig config (env FONTCONFIG_FILE) that adds the
            font's directory and still <include>s the system config. This MUST
            be set before the first Tk window is created (before Xft inits), so
            call setup() at the very top of main(), then apply() after tk.Tk().

The overlay numbers don't need this (PIL loads the .ttf file directly); this is
only for the tkinter launcher/settings windows. Everything degrades gracefully:
if the font can't be loaded the GUI just keeps its default font.
"""
import os
import shutil
import sys
import tempfile

FAMILY = "GodOfWar"        # the font's internal family name
_state = None              # None=untried, FAMILY=loaded, ""=unavailable


def _font_path():
    try:
        import respath
        return respath.asset_path("GODOFWAR.TTF")
    except Exception:
        return None


def setup():
    """Load the font for this process. Returns the family name or None.
    Idempotent. On Linux must run before the first Tk root is created."""
    global _state
    if _state is not None:
        return _state or None
    path = _font_path()
    if not path:
        _state = ""
        return None
    try:
        if sys.platform == "win32":
            import ctypes
            FR_PRIVATE = 0x10
            ok = ctypes.windll.gdi32.AddFontResourceExW(str(path), FR_PRIVATE, 0)
            _state = FAMILY if ok else ""
        elif sys.platform == "darwin":
            _state = ""        # no macOS build target; numbers still use the font via PIL
        else:
            _state = _load_fontconfig(path)
    except Exception:
        _state = ""
    return _state or None


def _load_fontconfig(path):
    """Point Xft/fontconfig at a private dir holding the font, keeping system
    fonts via <include>. Skipped if the system config is missing, so we never
    risk breaking the GUI's normal fonts."""
    sysconf = "/etc/fonts/fonts.conf"
    if not os.path.exists(sysconf):
        return ""
    d = tempfile.mkdtemp(prefix="gow-font-")
    shutil.copy(path, os.path.join(d, os.path.basename(path)))
    conf = os.path.join(d, "fonts.conf")
    with open(conf, "w") as f:
        f.write('<?xml version="1.0"?>\n'
                '<!DOCTYPE fontconfig SYSTEM "fonts.dtd">\n'
                '<fontconfig>\n'
                f'  <dir>{d}</dir>\n'
                f'  <cachedir>{os.path.join(d, "cache")}</cachedir>\n'
                f'  <include ignore_missing="yes">{sysconf}</include>\n'
                '</fontconfig>\n')
    os.environ["FONTCONFIG_FILE"] = conf
    return FAMILY


def family():
    """The family name to use in tk widgets, or None if unavailable."""
    return setup()


GOW_PALETTE = dict(BG="#0a0a0a", RED="#c01414", RED_BRIGHT="#e22020", DIM="#9a5a5a",
                   BTN="#181818", ACT="#2a0e0e", BORDER="#5a1414")


def dark_theme(root):
    """Apply the God of War black/blood-red theme (ttk 'clam', the one that
    honours custom colours on every element) to a Tk root. Returns the palette."""
    from tkinter import ttk
    p = GOW_PALETTE
    root.configure(bg=p["BG"])
    s = ttk.Style()
    try:
        s.theme_use("clam")
    except Exception:
        pass
    s.configure(".", background=p["BG"], foreground=p["RED"], fieldbackground=p["BG"],
                bordercolor=p["BORDER"], font="TkDefaultFont")
    s.configure("TFrame", background=p["BG"])
    s.configure("TLabel", background=p["BG"], foreground=p["RED"])
    s.configure("TLabelframe", background=p["BG"], bordercolor=p["BORDER"])
    s.configure("TLabelframe.Label", background=p["BG"], foreground=p["RED"])
    s.configure("TSeparator", background=p["BORDER"])
    for w in ("TRadiobutton", "TCheckbutton"):
        s.configure(w, background=p["BG"], foreground=p["RED"], indicatorcolor=p["BTN"])
        s.map(w, background=[("active", p["BG"])], foreground=[("active", p["RED_BRIGHT"])],
              indicatorcolor=[("selected", p["RED_BRIGHT"]), ("pressed", p["RED_BRIGHT"])])
    s.configure("TButton", background=p["BTN"], foreground=p["RED"], bordercolor=p["BORDER"],
                relief="raised", padding=4)
    s.map("TButton", background=[("active", p["ACT"]), ("disabled", "#101010")],
          foreground=[("active", p["RED_BRIGHT"]), ("disabled", "#5a3a3a")])
    s.configure("TNotebook", background=p["BG"], bordercolor=p["BORDER"])
    s.configure("TNotebook.Tab", background=p["BTN"], foreground=p["DIM"], padding=(10, 4))
    s.map("TNotebook.Tab", background=[("selected", p["ACT"])],
          foreground=[("selected", p["RED_BRIGHT"])])
    s.configure("TCombobox", fieldbackground=p["BTN"], background=p["BTN"],
                foreground=p["RED"], arrowcolor=p["RED"], bordercolor=p["BORDER"])
    s.map("TCombobox", fieldbackground=[("readonly", p["BTN"])],
          foreground=[("readonly", p["RED"])], arrowcolor=[("active", p["RED_BRIGHT"])])
    s.configure("Horizontal.TScale", background=p["BG"], troughcolor=p["BTN"])
    # the Combobox dropdown list is a classic Tk listbox - theme it via options
    root.option_add("*TCombobox*Listbox.background", p["BTN"])
    root.option_add("*TCombobox*Listbox.foreground", p["RED"])
    root.option_add("*TCombobox*Listbox.selectBackground", p["ACT"])
    root.option_add("*TCombobox*Listbox.selectForeground", p["RED_BRIGHT"])
    return p


def apply(root):
    """Retarget Tk's standard named fonts to the GoW family (keeps their sizes),
    so every ttk/tk widget that uses them inherits it. Returns the family or None."""
    fam = setup()
    if not fam:
        return None
    try:
        import tkinter.font as tkfont
        for nm in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont",
                   "TkCaptionFont", "TkSmallCaptionFont", "TkIconFont",
                   "TkTooltipFont"):
            try:
                tkfont.nametofont(nm).configure(family=fam)
            except Exception:
                pass
        root.option_add("*Font", "TkDefaultFont")
        from tkinter import ttk
        ttk.Style().configure(".", font="TkDefaultFont")
    except Exception:
        pass
    return fam
