"""
pine.py - Minimal, robust client for PCSX2's PINE IPC protocol.

On Windows PCSX2 exposes PINE as a TCP server on 127.0.0.1:<slot> (default
slot/port 28011). On Linux/macOS it is a Unix domain socket instead:
$XDG_RUNTIME_DIR/pcsx2.sock (/tmp if XDG_RUNTIME_DIR is unset), with a
".<slot>" suffix for non-default slots. The wire format is identical on both
(confirmed against pcsx2/PINE.cpp):

  Request:
    u32  total_length      (little-endian, INCLUDES these 4 bytes, must be >= 4)
    ... one or more commands packed back to back ...

  Command layout:
    u8 opcode, then opcode-specific args
      MsgRead8/16/32/64   = 0/1/2/3 : + u32 addr            -> reply: 1/2/4/8 value bytes
      MsgWrite8/16/32/64  = 4/5/6/7 : + u32 addr + N value  -> reply: (nothing)
      MsgVersion          = 8       : (no args)             -> reply: u32 len + string
      MsgSaveState        = 9       : + u8 slot
      MsgLoadState        = 0xA     : + u8 slot
      MsgTitle            = 0xB     : (no args)             -> reply: u32 len + string
      MsgID               = 0xC     : (no args)             -> reply: u32 len + string (serial)
      MsgUUID             = 0xD     : (no args)             -> reply: u32 len + string
      MsgGameVersion      = 0xE     : (no args)             -> reply: u32 len + string
      MsgStatus           = 0xF     : (no args)             -> reply: u32 status

  Reply:
    u32  total_length      (little-endian, INCLUDES these 4 bytes + the status byte)
    u8   result            (IPC_OK = 0, IPC_FAIL = 0xFF)
    ... per-command result bytes, concatenated in request order ...

Addresses are PS2 EE virtual addresses (main RAM is 32 MiB, 0x00000000..0x01FFFFFF;
game data typically lives at 0x00100000+). Values are little-endian.
"""

from __future__ import annotations

import os
import socket
import struct
import sys
import threading
from typing import Iterable, List, Sequence, Tuple, Union

# --- opcodes -----------------------------------------------------------------
MSG_READ8, MSG_READ16, MSG_READ32, MSG_READ64 = 0, 1, 2, 3
MSG_WRITE8, MSG_WRITE16, MSG_WRITE32, MSG_WRITE64 = 4, 5, 6, 7
MSG_VERSION = 8
MSG_SAVESTATE, MSG_LOADSTATE = 9, 0xA
MSG_TITLE, MSG_ID, MSG_UUID, MSG_GAMEVERSION, MSG_STATUS = 0xB, 0xC, 0xD, 0xE, 0xF

IPC_OK = 0
IPC_FAIL = 0xFF

# Server limits (pcsx2/PINE.cpp). Keep our requests/replies safely under these.
MAX_IPC_SIZE = 650000
MAX_IPC_RETURN_SIZE = 450000

# type-name -> (read opcode, result size in bytes, struct unpack format)
_READ_TYPES = {
    "u8":  (MSG_READ8,  1, "<B"),
    "s8":  (MSG_READ8,  1, "<b"),
    "u16": (MSG_READ16, 2, "<H"),
    "s16": (MSG_READ16, 2, "<h"),
    "u32": (MSG_READ32, 4, "<I"),
    "s32": (MSG_READ32, 4, "<i"),
    "u64": (MSG_READ64, 8, "<Q"),
    "s64": (MSG_READ64, 8, "<q"),
    "f32": (MSG_READ32, 4, "<f"),
    "f64": (MSG_READ64, 8, "<d"),
}

ReadReq = Tuple[str, int]  # (type_name, address)


class PineError(RuntimeError):
    pass


class PineClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 28011, timeout: float = 3.0,
                 socket_path: str | None = None):
        self.host = host
        self.port = port               # the PINE "slot" (also names the Unix socket)
        self.timeout = timeout
        self.socket_path = socket_path
        self._sock: socket.socket | None = None
        # PCSX2's PINE server handles a single connection, and several overlay
        # threads (frame loop + enemy scanner) share this client. Serialize
        # whole transactions or the threads consume each other's reply bytes.
        self._lock = threading.Lock()

    def _default_socket_path(self) -> str:
        # matches pcsx2/PINE.cpp: $XDG_RUNTIME_DIR/pcsx2.sock (or /tmp), and a
        # ".<slot>" suffix when a non-default slot is configured. A flatpak
        # PCSX2 gets its own runtime subdir, so probe that too.
        base = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
        name = "pcsx2.sock"
        if self.port != 28011:
            name += f".{self.port}"
        for d in (base, os.path.join(base, "app", "net.pcsx2.PCSX2"), "/tmp"):
            p = os.path.join(d, name)
            if os.path.exists(p):
                return p
        return os.path.join(base, name)

    # -- connection ----------------------------------------------------------
    def connect(self) -> "PineClient":
        if sys.platform == "win32":
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(self.timeout)
            s.connect((self.host, self.port))
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        else:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(self.timeout)
            s.connect(self.socket_path or self._default_socket_path())
        self._sock = s
        return self

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def __enter__(self):
        return self.connect()

    def __exit__(self, *exc):
        self.close()

    # -- low-level transaction ----------------------------------------------
    def _recv_exact(self, n: int) -> bytes:
        assert self._sock is not None
        buf = bytearray()
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise PineError("PINE socket closed mid-reply (is a game running?)")
            buf += chunk
        return bytes(buf)

    def _transact(self, body: bytes) -> bytes:
        """Send one framed request `body` (the packed commands, WITHOUT the
        length header) and return the reply payload (WITHOUT length+status).
        Thread-safe: one transaction at a time over the shared socket."""
        with self._lock:
            try:
                if self._sock is None:
                    self.connect()
                msg = struct.pack("<I", len(body) + 4) + body
                assert self._sock is not None
                self._sock.sendall(msg)

                header = self._recv_exact(4)
                (total,) = struct.unpack("<I", header)
                if total < 5:
                    raise PineError(f"bad reply length {total}")
                rest = self._recv_exact(total - 4)
                status = rest[0]
                if status != IPC_OK:
                    raise PineError(f"PINE returned IPC_FAIL (0x{status:02X})")
                return rest[1:]
            except (OSError, PineError):
                self.close()    # the stream may be desynced: reconnect next call
                raise

    # -- batched reads (the workhorse) --------------------------------------
    def batch_read(self, reqs: Sequence[ReadReq]) -> List[Union[int, float]]:
        """Read many typed values in as few round-trips as possible.

        `reqs` is a sequence of (type_name, address). Returns values in order.
        Automatically splits into multiple transactions to respect the
        server's max request/reply sizes.
        """
        results: List[Union[int, float]] = []
        i = 0
        n = len(reqs)
        while i < n:
            body = bytearray()
            specs: List[Tuple[int, str]] = []  # (result_size, fmt)
            req_bytes = 0
            ret_bytes = 0
            while i < n:
                tname, addr = reqs[i]
                opcode, size, fmt = _READ_TYPES[tname]
                # +5 request bytes (opcode + u32 addr), +size reply bytes
                if (req_bytes + 5 > MAX_IPC_SIZE - 8) or (ret_bytes + size > MAX_IPC_RETURN_SIZE - 8):
                    break
                body += struct.pack("<BI", opcode, addr & 0xFFFFFFFF)
                specs.append((size, fmt))
                req_bytes += 5
                ret_bytes += size
                i += 1
            payload = self._transact(bytes(body))
            off = 0
            for size, fmt in specs:
                (v,) = struct.unpack_from(fmt, payload, off)
                results.append(v)
                off += size
        return results

    # -- convenience single reads -------------------------------------------
    def read8(self, addr: int) -> int:   return int(self.batch_read([("u8", addr)])[0])
    def read16(self, addr: int) -> int:  return int(self.batch_read([("u16", addr)])[0])
    def read32(self, addr: int) -> int:  return int(self.batch_read([("u32", addr)])[0])
    def read64(self, addr: int) -> int:  return int(self.batch_read([("u64", addr)])[0])
    def read_s32(self, addr: int) -> int: return int(self.batch_read([("s32", addr)])[0])
    def read_float(self, addr: int) -> float: return float(self.batch_read([("f32", addr)])[0])

    def read_bytes(self, addr: int, n: int) -> bytes:
        """Read a contiguous block of `n` bytes. Uses Read32 for the aligned
        bulk and Read8 for the tail, batched, to minimise command count."""
        reqs: List[ReadReq] = []
        words = n // 4
        for w in range(words):
            reqs.append(("u32", addr + w * 4))
        tail = n - words * 4
        for t in range(tail):
            reqs.append(("u8", addr + words * 4 + t))
        vals = self.batch_read(reqs)
        out = bytearray()
        for w in range(words):
            out += struct.pack("<I", int(vals[w]))
        for t in range(tail):
            out += struct.pack("<B", int(vals[words + t]))
        return bytes(out)

    # -- writes --------------------------------------------------------------
    def _write(self, opcode: int, addr: int, value_bytes: bytes) -> None:
        body = struct.pack("<BI", opcode, addr & 0xFFFFFFFF) + value_bytes
        self._transact(body)

    def write8(self, addr: int, v: int) -> None:  self._write(MSG_WRITE8,  addr, struct.pack("<B", v & 0xFF))
    def write16(self, addr: int, v: int) -> None: self._write(MSG_WRITE16, addr, struct.pack("<H", v & 0xFFFF))
    def write32(self, addr: int, v: int) -> None: self._write(MSG_WRITE32, addr, struct.pack("<I", v & 0xFFFFFFFF))
    def write_float(self, addr: int, v: float) -> None: self._write(MSG_WRITE32, addr, struct.pack("<f", v))

    # -- status / identity ---------------------------------------------------
    def _read_string_reply(self, opcode: int) -> str:
        payload = self._transact(struct.pack("<B", opcode))
        if len(payload) < 4:
            return ""
        (slen,) = struct.unpack_from("<I", payload, 0)
        raw = payload[4:4 + slen]
        return raw.split(b"\x00", 1)[0].decode("latin-1", "replace")

    def status(self) -> int:
        """0 = running, 1 = paused, 2 = shutdown."""
        payload = self._transact(struct.pack("<B", MSG_STATUS))
        (st,) = struct.unpack_from("<I", payload, 0)
        return st

    def version(self) -> str:      return self._read_string_reply(MSG_VERSION)
    def title(self) -> str:        return self._read_string_reply(MSG_TITLE)
    def game_id(self) -> str:      return self._read_string_reply(MSG_ID)
    def game_uuid(self) -> str:    return self._read_string_reply(MSG_UUID)
    def game_version(self) -> str: return self._read_string_reply(MSG_GAMEVERSION)


if __name__ == "__main__":
    # quick smoke test
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 28011
    with PineClient(port=port) as p:
        print("status     :", p.status())
        print("version    :", p.version())
        print("title      :", p.title())
        print("game_id    :", p.game_id())
        print("game_uuid  :", p.game_uuid())
        # dump a few words of low RAM
        for a in (0x00100000, 0x00100004, 0x00100008):
            print(f"  [{a:08X}] = 0x{p.read32(a):08X}")
