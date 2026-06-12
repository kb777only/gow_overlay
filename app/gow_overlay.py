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
import time
import random
import threading

import pine
import memscan
import enemy
import liveproj
import winutil

import config as cfg
import overlay as overlay_mod
from settings import S


MARGIN = 80               # allow numbers this far past the client edge before culling

# --- logging verbosity ---
SILENT, DMG, NORMAL, VERBOSE = 0, 1, 2, 3


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
        self._fails = 0

    def run(self):
        while self._run:
            tk = S["tracking"]
            period = tk["scan_period"]
            t0 = time.time()
            try:
                # PINE-read scans make PCSX2's PINE thread do real work, which a
                # slow CPU feels in game speed. Skip scans while paused (nothing
                # spawns), and below pace them so scanning stays a small duty cycle.
                pcc = getattr(self.sc.reader, "pc", None)
                if pcc is not None and pcc.status() != 0:
                    time.sleep(period); continue
                found = enemy.scan(self.sc, creature_min=tk["creature_min_hp"],
                                   creature_max=tk["creature_max_hp"])
                self._fails = 0
            except Exception as e:
                # a failed scan now and then is normal (e.g. game shutdown race);
                # persistent failure means no enemies would ever be found - say so
                self._fails += 1
                if self._fails in (5, 100) and LEVEL >= NORMAL:
                    print(f"warning: enemy scans keep failing ({e!r})", flush=True)
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
            # pace by how long the scan actually took (<=25% duty): direct reads
            # are ~0.1s so this stays at scan_period; PINE reads self-throttle so
            # the emulator keeps its CPU on weak machines.
            time.sleep(max(period, 3.0 * (time.time() - t0)))

    def stop(self):
        self._run = False


def wait_for_game(poll=1.0):
    """Block until PCSX2 is running with a game loaded (PINE up + window present).
    Returns (PineClient, pid, hwnd). Prints a waiting message once, then precise
    one-time hints for whatever is actually missing (PINE off, window untrackable),
    and pre-enables PINE in PCSX2's config while PCSX2 isn't running yet.

    pid may be None (e.g. sandboxed builds can't see host processes); the memory
    reader then falls back to PINE-only reads, so it doesn't block readiness."""
    import pcsx2cfg
    announced = False
    said = set()

    def say(key, msg):
        if key not in said:
            said.add(key)
            print(msg, flush=True)

    misses = 0
    while True:
        pid = memscan.find_pcsx2_pid()
        hwnd = winutil.find_pcsx2_window()
        pine_ok = False
        pc = None
        try:
            pc = pine.PineClient(timeout=1.0).connect()
            pine_ok = True
            if hwnd and pc.title() and pc.game_id():
                return pc, pid, hwnd
        except Exception:
            pass
        if pc is not None:
            pc.close()

        if not announced:
            print("Waiting for game to launch...", flush=True)
            announced = True

        if not (pid or hwnd or pine_ok):
            # PCSX2 isn't running: the safe moment to fix its config so the PINE
            # server (the overlay's data channel) is on when it starts
            fixed = pcsx2cfg.enable_pine()
            if fixed:
                say("pine_fixed", f"note: enabled PCSX2's PINE server in {fixed} "
                                  "(the overlay needs it; PCSX2 had it off).")
        else:
            misses += 1
            if misses >= 5:                 # persistent, not a startup race
                if not pine_ok:
                    _, enabled, _ = pcsx2cfg.pine_state()
                    if enabled is False:
                        say("pine_off", pcsx2cfg.PINE_HINT)
                    else:
                        say("pine_down", "PCSX2 found, but its PINE server is not "
                                         "answering yet (it appears once the emulator "
                                         "is fully started).")
                elif not hwnd and sys.platform != "win32":
                    say("no_window",
                        "PCSX2 is running but its window cannot be located.\n"
                        "On Wayland the overlay tracks it automatically on KDE, "
                        "Hyprland and Sway; on other\ncompositors start PCSX2 as an "
                        "X11 client:    QT_QPA_PLATFORM=xcb pcsx2-qt")
        time.sleep(poll)


def main():
    global LEVEL
    import procname
    procname.set_name(procname.OVERLAY)     # `pkill -x gow_overlay` / Stop button
    import applog
    applog.start("overlay " + (" ".join(sys.argv[1:]) or "normal"))
    LEVEL = parse_level(sys.argv)
    cfg.load()
    pc, pid, hwnd = wait_for_game()
    if LEVEL >= NORMAL:
        print("connected:", pc.title(), pc.game_id())

    rpm = memscan.open_reader(pid, pc)      # direct reads, or PINE-only fallback
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
                # only follow plausible positions: a torn position read (or a
                # camera cut mid-frame) must not drag the number off the window
                if s and (-MARGIN <= s[0] <= overlay_mod.CALIB_W + MARGIN
                          and -MARGIN <= s[1] <= overlay_mod.CALIB_H + MARGIN):
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
