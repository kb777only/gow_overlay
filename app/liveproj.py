"""Live world->screen projection for GoW.

The camera-to-world matrix lives at 0x0072E090 (rotation in rows 0-2, camera
world position in row 3) and updates every frame. Projection:
    view   = R @ (worldP + (0,h,0) - cam)      # R = rows0-2, cam = row3
    screen = (cx + fx*view.x/view.z, cy + fy*view.y/view.z)
Intrinsics (cx,cy,fx,fy) + torso height h were calibrated from two frames at very
different camera angles (multi-view solve)."""
import json
import os
import numpy as np

ROT_ADDR = 0x0072E090
_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "camcalib.json")


class LiveProjection:
    def __init__(self, calib=None):
        if calib is None:
            calib = json.load(open(_PATH))
        self.cx = calib["cx"]; self.cy = calib["cy"]
        self.fx = calib["fx"]; self.fy = calib["fy"]
        self.h = calib["h"]
        self.R = None; self.cam = None

    def reqs(self):
        return [("f32", ROT_ADDR + i * 4) for i in range(16)]

    def set_matrix(self, vals16):
        M = np.array([float(v) for v in vals16], dtype=np.float64).reshape(4, 4)
        self.R = M[:3, :3]; self.cam = M[3, :3]

    def update(self, pc):
        self.set_matrix(pc.batch_read(self.reqs()))

    def project(self, x, y, z):
        if self.R is None:
            return None
        view = self.R @ (np.array([x, y + self.h, z]) - self.cam)
        if view[2] >= -1.0:          # behind / too close (front = negative z)
            return None
        return (self.cx + self.fx * view[0] / view[2],
                self.cy + self.fy * view[1] / view[2])
