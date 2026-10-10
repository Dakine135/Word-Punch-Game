"""Steadier skeletons: a One-Euro filter per keypoint, plus blending between pose updates.

The One-Euro filter (Casiez et al. 2012) smooths hard when a point is still (no jitter) and
lightly when it moves fast (little lag). Pose arrives ~15-30 times a second; the game draws
60 times a second, so draw positions are blended from the previous to the latest filtered
pose over one pose interval. Only drawing uses this - punches/slices read the raw pose.
"""
from __future__ import annotations

import math

from .pose_backend import Keypoint, Person

PRESETS = {  # min_cutoff (Hz): lower = steadier when still; beta: higher = follows fast moves sooner
    "off": None,
    "low": (3.0, 0.8),
    "medium": (1.5, 0.6),
    "high": (0.8, 0.4),
}


class OneEuro:
    def __init__(self, min_cutoff: float, beta: float, d_cutoff: float = 1.0):
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self.x = self.dx = self.t = None

    @staticmethod
    def _alpha(cutoff: float, dt: float) -> float:
        tau = 1.0 / (2 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def __call__(self, x: float, t: float) -> float:
        if self.t is None or t <= self.t:
            self.x, self.dx, self.t = x, 0.0, t
            return x
        dt = t - self.t
        dx = (x - self.x) / dt
        a_d = self._alpha(self.d_cutoff, dt)
        self.dx = a_d * dx + (1 - a_d) * self.dx
        cutoff = self.min_cutoff + self.beta * abs(self.dx)
        a = self._alpha(cutoff, dt)
        self.x = a * x + (1 - a) * self.x
        self.t = t
        return self.x


class PoseSmoother:
    """Per player slot: filtered keypoints and the last two poses for blending."""

    def __init__(self, preset: str = "medium"):
        self.set_preset(preset)

    def set_preset(self, preset: str) -> None:
        self.params = PRESETS.get(preset, PRESETS["medium"])
        self.filters: dict = {}
        self.history: dict[int, list[tuple[float, Person]]] = {}

    def update(self, slot: int, person: Person, t: float) -> None:
        if self.params is None:
            out = person
        else:
            mc, beta = self.params
            kps = {}
            for name, kp in person.keypoints.items():
                fx = self.filters.setdefault((slot, name, "x"), OneEuro(mc, beta * 10))
                fy = self.filters.setdefault((slot, name, "y"), OneEuro(mc, beta * 10))
                kps[name] = Keypoint(fx(kp.x, t), fy(kp.y, t), kp.vis)
            out = Person(kps)
        hist = self.history.setdefault(slot, [])
        hist.append((t, out))
        del hist[:-2]

    def drop(self, slot: int) -> None:
        """Slot lost its person: start fresh next time (no sliding in from the old spot)."""
        self.history.pop(slot, None)
        for key in [k for k in self.filters if k[0] == slot]:
            del self.filters[key]

    def at(self, slot: int, now: float) -> Person | None:
        """The pose to draw right now: blended from the previous to the latest update."""
        hist = self.history.get(slot)
        if not hist:
            return None
        if len(hist) == 1 or self.params is None:
            return hist[-1][1]
        (t0, p0), (t1, p1) = hist
        span = max(t1 - t0, 1e-3)
        a = min(1.0, max(0.0, (now - t1) / span))
        kps = {}
        for name, k1 in p1.keypoints.items():
            k0 = p0.keypoints.get(name, k1)
            kps[name] = Keypoint(k0.x + (k1.x - k0.x) * a, k0.y + (k1.y - k0.y) * a, k1.vis)
        return Person(kps)
