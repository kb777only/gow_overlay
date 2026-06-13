"""build.py - package the overlay for distribution.

    python build.py             one-file executable (release/GoW-Damage-Overlay[.exe])
    python build.py appimage    Linux: the executable wrapped as an AppImage
    python build.py flatpak     Linux: a flatpak bundle (needs flatpak + flathub)

The one-file build bundles Python, numpy, Pillow, tkinter and the read-only
calibration data; settings.json is created next to the executable (or in
~/.config/gow_overlay when the install dir is read-only) so players can keep
their tweaks. Build on the OS you are targeting - PyInstaller does not
cross-compile.

Requires PyInstaller:  python -m pip install pyinstaller
The AppImage build fetches appimagetool on first use; the flatpak build uses
org.flatpak.Builder (installed on demand via `flatpak install`).
"""
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(ROOT, "app")
RELEASE = os.path.join(ROOT, "release")
BUILDDIR = os.path.join(ROOT, "build")
NAME = "GoW-Damage-Overlay"
SEP = os.pathsep   # ';' on Windows, ':' elsewhere

with open(os.path.join(APP, "appinfo.json")) as f:
    VERSION = str(json.load(f)["version"])

MODULES = ["gow_overlay", "overlay", "liveproj", "enemy", "memscan", "pine",
           "winutil", "winshot", "emu", "config", "settings", "setup_gui",
           "pcsx2cfg", "applog", "respath", "procname", "guifont"]
if sys.platform == "win32":
    MODULES += ["winutil_win32", "overlay_win32"]
else:
    MODULES += ["winutil_x11", "winutil_wayland", "overlay_x11"]


def build_binary():
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
            "--onefile", "--console", "--name", NAME,
            "--add-data", os.path.join(APP, "camcalib.json") + SEP + ".",
            "--add-data", os.path.join(APP, "gow_addrs.json") + SEP + ".",
            "--add-data", os.path.join(APP, "appinfo.json") + SEP + ".",
            "--add-data", os.path.join(ROOT, "assets", "gow_overlay.png") + SEP + ".",
            "--add-data", os.path.join(ROOT, "assets", "gow_overlay.ico") + SEP + ".",
            "--add-data", os.path.join(ROOT, "assets", "GODOFWAR.TTF") + SEP + ".",
            "--distpath", RELEASE,
            "--workpath", BUILDDIR,
            "--specpath", BUILDDIR]
    if sys.platform == "win32":      # taskbar/explorer icon for the .exe itself
        args += ["--icon", os.path.join(ROOT, "assets", "gow_overlay.ico")]
    for m in MODULES:
        args += ["--hidden-import", m]
    args.append("launcher.py")
    print(">>", " ".join(args))
    subprocess.run(args, cwd=APP, check=True)
    write_release_readme()
    ext = ".exe" if sys.platform == "win32" else ""
    print("\nDone -> release/%s%s" % (NAME, ext))


def write_release_readme():
    with open(os.path.join(RELEASE, "README.txt"), "w", encoding="utf-8") as f:
        f.write(
            "God of War (PCSX2) - live damage-number overlay v%s\n"
            "================================================\n\n"
            "1. Start God of War (SCES-53133 PAL or SCUS-97399 US/NTSC) in PCSX2.\n"
            "2. Run the overlay and pick how to run it. You can also start it before\n"
            "   the game - it waits, and it switches PCSX2's PINE server on for you\n"
            "   (the data channel the overlay reads the game through).\n\n"
            "Damage numbers pop over enemies as you hit them. Use 'Settings' to tweak\n"
            "colours, size, screenshake, etc. Your tweaks are saved in settings.json\n"
            "next to the executable (or ~/.config/gow_overlay for AppImage/flatpak).\n"
            % VERSION)
        if sys.platform != "win32":
            f.write(
                "\nLinux notes\n"
                "-----------\n"
                "* Works on X11 and Wayland. On Wayland the game window is tracked\n"
                "  automatically on KDE, Hyprland and Sway; on other compositors start\n"
                "  PCSX2 as an X11 client:  QT_QPA_PLATFORM=xcb pcsx2-qt\n"
                "* For the fast memory-scan path, allow same-user process reads:\n"
                "  sudo sysctl kernel.yama.ptrace_scope=0   (otherwise a slower\n"
                "  PINE-only fallback is used automatically).\n")


