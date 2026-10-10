"""MediaPipe Pose Landmarker backend (multi-person). Used on the laptop."""
from __future__ import annotations

from pathlib import Path

import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision as mp_vision

from .pose_backend import Keypoint, Person

# MediaPipe's 33-landmark indices for the keypoints we use.
_INDEX = {
    "nose": 0,
    "left_shoulder": 11, "right_shoulder": 12,
    "left_elbow": 13, "right_elbow": 14,
    "left_wrist": 15, "right_wrist": 16,
    "left_hip": 23, "right_hip": 24,
}


class MediaPipeBackend:
    def __init__(self, cfg: dict):
        model = Path(cfg["mediapipe_model"])
        if not model.exists():
            raise FileNotFoundError(f"{model} missing - run: python tools/fetch_models.py")
        options = mp_vision.PoseLandmarkerOptions(
            base_options=mp_tasks.BaseOptions(model_asset_path=str(model)),
            running_mode=mp_vision.RunningMode.VIDEO,
            num_poses=cfg["max_people"],
            min_pose_detection_confidence=cfg["min_detection_confidence"],
            min_pose_presence_confidence=cfg["min_presence_confidence"],
            min_tracking_confidence=cfg["min_tracking_confidence"],
        )
        self._landmarker = mp_vision.PoseLandmarker.create_from_options(options)
        self._last_ts = -1

    def detect(self, rgb: np.ndarray, timestamp_ms: int) -> list[Person]:
        # VIDEO mode requires strictly increasing timestamps.
        timestamp_ms = max(timestamp_ms, self._last_ts + 1)
        self._last_ts = timestamp_ms
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        result = self._landmarker.detect_for_video(image, timestamp_ms)
        people = []
        for landmarks in result.pose_landmarks:
            kps = {}
            for name, idx in _INDEX.items():
                lm = landmarks[idx]
                vis = lm.visibility if lm.visibility is not None else 1.0
                kps[name] = Keypoint(lm.x, lm.y, float(vis))
            people.append(Person(kps))
        return people

    def close(self) -> None:
        self._landmarker.close()
