"""
gow_overlay.py - God of War (PCSX2) live damage overlay.

When an enemy loses health, the damage it took pops up above it and floats away.

Robust across saves/reloads (no hardcoded enemy addresses):
  * Enemies are found periodically by STRUCT SIGNATURE (enemy.scan): a world
    position vec4 (w=1) at +0x110 and a health pair (cur<=max) at +0x178/+0x17C.
  * Health + position are read live each frame for the tracked actors.
  * A health DROP => damage; the delta is drawn at the actor's screen position,
    projected by liveproj using the camera-to-world matrix read live from
    0x0072E090 (rotation + camera position) plus calibrated intrinsics. This
    tracks the camera through any pan/rotation/translation.
  * Each number is anchored to its enemy and re-projected every frame; the
    overlay LERPs the on-screen position so the number follows smoothly.

Look & behaviour are tunable in settings.json (edit live with --setup).

Run:
  python gow_overlay.py              normal logging
  python gow_overlay.py --verbose    show all data
  python gow_overlay.py --dmg         show only damage logs
  python gow_overlay.py --silent      print only 'running'
  python gow_overlay.py --setup       open the settings window
  python gow_overlay.py --simulate    inject demo hits
"""
import sys
import os
import time
import random
import threading

# ---------------------------------- WIP ----------------------------------
if "posix" in os.name:
    import _linux_support_wip_tools as ltools
    if "--force" in sys.argv:
        print(ltools.FORCE_WARNING_MESSAGE)
    else:
        ltools.ProgTrk.LinuxDevProgError()

else:
    import pine
    import memscan
    import enemy
    import liveproj
    import winutil
# ---------------------------------- WIP ----------------------------------


import config as cfg
import overlay as overlay_mod
from settings import S


MARGIN = 80               # allow numbers this far past the client edge before culling

# --- logging verbosity & force arg ---
SILENT, DMG, NORMAL, VERBOSE, FORCE = 0, 1, 2, 3, 99


def parse_level(argv):
    if "--silent" in argv:
        return SILENT
    if "--dmg" in argv:
        return DMG
    if "--verbose" in argv:
        return VERBOSE
    return NORMAL


LEVEL = NORMAL            # set in main()


class Tracker(threading.Thread):
    """Background actor enumeration (RPM only) so the draw loop never stalls."""
    def __init__(self, scanner):
        super().__init__(daemon=True)
        self.sc = scanner
        self.actors = {}            # base -> {"max", "last", "miss"}
        self.lock = threading.Lock()
        self._run = True

    def run(self):
        while self._run:
            tk = S["tracking"]
            period = tk["scan_period"]
            try:
                found = enemy.scan(self.sc, creature_min=tk["creature_min_hp"],
                                   creature_max=tk["creature_max_hp"])
            except Exception:
                time.sleep(period); continue
            valid = {a["base"] for a in found}
            player_base = enemy.find_player(self.sc, valid)     # Kratos -> excluded
            ppos = next((a["pos"] for a in found if a["base"] == player_base), None)
            near = tk["near_player_dist"]
            with self.lock:
                seen = set()
                for a in found:
                    if a["base"] == player_base:
                        continue                                 # never tag the player
                    if a["cur"] <= 0.5:
                        continue                                 # skip dead/inert actors
                    if ppos and (abs(a["pos"][0] - ppos[0]) > near or abs(a["pos"][2] - ppos[2]) > near):
                        continue
                    b = a["base"]; seen.add(b)
                    if b in self.actors:
                        self.actors[b]["max"] = a["max"]; self.actors[b]["miss"] = 0
                    else:
                        self.actors[b] = {"max": a["max"], "last": a["cur"], "miss": 0}
                for b in list(self.actors):
                    if b not in seen:
                        self.actors[b]["miss"] += 1
                        if self.actors[b]["miss"] > 3:
                            del self.actors[b]
            time.sleep(period)

    def stop(self):
        self._run = False


def wait_for_game(poll=1.0):
    """Block until PCSX2 is running with a game loaded (PINE up + window present).
    Returns (PineClient, pid, hwnd). Prints a waiting message once."""
    announced = False
    while True:
        pid = memscan.find_pcsx2_pid()
        hwnd = winutil.find_pcsx2_window()
        if pid and hwnd:
            try:
                pc = pine.PineClient().connect()
                if pc.title() and pc.game_id():
                    return pc, pid, hwnd
                pc.close()
            except Exception:
                pass
        if not announced:
            print("Waiting for game to launch...", flush=True)
            announced = True
        time.sleep(poll)


