"""Detect an upward punch from a stream of wrist positions.

A punch = the wrist rises at least `min_rise` shoulder-widths within `window_s`, at an
average speed of at least `min_speed` shoulder-widths/second, ending above the shoulder.
Measuring in shoulder-widths makes it work for big and small kids at any distance.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .pose_backend import Person


@dataclass
class Punch:
    t: float
    x: float  # normalized, where the fist is
    y: float
    hand: str  # "left_wrist" | "right_wrist"


@dataclass
class Metrics:
    """How close the latest motion came to a punch (for tuning screens)."""
    rise: float = 0.0       # shoulder-widths risen within the window
    speed: float = 0.0      # shoulder-widths per second
    above: bool = False     # wrist above its shoulder
    visible: bool = False
    t: float = 0.0


@dataclass
class HandTracker:
    hand: str
    shoulder: str
    cfg: dict
    history: deque = field(default_factory=lambda: deque(maxlen=30))
    last_punch: float = -1e9
    now: Metrics = field(default_factory=Metrics)   # this frame
    best: Metrics = field(default_factory=Metrics)  # strongest motion in the last second

    def update(self, person: Person, t: float) -> Punch | None:
        c = self.cfg
        wrist = person.get(self.hand, c["min_visibility"])
        if wrist is None:
            self.history.clear()
            self.now = Metrics(t=t)
            return None
        scale = person.scale
        self.history.append((t, wrist.x, wrist.y, scale))
        shoulder = person.get(self.shoulder, 0.3)
        above = bool(shoulder and wrist.y <= shoulder.y)

        # Lowest wrist point (largest y) within the window, compared with now.
        window = [h for h in self.history if t - h[0] <= c["window_s"]]
        rise = speed = 0.0
        if len(window) >= 2:
            t0, x0, y0, _ = max(window[:-1], key=lambda h: h[2])
            dt = t - t0
            if dt > 0:
                rise = max(0.0, (y0 - wrist.y) / scale)
                speed = rise / dt
        self.now = Metrics(rise, speed, above, True, t)
        if t - self.best.t > 1.0 or rise >= self.best.rise:
            self.best = self.now

        if t - self.last_punch < c["cooldown_s"]:
            return None
        if rise < c["min_rise"] or speed < c["min_speed"]:
            return None
        if c["above_shoulder"] and shoulder and not above:
            return None

        self.last_punch = t
        self.history.clear()
        return Punch(t, wrist.x, wrist.y, self.hand)


class PunchDetector:
    """Punch detection for one player (both hands)."""

    def __init__(self, cfg: dict):
        self.hands = [HandTracker("left_wrist", "left_shoulder", cfg),
                      HandTracker("right_wrist", "right_shoulder", cfg)]

    def update(self, person: Person | None, t: float) -> list[Punch]:
        if person is None:
            return []
        return [p for h in self.hands if (p := h.update(person, t))]
