"""
winutil_wayland.py - PCSX2 window tracking when PCSX2 runs as a NATIVE Wayland
client (so it has no X11 window for winutil_x11 to find).

Wayland has no portable "where is that other window?" protocol, so this asks
the compositor directly, picking whichever adapter matches the session:

  * KWin (KDE Plasma)  - loads a one-shot KWin script over DBus that prints the
                         PCSX2 window's client geometry to the journal, then
                         reads it back with journalctl. KWin's global compositor
                         coordinates map 1:1 onto the XWayland coordinate space
                         (at 100% scale), so the X11 overlay can be placed with
                         the values as-is.
  * Hyprland           - queries the Hyprland IPC socket ("j/clients").
  * Sway (i3 IPC)      - queries $SWAYSOCK with GET_TREE.

Everything is stdlib-only (subprocess + sockets). Geometry is cached and
refreshed at most every REFRESH_S, so the overlay's per-frame
client_rect_on_screen() calls stay cheap.

The overlay itself still renders through overlay_x11 (an XWayland window);
compositors stack those override-redirect windows above native Wayland
surfaces, which is verified on KWin. Keyboard synthesis is impossible into a
native Wayland window, so focus_window() reports failure and callers must
treat input-driving features as unavailable.

When this process runs inside a Flatpak, compositor CLIs (gdbus, journalctl)
are executed on the host via flatpak-spawn (requires --talk-name=org.freedesktop.Flatpak).
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import struct
import subprocess
import time
import uuid
from typing import List, Optional, Tuple

REFRESH_S = 1.0          # how stale a cached game-window rect may get
_TIMEOUT = 4             # seconds per external command


def _in_flatpak() -> bool:
    return os.path.exists("/.flatpak-info")


def _host_run(cmd: List[str], **kw) -> subprocess.CompletedProcess:
    """Run a command, on the host when sandboxed (flatpak-spawn --host)."""
    if _in_flatpak():
        cmd = ["flatpak-spawn", "--host"] + cmd
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    kw.setdefault("timeout", _TIMEOUT)
    return subprocess.run(cmd, **kw)


def _classify(title: str, app: str):
    """True when PCSX2 owns the window, else None. Compositors always report
    the real app class/app-id ("pcsx2-qt", flatpak "net.pcsx2.PCSX2"), so
    titles are deliberately NOT consulted: a title can be faked by anything -
    the overlay's own launcher, a browser tab about the game - and that made
    the overlay attach to the wrong window."""
    app = (app or "").lower()
    return True if "pcsx2" in app and "gow" not in app else None


def _pick(cands):
    """cands: [(class_hit, area, rect)] -> rect of the best one, or None.
    PCSX2-owned windows always beat title matches; then largest area."""
    if not cands:
        return None
    return max(cands, key=lambda c: (c[0], c[1]))[2]


# --- KWin (KDE Plasma) ---------------------------------------------------------
_KWIN_JS = """
const out = [];
const list = workspace.windowList ? workspace.windowList() : workspace.clientList();
for (const w of list) {
    const t = String(w.caption || ""), c = String(w.resourceClass || "");
    const lc = c.toLowerCase();
    if (lc.indexOf("pcsx2") === -1)
        continue;          // only PCSX2's own windows: titles can be faked
                           // (and nothing else reaches the journal)
    const g = w.clientGeometry || w.frameGeometry;
    out.push({t: t, c: c, r: [g.x, g.y, g.width, g.height],
              min: !!w.minimized, fs: !!w.fullScreen});
}
print("%(tag)s " + JSON.stringify(out));
"""


class KWinAdapter:
    name = "kwin"

    @staticmethod
    def available() -> bool:
        if not shutil.which("flatpak-spawn" if _in_flatpak() else "gdbus"):
            return False
        desk = os.environ.get("XDG_CURRENT_DESKTOP", "") + os.environ.get("KDE_FULL_SESSION", "")
        return "kde" in desk.lower() or "true" in desk.lower()

    def _gdbus(self, path: str, method: str, *args: str) -> Optional[str]:
        cmd = ["gdbus", "call", "--session", "--dest", "org.kde.KWin",
               "--object-path", path, "--method", method, *args]
        try:
            r = _host_run(cmd)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return r.stdout if r.returncode == 0 else None

    def query(self) -> Optional[List[dict]]:
        """All windows as [{t, c, r:[x,y,w,h], min, fs}], or None on failure."""
        tag = "GOWOV-" + uuid.uuid4().hex[:12]
        js = _KWIN_JS % {"tag": tag}
        path = f"/tmp/gow_overlay_kwin_{tag}.js"
        try:
            if _in_flatpak():
                _host_run(["sh", "-c", f"cat > {path}"], input=js)
            else:
                with open(path, "w") as f:
                    f.write(js)
            sname = "gowoverlay-probe"
            self._gdbus("/Scripting", "org.kde.kwin.Scripting.unloadScript", sname)
            out = self._gdbus("/Scripting", "org.kde.kwin.Scripting.loadScript", path, sname)
            if not out:
                return None
            sid = "".join(ch for ch in out if ch.isdigit() or ch == "-")
            # Plasma >= 5.27 exposes scripts at /Scripting/ScriptN, older at /N
            if not self._gdbus(f"/Scripting/Script{sid}", "org.kde.kwin.Script.run"):
                self._gdbus(f"/{sid}", "org.kde.kwin.Script.run")
            for _ in range(20):                      # wait for the print to land
                try:
                    r = _host_run(["journalctl", "--user", "-o", "cat", "-q",
                                   "--no-pager", "--since", "-15s"])
                except (OSError, subprocess.TimeoutExpired):
                    return None
                for ln in reversed((r.stdout or "").splitlines()):
                    i = ln.find(tag + " ")
                    if i != -1:
                        try:
                            return json.loads(ln[i + len(tag) + 1:])
                        except ValueError:
                            return None
                time.sleep(0.05)
            return None
        finally:
            self._gdbus("/Scripting", "org.kde.kwin.Scripting.unloadScript", "gowoverlay-probe")
            try:
                if _in_flatpak():
                    _host_run(["rm", "-f", path])
                else:
                    os.unlink(path)
            except OSError:
                pass

    def find(self) -> Optional[Tuple[int, int, int, int]]:
        cands = []
        for w in self.query() or []:
            hit = _classify(w.get("t"), w.get("c"))
            if hit is None or w.get("min"):
                continue
            r = tuple(int(v) for v in w["r"])
            cands.append((hit, r[2] * r[3], r))
        return _pick(cands)


# --- Hyprland --------------------------------------------------------------------
class HyprlandAdapter:
    name = "hyprland"

    @staticmethod
    def available() -> bool:
        return bool(os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"))

    def _socket_path(self) -> Optional[str]:
        sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
        run = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
        for p in (os.path.join(run, "hypr", sig, ".socket.sock"),
                  os.path.join("/tmp", "hypr", sig, ".socket.sock")):
            if os.path.exists(p):
                return p
        return None

    def find(self) -> Optional[Tuple[int, int, int, int]]:
        path = self._socket_path()
        if not path:
            return None
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(_TIMEOUT)
                s.connect(path)
                s.sendall(b"j/clients")
                raw = b""
                while True:
                    chunk = s.recv(65536)
                    if not chunk:
                        break
                    raw += chunk
            clients = json.loads(raw.decode("utf-8", "replace"))
        except (OSError, ValueError):
            return None
        cands = []
        for c in clients:
            hit = _classify(c.get("title"), c.get("class"))
            if hit is None or not c.get("mapped", True):
                continue
            r = (int(c["at"][0]), int(c["at"][1]),
                 int(c["size"][0]), int(c["size"][1]))
            cands.append((hit, r[2] * r[3], r))
        return _pick(cands)


# --- Sway (i3 IPC) -----------------------------------------------------------------
class SwayAdapter:
    name = "sway"

    @staticmethod
    def available() -> bool:
        return bool(os.environ.get("SWAYSOCK"))

    def find(self) -> Optional[Tuple[int, int, int, int]]:
        path = os.environ.get("SWAYSOCK")
        if not path:
            return None
        GET_TREE = 4
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(_TIMEOUT)
                s.connect(path)
                s.sendall(b"i3-ipc" + struct.pack("<II", 0, GET_TREE))
                hdr = b""
                while len(hdr) < 14:
                    hdr += s.recv(14 - len(hdr))
                size, _t = struct.unpack("<II", hdr[6:14])
                raw = b""
                while len(raw) < size:
                    raw += s.recv(size - len(raw))
            tree = json.loads(raw.decode("utf-8", "replace"))
        except (OSError, ValueError, struct.error):
            return None

        found = []

        def walk(n):
            app = n.get("app_id") or (n.get("window_properties") or {}).get("class", "")
            hit = _classify(n.get("name"), app)
            if hit is not None and n.get("visible", True) and n.get("rect"):
                r, wr = n["rect"], n.get("window_rect") or {}
                rect = (r["x"] + wr.get("x", 0), r["y"] + wr.get("y", 0),
                        wr.get("width") or r["width"], wr.get("height") or r["height"])
                found.append((hit, rect[2] * rect[3], rect))
            for c in (n.get("nodes") or []) + (n.get("floating_nodes") or []):
                walk(c)

        walk(tree)
        return _pick(found)


_ADAPTERS = (HyprlandAdapter, SwayAdapter, KWinAdapter)
_adapter = None
_adapter_checked = False


def _get_adapter():
    global _adapter, _adapter_checked
    if not _adapter_checked:
        _adapter_checked = True
        if os.environ.get("WAYLAND_DISPLAY") or os.environ.get("XDG_SESSION_TYPE") == "wayland":
            for cls in _ADAPTERS:
                try:
                    if cls.available():
                        _adapter = cls()
                        break
                except Exception:
                    continue
    return _adapter


class WaylandWindow:
    """Handle for a compositor-tracked (native Wayland) PCSX2 window. Looks up
    geometry through the session's adapter; cached for REFRESH_S between polls
    and holding the last good rect while a refresh fails (e.g. mid-resize)."""

    def __init__(self, adapter, rect):
        self.adapter = adapter
        self._rect = rect
        self._stamp = time.time()

    def rect(self) -> Tuple[int, int, int, int]:
        now = time.time()
        if now - self._stamp >= REFRESH_S:
            self._stamp = now
            try:
                r = self.adapter.find()
            except Exception:
                r = None
            if r:
                self._rect = r
        return self._rect


def find_pcsx2_window() -> Optional[WaylandWindow]:
    """A WaylandWindow for the PCSX2 display window, or None (not found / not a
    Wayland session / unsupported compositor)."""
    ad = _get_adapter()
    if ad is None:
        return None
    try:
        rect = ad.find()
    except Exception:
        return None
    return WaylandWindow(ad, rect) if rect else None


def client_rect_on_screen(wnd: WaylandWindow) -> Tuple[int, int, int, int]:
    return wnd.rect()


def focus_window(wnd) -> bool:
    return False      # cannot inject input into a native Wayland window


if __name__ == "__main__":
    ad = _get_adapter()
    print("adapter:", ad.name if ad else None)
    w = find_pcsx2_window()
    print("window:", w)
    if w:
        print("client rect (L,T,W,H):", client_rect_on_screen(w))
