"""Keep a stable player slot for each person between frames.

Slots are matched by horizontal position (kids mostly stay side by side). A slot survives
short detection dropouts so a player doesn't lose their identity when they duck or blur.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import permutations

from .pose_backend import Person


@dataclass
class Slot:
    index: int
    person: Person | None = None
    x: float = 0.5
    last_seen: float = -1e9
    active: bool = False
    track_id: int | None = None


@dataclass
class Tracker:
    max_players: int = 3
    max_jump: float = 0.25   # a person can't move further than this (normalized x) between frames
    keep_s: float = 1.0      # forget a slot after this long unseen
    slots: list[Slot] = field(default_factory=list)

    def __post_init__(self):
        self.slots = [Slot(i) for i in range(self.max_players)]

    def update(self, people: list[Person], t: float) -> list[Slot]:
        for s in self.slots:
            if s.active and t - s.last_seen > self.keep_s:
                s.active, s.person = False, None

        people = sorted(people, key=lambda p: p.center_x)[: self.max_players]
        if people and all(p.track_id is not None for p in people):
            return self._update_by_id(people, t)
        active = [s for s in self.slots if s.active]
        assigned: dict[int, Person] = {}
        unmatched = list(people)

        if active and people:
            # Brute force the best assignment; with <= 3 players this is tiny.
            best, best_cost = {}, float("inf")
            n = min(len(active), len(people))
            for slot_perm in permutations(active, n):
                for person_perm in permutations(people, n):
                    pairs = [(s, p) for s, p in zip(slot_perm, person_perm)
                             if abs(s.x - p.center_x) <= self.max_jump]
                    cost = sum(abs(s.x - p.center_x) for s, p in pairs) - len(pairs)  # prefer more matches
                    if cost < best_cost:
                        best_cost, best = cost, {s.index: p for s, p in pairs}
            assigned = best
            matched_ids = {id(p) for p in assigned.values()}
            unmatched = [p for p in people if id(p) not in matched_ids]

        # New people take free slots, filled left to right.
        free = [s for s in self.slots if not s.active and s.index not in assigned]
        for p, s in zip(unmatched, free):
            assigned[s.index] = p

        for s in self.slots:
            if s.index in assigned:
                p = assigned[s.index]
                s.person, s.x, s.last_seen, s.active = p, p.center_x, t, True
            elif s.active:
                s.person = None  # still reserved, just not seen this frame
        return self.slots

    def _update_by_id(self, people: list[Person], t: float) -> list[Slot]:
        """The pose tracker already numbers each person: keep each number in its slot."""
        by_id = {s.track_id: s for s in self.slots if s.active and s.track_id is not None}
        seen = set()
        new = []
        for p in people:
            s = by_id.get(p.track_id)
            if s is None:
                new.append(p)
                continue
            s.person, s.x, s.last_seen = p, p.center_x, t
            seen.add(s.index)
        # New IDs: a slot freed by someone who left, else the closest free slot by position.
        for p in new:
            free = [s for s in self.slots if s.index not in seen and
                    (not s.active or t - s.last_seen > self.keep_s * 0.5 or s.person is None)]
            if not free:
                continue
            # prefer a slot whose last position was near (same kid re-detected with a new ID)
            s = min(free, key=lambda s: (s.active and t - s.last_seen < self.keep_s and abs(s.x - p.center_x) > self.max_jump,
                                         abs(s.x - p.center_x) if s.active else 1.0 + s.index))
            s.person, s.x, s.last_seen, s.active, s.track_id = p, p.center_x, t, True, p.track_id
            seen.add(s.index)
        for s in self.slots:
            if s.index not in seen and s.active:
                s.person = None
        return self.slots
