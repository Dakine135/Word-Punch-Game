"""Game rules, independent of pygame, camera and mic (so it can be unit tested).

Coordinates are screen pixels; y grows downward. Inputs arrive as method calls:
    game.heard(word, now)        a word came from the speech recognizer (or the keyboard in --sim)
    game.voice(now)              an unrecognized sound (for forgiving letter mode)
    game.punch(player, x, now)   a player punched at screen x
    game.slice(player, x0, y0, x1, y1, now)   a fast hand swipe (slice mode)
    game.update(dt, now)         advance the simulation
and everything that happened is appended to game.events for sound/effects.
"""
from __future__ import annotations

import itertools
import math
import random
from dataclasses import dataclass, field
from typing import Callable

from ..speech.matcher import best_match
from ..words import WordBank
from . import scoring
from .difficulty import Difficulty
from .track import Track

MODES = ("split", "coop", "competitive")
ROUND_ENDS = ("lives", "words", "time", "level")

Measure = Callable[[str, bool], tuple[int, int]]  # (text, is_letter) -> (w, h) of the word block


@dataclass
class Player:
    index: int
    name: str
    score: int = 0
    combo: int = 0
    best_combo: int = 0
    broken: int = 0


@dataclass(eq=False)
class FallingWord:
    id: int
    text: str
    is_letter: bool
    level_key: str
    base_points: int
    track: Track
    lane: "Lane"
    x: float
    y: float
    w: int
    h: int
    spawned_at: float
    unlocked: bool = False
    unlocked_at: float = 0.0
    read_time: float = 0.0
    misses: int = 0  # times it hit the floor (gentle mode)
    last_clang: float = -1e9


@dataclass(eq=False)
class Rocket:
    player: int
    x: float
    y: float
    lane: "Lane"
    radius: float
    alive: bool = True
    clanged: set = field(default_factory=set)  # locked words already passed through


@dataclass(eq=False)
class Lane:
    index: int
    x0: float
    x1: float
    tracks: list[Track]
    difficulty: Difficulty
    players: list[int]                 # who plays here (split: one; shared: all)
    lives: int | None                  # None = gentle mode
    alive: bool = True                 # still playing (False once out of lives or finished)
    done: bool = False                 # finished the round's goal
    broken: int = 0                    # words broken in this lane this round
    spawn_timer: float = 0.0
    next_track: itertools.cycle = None  # round-robin over tracks (co-op with mixed levels)

    def __post_init__(self):
        self.next_track = itertools.cycle(self.tracks)


@dataclass
class Event:
    kind: str  # unlock|break|clang|miss|bounce|say|levelup|lane_out|lane_done|gameover|spawn|launch
    word: FallingWord | None = None
    player: int | None = None
    points: int = 0
    lane: Lane | None = None
    x: float = 0.0
    y: float = 0.0
    text: str = ""
    style: str = "punch"   # break: "punch" | "slice"
    angle: float = 0.0     # slice direction (radians)


