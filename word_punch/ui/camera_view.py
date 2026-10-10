"""Draw the mirrored camera frame to fill the screen, and map pose coords to screen pixels."""
from __future__ import annotations

import numpy as np
import pygame


class CameraView:
    def __init__(self, screen_size: tuple[int, int], frame_size: tuple[int, int], dim: float = 0.0):
        self.sw, self.sh = screen_size
        fw, fh = frame_size
        # "Cover": scale so the frame fills the screen, cropping the overflow evenly.
        self.scale = max(self.sw / fw, self.sh / fh)
        self.dw, self.dh = int(fw * self.scale), int(fh * self.scale)
        self.ox, self.oy = (self.sw - self.dw) // 2, (self.sh - self.dh) // 2
        self.dim = dim  # 0..1, darken the video so game graphics pop

    def to_screen(self, x: float, y: float) -> tuple[int, int]:
        return int(self.ox + x * self.dw), int(self.oy + y * self.dh)

    def draw(self, surface: pygame.Surface, frame: np.ndarray | None) -> None:
        if frame is None:
            surface.fill((20, 24, 40))
            return
        img = pygame.image.frombuffer(frame.tobytes(), (frame.shape[1], frame.shape[0]), "RGB")
        img = pygame.transform.scale(img, (self.dw, self.dh))
        surface.blit(img, (self.ox, self.oy))
        if self.dim > 0:
            shade = pygame.Surface((self.sw, self.sh))
            shade.set_alpha(int(255 * self.dim))
            surface.blit(shade, (0, 0))
