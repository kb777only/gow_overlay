"""
winutil_x11.py - Linux/X11 helpers (ctypes only, no third-party deps) with the
same API as winutil_win32:
  * locate the PCSX2 display window and its client rect in screen coords
  * focus it and synthesize keyboard input (XTEST) so we can drive God of War
    (menus + combat) programmatically
Import via `winutil`, which dispatches per platform.

Works on X11 sessions and on Wayland through XWayland. On Wayland, PCSX2 must
itself run as an X11 client (QT_QPA_PLATFORM=xcb) so its window is visible here.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import time
from typing import List, Optional, Tuple


def _load(name: str, fallback: str) -> ctypes.CDLL:
    path = ctypes.util.find_library(name)
    return ctypes.CDLL(path or fallback, use_errno=True)


_x11 = _load("X11", "libX11.so.6")
_x11.XInitThreads()        # MUST precede any other Xlib call: we use several threads

Display_p = ctypes.c_void_p
Window = ctypes.c_ulong
Atom = ctypes.c_ulong
KeySym = ctypes.c_ulong

# --- prototypes ---------------------------------------------------------------
_x11.XOpenDisplay.restype = Display_p
_x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
_x11.XDefaultRootWindow.restype = Window
_x11.XDefaultRootWindow.argtypes = [Display_p]
_x11.XInternAtom.restype = Atom
_x11.XInternAtom.argtypes = [Display_p, ctypes.c_char_p, ctypes.c_int]
_x11.XGetWindowProperty.restype = ctypes.c_int
_x11.XGetWindowProperty.argtypes = [Display_p, Window, Atom, ctypes.c_long, ctypes.c_long,
                                    ctypes.c_int, Atom, ctypes.POINTER(Atom),
                                    ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_ulong),
                                    ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_void_p)]
_x11.XFree.argtypes = [ctypes.c_void_p]
_x11.XFetchName.restype = ctypes.c_int
_x11.XFetchName.argtypes = [Display_p, Window, ctypes.POINTER(ctypes.c_char_p)]
_x11.XGetGeometry.restype = ctypes.c_int
_x11.XGetGeometry.argtypes = [Display_p, Window, ctypes.POINTER(Window),
                              ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
                              ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint),
                              ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint)]
_x11.XTranslateCoordinates.restype = ctypes.c_int
_x11.XTranslateCoordinates.argtypes = [Display_p, Window, Window, ctypes.c_int, ctypes.c_int,
                                       ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
                                       ctypes.POINTER(Window)]
_x11.XQueryTree.restype = ctypes.c_int
_x11.XQueryTree.argtypes = [Display_p, Window, ctypes.POINTER(Window), ctypes.POINTER(Window),
                            ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint)]
_x11.XRaiseWindow.argtypes = [Display_p, Window]
_x11.XFlush.argtypes = [Display_p]
_x11.XSendEvent.restype = ctypes.c_int
_x11.XStringToKeysym.restype = KeySym
_x11.XStringToKeysym.argtypes = [ctypes.c_char_p]
_x11.XKeysymToKeycode.restype = ctypes.c_ubyte
_x11.XKeysymToKeycode.argtypes = [Display_p, KeySym]


class XWindowAttributes(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int), ("y", ctypes.c_int),
                ("width", ctypes.c_int), ("height", ctypes.c_int),
                ("border_width", ctypes.c_int), ("depth", ctypes.c_int),
                ("visual", ctypes.c_void_p), ("root", Window),
                ("c_class", ctypes.c_int), ("bit_gravity", ctypes.c_int),
                ("win_gravity", ctypes.c_int), ("backing_store", ctypes.c_int),
                ("backing_planes", ctypes.c_ulong), ("backing_pixel", ctypes.c_ulong),
                ("save_under", ctypes.c_int), ("colormap", ctypes.c_ulong),
                ("map_installed", ctypes.c_int), ("map_state", ctypes.c_int),
                ("all_event_masks", ctypes.c_long), ("your_event_mask", ctypes.c_long),
                ("do_not_propagate_mask", ctypes.c_long), ("override_redirect", ctypes.c_int),
                ("screen", ctypes.c_void_p)]


_x11.XGetWindowAttributes.restype = ctypes.c_int
_x11.XGetWindowAttributes.argtypes = [Display_p, Window, ctypes.POINTER(XWindowAttributes)]


class XClientMessageEvent(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong),
                ("send_event", ctypes.c_int), ("display", Display_p),
                ("window", Window), ("message_type", Atom),
                ("format", ctypes.c_int), ("data", ctypes.c_long * 5)]


class XEvent(ctypes.Union):
    _fields_ = [("type", ctypes.c_int), ("xclient", XClientMessageEvent),
                ("pad", ctypes.c_long * 24)]


_x11.XSendEvent.argtypes = [Display_p, Window, ctypes.c_int, ctypes.c_long, ctypes.POINTER(XEvent)]

# X errors (e.g. BadWindow for a window that closed between enumeration and
# query) abort the process by default; ignore them instead.
_XERRORHANDLER = ctypes.CFUNCTYPE(ctypes.c_int, Display_p, ctypes.c_void_p)
_err_cb = _XERRORHANDLER(lambda d, e: 0)        # keep a ref so it isn't GC'd
_x11.XSetErrorHandler(_err_cb)

ClientMessage = 33
IsViewable = 2
SubstructureNotifyMask = 1 << 19
SubstructureRedirectMask = 1 << 20

_display_handle: Optional[int] = None
_xtst: Optional[ctypes.CDLL] = None


def _display():
    global _display_handle
    if _display_handle is None:
        _display_handle = _x11.XOpenDisplay(None)
        if not _display_handle:
            raise RuntimeError("cannot open X display - an X11 session or XWayland is "
                               "required (is $DISPLAY set?)")
    return _display_handle


# --- window discovery ----------------------------------------------------------
def _get_prop(dpy, win, prop: int, req_type: int = 0):
    """Read a window property. Returns bytes for format-8 props, a list of ints
    for format-16/32 props, or None."""
    atype = Atom(); afmt = ctypes.c_int()
    nitems = ctypes.c_ulong(); after = ctypes.c_ulong()
    data = ctypes.c_void_p()
    r = _x11.XGetWindowProperty(dpy, win, prop, 0, 0x7FFFFFF, False, req_type,
                                ctypes.byref(atype), ctypes.byref(afmt),
                                ctypes.byref(nitems), ctypes.byref(after),
                                ctypes.byref(data))
    if r != 0 or not data.value:
        return None
    try:
        n = nitems.value
        if afmt.value == 8:
            return ctypes.string_at(data, n)
        if afmt.value == 16:
            return list(ctypes.cast(data, ctypes.POINTER(ctypes.c_ushort))[:n])
        if afmt.value == 32:
            # format-32 properties come back as C longs (64-bit here)
            return list(ctypes.cast(data, ctypes.POINTER(ctypes.c_ulong))[:n])
        return None
    finally:
        _x11.XFree(data)


def _get_title(hwnd) -> str:
    dpy = _display()
    net = _x11.XInternAtom(dpy, b"_NET_WM_NAME", True)
    utf8 = _x11.XInternAtom(dpy, b"UTF8_STRING", True)
    if net and utf8:
        raw = _get_prop(dpy, hwnd, net, utf8)
        if raw:
            return raw.decode("utf-8", "replace")
    name = ctypes.c_char_p()
    if _x11.XFetchName(dpy, hwnd, ctypes.byref(name)) and name.value:
        try:
            return name.value.decode("latin-1", "replace")
        finally:
            _x11.XFree(name)
    return ""


def _children(dpy, win) -> List[int]:
    root_r = Window(); parent_r = Window()
    kids = ctypes.c_void_p(); n = ctypes.c_uint()
    if not _x11.XQueryTree(dpy, win, ctypes.byref(root_r), ctypes.byref(parent_r),
                           ctypes.byref(kids), ctypes.byref(n)):
        return []
    try:
        if not kids.value:
            return []
        arr = ctypes.cast(kids, ctypes.POINTER(Window))
        return [int(arr[i]) for i in range(n.value)]
    finally:
        if kids.value:
            _x11.XFree(kids)


def _is_viewable(dpy, win) -> bool:
    wa = XWindowAttributes()
    return bool(_x11.XGetWindowAttributes(dpy, win, ctypes.byref(wa))) and wa.map_state == IsViewable


def _get_class(hwnd) -> str:
    """The window's WM_CLASS ("instance class"), lowercased, or ""."""
    dpy = _display()
    wm_class = _x11.XInternAtom(dpy, b"WM_CLASS", True)
    if not wm_class:
        return ""
    raw = _get_prop(dpy, hwnd, wm_class)
    if isinstance(raw, bytes):
        return raw.replace(b"\0", b" ").decode("latin-1", "replace").strip().lower()
    return ""


