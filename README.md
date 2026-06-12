# God of War – Damage Overlay for PCSX2

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Live damage numbers that follow enemies – just like a modern action RPG.**  
A transparent, always‑on‑top overlay for the PS2 classic *God of War* (emulated via PCSX2).  
When you hit an enemy, a fiery damage number pops up above them, scales with the damage, floats upward, and fades out – exactly where the enemy is on screen, even if the camera moves.

![Demo](docs/demo.gif) *(GIF of in-gme demo to be added soon)*

## ✨ Features

- 🎯 **Attached to enemies** – numbers follow moving targets smoothly.  
- 📷 **Live camera projection** – uses the game’s camera‑to‑world matrix + calibrated intrinsics. Works through any camera pan, rotate, or zoom.  
- 💥 **Epic hit feedback** – screenshake, warm edge flash, expanding shockwave ring, and a white‑hot pop for big damage.  
- 🎨 **Fully customisable** – colours, size, lifetime, tracking behaviour, and all visual effects are tweakable **live** via a GUI settings window (or by editing `settings.json`).  
- 🐎 **Low performance impact** – actor scanning is vectorised (numpy) and runs on a background thread. The overlay uses `UpdateLayeredWindow` for per‑pixel alpha, with ≤1% CPU on a modern system.  
- 🎮 **No game modification required** – reads memory via PINE (PCSX2’s built‑in debug interface) and RPM (ReadProcessMemory). Works with the original game ISO, any save state, and persists across level reloads.  
- 📦 **Single‑file executable** – PyInstaller build included (see below). Double‑click `launcher.exe`, pick a mode, and play.  

## 🖥️ Requirements

- **Windows** (7 / 10 / 11) – Linux support is work‑in‑progress (see Roadmap).  
- **PCSX2** (v1.7+ recommended) – the overlay uses the **PINE** IPC server, which is enabled by default on port `28011`.  
  - *Check:* In PCSX2, go to `Config > Emulation > Enable PINE Server` (should be on).  
- **God of War** (SCES‑53133 / SCUS‑97399 / any region with the same actor struct layout – tested on European PAL `SCES-53133`).  
- **Python 3.8+** (only if running from source) – see [Running from Source](#running-from-source).

## 🚀 Quick Start (Pre‑built `.exe`)

1. **Download** the latest `gow_overlay.zip` from [Releases](https://github.com/kb777only/gow_overlay/releases).  
2. **Extract** anywhere.  
3. **Launch** `launcher.exe`.  
4. **Start PCSX2** and load *God of War* (get in‑game, past the main menu).  
5. In the launcher window, choose:  
   - **Normal** – overlay + terminal with basic logs.  
   - **Verbose** – overlay + terminal with all debug data.  
   - **Damage log** – overlay + terminal showing only damage numbers.  
   - **Silent (background)** – overlay only, no terminal window.  
6. Click **Start Overlay**.  

Damage numbers will now appear over enemies whenever you hurt them.  
To adjust colours, size, or effect strength, click **Settings** in the launcher while the overlay is running – changes apply instantly.

> 💡 The overlay waits for the game to launch. You can start it before PCSX2 – it will automatically connect once the game is running.

## 🔧 Running from Source (Python)

If you prefer to run the Python scripts directly (e.g., for development or customisation):

```bash
git clone https://github.com/kb777only/gow_overlay.git
cd gow_overlay
pip install -r requirements.txt   # numpy, pillow, (optional: distro, tkinter)
python ./app/gow_overlay.py
