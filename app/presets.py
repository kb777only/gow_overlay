"""presets.py - bundled and user visual presets for the overlay.

Bundled presets ship in assets/presets/*.json (read-only). User-imported
presets are copied into a writable 'presets' folder next to settings.json, so
they persist and show up in the Settings dropdown on every launch. A preset is
just a settings file (full or partial - it's merged over the defaults), named
by its filename.
"""
import glob
import json
import os
import shutil

import respath
from settings import S, DEFAULTS

DEFAULT_LABEL = "Default (balanced)"


def user_dir():
    # NOT named "presets": that would land next to the modules and shadow the
    # bundled assets/presets in respath.asset_path (which checks the module dir
    # before ../assets). Keep it distinct so both are always found.
    d = os.path.join(os.path.dirname(S.path), "user_presets")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


def _bundled_dir():
    return respath.asset_path("presets")


def _is_preset(path):
    try:
        with open(path) as f:
            d = json.load(f)
        return isinstance(d, dict) and bool(d.keys() & DEFAULTS.keys())
    except Exception:
        return False


def list_presets():
    """Ordered dict {display_name: path}: the built-ins first, then the user's.
    A user preset with the same name as a built-in overrides it."""
    out = {}
    bd = _bundled_dir()
    if bd and os.path.isdir(bd):
        for p in sorted(glob.glob(os.path.join(bd, "*.json"))):
            out[os.path.splitext(os.path.basename(p))[0]] = p
    for p in sorted(glob.glob(os.path.join(user_dir(), "*.json"))):
        out[os.path.splitext(os.path.basename(p))[0]] = p
    return out


def names():
    """Dropdown entries: the default reset, then every preset."""
    return [DEFAULT_LABEL] + list(list_presets().keys())


def apply(label):
    """Apply a dropdown entry by name. Returns True if it changed settings."""
    if label == DEFAULT_LABEL:
        S.reset()
        return True
    path = list_presets().get(label)
    if not path:
        return False
    S.import_from(path)
    return True


def import_file(src):
    """Validate `src`, copy it into the user presets folder so it joins the
    dropdown permanently, and return its display name."""
    if not _is_preset(src):
        raise ValueError("not a GoW-overlay settings/preset file")
    name = os.path.splitext(os.path.basename(src))[0]
    shutil.copyfile(src, os.path.join(user_dir(), name + ".json"))
    return name
