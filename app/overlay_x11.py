"""overlay_x11.py - Linux/X11 presentation backend for overlay.py.

A 32-bit ARGB override-redirect window: unmanaged (no border, ignores the WM),
kept above other windows by re-raising, and click-through via an empty XShape
input region. Pixels are pushed with XPutImage from a numpy (h, w, 4) BGRA
buffer - on a little-endian X server that is exactly premultiplied ARGB32, the
same convention compositors expect, so per-pixel alpha works as on Windows.

Requirements: a running compositor (KDE/GNOME/most modern desktops always
composite) and an X11 connection - a native X session or XWayland both work.
Must be created and driven from a single thread (overlay._run).
"""
import ctypes
import ctypes.util
import time

import numpy as np


def _load(name, fallback):
    path = ctypes.util.find_library(name)
    return ctypes.CDLL(path or fallback, use_errno=True)


_x11 = _load("X11", "libX11.so.6")
_x11.XInitThreads()                 # before any other Xlib call in this process
_xext = _load("Xext", "libXext.so.6")

Display_p = ctypes.c_void_p
Window = ctypes.c_ulong
Visual_p = ctypes.c_void_p
Colormap = ctypes.c_ulong
GC = ctypes.c_void_p

TrueColor = 4
InputOutput = 1
AllocNone = 0
ZPixmap = 2
LSBFirst = 0
CWBackPixel = 1 << 1
CWBorderPixel = 1 << 3
CWOverrideRedirect = 1 << 9
CWColormap = 1 << 13
ShapeInput = 2
ShapeSet = 0


class XSetWindowAttributes(ctypes.Structure):
    _fields_ = [("background_pixmap", ctypes.c_ulong), ("background_pixel", ctypes.c_ulong),
                ("border_pixmap", ctypes.c_ulong), ("border_pixel", ctypes.c_ulong),
                ("bit_gravity", ctypes.c_int), ("win_gravity", ctypes.c_int),
                ("backing_store", ctypes.c_int), ("backing_planes", ctypes.c_ulong),
                ("backing_pixel", ctypes.c_ulong), ("save_under", ctypes.c_int),
                ("event_mask", ctypes.c_long), ("do_not_propagate_mask", ctypes.c_long),
                ("override_redirect", ctypes.c_int), ("colormap", Colormap),
                ("cursor", ctypes.c_ulong)]


class XVisualInfo(ctypes.Structure):
    _fields_ = [("visual", Visual_p), ("visualid", ctypes.c_ulong),
                ("screen", ctypes.c_int), ("depth", ctypes.c_int),
                ("c_class", ctypes.c_int),
                ("red_mask", ctypes.c_ulong), ("green_mask", ctypes.c_ulong),
                ("blue_mask", ctypes.c_ulong),
                ("colormap_size", ctypes.c_int), ("bits_per_rgb", ctypes.c_int)]


class XImage(ctypes.Structure):
    _fields_ = [("width", ctypes.c_int), ("height", ctypes.c_int),
                ("xoffset", ctypes.c_int), ("format", ctypes.c_int),
                ("data", ctypes.c_void_p), ("byte_order", ctypes.c_int),
                ("bitmap_unit", ctypes.c_int), ("bitmap_bit_order", ctypes.c_int),
                ("bitmap_pad", ctypes.c_int), ("depth", ctypes.c_int),
                ("bytes_per_line", ctypes.c_int), ("bits_per_pixel", ctypes.c_int),
                ("red_mask", ctypes.c_ulong), ("green_mask", ctypes.c_ulong),
                ("blue_mask", ctypes.c_ulong), ("obdata", ctypes.c_void_p),
                ("f", ctypes.c_void_p * 6)]


_x11.XOpenDisplay.restype = Display_p
_x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
_x11.XCloseDisplay.argtypes = [Display_p]
_x11.XDefaultScreen.restype = ctypes.c_int
_x11.XDefaultScreen.argtypes = [Display_p]
_x11.XRootWindow.restype = Window
_x11.XRootWindow.argtypes = [Display_p, ctypes.c_int]
_x11.XMatchVisualInfo.restype = ctypes.c_int
_x11.XMatchVisualInfo.argtypes = [Display_p, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                  ctypes.POINTER(XVisualInfo)]
_x11.XCreateColormap.restype = Colormap
_x11.XCreateColormap.argtypes = [Display_p, Window, Visual_p, ctypes.c_int]
_x11.XCreateWindow.restype = Window
_x11.XCreateWindow.argtypes = [Display_p, Window, ctypes.c_int, ctypes.c_int,
                               ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_int,
                               ctypes.c_uint, Visual_p, ctypes.c_ulong,
                               ctypes.POINTER(XSetWindowAttributes)]
_x11.XStoreName.argtypes = [Display_p, Window, ctypes.c_char_p]
_x11.XCreateGC.restype = GC
_x11.XCreateGC.argtypes = [Display_p, Window, ctypes.c_ulong, ctypes.c_void_p]
_x11.XCreateImage.restype = ctypes.POINTER(XImage)
_x11.XCreateImage.argtypes = [Display_p, Visual_p, ctypes.c_uint, ctypes.c_int, ctypes.c_int,
                              ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint,
                              ctypes.c_int, ctypes.c_int]
_x11.XPutImage.argtypes = [Display_p, Window, GC, ctypes.POINTER(XImage),
                           ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                           ctypes.c_uint, ctypes.c_uint]
