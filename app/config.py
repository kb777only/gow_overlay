"""config.py - persist discovered God of War addresses/offsets to JSON so the
overlay app can load them without re-running discovery."""
import json
import os

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gow_addrs.json")

DEFAULTS = {
    "game_id": "SCES-53133",
    # filled in by discovery:
    "kratos_health": None,        # ps2 addr of Kratos current-health float
    "kratos_health_max": None,
    "kratos_pos": None,           # ps2 addr of Kratos world position vec (x,y,z floats)
    "actor_stride": None,         # bytes between actor structs (if table found)
    "actor_table": None,          # ps2 addr / pointer of actor array
    "actor_off_health": None,     # offset of health within an actor struct
    "actor_off_pos": None,        # offset of position vec within an actor struct
    "camera_matrix": None,        # ps2 addr of world->screen 4x4 matrix
    "camera_convention": None,    # how to read/apply the matrix
    "notes": {},
}


def load():
    d = dict(DEFAULTS)
    if os.path.exists(PATH):
        try:
            with open(PATH, "r") as f:
                d.update(json.load(f))
        except (json.JSONDecodeError, ValueError):
            pass   # corrupt file -> fall back to defaults
    return d


def _jsonable(v):
    try:
        import numpy as np
        if isinstance(v, np.integer):
            return int(v)
        if isinstance(v, np.floating):
            return float(v)
        if isinstance(v, np.ndarray):
            return v.tolist()
    except ImportError:
        pass
    return v


def save(d):
    clean = {k: _jsonable(v) for k, v in d.items()}
    with open(PATH, "w") as f:
        json.dump(clean, f, indent=2)
    return PATH


def update(**kw):
    d = load()
    d.update(kw)
    save(d)
    return d


if __name__ == "__main__":
    print(json.dumps(load(), indent=2))
