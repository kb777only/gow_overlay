"""Robust actor enumeration by struct signature (addresses are dynamic, so we
never hardcode them). Layout (offsets from actor base B), verified to survive
checkpoint reloads:
  B+0x110 : world position vec4 (x, y, z, 1.0)
  B+0x50  : 4x4 world transform (rotation rows + translation, w=1 at B+0x8C)
  B+0x178 : current health,  B+0x17C : max health

scan() is numpy-vectorised (~0.1s over 32 MiB). Returns dicts with base/cur/max/pos.
"""
import numpy as np

OFF_POS = 0x110
OFF_HP = 0x178
OFF_HPMAX = 0x17C
OFF_MAT = 0x50

# "current player entity" global pointers (SCES-53133). Several game systems hold
# a pointer to Kratos's actor; we read them from the snapshot each scan and take
# the actor base the majority agree on (validated as a live actor). These update
# when Kratos's actor is reallocated, so the player is excluded across reloads.
PLAYER_PTRS = (0x006CD110, 0x0076B2F0, 0x0076D0FC, 0x0076E108,
               0x007722F0, 0x007D8040, 0x007F71B0)


def scan(sc, snapshot=None, hp_min=1.0, hp_max=2000.0,
         creature_min=None, creature_max=None):
    data = snapshot if snapshot is not None else sc.snapshot()
    a = np.frombuffer(data, dtype=np.float32)
    N = len(a)
    i = np.arange(0x68 // 4, N - 2)              # health float index
    cur = a[i]; mx = a[i + 1]
    pw = a[i - (0x5C // 4)]                       # pos.w  (H-0x5C)
    px = a[i - (0x68 // 4)]                       # pos.x  (H-0x68)
    py = a[i - (0x64 // 4)]
    pz = a[i - (0x60 // 4)]
    with np.errstate(invalid="ignore"):
        m = (mx >= hp_min) & (mx <= hp_max) & (cur >= 0) & (cur <= mx + 0.01) & (pw == 1.0)
        m &= (np.abs(px) > 30) & (np.abs(px) < 50000) & (np.abs(pz) > 30) & (np.abs(pz) < 50000) & (np.abs(py) < 50000)
    if creature_min is not None:
        m &= mx >= creature_min
    if creature_max is not None:
        m &= mx <= creature_max
    idx = i[m]
    out = []
    for k in idx.tolist():
        base = sc.start + k * 4 - OFF_HP
        out.append({"base": base, "cur": float(a[k]), "max": float(a[k + 1]),
                    "pos": (float(px[k - (0x68 // 4)]) if False else float(a[k - (0x68 // 4)]),
                            float(a[k - (0x64 // 4)]), float(a[k - (0x60 // 4)]))})
    return out


def find_player(sc, valid_bases):
    """Identify Kratos's current actor base from the player-pointer globals in the
    last snapshot (sc.prev). Returns a base present in valid_bases, or None.
    Reliable regardless of the actor's health, so enemies need no health ceiling."""
    if getattr(sc, "prev", None) is None:
        return None
    u = np.frombuffer(sc.prev, dtype=np.uint32)
    n = len(u)
    counts = {}
    for ptr in PLAYER_PTRS:
        i = (ptr - sc.start) // 4
        if 0 <= i < n:
            b = int(u[i])
            if b in valid_bases:
                counts[b] = counts.get(b, 0) + 1
    return max(counts, key=counts.get) if counts else None


if __name__ == "__main__":
    import memscan, time
    pc, rpm, sc = memscan.open_default(pause_for_locate=False)
    t = time.time()
    actors = scan(sc, creature_min=10, creature_max=300)
    print(f"scan {len(actors)} creature-actors in {(time.time()-t)*1000:.0f} ms")
    for a in sorted(actors, key=lambda d: -d["max"])[:30]:
        x, y, z = a["pos"]
        print(f"  0x{a['base']:08X}  hp {a['cur']:.0f}/{a['max']:.0f}  ({x:.0f},{y:.0f},{z:.0f})")
