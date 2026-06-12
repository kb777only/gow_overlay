"""build.py - package the overlay into a single double-click executable.

    python build.py

Produces  release/GoW-Damage-Overlay.exe  on Windows or  release/GoW-Damage-Overlay
on Linux (one file; bundles Python, numpy, Pillow, tkinter and the read-only
calibration data). settings.json is created next to the executable on first run
so players can keep/edit their tweaks. Build on the OS you are targeting -
PyInstaller does not cross-compile.

Requires PyInstaller:  python -m pip install pyinstaller
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(ROOT, "app")
NAME = "GoW-Damage-Overlay"
SEP = os.pathsep   # ';' on Windows, ':' elsewhere

MODULES = ["gow_overlay", "overlay", "liveproj", "enemy", "memscan", "pine",
           "winutil", "winshot", "emu", "config", "settings", "setup_gui"]
if sys.platform == "win32":
    MODULES += ["winutil_win32", "overlay_win32"]
else:
    MODULES += ["winutil_x11", "overlay_x11"]

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

ext = ".exe" if sys.platform == "win32" else ""
readme = os.path.join(ROOT, "release", "README.txt")
with open(readme, "w", encoding="utf-8") as f:
    f.write(
        "God of War (PCSX2) - live damage-number overlay\n"
        "================================================\n\n"
        "1. Launch PCSX2 with PINE enabled (PCSX2 Settings > Advanced > Enable PINE) and\n"
        "   start God of War (SCES-53133, PAL).\n"
        "2. Run GoW-Damage-Overlay%s and pick how to run it.\n"
        "   You can start it before the game - it waits.\n\n"
        "Damage numbers pop over enemies as you hit them. Use 'Settings' to tweak\n"
        "colours, size, screenshake, etc. Your tweaks are saved in settings.json\n"
        "next to this executable.\n" % ext)
    if sys.platform != "win32":
        f.write(
            "\nLinux notes\n"
            "-----------\n"
            "* Wayland sessions: start PCSX2 as an X11 client so the overlay can track\n"
            "  its window:  QT_QPA_PLATFORM=xcb pcsx2-qt\n"
            "* For the fast memory-scan path, allow same-user process reads:\n"
            "  sudo sysctl kernel.yama.ptrace_scope=0   (otherwise a slower PINE-only\n"
            "  fallback is used automatically).\n")
print("\nDone -> release/%s%s" % (NAME, ext))
