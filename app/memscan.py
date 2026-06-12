"""
memscan.py - fast EE-RAM access + a small Cheat-Engine-style scanner.

Memory backends (same interface, picked automatically):
  * RpmReader   - direct reads of the pcsx2 process: ReadProcessMemory on
                  Windows, process_vm_readv on Linux. Fast bulk reads. The base
                  of the PS2 EE RAM inside the host process is located
                  automatically by using PINE as an oracle: we read a set of
                  (ps2_addr -> value) samples over PINE, then find the host
                  region where host[base + (ps2_addr & 0x1FFFFFF)] matches them.
  * PineReader  - fallback when direct reads aren't permitted (e.g. Linux
                  kernel.yama.ptrace_scope > 0): block reads go over PINE.
                  Slower for full-window scans, but everything still works.

EE main RAM is 32 MiB: PS2 addresses 0x00000000 .. 0x01FFFFFF.
"""

from __future__ import annotations

import ctypes
import errno
import os
import struct
import sys
from typing import Dict, Iterator, List, Optional, Tuple

import pine


EE_RAM_SIZE = 0x02000000          # 32 MiB
EE_MASK = 0x01FFFFFF
DEFAULT_SCAN_START = 0x00100000   # skip the low 1 MiB (kernel)
DEFAULT_SCAN_END = 0x02000000


