"""
winutil_win32.py - Win32 helpers (ctypes only, no third-party deps):
  * locate the PCSX2 display window and its client rect in screen coords
  * focus it and synthesize keyboard input (scancode SendInput) so we can
    drive God of War (menus + combat) programmatically
Import via `winutil`, which dispatches per platform (winutil_x11 on Linux).
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from typing import Optional, Tuple

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# --- window discovery --------------------------------------------------------
EnumWindows = user32.EnumWindows
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
GetWindowTextW = user32.GetWindowTextW
GetWindowTextLengthW = user32.GetWindowTextLengthW
IsWindowVisible = user32.IsWindowVisible
GetClassNameW = user32.GetClassNameW

GetWindowThreadProcessId = user32.GetWindowThreadProcessId
GetClientRect = user32.GetClientRect
ClientToScreen = user32.ClientToScreen
GetWindowRect = user32.GetWindowRect

SetForegroundWindow = user32.SetForegroundWindow
ShowWindow = user32.ShowWindow
BringWindowToTop = user32.BringWindowToTop
AttachThreadInput = user32.AttachThreadInput
GetForegroundWindow = user32.GetForegroundWindow

SW_RESTORE = 9


def _get_title(hwnd) -> str:
    n = GetWindowTextLengthW(hwnd)
    if n == 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def find_pcsx2_window() -> Optional[int]:
    """Return the HWND of the PCSX2 game/display window, or None.

    Prefers a window whose title contains the running game name; falls back to
    any visible 'PCSX2'/game window. PCSX2 renders into the main window's
    client area (no separate render window unless configured)."""
    found = []

    def cb(hwnd, _):
        if not IsWindowVisible(hwnd):
            return True
        title = _get_title(hwnd)
        if not title:
            return True
        low = title.lower()
        # PCSX2 main window title is the game name while running, e.g. "God of War".
        if ("god of war" in low) or ("pcsx2" in low):
            r = wintypes.RECT()
            GetClientRect(hwnd, ctypes.byref(r))
            found.append((hwnd, title, r.right - r.left, r.bottom - r.top))
        return True

    EnumWindows(EnumWindowsProc(cb), 0)
    if not found:
        return None
    # pick the one with the largest client area (the display), not a tiny dialog
    found.sort(key=lambda t: t[2] * t[3], reverse=True)
    return found[0][0]


def client_rect_on_screen(hwnd) -> Tuple[int, int, int, int]:
    """(left, top, width, height) of the window's *client* area in screen px."""
    r = wintypes.RECT()
    GetClientRect(hwnd, ctypes.byref(r))
    pt = wintypes.POINT(0, 0)
    ClientToScreen(hwnd, ctypes.byref(pt))
    return (pt.x, pt.y, r.right - r.left, r.bottom - r.top)


def focus_window(hwnd) -> bool:
    """Best-effort bring `hwnd` to the foreground (handles the usual Win32
    foreground-lock by attaching to the current foreground thread)."""
    ShowWindow(hwnd, SW_RESTORE)
    BringWindowToTop(hwnd)
    if SetForegroundWindow(hwnd):
        return True
    fg = GetForegroundWindow()
    cur_tid = kernel32.GetCurrentThreadId()
    fg_tid = GetWindowThreadProcessId(fg, None)
    tgt_tid = GetWindowThreadProcessId(hwnd, None)
    AttachThreadInput(cur_tid, fg_tid, True)
    AttachThreadInput(cur_tid, tgt_tid, True)
    try:
        BringWindowToTop(hwnd)
        SetForegroundWindow(hwnd)
    finally:
        AttachThreadInput(cur_tid, fg_tid, False)
        AttachThreadInput(cur_tid, tgt_tid, False)
    return GetForegroundWindow() == hwnd


# --- keyboard input via SendInput (scancodes) --------------------------------
PUL = ctypes.POINTER(ctypes.c_ulong)


ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class _INPUTunion(ctypes.Union):
    # MOUSEINPUT is the largest member; including it makes sizeof(INPUT) match
    # the real Win32 struct (40 bytes on x64) so SendInput's cbSize check passes.
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTunion)]


INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_EXTENDEDKEY = 0x0001

MAPVK_VK_TO_VSC = 0
MapVirtualKeyW = user32.MapVirtualKeyW
SendInput = user32.SendInput

# Virtual-key codes for the keys we bound in PCSX2.ini -> Pad1
VK = {
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "return": 0x0D, "backspace": 0x08, "space": 0x20,
    "J": 0x4A, "K": 0x4B, "I": 0x49, "L": 0x4C,
    "W": 0x57, "A": 0x41, "S": 0x53, "D": 0x44,
    "Q": 0x51, "E": 0x45, "Z": 0x5A, "C": 0x43, "F": 0x46, "V": 0x56,
    "T": 0x54, "G": 0x47, "H": 0x48, "Y": 0x59,
    "f1": 0x70, "f2": 0x71, "f3": 0x72,   # PCSX2 save/load-state hotkeys
    "f4": 0x73,                            # ToggleFrameLimit
    "tab": 0x09,                           # ToggleTurbo (fast-forward)
    "esc": 0x1B,
}
# arrows / nav keys are "extended" scancodes
_EXTENDED = {"up", "down", "left", "right"}

# friendly pad-name -> keyboard key (mirrors the PCSX2.ini Pad1 bindings)
PAD = {
    "up": "up", "down": "down", "left": "left", "right": "right",
    "cross": "J", "square": "K", "triangle": "I", "circle": "L",
    "start": "return", "select": "backspace",
    "l1": "Q", "r1": "E", "l2": "Z", "r2": "C", "l3": "F", "r3": "V",
    "lup": "W", "ldown": "S", "lleft": "A", "lright": "D",
    "rup": "T", "rdown": "G", "rleft": "H", "rright": "Y",
}


def _send_scan(vkname: str, keyup: bool):
    vk = VK[vkname]
    scan = MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
    flags = KEYEVENTF_SCANCODE
    if vkname in _EXTENDED:
        flags |= KEYEVENTF_EXTENDEDKEY
    if keyup:
        flags |= KEYEVENTF_KEYUP
    inp = INPUT(type=INPUT_KEYBOARD,
                u=_INPUTunion(ki=KEYBDINPUT(0, scan, flags, 0, 0)))
    SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def key_down(vkname: str):
    _send_scan(vkname, False)


def key_up(vkname: str):
    _send_scan(vkname, True)


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
    print("hwnd:", hwnd)
    if hwnd:
        print("title:", _get_title(hwnd))
        print("client rect (L,T,W,H):", client_rect_on_screen(hwnd))
        print("focus:", focus_window(hwnd))
