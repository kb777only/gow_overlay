# God of War – Damage Overlay for PCSX2

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Live damage numbers that follow enemies – just like a modern action RPG.**

A transparent, always‑on‑top overlay for the PS2 classic *God of War* (emulated in PCSX2). Hit an enemy and a fiery number pops up over them, scales with the damage, floats up and fades – pinned to where the enemy is on screen, even as the camera moves. No game files are touched.

![demo](assets/demo.gif)

*(demo with *EpicFX thresholds lowered* so they can be seen on every heavy hit)*

## 🎮 What's New in v0.7.3

- 🎚️ **Visual presets.** Pick **Inferno · Arcade · Subtle · Minimal** (or Default) from a new dropdown in **Settings** — applied live. Presets you import are saved and join the dropdown automatically. An optional **`presets.zip`** is on the [Releases](https://github.com/kb777only/gow_overlay/releases) page.
- 📈 **Damage FX rescaled for a whole playthrough.** Number size, colour and epic‑impact now ramp **logarithmically** across the entire damage range — tiny early hits stay clean, while the fire and explosions show up more and more as your damage grows.
- 🩸 **The settings window is God of War themed too** now — black with blood‑red text, matching the launcher.

Recent releases: **v0.7.2** bundled the real God of War font (numbers *and* UI, no install needed), themed the launcher, made closing it stop the overlay (and closing the game stop it too), and split the log modes; **v0.7.1** added US/NTSC `SCUS‑97399` support; **v0.7.0** animated the numbers with fire, exploding fireballs and molten gradients. Full history in [Releases](https://github.com/kb777only/gow_overlay/releases).

## ✨ Features

- 🎯 **Pinned to enemies** through any camera pan, rotate or zoom — a custom projection model (GoW has no global camera matrix; the PS2 VU transforms each object on its own) calibrated per region by matching actor world‑coords to screen pixels.
- 💥 **Epic hit feedback** — burning numbers, an exploding fireball with ember sparks, screenshake, edge flash, shockwave ring and a white‑hot pop, all scaling with the hit.
- 🎨 **Fully customisable, live** — a GoW‑themed settings window with presets you can pick, import and share.
- 🐎 **Light** — idles to ~1% of a core when nothing's on screen; see [Performance](#-performance).
- 🎮 **No game mod** — reads memory over PINE (PCSX2's debug interface); works with the original ISO, any save state, and across level reloads.
- 🐧 **Cross‑platform** — Windows and Linux (X11 **and** Wayland).

## 🖥️ Requirements

- **Windows 10/11** (the prebuilt `.exe` bundles Python) **or Linux** (X11 or Wayland — see [Linux notes](#-linux-notes)).
- **PCSX2** v1.7+ with its **PINE** server — the overlay turns PINE on for you, or points to where to click.
- **God of War** — PAL `SCES‑53133` and US/NTSC `SCUS‑97399`, auto‑detected. Other regions are detected for enemies/damage and just need a quick camera calibration to place the numbers — [open an issue](https://github.com/kb777only/gow_overlay/issues).

## 🚀 Quick Start

Grab a build from [Releases](https://github.com/kb777only/gow_overlay/releases):

| Platform | File | Run it |
|---|---|---|
| Windows | `gow_overlay-<v>-win64.zip` | extract, double‑click `GoW-Damage-Overlay.exe` |
| Linux | `GoW-Damage-Overlay-<v>-x86_64.AppImage` | `chmod +x`, run |
| Linux | `GoW-Damage-Overlay-<v>.flatpak` | `flatpak install --user <file>` |

1. Start the overlay (before or after the game — it waits and auto‑detects).
2. Pick a run mode and click **Start Overlay**: **Normal** (status + tracking), **Damage log** (only the hits), **Verbose** (everything), or **Silent** (no terminal).
3. Play — numbers pop over enemies as you hurt them.

Click **⚙ Settings** any time to tune the look or pick a **preset**, live. **⏹ Stop** ends the overlay; closing the launcher window stops it too, or use **✕ Close launcher, keep overlay running** to leave it going. Closing God of War also ends the overlay on its own.

## ⚡ Performance

**If PCSX2 can run God of War on your machine, it can run this overlay.** It's tested on an **Intel Core i3‑3240** (2012 dual‑core, no AVX2, PassMark single‑thread **1775**) — *below* [PCSX2's own minimum](https://pcsx2.net/docs/setup/requirements/) (SSE4.1, single‑thread ≥ 2000, four cores). The overlay's work is single‑threaded and scales with window size, so anything that meets PCSX2's bar has headroom to spare.

Measured on that i3‑3240 (1060×617 window, every animation on):

| State | CPU |
|---|---|
| Idle / no numbers *(most of play)* | **~1% of one core** |
| Damage numbers on screen | **~15% of one core** |
| Big‑hit FX (fire + fireball + sparks + flash) | **~85–90% of one core, for the ~0.4 s it lasts** |

The big‑hit figure is a brief, worst‑case spike on a 12‑year‑old dual‑core — one core of four threads, so the game stays smooth, and it drops fast on better hardware (roughly ~75% at PCSX2's minimum spec, ~60% at recommended). Animations are cache‑driven (repeated values cost nothing new). Enemy scanning is paced to a ≤25% duty cycle over PINE and skipped while paused; on Linux, `sudo sysctl kernel.yama.ptrace_scope=0` takes it off PCSX2's thread entirely.

**If it's struggling:** in **Settings → Animations** turn off the fireball, sparks and flames (and edge flash / white‑hot pop) — plain numbers still track perfectly; or raise `tracking.scan_period` in `settings.json`.

## 🐧 Linux notes

Works on X11 and Wayland (the overlay is an ARGB X11 window, via XWayland on Wayland); any compositing desktop gives transparency. The game window is found automatically on **KDE Plasma**, **Hyprland** and **Sway**; on other compositors (e.g. GNOME) start PCSX2 as an X11 client: `QT_QPA_PLATFORM=xcb pcsx2-qt`.

Settings, presets and logs live next to the executable, or under `~/.config/gow_overlay/` for AppImage/Flatpak installs.

## 🐞 Reporting bugs

Every run is logged (with full crash tracebacks). In the launcher, click **📋 Copy last log**, then **🐞 Report an issue**, and paste it into a [GitHub issue](https://github.com/kb777only/gow_overlay/issues).

## 🛠️ For developers

```bash
git clone https://github.com/kb777only/gow_overlay.git
cd gow_overlay && pip install -r requirements.txt
python ./app/launcher.py        # run from source

python build.py                 # one-file executable -> release/
python build.py appimage        # Linux AppImage
python build.py flatpak         # Flatpak bundle
```
