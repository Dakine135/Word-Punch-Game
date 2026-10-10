"""Camera capture + pose detection in their own process.

The latest mirrored camera frame is shared through shared memory (cheap to display at
camera fps), and pose results arrive on a queue whenever detection finishes (which can be
slower than the camera, e.g. on the Pi).

    svc = VisionService(cfg); svc.start()
    frame = svc.latest_frame()        # HxWx3 RGB uint8 (mirrored), or None
    for t, people in svc.poll(): ...  # people: list[Person]
"""
from __future__ import annotations

import multiprocessing as mp
import queue
import threading
import time
from multiprocessing import shared_memory

import numpy as np

from .pose_backend import Person


def _vision_main(cfg: dict, shm_name: str, seq, out_q: mp.Queue, stop) -> None:
    import cv2

    from .pose_backend import create_backend

    cam_cfg, pose_cfg = cfg["camera"], cfg["pose"]
    w, h = cam_cfg["width"], cam_cfg["height"]
    shm = shared_memory.SharedMemory(name=shm_name)
    shared = np.ndarray((h, w, 3), dtype=np.uint8, buffer=shm.buf)

    api = cv2.CAP_DSHOW if hasattr(cv2, "CAP_DSHOW") and _is_windows() else cv2.CAP_ANY
    cap = cv2.VideoCapture(cam_cfg["index"], api)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
    cap.set(cv2.CAP_PROP_FPS, cam_cfg["fps"])
    if not cap.isOpened():
        out_q.put(("error", f"could not open camera {cam_cfg['index']}"))
        return

    latest = {"frame": None, "t": 0.0}
    lock = threading.Lock()

    def capture_loop():
        # Always keep only the newest frame so pose never works on stale images.
        while not stop.is_set():
            ok, bgr = cap.read()
            if not ok:
                time.sleep(0.01)
                continue
            if bgr.shape[1] != w or bgr.shape[0] != h:
                bgr = cv2.resize(bgr, (w, h))
            rgb = cv2.cvtColor(cv2.flip(bgr, 1), cv2.COLOR_BGR2RGB)
            shared[:] = rgb
            with seq.get_lock():
                seq.value += 1
            with lock:
                latest["frame"], latest["t"] = rgb, time.time()

    threading.Thread(target=capture_loop, daemon=True).start()

    backend = create_backend(pose_cfg["backend"], pose_cfg)
    out_q.put(("ready", None))
    t0 = time.time()
    last_t = 0.0
    pose_w = pose_cfg["input_width"]
    try:
        while not stop.is_set():
            with lock:
                frame, t = latest["frame"], latest["t"]
            if frame is None or t == last_t:
                time.sleep(0.003)
                continue
            last_t = t
            small = frame
            if pose_w and pose_w < w:
                small = cv2.resize(frame, (pose_w, int(h * pose_w / w)), interpolation=cv2.INTER_AREA)
            start = time.time()
            people = backend.detect(small, int((t - t0) * 1000))
            out_q.put(("pose", (t, [p.to_wire() for p in people], time.time() - start)))
    finally:
        backend.close()
        cap.release()
        shm.close()


def _is_windows() -> bool:
    import sys
    return sys.platform == "win32"


class VisionService:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.width, self.height = cfg["camera"]["width"], cfg["camera"]["height"]
        ctx = mp.get_context("spawn")
        self._ctx = ctx
        self._shm = shared_memory.SharedMemory(create=True, size=self.width * self.height * 3)
        self._frame = np.ndarray((self.height, self.width, 3), dtype=np.uint8, buffer=self._shm.buf)
        self._seq = ctx.Value("L", 0)
        self._out_q = ctx.Queue()
        self._stop = ctx.Event()
        self._proc = None
        self.ready = False
        self.error: str | None = None
        self.pose_ms = 0.0  # last detection time, for the debug HUD
        self._last_seq = -1

    def start(self) -> None:
        self._proc = self._ctx.Process(
            target=_vision_main, daemon=True,
            args=(self.cfg, self._shm.name, self._seq, self._out_q, self._stop))
        self._proc.start()

    def latest_frame(self) -> np.ndarray | None:
        """The shared frame buffer (do not keep it; it is overwritten in place)."""
        return self._frame if self._seq.value > 0 else None

    def new_frame_available(self) -> bool:
        s = self._seq.value
        if s != self._last_seq:
            self._last_seq = s
            return True
        return False

    def poll(self) -> list[tuple[float, list[Person]]]:
        results = []
        while True:
            try:
                kind, arg = self._out_q.get_nowait()
            except queue.Empty:
                break
            if kind == "ready":
                self.ready = True
            elif kind == "error":
                self.error = arg
            elif kind == "pose":
                t, people, dt = arg
                self.pose_ms = dt * 1000
                results.append((t, [Person.from_wire(p) for p in people]))
        return results

    def stop(self) -> None:
        self._stop.set()
        if self._proc:
            self._proc.join(timeout=3)
            if self._proc.is_alive():
                self._proc.terminate()
        self._shm.close()
        self._shm.unlink()
