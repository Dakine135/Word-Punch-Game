"""Draw tracked people's full-body skeletons over the camera view."""
from __future__ import annotations

import pygame

from ..vision.pose_backend import Person
from .camera_view import CameraView

BONES = [
    # arms
    ("left_shoulder", "left_elbow"), ("left_elbow", "left_wrist"),
    ("right_shoulder", "right_elbow"), ("right_elbow", "right_wrist"),
    # body
    ("left_shoulder", "right_shoulder"), ("left_shoulder", "left_hip"),
    ("right_shoulder", "right_hip"), ("left_hip", "right_hip"),
    # legs
    ("left_hip", "left_knee"), ("left_knee", "left_ankle"),
    ("right_hip", "right_knee"), ("right_knee", "right_ankle"),
]


class SkeletonLayer:
    """Draws skeletons onto one reusable see-through layer (cheaper than many alpha surfaces)."""

    def __init__(self, size: tuple[int, int]):
        self.layer = pygame.Surface(size, pygame.SRCALPHA)

    def begin(self) -> None:
        self.layer.fill((0, 0, 0, 0))

    def add(self, view: CameraView, person: Person, color, alpha: int = 150, min_vis: float = 0.35,
            shoulder_line: bool = False) -> None:
        kp = person.keypoints
        scale = person.scale * view.dw  # shoulder width in screen pixels
        width = max(3, int(scale * 0.08))
        c = (*color, alpha)
        pts = {}
        for name, k in kp.items():
            if k.vis >= min_vis:
                pts[name] = view.to_screen(k.x, k.y)
        for a, b in BONES:
            if a in pts and b in pts:
                pygame.draw.line(self.layer, c, pts[a], pts[b], width)
        for name, p in pts.items():
            if name not in ("left_eye", "right_eye", "left_ear", "right_ear"):
                pygame.draw.circle(self.layer, c, p, max(4, width))
        if "nose" in pts:  # a head
            pygame.draw.circle(self.layer, c, pts["nose"], max(12, int(scale * 0.42)), max(2, width // 2))
        if shoulder_line and "left_shoulder" in pts and "right_shoulder" in pts:
            # wrists must get above this for a punch (when above_shoulder is on)
            (x0, y0), (x1, y1) = sorted([pts["left_shoulder"], pts["right_shoulder"]])
            y = (y0 + y1) // 2
            pad = int(scale * 0.6)
            for x in range(x0 - pad, x1 + pad, 16):
                pygame.draw.line(self.layer, (255, 255, 255, 220), (x, y), (min(x + 8, x1 + pad), y), 2)

    def end(self, surface: pygame.Surface) -> None:
        surface.blit(self.layer, (0, 0))


def draw_skeleton(surface: pygame.Surface, view: CameraView, person: Person, color, min_vis=0.35) -> None:
    """One-off drawing (tools)."""
    layer = SkeletonLayer(surface.get_size())
    layer.begin()
    layer.add(view, person, color, alpha=220, min_vis=min_vis, shoulder_line=True)
    layer.end(surface)
