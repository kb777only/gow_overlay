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
        self._err = None
        self._cache = {}
        self._ringcache = {}
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
        n = S["numbers"]; e = S["epic"]
        lerp = n["anchor_lerp"]; base_pop = n["pop"]; fade_start = n["fade_start"]
        ring_on = e["ring_enabled"]; whitehot_on = e["whitehot_enabled"]
        x, y, w, h = winutil.client_rect_on_screen(self.target)
        if (x, y, w, h) != self._geom:        # follow the game window live (move + RESIZE)
            self._geom = (x, y, w, h)
            self._backend.move(x, y, w, h)
        now = time.time()
        amp_, st0_ = self._shake
        fint_, ft0_ = self._flash
        with self.lock:
            content = bool(self.items or self._markers)
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
