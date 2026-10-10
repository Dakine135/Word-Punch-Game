"""Stars and the things they unlock: camera hats and glove/blade colours.

Stars only ever add up (nothing is spent), so a kid never loses anything.
Hats are drawn with shapes (no image files) on a 200x200 canvas whose head-top point
is (100, 170) for a head 140 px wide; draw_hat() scales/rotates that onto a real head.
"""
from __future__ import annotations

import colorsys
import math

import pygame

from .vision.pose_backend import Person

HATS = [  # (id, name, stars needed)
    ("none", "No hat", 0),
    ("party", "Party hat", 0),
    ("crown", "Crown", 3),
    ("bunny", "Bunny ears", 6),
    ("cowboy", "Cowboy hat", 10),
    ("pirate", "Pirate hat", 15),
    ("wizard", "Wizard hat", 20),
    ("viking", "Viking helmet", 30),
    ("tophat", "Top hat", 40),
]
COLORS = [  # (id, name, stars needed)
    ("team", "Team colour", 0),
    ("gold", "Gold", 5),
    ("ice", "Ice", 8),
    ("fire", "Fire", 12),
    ("rainbow", "Rainbow", 25),
    ("galaxy", "Galaxy", 35),
]


def unlocked(items, stars: int) -> list:
    return [i for i in items if stars >= i[2]]


def next_locked(items, stars: int):
    return next((i for i in items if stars < i[2]), None)


def item_name(items, item_id: str) -> str:
    return next((n for i, n, _ in items if i == item_id), item_id)


def glove_color(color_id: str, team: tuple, now: float) -> tuple:
    """The colour to draw a kid's glove/blade right now (some are animated)."""
    if color_id == "gold":
        return (255, 200, 40)
    if color_id == "ice":
        return (120, 220, 255)
    if color_id == "fire":
        k = 0.5 + 0.5 * math.sin(now * 9)
        return (255, int(90 + 110 * k), 30)
    if color_id == "rainbow":
        r, g, b = colorsys.hsv_to_rgb((now * 0.6) % 1.0, 0.8, 1.0)
        return (int(r * 255), int(g * 255), int(b * 255))
    if color_id == "galaxy":
        k = 0.5 + 0.5 * math.sin(now * 3)
        return (int(120 + 80 * k), int(60 + 40 * k), 255)
    return team


# ---- stars ----------------------------------------------------------------------------

def stars_for_round(broken: int, reached_goal: bool, misses: int, best_combo: int) -> int:
    """0-3 stars: played (5+ words), reached the goal, and an excellent round."""
    stars = 0
    if broken >= 5:
        stars += 1
    if reached_goal:
        stars += 1
    if broken >= 5 and misses <= 2 and best_combo >= 5:
        stars += 1
    return stars


# ---- hats -----------------------------------------------------------------------------

_cache: dict[str, pygame.Surface] = {}


