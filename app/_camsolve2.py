"""Brute-force camera finder over all orthonormal globals that changed between
the two poses. For each candidate x projection-model x front-sign, search the
pixel<->enemy correspondence (axis-aligned affine => match by sorted order),
fit intrinsics per pose, and keep candidates whose pose-1/pose-2 intrinsics
agree and are physically plausible."""
import json
import itertools
import numpy as np

P1 = np.load("/tmp/calib/pose_1.npz"); P2 = np.load("/tmp/calib/pose_2.npz")
START = int(P1["static_start"])
H = json.load(open("camcalib.json"))["h"]
PIX = {1: [(115, 300), (180, 235), (415, 265), (490, 265)],
       2: [(725, 260), (790, 270), (850, 290), (935, 275)]}


def calib_pix(pose, npz):
    rx0, ry0, scl = npz["rxyscl"]
    return np.array([[(x - rx0) / scl, (y - ry0) / scl] for x, y in PIX[pose]])


PX = {1: calib_pix(1, P1), 2: calib_pix(2, P2)}
S1 = P1["static"].astype(np.float64); S2 = P2["static"].astype(np.float64)
POS = {1: P1["enemy_pos"], 2: P2["enemy_pos"]}
STAT = {1: S1, 2: S2}


def omask(a):
    W = np.lib.stride_tricks.sliding_window_view(a, 16)
    fin = np.all(np.isfinite(W), axis=1)
    r = lambda i: W[:, [i * 4, i * 4 + 1, i * 4 + 2]]
    r0, r1, r2 = r(0), r(1), r(2)
    n = lambda x: (x * x).sum(1)
    m = (np.abs(n(r0) - 1) < 0.05) & (np.abs(n(r1) - 1) < 0.05) & (np.abs(n(r2) - 1) < 0.05)
    m &= (np.abs((r0 * r1).sum(1)) < 0.03) & (np.abs((r0 * r2).sum(1)) < 0.03) & (np.abs((r1 * r2).sum(1)) < 0.03)
    notI = (np.abs(r0[:, 0] - 1) + np.abs(r1[:, 1] - 1) + np.abs(r2[:, 2] - 1)) > 0.05
    return m & fin & notI


def candidates():
    m1, m2 = omask(S1), omask(S2)
    W1 = np.lib.stride_tricks.sliding_window_view(S1, 16)
    W2 = np.lib.stride_tricks.sliding_window_view(S2, 16)
    diff = np.abs(W1 - W2).sum(1)
    return np.nonzero(m1 & m2 & (diff > 0.5))[0]


def matrix(st, k):
    M = st[k:k + 16].reshape(4, 4)
    return M[:3, :3], M[3, :3]


def views(R, t, Pp, model):
    d = Pp - t
    if model == "R(P-t)":   return d @ R.T
    if model == "Rt(P-t)":  return d @ R
    if model == "RtP+t":    return Pp @ R + t
    if model == "RP+t":     return Pp @ R.T + t


def lin(x, y):
    """y = a + b x closed form; return a,b,rms."""
    xm, ym = x.mean(), y.mean()
    vx = ((x - xm) ** 2).sum()
    if vx < 1e-9:
        return 0.0, 0.0, 1e9
    b = ((x - xm) * (y - ym)).sum() / vx
    a = ym - b * xm
    r = a + b * x - y
    return a, b, float(np.sqrt((r * r).mean()))


def best_pose(view, pix, sign):
    vz = view[:, 2]
    keep = np.nonzero(sign * vz > 1e-3)[0]
    if len(keep) < 4:
        return None
    u = view[keep, 0] / vz[keep]; v = view[keep, 1] / vz[keep]
    px = np.sort(pix[:, 0]); order_px = np.argsort(pix[:, 0])
    py = pix[order_px, 1]                      # py paired to ascending-px
    best = None
    for combo in itertools.combinations(range(len(keep)), 4):
        c = np.array(combo)
        for desc in (False, True):
            ou = np.argsort(u[c])[::-1] if desc else np.argsort(u[c])
            cc = c[ou]                          # enemies ordered to match ascending px
            cxa, fx, rx = lin(u[cc], px)
            cya, fy, ry = lin(v[cc], py)
            if abs(fx) < 200 or abs(fy) < 200 or abs(fx) > 2500 or abs(fy) > 2500:
                continue
            if not (250 < cxa < 900 and 120 < cya < 560):
                continue
            rms = rx + ry
            if best is None or rms < best[0]:
                best = (rms, keep[cc], (cxa, cya, fx, fy))
    return best


def main():
    cand = candidates()
    print(f"testing {len(cand)} candidates")
    results = []
    for k in cand.tolist():
        addr = START + k * 4
        for model in ("R(P-t)", "Rt(P-t)", "RtP+t", "RP+t"):
            for sign in (-1, +1):
                per = {}
                for pose in (1, 2):
                    R, t = matrix(STAT[pose], k)
                    Pp = POS[pose] + np.array([0, H, 0])
                    b = best_pose(views(R, t, Pp, model), PX[pose], sign)
                    if b is None:
                        per = None; break
                    per[pose] = b
                if per is None:
                    continue
                p1, p2 = np.array(per[1][2]), np.array(per[2][2])
                dis = np.abs(p1 - p2)
                # principal point must agree well; focal lengths within ~25%
                if dis[0] > 60 or dis[1] > 60:
                    continue
                if dis[2] > 0.25 * abs(p1[2]) + 60 or dis[3] > 0.25 * abs(p1[3]) + 60:
                    continue
                score = per[1][0] + per[2][0] + 0.05 * (dis[0] + dis[1]) + 0.02 * (dis[2] + dis[3])
                results.append((score, addr, model, sign, per[1], per[2]))
    results.sort(key=lambda r: r[0])
    print(f"\n{len(results)} consistent fits. Top:")
    for score, addr, model, sign, b1, b2 in results[:15]:
        cx = (b1[2][0] + b2[2][0]) / 2; cy = (b1[2][1] + b2[2][1]) / 2
        fx = (b1[2][2] + b2[2][2]) / 2; fy = (b1[2][3] + b2[2][3]) / 2
        print(f"  0x{addr:08X} {model:8s} sign={sign:+d} score={score:5.1f} "
              f"rms=({b1[0]:.1f},{b2[0]:.1f}) -> cx={cx:.0f} cy={cy:.0f} fx={fx:.0f} fy={fy:.0f}")
        print(f"        pose1 enemies idx {b1[1].tolist()}  pose2 idx {b2[1].tolist()}")


if __name__ == "__main__":
    main()
