# v0.5.0 — Full Wayland Support, Zero-Setup PINE & Linux Packages

The overlay now works out of the box on every major Linux desktop — X11 **and Wayland** — and configures PCSX2's PINE server for you on both Windows and Linux. No environment variables, no settings digging, no terminal required: start the overlay, start the game, fight.

## ✨ Highlights

- **🌊 Native Wayland support (Linux).** PCSX2 no longer needs to be started with `QT_QPA_PLATFORM=xcb`. When PCSX2 runs as a native Wayland client, the overlay finds and follows the game window through the compositor itself — KDE Plasma (KWin), Hyprland and Sway are supported, on X11 sessions nothing changed. Just run both programs normally.
- **🔌 PINE auto-setup (Windows + Linux).** PCSX2 updates silently reset its PINE server to *off*, which used to leave the overlay waiting forever with no explanation. The overlay now turns PINE on in PCSX2's config automatically (when PCSX2 isn't running), and if PCSX2 is already running with PINE off, it tells you exactly where to click (`Settings > Advanced > PINE > Enable`).
- **🩺 Clear status messages.** "Waiting for game to launch..." now diagnoses precisely what's missing: PCSX2 not started, PINE server off, no game loaded, or the game window not trackable — each with the fix spelled out.
- **📦 New Linux packages.** Prebuilt **AppImage** and **Flatpak** alongside the existing one-file binary and the Windows `.exe`.

## 🐛 Fixed

- **No enemies / no damage numbers on Linux.** On the PINE-only read path (the default on most distros, where `kernel.yama.ptrace_scope` blocks direct process reads), the enemy scanner and the render loop raced on PCSX2's single PINE connection and corrupted each other's replies — the overlay ran but tracked 0 enemies, and `--simulate` showed nothing. PINE transactions are now serialized and the connection self-heals after errors. Windows was unaffected (it scans via `ReadProcessMemory`) but gets the hardened PINE client too.
- **Endless "Waiting for game" with no hint** when PCSX2 was running but its PINE server was disabled (see auto-setup above).
- **`diag.py` crashed** with a `KeyError` and identified the player with an outdated heuristic; it now mirrors the live tracker exactly (`enemy.find_player`, dead/distance exclusions).
- **Persistent enemy-scan failures are now reported** instead of being silently swallowed.
- **Read-only installs** (AppImage / Flatpak / system dirs): `settings.json` now falls back to `~/.config/gow_overlay/` instead of failing to save.
- Flatpak-packaged PCSX2 is now detected too (PINE socket at `$XDG_RUNTIME_DIR/app/net.pcsx2.PCSX2/`).

## 📥 Downloads

| Platform | File | Notes |
|---|---|---|
| Windows | `gow_overlay.zip` (`launcher.exe`) | as before |
| Linux | `GoW-Damage-Overlay-0.5.0-x86_64.AppImage` | `chmod +x`, run |
| Linux | `GoW-Damage-Overlay-0.5.0.flatpak` | `flatpak install --user GoW-Damage-Overlay-0.5.0.flatpak` |
| Any | source | `pip install -r requirements.txt`, `python app/launcher.py` |

Building yourself: `python build.py` (one-file binary), `python build.py appimage`, `python build.py flatpak` (manifest in `packaging/flatpak/`).

## 📝 Notes & known limitations

- **GNOME on Wayland** exposes no window-tracking interface; there (and on other unsupported compositors) start PCSX2 as an X11 client: `QT_QPA_PLATFORM=xcb pcsx2-qt`. KDE / Hyprland / Sway need nothing.
- **Flatpak build** always uses PINE-only memory reads (a sandbox cannot read another process's memory) — enemies are discovered slightly more slowly than with the AppImage/binary plus `ptrace_scope=0`.
- For the fastest enemy discovery on Linux, optionally allow direct reads: `sudo sysctl kernel.yama.ptrace_scope=0`. Everything works without it via the PINE fallback.
- Wayland window tracking assumes 100% display scaling; on scaled displays numbers may be offset (XWayland coordinate mapping) — run PCSX2 with `QT_QPA_PLATFORM=xcb` as a workaround.
- Tested on God of War **SCES-53133** (PAL); other regions with the same actor layout should work.

**Full changelog**: `diag.py`, `emu.py`, `gow_overlay.py`, `launcher.py`, `pine.py`, `settings.py`, `winutil.py`, `build.py` modified; `winutil_wayland.py`, `pcsx2cfg.py`, `packaging/flatpak/*` added.
