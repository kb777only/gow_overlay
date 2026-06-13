"""Interactive camera-matrix locator: overlays a numbered marker per candidate
camera-to-world matrix (projecting the live enemies through it) so a human can
read off which number lands on the on-screen enemies. One-off dev tool."""
import json
import time
import numpy as np

import pine
import memscan
import enemy
import winutil
import overlay as overlay_mod

CALIB_W, CALIB_H = 1124.0, 676.0
COLORS = [(255, 60, 60), (60, 220, 60), (80, 160, 255), (255, 230, 40),
          (255, 120, 255), (60, 240, 240), (255, 150, 40), (180, 120, 255)]


def main():
    calib = json.load(open("camcalib.json"))
    cx, cy, fx, fy, h = (calib[k] for k in ("cx", "cy", "fx", "fy", "h"))

    pc = pine.PineClient(timeout=5.0).connect()
    print("game", pc.game_id(), "status", pc.status())
    sc = memscan.Scanner(memscan.PineReader(pc))
    data = sc.snapshot()
    acts = enemy.scan(sc, creature_min=10, creature_max=300)
    live = [a for a in acts if a["cur"] > 0.5]
    P = np.array([a["pos"] for a in live], dtype=np.float64)
    cen = P.mean(0)
    print(f"{len(live)} live enemies, centroid {cen.round(0)}")

    a = np.frombuffer(data, dtype=np.float32).astype(np.float64)
    W = np.lib.stride_tricks.sliding_window_view(a, 16)
    finite = np.all(np.isfinite(W), axis=1)

    def rows(i):
        return W[:, [i * 4, i * 4 + 1, i * 4 + 2]]

    r0, r1, r2 = rows(0), rows(1), rows(2)
    n0 = (r0 * r0).sum(1); n1 = (r1 * r1).sum(1); n2 = (r2 * r2).sum(1)
    orth = (np.abs(n0 - 1) < 0.05) & (np.abs(n1 - 1) < 0.05) & (np.abs(n2 - 1) < 0.05)
    orth &= (np.abs((r0 * r1).sum(1)) < 0.03) & (np.abs((r0 * r2).sum(1)) < 0.03) \
        & (np.abs((r1 * r2).sum(1)) < 0.03)
    cam = W[:, [12, 13, 14]]
    near = np.all(np.abs(cam - cen) < 6000, axis=1)
    notI = (np.abs(r0[:, 0] - 1) + np.abs(r1[:, 1] - 1) + np.abs(r2[:, 2] - 1)) > 0.05
    idx = np.nonzero(finite & orth & near & notI)[0]

    D0 = P + np.array([0, h, 0])
    scored = []
    for k in idx.tolist():
        R = np.array([r0[k], r1[k], r2[k]]); c = cam[k]
        view = (D0 - c) @ R.T
        z = view[:, 2]; inf = z < -1.0
        if inf.sum() < len(P) * 0.6:
            continue
        sx = cx + fx * view[:, 0] / z
        sy = cy + fy * view[:, 1] / z
        on = inf & (sx > -200) & (sx < CALIB_W + 200) & (sy > -200) & (sy < CALIB_H + 200)
        if on.sum() < len(P) * 0.5:
            continue
        spread = float(np.std(sx[on]) + np.std(sy[on])) if on.sum() > 1 else 0.0
        scored.append((int(on.sum()), spread, sc.start + k * 4, R, c))
    scored.sort(key=lambda t: (-t[0], -t[1]))

    # dedupe near-identical matrices (same cam, same rotation)
    distinct = []
    for on, sp, addr, R, c in scored:
        if any(np.allclose(c, c2, atol=30) and np.allclose(R, R2, atol=0.02)
               for _, _, _, R2, c2 in distinct):
            continue
        distinct.append((on, sp, addr, R, c))
        if len(distinct) >= 6:
            break

    print("\n=== CANDIDATES (number you'll see on screen -> address) ===")
    markers = []
    for i, (on, sp, addr, R, c) in enumerate(distinct, 1):
        col = COLORS[(i - 1) % len(COLORS)]
        print(f"  #{i}  0x{addr:08X}  cam=({c[0]:.0f},{c[1]:.0f},{c[2]:.0f})  "
              f"onscreen {on}/{len(P)} spread {sp:.0f}  color rgb{col}")
        view = (D0 - c) @ R.T
        z = view[:, 2]
        for e in range(len(P)):
            if z[e] >= -1.0:
                continue
            px = cx + fx * view[e, 0] / z[e]
            py = cy + fy * view[e, 1] / z[e]
            if -200 < px < CALIB_W + 200 and -200 < py < CALIB_H + 200:
                markers.append((px, py, str(i), col))
    pc.close()   # PINE is single-connection; release it for the overlay/window IPC

    hwnd = winutil.find_pcsx2_window()
    ov = overlay_mod.Overlay(hwnd).start()
    ov.set_markers(markers)
    print(f"\nOverlay up with {len(markers)} markers. Look at the game: the number"
          f"\nwhose copies sit centered on the enemies is the real camera.")
    print("Leave this running; it holds the overlay. (Ctrl+C to stop.)")
    while True:
        time.sleep(1.0)
        ov.set_markers(markers)   # keep them latched


if __name__ == "__main__":
    main()
