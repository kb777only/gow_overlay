"""Measure the overlay's CPU cost per regime on this machine. Reads the whole
process's utime+stime from /proc/self/stat (the render thread runs in-process),
so the figure is % of ONE core devoted to the overlay."""
import os
import time
import random
import overlay as om
import winutil

CLK = os.sysconf("SC_CLK_TCK")


def ticks():
    with open("/proc/self/stat") as f:
        p = f.read().split()
    return int(p[13]) + int(p[14])      # utime + stime (process-wide, all threads)


def main():
    hwnd = winutil.find_pcsx2_window()
    assert hwnd, "no pcsx2 window"
    ov = om.Overlay(hwnd).start()
    x, y, w, h = winutil.client_rect_on_screen(hwnd)
    print(f"window {w}x{h}")
    time.sleep(1.0)                     # let it settle / first window-follow ticks

    def measure(name, dur, spawn=None, interval=0.4):
        t0 = time.time(); c0 = ticks(); nxt = 0.0
        while time.time() - t0 < dur:
            if spawn and (time.time() - t0) >= nxt:
                spawn(); nxt += interval
            time.sleep(0.03)
        dt = time.time() - t0; dc = ticks() - c0
        print(f"  {name:<22} {dc / (CLK * dt) * 100:5.1f}% of one core")

    def pos():
        return random.uniform(320, 780), random.uniform(250, 440)

    PLAIN = [7, 12, 19, 26, 34]         # small rotating set => warm tile cache
    EPIC = [140, 220, 310, 420]
    pi = ei = 0

    def plain():
        nonlocal pi
        px, py = pos(); v = PLAIN[pi % len(PLAIN)]; pi += 1
        ov.spawn(px, py, str(v), (255, 150, 40), 32, epic=0.0)

    def epic():
        nonlocal ei
        px, py = pos(); v = EPIC[ei % len(EPIC)]; ei += 1
        ov.spawn(px, py, str(v), (255, 210, 90), 62, epic=1.0)

    print("benchmarking (8s each)...")
    measure("idle / blank", 8, None)
    measure("plain numbers", 8, plain, 0.4)
    measure("epic bursts (all FX)", 8, epic, 0.6)
    ov.stop(); time.sleep(0.3)


if __name__ == "__main__":
    main()