class _ReaderBase:
    """Shared logic for the direct-read backends: EE-base location via the
    PINE oracle, and PS2-address block reads once the base is known."""

    pid: int
    ee_base: Optional[int] = None

    # platform backends implement these two:
    def _read_raw(self, host_addr: int, size: int) -> Optional[bytes]:
        raise NotImplementedError

    def regions(self) -> Iterator[Tuple[int, int, object]]:
        raise NotImplementedError

    def close(self):
        pass

    def locate_ee_base(self, pc: pine.PineClient, samples: int = 300) -> Optional[int]:
        """Find the host base of PS2 EE RAM using PINE reads as ground truth.

        PCSX2 maps the PS2 address space at a fixed host base (fastmem), so
        host = base + ps2_addr. We sample many (addr, value) pairs over PINE,
        pick a distinctive pivot, byte-search candidate regions for it to get a
        page-aligned base hypothesis, score it against all samples, and finally
        confirm with fresh paired PINE/direct reads. Emulation should be paused
        by the caller for a clean match (memory frozen)."""
        step = 0x01E00000 // samples
        addrs = [0x00100000 + i * step for i in range(samples)]
        vals = [int(v) & 0xFFFFFFFF for v in pc.batch_read([("u32", a) for a in addrs])]
        pairs = [(a, v) for a, v in zip(addrs, vals) if v not in (0, 0xFFFFFFFF)]
        if not pairs:
            return None
        pivot = pairs[len(pairs) // 2]
        pivot_bytes = struct.pack("<I", pivot[1])
        # The real base matches the vast majority of samples; a wrong base matches
        # ~none. On a RUNNING game some samples change between the PINE read and the
        # (slow) region scan, so don't demand a near-perfect match - the correct
        # base still stands out hugely (e.g. 88% vs ~0%).
        need = max(20, int(len(pairs) * 0.55))

        best = (None, -1)
        for b, size, _prot in self.regions():
            if size < EE_RAM_SIZE:
                continue
            data = self._read_raw(b, size)
            if data is None:
                continue
            seen = set()
            idx = data.find(pivot_bytes)
            while idx != -1:
                base = (b + idx) - (pivot[0] & EE_MASK)
                if base % 0x1000 == 0 and base not in seen:
                    seen.add(base)
                    score = 0
                    for a, v in pairs:
                        ho = base - b + (a & EE_MASK)
                        if 0 <= ho <= len(data) - 4 and struct.unpack_from("<I", data, ho)[0] == v:
                            score += 1
                    if score > best[1]:
                        best = (base, score)
                idx = data.find(pivot_bytes, idx + 1)
            if best[1] >= need:
                break

        base = best[0]
        if base is None or best[1] < need:
            self.ee_base = None
            return None
        # final confirmation with fresh paired reads
        chk = [0x00100000 + (i * 0x1F1) * 0x401 % 0x01E00000 & ~3 for i in range(24)]
        pv = pc.batch_read([("u32", a) for a in chk])
        good = 0
        for a, v in zip(chk, pv):
            raw = self._read_raw(base + (a & EE_MASK), 4)
            if raw and struct.unpack("<I", raw)[0] == int(v):
                good += 1
        if good < max(8, int(len(chk) * 0.6)):     # tolerate live-game churn
            self.ee_base = None
            return None
        self.ee_base = base
        return base

    def read_block(self, ps2_addr: int, size: int) -> bytes:
        assert self.ee_base is not None
        raw = self._read_raw(self.ee_base + (ps2_addr & EE_MASK), size)
        if raw is None:
            raise OSError("direct process read failed for block")
        return raw


if sys.platform == "win32":
    # --- Win32 backend (ReadProcessMemory) -----------------------------------
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _HANDLE = wintypes.HANDLE
    _LPCVOID = wintypes.LPCVOID
    _SIZE_T = ctypes.c_size_t
    kernel32.OpenProcess.restype = _HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [_HANDLE]
    kernel32.ReadProcessMemory.restype = wintypes.BOOL
    kernel32.ReadProcessMemory.argtypes = [_HANDLE, _LPCVOID, wintypes.LPVOID, _SIZE_T, ctypes.POINTER(_SIZE_T)]
    kernel32.VirtualQueryEx.restype = _SIZE_T
    kernel32.VirtualQueryEx.argtypes = [_HANDLE, _LPCVOID, wintypes.LPVOID, _SIZE_T]
    kernel32.CreateToolhelp32Snapshot.restype = _HANDLE
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.Process32FirstW.argtypes = [_HANDLE, wintypes.LPVOID]
    kernel32.Process32NextW.argtypes = [_HANDLE, wintypes.LPVOID]

    PROCESS_QUERY_INFORMATION = 0x0400
    PROCESS_VM_READ = 0x0010
    MEM_COMMIT = 0x1000
    PAGE_READWRITE = 0x04
    PAGE_READONLY = 0x02
    PAGE_EXECUTE_READWRITE = 0x40
    PAGE_WRITECOPY = 0x08
    PAGE_EXECUTE_READ = 0x20
    _READABLE = (PAGE_READWRITE, PAGE_READONLY, PAGE_EXECUTE_READWRITE,
                 PAGE_WRITECOPY, PAGE_EXECUTE_READ)

    class MEMORY_BASIC_INFORMATION(ctypes.Structure):
        _fields_ = [("BaseAddress", ctypes.c_void_p),
                    ("AllocationBase", ctypes.c_void_p),
                    ("AllocationProtect", wintypes.DWORD),
                    ("__align", wintypes.DWORD),
                    ("RegionSize", ctypes.c_size_t),
                    ("State", wintypes.DWORD),
                    ("Protect", wintypes.DWORD),
                    ("Type", wintypes.DWORD),
                    ("__align2", wintypes.DWORD)]

    def find_pcsx2_pid() -> Optional[int]:
        # Use the toolhelp snapshot via ctypes to avoid spawning processes.
        TH32CS_SNAPPROCESS = 0x2

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                        ("th32ProcessID", wintypes.DWORD),
                        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                        ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]

        snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        INVALID = ctypes.c_void_p(-1).value
        if not snap or snap == INVALID:
            return None
        pe = PROCESSENTRY32W()
        pe.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        pid = None
        if kernel32.Process32FirstW(snap, ctypes.byref(pe)):
            while True:
                if pe.szExeFile.lower().startswith("pcsx2-qt"):
                    pid = pe.th32ProcessID
                    break
                if not kernel32.Process32NextW(snap, ctypes.byref(pe)):
                    break
        kernel32.CloseHandle(snap)
        return pid

    class RpmReader(_ReaderBase):
        def __init__(self, pid: int):
            self.pid = pid
            self.h = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
            if not self.h:
                raise OSError(f"OpenProcess failed (err {ctypes.get_last_error()})")
            self.ee_base: Optional[int] = None  # host address of PS2 addr 0

        def close(self):
            if self.h:
                kernel32.CloseHandle(self.h)
                self.h = None

        def _read_raw(self, host_addr: int, size: int) -> Optional[bytes]:
            buf = ctypes.create_string_buffer(size)
            got = ctypes.c_size_t(0)
            ok = kernel32.ReadProcessMemory(self.h, ctypes.c_void_p(host_addr),
                                            buf, size, ctypes.byref(got))
            if not ok or got.value != size:
                return None
            return buf.raw

        def regions(self):
            addr = 0
            mbi = MEMORY_BASIC_INFORMATION()
            max_addr = 0x00007FFFFFFFFFFF
            while addr < max_addr:
                res = kernel32.VirtualQueryEx(self.h, ctypes.c_void_p(addr),
                                              ctypes.byref(mbi), ctypes.sizeof(mbi))
                if not res:
                    break
                base = mbi.BaseAddress or 0
                size = mbi.RegionSize
                if size == 0:
                    break
                if mbi.State == MEM_COMMIT and mbi.Protect in _READABLE:
                    yield (base, size, mbi.Protect)
                addr = base + size

