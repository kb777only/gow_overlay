# v0.6.5 — Preset Sharing, Crash Logs & a Launcher That Stays Open

A quality-of-life release for **Windows and Linux**.

## 🎁 Import / Export presets

The Settings window (launcher → **Settings**) has a new **Presets** row:

- **Export…** saves your complete configuration — colours, number sizes and motion, epic-FX toggles and strengths, tracking tuning — to a single shareable `.json` file.
- **Import…** loads a preset and applies it instantly; a running overlay picks it up live, no restart needed.

Presets are version-tolerant: on import they're merged over the current defaults, so files made with older or newer versions of the overlay load fine (anything missing keeps its default, junk files are rejected with a clear error).

## 📋 Crash logs for easy bug reports

Every overlay run is now logged — everything it prints plus the full traceback of any crash, including ones in background threads, with a header recording the overlay version, OS and session type. Two files are kept: `gow_overlay.log` (latest run) and `gow_overlay.prev.log` (the run before), next to the executable or in `~/.config/gow_overlay/` for AppImage/Flatpak installs.

In the launcher:

- **📋 Copy last log** — puts the most recent log on your clipboard, ready to paste into an issue.
- **🐞 Report an issue** — opens the repo's new-issue page.

## 🪟 The launcher stays open

Starting the overlay no longer closes the launcher: the Start button shows "Overlay running…" and re-arms when the overlay exits, so you can finally use **Settings** to live-tweak colours and effects *while playing*. Closing the launcher leaves the overlay running.

## 📝 Also

- README reorganised — shorter, with a Quick-Start table, a bug-reporting guide, and the changelog history moved to the release pages.

No engine, tracking, or rendering changes; v0.6.0's performance characteristics are unchanged, and existing `settings.json` files work as-is.

## 📥 Downloads

| Platform | File |
|---|---|
| Windows 10/11 | `gow_overlay-0.6.5-win64.zip` |
| Linux | `GoW-Damage-Overlay-0.6.5-x86_64.AppImage` |
| Linux | `GoW-Damage-Overlay-0.6.5.flatpak` |
