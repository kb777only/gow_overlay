# v0.6.0 — Performance: the overlay gets out of the emulator's way

v0.5.0 made the overlay work everywhere; v0.6.0 makes it *cheap*. On slower machines the overlay could visibly lag the game — most of that cost existed even when nothing was on screen. This release reworks the renderer and the memory scanner so an idle overlay costs (almost) nothing and an active one touches only the pixels it draws. Applies to **Windows and Linux**.

## 🐎 What changed

- **Idle renderer.** The overlay used to composite and push a full transparent frame to the display server 60×/second even with no damage numbers visible — on Linux that burned CPU in Xwayland *and* the compositor, on top of the overlay's own. It now renders nothing while blank: no compositing, no surface uploads, just a low-rate window-follow tick.
- **Dirty-rectangle rendering.** While numbers are on screen, only the rectangle around them is composited, converted and uploaded — not the whole window. ~5× less CPU during normal hits.
- **Cheaper enemy scans (Linux PINE fallback).** Full-memory scans now use 64-bit PINE reads (half the commands — ~40% less emulator-side CPU per scan), pace themselves to a ≤25% duty cycle no matter how slow the machine (the scanner sleeps at least 3× as long as the scan took), and are skipped entirely while the game is paused. Windows and `ptrace_scope=0` setups already scanned via direct process reads and are unaffected.
- **Big-hit edge flash at half rate.** The warm edge flash is the one effect that inherently touches the whole frame; during its ~0.4 s burst those frames now run at 30 fps (visually identical) for roughly half the cost. Its math also runs in-place without large temporaries.

## 📊 Measured — Intel Core i3-3240 (2c/4t, 2012), 1060×663 game window, Linux/PINE fallback

All numbers below come from genuinely low-end hardware, the kind retro games actually get played on; newer machines see proportionally smaller footprints.

| state | before | after |
|---|---|---|
| no numbers on screen — overlay process | ~30% of a core | **~1%** |
| no numbers on screen — Xwayland + compositor | ~28% extra | **~0** |
| numbers floating | ~67% of a core | **~14%** |
| big-hit flash burst (0.4 s) | ~86% of a core | **~50%** |
| PCSX2-side scan cost (game paused) | 7.5% continuous | **~0 (skipped)** |

## 🔧 Tuning for very slow machines

See the new **Performance** section in the README. Short version, in order of effect:
1. Linux: `sudo sysctl kernel.yama.ptrace_scope=0` — direct memory reads take PCSX2's PINE thread out of the scan path entirely.
2. Settings → disable **edge flash** and **white-hot pop** (the only full-frame effects).
3. Raise `tracking.scan_period` in `settings.json`.

## 📥 Downloads

Same artifacts as v0.5.0, rebuilt: Windows `gow_overlay.zip`, Linux `GoW-Damage-Overlay-0.6.0-x86_64.AppImage` and `GoW-Damage-Overlay-0.6.0.flatpak`, or run from source.

No settings or compatibility changes; v0.5.0 configs work as-is.
