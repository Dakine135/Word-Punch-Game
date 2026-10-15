"""Pose backend interface. Backends turn an RGB frame into a list of Person.

Coordinates are normalized to the frame (0..1, y pointing down) of the frame that was
passed in, which is already mirrored, so "left" in a Person means screen-left.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

# The keypoints the game uses. Backends map their own indices onto these names.
KEYPOINTS = (  # the 17 COCO body points (MoveNet uses the same set)
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder",
    "left_elbow", "right_elbow",
    "left_wrist", "right_wrist",
    "left_hip", "right_hip",
    "left_knee", "right_knee",
    "left_ankle", "right_ankle",
)


@dataclass
class Keypoint:
    x: float
    y: float
    vis: float  # 0..1 confidence that the point is visible


@dataclass
class Person:
    keypoints: dict[str, Keypoint] = field(default_factory=dict)
    track_id: int | None = None  # same number for the same kid across frames (YOLO tracker)

    def get(self, name: str, min_vis: float = 0.0) -> Keypoint | None:
        kp = self.keypoints.get(name)
        if kp is None or kp.vis < min_vis:
            return None
        return kp

    @property
    def center_x(self) -> float:
        """Horizontal center: shoulder midpoint, falling back to the nose."""
        ls, rs = self.get("left_shoulder", 0.3), self.get("right_shoulder", 0.3)
        if ls and rs:
            return (ls.x + rs.x) / 2
        nose = self.get("nose")
        if nose:
            return nose.x
        xs = [k.x for k in self.keypoints.values()]
        return sum(xs) / len(xs) if xs else 0.5

    @property
    def scale(self) -> float:
        """Shoulder width in normalized x units; used to make thresholds size-invariant."""
        ls, rs = self.get("left_shoulder", 0.3), self.get("right_shoulder", 0.3)
        if ls and rs:
            return max(abs(ls.x - rs.x), 0.03)
        return 0.12  # a typical value for a kid a few feet from the camera

    def to_wire(self) -> dict:
        """Plain dict for sending across processes."""
        d = {k: (v.x, v.y, v.vis) for k, v in self.keypoints.items()}
        d["_id"] = self.track_id
        return d

    @classmethod
    def from_wire(cls, d: dict) -> "Person":
        d = dict(d)
        tid = d.pop("_id", None)
        return cls({k: Keypoint(*v) for k, v in d.items()}, track_id=tid)


class PoseBackend(Protocol):
    def detect(self, rgb: np.ndarray, timestamp_ms: int) -> list[Person]: ...

    def close(self) -> None: ...


def create_backend(name: str, cfg: dict) -> PoseBackend:
    if name == "yolo":
        from .yolo_backend import YoloBackend
        return YoloBackend(cfg)
    if name == "mediapipe":
        from .mediapipe_backend import MediaPipeBackend
        return MediaPipeBackend(cfg)
    raise ValueError(f"unknown pose backend: {name}")
