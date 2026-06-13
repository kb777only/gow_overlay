"""Show numbered markers for an explicit list of candidate camera-matrix
addresses against the CURRENT live scene, so a human can read off which one
projects onto the enemies."""
import sys
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
          (255, 120, 255), (60, 240, 240)]


def main():
    cand_addrs = [int(x, 16) for x in sys.argv[1:]]
    calib = json.load(open("camcalib.json"))
    cx, cy, fx, fy, h = (calib[k] for k in ("cx", "cy", "fx", "fy", "h"))

    pc = pine.PineClient(timeout=5.0).connect()
    print("game", pc.game_id(), "status", pc.status())
    sc = memscan.Scanner(memscan.PineReader(pc))
    print("=== CANDIDATES (number -> address, color) ===")
    for i, addr in enumerate(cand_addrs, 1):
        print(f"  #{i}  0x{addr:08X}  color rgb{COLORS[(i - 1) % len(COLORS)]}")

    hwnd = winutil.find_pcsx2_window()
    ov = overlay_mod.Overlay(hwnd).start()
    print("Overlay up; markers track the enemies live. Ctrl+C to stop.", flush=True)

    FRUSTUM = 4500.0     # only mark actors this close to the camera (cull off-screen world)
    while True:
        data = sc.snapshot()
        acts = enemy.scan(sc, creature_min=10, creature_max=300)   # real enemies only
        P = np.array([a["pos"] for a in acts], dtype=np.float64)
        a = np.frombuffer(data, dtype=np.float32).astype(np.float64)

        def mat(addr):
            off = (addr - sc.start) // 4
            M = a[off:off + 16].reshape(4, 4)
            return M[:3, :3], M[3, :3]

        D0 = P + np.array([0, h, 0]) if len(P) else P
        markers = []
        for i, addr in enumerate(cand_addrs, 1):
            col = COLORS[(i - 1) % len(COLORS)]
            R, c = mat(addr)
            if len(P) == 0:
                continue
            dist = np.linalg.norm(P - c, axis=1)
            view = (D0 - c) @ R.T
            # auto front-sign: whichever makes more enemies project on-screen
            sign = -1.0 if (view[:, 2] < 0).sum() >= (view[:, 2] > 0).sum() else 1.0
            z = view[:, 2]
            for e in range(len(P)):
                if sign * z[e] <= 1.0 or dist[e] > FRUSTUM:
                    continue
                px = cx + fx * view[e, 0] / z[e]
                py = cy + fy * view[e, 1] / z[e]
                if 0 < px < CALIB_W and 0 < py < CALIB_H:    # strictly on-screen only
                    markers.append((px, py, str(i), col))
        ov.set_markers(markers)
        time.sleep(0.1)


if __name__ == "__main__":
    main()
