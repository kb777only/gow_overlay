"""
winutil.py - window & keyboard-input helpers for the PCSX2 display window.

Thin platform dispatcher; the real implementations live in:
  winutil_win32 - Win32 (EnumWindows, SendInput scancodes)
  winutil_x11   - Linux/X11, also under XWayland (EWMH, XTEST)

Both expose the same API: find_pcsx2_window, client_rect_on_screen,
focus_window, key_down, key_up, tap, tap_vk, hold, PAD, VK.
"""
import sys

if sys.platform == "win32":
    from winutil_win32 import *          # noqa: F401,F403
else:
    from winutil_x11 import *            # noqa: F401,F403
