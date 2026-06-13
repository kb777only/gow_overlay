"""Record N memory snapshots of the EE static-data region over ~15s while the
user pans the in-game camera. The camera-to-world matrix is the orthonormal
4x4 global that CHANGES across frames; everything static (room geometry, matrix
palettes) stays put. Saves frames for offline analysis."""
import time
import numpy as np
import pine
import memscan

START = 0x00100000
END = 0x01000000              # static data region (PAL camera was 0x0072E090)
NFRAMES = 22
INTERVAL = 0.7


def main():
    pc = pine.PineClient(timeout=8.0).connect()
    print("game", pc.game_id(), "status", pc.status(), flush=True)
    rdr = memscan.PineReader(pc)
    frames = []
    stamps = []
    t0 = time.time()
    for i in range(NFRAMES):
        blk = rdr.read_block(START, END - START)
        frames.append(np.frombuffer(blk, dtype=np.float32).copy())
        stamps.append(time.time() - t0)
        st = pc.status()
        print(f"frame {i:2d}  t={stamps[-1]:5.1f}s  status={st}  bytes={len(blk)}", flush=True)
        time.sleep(INTERVAL)
    arr = np.stack(frames)            # (NFRAMES, Nfloats) float32
    np.savez("/tmp/gow_frames.npz", frames=arr, start=START)
    print(f"saved {arr.shape} to /tmp/gow_frames.npz", flush=True)
    pc.close()


if __name__ == "__main__":
    main()
