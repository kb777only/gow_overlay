"""procname.py - process naming + finding/stopping running overlays.

The launcher and the overlay are the same executable (the launcher re-spawns
itself with --run), so each role names its own process: the overlay is
`gow_overlay`, the launcher `gow_overlay-launcher`. On Linux this sets the
kernel comm (kept to its 15-char limit), so the background overlay is easy to
spot in any process list and `pkill -x gow_overlay` just works - and it is what
powers the launcher's Stop button, including for overlays started by an earlier
launcher. Windows cannot rename a running process (it always shows the exe
name), so there overlays are found by command line instead.
"""
import ctypes
import os
import subprocess
import sys

OVERLAY = "gow_overlay"
LAUNCHER = "gow_overlay-launcher"
SETUP = "gow_overlay-setup"


def set_name(name):
    """Name the current process (Linux comm; no-op on Windows)."""
    if sys.platform == "win32":
        return
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        libc.prctl(15, name.encode()[:15], 0, 0, 0)      # PR_SET_NAME = 15
    except Exception:
        pass


if sys.platform == "win32":
    CREATE_NO_WINDOW = 0x08000000

    def find_overlays():
        """PIDs of running overlay processes (never the launcher/settings):
        anything whose command line has the --run flag or runs gow_overlay.py."""
        ps = ("Get-CimInstance Win32_Process | Where-Object { "
              "$_.Name -notmatch 'powershell|pwsh' -and "
              "($_.CommandLine -match '--run ' -or $_.CommandLine -match 'gow_overlay\\.py') "
              "} | ForEach-Object { $_.ProcessId }")
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                               capture_output=True, text=True, timeout=15,
                               creationflags=CREATE_NO_WINDOW)
            pids = [int(x) for x in r.stdout.split() if x.strip().isdigit()]
        except Exception:
            return []
        me = os.getpid()
        return [p for p in pids if p != me]

    def _kill(pid):
        PROCESS_TERMINATE = 0x0001
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(PROCESS_TERMINATE, False, pid)
        if h:
            k32.TerminateProcess(h, 1)
            k32.CloseHandle(h)

else:
    def find_overlays():
        """PIDs whose comm is exactly the overlay's process name."""
        target = OVERLAY.encode()[:15]
        me = os.getpid()
        out = []
        for e in os.listdir("/proc"):
            if not e.isdigit() or int(e) == me:
                continue
            try:
                with open(f"/proc/{e}/comm", "rb") as f:
                    if f.read().strip() == target:
                        out.append(int(e))
            except OSError:
                continue
        return out

    def _kill(pid):
        import signal
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass


def stop_overlays():
    """Terminate every running overlay process. Returns how many were stopped."""
    pids = find_overlays()
    for p in pids:
        _kill(p)
    return len(pids)


if __name__ == "__main__":
    print("running overlays:", find_overlays())
