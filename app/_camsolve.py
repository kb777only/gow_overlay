"""Solve: which projection convention + intrinsics make a candidate camera
matrix reproject the user-marked enemy pixels across both poses."""
import sys
import json
import itertools
import numpy as np

P1 = np.load("/tmp/calib/pose_1.npz"); P2 = np.load("/tmp/calib/pose_2.npz")
START = int(P1["static_start"])
H = json.load(open("camcalib.json"))["h"]

# user pixels (crop coords) -> CALIB via each pose's saved rx0,ry0,scl
PIX = {
    1: [(115, 300), (180, 235), (415, 265), (490, 265)],
    2: [(725, 260), (790, 270), (850, 290), (935, 275)],
}


def calib_pix(pose, npz):
    rx0, ry0, scl = npz["rxyscl"]
    return np.array([[(x - rx0) / scl, (y - ry0) / scl] for x, y in PIX[pose]])


POSES = {1: (P1, calib_pix(1, P1)), 2: (P2, calib_pix(2, P2))}


def matrix(npz, addr):
    st = npz["static"].astype(np.float64)
    o = (addr - START) // 4
    M = st[o:o + 16].reshape(4, 4)
    return M[:3, :3], M[3, :3]


def models(R, t, Pp):
    """Pp: (N,3) world+head. Return dict name->view(N,3)."""
    d = Pp - t
    return {
        "R(P-t)":   d @ R.T,          # col-vec camera-to-world: R@(p-t)
        "Rt(P-t)":  d @ R,            # R.T@(p-t)
        "RtP+t":    Pp @ R + t,       # row-vec world-to-view
        "RP+t":     Pp @ R.T + t,     # col-vec world-to-view
    }


def fit_axis(x, target):
    """least squares target = a + b*x ; return a,b,rms."""
    A = np.vstack([np.ones_like(x), x]).T
    sol, *_ = np.linalg.lstsq(A, target, rcond=None)
    res = A @ sol - target
    return sol[0], sol[1], float(np.sqrt(np.mean(res ** 2)))


def best_assignment(view, pix, sign):
    """view (N,3), pix (4,2). sign: keep points with sign*vz>0. Try all
    ordered 4-subsets; fit px=a+b*u, py=c+d*v; return best (idx, params, rms)."""
    vz = view[:, 2]
    keep = np.nonzero(sign * vz > 1e-3)[0]
    if len(keep) < 4:
        return None
    u = view[keep, 0] / vz[keep]
    v = view[keep, 1] / vz[keep]
    best = None
    px, py = pix[:, 0], pix[:, 1]
    for combo in itertools.permutations(range(len(keep)), 4):
        c = list(combo)
        cx, fx, rx = fit_axis(u[c], px)
        cy, fy, ry = fit_axis(v[c], py)
        rms = (rx + ry)
        if best is None or rms < best[0]:
            best = (rms, keep[c], (cx, cy, fx, fy), (rx, ry))
    return best


def main():
    addrs = [int(x, 16) for x in sys.argv[1:]] or [0x006F7150]
    for addr in addrs:
        print(f"\n######## candidate 0x{addr:08X} ########")
        for mname in ["R(P-t)", "Rt(P-t)", "RtP+t", "RP+t"]:
            for sign in (-1, +1):
                per = {}
                ok = True
                for pose, (npz, pix) in POSES.items():
                    R, t = matrix(npz, addr)
                    Pp = npz["enemy_pos"] + np.array([0, H, 0])
                    view = models(R, t, Pp)[mname]
                    b = best_assignment(view, pix, sign)
                    if b is None:
                        ok = False; break
                    per[pose] = b
                if not ok:
                    continue
                # cross-pose: average params, total rms, param agreement
                p1, p2 = per[1][2], per[2][2]
                disagree = np.abs(np.array(p1) - np.array(p2))
                tot = per[1][0] + per[2][0]
                # only report promising ones
                if tot < 120:
                    print(f"  model={mname:8s} sign={sign:+d}  rms1={per[1][0]:6.1f} "
                          f"rms2={per[2][0]:6.1f}")
                    print(f"      pose1 cx,cy,fx,fy = {tuple(round(x,1) for x in p1)}")
                    print(f"      pose2 cx,cy,fx,fy = {tuple(round(x,1) for x in p2)}")
                    print(f"      |disagree| = {tuple(round(x,1) for x in disagree)}")


if __name__ == "__main__":
    main()
