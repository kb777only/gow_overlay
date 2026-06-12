# God of War – Damage Overlay for PCSX2
![Icon Name](assets/gow_overlay.ico)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Live damage numbers that follow enemies – just like a modern action RPG.**  
A transparent, always‑on‑top overlay for the PS2 classic *God of War* (emulated via PCSX2).  
When you hit an enemy, a fiery damage number pops up above them, scales with the damage, floats upward, and fades out – exactly where the enemy is on screen, even if the camera moves.

### Demo with lowered EpicFX thresholds for demonstration:
  (configurable by clicking Setup in the Launcher)
  
![Demo](assets/demo.gif)

## 🚀 What's New in v0.6.95

- 🪟 **Fixed the overlay attaching to the wrong window** – window matching was title-based, so the launcher itself (titled "God of War — Damage Overlay" and, since v0.6.5, always open) could be mistaken for the game and collect the damage numbers. Matching is now based on which **process owns the window** (PCSX2's window class / app-id / exe), titles are only a last resort (and ignored entirely on Wayland), and the overlay's own windows – including older versions' – are always excluded. The launcher is now titled "GoW Damage Overlay — Launcher".

Recent releases: **v0.6.9** fixed misplaced damage numbers and added the launcher's ⏹ Stop button, named processes (`gow_overlay` / `gow_overlay-launcher`), and the app icon everywhere; **v0.6.5** added preset sharing, crash logs + one-click bug reports, and a launcher that stays open for live tweaking; **v0.6.0** cut the overlay's overhead to near zero ([Performance](#-performance)); **v0.5.0** added full Wayland support, PINE auto-setup, and the AppImage/Flatpak packages. Full history in [Releases](https://github.com/kb777only/gow_overlay/releases).

## 🗺️ Roadmap

The road to **v1.0.0** is all about spectacle and reach:

- 🔥 **Fire animations on the numbers** – living flames instead of a static glow.
- 🌈 **Animated, colour-shifting numbers** – ramps that move and breathe with the damage.
- 🕹️ **Full, verified Steam Deck support** – tested and tuned on the Deck itself, out of the box.
- ✨ …and more cool stuff not yet planned – ideas welcome in [issues](https://github.com/kb777only/gow_overlay/issues)!

Meanwhile, **performance and stability updates** will keep being released as we go, through minor version updates.

## ✨ Features

- 🎯 **Attached to enemies** – numbers follow moving targets smoothly.  
- 📷 **World-Space Projection Engine** – GoW projects objects individually (a PS2 VU quirk), it lacks a standard global camera matrix. This uses a custom projection model calibrated through multi‑frame triangulation (matching actor world-coords to screen pixels) to pin numbers in 3D space through any pan, rotate, or zoom.  
- 💥 **Epic hit feedback** – screenshake, warm edge flash, expanding shockwave ring, and a white‑hot pop for big damage.  
- 🎨 **Fully customisable** – everything is tweakable **live** via a GUI settings window, and shareable as presets.  
- 🐎 **Low performance impact** – the renderer goes fully idle when nothing is on screen and touches only the pixels around the numbers when there is; scanning paces itself so the emulator always keeps its CPU. See [Performance](#-performance).  
- 🎮 **No game modification required** – reads memory via PINE (PCSX2's built‑in debug interface) and direct process reads. Works with the original ISO, any save state, and persists across level reloads.  
- 🐧 **Cross‑platform** – Windows and Linux (X11 **and Wayland**), same features on both.  

## 🖥️ Requirements

- **Windows 10 / 11** (the prebuilt `.exe` bundles Python 3.12) **or Linux** (X11 or Wayland – see [Linux notes](#-linux-notes)).
- **PCSX2** v1.7+ with its **PINE** server – the overlay switches PINE on in PCSX2's config for you, or tells you exactly where to click if PCSX2 is already running.
- **God of War** – tested on European PAL `SCES-53133`; other regions with the same actor layout should work.

## 🚀 Quick Start

Grab a build from [Releases](https://github.com/kb777only/gow_overlay/releases):

| Platform | File | Run it |
|---|---|---|
| Windows | `gow_overlay-<v>-win64.zip` | extract, double-click `GoW-Damage-Overlay.exe` |
| Linux | `GoW-Damage-Overlay-<v>-x86_64.AppImage` | `chmod +x`, run |
| Linux | `GoW-Damage-Overlay-<v>.flatpak` | `flatpak install --user <file>`, launch from the app menu |

Then:

1. Start the overlay (before or after the game – it waits, and auto-detects a running game).
2. Pick a mode – **Normal** / **Verbose** / **Damage log** (with a log terminal) or **Silent** (overlay only) – and click **Start Overlay**.
3. Play. Damage numbers pop over enemies as you hurt them.

The launcher stays open: click **Settings** any time to tune colours, sizes and effects **live while playing**, or to **Import/Export** a preset. **⏹ Stop** ends the overlay (even a background/Silent one) whenever you're done.

## ⚡ Performance

All figures were measured on an **Intel Core i3-3240** (2 cores / 4 threads, 3.4 GHz, Ivy Bridge 2012, 8 GB RAM) – extremely low-end hardware by today's standards, and deliberately so: it's representative of the machines retro games actually get played on. On anything newer the overlay's footprint shrinks accordingly.

- **Waiting / no numbers on screen** (most of gameplay): the renderer skips work entirely – **~1% of one core**, zero display-server traffic, zero compositor load.
- **Numbers on screen**: only the rectangle around the numbers is composited and uploaded – **~14% of one core** (at a 1060×663 window; scales with window size).
- **Big-hit feedback** (~0.4 s burst): the edge flash is inherently full-frame, so those frames run at 30 fps – **~50% of one core** for the burst.
- **Enemy scanning**: with direct process reads (Windows, or Linux with `ptrace_scope=0`) a full scan takes ~0.1 s and costs the emulator nothing. Over the PINE fallback it is paced to a **≤25% duty cycle**, costs PCSX2 a few percent of one core, and is **skipped while the game is paused**.

**If your machine is really struggling**, in order of effect:

1. **Linux**: `sudo sysctl kernel.yama.ptrace_scope=0` – direct memory reads take PCSX2's PINE thread out of the scan path completely (the Flatpak always uses PINE reads; AppImage/binary benefit automatically).
2. **Settings** → disable **edge flash** and **white-hot pop** (the only full-frame effects).
3. Raise `tracking.scan_period` in `settings.json` (e.g. `1.0`) – enemies are discovered slightly later, nothing else changes.

## 🐧 Linux notes

Works on X11 and Wayland. The overlay is an ARGB X11 window (via XWayland on Wayland – compositors stack it above native Wayland windows); a compositing desktop (KDE, GNOME, anything modern) is required for transparency.

**Finding the game window on Wayland** is automatic on **KDE Plasma** (KWin scripting API), **Hyprland** and **Sway** (IPC). Other compositors (e.g. GNOME) expose no window-tracking interface – start PCSX2 as an X11 client instead:

```bash
QT_QPA_PLATFORM=xcb pcsx2-qt
```

**PINE socket**: `$XDG_RUNTIME_DIR/pcsx2.sock` (flatpak PCSX2: `$XDG_RUNTIME_DIR/app/net.pcsx2.PCSX2/pcsx2.sock`) – both found automatically.

Settings live next to the executable, or in `~/.config/gow_overlay/settings.json` for AppImage/Flatpak installs.

## 🐞 Reporting bugs

Something crashed or misbehaved? Every overlay run is logged automatically – including full tracebacks of crashes – so reporting takes a minute:

1. Open the launcher and click **📋 Copy last log** (the log of the run that just ended/crashed is now on your clipboard).
2. Click **🐞 Report an issue** (or go to [issues](https://github.com/kb777only/gow_overlay/issues)), describe what happened, paste the log.

The log files themselves (`gow_overlay.log`, plus `gow_overlay.prev.log` for the run before) live next to the executable, or in `~/.config/gow_overlay/` for AppImage/Flatpak installs.

## 🛠️ For developers

Run from source (Python 3.8+, `numpy` + `pillow`, tkinter from your distro):

```bash
git clone https://github.com/kb777only/gow_overlay.git
cd gow_overlay
pip install -r requirements.txt
python ./app/launcher.py
```

Build the packages (PyInstaller for binary/AppImage; `flatpak` + Flathub for the flatpak – manifest in `packaging/flatpak/`):

```bash
python build.py            # one-file executable -> release/GoW-Damage-Overlay[.exe]
python build.py appimage   # Linux AppImage
python build.py flatpak    # Flatpak bundle
```
