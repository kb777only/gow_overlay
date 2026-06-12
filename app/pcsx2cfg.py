"""
pcsx2cfg.py - find PCSX2's own PCSX2.ini and make sure the PINE server (the
overlay's data channel) is enabled, so users never have to dig through PCSX2's
settings. PCSX2 updates/reinstalls reset EnablePINE to false, which used to
strand the overlay on "Waiting for game" with no explanation.

Editing the ini only sticks while PCSX2 is NOT running (PCSX2 rewrites it from
memory on exit), so callers must check that before calling enable_pine(); for a
running PCSX2 the only fix is the settings UI, see PINE_HINT.
"""
import os
import re
import sys

DEFAULT_SLOT = 28011

PINE_HINT = ("PCSX2 is running but its PINE server is off, so the overlay cannot "
             "see the game.\nEnable it in PCSX2:  Settings > Advanced > PINE > "
             "'Enable' (slot 28011) - it applies\nimmediately, no restart needed.")


def candidate_inis():
    home = os.path.expanduser("~")
    if sys.platform == "win32":
        return [os.path.join(home, "Documents", "PCSX2", "inis", "PCSX2.ini")]
    return [
        os.path.join(home, ".config", "PCSX2", "inis", "PCSX2.ini"),
        # flatpak PCSX2
        os.path.join(home, ".var", "app", "net.pcsx2.PCSX2", "config", "PCSX2", "inis", "PCSX2.ini"),
    ]


def pine_state():
    """(ini_path, enabled, slot) for the first PCSX2.ini found, else (None, None, None).
    A missing EnablePINE key means disabled (PCSX2's default)."""
    for path in candidate_inis():
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                txt = f.read()
        except OSError:
            continue
        en = re.search(r"^EnablePINE\s*=\s*(\S+)", txt, re.M)
        slot = re.search(r"^PINESlot\s*=\s*(\d+)", txt, re.M)
        return (path, bool(en) and en.group(1).lower() == "true",
                int(slot.group(1)) if slot else DEFAULT_SLOT)
    return None, None, None


def enable_pine():
    """Flip EnablePINE = true in PCSX2.ini. Only call while PCSX2 is not
    running. Returns the ini path if a change was written, else None."""
    path, enabled, _slot = pine_state()
    if path is None or enabled:
        return None
    with open(path, encoding="utf-8", errors="replace") as f:
        txt = f.read()
    if re.search(r"^EnablePINE\s*=", txt, re.M):
        txt = re.sub(r"^EnablePINE\s*=.*$", "EnablePINE = true", txt, count=1, flags=re.M)
    elif re.search(r"^\[EmuCore\]\s*$", txt, re.M):    # the section PINE keys live in
        txt = re.sub(r"^\[EmuCore\]\s*$", "[EmuCore]\nEnablePINE = true",
                     txt, count=1, flags=re.M)
    else:
        txt += "\n[EmuCore]\nEnablePINE = true\n"
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(txt)
    os.replace(tmp, path)
    return path


if __name__ == "__main__":
    print("ini, enabled, slot:", pine_state())
