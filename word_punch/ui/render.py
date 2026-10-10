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
        """Text with a dark outline so it reads well over the camera picture."""
        key = (text, id(f), color)
        if key not in self._text_cache:
            if len(self._text_cache) > 400:
                self._text_cache.clear()
            fg = f.render(text, True, color)
            bg = f.render(text, True, (0, 0, 0))
            out = pygame.Surface((fg.get_width() + 4, fg.get_height() + 4), pygame.SRCALPHA)
            for dx, dy in ((0, 2), (4, 2), (2, 0), (2, 4), (3, 3)):
                out.blit(bg, (dx, dy))
            out.blit(fg, (2, 2))
            self._text_cache[key] = out
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

    def block_image(self, w) -> pygame.Surface:
        """A plain gold (unlocked) word block, used for sliced halves."""
        img = pygame.Surface((w.w, w.h), pygame.SRCALPHA)
        rect = img.get_rect()
        radius = int(w.h * 0.3)
        pygame.draw.rect(img, GOLD, rect, border_radius=radius)
        pygame.draw.rect(img, WHITE, rect, 4, border_radius=radius)
        f = self.letter_font if w.is_letter else self.word_font
        txt = self._text(w.text, f, INK)
        img.blit(txt, txt.get_rect(center=rect.center))
        return img

    def draw_blades(self, surface: pygame.Surface, blades: dict, now: float, life: float = 0.22) -> None:
        """Glowing trails behind fast-moving hands (slice mode). blades: key -> [(t, x, y, player)]."""
        for pts in blades.values():
            pts = [p for p in pts if now - p[0] < life]
            if len(pts) < 2:
                continue
            color = PLAYER_COLORS[pts[-1][3] % 3]
            for (t0, x0, y0, _), (t1, x1, y1, _) in zip(pts, pts[1:]):
                k = 1 - (now - t1) / life
                pygame.draw.line(surface, color, (x0, y0), (x1, y1), max(2, int(22 * k)))
                pygame.draw.line(surface, WHITE, (x0, y0), (x1, y1), max(1, int(8 * k)))

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

    def glove(self, color: tuple, height: int) -> pygame.Surface:
        """A cartoon boxing glove pointing up, cached per color/size."""
        key = ("glove", color, height)
        if key in self._text_cache:
            return self._text_cache[key]
        k = 3  # draw big, then smooth-scale down for clean edges
        H = height * k
        W = int(H * 0.78)
        surf = pygame.Surface((W, H), pygame.SRCALPHA)
        dark = tuple(int(c * 0.55) for c in color)
        light = tuple(min(255, int(c + (255 - c) * 0.55)) for c in color)
        o = 4 * k  # outline width
        fist = pygame.Rect(int(W * 0.12), 0, int(W * 0.84), int(H * 0.66))
        thumb = pygame.Rect(0, int(H * 0.26), int(W * 0.36), int(H * 0.36))
        cuff = pygame.Rect(int(W * 0.22), int(H * 0.6), int(W * 0.62), int(H * 0.38))
        for shape, fill in ((cuff, (245, 245, 250)), (fist, color), (thumb, color)):
            if shape is cuff:
                pygame.draw.rect(surf, dark, shape, border_radius=10 * k)
                pygame.draw.rect(surf, fill, shape.inflate(-2 * o, -2 * o), border_radius=8 * k)
            else:
                pygame.draw.ellipse(surf, dark, shape)
                pygame.draw.ellipse(surf, fill, shape.inflate(-2 * o, -2 * o))
        # thumb crease, cuff stripe, shine
        pygame.draw.arc(surf, dark, thumb.inflate(-o, -o).move(int(W * 0.05), 0), 0.3, 2.2, 3 * k)
        pygame.draw.line(surf, color, (cuff.left + o, cuff.top + cuff.height // 2),
                         (cuff.right - o, cuff.top + cuff.height // 2), 5 * k)
        shine = pygame.Rect(int(W * 0.3), int(H * 0.06), int(W * 0.28), int(H * 0.16))
        pygame.draw.ellipse(surf, light, shine)
        out = pygame.transform.smoothscale(surf, (W // k, H // k))
        self._text_cache[key] = out
        return out

    def draw_rockets(self, surface: pygame.Surface, game: Game, now: float = 0.0) -> None:
        for r in game.rockets:
            color = PLAYER_COLORS[r.player % 3]
            g = self.glove(color, int(r.radius * 3.4))
            wobble = math.sin(now * 40 + r.x) * 2
            rect = g.get_rect(center=(int(r.x + wobble), int(r.y)))
            # speed lines
            for dx, length in ((-0.55, 1.3), (0.55, 1.1), (0.0, 1.6)):
                x = int(r.x + dx * rect.width)
                pygame.draw.line(surface, (255, 255, 255), (x, rect.bottom),
                                 (x, rect.bottom + int(r.radius * length)), 3)
            surface.blit(g, rect)

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

    def round_progress(self, game: Game, lane, player=None) -> str:
        if game.round_end != "words":
            return ""
        if game.mode == "competitive" and player is not None:
            return f"{player.broken}/{game.round_words}"
        return f"{lane.broken}/{game.word_goal(lane)}"

    def draw_hud(self, surface: pygame.Surface, game: Game, now: float = 0.0) -> None:
        pad = 14
        # Words emerge from behind this strip.
        strip = pygame.Surface((self.w, self.hud_height), pygame.SRCALPHA)
        strip.fill((12, 14, 30, 105))  # see-through: kids can see their heads and fists
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
                prog = self.round_progress(game, lane)
                t = self._text(f"Team {total}" + (f"   {prog} words" if prog else ""), self.hud_font, GOLD)
                surface.blit(t, (self.w // 2 - t.get_width() // 2, pad))
        left = game.time_left(now) if now else None
        if left is not None:
            m, s = divmod(int(left + 0.999), 60)
            color = (255, 120, 120) if left < 15 else WHITE
            t = self._text(f"{m}:{s:02d}", self.hud_font, color)
            surface.blit(t, t.get_rect(midtop=(self.w // 2, pad + (40 if game.mode == "coop" else 0))))

    def _player_panel(self, surface, game, p, lane, x, y) -> int:
        color = PLAYER_COLORS[p.index % 3]
        name = self._text(p.name, self.hud_font, color)
        score = self._text(f"{p.score}", self.hud_font, WHITE)
        surface.blit(name, (x, y))
        surface.blit(score, (x + name.get_width() + 14, y))
        end = x + name.get_width() + 14 + score.get_width()
        lane_for = lane if lane is not None else game.lanes[0]
        prog = self.round_progress(game, lane_for, p) if (lane is not None or game.mode == "competitive") else ""
        if prog:
            t = self._text(prog, self.small_font, GOLD)
            surface.blit(t, (end + 14, y + 8))
            end += 14 + t.get_width()
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

    def draw_lane_out(self, surface: pygame.Surface, game: Game, now: float = 0.0) -> None:
        for lane in game.lanes:
            if lane.alive or game.over:
                continue
            shade = pygame.Surface((int(lane.x1 - lane.x0), self.h), pygame.SRCALPHA)
            shade.fill((40, 30, 0, 140) if lane.done else (0, 0, 0, 150))
            surface.blit(shade, (int(lane.x0), 0))
            cx = (lane.x0 + lane.x1) / 2
            if lane.done:
                bob = math.sin(now * 3) * 8
                t = self._text("Finished!", self.big_font, GOLD)
                surface.blit(t, t.get_rect(center=(cx, self.h / 2 - 30 + bob)))
                self._star(surface, cx, self.h / 2 + 70 + bob, 40, now)
            else:
                t = self._text("Great job!", self.pop_font, WHITE)
                surface.blit(t, t.get_rect(center=(cx, self.h / 2)))

    def _star(self, surface, cx, cy, r, now, color=GOLD):
        pts = []
        spin = now * 0.8
        for i in range(10):
            rad = r if i % 2 == 0 else r * 0.45
            a = spin + i * math.pi / 5 - math.pi / 2
            pts.append((cx + math.cos(a) * rad, cy + math.sin(a) * rad))
        pygame.draw.polygon(surface, color, pts)
        pygame.draw.polygon(surface, WHITE, pts, 3)

    def draw_game_over(self, surface: pygame.Surface, game: Game, hint: str) -> None:
        shade = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
        shade.fill((0, 0, 0, 170))
        surface.blit(shade, (0, 0))
        if game.result == "complete":
            if game.mode == "competitive" and game.winner is not None and len(game.players) > 1:
                text = f"{game.players[game.winner].name} wins!"
            else:
                text = "Round complete!"
        else:
            text = "Game Over!"
        title = self._text(text, self.big_font, GOLD)
        surface.blit(title, title.get_rect(center=(self.w // 2, int(self.h * 0.2))))
        ranked = sorted(game.players, key=lambda p: -p.score)
        for i, p in enumerate(ranked):
            words = "word" if p.broken == 1 else "words"
            line = f"{p.name}:  {p.score} points   {p.broken} {words}   best combo x{p.best_combo}"
            t = self._text(line, self.hud_font, PLAYER_COLORS[p.index % 3])
            surface.blit(t, t.get_rect(center=(self.w // 2, int(self.h * (0.4 + 0.09 * i)))))
        h = self._text(hint, self.hud_font, WHITE)
        surface.blit(h, h.get_rect(center=(self.w // 2, int(self.h * 0.85))))

    def draw_say_hint(self, surface: pygame.Surface, text: str) -> None:
        t = self._text(text, self.small_font, (230, 230, 230))
        surface.blit(t, t.get_rect(midbottom=(self.w // 2, self.h - 6)))
