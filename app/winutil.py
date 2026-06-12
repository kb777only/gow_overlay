"""
winutil.py - window & keyboard-input helpers for the PCSX2 display window.

Thin platform dispatcher; the real implementations live in:
  winutil_win32   - Win32 (EnumWindows, SendInput scancodes)
  winutil_x11     - Linux/X11, also under XWayland (EWMH, XTEST)
  winutil_wayland - Linux/Wayland sessions where PCSX2 runs as a NATIVE Wayland
                    client (no X11 window): tracks geometry via the compositor
                    (KWin scripting / Hyprland / Sway IPC)

All expose the same API: find_pcsx2_window, client_rect_on_screen,
focus_window, key_down, key_up, tap, tap_vk, hold, PAD, VK.

On Linux the lookup is hybrid: the X11/XWayland window is preferred when it
exists (cheap, real-time geometry); otherwise the Wayland compositor adapters
take over, returning a winutil_wayland.WaylandWindow handle that the other
functions dispatch on. Keyboard synthesis stays XTEST-based and only reaches
X11/XWayland windows; focus_window() returns False for native Wayland windows
so callers can tell input-driving is unavailable.
"""
import sys

if sys.platform == "win32":
    from winutil_win32 import *          # noqa: F401,F403
else:
    import winutil_wayland as _wl
    try:
        import winutil_x11 as _x11
        from winutil_x11 import (PAD, VK, key_down, key_up,        # noqa: F401
                                 tap, tap_vk, hold)
    except Exception:                    # no libX11 / no X display at all
        _x11 = None
        PAD, VK = {}, {}

        def key_down(vkname):            # noqa: D103
            raise RuntimeError("keyboard synthesis needs X11/XWayland")
        key_up = tap = tap_vk = hold = key_down

    def find_pcsx2_window():
        if _x11 is not None:
            try:
                w = _x11.find_pcsx2_window()
                if w:
                    return w
            except Exception:
                pass
        return _wl.find_pcsx2_window()

    def client_rect_on_screen(hwnd):
        if isinstance(hwnd, _wl.WaylandWindow):
            return _wl.client_rect_on_screen(hwnd)
        return _x11.client_rect_on_screen(hwnd)

    def focus_window(hwnd):
        if isinstance(hwnd, _wl.WaylandWindow):
            return _wl.focus_window(hwnd)
        return _x11.focus_window(hwnd)