def find_pcsx2_window() -> Optional[int]:
    """Return the X window id of the PCSX2 game/display window, or None.

    Windows whose WM_CLASS belongs to PCSX2 win outright; title matches
    ("God of War"/"PCSX2") are only a fallback, so a lookalike title - the
    overlay's own launcher, a browser tab - can never shadow the game. Our own
    windows (WM_CLASS gow_overlay*) are excluded entirely."""
    dpy = _display()
    root = _x11.XDefaultRootWindow(dpy)
    wins: List[int] = []
    net_list = _x11.XInternAtom(dpy, b"_NET_CLIENT_LIST", True)
    if net_list:
        ids = _get_prop(dpy, root, net_list)
        if isinstance(ids, list):
            wins = ids
    if not wins:
        # no EWMH window list (bare WM): walk the tree two levels (WM frames wrap clients)
        for c in _children(dpy, root):
            wins.append(c)
            wins.extend(_children(dpy, c))

    found = []
    for w in wins:
        if not _is_viewable(dpy, w):
            continue
        cls = _get_class(w)
        if "gow_overlay" in cls or "gow-damage-overlay" in cls:
            continue                       # never our own launcher/settings/overlay
        low = _get_title(w).lower()
        if "damage overlay" in low:
            continue                       # ...nor an older overlay's windows
        class_hit = "pcsx2" in cls
        if not class_hit:
            if not (("god of war" in low) or ("pcsx2" in low)):
                continue
        _, _, cw, ch = client_rect_on_screen(w)
        found.append((class_hit, cw * ch, int(w)))
    if not found:
        return None
    # PCSX2's own windows first; among those the largest client area (the
    # display, not a tiny dialog)
    found.sort(reverse=True)
    return found[0][2]


