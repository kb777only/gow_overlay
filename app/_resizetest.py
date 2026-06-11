"""Verify the overlay window follows the game window on resize, then restore."""
import time, ctypes
import ctypes.wintypes as wt
import winutil
import overlay as ov_mod

u = ctypes.windll.user32
hwnd = winutil.find_pcsx2_window()
assert hwnd, "no pcsx2 window"


def winrect(h):
    r = wt.RECT(); u.GetWindowRect(h, ctypes.byref(r))
    return (r.left, r.top, r.right - r.left, r.bottom - r.top)


orig = winrect(hwnd)
ov = ov_mod.Overlay(hwnd).start()
time.sleep(0.4)
oh = u.FindWindowW("GowDmgOverlayA", None)
try:
    print("BEFORE  pcsx2 client:", winutil.client_rect_on_screen(hwnd))
    print("        overlay rect :", winrect(oh))
    u.MoveWindow(hwnd, orig[0], orig[1], orig[2] + 160, orig[3] + 120, True)
    time.sleep(0.5)
    pc = winutil.client_rect_on_screen(hwnd)
    ovr = winrect(oh)
    print("AFTER   pcsx2 client:", pc)
    print("        overlay rect :", ovr)
    print("MATCH:", pc == ovr)
finally:
    u.MoveWindow(hwnd, orig[0], orig[1], orig[2], orig[3], True)
    time.sleep(0.3)
    print("restored:", winrect(hwnd) == orig)
