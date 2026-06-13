# God of War – Damage Overlay for PCSX2

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

![Icon Name](assets/gow_overlay.ico)  
**Live damage numbers that follow enemies – just like a modern action RPG.**  
A transparent, always‑on‑top overlay for the PS2 classic *God of War* (emulated via PCSX2).  
When you hit an enemy, a fiery damage number pops up above them, scales with the damage, floats upward, and fades out – exactly where the enemy is on screen, even if the camera moves.

### Demo with lowered EpicFX thresholds for demonstration:
  (configurable by clicking Setup in the Launcher)
  
![Demo](assets/demo.gif)

## 🌍 What's New in v0.7.1 (now plays the US/NTSC release too)

- 🇺🇸 **North American `SCUS-97399` support.** Until now the numbers only lined up on the PAL `SCES-53133` disc; on the US release enemies and damage were detected but nothing drew on screen. The overlay now auto-detects the game by its ID (over PINE) and loads the right **per-region camera profile**, so PAL **and** US/NTSC both work out of the box.
- 🎯 **Why it needs a profile:** GoW has no global camera matrix — the PS2's VU transforms each object on its own — so the overlay reads the live camera-to-world matrix from a fixed address and applies hand-calibrated lens intrinsics. Both the **address and the intrinsics differ between the PAL and NTSC builds**, so v0.7.1 keeps a profile per game ID in `camcalib.json` and selects it automatically.
- ➕ **Adding more regions is quick** — a two-pose calibration (match enemy world-coords to on-screen pixels at two camera angles) pins a new disc's camera and intrinsics. Issues/PRs welcome.

Recent releases: **v0.7.0** brought animated numbers – fire, exploding fireballs with ember sparks, and molten heat-shimmer gradients (all live-tweakable in **Settings → Animations**); **v0.6.95** fixed the overlay attaching to the launcher window; **v0.6.9** fixed misplaced damage numbers and added the ⏹ Stop button, named processes, and the app icon; **v0.6.5** added preset sharing, crash logs and the always-open launcher; **v0.6.0** cut the overlay's overhead to near zero; **v0.5.0** added full Wayland support and the Linux packages. Full history in [Releases](https://github.com/kb777only/gow_overlay/releases).

## 🗺️ Roadmap

The road to **v1.0.0** is all about spectacle and reach:

