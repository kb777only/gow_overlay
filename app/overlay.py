"""overlay.py - transparent, click-through, always-on-top damage-number overlay
for the PCSX2 display, with true per-pixel alpha.

Text is rendered with PIL (anti-aliased, dark-outlined, with a fiery glow) and
animated God-of-War style: a quick scale "punch" on spawn, an ease-out rise, and
a smooth alpha fade-out. Bigger hits run hotter on a blood -> fire -> gold ramp.
Each number is anchored to its enemy via set_target(); the on-screen position
lerps toward the target so tracking never snaps. Runs its own thread + frame
loop; the app calls spawn()/set_target()/set_markers() and the overlay animates.

All rendering/animation here is platform-neutral (numpy premultiplied-RGBA
compositing); putting the pixels on screen is delegated to a small backend:
  overlay_win32.Backend - layered window + UpdateLayeredWindow
  overlay_x11.Backend   - ARGB override-redirect window + XPutImage (needs a
                          compositor; works on X11 and under XWayland)
"""
import math
import subprocess
import sys
import threading
import time
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

import winutil
from settings import S, dmg_color, dmg_size, impact_strength

if sys.platform == "win32":
    import overlay_win32 as _backend_mod
else:
    import overlay_x11 as _backend_mod

# impact-FX durations / flash tint (not exposed in the GUI). dmg_color / dmg_size /
# impact_strength and all behavioural tunables live in settings.py (settings.json).
SHAKE_DUR = 0.28
FLASH_DUR = 0.42
FLASH_COLOR = (255, 150, 70)
CALIB_W, CALIB_H = 1124.0, 676.0     # resolution the camera projection is calibrated for
FRAME_DT = 0.016                     # ~60 Hz while numbers/FX are on screen
IDLE_DT = 0.05                       # ~20 Hz window-follow ticks while blank

# --- animation lookups (built once; all effects index into these) -------------
_PHASES = 8                          # shimmer phases per cycle (tiles cached per phase)


def _build_fire_lut():
    """64-entry heat -> colour ramp: deep ember red up to white-hot."""
    stops = [(96, 6, 0), (190, 36, 6), (255, 96, 18),
             (255, 168, 40), (255, 228, 118), (255, 255, 215)]
    lut = np.zeros((64, 3), np.float32)
    for i in range(64):
        t = i / 63 * (len(stops) - 1)
        k = min(int(t), len(stops) - 2)
        f = t - k
        for c in range(3):
            lut[i, c] = stops[k][c] * (1 - f) + stops[k + 1][c] * f
    return lut


_FIRE = _build_fire_lut()
_NOISE = np.random.RandomState(7).rand(256).astype(np.float32)
_SPARK_COLORS = ((255, 224, 130), (255, 150, 52), (255, 92, 30))


def RGB(r, g, b):
    return (int(r), int(g), int(b))


def _ease_out(t):
    return 1 - (1 - t) * (1 - t)


def _smoothstep(a, b, x):
    if x <= a:
        return 0.0
    if x >= b:
        return 1.0
    t = (x - a) / (b - a)
    return t * t * (3 - 2 * t)


_FONT_CANDIDATES = (("ariblk.ttf", "impact.ttf", "arialbd.ttf", "arial.ttf")
                    if sys.platform == "win32" else
                    ("DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf",
                     "NotoSans-Bold.ttf", "FreeSansBold.ttf"))
_fc_match_path = None


def _fc_match_bold():
    """Ask fontconfig for the system bold sans font (Linux last resort)."""
    global _fc_match_path
    if _fc_match_path is None:
        try:
            _fc_match_path = subprocess.run(
                ["fc-match", "-f", "%{file}", "sans-serif:bold"],
                capture_output=True, text=True, timeout=3).stdout.strip()
        except Exception:
            _fc_match_path = ""
    return _fc_match_path