def main():
    global LEVEL
    LEVEL = parse_level(sys.argv)
    cfg.load()
    pc, pid, hwnd = wait_for_game()
    if LEVEL >= NORMAL:
        print("connected:", pc.title(), pc.game_id())

    rpm = memscan.RpmReader(pid)
    base = None
    for attempt in range(8):
        base = rpm.locate_ee_base(pc)       # re-samples each try (fresh pivot)
        if base is not None:
            break
        if attempt == 0 and LEVEL >= NORMAL:
            print("locating game memory...", flush=True)
        time.sleep(0.4)
    if base is None:
        print("ERROR: could not locate EE RAM base (make sure you're in-game, then retry)")
        return
    rpm.ee_base = base
    sc = memscan.Scanner(rpm)

    ov = overlay_mod.Overlay(hwnd).start()
    _, _, cw, ch = winutil.client_rect_on_screen(hwnd)
    proj = liveproj.LiveProjection()

    simulate = "--simulate" in sys.argv
    tr = Tracker(sc); tr.start()
    if LEVEL >= NORMAL:
        print(f"running ({cw}x{ch}) - damage numbers appear over enemies that lose health. "
              f"Ctrl+C to stop.", flush=True)
    else:
        print("running", flush=True)

    OFF_HP, OFF_POS = enemy.OFF_HP, enemy.OFF_POS
    active = []          # [{"base", "fn"}] live damage numbers being tracked
    frame = 0
    while True:
        frame += 1
        if simulate and frame % 18 == 0:        # demo: inject a hit on a random enemy
            with tr.lock:
                bs = list(tr.actors.keys())
            if bs:
                b = random.choice(bs)
                cur = float(pc.batch_read([("f32", b + OFF_HP)])[0])
                pc.write_float(b + OFF_HP, (cur - random.choice([8, 11, 18, 32])) if cur > 6 else 35.0)

        with tr.lock:
            bases = list(tr.actors.keys())
            last = {b: tr.actors[b]["last"] for b in bases}

        head = S["numbers"]["head_offset"]
        # one batched read: camera matrix (16 floats) + hp/pos per enemy
        reqs = proj.reqs()
        for b in bases:
            reqs += [("f32", b + OFF_HP), ("f32", b + OFF_POS),
                     ("f32", b + OFF_POS + 4), ("f32", b + OFF_POS + 8)]
        try:
            vals = pc.batch_read(reqs)
        except Exception:
            time.sleep(0.1); continue
        proj.set_matrix(vals[:16])

        o = 16
        cur_pos = {}
        for b in bases:
            hp, x, y, z = (float(vals[o]), float(vals[o + 1]), float(vals[o + 2]), float(vals[o + 3]))
            o += 4
            cur_pos[b] = (hp, x, y, z)
            if hp < last[b] - 0.5 and hp >= 0 and (last[b] - hp) <= S["numbers"]["max_damage"]:
                dmg = int(round(last[b] - hp))
                s = proj.project(x, y, z)
                onscreen = s and (-MARGIN <= s[0] <= overlay_mod.CALIB_W + MARGIN
                                  and -MARGIN <= s[1] <= overlay_mod.CALIB_H + MARGIN)
                if LEVEL >= VERBOSE:
                    print(f"  DMG {dmg} on 0x{b:08X} hp{last[b]:.0f}->{hp:.0f} -> "
                          f"{None if not s else (round(s[0]), round(s[1]))}", flush=True)
                elif LEVEL >= DMG:
                    print(f"  DMG {dmg} on 0x{b:08X}", flush=True)
                if onscreen:
                    fn = ov.spawn(s[0], s[1] - head, str(dmg),
                                  overlay_mod.dmg_color(dmg), overlay_mod.dmg_size(dmg),
                                  epic=overlay_mod.impact_strength(dmg))
                    active.append({"base": b, "fn": fn})
            with tr.lock:
                if b in tr.actors:
                    tr.actors[b]["last"] = hp

        # keep each live number anchored to its (moving) enemy; overlay lerps
        nowt = time.time()
        alive = []
        for a in active:
            fn = a["fn"]
            if nowt - fn.born > fn.ttl:
                continue
            hp_xyz = cur_pos.get(a["base"])
            if hp_xyz is not None:
                s = proj.project(hp_xyz[1], hp_xyz[2], hp_xyz[3])
                if s:
                    fn.set_target(s[0], s[1] - head)
            alive.append(a)
        active = alive

        if LEVEL >= NORMAL and frame % 60 == 0:
            print(f"[{frame}] tracking {len(bases)} enemies, {len(active)} numbers", flush=True)
        time.sleep(0.03)


if __name__ == "__main__":
    if "--setup" in sys.argv:
        import setup_gui
        setup_gui.main()
    else:
        try:
            main()
        except KeyboardInterrupt:
            print("\nstopped.")
