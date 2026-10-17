"""Draws the game: falling word blocks, fist rockets, hands, lanes and the HUD."""
from __future__ import annotations

import math
from pathlib import Path

import pygame

import re

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
        self.color_fn = None  # (player, now) -> glove/blade colour; set by the app (unlockable colours)

    def player_color(self, player: int, now: float) -> tuple:
        if self.color_fn:
            return self.color_fn(player, now)
        return PLAYER_COLORS[player % 3]

    # ---- sizes (the game uses these for collisions) ------------------------------

    max_block_w: int | None = None  # set per game: long words shrink to fit a lane

    def measure(self, text: str, is_letter: bool) -> tuple[int, int]:
        f = self.letter_font if is_letter else self.word_font
        tw, th = f.size(text)
        pad_x, pad_y = int(f.get_height() * 0.45), int(f.get_height() * 0.08)
        w, h = tw + 2 * pad_x, th + 2 * pad_y
        if self.max_block_w and w > self.max_block_w:  # e.g. "comprehensive" with 3 kids
            k = self.max_block_w / w
            w, h = self.max_block_w, max(int(h * k), int(h * 0.7))
        return w, h

    def _fit(self, txt: pygame.Surface, max_w: int) -> pygame.Surface:
        """Shrink rendered text that's wider than its block (long words in narrow lanes)."""
        if txt.get_width() <= max_w:
            return txt
        k = max_w / txt.get_width()
        return pygame.transform.smoothscale(txt, (max_w, max(1, int(txt.get_height() * k))))

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
        txt = self._fit(txt, rect.width - 24)
        img.blit(txt, txt.get_rect(center=rect.center))
        return img

    def draw_blades(self, surface: pygame.Surface, blades: dict, now: float, life: float = 0.22) -> None:
        """Glowing trails behind fast-moving hands (slice mode). blades: key -> [(t, x, y, player)]."""
        for pts in blades.values():
            pts = [p for p in pts if now - p[0] < life]
            if len(pts) < 2:
                continue
            color = self.player_color(pts[-1][3], now)
            for (t0, x0, y0, _), (t1, x1, y1, _) in zip(pts, pts[1:]):
                k = 1 - (now - t1) / life
                pygame.draw.line(surface, color, (x0, y0), (x1, y1), max(2, int(22 * k)))
                pygame.draw.line(surface, WHITE, (x0, y0), (x1, y1), max(1, int(8 * k)))

    def draw_words(self, surface: pygame.Surface, game: Game, now: float) -> None:
        for w in game.words:
            if w.scale <= 0.03:
                continue
            f = self.big_font if w.big else self.letter_font if w.is_letter else self.word_font
            radius = int(w.h * 0.3)
            pad = 16
            blk = pygame.Surface((w.w + 2 * pad, w.h + 2 * pad), pygame.SRCALPHA)
            rect = pygame.Rect(pad, pad, w.w, w.h)
            if w.neutral:  # catch: plain, all look the same - find it by reading
                pygame.draw.rect(blk, (248, 248, 252), rect, border_radius=radius)
                pygame.draw.rect(blk, (120, 130, 175), rect, 4, border_radius=radius)
                txt = self._text(w.text, f, INK)
            elif w.unlocked:
                pulse = 0.5 + 0.5 * math.sin(now * 10 + w.id)
                glow = rect.inflate(10 + 10 * pulse, 10 + 10 * pulse)
                pygame.draw.rect(blk, (255, 236, 140, 170), glow, border_radius=radius + 8)
                pygame.draw.rect(blk, GOLD, rect, border_radius=radius)
                pygame.draw.rect(blk, WHITE, rect, 4, border_radius=radius)
                txt = self._text(w.text, f, INK)
            else:
                pygame.draw.rect(blk, (35, 42, 70, 225), rect, border_radius=radius)
                pygame.draw.rect(blk, (150, 160, 200), rect, 3, border_radius=radius)
                txt = self._text(w.text, f, WHITE)
            txt = self._fit(txt, rect.width - 24)
            blk.blit(txt, txt.get_rect(center=rect.center))
            if w.scale < 1.0:
                sw, sh = max(1, int(blk.get_width() * w.scale)), max(1, int(blk.get_height() * w.scale))
                blk = pygame.transform.smoothscale(blk, (sw, sh))
                # pop up from the bottom (whack holes)
                dest = blk.get_rect(midbottom=(int(w.x), int(w.y + (w.h / 2 + pad))))
            else:
                dest = blk.get_rect(center=(int(w.x), int(w.y)))
            surface.blit(blk, dest)
            screen_rect = pygame.Rect(0, 0, int(w.w * w.scale), int(w.h * w.scale))
            screen_rect.center = dest.center
            if w.scale < 0.9:
                continue
            if w.power:
                self._power_badge(surface, w, screen_rect, now)
            if now < w.lane.freeze_until:
                ice = pygame.Surface(screen_rect.size, pygame.SRCALPHA)
                pygame.draw.rect(ice, (170, 230, 255, 90), ice.get_rect(), border_radius=radius)
                surface.blit(ice, screen_rect)
                pygame.draw.rect(surface, (200, 240, 255), screen_rect, 3, border_radius=radius)
            if w.big and w.hits > 0:  # boss word: hits left
                for i in range(w.hits):
                    self._star(surface, screen_rect.centerx + (i - (w.hits - 1) / 2) * 44,
                               screen_rect.bottom + 26, 16, 0.0, (255, 90, 90))
            for i in range(w.misses):  # gentle mode: how many times it fell
                pygame.draw.circle(surface, (255, 120, 120), (screen_rect.right - 10 - 14 * i, screen_rect.top + 10), 5)

    # ---- extras for the other games ------------------------------------------------------

    def draw_holes(self, surface: pygame.Surface, game, front: bool = False) -> None:
        """Whack-a-word holes; the front lip is drawn over the words so they rise out of it."""
        for lane in game.lanes:
            for x, y in getattr(lane, "holes", []):
                r = pygame.Rect(0, 0, 210, 54)
                r.center = (int(x), int(y + self.h * 0.055))
                if front:
                    pygame.draw.arc(surface, (120, 85, 55), r, math.pi, 2 * math.pi, 10)
                else:
                    pygame.draw.ellipse(surface, (20, 14, 10), r)
                    pygame.draw.ellipse(surface, (120, 85, 55), r, 8)

    def draw_boss(self, surface: pygame.Surface, game, now: float) -> None:
        if getattr(game, "defeated", False):
            return
        x = game.boss_x + math.sin(now * 1.3) * 30
        y = game.boss_y + math.sin(now * 2.1) * 8
        r = game.boss_r
        hurt = now < game.hurt_until
        frac = game.boss_hp / max(1, game.boss_max)
        body = (int(120 + 100 * (1 - frac)), int(70 + 90 * frac), int(170 * frac + 60)) if not hurt else (255, 255, 255)
        shake = math.sin(now * 80) * 8 if hurt else 0
        x += shake
        # horns
        for s in (-1, 1):
            pygame.draw.polygon(surface, (240, 230, 200), [(x + s * r * 0.45, y - r * 0.7), (x + s * r * 0.9, y - r * 1.35),
                                                             (x + s * r * 0.75, y - r * 0.55)])
        pygame.draw.ellipse(surface, body, (x - r * 1.1, y - r, r * 2.2, r * 1.9))
        pygame.draw.ellipse(surface, (30, 20, 40), (x - r * 1.1, y - r, r * 2.2, r * 1.9), 5)
        # eyes look down at the kids; squint when hurt
        for s in (-1, 1):
            ex, ey = x + s * r * 0.42, y - r * 0.25
            if hurt:
                pygame.draw.line(surface, (30, 20, 40), (ex - 18, ey - 8), (ex + 18, ey + 8), 6)
                pygame.draw.line(surface, (30, 20, 40), (ex - 18, ey + 8), (ex + 18, ey - 8), 6)
            else:
                pygame.draw.circle(surface, WHITE, (ex, ey), r * 0.24)
                pygame.draw.circle(surface, (30, 20, 40), (ex, ey + r * 0.08), r * 0.11)
            pygame.draw.line(surface, (30, 20, 40), (ex - s * r * 0.3, ey - r * 0.38), (ex + s * r * 0.1, ey - r * 0.25), 7)
        # mouth with teeth
        mouth = pygame.Rect(0, 0, r * 1.1, r * (0.5 if hurt else 0.35))
        mouth.center = (int(x), int(y + r * 0.42))
        pygame.draw.ellipse(surface, (60, 10, 20), mouth)
        for i in range(5):
            tx = mouth.left + (i + 0.5) * mouth.width / 5
            pygame.draw.polygon(surface, WHITE, [(tx - 9, mouth.top + 4), (tx + 9, mouth.top + 4), (tx, mouth.top + 20)])
        # health bar
        bar = pygame.Rect(0, 0, int(self.w * 0.4), 22)
        bar.midtop = (self.w // 2, self.hud_height + 8)
        pygame.draw.rect(surface, (40, 30, 50), bar, border_radius=10)
        fill = bar.copy()
        fill.width = int(bar.width * frac)
        pygame.draw.rect(surface, (230, 60, 80), fill, border_radius=10)
        pygame.draw.rect(surface, WHITE, bar, 3, border_radius=10)
        t = self._text(f"BOSS  {game.boss_hp}", self.small_font, WHITE)
        surface.blit(t, t.get_rect(midleft=(bar.right + 12, bar.centery)))

    def draw_sentence_bar(self, surface: pygame.Surface, game, now: float) -> None:
        if not game.tokens and not game.sentence:
            return
        f = self.word_font
        y = int(game.bar_y)
        bg = pygame.Rect(int(self.w * 0.05), y - 44, int(self.w * 0.9), 88)
        panel = pygame.Surface(bg.size, pygame.SRCALPHA)
        panel.fill((12, 14, 30, 190))
        surface.blit(panel, bg)
        pygame.draw.rect(surface, (120, 130, 180), bg, 3, border_radius=14)
        toks = game.tokens or re_words(game.sentence)
        widths = [f.size(t)[0] + 30 for t in toks]
        x = self.w / 2 - sum(widths) / 2
        for i, (tok, wd) in enumerate(zip(toks, widths)):
            cx = x + wd / 2
            if i < game.placed or not game.tokens:
                t = self._text(tok, f, GOLD)
                surface.blit(t, t.get_rect(center=(cx, y)))
            else:
                nxt = i == game.placed
                k = 0.5 + 0.5 * math.sin(now * 6) if nxt else 0
                color = (255, 255, 255) if nxt else (110, 115, 140)
                pygame.draw.line(surface, color, (x + 8, y + 26 - 4 * k), (x + wd - 8, y + 26 - 4 * k), 6)
            x += wd
        if game.sentence and game.sentence[-1] in ".?!" and (not game.tokens or game.placed == len(game.tokens)):
            t = self._text(game.sentence[-1], f, GOLD)
            surface.blit(t, t.get_rect(midleft=(x - 10, y)))
        t = self._text(f"Sentence {min(game.done_count + 1, game.goal)} of {game.goal}", self.small_font, WHITE)
        surface.blit(t, t.get_rect(midtop=(self.w // 2, bg.bottom + 4)))

    def draw_listen(self, surface: pygame.Surface, game, now: float) -> None:
        """Catch the word: a speaker that pulses when the word is said."""
        cx, cy = self.w // 2, self.hud_height + 50
        since = now - (game.next_announce - game.ANNOUNCE_EVERY)
        pulse = max(0.0, 1 - since / 1.5)
        pygame.draw.circle(surface, (40, 50, 90), (cx - 120, cy), 34)
        pygame.draw.polygon(surface, WHITE, [(cx - 138, cy - 10), (cx - 126, cy - 10), (cx - 110, cy - 24),
                                             (cx - 110, cy + 24), (cx - 126, cy + 10), (cx - 138, cy + 10)])
        for i in range(3):
            rr = 14 + i * 10 + pulse * 6
            pygame.draw.arc(surface, (255, 255, 255), (cx - 110 - rr, cy - rr, rr * 2, rr * 2), -0.8, 0.8, 4)
        t = self._text("Listen!  Find the word", self.hud_font, GOLD if pulse > 0 else WHITE)
        surface.blit(t, t.get_rect(midleft=(cx - 70, cy)))

    POWER_COLORS = {"gold": (255, 190, 30), "freeze": (120, 210, 255), "giant": (190, 110, 255)}

    def _power_badge(self, surface, w, rect, now) -> None:
        """Shimmering border + a round badge: x2 (gold), snowflake (freeze), fist (giant)."""
        color = self.POWER_COLORS[w.power]
        k = 0.5 + 0.5 * math.sin(now * 8 + w.id)
        pygame.draw.rect(surface, color, rect.inflate(8, 8), 4 + int(3 * k), border_radius=int(w.h * 0.34))
        r = max(14, int(w.h * 0.26))
        cx, cy = rect.right - 4, rect.top + 4
        pygame.draw.circle(surface, color, (cx, cy), r)
        pygame.draw.circle(surface, WHITE, (cx, cy), r, 3)
        if w.power == "gold":
            t = self._text("x2", self.small_font, INK)
            surface.blit(t, t.get_rect(center=(cx, cy)))
        elif w.power == "freeze":
            for i in range(3):
                a = i * math.pi / 3
                dx, dy = math.cos(a) * r * 0.7, math.sin(a) * r * 0.7
                pygame.draw.line(surface, WHITE, (cx - dx, cy - dy), (cx + dx, cy + dy), 3)
        else:
            g = self.glove(WHITE, int(r * 1.5))
            surface.blit(g, g.get_rect(center=(cx, cy)))

    def glove(self, color: tuple, height: int) -> pygame.Surface:
        """A cartoon boxing glove pointing up, cached per color/size."""
        color = tuple(min(255, (c // 24) * 24 + 12) for c in color)  # animated colours: bounded cache
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
            color = self.player_color(r.player, now)
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

    def draw_hand_cursors(self, surface: pygame.Surface, hands: list, now: float) -> None:
        """Menu cursors on raised hands: an open hand when a palm is seen, a fist otherwise."""
        for player, x, y, gesture in hands:
            color = PLAYER_COLORS[player % 3]
            x, y = int(x), int(y)
            r = int(self.h * 0.04)
            if gesture == "Open_Palm":
                glow = pygame.Surface((r * 4, r * 4), pygame.SRCALPHA)
                pygame.draw.circle(glow, (*color, 90), (r * 2, r * 2), int(r * 1.9))
                surface.blit(glow, (x - r * 2, y - r * 2))
                pygame.draw.circle(surface, color, (x, y + r // 3), int(r * 0.8))       # palm
                for i, ang in enumerate((-50, -22, 0, 22, 55)):                         # fingers
                    a = math.radians(ang - 90)
                    ln = r * (0.95 if i in (1, 2) else 0.8)
                    x0, y0 = x + math.cos(a) * r * 0.55, y + r // 3 + math.sin(a) * r * 0.55
                    pygame.draw.line(surface, color, (x0, y0), (x0 + math.cos(a) * ln, y0 + math.sin(a) * ln),
                                     max(4, r // 3))
                pygame.draw.circle(surface, WHITE, (x, y + r // 3), int(r * 0.8), 2)
            else:
                pygame.draw.circle(surface, color, (x, y), int(r * 0.85))                # fist / unsure
                pygame.draw.circle(surface, WHITE, (x, y), int(r * 0.85), 3)
                for i in range(3):
                    kx = x - r // 2 + i * r // 2
                    pygame.draw.line(surface, WHITE, (kx, y - r // 3), (kx, y), 2)

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

    def draw_game_over(self, surface: pygame.Surface, game: Game, hint: str, stars: dict | None = None,
                       totals: dict | None = None, unlocks: dict | None = None, now: float = 0.0) -> None:
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
            y = int(self.h * (0.36 + 0.11 * i))
            t = self._text(line, self.hud_font, PLAYER_COLORS[p.index % 3])
            if stars is not None and p.index in stars:
                rect = t.get_rect(midright=(self.w // 2 + 260, y))
                surface.blit(t, rect)
                got = stars[p.index]
                for s in range(3):
                    pop = 1.0 + 0.25 * math.sin(now * 6 + s) if s < got else 1.0
                    self._star(surface, rect.right + 40 + s * 52, y, int(20 * pop), 0.0,
                               GOLD if s < got else (70, 70, 85))
                extra = f"+{got} = {totals.get(p.index, 0)} stars" if totals else ""
                if unlocks and unlocks.get(p.index):
                    extra += "   New: " + ", ".join(unlocks[p.index]) + "!"
                if extra:
                    e = self._text(extra, self.small_font, GOLD)
                    surface.blit(e, e.get_rect(midleft=(rect.left, y + 34)))
            else:
                surface.blit(t, t.get_rect(center=(self.w // 2, y)))
        h = self._text(hint, self.hud_font, WHITE)
        surface.blit(h, h.get_rect(center=(self.w // 2, int(self.h * 0.85))))

    def draw_say_hint(self, surface: pygame.Surface, text: str) -> None:
        t = self._text(text, self.small_font, (230, 230, 230))
        surface.blit(t, t.get_rect(midbottom=(self.w // 2, self.h - 6)))


def re_words(sentence: str) -> list[str]:
    return re.findall(r"[A-Za-z']+", sentence)