class FloatingNumber:
    __slots__ = ("x", "y", "tx", "ty", "text", "color", "size", "born", "ttl",
                 "rise", "epic", "phase0", "ix", "iy", "_fx", "_fxt")

    def __init__(self, x, y, text, color, size, ttl=1.45, rise=48.0, epic=0.0):
        self.x = float(x); self.y = float(y); self.tx = float(x); self.ty = float(y)
        self.text = text; self.color = color; self.size = size
        self.born = time.time(); self.ttl = ttl; self.rise = rise; self.epic = epic
        self.phase0 = random.random()      # de-syncs the shimmer between numbers
        self.ix = float(x); self.iy = float(y)   # impact anchor (fireball stays put)
        self._fx = None; self._fxt = 0.0         # cached flame layer + timestamp

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
        self._err = None
        self._cache = {}
        self._shapecache = {}           # (text,size) -> grayscale glyph masks
        self._ringcache = {}
        self._sparkcache = {}
        self._boomcache = {}
        self._particles = []            # ember sparks [[x,y,vx,vy,born,ttl,ci,sz]]
        self._last_t = time.time()
        self._vignette = None
        self._vignette_wh = (0, 0)
        self._shake = (0.0, 0.0)        # (amplitude, start_time)
        self._flash = (0.0, 0.0)        # (intensity, start_time)
        self._geom = None               # last (x,y,w,h) pushed to the window
        self._backend = None
        self._surf = None               # reused float32 compositing buffer
        self._blank = False             # window is currently fully transparent
        self._dirty = None              # bbox drawn this frame [x0,y0,x1,y1]
        self._prev_dirty = None         # bbox drawn last frame (to erase)

    # public API -------------------------------------------------------------
    def spawn(self, cx, cy, text, color=(255, 90, 40), size=34, epic=0.0):
        n = S["numbers"]; e = S["epic"]; an = S["anim"]
        ttl = n["ttl"] * (1.0 + e["extra_ttl"] * epic)
        fn = FloatingNumber(cx, cy, text, color, size, ttl=ttl, rise=n["rise"], epic=epic)
        with self.lock:
            self.items.append(fn)
            if epic > 0 and an["sparks_enabled"]:
                now = time.time()
                for _ in range(int((7 + 13 * epic) * an["sparks_amount"])):
                    ang = random.uniform(0, 2 * math.pi)
                    sp = random.uniform(35, 150) * (0.6 + epic)
                    self._particles.append(
                        [cx, cy, math.cos(ang) * sp, math.sin(ang) * sp * 0.7 - 40,
                         now, random.uniform(0.35, 0.85), random.randrange(3),
                         random.uniform(2.5, 4.5 + 3 * epic)])
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
            if self.hwnd or self._err:
                break
            time.sleep(0.02)
        if self._err:
            raise RuntimeError(f"overlay window creation failed: {self._err}")
        return self

    def stop(self):
        self._running = False

    # font / tile rendering --------------------------------------------------
    def _font(self, size):
        for name in _FONT_CANDIDATES:
            try:
                return ImageFont.truetype(name, size)
            except Exception:
                continue
        if sys.platform != "win32":
            path = _fc_match_bold()
            if path:
                try:
                    return ImageFont.truetype(path, size)
                except Exception:
                    pass
        return ImageFont.load_default()

    def _shape(self, text, size):
        """Grayscale masks for a number, rendered once per (text, size):
        (fill, outline, glow) uint8 HxW arrays + center. All coloured/animated
        variants below derive from these, so PIL only ever runs here."""
        key = (text, size)
        cached = self._shapecache.get(key)
        if cached is not None:
            return cached
        font = self._font(size)
        sw = max(2, size // 9)
        pad = max(8, size // 2)
        meas = ImageDraw.Draw(Image.new("L", (4, 4)))
        bb = meas.textbbox((0, 0), text, font=font, stroke_width=sw)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        W, H = tw + 2 * pad, th + 2 * pad
        ox, oy = pad - bb[0], pad - bb[1]
        fill_img = Image.new("L", (W, H), 0)
        ImageDraw.Draw(fill_img).text((ox, oy), text, font=font, fill=255)
        both_img = Image.new("L", (W, H), 0)
        ImageDraw.Draw(both_img).text((ox, oy), text, font=font, fill=255,
                                      stroke_width=sw, stroke_fill=255)
        glow_img = fill_img.filter(ImageFilter.GaussianBlur(max(2, size // 6)))
        fill = np.asarray(fill_img, np.uint8)
        outline = np.asarray(both_img, np.uint8).astype(np.int16)
        outline = np.clip(outline - fill, 0, 255).astype(np.uint8)
        out = (fill, outline, np.asarray(glow_img, np.uint8),
               pad + tw / 2.0, pad + th / 2.0)
        if len(self._shapecache) < 300:
            self._shapecache[key] = out
        return out

    def _tile(self, text, color, size, phase=0.0, solid=False):
        """A coloured glow+outline+fill number tile (uint8 RGBA + center).
        With gradients enabled the fill is a molten vertical ramp; `phase`
        shifts it (heat shimmer) and is quantized so tiles cache well."""
        an = S["anim"]
        grad = an["gradient_enabled"] and not solid
        pq = int(phase * _PHASES) % _PHASES if (grad and an["shimmer_enabled"]) else 0
        key = (text, color, size, grad, pq)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        size = max(12, size)
        fill_u, outline_u, glow_u, cx, cy = self._shape(text, size)
        f = fill_u.astype(np.float32) * (1.0 / 255.0)
        o = outline_u.astype(np.float32) * (0.96 / 255.0)
        gl = glow_u.astype(np.float32) * (0.75 / 255.0)
        H, W = f.shape
        col = np.array(color, np.float32)
        if grad:
            ys = np.linspace(0.0, 1.0, H, dtype=np.float32)[:, None]
            t = np.clip(ys + 0.16 * np.sin(2 * np.pi * (ys * 1.2 + pq / _PHASES)), 0, 1)
            c_top = col * 0.45 + np.array((255, 235, 170), np.float32) * 0.55
            c_bot = col * 0.55 + np.array((120, 10, 0), np.float32) * 0.45
            fill_rgb = c_top[None, None, :] * (1 - t[:, :, None]) + c_bot[None, None, :] * t[:, :, None]
        else:
            fill_rgb = col[None, None, :]
        # layered "over" compositing (premultiplied): glow, dark outline, fill
        P = np.zeros((H, W, 3), np.float32)
        A = np.zeros((H, W), np.float32)
        for lay_rgb, lay_a in ((col[None, None, :], gl),
                               (np.zeros((1, 1, 3), np.float32), o),
                               (fill_rgb, f)):
            P = lay_rgb * lay_a[:, :, None] + P * (1 - lay_a[:, :, None])
            A = lay_a + A * (1 - lay_a)
        arr = np.empty((H, W, 4), np.uint8)
        arr[:, :, :3] = np.clip(P / np.maximum(A, 1e-4)[:, :, None], 0, 255).astype(np.uint8)
        arr[:, :, 3] = np.clip(A * 255.0, 0, 255).astype(np.uint8)
        out = (arr, cx, cy)
        if len(self._cache) < 400:
            self._cache[key] = out
        return out

    def _flame(self, text, size, step, strength):
        """Flame licks rising off a glyph, derived from its mask with a few
        vectorized passes over the tile box (no PIL). Refreshed at ~30 Hz per
        burning number; `step` advances the flicker."""
        fill_u, outline_u, _g, cx, cy = self._shape(text, size)
        ext = max(8, int(size * 0.9 * min(1.5, max(0.2, strength))))
        ext += ext & 1                              # even, for the 2x upscale
        # the flame field is computed at HALF resolution and upscaled - it is
        # flickering noise, so this is visually free and ~4x cheaper
        base = np.maximum(fill_u[::2, ::2], outline_u[::2, ::2]).astype(np.float32) * (1.0 / 255.0)
        h, w = base.shape
        e2 = ext // 2
        out = np.zeros((h + e2, w), np.float32)
        out[e2:, :] = base * 0.45                   # roots hug the glyph
        cols = np.arange(w)
        dest = np.arange(h + e2)[:, None]
        for i, (fr, amp) in enumerate(((0.35, 0.8), (0.7, 0.45), (1.05, 0.22))):
            sh = max(1, int(e2 * fr))
            jit = (_NOISE[(cols * 13 + step * 29 + i * 101) % 256] * sh * 0.8).astype(np.int32)
            sr = dest - e2 + sh + jit[None, :]
            valid = (sr >= 0) & (sr < h)
            np.clip(sr, 0, h - 1, out=sr)
            out = np.maximum(out, base[sr, cols[None, :]] * valid * amp)
        # taper toward the tips + per-column gating so it breaks into tongues
        ramp = np.clip(dest / max(1.0, float(e2)), 0.0, 1.0) ** 0.8
        gate = (0.40 + 0.60 * _NOISE[(cols * 31 + step * 7) % 256])[None, :]
        out *= ramp * gate * min(1.0, strength)
        idx = np.clip(out * 63, 0, 63).astype(np.uint8)
        small = np.empty((h + e2, w, 4), np.float32)
        small[:, :, :3] = _FIRE[idx]
        small[:, :, 3] = np.clip(out, 0, 1) * 235
        arr = np.repeat(np.repeat(small, 2, axis=0), 2, axis=1)
        return arr, cx, cy + ext

    def _spark_tile(self, r, ci):
        """A small glowing ember dot (hot core, soft falloff), cached."""
        r = max(2, int(r))
        key = (r, ci)
        cached = self._sparkcache.get(key)
        if cached is not None:
            return cached
        ax = np.arange(-r, r + 1, dtype=np.float32)
        d = np.hypot(ax[:, None], ax[None, :]) / r
        a = np.clip(1 - d, 0, 1) ** 2
        col = np.array(_SPARK_COLORS[ci], np.float32)
        hot = np.clip(a * 1.7 - 0.7, 0, 1)[:, :, None]
        S2 = 2 * r + 1
        arr = np.empty((S2, S2, 4), np.float32)
        arr[:, :, :3] = col[None, None, :] * (1 - hot) + 255.0 * hot
        arr[:, :, 3] = a * 255.0
        out = (arr, r, r)
        if len(self._sparkcache) < 120:
            self._sparkcache[key] = out
        return out

    def _boom_tile(self, r, seed):
        """An expanding fireball: radial heat ramp with noise lobes, cached by
        radius bucket so the flipbook builds itself on demand."""
        r = max(8, (int(r) // 5) * 5)
        key = (r, seed)
        cached = self._boomcache.get(key)
        if cached is not None:
            return cached
        ax = np.arange(-r - 2, r + 3, dtype=np.float32)
        yy, xx = ax[:, None], ax[None, :]
        d = np.hypot(yy, xx) / r
        ang = np.arctan2(yy, xx)
        wob = 1 + 0.22 * np.sin(ang * 5 + seed * 2.1) + 0.13 * np.sin(ang * 9 + seed * 4.7)
        body = np.clip(1 - d / wob, 0, 1)
        idx = np.clip((body ** 1.4) * 63, 0, 63).astype(np.uint8)
        S2 = 2 * r + 5
        arr = np.empty((S2, S2, 4), np.float32)
        arr[:, :, :3] = _FIRE[idx]
        arr[:, :, 3] = (body ** 0.7) * 255.0
        out = (arr, r + 2, r + 2)
        if len(self._boomcache) < 80:
            self._boomcache[key] = out
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
    def _ensure_vignette(self, w, h):
        """Radial edge mask for the impact flash (0 centre -> 1 at edges/corners)."""
        if (w, h) == self._vignette_wh and self._vignette is not None:
            return
        self._vignette_wh = (w, h)
        ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
        dx = (xs - w / 2.0) / (w / 2.0); dy = (ys - h / 2.0) / (h / 2.0)
        d = np.clip((np.sqrt(dx * dx + dy * dy) - 0.5) / 0.6, 0, 1)
        self._vignette = (d * d * (3 - 2 * d)).astype(np.float32)

    def _run(self):
        try:
            x, y, w, h = winutil.client_rect_on_screen(self.target)
            self._backend = _backend_mod.Backend(x, y, w, h)
        except Exception as e:
            self._err = e
            return
        self._geom = (x, y, w, h)
        self.hwnd = self._backend.hwnd
        self._running = True
        while self._running:
            t0 = time.time()
            state = 0
            try:
                state = self._render()
            except Exception:
                pass
            self._backend.pump()
            # while blank the overlay costs (almost) nothing (state 1): no
            # compositing or surface pushes, just a low-rate geometry follow +
            # keep-on-top nudge. Edge-flash frames (state 2) touch the whole
            # frame, so they run at half rate to spare slow machines.
            dt_target = IDLE_DT if state == 1 else (FRAME_DT * 2 if state == 2 else FRAME_DT)
            time.sleep(max(0.0, dt_target - (time.time() - t0)))
        self._backend.close()

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
        if src.dtype != np.float32:                    # cached tiles are uint8
            src = src.astype(np.float32)
        sa = (src[:, :, 3:4] / 255.0) * alpha          # effective src alpha (0-1)
        src_pm = src[:, :, :3] * sa                    # premultiplied src rgb
        reg = surf[cy0:cy1, cx0:cx1]
        reg[:, :, :3] = src_pm + reg[:, :, :3] * (1 - sa)
        reg[:, :, 3:4] = sa * 255.0 + reg[:, :, 3:4] * (1 - sa)
        self._mark(cx0, cy0, cx1, cy1)

    def _mark(self, x0, y0, x1, y1):
        """Grow this frame's dirty bbox (the only region converted + uploaded)."""
        d = self._dirty
        if d is None:
            self._dirty = [x0, y0, x1, y1]
        else:
            d[0] = min(d[0], x0); d[1] = min(d[1], y0)
            d[2] = max(d[2], x1); d[3] = max(d[3], y1)

    def _render(self):
        """Draw one frame. Returns 1 when the overlay is blank (idle), 2 when a
        full-frame effect (edge flash) ran, 0 for a normal active frame."""
        S.maybe_reload()                       # live-apply settings changes
        n = S["numbers"]; e = S["epic"]; an = S["anim"]
        lerp = n["anchor_lerp"]; base_pop = n["pop"]; fade_start = n["fade_start"]
        ring_on = e["ring_enabled"]; whitehot_on = e["whitehot_enabled"]
        fire_on = an["fire_enabled"]; boom_on = an["fireball_enabled"]
        shimmer = an["shimmer_speed"] if an["shimmer_enabled"] else 0.0
        x, y, w, h = winutil.client_rect_on_screen(self.target)
        if (x, y, w, h) != self._geom:        # follow the game window live (move + RESIZE)
            self._geom = (x, y, w, h)
            self._backend.move(x, y, w, h)
        now = time.time()
        amp_, st0_ = self._shake
        fint_, ft0_ = self._flash
        with self.lock:
            content = bool(self.items or self._markers or self._particles)
        idle = not (content or (amp_ > 0 and now - st0_ < SHAKE_DUR)
                    or (fint_ > 0 and now - ft0_ < FLASH_DUR))
        if idle and self._blank:
            self._backend.idle()              # nothing to draw, already cleared
            return 1
        bgra = self._backend.surface(w, h)    # (h,w,4) uint8 BGRA, top-down
        self._dirty = None
        if self._surf is None or self._surf.shape[:2] != (h, w):
            self._surf = np.zeros((h, w, 4), np.float32)
            self._prev_dirty = None
        elif self._prev_dirty:                # erase only what last frame drew
            px0, py0, px1, py1 = self._prev_dirty
            self._surf[py0:py1, px0:px1] = 0.0
        surf = self._surf
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
                # expanding fireball at the impact point (epic hits), under everything
                if boom_on and it.epic > 0 and age < 0.30:
                    br = (8 + _ease_out(age / 0.30) * (22 + 34 * it.epic)) * sc
                    ba = (1 - age / 0.30) * (0.40 + 0.5 * it.epic)
                    bx, by = to_screen(it.ix + shx, it.iy + shy)
                    self._composite(surf, self._boom_tile(br, id(it) % 5), bx, by, ba)
                # expanding shockwave ring at the impact point (epic hits)
                if ring_on and it.epic > 0 and age < 0.34:
                    rr = (10 + _ease_out(age / 0.34) * (38 + 46 * it.epic)) * sc
                    ra = max(0.0, (1 - age / 0.36)) * (0.55 + 0.45 * it.epic)
                    rcx, rcy = to_screen(it.x + shx, it.y + shy)
                    self._composite(surf, self._ring_tile(rr, (255, 205, 120)), rcx, rcy, ra)
                # quantize the animated size: the spawn "pop" sweeps through
                # sizes, and every distinct size means rendering a fresh glyph
                # mask - 6 px steps keep that to a handful of cached tiles
                size = max(12, int(round(it.size * anim * sc / 6) * 6))
                # flame licks on burning (epic) numbers, behind the glyph;
                # the layer regenerates at ~30 Hz so the fire flickers
                if fire_on and it.epic > 0:
                    if it._fx is None or now - it._fxt > 0.045:   # ~22 Hz flicker
                        it._fx = self._flame(it.text, size, int(now * 22) & 0xFF,
                                             (0.45 + 0.65 * it.epic) * an["fire_amount"])
                        it._fxt = now
                    self._composite(surf, it._fx, ax, ay, alpha)
                ph = age * shimmer + it.phase0
                self._composite(surf, self._tile(it.text, it.color, size, ph), ax, ay, alpha)
                # white-hot flash on spawn (epic hits)
                if whitehot_on and it.epic > 0 and age < 0.12:
                    self._composite(surf, self._tile(it.text, (255, 255, 255), size, solid=True),
                                    ax, ay, (1 - age / 0.12) * 0.85 * alpha)
            for (mx, my, mtext, mcolor) in self._markers:
                bx, by = to_screen(mx + shx, my + shy)
                self._composite(surf, self._tile(mtext, mcolor, max(12, int(26 * sc))), bx, by, 1.0)
            # ember sparks: burst outward, drag, then drift up while fading
            if self._particles:
                dt = min(0.1, max(0.0, now - self._last_t))
                keep = []
                for p in self._particles:
                    pt = (now - p[4]) / p[5]
                    if pt >= 1.0:
                        continue
                    p[0] += p[2] * dt; p[1] += p[3] * dt
                    p[3] -= 55 * dt
                    p[2] *= (1 - 1.4 * dt)
                    px, py = to_screen(p[0] + shx, p[1] + shy)
                    self._composite(surf, self._spark_tile(int(p[7] * sc), p[6]),
                                    px, py, (1 - pt) ** 1.3)
                    keep.append(p)
                self._particles = keep
            self.items = alive
        self._last_t = now
        # warm edge-flash on impact (full-frame by nature)
        flash_frame = False
        fint, ft0 = self._flash
        fage = now - ft0
        if fint > 0 and fage < FLASH_DUR:
            flash_frame = True
            self._ensure_vignette(w, h)
            # in-place lerp (x' = x + a*(target - x)), no (h,w,3) temporaries -
            # this runs over the whole frame, so allocations would hurt
            a = self._vignette * np.float32(fint * (1 - fage / FLASH_DUR))
            for c in range(3):
                ch = surf[:, :, c]
                ch += a * (np.float32(FLASH_COLOR[c]) - ch)
            al = surf[:, :, 3]
            al += a * (np.float32(255.0) - al)
            self._mark(0, 0, w, h)
        # convert + upload only the dirty region: what was drawn this frame plus
        # what must be erased from the last one. Slow machines feel full-frame
        # 60 Hz conversions; a couple of damage numbers touch a few % of it.
        box = self._dirty
        if self._prev_dirty:
            box = self._prev_dirty if box is None else [
                min(box[0], self._prev_dirty[0]), min(box[1], self._prev_dirty[1]),
                max(box[2], self._prev_dirty[2]), max(box[3], self._prev_dirty[3])]
        if box is not None:
            x0 = max(0, box[0]); y0 = max(0, box[1])
            x1 = min(w, box[2]); y1 = min(h, box[3])
            if x1 > x0 and y1 > y0:
                sub = surf[y0:y1, x0:x1]
                np.clip(sub, 0, 255, out=sub)
                breg = bgra[y0:y1, x0:x1]
                breg[:, :, 0] = sub[:, :, 2]
                breg[:, :, 1] = sub[:, :, 1]
                breg[:, :, 2] = sub[:, :, 0]
                breg[:, :, 3] = sub[:, :, 3]
                self._backend.present(x, y, w, h, (x0, y0, x1, y1))
        self._prev_dirty = self._dirty
        self._blank = idle          # idle here means this frame just cleared the window
        return 1 if idle else (2 if flash_frame else 0)


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
