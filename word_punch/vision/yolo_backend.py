"""YOLO11-pose on the GPU (Ultralytics), with BoT-SORT (or ByteTrack) person IDs.

More robust than MediaPipe with two or three kids close together, and the tracker keeps
the same ID on each kid from frame to frame, so players don't get jumbled when they move
around or cross over.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .pose_backend import KEYPOINTS, Keypoint, Person

# YOLO pose keypoints are the 17 COCO points, in the same order as KEYPOINTS.


class YoloBackend:
    def __init__(self, cfg: dict):
        from ultralytics import YOLO
        weights = Path(cfg["yolo_model"])
        if not weights.exists():
            raise FileNotFoundError(f"{weights} missing - run: python tools/fetch_models.py")
        self.model = YOLO(str(weights))
        self.imgsz = cfg.get("yolo_imgsz", 640)
        self.conf = cfg.get("yolo_conf", 0.35)
        self.max_people = cfg.get("max_people", 5)
        tracker = cfg.get("tracker", "botsort")
        self.tracker = str(Path(__file__).with_name("botsort.yaml")) if tracker == "botsort" else "bytetrack.yaml"
        self.device = 0 if _cuda() else "cpu"
        self.half = self.device == 0

    def detect(self, rgb: np.ndarray, timestamp_ms: int) -> list[Person]:
        bgr = np.ascontiguousarray(rgb[:, :, ::-1])  # Ultralytics treats arrays as BGR
        r = self.model.track(bgr, persist=True, tracker=self.tracker, device=self.device, half=self.half,
                             imgsz=self.imgsz, conf=self.conf, verbose=False)[0]
        if r.keypoints is None or r.boxes is None or not len(r.boxes):
            return []
        xyn = r.keypoints.xyn.cpu().numpy()
        kconf = r.keypoints.conf.cpu().numpy() if r.keypoints.conf is not None else np.ones(xyn.shape[:2])
        ids = r.boxes.id.int().cpu().tolist() if r.boxes.id is not None else [None] * len(xyn)
        box_conf = r.boxes.conf.cpu().numpy()
        order = np.argsort(-box_conf)[: self.max_people]
        people = []
        for i in order:
            kps = {name: Keypoint(float(xyn[i, j, 0]), float(xyn[i, j, 1]), float(kconf[i, j]))
                   for j, name in enumerate(KEYPOINTS)}
            # YOLO reports (0, 0) for points it can't see; mark them invisible
            for j, name in enumerate(KEYPOINTS):
                if xyn[i, j, 0] == 0 and xyn[i, j, 1] == 0:
                    kps[name].vis = 0.0
            people.append(Person(kps, track_id=ids[i]))
        return people

    def close(self) -> None:
        pass


def _cuda() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False