else:
    # --- Linux backend (process_vm_readv + /proc) -----------------------------
    _libc = ctypes.CDLL("libc.so.6", use_errno=True)

    class _iovec(ctypes.Structure):
        _fields_ = [("iov_base", ctypes.c_void_p), ("iov_len", ctypes.c_size_t)]

    _libc.process_vm_readv.restype = ctypes.c_ssize_t
    _libc.process_vm_readv.argtypes = [ctypes.c_int, ctypes.POINTER(_iovec), ctypes.c_ulong,
                                       ctypes.POINTER(_iovec), ctypes.c_ulong, ctypes.c_ulong]

    def find_pcsx2_pid() -> Optional[int]:
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                with open(f"/proc/{entry}/comm", "rb") as f:
                    comm = f.read().strip().lower()
            except OSError:
                continue
            if comm.startswith(b"pcsx2"):       # pcsx2-qt, AppImage and flatpak alike
                return int(entry)
        return None

    PTRACE_HINT = ("process_vm_readv was denied (kernel.yama.ptrace_scope restricts "
                   "reading other processes). Allow it with:  "
                   "sudo sysctl kernel.yama.ptrace_scope=0")

    class RpmReader(_ReaderBase):
        def __init__(self, pid: int):
            self.pid = pid
            self.ee_base: Optional[int] = None  # host address of PS2 addr 0
            # probe now so a permission problem surfaces here with a useful
            # message instead of as silent scan failures later. Depending on the
            # kernel, ptrace restrictions show up either as EACCES opening
            # /proc/<pid>/maps or as EPERM from process_vm_readv.
            try:
                with open(f"/proc/{pid}/maps") as f:
                    f.readline()
            except PermissionError as e:
                raise PermissionError(PTRACE_HINT) from e
            tried = 0
            for base, size, _prot in self.regions():
                if self._read_raw(base, 4) is not None:
                    return
                if ctypes.get_errno() in (errno.EPERM, errno.EACCES):
                    raise PermissionError(PTRACE_HINT)
                tried += 1
                if tried >= 5:
                    break
            raise OSError(f"could not read pcsx2 process memory (pid {pid})")

        def _read_raw(self, host_addr: int, size: int) -> Optional[bytes]:
            buf = ctypes.create_string_buffer(size)
            local = _iovec(ctypes.cast(buf, ctypes.c_void_p), size)
            remote = _iovec(ctypes.c_void_p(host_addr), size)
            ctypes.set_errno(0)
            n = _libc.process_vm_readv(self.pid, ctypes.byref(local), 1,
                                       ctypes.byref(remote), 1, 0)
            if n != size:
                return None
            return buf.raw

        def regions(self):
            try:
                with open(f"/proc/{self.pid}/maps") as f:
                    lines = f.readlines()
            except OSError:
                return
            for ln in lines:
                parts = ln.split()
                if len(parts) < 2 or "r" not in parts[1]:
                    continue
                lo, hi = (int(x, 16) for x in parts[0].split("-"))
                size = hi - lo
                if size > 0x40000000:     # skip giant reservations; EE RAM is 32 MiB
                    continue
                yield (lo, size, parts[1])


