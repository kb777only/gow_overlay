"""overlay.py - transparent, click-through, always-on-top damage-number overlay
for the PCSX2 display, with true per-pixel alpha (UpdateLayeredWindow).

Text is rendered with PIL (anti-aliased, dark-outlined, with a fiery glow) and
animated God-of-War style: a quick scale "punch" on spawn, an ease-out rise, and
a smooth alpha fade-out. Bigger hits run hotter on a blood -> fire -> gold ramp.
Each number is anchored to its enemy via set_target(); the on-screen position
lerps toward the target so tracking never snaps. Runs its own thread + message
loop; the app calls spawn()/set_target()/set_markers() and the overlay animates."""
import ctypes
import threading
import time
import math
import random
from ctypes import wintypes

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

import winutil
from settings import S, dmg_color, dmg_size, impact_strength

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

# --- window styles / constants ---
WS_POPUP = 0x80000000
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
SW_SHOWNOACTIVATE = 4
HWND_TOPMOST = -1
SWP_NOACTIVATE = 0x0010
SWP_NOZORDER = 0x0004
WM_TIMER = 0x0113
WM_DESTROY = 0x0002
ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
BI_RGB = 0
DIB_RGB_COLORS = 0

# impact-FX durations / flash tint (not exposed in the GUI). dmg_color / dmg_size /
# impact_strength and all behavioural tunables live in settings.py (settings.json).
SHAKE_DUR = 0.28
FLASH_DUR = 0.42
FLASH_COLOR = (255, 150, 70)
CALIB_W, CALIB_H = 1124.0, 676.0     # resolution the camera projection is calibrated for


def RGB(r, g, b):
    return (int(r), int(g), int(b))


# --- Win32 structs ---
class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_byte), ("BlendFlags", ctypes.c_byte),
                ("SourceConstantAlpha", ctypes.c_byte), ("AlphaFormat", ctypes.c_byte)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASS(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


user32.DefWindowProcW.restype = ctypes.c_longlong
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.CreateWindowExW.restype = wintypes.HWND
user32.UpdateLayeredWindow.argtypes = [wintypes.HWND, wintypes.HDC, ctypes.POINTER(POINT),
                                       ctypes.POINTER(SIZE), wintypes.HDC, ctypes.POINTER(POINT),
                                       wintypes.COLORREF, ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(BITMAPINFO), wintypes.UINT,
                                   ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
user32.GetDC.restype = wintypes.HDC
user32.GetDC.argtypes = [wintypes.HWND]
user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.UINT, ctypes.c_void_p]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wintypes.UINT]


def _ease_out(t):
    return 1 - (1 - t) * (1 - t)


def _smoothstep(a, b, x):
    if x <= a:
        return 0.0
    if x >= b:
        return 1.0
    t = (x - a) / (b - a)
    return t * t * (3 - 2 * t)


class FloatingNumber:
    __slots__ = ("x", "y", "tx", "ty", "text", "color", "size", "born", "ttl", "rise", "epic")

    def __init__(self, x, y, text, color, size, ttl=1.45, rise=48.0, epic=0.0):
        self.x = float(x); self.y = float(y); self.tx = float(x); self.ty = float(y)
        self.text = text; self.color = color; self.size = size
        self.born = time.time(); self.ttl = ttl; self.rise = rise; self.epic = epic

    def set_target(self, tx, ty):
        self.tx = float(tx); self.ty = float(ty)


