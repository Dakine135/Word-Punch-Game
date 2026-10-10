"""Draw a tracked person's upper-body skeleton over the camera view."""
from __future__ import annotations

import pygame

from ..vision.pose_backend import Person
from .camera_view import CameraView

BONES = [("left_shoulder", "right_shoulder"), ("left_shoulder", "left_elbow"),
         ("left_elbow", "left_wrist"), ("right_shoulder", "right_elbow"),
         ("right_elbow", "right_wrist"), ("left_shoulder", "left_hip"),
         ("right_shoulder", "right_hip"), ("left_hip", "right_hip")]


def draw_skeleton(surface: pygame.Surface, view: CameraView, person: Person, color, min_vis=0.3) -> None:
    kp = person.keypoints
    for a, b in BONES:
        if a in kp and b in kp and kp[a].vis > min_vis and kp[b].vis > min_vis:
            pygame.draw.line(surface, color, view.to_screen(kp[a].x, kp[a].y),
                             view.to_screen(kp[b].x, kp[b].y), 4)
    for name, k in kp.items():
        if k.vis > min_vis:
            pygame.draw.circle(surface, color, view.to_screen(k.x, k.y), 6)
    # shoulder line extended: wrists must get above this for a punch (when above_shoulder is on)
    ls, rs = kp.get("left_shoulder"), kp.get("right_shoulder")
    if ls and rs and ls.vis > min_vis and rs.vis > min_vis:
        y = (ls.y + rs.y) / 2
        x0, y0 = view.to_screen(min(ls.x, rs.x) - 0.08, y)
        x1, _ = view.to_screen(max(ls.x, rs.x) + 0.08, y)
        for x in range(x0, x1, 16):
            pygame.draw.line(surface, (255, 255, 255), (x, y0), (min(x + 8, x1), y0), 2)
