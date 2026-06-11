"""build.py - package the overlay into a single double-click .exe (release build).

    python build.py

Produces  release/GoW-Damage-Overlay.exe  (one file; bundles Python, numpy, Pillow,
tkinter and the read-only calibration data). settings.json is created next to the
exe on first run so players can keep/edit their tweaks.

Requires PyInstaller:  python -m pip install pyinstaller
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(ROOT, "app")
NAME = "GoW-Damage-Overlay"
SEP = os.pathsep   # ';' on Windows

MODULES = ["gow_overlay", "overlay", "liveproj", "enemy", "memscan", "pine",
           "winutil", "winshot", "emu", "config", "settings", "setup_gui", "_linux_support_wip_tools"]

args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--onefile", "--console", "--name", NAME,
        "--add-data", os.path.join(APP, "camcalib.json") + SEP + ".",
        "--add-data", os.path.join(APP, "gow_addrs.json") + SEP + ".",
        "--distpath", os.path.join(ROOT, "release"),
        "--workpath", os.path.join(ROOT, "build"),
        "--specpath", os.path.join(ROOT, "build")]
for m in MODULES:
    args += ["--hidden-import", m]
args.append("launcher.py")

print(">>", " ".join(args))
subprocess.run(args, cwd=APP, check=True)

readme = os.path.join(ROOT, "release", "README.txt")
with open(readme, "w", encoding="utf-8") as f:
    f.write(
        "God of War (PCSX2) - live damage-number overlay\n"
        "================================================\n\n"
        "1. Launch PCSX2 with PINE enabled (PCSX2 Settings > Advanced > Enable PINE) and\n"
        "   start God of War (SCES-53133, PAL).\n"
        "2. Double-click GoW-Damage-Overlay.exe and pick how to run it.\n"
        "   You can start it before the game - it waits.\n\n"
        "Damage numbers pop over enemies as you hit them. Use 'Settings' to tweak\n"
        "colours, size, screenshake, etc. Your tweaks are saved in settings.json\n"
        "next to this exe.\n")
ext = ".exe" if sys.platform == "win32" else ""
print("\nDone -> release/%s%s" % (NAME, ext))
