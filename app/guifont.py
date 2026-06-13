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
