"""Adaptive speed: the game settles at each kid's reading pace.

Quick reads speed a lane up, slow reads and misses ease it off."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass
class Difficulty:
    cfg: dict
    fall: float = 0.0       # fraction of screen height per second
    interval: float = 0.0   # seconds between spawns
    recent_reads: deque = field(default_factory=lambda: deque(maxlen=4))

    def __post_init__(self):
        self.fall = self.cfg["start_fall"]
        self.interval = self.cfg["start_interval"]

    def on_hit(self, read_time: float) -> int:
        """Returns +1 if this sped things up, -1 if it slowed them down, 0 otherwise."""
        self.recent_reads.append(read_time)
        if len(self.recent_reads) < 3:
            return 0
        avg = sum(self.recent_reads) / len(self.recent_reads)
        if avg < self.cfg["fast_read_s"]:
            return self._scale(self.cfg["ramp_up"])
        if avg > self.cfg.get("slow_read_s", 4.5):
            return -self._scale(1 / self.cfg["ramp_up"])
        return 0

    def on_miss(self) -> int:
        self.recent_reads.clear()
        return -self._scale(self.cfg["ease_down"])

    def _scale(self, f: float) -> int:
        """Returns 1 if the speed actually changed (not already at the limit)."""
        c = self.cfg
        before = self.fall
        self.fall = min(c["max_fall"], max(c["min_fall"], self.fall * f))
        self.interval = min(c["max_interval"], max(c["min_interval"], self.interval / f))
        return 1 if abs(self.fall - before) > 1e-9 else 0

    @property
    def level_pct(self) -> float:
        """0..1 for showing a speed meter."""
        c = self.cfg
        return (self.fall - c["min_fall"]) / (c["max_fall"] - c["min_fall"])
