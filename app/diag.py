"""diag.py - enemy-detection diagnostic.

Lists every actor the signature scan finds, with health, world position, the live
camera view-space position and projected screen position, and whether the current
tracker would register it. Use it to see which enemy types are missed and to spot
the player. Optional movement test (`--move`) re-scans after a delay so you can
identify Kratos by walking (the actor whose position changes is the player).

Run from app/:  python diag.py        (or:  python diag.py --move)
"""
import sys
import time

import numpy as np
import pine
import memscan
import enemy
import liveproj
from settings import S


def classify(a, ppos, tk):
    """How the current tracker treats this actor."""
    if a["max"] >= tk["enemy_max_hp"]:
        return "EXCLUDED(max>=%d)" % tk["enemy_max_hp"]
    if ppos and (abs(a["pos"][0] - ppos[0]) > tk["near_player_dist"]
                 or abs(a["pos"][2] - ppos[2]) > tk["near_player_dist"]):
        return "EXCLUDED(far)"
    return "enemy"


def main():
    pc = pine.PineClient().connect()
    print("status", pc.status(), pc.title(), pc.game_id())
    rpm = memscan.open_reader(memscan.find_pcsx2_pid(), pc)
    rpm.ee_base = rpm.locate_ee_base(pc)
    sc = memscan.Scanner(rpm)
    tk = S["tracking"]

    found = enemy.scan(sc, creature_min=tk["creature_min_hp"], creature_max=tk["creature_max_hp"])
    players = [a for a in found if 90 <= a["max"] <= 160 and a["cur"] > 0.5]
    ppos = min(players, key=lambda a: abs(a["max"] - 100))["pos"] if players else None

    proj = liveproj.LiveProjection()
    proj.update(pc)
    cam = proj.cam
    print(f"\ncamera world pos = {None if cam is None else tuple(round(c,0) for c in cam)}")
    print(f"{len(found)} actors found  (current tracker would register "
          f"{sum(1 for a in found if classify(a, ppos, tk) == 'enemy')})\n")

    rows = []
    for a in found:
        wx, wy, wz = a["pos"]
        v = proj.R @ (np.array([wx, wy, wz]) - cam) if (proj.R is not None and cam is not None) else None
        s = proj.project(wx, wy, wz)
        rows.append((a, v, s))
    # sort by view-space depth (closest in front first) when available
    def vz(r):
        return r[1][2] if r[1] is not None else 1e9
    rows.sort(key=vz)
    print(f"{'base':>10} {'hp/max':>11} {'world(x,y,z)':>22} {'view(x,y,z)':>20} {'screen':>13} {'on':>3}  class")
    for a, v, s in rows:
        wx, wy, wz = a["pos"]
        vs = "  (none)" if v is None else f"({v[0]:6.0f},{v[1]:6.0f},{v[2]:6.0f})"
        ss = "   -  " if not s else f"({s[0]:5.0f},{s[1]:5.0f})"
        on = "Y" if (s and 0 <= s[0] <= 1124 and 0 <= s[1] <= 676) else "."
        print(f"0x{a['base']:08X} {a['cur']:5.0f}/{a['max']:<5.0f} "
              f"({wx:6.0f},{wy:6.0f},{wz:6.0f}) {vs} {ss}  {on}  {classify(a, ppos, tk)}")

    if "--move" in sys.argv:
        print("\n--move: walk Kratos now... re-scanning in 3s")
        time.sleep(3)
        found2 = {a["base"]: a for a in enemy.scan(sc, creature_min=tk["creature_min_hp"],
                                                   creature_max=tk["creature_max_hp"])}
        moved = []
        for a in found:
            b = a["base"]
            if b in found2:
                d = ((found2[b]["pos"][0]-a["pos"][0])**2 + (found2[b]["pos"][2]-a["pos"][2])**2) ** 0.5
                if d > 3:
                    moved.append((d, b, a["max"]))
        moved.sort(reverse=True)
        print("actors that moved (largest first - the player should be near the top):")
        for d, b, mx in moved[:12]:
            print(f"  0x{b:08X} moved {d:6.1f}  max={mx:.0f}")


if __name__ == "__main__":
    main()
