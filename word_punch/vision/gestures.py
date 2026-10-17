"""Open palm vs fist for menu "clicks" (MediaPipe Gesture Recognizer on zoomed hand crops).

The pose model only finds wrists, not fingers. For each RAISED hand (wrist above its elbow)
we cut a square around where the hand is - past the wrist, along the forearm - out of the
full-resolution camera frame and ask the gesture recognizer what it sees. Cropping matters:
kids stand a few metres back, so a hand is only ~40 px in the full frame.

Labels from the recognizer: Open_Palm, Closed_Fist, Pointing_Up, Thumb_Up, Thumb_Down,
Victory, ILoveYou, None.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .pose_backend import Person

HANDS = (("left_wrist", "left_elbow"), ("right_wrist", "right_elbow"))


def raised(person: Person, wrist: str, elbow: str) -> bool:
    w, e = person.get(wrist, 0.3), person.get(elbow, 0.3)
    return bool(w and e and w.y < e.y)


def hand_box(person: Person, wrist: str, elbow: str, fw: int, fh: int) -> tuple[int, int, int, int] | None:
    """Pixel square (x0, y0, x1, y1) around the hand, or None."""
    w, e = person.get(wrist, 0.3), person.get(elbow, 0.3)
    if not w or not e:
        return None
    # the hand sits a little beyond the wrist, along the forearm
    cx = (w.x + (w.x - e.x) * 0.35) * fw
    cy = (w.y + (w.y - e.y) * 0.35) * fh
    shoulder_px = person.scale * fw
    side = max(64.0, shoulder_px * 1.1)
    x0, y0 = int(max(0, cx - side / 2)), int(max(0, cy - side / 2))
    x1, y1 = int(min(fw, cx + side / 2)), int(min(fh, cy + side / 2))
    if x1 - x0 < 24 or y1 - y0 < 24:
        return None
    return x0, y0, x1, y1


class HandGestures:
    def __init__(self, model_path: str | Path, min_score: float = 0.5):
        import mediapipe as mp
        from mediapipe.tasks import python as mp_tasks
        from mediapipe.tasks.python import vision as mp_vision
        self.mp = mp
        options = mp_vision.GestureRecognizerOptions(
            base_options=mp_tasks.BaseOptions(model_asset_path=str(model_path)),
            running_mode=mp_vision.RunningMode.IMAGE, num_hands=1,
            min_hand_detection_confidence=0.4, min_hand_presence_confidence=0.4)
        self.rec = mp_vision.GestureRecognizer.create_from_options(options)
        self.min_score = min_score

    def classify(self, rgb: np.ndarray, person: Person) -> dict[str, tuple[str, float]]:
        """{wrist name: (gesture, score)} for each raised hand it could read."""
        fh, fw = rgb.shape[:2]
        out = {}
        for wrist, elbow in HANDS:
            if not raised(person, wrist, elbow):
                continue
            box = hand_box(person, wrist, elbow, fw, fh)
            if box is None:
                continue
            x0, y0, x1, y1 = box
            crop = np.ascontiguousarray(rgb[y0:y1, x0:x1])
            if crop.shape[0] < 160:  # upscale small hands so the palm detector can see them
                import cv2
                k = 192 / crop.shape[0]
                crop = cv2.resize(crop, (int(crop.shape[1] * k), 192), interpolation=cv2.INTER_CUBIC)
            image = self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=crop)
            res = self.rec.recognize(image)
            if res.gestures and res.gestures[0]:
                g = res.gestures[0][0]
                if g.score >= self.min_score:
                    out[wrist] = (g.category_name, float(g.score))
        return out

    def close(self) -> None:
        self.rec.close()
