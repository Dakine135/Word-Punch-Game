"""A horizontal mic level bar: green while quiet, yellow when talking, red when too loud."""
from __future__ import annotations

import pygame

# Rough guide on the 0..1 scale (-60..0 dBFS): background noise sits low,
# a kid talking a few feet away should reach the yellow zone.
TALK = 0.45
LOUD = 0.9


def draw_mic_meter(surface: pygame.Surface, rect: pygame.Rect, level: float, peak: float,
                   font: pygame.font.Font | None = None, label: str = "") -> None:
    pygame.draw.rect(surface, (40, 44, 60), rect, border_radius=6)
    fill = rect.copy()
    fill.width = int(rect.width * max(0.0, min(1.0, level)))
    color = (80, 200, 90) if level < TALK else (240, 200, 60) if level < LOUD else (240, 70, 60)
    if fill.width > 0:
        pygame.draw.rect(surface, color, fill, border_radius=6)
    # "talking" threshold tick and peak marker
    tx = rect.left + int(rect.width * TALK)
    pygame.draw.line(surface, (200, 200, 220), (tx, rect.top), (tx, rect.bottom), 1)
    px = rect.left + int(rect.width * max(0.0, min(1.0, peak)))
    pygame.draw.line(surface, (255, 255, 255), (px, rect.top - 3), (px, rect.bottom + 3), 3)
    pygame.draw.rect(surface, (150, 155, 180), rect, 2, border_radius=6)
    if font and label:
        t = font.render(label, True, (230, 230, 240))
        surface.blit(t, (rect.left, rect.top - t.get_height() - 4))