- ✅ ~~**Fire animations on the numbers**~~ – shipped in v0.7.0!
- ✅ ~~**Animated, colour-shifting numbers**~~ – shipped in v0.7.0!
- 🕹️ **Full, verified Steam Deck support** – tested and tuned on the Deck itself, out of the box.
- ✨ …and more cool stuff not yet planned – ideas welcome in [issues](https://github.com/kb777only/gow_overlay/issues)!

Meanwhile, **performance and stability updates** will keep being released as we go, through minor version updates.

## ✨ Features

- 🎯 **Attached to enemies** – numbers follow moving targets smoothly.  
- 📷 **World-Space Projection Engine** – GoW projects objects individually (a PS2 VU quirk), it lacks a standard global camera matrix. This uses a custom projection model calibrated through multi‑frame triangulation (matching actor world-coords to screen pixels) to pin numbers in 3D space through any pan, rotate, or zoom.  
- 💥 **Epic hit feedback** – burning numbers, an exploding fireball with ember sparks, screenshake, warm edge flash, expanding shockwave ring, and a white‑hot pop for big damage.  
- 🎨 **Fully customisable** – everything is tweakable **live** via a GUI settings window, and shareable as presets.  
- 🐎 **Low performance impact** – the renderer goes fully idle when nothing is on screen and touches only the pixels around the numbers when there is; scanning paces itself so the emulator always keeps its CPU. See [Performance](#-performance).  
- 🎮 **No game modification required** – reads memory via PINE (PCSX2's built‑in debug interface) and direct process reads. Works with the original ISO, any save state, and persists across level reloads.  
- 🐧 **Cross‑platform** – Windows and Linux (X11 **and Wayland**), same features on both.  

## 🖥️ Requirements

- **Windows 10 / 11** (the prebuilt `.exe` bundles Python 3.12) **or Linux** (X11 or Wayland – see [Linux notes](#-linux-notes)).
- **PCSX2** v1.7+ with its **PINE** server – the overlay switches PINE on in PCSX2's config for you, or tells you exactly where to click if PCSX2 is already running.
- **God of War** – works on PAL `SCES-53133` and US/NTSC `SCUS-97399` (auto-detected by game ID). Other regions with the same actor layout are detected for enemies/damage and just need a quick camera calibration to place the numbers – open an issue.

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

**If PCSX2 can run God of War on your machine at all, it can run this overlay.** The numbers below were measured on hardware that sits *below PCSX2's own minimum spec on every CPU axis* — so it's the worst case you're likely to see.

The test rig is an **Intel Core i3-3240**: Ivy Bridge (2012/2013), **2 physical cores / 4 threads, 3.4 GHz, no AVX2, PassMark single-thread 1775, 8 GB RAM**. For comparison, [PCSX2's requirements](https://pcsx2.net/docs/setup/requirements/) ask for:

- **Minimum:** SSE4.1, single-thread **≥ 2000**, **four** physical cores w/ SMT, 8 GB RAM.
- **Recommended:** **AVX2**, single-thread **≥ 2500**, **six** physical cores, 16 GB RAM.

This rig has half the cores, no AVX2, and a single-thread score under the 2000 floor — yet the overlay runs comfortably alongside the game. The overlay's work is single-threaded (project points, composite the rectangle around the numbers, upload it), so its cost scales with single-thread speed and window size, not core count.

**Measured here** (i3-3240, 1060×617 window, every animation enabled):

| State | CPU |
|---|---|
| Waiting / no numbers on screen *(most of gameplay)* | **~1% of one core** |
| Damage numbers on screen | **~15% of one core** |
| Big-hit FX — fire + fireball + ember sparks + edge flash, all on | **~85–90% of one core, for the ~0.4 s the effect lasts** |

The big-hit spike is brief and worst-case: a 12-year-old dual-core with every effect maxed. It's still **one core out of four threads**, so PCSX2 (spread across the others) keeps running smoothly, and it falls away the moment the effect ends. Plain numbers (~15%) and idle (~1%, where you spend most of your time) are the figures that matter for sustained play.

**Expected on machines that actually meet PCSX2's spec** — extrapolated from single-thread scaling (≈ ×1.13 at min, ×1.41 at recommended), and remember these have 4–6 cores so the one busy core is a far smaller slice of the whole:

| Config (CPU single-thread) | idle | numbers on screen | big-hit FX burst |
|---|---|---|---|
| PCSX2 **minimum** (~2000) | <1% | **~13%** of one core | **~75%** of one core, ~0.4 s |
| PCSX2 **recommended** (~2500) | <1% | **~11%** of one core | **~60%** of one core, ~0.4 s |

Other notes:

- **Animations are cache-driven**: every gradient/shimmer frame variant of a number is rendered once and reused, so repeated damage values cost nothing new; a value's tiles are built on its first-ever appearance (~1–3 frames). Flames are computed at half resolution over just the number's own pixels (~2–4% per burning number).
- **Enemy scanning**: with direct process reads (Windows, or Linux with `ptrace_scope=0`) a full scan takes ~0.1 s and costs the emulator nothing. Over the PINE fallback it is paced to a **≤25% duty cycle**, costs PCSX2 a few percent of one core, and is **skipped while the game is paused**.

**If your machine is really struggling**, in order of effect:

1. **Settings → Animations**: switch off the **fireball, sparks and flames** (the per-number effects that dominate a heavy on-screen barrage), then **edge flash** and **white-hot pop** (the full-frame effects). Plain numbers still track perfectly.
2. **Linux**: `sudo sysctl kernel.yama.ptrace_scope=0` – direct memory reads take PCSX2's PINE thread out of the scan path completely (the Flatpak always uses PINE reads; AppImage/binary benefit automatically).
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
