"""Single-pose intrinsics refinement. The camera (0x0075CFB0) is now known, so
project each enemy with the current NTSC intrinsics, label it, draw a fine 25px
grid, and let the user report the corrected center-chest pixel per letter."""
import json
import subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

import pine
import memscan
import enemy
import winutil
import liveproj

CALIB_W, CALIB_H = 1124.0, 676.0
LETTERS = "ABCDEFGHIJ"


def font(sz):
    for p in ("/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(p, sz)
        except Exception:
            pass
    return ImageFont.load_default()


def main():
    pc = pine.PineClient(timeout=6.0).connect()
    gid = pc.game_id()
    proj = liveproj.LiveProjection(gid)
    cx, cy, fx, fy, h = proj.cx, proj.cy, proj.fx, proj.fy, proj.h
    print("game", gid, "status", pc.status(), "rot_addr=0x%08X" % proj.rot_addr)

    sc = memscan.Scanner(memscan.PineReader(pc))
    full = sc.snapshot()
    acts = enemy.scan(sc, creature_min=10, creature_max=300)
    live = [a for a in acts if a["cur"] > 0.5]
    a32 = np.frombuffer(full, dtype=np.float32).astype(np.float64)
    o = (proj.rot_addr - sc.start) // 4
    M = a32[o:o + 16].reshape(4, 4)
    R, c = M[:3, :3], M[3, :3]

    hwnd = winutil.find_pcsx2_window()
    wx, wy, ww, wh = winutil.client_rect_on_screen(hwnd)
    ar = CALIB_W / CALIB_H
    if ww / max(1, wh) > ar:
        rh = float(wh); rw = rh * ar
    else:
        rw = float(ww); rh = rw / ar
    rx0 = (ww - rw) * 0.5; ry0 = (wh - rh) * 0.5; scl = rw / CALIB_W

    rows = []                # (letter, world, u, v, crop_px, crop_py)
    for a in live:
        P = np.array(a["pos"], dtype=np.float64)
        v = R @ (P + np.array([0, h, 0]) - c)
        if v[2] >= -1.0:
            continue
        u, w = v[0] / v[2], v[1] / v[2]
        calx, caly = cx + fx * u, cy + fy * w
        px, py = rx0 + calx * scl, ry0 + caly * scl
        if -40 < px < ww + 40 and -40 < py < wh + 40:
            rows.append([a, P, u, w, px, py])

    np.savez("/tmp/calib/refine.npz",
             world=np.array([r[1] for r in rows]),
             uv=np.array([[r[2], r[3]] for r in rows]),
             proj_px=np.array([[r[4], r[5]] for r in rows]),
             rxyscl=np.array([rx0, ry0, scl]),
             intr=np.array([cx, cy, fx, fy, h]))

    subprocess.run(["spectacle", "-b", "-f", "-n", "-o", "/tmp/calib/_full.png"], check=False)
    im = Image.open("/tmp/calib/_full.png").crop((wx, wy, wx + ww, wy + wh)).convert("RGB")
    im = ImageEnhance.Brightness(im).enhance(1.7)
    d = ImageDraw.Draw(im, "RGBA")
    fg = font(11); fl = font(26)
    for gx in range(0, ww, 25):
        major = gx % 100 == 0
        d.line([(gx, 0), (gx, wh)], fill=(255, 255, 0, 170) if major else (255, 255, 255, 70), width=1)
        if major:
            d.text((gx + 1, 1), str(gx), font=fg, fill=(255, 255, 0, 255))
    for gy in range(0, wh, 25):
        major = gy % 100 == 0
        d.line([(0, gy), (ww, gy)], fill=(255, 255, 0, 170) if major else (255, 255, 255, 70), width=1)
        if major:
            d.text((1, gy + 1), str(gy), font=fg, fill=(255, 255, 0, 255))
    print(f"\n=== {len(rows)} on-screen enemies (current projection) ===")
    for i, r in enumerate(rows):
        lbl = LETTERS[i]
        px, py = r[4], r[5]
        d.ellipse([px - 6, py - 6, px + 6, py + 6], outline=(0, 255, 255, 255), width=2)
        d.line([(px - 12, py), (px + 12, py)], fill=(0, 255, 255, 255), width=1)
        d.line([(px, py - 12), (px, py + 12)], fill=(0, 255, 255, 255), width=1)
        d.text((px + 8, py - 14), lbl, font=fl, fill=(0, 255, 255, 255),
               stroke_width=2, stroke_fill=(0, 0, 0, 255))
        print(f"  {lbl}: world=({r[1][0]:.0f},{r[1][1]:.0f},{r[1][2]:.0f})  "
              f"current_proj=({px:.0f},{py:.0f})")
    im.save("/tmp/calib/refine_grid.png")
    print("\nGrid: /tmp/calib/refine_grid.png  (25px lines, 100px yellow+labelled)")
    print("Cyan crosshair = where each lettered enemy projects NOW. Give me the")
    print("corrected center-chest pixel for each letter.")
    pc.close()


if __name__ == "__main__":
    main()
