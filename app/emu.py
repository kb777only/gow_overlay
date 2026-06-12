"""emu.py - reliable pause/resume of PCSX2 via the Space hotkey + PINE status."""
import time
import winutil
import pine

RUNNING, PAUSED, SHUTDOWN = 0, 1, 2


def _toggle():
    h = winutil.find_pcsx2_window()
    if not h:
        return False
    if not winutil.focus_window(h):     # native Wayland window: keys can't reach it
        return False
    time.sleep(0.25)
    winutil.key_down('space')
    time.sleep(0.06)
    winutil.key_up('space')
    time.sleep(0.35)
    return True


def ensure_paused(pc: pine.PineClient, tries: int = 4) -> bool:
    for _ in range(tries):
        if pc.status() == PAUSED:
            return True
        _toggle()
    return pc.status() == PAUSED


def ensure_running(pc: pine.PineClient, tries: int = 4) -> bool:
    for _ in range(tries):
        if pc.status() == RUNNING:
            return True
        _toggle()
    return pc.status() == RUNNING


if __name__ == "__main__":
    pc = pine.PineClient().connect()
    print("status:", pc.status())
    print("pause ->", ensure_paused(pc), "status", pc.status())
    print("run   ->", ensure_running(pc), "status", pc.status())
