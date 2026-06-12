"""applog.py - run/crash logging for easy bug reports.

Every overlay run is logged to gow_overlay.log (the previous run is kept as
gow_overlay.prev.log), including everything printed to the console and the
traceback of any crash - from the main thread or background threads. The
launcher's "Copy last log" button puts the latest log on the clipboard so
users can paste it straight into a GitHub issue.

Logs live next to the executable, or in ~/.config/gow_overlay/ when the
install dir is read-only (AppImage, flatpak) - same rule as settings.json.
"""
import io
import json
import os
import platform
import sys
import threading
import time
import traceback

LOG_NAME = "gow_overlay.log"
PREV_NAME = "gow_overlay.prev.log"

_started = False


def _log_dir():
    d = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
         else os.path.dirname(os.path.abspath(__file__)))
    if os.access(d, os.W_OK):
        return d
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    d = os.path.join(base, "gow_overlay")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


def log_path():
    return os.path.join(_log_dir(), LOG_NAME)


def prev_path():
    return os.path.join(_log_dir(), PREV_NAME)


def _version():
    try:
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(base, "appinfo.json")) as f:
            return str(json.load(f).get("version", "?"))
    except Exception:
        return "?"


class _Tee(io.TextIOBase):
    """Write-through to the original stream AND the log file (flushed, so the
    log is complete even after a hard crash)."""

    def __init__(self, orig, f):
        self.orig, self.f = orig, f

    def write(self, s):
        try:
            self.orig.write(s)
            self.orig.flush()
        except Exception:
            pass
        try:
            self.f.write(s)
            self.f.flush()
        except Exception:
            pass
        return len(s)

    def flush(self):
        for t in (self.orig, self.f):
            try:
                t.flush()
            except Exception:
                pass


def start(tag=""):
    """Rotate logs, tee stdout/stderr into the new one, and make sure uncaught
    exceptions (any thread) land in it. Safe to call more than once."""
    global _started
    if _started:
        return log_path()
    path = log_path()
    try:
        if os.path.exists(path):
            os.replace(path, prev_path())
        f = open(path, "w", encoding="utf-8", errors="replace")
    except OSError:
        return None
    _started = True
    f.write(f"=== GoW Damage Overlay v{_version()} - {time.strftime('%Y-%m-%d %H:%M:%S')}"
            f"{' - ' + tag if tag else ''}\n"
            f"=== {platform.platform()} | python {platform.python_version()} | "
            f"session {os.environ.get('XDG_SESSION_TYPE', '-')} | "
            f"desktop {os.environ.get('XDG_CURRENT_DESKTOP', '-')}\n")
    f.flush()
    sys.stdout = _Tee(sys.stdout, f)
    sys.stderr = _Tee(sys.stderr, f)

    def _hook(tp, val, tb):
        if tp is KeyboardInterrupt:
            return
        print("\n=== CRASH ===\n" + "".join(traceback.format_exception(tp, val, tb)),
              file=sys.stderr, flush=True)

    sys.excepthook = _hook
    threading.excepthook = lambda a: _hook(a.exc_type, a.exc_value, a.exc_traceback)
    return path


def read_latest():
    """(path, text) of the most recent log - the current run's if one exists,
    else the previous run's. ('', '') when there is none yet."""
    for p in (log_path(), prev_path()):
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                return p, f.read()
        except OSError:
            continue
    return "", ""
