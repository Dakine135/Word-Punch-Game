"""Particles and floating text."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

import pygame


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    life: float
    max_life: float
    color: tuple
    size: float


@dataclass
class FloatText:
    text: str
    x: float
    y: float
    life: float
    max_life: float
    color: tuple
    font: pygame.font.Font
    rise: float = 80.0
    pop: bool = False  # scale in


class Effects:
    def __init__(self):
        self.particles: list[Particle] = []
        self.texts: list[FloatText] = []
        self.flash_color = None
        self.flash_life = 0.0
        self.shake = 0.0

    def burst(self, x, y, colors, n=40, speed=500, size=10, life=0.9):
        for _ in range(n):
            a = random.uniform(0, 2 * math.pi)
            s = random.uniform(0.3, 1.0) * speed
            self.particles.append(Particle(x, y, math.cos(a) * s, math.sin(a) * s - speed * 0.3,
                                           life, life, random.choice(colors), random.uniform(0.5, 1) * size))

    def sparkle(self, x, y, color, n=12):
        self.burst(x, y, [color, (255, 255, 255)], n=n, speed=220, size=6, life=0.5)

    def float_text(self, text, x, y, color, font, life=1.0, rise=80.0, pop=False):
        self.texts.append(FloatText(text, x, y, life, life, color, font, rise, pop))

    def flash(self, color, life=0.25):
        self.flash_color, self.flash_life = color, life

    def update(self, dt):
        for p in self.particles:
            p.life -= dt
            p.x += p.vx * dt
            p.y += p.vy * dt
            p.vy += 900 * dt  # gravity
        self.particles = [p for p in self.particles if p.life > 0]
        for t in self.texts:
            t.life -= dt
            t.y -= t.rise * dt
        self.texts = [t for t in self.texts if t.life > 0]
        self.flash_life = max(0.0, self.flash_life - dt)
        self.shake = max(0.0, self.shake - dt * 30)

    def draw(self, surface: pygame.Surface):
        for p in self.particles:
            r = max(1, int(p.size * (p.life / p.max_life)))
            pygame.draw.circle(surface, p.color, (int(p.x), int(p.y)), r)
        for t in self.texts:
            k = t.life / t.max_life
            img = t.font.render(t.text, True, t.color)
            if t.pop:
                scale = min(1.0, (1 - k) * 6) * (1 + 0.1 * math.sin((1 - k) * 12))
                if scale <= 0.05:
                    continue
                img = pygame.transform.rotozoom(img, 0, scale)
            outline = t.font.render(t.text, True, (0, 0, 0))
            if t.pop:
                outline = pygame.transform.rotozoom(outline, 0, scale)
            img.set_alpha(int(255 * min(1.0, k * 3)))
            outline.set_alpha(int(200 * min(1.0, k * 3)))
            rect = img.get_rect(center=(int(t.x), int(t.y)))
            for dx, dy in ((-3, 0), (3, 0), (0, -3), (0, 3)):
                surface.blit(outline, rect.move(dx, dy))
            surface.blit(img, rect)
        if self.flash_life > 0 and self.flash_color:
            overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
            overlay.fill((*self.flash_color, int(110 * self.flash_life / 0.25)))
            surface.blit(overlay, (0, 0))
