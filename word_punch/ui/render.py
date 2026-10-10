"""Draws the game: falling word blocks, fist rockets, hands, lanes and the HUD."""
from __future__ import annotations

import math
from pathlib import Path

import pygame

from ..game.core import Event, Game

FONTS = Path(__file__).resolve().parent.parent.parent / "assets" / "fonts"
PLAYER_COLORS = [(255, 90, 90), (70, 170, 255), (110, 225, 90)]
GOLD = (255, 205, 50)
WHITE = (255, 255, 255)
INK = (30, 30, 45)


def font(size: int, bold: bool = True) -> pygame.font.Font:
    path = FONTS / ("Andika-Bold.ttf" if bold else "Andika-Regular.ttf")
    if path.exists():
        return pygame.font.Font(str(path), size)
    return pygame.font.SysFont("arial", size, bold=bold)


class Renderer:
    def __init__(self, size: tuple[int, int]):
        self.w, self.h = size
        self.word_font = font(int(self.h * 0.085))
        self.letter_font = font(int(self.h * 0.12))
        self.hud_font = font(int(self.h * 0.04))
        self.small_font = font(int(self.h * 0.03), bold=False)
        self.pop_font = font(int(self.h * 0.06))
        self.big_font = font(int(self.h * 0.11))
        self._text_cache: dict = {}

    # ---- sizes (the game uses these for collisions) ------------------------------

    def measure(self, text: str, is_letter: bool) -> tuple[int, int]:
        f = self.letter_font if is_letter else self.word_font
        tw, th = f.size(text)
        pad_x, pad_y = int(f.get_height() * 0.45), int(f.get_height() * 0.08)
        return tw + 2 * pad_x, th + 2 * pad_y

    def _text(self, text, f, color):
        key = (text, id(f), color)
        if key not in self._text_cache:
            if len(self._text_cache) > 400:
                self._text_cache.clear()
            self._text_cache[key] = f.render(text, True, color)
        return self._text_cache[key]

    # ---- drawing -------------------------------------------------------------------

    def draw_background(self, surface: pygame.Surface, game: Game) -> None:
        if game.mode == "split" and len(game.lanes) > 1:
            for lane in game.lanes[1:]:
                x = int(lane.x0)
                for y in range(0, self.h, 28):
                    pygame.draw.line(surface, (255, 255, 255), (x, y), (x, y + 14), 3)
        # glowing floor line
        fy = int(game.floor)
        for lane in game.lanes:
            color = PLAYER_COLORS[lane.players[0] % 3] if game.mode == "split" else (255, 120, 60)
            if not lane.alive:
                color = (90, 90, 90)
            pygame.draw.line(surface, color, (int(lane.x0), fy), (int(lane.x1), fy), 6)

    def draw_words(self, surface: pygame.Surface, game: Game, now: float) -> None:
        for w in game.words:
            rect = pygame.Rect(0, 0, w.w, w.h)
            rect.center = (int(w.x), int(w.y))
            f = self.letter_font if w.is_letter else self.word_font
            radius = int(w.h * 0.3)
            if w.unlocked:
                pulse = 0.5 + 0.5 * math.sin(now * 10 + w.id)
                glow = rect.inflate(18 + 10 * pulse, 18 + 10 * pulse)
                g = pygame.Surface(glow.size, pygame.SRCALPHA)
                pygame.draw.rect(g, (255, 236, 140, 170), g.get_rect(), border_radius=radius + 8)
                surface.blit(g, glow)
                pygame.draw.rect(surface, GOLD, rect, border_radius=radius)
                pygame.draw.rect(surface, WHITE, rect, 4, border_radius=radius)
                txt = self._text(w.text, f, INK)
            else:
                block = pygame.Surface(rect.size, pygame.SRCALPHA)
                pygame.draw.rect(block, (35, 42, 70, 225), block.get_rect(), border_radius=radius)
                surface.blit(block, rect)
                pygame.draw.rect(surface, (150, 160, 200), rect, 3, border_radius=radius)
                txt = self._text(w.text, f, WHITE)
            surface.blit(txt, txt.get_rect(center=rect.center))
            for i in range(w.misses):  # gentle mode: how many times it fell
                pygame.draw.circle(surface, (255, 120, 120), (rect.right - 10 - 14 * i, rect.top + 10), 5)

    def draw_rockets(self, surface: pygame.Surface, game: Game) -> None:
        for r in game.rockets:
            color = PLAYER_COLORS[r.player % 3]
            x, y, rad = int(r.x), int(r.y), int(r.radius)
            # trail
            for i in range(1, 6):
                t = pygame.Surface((rad * 2, rad * 2), pygame.SRCALPHA)
                pygame.draw.circle(t, (*color, 120 - i * 20), (rad, rad), max(2, rad - i * rad // 6))
                surface.blit(t, (x - rad, y + i * rad // 2 - rad))
            self._draw_fist(surface, x, y, rad, color)

    def _draw_fist(self, surface, x, y, rad, color):
        body = pygame.Rect(0, 0, int(rad * 1.6), int(rad * 1.5))
        body.center = (x, y + rad // 4)
        pygame.draw.rect(surface, color, body, border_radius=rad // 2)
        pygame.draw.rect(surface, WHITE, body, 3, border_radius=rad // 2)
        kr = max(3, rad // 4)
        for i in range(4):  # knuckles on top
            kx = body.left + kr + i * (body.width - 2 * kr) // 3
            pygame.draw.circle(surface, color, (kx, body.top + kr // 2), kr)
            pygame.draw.circle(surface, WHITE, (kx, body.top + kr // 2), kr, 2)

    def draw_hands(self, surface: pygame.Surface, hands: list[tuple[int, int, int]], now: float) -> None:
        """hands: (player, x, y) in screen pixels."""
        for player, x, y in hands:
            color = PLAYER_COLORS[player % 3]
            r = int(self.h * 0.035 + 4 * math.sin(now * 6))
            pygame.draw.circle(surface, color, (x, y), r, 6)
            pygame.draw.circle(surface, WHITE, (x, y), r + 4, 2)

    @property
    def hud_height(self) -> int:
        return int(self.h * 0.19)

    def draw_hud(self, surface: pygame.Surface, game: Game) -> None:
        pad = 14
        # Words emerge from behind this strip.
        strip = pygame.Surface((self.w, self.hud_height), pygame.SRCALPHA)
        strip.fill((12, 14, 30, 215))
        surface.blit(strip, (0, 0))
        pygame.draw.line(surface, (90, 100, 150), (0, self.hud_height), (self.w, self.hud_height), 2)
        if game.mode == "split":
            for lane in game.lanes:
                p = game.players[lane.players[0]]
                self._player_panel(surface, game, p, lane, int(lane.x0) + pad, pad)
        else:
            lane = game.lanes[0]
            x = pad
            for p in game.players:
                x = self._player_panel(surface, game, p, None, x, pad) + 30
            # shared lives + level at the right
            self._lives_and_level(surface, game, lane, self.w - pad, pad, align_right=True)
            if game.mode == "coop":
                total = sum(p.score for p in game.players)
                t = self._text(f"Team {total}", self.hud_font, GOLD)
                surface.blit(t, (self.w // 2 - t.get_width() // 2, pad))

    def _player_panel(self, surface, game, p, lane, x, y) -> int:
        color = PLAYER_COLORS[p.index % 3]
        name = self._text(p.name, self.hud_font, color)
        score = self._text(f"{p.score}", self.hud_font, WHITE)
        surface.blit(name, (x, y))
        surface.blit(score, (x + name.get_width() + 14, y))
        end = x + name.get_width() + 14 + score.get_width()
        if p.combo >= 2:
            c = self._text(f"x{p.combo} combo", self.small_font, GOLD)
            surface.blit(c, (x, y + name.get_height()))
        if lane is not None:
            self._lives_and_level(surface, game, lane, x, y + int(name.get_height() * 1.6), align_right=False)
        return end

    def _heart(self, surface, x, y, size, color):
        r = size // 4
        pygame.draw.circle(surface, color, (x + r, y + r), r)
        pygame.draw.circle(surface, color, (x + 3 * r, y + r), r)
        pygame.draw.polygon(surface, color, [(x, y + r + 1), (x + 4 * r, y + r + 1), (x + 2 * r, y + 4 * r)])

    def _lives_and_level(self, surface, game, lane, x, y, align_right) -> int:
        track = lane.tracks[0]
        level_names = " + ".join(dict.fromkeys(t.level.name for t in lane.tracks))
        t = self._text(level_names, self.small_font, WHITE)
        size = t.get_height()
        lives = 0 if lane.lives is None else max(lane.lives, 0)
        width = t.get_width() + (16 + lives * (size + 4) if lives else 0)
        tx = x - width if align_right else x
        surface.blit(t, (tx, y))
        for i in range(lives):
            self._heart(surface, tx + t.get_width() + 16 + i * (size + 4), y + size // 6, size - 4, (255, 80, 110))
        # mastery progress bar for the (first) track
        bar = pygame.Rect(tx, y + size + 4, max(120, width), 8)
        pygame.draw.rect(surface, (60, 60, 80), bar, border_radius=4)
        fill = bar.copy()
        fill.width = int(bar.width * track.progress())
        pygame.draw.rect(surface, GOLD, fill, border_radius=4)
        return tx

    def draw_lane_out(self, surface: pygame.Surface, game: Game) -> None:
        for lane in game.lanes:
            if lane.alive or game.over:
                continue
            shade = pygame.Surface((int(lane.x1 - lane.x0), self.h), pygame.SRCALPHA)
            shade.fill((0, 0, 0, 150))
            surface.blit(shade, (int(lane.x0), 0))
            t = self._text("Great job!", self.pop_font, WHITE)
            surface.blit(t, t.get_rect(center=((lane.x0 + lane.x1) / 2, self.h / 2)))

    def draw_game_over(self, surface: pygame.Surface, game: Game, hint: str) -> None:
        shade = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
        shade.fill((0, 0, 0, 170))
        surface.blit(shade, (0, 0))
        title = self._text("Game Over!", self.big_font, GOLD)
        surface.blit(title, title.get_rect(center=(self.w // 2, int(self.h * 0.2))))
        ranked = sorted(game.players, key=lambda p: -p.score)
        for i, p in enumerate(ranked):
            crown = "★ " if i == 0 and game.mode == "competitive" and len(ranked) > 1 else ""
            words = "word" if p.broken == 1 else "words"
            line = f"{crown}{p.name}:  {p.score} points   {p.broken} {words}   best combo x{p.best_combo}"
            t = self._text(line, self.hud_font, PLAYER_COLORS[p.index % 3])
            surface.blit(t, t.get_rect(center=(self.w // 2, int(self.h * (0.4 + 0.09 * i)))))
        h = self._text(hint, self.hud_font, WHITE)
        surface.blit(h, h.get_rect(center=(self.w // 2, int(self.h * 0.85))))

    def draw_say_hint(self, surface: pygame.Surface, text: str) -> None:
        t = self._text(text, self.small_font, (230, 230, 230))
        surface.blit(t, t.get_rect(midbottom=(self.w // 2, self.h - 6)))
