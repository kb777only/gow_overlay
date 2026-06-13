"""settings.py - user-tunable overlay settings, persisted to settings.json with
live reload. Edit via `python gow_overlay.py --setup` (a GUI) or by hand; a running
overlay picks up changes within a frame."""
import copy
import json
import math
import os
import sys


def _settings_path():
    # keep settings.json next to the executable (frozen) / this module (source)
    # so it persists and the user can edit it. If that directory is read-only
    # (AppImage mount, flatpak, /usr install), fall back to the per-user
    # config dir instead.
    d = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
         else os.path.dirname(os.path.abspath(__file__)))
    if os.access(d, os.W_OK):
        return os.path.join(d, "settings.json")
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    d = os.path.join(base, "gow_overlay")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return os.path.join(d, "settings.json")


_PATH = _settings_path()

DEFAULTS = {
    "numbers": {
        "size_base": 22,          # font size for a minimal (1-damage) hit
        "size_per_damage": 5.0,   # px added per DOUBLING of damage (log growth)
        "size_cap_damage": 4096,  # damage past which numbers stop growing
        "ttl": 1.45,              # seconds a number stays on screen
        "rise": 48.0,             # px it floats upward over its life
        "anchor_lerp": 0.28,      # tracking smoothing (0 = frozen, 1 = snap)
        "head_offset": 42,        # px above the enemy's projected point
        "fade_start": 0.5,        # fraction of life before the fade-out begins
        "pop": 0.42,              # scale-punch strength on spawn
        "max_damage": 9999        # ignore bigger deltas (garbage from off-screen deaths)
    },
    "colors": [                   # damage -> colour ramp (ascending thresholds, spans the game)
        [25, [232, 58, 34]],
        [80, [255, 96, 28]],
        [200, [255, 138, 32]],
        [600, [255, 178, 48]],
        [100000, [255, 214, 92]]
    ],
    "epic": {
        "min_damage": 40,         # hits past this start triggering impact FX
        "full_damage": 1200,      # ... and reach full intensity here (geometric ramp)
        "shake_enabled": True,
        "shake_amount": 1.0,      # multiplier on the screenshake
        "flash_enabled": True,
        "flash_amount": 1.0,      # multiplier on the warm edge-flash
        "ring_enabled": True,     # expanding shockwave ring
        "whitehot_enabled": True, # white flash on spawn for big hits
        "extra_pop": 0.55,        # extra scale-punch for big hits
        "extra_ttl": 0.35         # big hits linger this much longer (fraction)
    },
    "anim": {
        "gradient_enabled": True,  # molten vertical gradient inside the digits
        "shimmer_enabled": True,   # ...that slowly shifts, like heat shimmer
        "shimmer_speed": 1.0,      # shimmer cycles per second
        "fire_enabled": True,      # flame licks rising off big-hit numbers
        "fire_amount": 1.0,        # flame height/intensity multiplier
        "sparks_enabled": True,    # ember burst on big hits
        "sparks_amount": 1.0,      # multiplier on ember count
        "fireball_enabled": True   # expanding fireball at the impact point
    },
    "tracking": {
        "scan_period": 0.3,       # how often actors are re-enumerated (s)
        "near_player_dist": 700,  # only enemies within this of Kratos (world units)
        "creature_min_hp": 6,     # signature scan: min plausible max-health
        "creature_max_hp": 1000   # signature scan: max plausible max-health (covers bosses)
    }
}


def _deepmerge(base, over):
    out = copy.deepcopy(base)
    if isinstance(over, dict):
        for k, v in over.items():
            if k in out and isinstance(out[k], dict) and isinstance(v, dict):
                out[k] = _deepmerge(out[k], v)
            else:
                out[k] = copy.deepcopy(v)
    return out


class Settings:
    def __init__(self):
        self.data = copy.deepcopy(DEFAULTS)
        self._mtime = -1.0
        self.reload(force=True)
        if not os.path.exists(_PATH):
            self.save()           # materialise defaults so the file exists to edit

    def reload(self, force=False):
        try:
            m = os.path.getmtime(_PATH)
        except OSError:
            m = 0.0
        if not force and m == self._mtime:
            return False
        self._mtime = m
        loaded = {}
        if os.path.exists(_PATH):
            try:
                with open(_PATH) as f:
                    loaded = json.load(f)
            except Exception:
                loaded = {}
        self.data = _deepmerge(DEFAULTS, loaded)
        return True

    def maybe_reload(self):
        return self.reload(force=False)

    def __getitem__(self, k):
        return self.data[k]

    def save(self):
        tmp = _PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.data, f, indent=2)
        os.replace(tmp, _PATH)
        try:
            self._mtime = os.path.getmtime(_PATH)
        except OSError:
            pass

    def reset(self):
        self.data = copy.deepcopy(DEFAULTS)
        self.save()

    # -- preset sharing ------------------------------------------------------
    def export_to(self, path):
        """Write the current settings to `path` (a shareable preset file)."""
        with open(path, "w") as f:
            json.dump(self.data, f, indent=2)

    def import_from(self, path):
        """Load a preset file and make it the active settings. The preset is
        merged over the defaults, so files from older/newer versions work -
        missing keys keep their defaults."""
        with open(path) as f:
            loaded = json.load(f)
        if not isinstance(loaded, dict) or not (loaded.keys() & DEFAULTS.keys()):
            raise ValueError("not a GoW-overlay settings file")
        self.data = _deepmerge(DEFAULTS, loaded)
        self.save()

    @property
    def path(self):
        return _PATH


S = Settings()


# --- helpers the overlay/app use (read live from S) ---
def dmg_color(dmg):
    for mx, rgb in S["colors"]:
        if dmg < mx:
            return (int(rgb[0]), int(rgb[1]), int(rgb[2]))
    last = S["colors"][-1][1]
    return (int(last[0]), int(last[1]), int(last[2]))


def dmg_size(dmg):
    """Number size grows LOGARITHMICALLY with damage so it reads well across the
    whole game - a 2000 looks bigger than a 200 looks bigger than a 20, yet no
    single hit becomes absurd. `size_per_damage` is px added per doubling of
    damage; growth stops at `size_cap_damage`."""
    n = S["numbers"]
    d = max(1.0, float(dmg))
    cap = max(2.0, float(n["size_cap_damage"]))
    grow = float(n["size_per_damage"]) * math.log2(min(d, cap))
    return int(round(n["size_base"] + grow))


def impact_strength(dmg):
    """Epic-FX intensity (0..1) ramps GEOMETRICALLY from min_damage to
    full_damage, so the ramp spans the entire damage range. Combined with the
    fact that your hits get bigger as you progress, epic FX naturally appear
    more often and more strongly the further you get."""
    e = S["epic"]
    lo = max(1.0, float(e["min_damage"]))
    hi = float(e["full_damage"])
    if dmg <= lo:
        return 0.0
    if hi <= lo:
        return 1.0
    return max(0.0, min(1.0, math.log(dmg / lo) / math.log(hi / lo)))
