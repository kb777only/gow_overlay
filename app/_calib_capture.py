"""Multi-view calibration capture. For one paused pose:
  * snapshot the EE static region (for later brute-force camera search)
  * enumerate live enemies (world positions)
  * screenshot the frame, crop to the PCSX2 client, draw a labelled pixel grid
    and a lettered circle at each enemy's ROUGH projected spot
The user then reports the true pixel of each lettered enemy. Run once per pose:
    python _calib_capture.py <pose_index>
"""
import sys
import json
import subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

import pine
import memscan
import enemy
import winutil

STATIC_START = 0x00100000
STATIC_END = 0x01000000
CALIB_W, CALIB_H = 1124.0, 676.0
ROUGH_CAM = 0x003E9D00          # candidate #2: rough projection just to place letters
LETTERS = "ABCDEFGH"


def font(sz):
    for p in ("/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(p, sz)
        except Exception:
            pass
    return ImageFont.load_default()


def main():
    pose = int(sys.argv[1])
    calib = json.load(open("camcalib.json"))
    cx, cy, fx, fy, h = (calib[k] for k in ("cx", "cy", "fx", "fy", "h"))

    pc = pine.PineClient(timeout=6.0).connect()
    print("game", pc.game_id(), "status", pc.status())
    sc = memscan.Scanner(memscan.PineReader(pc))
    full = sc.snapshot()                              # full window (for enemy scan)
    acts = enemy.scan(sc, creature_min=10, creature_max=300)
    live = [a for a in acts if a["cur"] > 0.5]
    P = np.array([a["pos"] for a in live], dtype=np.float64)
    bases = np.array([a["base"] for a in live], dtype=np.int64)

    a32 = np.frombuffer(full, dtype=np.float32).astype(np.float64)
    off = (ROUGH_CAM - sc.start) // 4
    M = a32[off:off + 16].reshape(4, 4)
    R, c = M[:3, :3], M[3, :3]
    view = (P + np.array([0, h, 0]) - c) @ R.T
    z = view[:, 2]
    rough = []                                        # (calib_px, calib_py) per enemy
    for e in range(len(P)):
        if z[e] < -1.0:
            rough.append((cx + fx * view[e, 0] / z[e], cy + fy * view[e, 1] / z[e]))
        else:
            rough.append((None, None))

    # window geometry + CALIB->client mapping (matches overlay.to_screen)
    hwnd = winutil.find_pcsx2_window()
    wx, wy, ww, wh = winutil.client_rect_on_screen(hwnd)
    ar = CALIB_W / CALIB_H
    if ww / max(1, wh) > ar:
        rh = float(wh); rw = rh * ar
    else:
        rw = float(ww); rh = rw / ar
    rx0 = (ww - rw) * 0.5; ry0 = (wh - rh) * 0.5
    scl = rw / CALIB_W

    def to_crop(px, py):
        return rx0 + px * scl, ry0 + py * scl

    # save the static-region snapshot + enemy data for the solver
    static = np.frombuffer(full, dtype=np.float32)[
        (STATIC_START - sc.start) // 4: (STATIC_END - sc.start) // 4].copy()
    np.savez(f"/tmp/calib/pose_{pose}.npz", static=static, static_start=STATIC_START,
             enemy_pos=P, enemy_base=bases, window=np.array([wx, wy, ww, wh]),
             rxyscl=np.array([rx0, ry0, scl]))

    # screenshot -> crop -> grid + lettered enemies
    subprocess.run(["spectacle", "-b", "-f", "-n", "-o", "/tmp/calib/_full.png"],
                   check=False)
    im = Image.open("/tmp/calib/_full.png").crop((wx, wy, wx + ww, wy + wh)).convert("RGB")
    im = ImageEnhance.Brightness(im).enhance(1.9)
    im = ImageEnhance.Contrast(im).enhance(1.15)
    d = ImageDraw.Draw(im, "RGBA")
    fnt = font(13); fbig = font(30)
    for gx in range(0, ww, 50):
        col = (255, 255, 255, 110) if gx % 100 else (255, 255, 0, 150)
        d.line([(gx, 0), (gx, wh)], fill=col, width=1)
        if gx % 100 == 0:
            d.text((gx + 2, 2), str(gx), font=fnt, fill=(255, 255, 0, 255))
    for gy in range(0, wh, 50):
        col = (255, 255, 255, 110) if gy % 100 else (255, 255, 0, 150)
        d.line([(0, gy), (ww, gy)], fill=col, width=1)
        if gy % 100 == 0:
            d.text((2, gy + 2), str(gy), font=fnt, fill=(255, 255, 0, 255))
    print(f"\n=== POSE {pose}: {len(live)} live enemies ===")
    for e in range(len(P)):
        rx, ry = rough[e]
        lbl = LETTERS[e] if e < len(LETTERS) else f"e{e}"
        info = f"  {lbl}: world=({P[e,0]:.0f},{P[e,1]:.0f},{P[e,2]:.0f}) hp={live[e]['cur']:.0f}"
        if rx is not None:
            wxp, wyp = to_crop(rx, ry)
            info += f"  rough_pixel=({wxp:.0f},{wyp:.0f})"
            if 0 <= wxp < ww and 0 <= wyp < wh:        # only mark on-screen rough spots
                d.ellipse([wxp - 16, wyp - 16, wxp + 16, wyp + 16], outline=(255, 20, 20, 255), width=4)
                d.text((wxp + 17, wyp - 16), lbl, font=fbig, fill=(255, 60, 0, 255),
                       stroke_width=2, stroke_fill=(0, 0, 0, 255))
            else:
                info += " (off-screen)"
        else:
            info += "  (behind camera in rough proj)"
        print(info)
    out = f"/tmp/calib/pose_{pose}_grid.png"
    im.save(out)
    print(f"\nGrid image: {out}")
    print("Open it and tell me the TRUE pixel (x,y) of each lettered enemy.")
    pc.close()


if __name__ == "__main__":
    main()
