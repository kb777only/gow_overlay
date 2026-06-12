![Icon Name](assets/gow_overlay.ico)
# God of War – Damage Overlay for PCSX2

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Live damage numbers that follow enemies – just like a modern action RPG.**  
A transparent, always‑on‑top overlay for the PS2 classic *God of War* (emulated via PCSX2).  
When you hit an enemy, a fiery damage number pops up above them, scales with the damage, floats upward, and fades out – exactly where the enemy is on screen, even if the camera moves.

## Demo with lowered EpicFX thresholds for demonstration:
  (configurable by clicking Setup in the Launcher)
![Demo](assets/demo.gif)


## 🚀 What's New in v0.5.0 (Full Wayland Support):

### 🌊 Native Wayland support – no setup needed: the overlay now tracks PCSX2 even when it runs as a native Wayland client. The game window is located through the compositor itself (KDE/KWin, Hyprland and Sway), so `QT_QPA_PLATFORM=xcb` is no longer required.

### 🔌 PINE auto-setup: PCSX2 updates silently turn its PINE server off, which used to leave the overlay waiting forever. The overlay now switches PINE on in PCSX2's config for you (when PCSX2 isn't running), and tells you exactly what to click if it is.

### 🩺 Clear status messages: "Waiting for game" now diagnoses precisely what's missing – PCSX2 not started, PINE off, game not loaded, or window not trackable.

### 📦 Linux packages: prebuilt **AppImage** and **Flatpak** builds (see below), plus the existing one-file binary build.

### 🐛 Fixed "0 enemies" on Linux: with the PINE-only fallback (the default on most distros), the enemy scanner and the render loop raced on the single PINE socket and corrupted each other's replies, so no enemies were ever tracked and `--simulate` showed nothing. PINE transactions are now serialized and self-heal on errors.

### 🐛 Fixes: `diag.py` crashed with a `KeyError` and used an outdated player heuristic; it now mirrors the live tracker exactly. Persistent enemy-scan failures are now reported instead of silently swallowed.


## Features

- 🎯 **Attached to enemies** – numbers follow moving targets smoothly.  
- 📷 **Live camera projection** – uses the game’s camera‑to‑world matrix + calibrated intrinsics. Works through any camera pan, rotate, or zoom.  
- 💥 **Epic hit feedback** – screenshake, warm edge flash, expanding shockwave ring, and a white‑hot pop for big damage.  
- 🎨 **Fully customisable** – colours, size, lifetime, tracking behaviour, and all visual effects are tweakable **live** via a GUI settings window (or by editing `settings.json`).  
- 🐎 **Low performance impact** – actor scanning is vectorised (numpy) and runs on a background thread. The overlay draws with per‑pixel alpha (`UpdateLayeredWindow` on Windows, an ARGB X11 window on Linux), with ≤1% CPU on a modern system.  
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
python ./app/gow_overlay.py
```

## 📦 Building the packages

```bash
python build.py            # one-file executable -> release/GoW-Damage-Overlay[.exe]
python build.py appimage   # Linux AppImage     -> release/GoW-Damage-Overlay-<v>-x86_64.AppImage
python build.py flatpak    # Flatpak bundle     -> release/GoW-Damage-Overlay-<v>.flatpak
```

The binary/AppImage builds need PyInstaller (`pip install pyinstaller`); the AppImage build fetches `appimagetool` automatically on first use. The flatpak build needs `flatpak` with the Flathub remote and builds everything else itself (manifest in `packaging/flatpak/`).

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