def client_rect_on_screen(hwnd) -> Tuple[int, int, int, int]:
    """(left, top, width, height) of the window's drawable area in screen px.
    X11 toplevel client windows ARE the client area (the WM frame is a separate
    parent window), so this mirrors the Win32 GetClientRect+ClientToScreen pair."""
    dpy = _display()
    root = _x11.XDefaultRootWindow(dpy)
    rr = Window(); x0 = ctypes.c_int(); y0 = ctypes.c_int()
    w = ctypes.c_uint(); h = ctypes.c_uint(); bw = ctypes.c_uint(); depth = ctypes.c_uint()
    _x11.XGetGeometry(dpy, hwnd, ctypes.byref(rr), ctypes.byref(x0), ctypes.byref(y0),
                      ctypes.byref(w), ctypes.byref(h), ctypes.byref(bw), ctypes.byref(depth))
    sx = ctypes.c_int(); sy = ctypes.c_int(); child = Window()
    _x11.XTranslateCoordinates(dpy, hwnd, root, 0, 0,
                               ctypes.byref(sx), ctypes.byref(sy), ctypes.byref(child))
    return (sx.value, sy.value, int(w.value), int(h.value))


def focus_window(hwnd) -> bool:
    """Best-effort activate `hwnd` via the EWMH _NET_ACTIVE_WINDOW protocol."""
    dpy = _display()
    root = _x11.XDefaultRootWindow(dpy)
    active = _x11.XInternAtom(dpy, b"_NET_ACTIVE_WINDOW", False)
    ev = XEvent()
    ev.xclient.type = ClientMessage
    ev.xclient.window = hwnd
    ev.xclient.message_type = active
    ev.xclient.format = 32
    ev.xclient.data[0] = 1          # source indication: normal application
    ev.xclient.data[1] = 0          # timestamp (CurrentTime)
    _x11.XSendEvent(dpy, root, False, SubstructureRedirectMask | SubstructureNotifyMask,
                    ctypes.byref(ev))
    _x11.XRaiseWindow(dpy, hwnd)
    _x11.XFlush(dpy)
    return True