class Overlay:
    def __init__(self, target_hwnd):
        self.target = target_hwnd
        self.hwnd = None
        self.items = []
        self._markers = []
        self.lock = threading.Lock()
        self.thread = None
        self._running = False
        self._cache = {}
        self._ringcache = {}
        self._vignette = None
        self._shake = (0.0, 0.0)        # (amplitude, start_time)
        self._flash = (0.0, 0.0)        # (intensity, start_time)
        self._w = self._h = 0
        self._geom = None               # last (x,y,w,h) pushed to the window
        self._screen_dc = None
        self._mem_dc = None
        self._dib = None
        self._buf = None        # numpy view of the DIB (h,w,4) BGRA top-down

    # public API -------------------------------------------------------------
    def spawn(self, cx, cy, text, color=(255, 90, 40), size=34, epic=0.0):
        n = S["numbers"]; e = S["epic"]
        ttl = n["ttl"] * (1.0 + e["extra_ttl"] * epic)
        fn = FloatingNumber(cx, cy, text, color, size, ttl=ttl, rise=n["rise"], epic=epic)
        with self.lock:
            self.items.append(fn)
        if epic > 0:
            self.trigger_impact(epic)
        return fn

    def trigger_impact(self, strength):
        """Fire a brief screenshake + warm edge-flash, scaled by strength (0..1)."""
        now = time.time(); e = S["epic"]
        amp = (1.5 + 4.0 * strength) * e["shake_amount"] if e["shake_enabled"] else 0.0
        fin = (0.12 + 0.30 * strength) * e["flash_amount"] if e["flash_enabled"] else 0.0
        self._shake = (amp, now)
        self._flash = (fin, now)

    def set_markers(self, marks):
        with self.lock:
            self._markers = list(marks)

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        for _ in range(100):
            if self.hwnd:
                break
            time.sleep(0.02)
        return self

    def stop(self):
        self._running = False

    # font / tile rendering --------------------------------------------------
    def _font(self, size):
        for name in ("ariblk.ttf", "impact.ttf", "arialbd.ttf", "arial.ttf"):
            try:
                return ImageFont.truetype(name, size)
            except Exception:
                continue
        return ImageFont.load_default()

    def _tile(self, text, color, size):
        """Render a glow+outline+fill number to an RGBA np array; cache it.
        Returns (rgba_uint8 HxWx4, center_x, center_y)."""
        key = (text, color, size)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        size = max(12, size)
        font = self._font(size)
        sw = max(2, size // 9)
        pad = max(8, size // 2)
        meas = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
        bb = meas.textbbox((0, 0), text, font=font, stroke_width=sw)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        W, H = tw + 2 * pad, th + 2 * pad
        ox, oy = pad - bb[0], pad - bb[1]
        # fiery glow underneath
        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(glow).text((ox, oy), text, font=font, fill=(color[0], color[1], color[2], 255))
        glow = glow.filter(ImageFilter.GaussianBlur(max(2, size // 6)))
        a = glow.split()[3].point(lambda v: int(v * 0.75))
        glow.putalpha(a)
        img = Image.alpha_composite(Image.new("RGBA", (W, H), (0, 0, 0, 0)), glow)
        # crisp number with dark outline
        ImageDraw.Draw(img).text((ox, oy), text, font=font, fill=(color[0], color[1], color[2], 255),
                                 stroke_width=sw, stroke_fill=(0, 0, 0, 245))
        arr = np.asarray(img).astype(np.float32)        # (H,W,4) RGBA
        out = (arr, pad + tw / 2.0, pad + th / 2.0)
        if len(self._cache) < 600:
            self._cache[key] = out
        return out

    def _ring_tile(self, r, color):
        """A soft expanding shockwave ring, cached by integer radius."""
        r = max(6, int(r))
        key = (r, color)
        c = self._ringcache.get(key)
        if c is not None:
            return c
        pad = 8
        S = 2 * r + 2 * pad
        img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        w = max(2, int(r * 0.11))
        ImageDraw.Draw(img).ellipse([pad, pad, pad + 2 * r, pad + 2 * r],
                                    outline=(color[0], color[1], color[2], 255), width=w)
        img = img.filter(ImageFilter.GaussianBlur(1.6))
        out = (np.asarray(img).astype(np.float32), S / 2.0, S / 2.0)
        if len(self._ringcache) < 240:
            self._ringcache[key] = out
        return out

    # internals --------------------------------------------------------------
    def _ensure_surface(self, w, h):
        if w == self._w and h == self._h and self._buf is not None:
            return
        if self._dib:
            gdi32.DeleteObject(self._dib)
        self._w, self._h = w, h
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h        # top-down
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = BI_RGB
        bits = ctypes.c_void_p()
        self._dib = gdi32.CreateDIBSection(self._screen_dc, ctypes.byref(bmi), DIB_RGB_COLORS,
                                           ctypes.byref(bits), None, 0)
        gdi32.SelectObject(self._mem_dc, self._dib)
        cbuf = (ctypes.c_ubyte * (w * h * 4)).from_address(bits.value)
        self._buf = np.frombuffer(cbuf, dtype=np.uint8).reshape(h, w, 4)
        # radial edge mask for the impact flash (0 centre -> 1 at edges/corners)
        ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
        dx = (xs - w / 2.0) / (w / 2.0); dy = (ys - h / 2.0) / (h / 2.0)
        d = np.clip((np.sqrt(dx * dx + dy * dy) - 0.5) / 0.6, 0, 1)
        self._vignette = (d * d * (3 - 2 * d)).astype(np.float32)

    def _run(self):
        hInst = ctypes.WinDLL("kernel32").GetModuleHandleW(None)
        clsname = "GowDmgOverlayA"
        self._wndproc = WNDPROC(self._on_msg)
        wc = WNDCLASS()
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = hInst
        wc.lpszClassName = clsname
        user32.RegisterClassW(ctypes.byref(wc))
        x, y, w, h = winutil.client_rect_on_screen(self.target)
        exstyle = (WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST |
                   WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
        self.hwnd = user32.CreateWindowExW(exstyle, clsname, "overlay", WS_POPUP,
                                           x, y, w, h, None, None, hInst, None)
        self._screen_dc = user32.GetDC(0)
        self._mem_dc = gdi32.CreateCompatibleDC(self._screen_dc)
        self._ensure_surface(w, h)
        user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
        user32.SetTimer(self.hwnd, 1, 16, None)         # ~60 Hz
        self._running = True
        msg = wintypes.MSG()
        while self._running and user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _on_msg(self, hwnd, msg, wp, lp):
        if msg == WM_TIMER:
            try:
                self._render()
            except Exception:
                pass
            return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wp, lp)

    def _composite(self, surf, tile, ax, ay, alpha):
        """Alpha-composite an RGBA tile (straight) onto the premultiplied float
        surface (h,w,4 RGBA premultiplied 0-255) centered at (ax,ay)."""
        arr, cx, cy = tile
        H, W = arr.shape[:2]
        x0 = int(round(ax - cx)); y0 = int(round(ay - cy))
        x1, y1 = x0 + W, y0 + H
        sh, sw = surf.shape[:2]
        tx0 = max(0, -x0); ty0 = max(0, -y0)
        cx0 = max(0, x0); cy0 = max(0, y0)
        cx1 = min(sw, x1); cy1 = min(sh, y1)
        if cx1 <= cx0 or cy1 <= cy0:
            return
        tw = cx1 - cx0; thh = cy1 - cy0
        src = arr[ty0:ty0 + thh, tx0:tx0 + tw]
        sa = (src[:, :, 3:4] / 255.0) * alpha          # effective src alpha (0-1)
        src_pm = src[:, :, :3] * sa                    # premultiplied src rgb
        reg = surf[cy0:cy1, cx0:cx1]
        reg[:, :, :3] = src_pm + reg[:, :, :3] * (1 - sa)
        reg[:, :, 3:4] = sa * 255.0 + reg[:, :, 3:4] * (1 - sa)

    def _render(self):
        S.maybe_reload()                       # live-apply settings changes
        n = S["numbers"]; e = S["epic"]
        lerp = n["anchor_lerp"]; base_pop = n["pop"]; fade_start = n["fade_start"]
        ring_on = e["ring_enabled"]; whitehot_on = e["whitehot_enabled"]
        x, y, w, h = winutil.client_rect_on_screen(self.target)
        self._ensure_surface(w, h)
        if (x, y, w, h) != self._geom:        # follow the game window live (move + RESIZE)
            self._geom = (x, y, w, h)
            user32.SetWindowPos(self.hwnd, None, x, y, w, h, SWP_NOACTIVATE | SWP_NOZORDER)
        surf = np.zeros((h, w, 4), np.float32)
        now = time.time()
        # map the calibrated projection space onto the actual game-render area inside
        # the client (letterbox-aware) so everything scales with the window/fullscreen
        ar = CALIB_W / CALIB_H
        if w / max(1, h) > ar:
            rh = float(h); rw = rh * ar
        else:
            rw = float(w); rh = rw / ar
        rx0 = (w - rw) * 0.5; ry0 = (h - rh) * 0.5
        sc = rw / CALIB_W

        def to_screen(px, py):
            return rx0 + px * sc, ry0 + py * sc

        # decaying screenshake offset (in calibrated px; scaled with the rest)
        shx = shy = 0.0
        amp, st0 = self._shake
        sage = now - st0
        if amp > 0 and sage < SHAKE_DUR:
            dk = (1 - sage / SHAKE_DUR) ** 1.5
            shx = random.uniform(-1, 1) * amp * dk
            shy = random.uniform(-1, 1) * amp * dk
        with self.lock:
            alive = []
            for it in self.items:
                age = now - it.born
                if age > it.ttl:
                    continue
                alive.append(it)
                it.x += (it.tx - it.x) * lerp
                it.y += (it.ty - it.y) * lerp
                t = age / it.ttl
                pop = 1.0 + (base_pop + e["extra_pop"] * it.epic) * max(0.0, 1 - age / 0.13) ** 2
                anim = pop * (1.0 - 0.06 * t)
                alpha = 1.0 - _smoothstep(fade_start, 1.0, t)
                yoff = it.rise * _ease_out(t)
                ax, ay = to_screen(it.x + shx, it.y - yoff + shy)
                # expanding shockwave ring at the impact point (epic hits)
                if ring_on and it.epic > 0 and age < 0.34:
                    rr = (10 + _ease_out(age / 0.34) * (38 + 46 * it.epic)) * sc
                    ra = max(0.0, (1 - age / 0.36)) * (0.55 + 0.45 * it.epic)
                    rcx, rcy = to_screen(it.x + shx, it.y + shy)
                    self._composite(surf, self._ring_tile(rr, (255, 205, 120)), rcx, rcy, ra)
                size = max(12, int(round(it.size * anim * sc / 2) * 2))
                self._composite(surf, self._tile(it.text, it.color, size), ax, ay, alpha)
                # white-hot flash on spawn (epic hits)
                if whitehot_on and it.epic > 0 and age < 0.12:
                    self._composite(surf, self._tile(it.text, (255, 255, 255), size),
                                    ax, ay, (1 - age / 0.12) * 0.85 * alpha)
            for (mx, my, mtext, mcolor) in self._markers:
                bx, by = to_screen(mx + shx, my + shy)
                self._composite(surf, self._tile(mtext, mcolor, max(12, int(26 * sc))), bx, by, 1.0)
            self.items = alive
        # warm edge-flash on impact
        fint, ft0 = self._flash
        fage = now - ft0
        if fint > 0 and fage < FLASH_DUR and self._vignette is not None:
            m = (self._vignette * (fint * (1 - fage / FLASH_DUR)))[:, :, None]
            col = np.array(FLASH_COLOR, np.float32)
            surf[:, :, :3] = col * m + surf[:, :, :3] * (1 - m)
            surf[:, :, 3:4] = m * 255.0 + surf[:, :, 3:4] * (1 - m)
        # to premultiplied BGRA top-down for UpdateLayeredWindow
        np.clip(surf, 0, 255, out=surf)
        bgra = self._buf
        bgra[:, :, 0] = surf[:, :, 2]
        bgra[:, :, 1] = surf[:, :, 1]
        bgra[:, :, 2] = surf[:, :, 0]
        bgra[:, :, 3] = surf[:, :, 3]
        pt_dst = POINT(x, y); psize = SIZE(w, h); pt_src = POINT(0, 0)
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        user32.UpdateLayeredWindow(self.hwnd, self._screen_dc, ctypes.byref(pt_dst),
                                   ctypes.byref(psize), self._mem_dc, ctypes.byref(pt_src),
                                   0, ctypes.byref(blend), ULW_ALPHA)


if __name__ == "__main__":
    import random
    hwnd = winutil.find_pcsx2_window()
    assert hwnd, "no pcsx2 window"
    ov = Overlay(hwnd).start()
    t0 = time.time()
    while time.time() - t0 < 8:
        dmg = random.randint(3, 90)
        x = random.randint(300, 800); y = random.randint(250, 450)
        ov.spawn(x, y, str(dmg), dmg_color(dmg), dmg_size(dmg), epic=impact_strength(dmg))
        time.sleep(0.5)
    print("overlay demo done")
