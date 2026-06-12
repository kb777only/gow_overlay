![Icon Name](assets/gow_overlay.ico)
# God of War – Damage Overlay for PCSX2

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Live damage numbers that follow enemies – just like a modern action RPG.**  
A transparent, always‑on‑top overlay for the PS2 classic *God of War* (emulated via PCSX2).  
When you hit an enemy, a fiery damage number pops up above them, scales with the damage, floats upward, and fades out – exactly where the enemy is on screen, even if the camera moves.

### Demo with lowered EpicFX thresholds for demonstration:
  (configurable by clicking Setup in the Launcher)
  
![Demo](assets/demo.gif)


## 🚀 What's New in v0.6.0 (Performance):

### 🐎 The overlay now stays out of the emulator's way, even on slow machines:

- **Idle renderer**: with no numbers on screen (most of the time!), the overlay used to push a full transparent frame to the display server 60×/second. It now draws *nothing* until a hit lands – near-zero CPU, display-server and compositor load while you play.
- **Dirty-rectangle rendering**: while numbers are on screen, only the small region around them is composited and uploaded instead of the whole window (~5× less CPU).
- **Lighter memory scans**: enemy discovery over PINE uses 64-bit reads (40% less emulator-side CPU per scan), paces itself to a ≤25% duty cycle however slow the machine, and skips scanning entirely while the game is paused.
- **Big-hit edge flash** (the one full-frame effect) renders at half rate during its 0.4 s burst – visually identical, half the cost.

