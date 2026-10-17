"""'Getting ready...' panel: shows what's still loading when the game starts.

Body tracking (camera + YOLO on the GPU) and speech (Vosk + Whisper) take several seconds
to load. Each bar fills over how long that part took last time (remembered in
logs/startup.json), waits at 95% until it's really ready, then shows a check mark.
"""
from __future__ import annotations

import json
import time

import pygame

from ..config import ROOT

TIMES = ROOT / "logs" / "startup.json"
DEFAULT_S = {"vision": 10.0, "speech": 15.0}


class Loading:
    def __init__(self):
        self.start = time.time()
        try:
            self.expected = {**DEFAULT_S, **json.loads(TIMES.read_text(encoding="utf-8"))}
        except (OSError, ValueError):
            self.expected = dict(DEFAULT_S)
        self.ready_at: dict[str, float] = {}
        self.all_ready_at: float | None = None

    def mark(self, key: str, ready: bool, now: float) -> None:
        if ready and key not in self.ready_at:
            self.ready_at[key] = now
            took = now - self.start
            self.expected[key] = round(took, 1)
            try:
                TIMES.parent.mkdir(exist_ok=True)
                TIMES.write_text(json.dumps(self.expected), encoding="utf-8")
            except OSError:
                pass

    def progress(self, key: str, now: float) -> float:
        if key in self.ready_at:
            return 1.0
        return min(0.95, (now - self.start) / max(1.0, self.expected.get(key, 10.0)))

    def visible(self, keys: list[str], now: float) -> bool:
        if all(k in self.ready_at for k in keys):
            if self.all_ready_at is None:
                self.all_ready_at = now
            return now - self.all_ready_at < 1.5  # show the check marks briefly, then hide
        return True


def draw_loading(surface: pygame.Surface, renderer, rows: list[tuple[str, float, str]], now: float) -> None:
    """rows: (label, progress 0..1, note). Drawn in the lower half, under the buttons."""
    from .render import GOLD, WHITE
    w, h = surface.get_size()
    panel = pygame.Rect(0, 0, 640, 54 + 46 * len(rows))
    panel.midbottom = (w // 2, h - 54)
    bg = pygame.Surface(panel.size, pygame.SRCALPHA)
    bg.fill((12, 14, 30, 215))
    surface.blit(bg, panel)
    pygame.draw.rect(surface, (90, 100, 150), panel, 2, border_radius=12)
    dots = "." * (1 + int(now * 2) % 3)
    t = renderer.small_font.render(f"Getting ready{dots}   (the first start takes a little longer)", True, GOLD)
    surface.blit(t, (panel.left + 18, panel.top + 12))
    for i, (label, frac, note) in enumerate(rows):
        y = panel.top + 48 + i * 46
        surface.blit(renderer.small_font.render(label, True, WHITE), (panel.left + 18, y))
        bar = pygame.Rect(panel.left + 250, y + 4, 300, 18)
        pygame.draw.rect(surface, (50, 54, 72), bar, border_radius=9)
        fill = bar.copy()
        fill.width = int(bar.width * frac)
        done = frac >= 1.0
        pygame.draw.rect(surface, (120, 220, 130) if done else (90, 160, 255), fill, border_radius=9)
        if done:  # check mark
            cx, cy = bar.right + 26, bar.centery
            pygame.draw.lines(surface, (120, 235, 140), False, [(cx - 9, cy), (cx - 2, cy + 8), (cx + 11, cy - 8)], 4)
        elif note:
            n = renderer.small_font.render(note, True, (170, 175, 195))
            surface.blit(n, (bar.right + 12, y))
