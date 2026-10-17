"""What each player looks like, so the game can tell the kids apart from each other (and
from a grown-up walking through) when tracking loses someone for a moment.

Only a few numbers per person: the colours of their top and bottoms (small colour
histograms) and how wide their head is next to their shoulders. They live in memory for the
session and are never saved; no pictures are kept.
"""
from __future__ import annotations

import math
from collections import deque

import numpy as np

from .pose_backend import Person

HUE_BINS = 12   # coloured pixels by hue, plus 4 bins for black / grey / light / white
BINS = HUE_BINS + 4
EAR_PER_EYE = 2.2  # ears are about this much further apart than the eyes


def head_ratio(p: Person) -> float | None:
    """Head width / shoulder width. Kids have big heads for their shoulders (~0.6 for a
    4-7 year old), grown-ups small ones (~0.45). Both widths shrink together when someone
    turns, and both scale with distance, so the ratio holds wherever they stand."""
    ls, rs = p.get("left_shoulder", 0.5), p.get("right_shoulder", 0.5)
    if not (ls and rs):
        return None
    sw = abs(ls.x - rs.x)
    if sw < 0.025:
        return None  # side-on or tiny: too noisy
    le, re = p.get("left_ear", 0.5), p.get("right_ear", 0.5)
    if le and re:
        r = abs(le.x - re.x) / sw
    else:
        ey1, ey2 = p.get("left_eye", 0.5), p.get("right_eye", 0.5)
        if not (ey1 and ey2):
            return None
        r = abs(ey1.x - ey2.x) * EAR_PER_EYE / sw
    return r if 0.15 < r < 1.5 else None


def _hist(crop: np.ndarray) -> list[float] | None:
    import cv2
    h, w = crop.shape[:2]
    if h * w < 64:
        return None
    if max(h, w) > 24:
        s = 24 / max(h, w)
        crop = cv2.resize(crop, (max(2, int(w * s)), max(2, int(h * s))), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(np.ascontiguousarray(crop), cv2.COLOR_RGB2HSV).reshape(-1, 3).astype(np.int32)
    hue, sat, val = hsv[:, 0], hsv[:, 1], hsv[:, 2]
    coloured = (sat >= 50) & (val >= 40)
    bins = np.where(coloured, hue * HUE_BINS // 180,
                    HUE_BINS + np.digitize(val, (60, 130, 200)))
    counts = np.bincount(bins, minlength=BINS).astype(np.float32)
    return (counts / counts.sum()).round(4).tolist()


def _boxes(p: Person, w: int, h: int):
    """(top, bottom) pixel boxes: the shirt between the shoulders and hips, the trousers or
    skirt between the hips and knees."""
    ls, rs = p.get("left_shoulder", 0.4), p.get("right_shoulder", 0.4)
    if not (ls and rs):
        return None, None
    sx0, sx1 = sorted((ls.x * w, rs.x * w))
    sw = sx1 - sx0
    if sw < 8:
        return None, None
    sy = (ls.y + rs.y) / 2 * h
    lh, rh = p.get("left_hip", 0.4), p.get("right_hip", 0.4)
    hy = (lh.y + rh.y) / 2 * h if lh and rh else sy + 1.2 * sw
    torso = hy - sy
    if torso < 4:
        return None, None
    top = (sx0 + 0.15 * sw, sy + 0.12 * torso, sx1 - 0.15 * sw, hy - 0.1 * torso)
    bottom = None
    lk, rk = p.get("left_knee", 0.4), p.get("right_knee", 0.4)
    if lh and rh and (lk or rk):
        ky = sum(k.y for k in (lk, rk) if k) / sum(1 for k in (lk, rk) if k) * h
        hx0, hx1 = sorted((lh.x * w, rh.x * w))
        hw = max(hx1 - hx0, 0.5 * sw)
        if ky - hy > 6:
            bottom = (hx0 - 0.1 * hw, hy + 0.1 * (ky - hy), hx1 + 0.1 * hw, ky)
    return top, bottom


def _body_box(p: Person, w: int, h: int):
    pts = [(k.x * w, k.y * h) for k in p.keypoints.values() if k.vis >= 0.3]
    if not pts:
        return None
    xs, ys = zip(*pts)
    return min(xs), min(ys), max(xs), max(ys)


def _overlap(a, b) -> float:
    """Fraction of box a covered by box b."""
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    area = max(1.0, (a[2] - a[0]) * (a[3] - a[1]))
    return ix * iy / area


def add_looks(rgb: np.ndarray, people: list[Person]) -> None:
    """Fill in person.look for everyone in this frame (runs in the vision process)."""
    h, w = rgb.shape[:2]
    bodies = [_body_box(p, w, h) for p in people]
    for i, p in enumerate(people):
        top, bottom = _boxes(p, w, h)
        if top is None:
            continue
        look = {}
        for name, box in (("top", top), ("bottom", bottom)):
            if box is None:
                continue
            x0, y0, x1, y1 = (int(round(v)) for v in box)
            x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
            if x1 - x0 < 4 or y1 - y0 < 4:
                continue
            hist = _hist(rgb[y0:y1, x0:x1])
            if hist:
                look[name] = hist
        if not look:
            continue
        # Someone standing in front mixes their colours in: use it for matching, not learning.
        look["clean"] = not any(b is not None and j != i and _overlap(top, b) > 0.1
                                for j, b in enumerate(bodies))
        p.look = look


def _hellinger(a: np.ndarray, b: np.ndarray) -> float:
    return math.sqrt(max(0.0, 1.0 - float(np.sum(np.sqrt(a * b)))))


class Look:
    """A running average of how one person looks (clothes colours + head size)."""

    def __init__(self):
        self.top: np.ndarray | None = None
        self.bottom: np.ndarray | None = None
        self.heads: deque = deque(maxlen=90)
        self.n = 0  # clean frames learned

    @property
    def head(self) -> float | None:
        return float(np.median(self.heads)) if len(self.heads) >= 5 else None

    @property
    def known(self) -> bool:
        return self.top is not None or self.bottom is not None

    def learn(self, look: dict | None, head: float | None, rate: float | None = None,
              dirty_ok: bool = False) -> None:
        if head is not None:
            self.heads.append(head)
        if not look or not (look.get("clean") or dirty_ok):
            return
        r = rate if rate is not None else max(0.05, 1.0 / (self.n + 1))
        for part in ("top", "bottom"):
            v = look.get(part)
            if v is None:
                continue
            v = np.asarray(v, np.float32)
            old = getattr(self, part)
            setattr(self, part, v if old is None else (1 - r) * old + r * v)
        self.n += 1

    def distance(self, other: "Look") -> float | None:
        """0 = same clothes and build, ~1 = nothing alike. None if there's nothing to compare."""
        parts = [(w, _hellinger(getattr(self, k), getattr(other, k)))
                 for k, w in (("top", 0.65), ("bottom", 0.35))
                 if getattr(self, k) is not None and getattr(other, k) is not None]
        if not parts:
            return None
        d = sum(w * v for w, v in parts) / sum(w for w, _ in parts)
        ha, hb = self.head, other.head
        if ha and hb:  # a grown-up's head is ~30% smaller next to their shoulders than a kid's
            d = 0.75 * d + 0.25 * min(1.0, abs(math.log(ha / hb)) / 0.3)
        return d
