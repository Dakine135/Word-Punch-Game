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
    gravity: float = 900.0
    rect: bool = False      # chunky debris instead of a dot
    spin: float = 0.0


@dataclass
class Ring:
    """An expanding shockwave circle."""
    x: float
    y: float
    r0: float
    r1: float
    life: float
    max_life: float
    color: tuple
    width: int


@dataclass
class Sprite:
    """A flying image (e.g. half of a sliced word block)."""
    img: pygame.Surface
    x: float
    y: float
    vx: float
    vy: float
    rot: float
    vrot: float
    life: float
    max_life: float


@dataclass
class Streak:
    """A bright slash line that fades out."""
    x0: float
    y0: float
    x1: float
    y1: float
    color: tuple
    life: float
    max_life: float


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
        self.rings: list[Ring] = []
        self.sprites: list[Sprite] = []
        self.streaks: list[Streak] = []
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

    def ring(self, x, y, color, r0=10, r1=160, life=0.4, width=8):
        self.rings.append(Ring(x, y, r0, r1, life, life, color, width))

    def debris(self, x, y, w, h, colors, n=18, speed=600):
        """Chunks of a broken word block flying apart."""
        for _ in range(n):
            px, py = x + random.uniform(-w / 2, w / 2), y + random.uniform(-h / 2, h / 2)
            a = math.atan2(py - y, px - x) + random.uniform(-0.5, 0.5)
            s = random.uniform(0.4, 1.0) * speed
            life = random.uniform(0.6, 1.1)
            self.particles.append(Particle(px, py, math.cos(a) * s, math.sin(a) * s - speed * 0.5,
                                           life, life, random.choice(colors), random.uniform(10, 22),
                                           gravity=1400, rect=True, spin=random.uniform(-12, 12)))

    def trail(self, x, y, color, size=14):
        """Flame puffs behind a rocket; call every frame while it flies."""
        for c in (color, (255, 200, 60), (255, 140, 40)):
            life = random.uniform(0.18, 0.35)
            self.particles.append(Particle(x + random.uniform(-size / 2, size / 2), y,
                                           random.uniform(-40, 40), random.uniform(150, 300),
                                           life, life, c, random.uniform(0.6, 1.0) * size, gravity=0))

    def split(self, img: pygame.Surface, x: float, y: float, angle: float, speed: float = 420) -> None:
        """Cut a block image in two along the swipe and send the halves flying apart."""
        w, h = img.get_size()
        horizontal = abs(math.cos(angle)) >= abs(math.sin(angle))  # swipe mostly sideways -> cut top/bottom
        if horizontal:
            parts = [(img.subsurface((0, 0, w, h // 2)).copy(), 0, -h / 4, (0, -1)),
                     (img.subsurface((0, h // 2, w, h - h // 2)).copy(), 0, h / 4, (0, 1))]
        else:
            parts = [(img.subsurface((0, 0, w // 2, h)).copy(), -w / 4, 0, (-1, 0)),
                     (img.subsurface((w // 2, 0, w - w // 2, h)).copy(), w / 4, 0, (1, 0))]
        dx, dy = math.cos(angle), math.sin(angle)  # carry some of the swipe's motion
        for part, ox, oy, (nx, ny) in parts:
            vx = nx * speed * 0.6 + dx * speed * 0.5 + random.uniform(-60, 60)
            vy = ny * speed * 0.6 + dy * speed * 0.3 - speed * 0.5
            spin = random.uniform(120, 300) * (1 if (nx + ny) > 0 else -1)
            self.sprites.append(Sprite(part, x + ox, y + oy, vx, vy, 0.0, spin, 1.3, 1.3))

    def streak(self, x0, y0, x1, y1, color, life=0.25):
        self.streaks.append(Streak(x0, y0, x1, y1, color, life, life))

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
            p.vy += p.gravity * dt
        self.particles = [p for p in self.particles if p.life > 0]
        for r in self.rings:
            r.life -= dt
        self.rings = [r for r in self.rings if r.life > 0]
        for s in self.sprites:
            s.life -= dt
            s.x += s.vx * dt
            s.y += s.vy * dt
            s.vy += 1500 * dt
            s.rot += s.vrot * dt
        self.sprites = [s for s in self.sprites if s.life > 0]
        for s in self.streaks:
            s.life -= dt
        self.streaks = [s for s in self.streaks if s.life > 0]
        for t in self.texts:
            t.life -= dt
            t.y -= t.rise * dt
        self.texts = [t for t in self.texts if t.life > 0]
        self.flash_life = max(0.0, self.flash_life - dt)
        self.shake = max(0.0, self.shake - dt * 30)

    def draw(self, surface: pygame.Surface):
        for s in self.sprites:
            img = pygame.transform.rotate(s.img, s.rot)
            img.set_alpha(int(255 * min(1.0, s.life / s.max_life * 2.5)))
            surface.blit(img, img.get_rect(center=(int(s.x), int(s.y))))
        for st in self.streaks:
            k = st.life / st.max_life
            # extend the line a bit past both ends, like a blade flash
            dx, dy = st.x1 - st.x0, st.y1 - st.y0
            a = (st.x0 - dx * 0.3, st.y0 - dy * 0.3)
            b = (st.x1 + dx * 0.3, st.y1 + dy * 0.3)
            pygame.draw.line(surface, st.color, a, b, max(2, int(18 * k)))
            pygame.draw.line(surface, (255, 255, 255), a, b, max(1, int(7 * k)))
        for ring in self.rings:
            k = 1 - ring.life / ring.max_life  # 0 -> 1
            radius = int(ring.r0 + (ring.r1 - ring.r0) * (1 - (1 - k) ** 2))  # ease out
            width = max(1, int(ring.width * (1 - k)))
            if radius > width:
                pygame.draw.circle(surface, ring.color, (int(ring.x), int(ring.y)), radius, width)
        for p in self.particles:
            k = p.life / p.max_life
            if p.rect:
                size = max(2, int(p.size * min(1.0, k * 2)))
                chunk = pygame.Surface((size, size), pygame.SRCALPHA)
                chunk.fill(p.color)
                chunk = pygame.transform.rotate(chunk, (p.max_life - p.life) * p.spin * 57)
                surface.blit(chunk, chunk.get_rect(center=(int(p.x), int(p.y))))
            else:
                pygame.draw.circle(surface, p.color, (int(p.x), int(p.y)), max(1, int(p.size * k)))

    def draw_texts(self, surface: pygame.Surface):
        """Floating text and screen flash; drawn after the HUD so nothing hides them."""
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
