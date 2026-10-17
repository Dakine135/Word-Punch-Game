"""Keep a stable player slot for each person between frames.

Menus: slots follow whoever is in view (by the pose tracker's IDs, else by position), and a
slot survives short detection dropouts so a player doesn't lose their identity when they
duck or blur.

Rounds (`lock`): the players are whoever was in view when the round started. Their slots
are held for the whole round, even when a kid is lost for a while, and are won back by the
person who looks like that kid (clothes colours + head size, see appearance.py). Anyone
else - a grown-up walking through - is an "extra": drawn grey, can't play.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from itertools import permutations

from .appearance import Look, head_ratio
from .pose_backend import Person


@dataclass
class Slot:
    index: int
    person: Person | None = None
    x: float = 0.5
    last_seen: float = -1e9
    active: bool = False
    track_id: int | None = None
    look: Look = field(default_factory=Look)


@dataclass
class _Track:
    look: Look = field(default_factory=Look)
    seen: float = 0.0


@dataclass
class Tracker:
    max_players: int = 3
    max_jump: float = 0.25   # a person can't move further than this (normalized x) between frames
    keep_s: float = 1.0      # forget a slot after this long unseen (menus; rounds hold slots)
    slots: list[Slot] = field(default_factory=list)
    ignore_grownups: bool = False
    grownup_ratio: float = 0.53   # head width / shoulder width below this = grown-up
    look_match: float = 0.4       # clothes this different (0..1) aren't the same kid
    relax_s: float = 4.0          # ...unless their slot has been empty this long (lighting changes)
    locked: int = 0               # players this round (0 = menus: anyone can take a slot)
    extras: list[Person] = field(default_factory=list)  # in view but not playing (drawn grey)

    def __post_init__(self):
        self.slots = [Slot(i) for i in range(self.max_players)]
        self._tracks: dict[int, _Track] = {}

    # ---- rounds --------------------------------------------------------------------

    def lock(self, n: int) -> None:
        """Start a round with n players: keep the n people in view (kids before grown-ups,
        then in the order they arrived) as players 1..n and hold their slots all round."""
        n = max(1, min(n, self.max_players))
        active = [s for s in self.slots if s.active]
        keep = sorted(active, key=lambda s: (self._slot_is_grownup(s), s.index))[:n]
        keep.sort(key=lambda s: s.index)
        new = []
        for i in range(self.max_players):
            if i < len(keep):
                s = keep[i]
                s.index = i
                new.append(s)
            else:
                new.append(Slot(i))
        self.slots = new
        self.locked = n

    def unlock(self) -> None:
        self.locked = 0

    def is_grownup(self, p: Person) -> bool:
        if not self.ignore_grownups:
            return False
        head = self._head_of(p)
        return head is not None and head < self.grownup_ratio

    def head_of(self, p: Person) -> float | None:
        """Head width / shoulder width, steadied over the frames of this person's track."""
        return self._head_of(p)

    # ---- per frame -----------------------------------------------------------------

    def update(self, people: list[Person], t: float) -> list[Slot]:
        self._note_tracks(people, t)
        players = [p for p in people if not self.is_grownup(p)]
        if self.locked:
            self._update_locked(players, t)
        else:
            for s in self.slots:
                if s.active and t - s.last_seen > self.keep_s:
                    s.active, s.person, s.look = False, None, Look()
            players = sorted(players, key=lambda p: p.center_x)[: self.max_players]
            if players and all(p.track_id is not None for p in players):
                self._update_by_id(players, t)
            else:
                self._update_by_position(players, t)
        for s in self.slots:
            if s.person is not None and self._sure(s):
                s.look.learn(s.person.look, head_ratio(s.person))
        playing = {id(s.person) for s in self.slots if s.person is not None}
        self.extras = [p for p in people if id(p) not in playing]
        return self.slots

    def _update_by_position(self, people: list[Person], t: float) -> None:
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

    def _update_by_id(self, people: list[Person], t: float) -> None:
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
            if s.active:
                d = s.look.distance(self._look_of(p))
                if d is None or d > self.look_match:
                    s.look = Look()  # somebody else: learn them afresh
            s.person, s.x, s.last_seen, s.active, s.track_id = p, p.center_x, t, True, p.track_id
            seen.add(s.index)
        for s in self.slots:
            if s.index not in seen and s.active:
                s.person = None

    def _update_locked(self, people: list[Person], t: float) -> None:
        """Round in progress: give each player slot to the person most like that kid."""
        slots = self.slots[: self.locked]
        ids = {s.track_id: s.index for s in slots if s.track_id is not None}
        people = sorted(people, key=lambda p: p.center_x)[:6]

        def cost(s: Slot, p: Person) -> float | None:
            look = self._look_of(p)
            d = s.look.distance(look)
            recent = s.active and t - s.last_seen < 0.5
            same = s.track_id is not None and p.track_id == s.track_id
            if same and not self._looks_more_like_another(s, look, d):
                # Same tracker ID: the same kid. (IDs can swap when kids cross; then the
                # other kid's clothes match better and the colours win after a few frames.)
                return -0.2 + (0.3 if d is None else d)
            sure = d is not None and d < self.look_match * 0.5  # clearly that kid's clothes
            if recent and not sure and abs(s.x - p.center_x) > self.max_jump:
                return None
            c = 0.1 if p.track_id in ids and not same else 0.0  # that ID is another player's
            if d is None:
                if not s.look.known:
                    c += 0.3   # nobody to compare with yet: whoever turns up first
                elif recent:
                    c += 0.45  # can't see their clothes right now; go by position
                else:
                    return None
            else:
                limit = self.look_match if t - s.last_seen < self.relax_s else self.look_match * 1.3
                if d > limit:
                    return None
                c += d
            if recent and not sure:
                c += 0.5 * abs(s.x - p.center_x)
            return c

        options = [[cost(s, p) for p in people] for s in slots]
        best: dict[int, int] = {}
        best_cost = 0.0
        # Brute force: every way of giving each slot one person (or nobody). <= 3 x 6: tiny.
        def search(i: int, used: set, total: float, pick: dict):
            nonlocal best, best_cost
            if i == len(slots):
                if total < best_cost:
                    best_cost, best = total, dict(pick)
                return
            search(i + 1, used, total, pick)
            for j, c in enumerate(options[i]):
                if c is None or j in used:
                    continue
                pick[i] = j
                search(i + 1, used | {j}, total + c - 1.0, pick)  # -1: prefer more matches
                del pick[i]
        search(0, set(), 0.0, {})

        for i, s in enumerate(slots):
            if i in best:
                p = people[best[i]]
                s.person, s.x, s.last_seen, s.active, s.track_id = p, p.center_x, t, True, p.track_id
            else:
                s.person = None  # held for them: they're still playing
        for s in self.slots[self.locked:]:
            s.active, s.person = False, None

    # ---- what each tracked person looks like ----------------------------------------

    def _note_tracks(self, people: list[Person], t: float) -> None:
        for p in people:
            if p.track_id is None:
                continue
            tr = self._tracks.setdefault(p.track_id, _Track())
            tr.look.learn(p.look, head_ratio(p), rate=0.3, dirty_ok=not tr.look.known)
            tr.seen = t
        if len(self._tracks) > 40:
            for tid in [k for k, v in self._tracks.items() if t - v.seen > 10]:
                del self._tracks[tid]

    def _look_of(self, p: Person) -> Look:
        tr = self._tracks.get(p.track_id) if p.track_id is not None else None
        if tr is not None:
            return tr.look
        look = Look()
        look.learn(p.look, None, rate=1.0, dirty_ok=True)
        h = head_ratio(p)
        if h is not None:
            look.heads.extend([h] * 5)
        return look

    def _head_of(self, p: Person) -> float | None:
        return self._look_of(p).head

    def _looks_more_like_another(self, s: Slot, look: Look, d: float | None) -> bool:
        if d is None:
            return False
        for other in self.slots[: self.locked]:
            if other is not s:
                d2 = other.look.distance(look)
                if d2 is not None and d2 < d - 0.2:
                    return True
        return False

    def _sure(self, s: Slot) -> bool:
        """Learn a player's look only from frames where it's surely them (during a round a
        slot can be won on position alone, e.g. while their shirt is hidden)."""
        if not self.locked or s.look.n < 15:
            return True
        frame = Look()
        frame.learn(s.person.look, None, rate=1.0, dirty_ok=True)
        d = s.look.distance(frame)
        return d is not None and d < self.look_match * 0.6

    def _slot_is_grownup(self, s: Slot) -> bool:
        head = s.look.head
        return head is not None and head < self.grownup_ratio