class Game:
    def __init__(self, *, mode: str, player_names: list[str], player_levels: list[str],
                 bank: WordBank, cfg: dict, size: tuple[int, int], measure: Measure,
                 rng: random.Random | None = None, now: float = 0.0):
        assert mode in MODES, mode
        assert len(player_names) == len(player_levels) >= 1
        self.mode = mode
        self.bank = bank
        self.rules, self.diff_cfg, self.score_cfg = cfg["rules"], cfg["difficulty"], cfg["scoring"]
        self.w, self.h = size
        self.floor = self.h * 0.93
        self.measure = measure
        self.rng = rng or random.Random()
        self.players = [Player(i, n) for i, n in enumerate(player_names)]
        self.words: list[FallingWord] = []
        self.rockets: list[Rocket] = []
        self.events: list[Event] = []
        self.over = False
        self.result: str | None = None   # "complete" | "out" once over
        self.winner: int | None = None   # competitive
        self.started_at = now
        self.round_end = self.rules.get("round_end", "lives")
        self.round_words = int(self.rules.get("round_words", 15))
        self.round_seconds = float(self.rules.get("round_minutes", 3)) * 60
        self._ids = itertools.count()
        lives = None if self.rules["gentle"] else self.rules["lives"]
        n = len(self.players)

        if mode == "split":
            lane_w = self.w / n
            self.lanes = [
                Lane(i, i * lane_w, (i + 1) * lane_w,
                     [Track(bank, player_levels[i], self.rules, owner=i)],
                     Difficulty(self.diff_cfg), [i], lives)
                for i in range(n)]
        elif mode == "coop":
            # One sky; words alternate between each kid's level.
            tracks = [Track(bank, lvl, self.rules, owner=i) for i, lvl in enumerate(player_levels)]
            self.lanes = [Lane(0, 0, self.w, tracks, Difficulty(self.diff_cfg), list(range(n)), lives)]
        else:
            # Same words for everyone, at the easiest level among the players so it's fair.
            shared = min(player_levels, key=lambda k: bank.level(k).index)
            self.lanes = [Lane(0, 0, self.w, [Track(bank, shared, self.rules)],
                               Difficulty(self.diff_cfg), list(range(n)), lives)]
        for lane in self.lanes:
            lane.spawn_timer = 0.8  # first word comes quickly

    # ---- queries -------------------------------------------------------------------

    def levels_in_play(self) -> set[str]:
        return {k for lane in self.lanes for t in lane.tracks for k in t.levels_in_play()}

    def vocab(self) -> set[str]:
        return self.bank.vocab(self.levels_in_play())

    def screen_vocab(self) -> set[str]:
        """Only the tokens that would unlock a word on screen right now (much more accurate)."""
        tokens: set[str] = set()
        for w in self.words:
            if not w.unlocked and w.lane.alive:
                tokens |= self.bank.listen_tokens(w.text, w.is_letter)
        return tokens

    def word_goal(self, lane: Lane) -> int:
        """Words to finish this lane (co-op shares one bigger goal; race is per player)."""
        if self.mode == "coop":
            return self.round_words * len(self.players)
        return self.round_words

    def time_left(self, now: float) -> float | None:
        if self.round_end != "time":
            return None
        return max(0.0, self.round_seconds - (now - self.started_at))

    def lane_at(self, x: float) -> Lane:
        for lane in self.lanes:
            if lane.x0 <= x < lane.x1:
                return lane
        return self.lanes[-1] if x >= self.w else self.lanes[0]

    def track_for(self, player: int) -> Track | None:
        """The player's own level track (None in competitive, where the track is shared)."""
        for lane in self.lanes:
            for t in lane.tracks:
                if t.owner == player:
                    return t
        return None

    def lane_of_player(self, player: int) -> Lane:
        for lane in self.lanes:
            if player in lane.players:
                return lane
        return self.lanes[0]

    # ---- inputs --------------------------------------------------------------------

    def heard(self, token: str, now: float) -> FallingWord | None:
        if self.over:
            return None
        live = [w for w in self.words if w.lane.alive]
        target = best_match(token, live, self.bank)
        if target:
            target.unlocked = True
            target.unlocked_at = now
            target.read_time = now - target.spawned_at
            self.events.append(Event("unlock", target, x=target.x, y=target.y))
        return target

    def voice(self, now: float) -> None:
        """Forgiving letter mode: any sound unlocks a lane's only locked letter."""
        if self.over or not self.rules.get("letters_easy"):
            return
        for lane in self.lanes:
            locked = [w for w in self.words if w.lane is lane and not w.unlocked]
            if len(locked) == 1 and locked[0].is_letter:
                self.heard(self.bank.letter_names[locked[0].text.lower()][0], now)

    def punch(self, player: int, x: float, now: float, y: float | None = None) -> Rocket | None:
        if self.over:
            return None
        lane = self.lane_at(x)
        if self.mode == "split":
            player = lane.players[0]  # whoever owns the lane under the fist
        if not lane.alive or player >= len(self.players):
            return None
        start_y = self.floor if self.rules["rocket_from"] == "bottom" or y is None else y
        rocket = Rocket(player, x, start_y, lane, radius=self.h * 0.045)
        self.rockets.append(rocket)
        self.events.append(Event("launch", player=player, x=x, y=start_y, lane=lane))
        return rocket

    def slice(self, player: int, x0: float, y0: float, x1: float, y1: float, now: float) -> list:
        """A fast swipe from (x0, y0) to (x1, y1): cuts unlocked words it passes through."""
        if self.over:
            return []
        mx = (x0 + x1) / 2
        lane = self.lane_at(mx)
        if self.mode == "split":
            player = lane.players[0]
        if player >= len(self.players):
            return []
        angle = math.atan2(y1 - y0, x1 - x0)
        cut = []
        for w in list(self.words):
            if not w.lane.alive or (self.mode == "split" and w.lane is not lane):
                continue
            if not _segment_hits_rect(x0, y0, x1, y1, w.x, w.y, w.w / 2 + 12, w.h / 2 + 12):
                continue
            if w.unlocked:
                self._break(w, player, now, style="slice", angle=angle)
                cut.append(w)
            elif now - w.last_clang > 0.6:
                w.last_clang = now
                self.events.append(Event("clang", w, player=player, x=w.x, y=w.y, style="slice"))
        return cut

    # ---- simulation ----------------------------------------------------------------

    def update(self, dt: float, now: float) -> None:
        if self.over:
            return
        if self.round_end == "time" and now - self.started_at >= self.round_seconds:
            for lane in self.lanes:
                if lane.alive:
                    self._finish_lane(lane)
            self._check_over()
            return
        for lane in self.lanes:
            if not lane.alive:
                continue
            lane.spawn_timer -= dt
            on_screen = sum(1 for w in self.words if w.lane is lane)
            if lane.spawn_timer <= 0 and on_screen < self.diff_cfg["max_on_screen"]:
                if self._spawn(lane, now):
                    lane.spawn_timer = lane.difficulty.interval
                else:
                    lane.spawn_timer = 0.3  # nothing fit; try again shortly

        for w in list(self.words):
            speed = w.lane.difficulty.fall * self.h
            if w.unlocked:
                speed *= self.diff_cfg["unlocked_slowdown"]
            w.y += speed * dt
            if w.y + w.h / 2 >= self.floor:
                self._word_hit_floor(w, now)

        rocket_speed = self.h * 1.8
        for r in self.rockets:
            r.y -= rocket_speed * dt
            if r.y < -r.radius:
                r.alive = False
                continue
            # Lowest words first, since the rocket travels upward.
            for w in sorted(self.words, key=lambda w: -w.y):
                if not self._collides(r, w):
                    continue
                if w.unlocked:
                    r.alive = False
                    self._break(w, r.player, now)
                    break
                if w.id not in r.clanged:
                    # Locked: "read it first!" The rocket passes through so it can't
                    # block a shot at an unlocked word above.
                    r.clanged.add(w.id)
                    self.events.append(Event("clang", w, player=r.player, x=w.x, y=w.y + w.h / 2))
        self.rockets = [r for r in self.rockets if r.alive]

    def _collides(self, r: Rocket, w: FallingWord) -> bool:
        return (abs(r.x - w.x) <= w.w / 2 + r.radius * 0.6
                and abs(r.y - w.y) <= w.h / 2 + r.radius)

    def _spawn(self, lane: Lane, now: float) -> FallingWord | None:
        track = next(lane.next_track)
        taken = set().union(*(self.bank.sound_keys(w.text, w.is_letter) for w in self.words))
        for pick in track.candidates(self.rng):
            if self.bank.sound_keys(pick.text, pick.is_letter) & taken:
                continue
            bw, bh = self.measure(pick.text, pick.is_letter)
            x = self._free_x(lane, bw, bh)
            if x is None:
                return None
            word = FallingWord(next(self._ids), pick.text, pick.is_letter, pick.level_key,
                               pick.points, track, lane, x, -bh / 2, bw, bh, now)
            self.words.append(word)
            self.events.append(Event("spawn", word, lane=lane))
            return word
        return None

    def _free_x(self, lane: Lane, bw: float, bh: float) -> float | None:
        """A random x in the lane where the new word won't overlap words still near the top."""
        margin = bw / 2 + 10
        lo, hi = lane.x0 + margin, lane.x1 - margin
        if hi < lo:
            return (lane.x0 + lane.x1) / 2
        near_top = [w for w in self.words if w.lane is lane and w.y - w.h / 2 < bh * 1.5]
        for _ in range(12):
            x = self.rng.uniform(lo, hi)
            if all(abs(x - w.x) > (w.w + bw) / 2 + 10 for w in near_top):
                return x
        return None

    def _break(self, w: FallingWord, player: int, now: float, style: str = "punch", angle: float = 0.0) -> None:
        p = self.players[player]
        p.combo += 1
        p.best_combo = max(p.best_combo, p.combo)
        p.broken += 1
        pts = scoring.points(w.base_points, w.read_time, now - w.unlocked_at, p.combo - 1, self.score_cfg)
        p.score += pts
        self.words.remove(w)
        lane = w.lane
        lane.broken += 1
        lane.difficulty.on_hit(w.read_time)
        self.events.append(Event("break", w, player=player, points=pts, x=w.x, y=w.y,
                                 style=style, angle=angle))
        if w.track.record_hit(w.text, w.level_key, w.read_time):
            w.track.finished = True
            if w.track.level_up():
                self.events.append(Event("levelup", lane=lane, player=w.track.owner,
                                         text=w.track.level.name))

        # Round goals.
        if self.round_end == "words":
            if self.mode == "competitive":
                if p.broken >= self.round_words:
                    self.winner = player
                    self._finish_lane(lane)
            elif lane.broken >= self.word_goal(lane):
                self._finish_lane(lane)
        elif self.round_end == "level" and all(getattr(t, "finished", False) for t in lane.tracks):
            if self.mode == "competitive":
                self.winner = max(range(len(self.players)), key=lambda i: self.players[i].score)
            self._finish_lane(lane)
        self._check_over()

    def _finish_lane(self, lane: Lane) -> None:
        lane.alive, lane.done = False, True
        for w in [x for x in self.words if x.lane is lane]:
            self.words.remove(w)
            self.events.append(Event("vanish", w, x=w.x, y=w.y))
        self.events.append(Event("lane_done", lane=lane))

    def _check_over(self) -> None:
        if self.over or any(l.alive for l in self.lanes):
            return
        self.over = True
        self.result = "complete" if any(l.done for l in self.lanes) else "out"
        if self.mode == "competitive" and self.winner is None and self.result == "complete":
            self.winner = max(range(len(self.players)), key=lambda i: self.players[i].score)
        self.events.append(Event("gameover", text=self.result))

    def _word_hit_floor(self, w: FallingWord, now: float) -> None:
        lane = w.lane
        w.track.record_miss(w.text)
        lane.difficulty.on_miss()
        for i in lane.players:
            self.players[i].combo = 0
        if lane.lives is None:
            # Gentle: bounce back up for another try; read it aloud after the 2nd miss.
            w.misses += 1
            w.y = w.h / 2 + self.h * 0.05
            w.spawned_at = now
            w.unlocked = False
            self.events.append(Event("bounce", w, x=w.x, y=self.floor))
            if w.misses >= 2:
                self.events.append(Event("say", w, text=w.text))
            return
        self.words.remove(w)
        lane.lives -= 1
        self.events.append(Event("miss", w, lane=lane, x=w.x, y=self.floor))
        if lane.lives <= 0:
            lane.alive = False
            self.words = [x for x in self.words if x.lane is not lane]
            self.events.append(Event("lane_out", lane=lane))
            self._check_over()

    def drain_events(self) -> list[Event]:
        ev, self.events = self.events, []
        return ev


def _segment_hits_rect(x0, y0, x1, y1, cx, cy, hw, hh) -> bool:
    """Does the segment touch the axis-aligned box centered at (cx, cy) with half sizes hw, hh?"""
    # Liang-Barsky clipping against the box.
    dx, dy = x1 - x0, y1 - y0
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0 - (cx - hw)), (dx, (cx + hw) - x0), (-dy, y0 - (cy - hh)), (dy, (cy + hh) - y0)):
        if p == 0:
            if q < 0:
                return False
            continue
        r = q / p
        if p < 0:
            t0 = max(t0, r)
        else:
            t1 = min(t1, r)
        if t0 > t1:
            return False
    return True
