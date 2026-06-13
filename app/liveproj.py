"""Live world->screen projection for GoW.

The camera-to-world matrix is a per-frame global (rotation in rows 0-2, camera
world position in row 3). Its address and the projection intrinsics are
region-specific (the PAL and NTSC builds lay data out differently), so both are
selected by game_id from camcalib.json:
    SCES-53133 (PAL)   : 0x0072E090
    SCUS-97399 (NTSC-U): 0x0075CFB0
Projection (identical convention across regions):
    view   = R @ (worldP + (0,h,0) - cam)      # R = rows0-2, cam = row3
    screen = (cx + fx*view.x/view.z, cy + fy*view.y/view.z)
Intrinsics (cx,cy,fx,fy) + torso height h were calibrated per region from two
frames at very different camera angles (multi-view solve)."""
import json
import os
import numpy as np

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "camcalib.json")


def _profile_for(calib, game_id):
    """Pick the calibration profile for a game_id, falling back to the default.
    Accepts either the new {"profiles": {...}, "default": ...} layout or a bare
    single-profile dict (older format)."""
    profiles = calib.get("profiles")
    if profiles is None:
        return calib                                   # legacy flat file
    if game_id and game_id in profiles:
        return profiles[game_id]
    return profiles[calib.get("default", next(iter(profiles)))]


class LiveProjection:
    def __init__(self, game_id=None, calib=None):
        if calib is None:
            calib = json.load(open(_PATH))
        p = _profile_for(calib, game_id)
        self.cx = p["cx"]; self.cy = p["cy"]
        self.fx = p["fx"]; self.fy = p["fy"]
        self.h = p["h"]
        ra = p.get("rot_addr", 0x0072E090)
        self.rot_addr = int(ra, 16) if isinstance(ra, str) else int(ra)
        self.R = None; self.cam = None

    def reqs(self):
        return [("f32", self.rot_addr + i * 4) for i in range(16)]

    def set_matrix(self, vals16):
        """Adopt the 16 floats at rot_addr as the camera matrix - only if they
        actually look like one. During loads/menus/camera cuts the game leaves
        garbage or half-written data there (and a PINE read can tear mid-update);
        a bad matrix projects numbers anywhere on - or off - screen. Reject such
        frames and keep the last good matrix. Returns True if adopted."""
        M = np.array([float(v) for v in vals16], dtype=np.float64).reshape(4, 4)
        if not np.all(np.isfinite(M)):
            return False
        R = M[:3, :3]; cam = M[3, :3]
        n2 = (R * R).sum(axis=1)                 # rotation rows must be ~unit...
        if np.any(np.abs(n2 - 1.0) > 0.1):
            return False
        if (abs(R[0] @ R[1]) > 0.05 or abs(R[0] @ R[2]) > 0.05
                or abs(R[1] @ R[2]) > 0.05):     # ...and mutually orthogonal
            return False
        if np.any(np.abs(cam) > 1e7):
            return False
        self.R = R; self.cam = cam
        return True

    def update(self, pc):
        return self.set_matrix(pc.batch_read(self.reqs()))

    def project(self, x, y, z):
        if self.R is None:
            return None
        view = self.R @ (np.array([x, y + self.h, z]) - self.cam)
        if view[2] >= -1.0:          # behind / too close (front = negative z)
            return None
        return (self.cx + self.fx * view[0] / view[2],
                self.cy + self.fy * view[1] / view[2])
