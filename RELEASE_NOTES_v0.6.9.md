# v0.6.9 — Misplaced-Number Fix & App Icon

A focused release for **Windows and Linux**.

## 🎯 Fixed: damage numbers in the wrong place

Numbers could occasionally spawn in the wrong spot — sometimes far from the enemy, sometimes outside the game view entirely (in the letterbox bars or at a window edge). Two root causes, both fixed:

- **Garbage camera matrices.** The overlay reads the game's camera-to-world matrix from EE RAM every frame. During loads, menus and hard camera cuts that memory briefly holds non-camera data, and a PINE read can also tear mid-update — either way the resulting "matrix" projected hits to arbitrary screen positions. The overlay now validates every matrix before trusting it (finite values, orthonormal rotation rows, sane camera position) and keeps the last good one when a frame fails validation.
- **Unbounded number tracking.** A live number follows its enemy every frame; a single bad projection (torn position read, mid-frame camera cut) could yank it across or off the screen. Position updates that land implausibly far outside the view are now ignored — the number simply holds its last good spot instead of flying away.

Validated against live gameplay: real camera matrices pass the filter exactly (rotation row norms are 1.0 in-game), and synthetic garbage (zeros, random data, NaNs, torn rows) is rejected while retaining the previous good matrix.

## 🖼️ App icon

The GoW overlay icon now shows up everywhere the app does:

- the **launcher** and **Settings** windows (title bar / taskbar / dock),
- the **overlay window** itself (`WM_CLASS` + `_NET_WM_ICON` on Linux, so window tools identify it properly),
- the **Windows `.exe`** (Explorer and taskbar).

## 📥 Downloads

| Platform | File |
|---|---|
| Windows 10/11 | `gow_overlay-0.6.9-win64.zip` |
| Linux | `GoW-Damage-Overlay-0.6.9-x86_64.AppImage` |
| Linux | `GoW-Damage-Overlay-0.6.9.flatpak` |

No settings changes; existing configs and presets work as-is.