class PineReader:
    """Block reads over PINE only - the fallback when direct process reads are
    unavailable. Full-window scans take a couple of seconds instead of ~0.1 s
    (actors are discovered more slowly), but the overlay's per-frame reads go
    over PINE anyway, so damage tracking is unaffected.

    PINE addresses ARE PS2 EE addresses, so there is no host base to locate."""

    def __init__(self, pc: pine.PineClient):
        self.pc = pc
        self.pid = -1
        self.ee_base = 0

    def close(self):
        pass

    def locate_ee_base(self, pc: pine.PineClient = None, samples: int = 0) -> int:
        return 0

    def read_block(self, ps2_addr: int, size: int) -> bytes:
        import numpy as np
        # One MsgRead64 per 8 bytes - half the commands of per-word reads, which
        # matters: the PINE server iterates commands one by one, and that loop is
        # what slow CPUs feel during full-window scans. The concatenated reply
        # payload is exactly the raw little-endian memory, so no per-value
        # unpacking is needed; request bytes are built vectorised (5 per command).
        qwords = size // 8
        cmds = np.zeros(qwords, dtype=[("op", "u1"), ("addr", "<u4")])
        cmds["op"] = pine.MSG_READ64
        cmds["addr"] = (ps2_addr + 8 * np.arange(qwords, dtype=np.uint64)).astype(np.uint32)
        raw = cmds.tobytes()
        out = bytearray()
        chunk = min((pine.MAX_IPC_RETURN_SIZE - 8) // 8, (pine.MAX_IPC_SIZE - 8) // 5)
        for i in range(0, qwords, chunk):
            k = min(chunk, qwords - i)
            out += self.pc._transact(raw[i * 5:(i + k) * 5])
        tail = size - qwords * 8
        if tail:
            out += self.pc.read_bytes(ps2_addr + qwords * 8, tail)
        return bytes(out)


# --- the scanner ------------------------------------------------------------
class Scanner:
    """Holds the EE RAM scan window and successive snapshots; supports value
    scans and differential (changed/increased/decreased) refinement."""

    def __init__(self, reader, start: int = DEFAULT_SCAN_START,
                 end: int = DEFAULT_SCAN_END):
        self.reader = reader
        self.start = start
        self.end = end
        self.size = end - start
        self.prev: Optional[bytes] = None  # last snapshot of [start,end)

    def snapshot(self) -> bytes:
        data = self.reader.read_block(self.start, self.size)
        self.prev = data
        return data

    def _addr_of(self, off: int) -> int:
        return self.start + off

    # -- value scans ---------------------------------------------------------
    def scan_float(self, target: float, tol: float = 0.5,
                   lo: float = -1e9, hi: float = 1e9) -> List[int]:
        data = self.reader.read_block(self.start, self.size)
        self.prev = data
        out = []
        n = len(data) - 3
        unpack = struct.unpack_from
        for off in range(0, n, 4):
            (f,) = unpack("<f", data, off)
            if f == f and abs(f) < 1e30:  # not NaN/inf
                if abs(f - target) <= tol:
                    out.append(self._addr_of(off))
        return out

    def scan_u32(self, target: int) -> List[int]:
        data = self.reader.read_block(self.start, self.size)
        self.prev = data
        tb = struct.pack("<I", target & 0xFFFFFFFF)
        out = []
        idx = data.find(tb)
        while idx != -1:
            if idx % 4 == 0:
                out.append(self._addr_of(idx))
            idx = data.find(tb, idx + 1)
        return out

    # -- differential scans over the whole window ---------------------------
    def diff_changed_floats(self, prev: bytes, cur: bytes,
                            min_abs: float = 0.0, max_abs: float = 1e7,
                            page: int = 4096) -> List[Tuple[int, float, float]]:
        """Return [(addr, old, new)] for 4-byte floats that changed, skipping
        unchanged pages for speed. Filters out NaN/inf and absurd magnitudes."""
        out = []
        unpack = struct.unpack_from
        nlen = min(len(prev), len(cur))
        for pbase in range(0, nlen, page):
            pend = min(pbase + page, nlen)
            if prev[pbase:pend] == cur[pbase:pend]:
                continue
            start_off = pbase - (pbase % 4)
            for off in range(start_off, pend - 3, 4):
                if prev[off:off + 4] == cur[off:off + 4]:
                    continue
                (a,) = unpack("<f", prev, off)
                (b,) = unpack("<f", cur, off)
                if a != a or b != b:
                    continue
                if abs(b) > max_abs or abs(a) > max_abs:
                    continue
                if abs(b - a) < min_abs:
                    continue
                out.append((self._addr_of(off), a, b))
        return out

    def values_at(self, addrs: List[int], fmt: str = "<f") -> Dict[int, float]:
        """Read current values for a set of addresses (single block re-read)."""
        data = self.reader.read_block(self.start, self.size)
        self.prev = data
        sz = struct.calcsize(fmt)
        res = {}
        for a in addrs:
            off = a - self.start
            if 0 <= off <= len(data) - sz:
                (v,) = struct.unpack_from(fmt, data, off)
                res[a] = v
        return res


def open_reader(pid: Optional[int], pc: pine.PineClient):
    """RpmReader if direct process reads work, else the PineReader fallback
    (with a one-line note about why)."""
    if pid is not None:
        try:
            return RpmReader(pid)
        except (OSError, PermissionError) as e:
            print(f"note: direct memory reads unavailable ({e})")
    else:
        print("note: pcsx2 process not found by name")
    print("      falling back to PINE-only reads - enemy scans will be slower.", flush=True)
    return PineReader(pc)


def open_default(pause_for_locate: bool = True) -> Tuple[pine.PineClient, object, Scanner]:
    import emu
    pc = pine.PineClient().connect()
    rpm = open_reader(find_pcsx2_pid(), pc)
    if isinstance(rpm, PineReader):
        return pc, rpm, Scanner(rpm)        # PS2 addresses directly; nothing to locate
    was_running = pc.status() == 0
    if pause_for_locate:
        emu.ensure_paused(pc)
    base = rpm.locate_ee_base(pc)
    if pause_for_locate and was_running:
        emu.ensure_running(pc)
    if base is None:
        raise RuntimeError("could not locate EE RAM base via PINE oracle")
    return pc, rpm, Scanner(rpm)


if __name__ == "__main__":
    pc = pine.PineClient().connect()
    print("game:", pc.title(), pc.game_id(), "status", pc.status())
    pid = find_pcsx2_pid()
    print("pcsx2 pid:", pid)
    rpm = open_reader(pid, pc)
    base = rpm.locate_ee_base(pc)
    print("EE base host addr:", hex(base) if base else base)
    if base is not None:
        # cross-check a few reads direct vs PINE
        import random
        random.seed(1)
        ok = True
        for _ in range(8):
            a = 0x00100000 + random.randint(0, 0x01E00000) & ~3
            v_pine = pc.read32(a)
            v_rpm = struct.unpack("<I", rpm.read_block(a, 4))[0]
            flag = "ok" if v_pine == v_rpm else "MISMATCH"
            if v_pine != v_rpm:
                ok = False
            print(f"  [{a:08X}] pine={v_pine:08X} rpm={v_rpm:08X} {flag}")
        print("cross-check:", "PASS" if ok else "FAIL")
        # bulk read timing
        import time
        t = time.time()
        blk = rpm.read_block(DEFAULT_SCAN_START, DEFAULT_SCAN_END - DEFAULT_SCAN_START)
        print(f"bulk read {len(blk)} bytes in {(time.time()-t)*1000:.0f} ms")
