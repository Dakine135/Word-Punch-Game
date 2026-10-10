"""Adaptive speed: quick, accurate reading speeds a lane up; misses ease it off."""
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

    def on_hit(self, read_time: float) -> None:
        self.recent_reads.append(read_time)
        if len(self.recent_reads) >= 3 and sum(self.recent_reads) / len(self.recent_reads) < self.cfg["fast_read_s"]:
            self._scale(self.cfg["ramp_up"])

    def on_miss(self) -> None:
        self.recent_reads.clear()
        self._scale(self.cfg["ease_down"])

    def _scale(self, f: float) -> None:
        c = self.cfg
        self.fall = min(c["max_fall"], max(c["min_fall"], self.fall * f))
        self.interval = min(c["max_interval"], max(c["min_interval"], self.interval / f))

    @property
    def level_pct(self) -> float:
        """0..1 for showing a speed meter."""
        c = self.cfg
        return (self.fall - c["min_fall"]) / (c["max_fall"] - c["min_fall"])
