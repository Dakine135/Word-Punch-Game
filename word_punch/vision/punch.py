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
class HandTracker:
    hand: str
    shoulder: str
    cfg: dict
    history: deque = field(default_factory=lambda: deque(maxlen=30))
    last_punch: float = -1e9

    def update(self, person: Person, t: float) -> Punch | None:
        c = self.cfg
        wrist = person.get(self.hand, c["min_visibility"])
        if wrist is None:
            self.history.clear()
            return None
        scale = person.scale
        self.history.append((t, wrist.x, wrist.y, scale))
        if t - self.last_punch < c["cooldown_s"]:
            return None

        # Lowest wrist point (largest y) within the window, compared with now.
        window = [h for h in self.history if t - h[0] <= c["window_s"]]
        if len(window) < 2:
            return None
        t0, x0, y0, _ = max(window[:-1], key=lambda h: h[2])
        dt = t - t0
        if dt <= 0:
            return None
        rise = (y0 - wrist.y) / scale
        speed = rise / dt
        if rise < c["min_rise"] or speed < c["min_speed"]:
            return None
        if c["above_shoulder"]:
            shoulder = person.get(self.shoulder, 0.3)
            if shoulder and wrist.y > shoulder.y:
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