# --- keyboard input via XTEST (keysyms) -----------------------------------------
# key name -> X keysym string (same key names as the Win32 VK table)
VK = {
    "up": "Up", "down": "Down", "left": "Left", "right": "Right",
    "return": "Return", "backspace": "BackSpace", "space": "space",
    "J": "j", "K": "k", "I": "i", "L": "l",
    "W": "w", "A": "a", "S": "s", "D": "d",
    "Q": "q", "E": "e", "Z": "z", "C": "c", "F": "f", "V": "v",
    "T": "t", "G": "g", "H": "h", "Y": "y",
    "f1": "F1", "f2": "F2", "f3": "F3",   # PCSX2 save/load-state hotkeys
    "f4": "F4",                            # ToggleFrameLimit
    "tab": "Tab",                          # ToggleTurbo (fast-forward)
    "esc": "Escape",
}

# friendly pad-name -> keyboard key (mirrors the PCSX2.ini Pad1 bindings)
PAD = {
    "up": "up", "down": "down", "left": "left", "right": "right",
    "cross": "J", "square": "K", "triangle": "I", "circle": "L",
    "start": "return", "select": "backspace",
    "l1": "Q", "r1": "E", "l2": "Z", "r2": "C", "l3": "F", "r3": "V",
    "lup": "W", "ldown": "S", "lleft": "A", "lright": "D",
    "rup": "T", "rdown": "G", "rleft": "H", "rright": "Y",
}


def _xtest() -> ctypes.CDLL:
    global _xtst
    if _xtst is None:
        try:
            _xtst = _load("Xtst", "libXtst.so.6")
        except OSError as e:
            raise RuntimeError("libXtst is required for keyboard synthesis on Linux "
                               "(install your distro's libXtst package)") from e
        _xtst.XTestFakeKeyEvent.argtypes = [Display_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
    return _xtst


def _send_key(vkname: str, keyup: bool):
    dpy = _display()
    sym = _x11.XStringToKeysym(VK[vkname].encode())
    code = _x11.XKeysymToKeycode(dpy, sym)
    if not code:
        return
    _xtest().XTestFakeKeyEvent(dpy, code, not keyup, 0)
    _x11.XFlush(dpy)


def key_down(vkname: str):
    _send_key(vkname, False)


def key_up(vkname: str):
    _send_key(vkname, True)


def tap(padname: str, hold: float = 0.07):
    """Press and release a PS2 pad button by friendly name (e.g. 'down', 'cross')."""
    vkname = PAD[padname.lower()]
    key_down(vkname)
    time.sleep(hold)
    key_up(vkname)


def tap_vk(vkname: str, hold: float = 0.06):
    """Tap a raw key by VK name (e.g. 'f1', 'f3')."""
    key_down(vkname)
    time.sleep(hold)
    key_up(vkname)


def hold(padname: str, dur: float):
    vkname = PAD[padname.lower()]
    key_down(vkname)
    time.sleep(dur)
    key_up(vkname)


if __name__ == "__main__":
    hwnd = find_pcsx2_window()
    print("window:", hwnd)
    if hwnd:
        print("title:", _get_title(hwnd))
        print("client rect (L,T,W,H):", client_rect_on_screen(hwnd))
        print("focus:", focus_window(hwnd))