def hat_surface(hat_id: str) -> pygame.Surface | None:
    if hat_id == "none":
        return None
    if hat_id in _cache:
        return _cache[hat_id]
    k = 2  # draw at 2x then smooth-scale for clean edges
    s = pygame.Surface((200 * k, 200 * k), pygame.SRCALPHA)

    def P(*pts):
        return [(x * k, y * k) for x, y in pts]

    def R(x, y, w, h):
        return pygame.Rect(x * k, y * k, w * k, h * k)

    BLACK, WHITE = (25, 25, 30), (250, 250, 250)
    if hat_id == "party":
        pygame.draw.polygon(s, (255, 90, 160), P((50, 172), (150, 172), (100, 40)))
        for i, y in enumerate((150, 120, 90)):
            w = (172 - y) * 50 / 132
            pygame.draw.line(s, (255, 230, 80) if i % 2 == 0 else (90, 200, 255), (100 * k - w * k, y * k),
                             (100 * k + w * k, y * k), 7 * k)
        pygame.draw.circle(s, (255, 230, 80), (100 * k, 38 * k), 14 * k)
    elif hat_id == "crown":
        pts = P((35, 172), (35, 110), (62, 140), (82, 95), (100, 130), (118, 95), (138, 140), (165, 110), (165, 172))
        pygame.draw.polygon(s, (255, 200, 40), pts)
        pygame.draw.polygon(s, (200, 140, 20), pts, 4 * k)
        for x, c in ((70, (230, 50, 60)), (100, (60, 140, 255)), (130, (40, 190, 90))):
            pygame.draw.circle(s, c, (x * k, 155 * k), 9 * k)
        for x, y in ((35, 108), (82, 93), (118, 93), (165, 108)):
            pygame.draw.circle(s, WHITE, (x * k, y * k), 6 * k)
    elif hat_id == "bunny":
        for cx, tilt in ((72, -12), (128, 12)):
            ear = pygame.Surface((50 * k, 150 * k), pygame.SRCALPHA)
            pygame.draw.ellipse(ear, (245, 245, 250), (0, 0, 50 * k, 150 * k))
            pygame.draw.ellipse(ear, (255, 170, 200), (13 * k, 18 * k, 24 * k, 112 * k))
            ear = pygame.transform.rotate(ear, tilt)
            s.blit(ear, ear.get_rect(midbottom=(cx * k, 180 * k)))
    elif hat_id == "cowboy":
        pygame.draw.ellipse(s, (130, 80, 40), R(5, 145, 190, 38))
        pygame.draw.rect(s, (150, 95, 50), R(50, 85, 100, 75), border_radius=28 * k)
        pygame.draw.rect(s, (90, 50, 25), R(50, 140, 100, 14))
        pygame.draw.ellipse(s, (170, 110, 60), R(5, 145, 190, 38), 4 * k)
    elif hat_id == "pirate":
        pts = P((10, 168), (40, 110), (100, 85), (160, 110), (190, 168), (100, 150))
        pygame.draw.polygon(s, BLACK, pts)
        pygame.draw.polygon(s, (200, 160, 40), pts, 4 * k)
        pygame.draw.circle(s, WHITE, (100 * k, 122 * k), 16 * k)
        pygame.draw.circle(s, BLACK, (94 * k, 120 * k), 4 * k)
        pygame.draw.circle(s, BLACK, (106 * k, 120 * k), 4 * k)
        pygame.draw.line(s, WHITE, (84 * k, 146 * k), (116 * k, 136 * k), 4 * k)
        pygame.draw.line(s, WHITE, (84 * k, 136 * k), (116 * k, 146 * k), 4 * k)
    elif hat_id == "wizard":
        pygame.draw.polygon(s, (90, 60, 190), P((45, 165), (155, 165), (120, 30), (150, 10)))
        pygame.draw.ellipse(s, (70, 45, 160), R(15, 150, 170, 32))
        for x, y, r in ((92, 120, 9), (118, 80, 7), (104, 150, 6), (130, 125, 5)):
            pts = []
            for i in range(10):
                rad = r if i % 2 == 0 else r * 0.45
                a = i * math.pi / 5 - math.pi / 2
                pts.append(((x + math.cos(a) * rad) * k, (y + math.sin(a) * rad) * k))
            pygame.draw.polygon(s, (255, 220, 80), pts)
    elif hat_id == "viking":
        for side in (-1, 1):
            horn = P((100 + side * 58, 150), (100 + side * 92, 120), (100 + side * 98, 70),
                     (100 + side * 84, 110), (100 + side * 55, 128))
            pygame.draw.polygon(s, (245, 240, 220), horn)
            pygame.draw.polygon(s, (180, 170, 140), horn, 3 * k)
        pygame.draw.ellipse(s, (150, 155, 165), R(38, 95, 124, 120))
        s.fill((0, 0, 0, 0), R(0, 172, 200, 28))
        pygame.draw.rect(s, (120, 90, 50), R(36, 158, 128, 16), border_radius=6 * k)
        for x in range(48, 160, 22):
            pygame.draw.circle(s, (220, 200, 120), (x * k, 166 * k), 4 * k)
    elif hat_id == "tophat":
        pygame.draw.ellipse(s, BLACK, R(20, 152, 160, 28))
        pygame.draw.rect(s, BLACK, R(55, 45, 90, 120), border_radius=6 * k)
        pygame.draw.rect(s, (200, 30, 50), R(55, 130, 90, 18))
        pygame.draw.ellipse(s, (60, 60, 70), R(55, 38, 90, 18))
    out = pygame.transform.smoothscale(s, (200, 200))
    _cache[hat_id] = out
    return out


def head_pose(person: Person, to_screen) -> tuple[float, float, float, float] | None:
    """(top_x, top_y, head_width, tilt_degrees) on screen, or None if the head isn't visible."""
    nose = person.get("nose", 0.4)
    if nose is None:
        return None
    nx, ny = to_screen(nose.x, nose.y)
    le, re_ = person.get("left_ear", 0.3), person.get("right_ear", 0.3)
    ls, rs = person.get("left_shoulder", 0.3), person.get("right_shoulder", 0.3)
    if le and re_:
        (x0, y0), (x1, y1) = to_screen(le.x, le.y), to_screen(re_.x, re_.y)
        width = math.hypot(x1 - x0, y1 - y0) * 1.25
    elif ls and rs:
        (x0, y0), (x1, y1) = to_screen(ls.x, ls.y), to_screen(rs.x, rs.y)
        width = math.hypot(x1 - x0, y1 - y0) * 0.6
    else:
        return None
    lft, rgt = person.get("left_eye", 0.3), person.get("right_eye", 0.3)
    tilt = 0.0
    if lft and rgt:
        (ax, ay), (bx, by) = to_screen(lft.x, lft.y), to_screen(rgt.x, rgt.y)
        if bx < ax:
            ax, ay, bx, by = bx, by, ax, ay
        tilt = -math.degrees(math.atan2(by - ay, bx - ax))
    up = math.radians(tilt)
    top_x = nx - math.sin(up) * width * 0.62
    top_y = ny - math.cos(up) * width * 0.62
    return top_x, top_y, width, tilt


def draw_hat(surface: pygame.Surface, hat_id: str, top_x: float, top_y: float, width: float, tilt: float) -> None:
    img = hat_surface(hat_id)
    if img is None or width < 8:
        return
    scale = width / 140
    img = pygame.transform.rotozoom(img, tilt, scale)
    # the canvas point (100, 170) is the head top; account for rotation around the centre
    ox, oy = (100 - 100) * scale, (170 - 100) * scale
    a = math.radians(tilt)
    rx = ox * math.cos(a) + oy * math.sin(a)
    ry = -ox * math.sin(a) + oy * math.cos(a)
    rect = img.get_rect(center=(int(top_x - rx), int(top_y - ry)))
    surface.blit(img, rect)