def make_icon_png(dest, size=256):
    """Render assets/gow_overlay.ico to a PNG (AppImage/flatpak want PNG icons)."""
    from PIL import Image
    img = Image.open(os.path.join(ROOT, "assets", "gow_overlay.ico"))
    img = img.convert("RGBA").resize((size, size), Image.LANCZOS)
    img.save(dest)


def fetch_appimagetool():
    cached = os.path.join(BUILDDIR, "appimagetool-x86_64.AppImage")
    found = shutil.which("appimagetool")
    if found:
        return [found]
    if not os.path.exists(cached):
        os.makedirs(BUILDDIR, exist_ok=True)
        url = ("https://github.com/AppImage/appimagetool/releases/download/"
               "continuous/appimagetool-x86_64.AppImage")
        print(">> downloading", url)
        subprocess.run(["curl", "-fL", "-o", cached, url], check=True)
        os.chmod(cached, 0o755)
    # --appimage-extract-and-run avoids needing FUSE on the build machine
    return [cached, "--appimage-extract-and-run"]


def build_appimage():
    if sys.platform == "win32":
        sys.exit("AppImages are Linux-only")
    build_binary()
    appdir = os.path.join(BUILDDIR, "AppDir")
    shutil.rmtree(appdir, ignore_errors=True)
    os.makedirs(os.path.join(appdir, "usr", "bin"))
    shutil.copy2(os.path.join(RELEASE, NAME), os.path.join(appdir, "usr", "bin", NAME))
    make_icon_png(os.path.join(appdir, "gow_overlay.png"))
    with open(os.path.join(appdir, "gow-overlay.desktop"), "w") as f:
        f.write("[Desktop Entry]\nType=Application\nName=GoW Damage Overlay\n"
                "Comment=Live damage numbers over God of War (PCSX2)\n"
                f"Exec={NAME}\nIcon=gow_overlay\nCategories=Game;Emulator;\n"
                "Terminal=false\n")
    with open(os.path.join(appdir, "AppRun"), "w") as f:
        f.write('#!/bin/sh\nexec "$(dirname "$0")/usr/bin/%s" "$@"\n' % NAME)
    os.chmod(os.path.join(appdir, "AppRun"), 0o755)

    out = os.path.join(RELEASE, f"{NAME}-{VERSION}-x86_64.AppImage")
    env = dict(os.environ, ARCH="x86_64")
    subprocess.run(fetch_appimagetool() + [appdir, out], check=True, env=env)
    print("\nDone ->", os.path.relpath(out, ROOT))


def build_flatpak():
    if sys.platform == "win32":
        sys.exit("flatpaks are Linux-only")
    manifest = os.path.join(ROOT, "packaging", "flatpak",
                            "io.github.kb777only.gow_overlay.yml")
    appid = "io.github.kb777only.gow_overlay"
    state = os.path.join(BUILDDIR, "flatpak-state")
    repo = os.path.join(BUILDDIR, "flatpak-repo")
    fpdir = os.path.join(BUILDDIR, "flatpak-build")
    builder = (["flatpak-builder"] if shutil.which("flatpak-builder")
               else ["flatpak", "run", "org.flatpak.Builder"])
    if builder[0] != "flatpak-builder":
        subprocess.run(["flatpak", "install", "--user", "-y", "--noninteractive",
                        "flathub", "org.flatpak.Builder"], check=True)
    subprocess.run(builder + ["--force-clean", "--user",
                              "--install-deps-from=flathub",
                              "--state-dir", state, "--repo", repo,
                              fpdir, manifest], check=True, cwd=ROOT)
    out = os.path.join(RELEASE, f"{NAME}-{VERSION}.flatpak")
    os.makedirs(RELEASE, exist_ok=True)
    subprocess.run(["flatpak", "build-bundle", repo, out, appid], check=True)
    print("\nDone ->", os.path.relpath(out, ROOT))
    print("install with:  flatpak install --user", os.path.relpath(out, ROOT))


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "binary"
    {"binary": build_binary,
     "appimage": build_appimage,
     "flatpak": build_flatpak}[mode]()