_x11.XMapRaised.argtypes = [Display_p, Window]
_x11.XRaiseWindow.argtypes = [Display_p, Window]
_x11.XMoveResizeWindow.argtypes = [Display_p, Window, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_uint, ctypes.c_uint]
_x11.XDestroyWindow.argtypes = [Display_p, Window]
_x11.XFlush.argtypes = [Display_p]
_x11.XPending.restype = ctypes.c_int
_x11.XPending.argtypes = [Display_p]
_x11.XNextEvent.argtypes = [Display_p, ctypes.c_void_p]
_x11.XFree.argtypes = [ctypes.c_void_p]
_xext.XShapeCombineRectangles.argtypes = [Display_p, Window, ctypes.c_int,
                                          ctypes.c_int, ctypes.c_int, ctypes.c_void_p,
                                          ctypes.c_int, ctypes.c_int, ctypes.c_int]

# ignore X errors (BadWindow etc.) instead of letting Xlib abort the process
_XERRORHANDLER = ctypes.CFUNCTYPE(ctypes.c_int, Display_p, ctypes.c_void_p)
_err_cb = _XERRORHANDLER(lambda d, e: 0)
_x11.XSetErrorHandler(_err_cb)

RAISE_PERIOD = 1.0      # s between XRaiseWindow keep-on-top nudges


class Backend:
    def __init__(self, x, y, w, h):
        self._dpy = _x11.XOpenDisplay(None)
        if not self._dpy:
            raise RuntimeError("cannot open X display - an X11 session or XWayland is "
                               "required (is $DISPLAY set?)")
        scr = _x11.XDefaultScreen(self._dpy)
        root = _x11.XRootWindow(self._dpy, scr)
        vinfo = XVisualInfo()
        if not _x11.XMatchVisualInfo(self._dpy, scr, 32, TrueColor, ctypes.byref(vinfo)):
            raise RuntimeError("no 32-bit ARGB visual - a compositing window manager "
                               "is required for the transparent overlay")
        self._visual = vinfo.visual
        attrs = XSetWindowAttributes()
        attrs.background_pixel = 0
        attrs.border_pixel = 0          # must be set explicitly for a depth-32 window
        attrs.override_redirect = 1     # unmanaged: borderless, skips taskbar, stays put
        attrs.colormap = _x11.XCreateColormap(self._dpy, root, vinfo.visual, AllocNone)
        mask = CWBackPixel | CWBorderPixel | CWOverrideRedirect | CWColormap
        self.hwnd = _x11.XCreateWindow(self._dpy, root, x, y, max(1, w), max(1, h), 0,
                                       32, InputOutput, vinfo.visual, mask, ctypes.byref(attrs))
        if not self.hwnd:
            raise RuntimeError("XCreateWindow failed")
        _x11.XStoreName(self._dpy, self.hwnd, b"overlay")
        # empty input region -> clicks fall through to the game underneath
        _xext.XShapeCombineRectangles(self._dpy, self.hwnd, ShapeInput, 0, 0, None, 0,
                                      ShapeSet, 0)
        self._gc = _x11.XCreateGC(self._dpy, self.hwnd, 0, None)
        self._img = None
        self._buf = None
        self._w = self._h = 0
        self._ev = (ctypes.c_byte * 192)()      # sizeof(XEvent)
        self._last_raise = 0.0
        self.surface(w, h)
        _x11.XMapRaised(self._dpy, self.hwnd)
        _x11.XFlush(self._dpy)

    def surface(self, w, h) -> np.ndarray:
        """(Re)allocate the BGRA frame buffer + its XImage wrapper."""
        if w == self._w and h == self._h and self._buf is not None:
            return self._buf
        if self._img:
            # the pixel data belongs to numpy; detach it before freeing the struct
            self._img.contents.data = None
            _x11.XFree(self._img)
        self._w, self._h = w, h
        self._buf = np.zeros((h, w, 4), np.uint8)
        self._img = _x11.XCreateImage(self._dpy, self._visual, 32, ZPixmap, 0,
                                      self._buf.ctypes.data, w, h, 32, w * 4)
        if not self._img:
            raise RuntimeError("XCreateImage failed")
        self._img.contents.byte_order = LSBFirst    # BGRA bytes == ARGB32 little-endian
        return self._buf

    def move(self, x, y, w, h):
        _x11.XMoveResizeWindow(self._dpy, self.hwnd, x, y, max(1, w), max(1, h))
        _x11.XRaiseWindow(self._dpy, self.hwnd)
        _x11.XFlush(self._dpy)

    def present(self, x, y, w, h):
        _x11.XPutImage(self._dpy, self.hwnd, self._gc, self._img, 0, 0, 0, 0, w, h)
        now = time.time()
        if now - self._last_raise > RAISE_PERIOD:   # stay above the game window
            self._last_raise = now
            _x11.XRaiseWindow(self._dpy, self.hwnd)
        _x11.XFlush(self._dpy)

    def pump(self):
        while _x11.XPending(self._dpy):
            _x11.XNextEvent(self._dpy, ctypes.byref(self._ev))

    def close(self):
        if self._dpy:
            if self._img:
                self._img.contents.data = None
                _x11.XFree(self._img)
                self._img = None
            if self.hwnd:
                _x11.XDestroyWindow(self._dpy, self.hwnd)
                self.hwnd = None
            _x11.XCloseDisplay(self._dpy)
            self._dpy = None
