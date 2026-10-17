"""Adaptive speed: the game settles where the kids smash words partway down the screen.

Every smashed word reports how far down the screen it was when it was read and when it was
hit (0 = top, 1 = floor). Higher than `target_depth` -> the lane speeds up and sends words
more often (and allows a few more on screen); lower -> it slows down. A word that gets away
slows it down more.

Speed is one number, `pace` (1.0 = start_fall). Fall speed and the gap between new words
both follow it, so they can't drift apart.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class Difficulty:
    cfg: dict
    pace: float = 1.0
    fall: float = 0.0       # fraction of screen height per second
    interval: float = 0.0   # seconds between spawns

    def __post_init__(self):
        self._apply()

    def on_hit(self, depth: float | None) -> int:
        """depth 0..1 (how far down the word was when read/smashed), or None for no change.

        Returns +1 if the lane sped up, -1 if it slowed down, 0 if (about) the same."""
        if depth is None:
            return 0
        err = self.cfg.get("target_depth", 0.4) - min(1.0, max(0.0, depth))
        return self._scale(math.exp(self.cfg.get("pace_gain", 0.8) * err))

    def on_miss(self) -> int:
        return self._scale(self.cfg["ease_down"])

    def _scale(self, f: float) -> int:
        c = self.cfg
        lo, hi = c["min_fall"] / c["start_fall"], c["max_fall"] / c["start_fall"]
        before = self.pace
        self.pace = min(hi, max(lo, self.pace * f))
        self._apply()
        ratio = self.pace / before
        return 1 if ratio > 1.03 else -1 if ratio < 0.97 else 0

    def _apply(self) -> None:
        c = self.cfg
        self.fall = c["start_fall"] * self.pace
        self.interval = min(c["max_interval"], max(c["min_interval"], c["start_interval"] / self.pace))

    @property
    def level_pct(self) -> float:
        """0..1 for showing a speed meter."""
        c = self.cfg
        return max(0.0, min(1.0, (self.fall - c["min_fall"]) / (c["max_fall"] - c["min_fall"])))

    @property
    def on_screen(self) -> int:
        """Words allowed on screen at once: more as the lane speeds up."""
        c = self.cfg
        return c["max_on_screen"] + round(c.get("extra_on_screen", 2) * self.level_pct)