See the new [Performance](#-performance) section for measured numbers and tuning tips.

## What's New in v0.5.0 (Full Wayland Support):

### 🌊 Native Wayland support – no setup needed: the overlay now tracks PCSX2 even when it runs as a native Wayland client. The game window is located through the compositor itself (KDE/KWin, Hyprland and Sway), so `QT_QPA_PLATFORM=xcb` is no longer required.

### 🔌 PINE auto-setup: PCSX2 updates silently turn its PINE server off, which used to leave the overlay waiting forever. The overlay now switches PINE on in PCSX2's config for you (when PCSX2 isn't running), and tells you exactly what to click if it is.

### 🩺 Clear status messages: "Waiting for game" now diagnoses precisely what's missing – PCSX2 not started, PINE off, game not loaded, or window not trackable.

### 📦 Linux packages: prebuilt **AppImage** and **Flatpak** builds (see below), plus the existing one-file binary build.

### 🐛 Fixed "0 enemies" on Linux: with the PINE-only fallback (the default on most distros), the enemy scanner and the render loop raced on the single PINE socket and corrupted each other's replies, so no enemies were ever tracked and `--simulate` showed nothing. PINE transactions are now serialized and self-heal on errors.

### 🐛 Fixes: `diag.py` crashed with a `KeyError` and used an outdated player heuristic; it now mirrors the live tracker exactly. Persistent enemy-scan failures are now reported instead of silently swallowed.


## Features

- 🎯 **Attached to enemies** – numbers follow moving targets smoothly.  
- 📷 **World-Space Projection Engine** – GoW projects objects individually (a PS2 VU quirk), it lacks a standard global camera matrix. This uses a custom projection model calibrated through multi‑frame triangulation (matching actor world-coords to screen pixels) to pin numbers in 3D space through any pan, rotate, or zoom.  
- 💥 **Epic hit feedback** – screenshake, warm edge flash, expanding shockwave ring, and a white‑hot pop for big damage.  
- 🎨 **Fully customisable** – colours, size, lifetime, tracking behaviour, and all visual effects are tweakable **live** via a GUI settings window (or by editing `settings.json`).  
- 🐎 **Low performance impact** – the renderer goes fully idle when no numbers are on screen and only touches the pixels around them when there are (dirty rectangles); enemy scanning is vectorised (numpy), runs on a background thread, and paces itself so the emulator always keeps its CPU. See [Performance](#-performance).  
- 🎮 **No game modification required** – reads memory via PINE (PCSX2’s built‑in debug interface) and direct process reads (`ReadProcessMemory` / `process_vm_readv`). Works with the original game ISO, any save state, and persists across level reloads.  
- 🐧 **Cross‑platform** – Windows and Linux (X11 **and Wayland**), same features on both.  
- 📦 **Easy to run** – one‑file executable, AppImage, or Flatpak. Pick a mode in the launcher and play.  

## 🖥️ Requirements

- **Windows** (7 / 10 / 11) **or Linux** (X11 or Wayland session – see [Linux notes](#-linux-notes)).  
- **PCSX2** (v1.7+ recommended) – the overlay uses the **PINE** IPC server (TCP port `28011` on Windows, a Unix socket on Linux).  
  - The overlay **enables PINE for you** in PCSX2's config when PCSX2 isn't running. If PCSX2 is already running with PINE off, it tells you where to click (`Settings > Advanced > PINE > Enable`).  
- **God of War** (SCES‑53133 / SCUS‑97399 / any region with the same actor struct layout – tested on European PAL `SCES-53133`).  
- **Python 3.8+** (only if running from source) – see [Running from Source](#-running-from-source-python).

## 🚀 Quick Start

**Windows:**
1. **Download** the latest `gow_overlay.zip` from [Releases](https://github.com/kb777only/gow_overlay/releases) and extract anywhere.  
2. **Launch** `launcher.exe`.

**Linux:** download from [Releases](https://github.com/kb777only/gow_overlay/releases) either the
- **AppImage** – `chmod +x GoW-Damage-Overlay-*.AppImage` and run it, or the  
- **Flatpak** – `flatpak install --user GoW-Damage-Overlay-*.flatpak`, then launch *GoW Damage Overlay* from your app menu.

Then:
1. **That's it.** It automatically detects GoW and gets to work, or waits for you to start the game.  
2. In the launcher window, choose:  
   - **Normal** – overlay + terminal with basic logs.  
   - **Verbose** – overlay + terminal with all debug data.  
   - **Damage log** – overlay + terminal showing only damage numbers.  
   - **Silent (background)** – overlay only, no terminal window.  
3. Click **Start Overlay**.  

Damage numbers will now appear over enemies whenever you hurt them.  
To adjust colours, size, or effect strength, click **Settings** in the launcher while the overlay is running – changes apply instantly.

> 💡 The overlay waits for the game to launch. You can start it before PCSX2 – it will automatically connect once the game is running, or automatically detect it if the game is already running (can be started/stopped freely during active gameplay).

## 🔧 Running from Source (Python)

If you prefer to run the Python scripts directly (e.g., for development or customisation):

```bash
git clone https://github.com/kb777only/gow_overlay.git
cd gow_overlay
pip install -r requirements.txt   # numpy, pillow (tkinter from your OS / distro)
python ./app/launcher.py
```

## 📦 Building the packages

```bash
python build.py            # one-file executable -> release/GoW-Damage-Overlay[.exe]
python build.py appimage   # Linux AppImage     -> release/GoW-Damage-Overlay-<v>-x86_64.AppImage
python build.py flatpak    # Flatpak bundle     -> release/GoW-Damage-Overlay-<v>.flatpak
```

The binary/AppImage builds need PyInstaller (`pip install pyinstaller`); the AppImage build fetches `appimagetool` automatically on first use. The flatpak build needs `flatpak` with the Flathub remote and builds everything else itself (manifest in `packaging/flatpak/`).

## ⚡ Performance

All figures below were measured on an **Intel Core i3-3240** (2 cores / 4 threads, 3.4 GHz, Ivy Bridge 2012, 8 GB RAM) – extremely low-end hardware by today's standards, and deliberately so: it's representative of the machines retro games actually get played on. On anything newer the overlay's footprint shrinks accordingly.

The overlay is built so the emulator never has to share its CPU with it in any meaningful way:

- **Waiting / no numbers on screen** (most of gameplay): the renderer skips work entirely – **~1% of one core**, zero display-server traffic, zero compositor load.
- **Numbers on screen**: only the rectangle around the numbers is composited and uploaded – **~14% of one core** while numbers float (at a 1060×663 window; scales with window size).
- **Big-hit feedback** (screenshake + edge flash, ~0.4 s burst): the edge flash is inherently full-frame, so those frames run at 30 fps instead of 60 – **~50% of one core** for the burst duration.
- **Enemy scanning**: with direct process reads (Windows, or Linux with `ptrace_scope=0`) a full scan takes ~0.1 s and costs the emulator nothing. Over the PINE fallback the scan makes PCSX2's PINE thread work, so it is paced to a **≤25% duty cycle** (the slower the machine, the more it backs off), costs PCSX2 itself only a few percent of one core, and is **skipped entirely while the game is paused**.

**If your machine is really struggling**, in order of effect:

1. **Linux**: allow direct memory reads – `sudo sysctl kernel.yama.ptrace_scope=0` – which takes PCSX2's PINE thread out of the scan path completely (the AppImage/binary builds use it automatically; the Flatpak cannot).
2. Open **Settings** and disable **edge flash** and **white-hot pop** (the only effects that ever touch the full frame); the screenshake and shockwave ring are cheap.
3. Increase `tracking.scan_period` in `settings.json` (e.g. to `1.0`) – enemies are discovered a little later after spawning, everything else is unaffected.

## 🐧 Linux notes

Linux is fully supported, on both X11 and Wayland sessions.

**The overlay window** is an ARGB X11 client (the X equivalent of Windows' layered windows), shown through XWayland on Wayland – compositors stack it above native Wayland windows, so this works everywhere. A **compositing** desktop (KDE, GNOME, anything modern) is required for the transparency; bare WMs need a compositor like `picom`.

**Finding the game window:**

- **X11 sessions** – work out of the box.
- **Wayland sessions** – the game window is tracked through the compositor, automatically:
  - **KDE Plasma (KWin)** – via the KWin scripting API (needs `gdbus` and `journalctl`, present on any KDE system).
  - **Hyprland / Sway** – via their IPC sockets.
  - **Other compositors (e.g. GNOME)** – no window-tracking interface exists; start PCSX2 as an X11 client instead and everything works as on X11:

    ```bash
    QT_QPA_PLATFORM=xcb pcsx2-qt
    ```

**PINE on Linux** is a Unix socket at `$XDG_RUNTIME_DIR/pcsx2.sock` (flatpak PCSX2: `$XDG_RUNTIME_DIR/app/net.pcsx2.PCSX2/pcsx2.sock`) – both are found automatically, and the overlay enables the PINE server in PCSX2's settings for you.

**Memory reading.** The fast scan path reads PCSX2's memory directly with `process_vm_readv`. Most distros restrict this by default (`kernel.yama.ptrace_scope = 1`); allow it with:

```bash
sudo sysctl kernel.yama.ptrace_scope=0    # or persist it in /etc/sysctl.d/
```

If it stays restricted the overlay automatically falls back to PINE‑only reads – everything still works, enemies are just discovered a little more slowly after spawning. The **Flatpak build always uses the PINE‑only fallback** (a sandbox can't read other processes' memory directly).
