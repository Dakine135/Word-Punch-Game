"""The other games, built on the falling-words Game in core.py.

    catch    - the game SAYS a word; find it and hit it (no reading aloud needed)
    whack    - words pop up from holes in reach; read it, then whack it before it ducks
    boss     - a monster drops words; each word you break hurts it; then a big final word
    sentence - read and hit floating words in order to build a sentence

Tag team (player 1 reads, the others punch) is a mode in core.py that works with
classic, whack and boss.
"""
from __future__ import annotations

import math
import re
import tomllib
from pathlib import Path

from .core import Event, FallingWord, Game, Lane
from ..words import norm

KINDS = ("classic", "catch", "whack", "boss", "sentence")
TITLES = {"classic": "Word Punch", "catch": "Catch the Word", "whack": "Whack-a-Word",
          "boss": "Boss Battle", "sentence": "Sentence Builder"}


def allowed_modes(kind: str, players: int) -> list[str]:
    """Player arrangements that make sense for each game."""
    if players <= 1:
        return ["split"] if kind in ("classic", "whack") else ["coop"]
    return {
        "classic": ["split", "coop", "competitive", "tag"],
        "catch": ["coop", "competitive"],
        "whack": ["split", "coop", "competitive", "tag"],
        "boss": ["coop", "tag"],
        "sentence": ["coop", "tag"],
    }[kind]


def make_game(kind: str, **kw) -> Game:
    return {"classic": Game, "catch": CatchGame, "whack": WhackGame,
            "boss": BossGame, "sentence": SentenceGame}[kind](**kw)


# ======================================================================================
def reader_track(lane):
    """The most advanced reader's track in a lane (sentences and boss words use it)."""
    return max(lane.tracks, key=lambda t: t.level.index)


class CatchGame(Game):
    """Listen and find: every word can be hit, but only the one the game says counts."""
    kind = "catch"
    ANNOUNCE_EVERY = 7.0

    def __init__(self, **kw):
        super().__init__(**kw)
        self.target: FallingWord | None = None
        self.next_announce = 0.0

    def _spawn(self, lane: Lane, now: float):
        w = super()._spawn(lane, now)
        if w:
            w.unlocked, w.unlocked_at, w.neutral = True, now, True
            w.read_time = 2.0  # no reading in this game; a fixed middle bonus
        return w

    def update(self, dt: float, now: float) -> None:
        super().update(dt, now)
        if self.over:
            return
        if self.target is None or self.target not in self.words:
            self._choose_target(now)
        elif now >= self.next_announce:
            self._announce(now)

    def _choose_target(self, now: float) -> None:
        visible = [w for w in self.words if w.lane.alive and w.y > 0]
        self.target = self.rng.choice(visible) if visible else None
        if self.target:
            self.target.unlocked_at = now
            self._announce(now)

    def _announce(self, now: float) -> None:
        self.next_announce = now + self.ANNOUNCE_EVERY
        self.events.append(Event("target", self.target, text=self.target.text))

    def _break(self, w, player, now, style="punch", angle=0.0):
        if w is not self.target:
            self.players[player].combo = 0
            w.y = max(w.h / 2, w.y - self.h * 0.03)
            self.events.append(Event("wrong", w, player=player, x=w.x, y=w.y, text=w.text))
            return
        self.target = None
        super()._break(w, player, now, style, angle)

    def _word_hit_floor(self, w, now):
        if w is self.target:
            super()._word_hit_floor(w, now)
            if w not in self.words:
                self.target = None
        else:  # not the one asked for: just goes away, no penalty
            self.words.remove(w)


# ======================================================================================
class WhackGame(Game):
    """Words pop up from holes within reach and duck back down after a few seconds."""
    kind = "whack"
    POP_S = 0.25

    def __init__(self, **kw):
        super().__init__(**kw)
        for lane in self.lanes:
            width = lane.x1 - lane.x0
            cols = 2 if width < 700 else 3
            xs = [lane.x0 + width * (i + 0.5) / cols for i in range(cols)]
            ys = [self.h * 0.42, self.h * 0.72]
            lane.holes = [(x, y) for y in ys for x in xs]
            lane.spawn_timer = 0.5

    def stay_seconds(self, lane: Lane) -> float:
        d = self.diff_cfg
        return max(2.5, 6.0 * d["start_fall"] / max(lane.difficulty.fall, 1e-6))

    def _update_spawns(self, dt: float, now: float) -> None:
        for lane in self.lanes:
            if not lane.alive:
                continue
            lane.spawn_timer -= dt
            up = [w for w in self.words if w.lane is lane]
            if lane.spawn_timer > 0 or len(up) >= min(lane.difficulty.on_screen, len(lane.holes) - 1):
                continue
            used = {w.hole for w in up}
            free = [i for i in range(len(lane.holes)) if i not in used]
            track = next(lane.next_track)
            pick = self._pick(track)
            if not free or pick is None:
                lane.spawn_timer = 0.3
                continue
            hole = self.rng.choice(free)
            x, y = lane.holes[hole]
            bw, bh = self.measure(pick.text, pick.is_letter)
            w = FallingWord(next(self._ids), pick.text, pick.is_letter, pick.level_key, pick.points,
                            track, lane, x, y, bw, bh, now)
            w.hole, w.pop_at, w.down_at, w.scale = hole, now, now + self.stay_seconds(lane), 0.0
            if self.rules.get("powerups", True) and self.rng.random() < self.rules.get("powerup_chance", 0.12):
                from .core import POWERS
                w.power = self.rng.choice(POWERS)
            self.words.append(w)
            self._stat(w.track.owner, w.text, "seen")
            self.events.append(Event("spawn", w, lane=lane))
            lane.spawn_timer = lane.difficulty.interval * 0.8

    def _update_falling(self, dt: float, now: float) -> None:
        for w in list(self.words):
            frozen = now < w.lane.freeze_until
            if frozen:
                w.down_at += dt  # freeze keeps them up
            t_up = now - w.pop_at
            t_left = w.down_at - now
            w.scale = min(1.0, t_up / self.POP_S, max(0.0, t_left / self.POP_S))
            if t_left <= 0:
                self._duck(w, now)

    def _depth(self, w: FallingWord, now: float) -> float | None:
        """Whack words don't fall: use how much of their time up has gone by."""
        return max(0.0, min(1.0, (now - w.pop_at) / max(0.1, w.down_at - w.pop_at)))

    def _duck(self, w: FallingWord, now: float) -> None:
        """A word went back down without being whacked."""
        lane = w.lane
        self.words.remove(w)
        w.track.record_miss(w.text)
        self._stat(w.track.owner, w.text, "missed")
        for t in lane.tracks:
            t.lost_life()
        self._speed_changed(lane, lane.difficulty.on_miss(), now)
        for i in lane.players:
            self.players[i].combo = 0
        if lane.lives is None:
            self.events.append(Event("duck", w, x=w.x, y=w.y))
            return
        lane.lives -= 1
        self.events.append(Event("miss", w, lane=lane, x=w.x, y=w.y))
        if lane.lives <= 0:
            lane.alive = False
            self.words = [x for x in self.words if x.lane is not lane]
            self.events.append(Event("lane_out", lane=lane))
            self._check_over()

    def touch(self, player: int, x: float, y: float, now: float) -> FallingWord | None:
        """A hand at (x, y): whacks an unlocked word it's on."""
        if self.over:
            return None
        lane = self.lane_at(x)
        if self.mode == "split":
            player = lane.players[0]
        if player >= len(self.players):
            return None
        for w in self.words:
            if w.scale < 0.8 or (self.mode == "split" and w.lane is not lane):
                continue
            pad = 60 if now < w.lane.giant_until else 15
            if abs(x - w.x) <= w.w / 2 + pad and abs(y - w.y) <= w.h / 2 + pad:
                if self._tag_blocked(player, x, y):
                    return None
                if w.unlocked:
                    self._break(w, player, now, style="whack")
                    return w
                if now - w.last_clang > 0.8:
                    w.last_clang = now
                    self.events.append(Event("clang", w, player=player, x=w.x, y=w.y, style="whack"))
                return None
        return None


# ======================================================================================
class BossGame(Game):
    """Team vs a monster. Each word broken hurts it; at zero, a big final word appears."""
    kind = "boss"

    def __init__(self, **kw):
        super().__init__(**kw)
        if self.round_end != "time":
            self.round_end = "boss"
        punchers = max(1, len(self.players) - (1 if self.mode == "tag" else 0))
        self.boss_max = self.boss_hp = max(5, self.round_words * punchers)
        self.boss_x, self.boss_y = self.w / 2, self.h * 0.37
        self.boss_r = self.h * 0.13
        self.hurt_until = 0.0
        self.final: FallingWord | None = None
        self.defeated = False

    def _free_x(self, lane, bw, bh):
        span = self.w * 0.36
        lo, hi = self.boss_x - span + bw / 2, self.boss_x + span - bw / 2
        near_top = [w for w in self.words if w.y < self.boss_y + self.boss_r + bh * 1.5]
        for _ in range(12):
            x = self.rng.uniform(lo, hi)
            if all(abs(x - w.x) > (w.w + bw) / 2 + 10 for w in near_top):
                return x
        return None

    def _spawn(self, lane, now):
        if self.final is not None:
            return None
        w = super()._spawn(lane, now)
        if w:
            w.y = self.boss_y + self.boss_r * 0.5  # dropped from the boss's mouth
        return w

    def _update_falling(self, dt, now):
        if self.final is not None and self.final in self.words:
            self.final.y = self.boss_y + self.boss_r + self.final.h * 0.7 + math.sin(now * 2) * 6
        super()._update_falling(dt, now)

    def _word_hit_floor(self, w, now):
        if w is self.final:
            return
        super()._word_hit_floor(w, now)

    def _break(self, w, player, now, style="punch", angle=0.0):
        if w is self.final:
            w.hits -= 1
            self.hurt_until = now + 0.5
            if w.hits > 0:
                self.events.append(Event("boss_hit", w, player=player, x=w.x, y=w.y, text="final"))
                return
            super()._break(w, player, now, style, angle)
            self.defeated = True
            self.events.append(Event("boss_defeated", x=self.boss_x, y=self.boss_y))
            self._finish_lane(self.lanes[0])
            self._check_over()
            return
        super()._break(w, player, now, style, angle)
        self.boss_hp = max(0, self.boss_hp - 1)
        self.hurt_until = now + 0.4
        self.events.append(Event("boss_hit", w, player=player, x=self.boss_x, y=self.boss_y))
        if self.boss_hp == 0 and self.final is None and not self.over:
            self._spawn_final(now)

    def _spawn_final(self, now: float) -> None:
        track = reader_track(self.lanes[0])
        words = list(track.level.words)
        # the trickiest: most missed, then longest
        text = max(words, key=lambda t: (track.misses[t], len(t), self.rng.random()))
        bw, bh = self.measure(text, track.level.is_letters)
        w = FallingWord(next(self._ids), text, track.level.is_letters, track.level_key, track.level.points * 3,
                        track, self.lanes[0], self.boss_x, self.boss_y + self.boss_r + bh,
                        int(bw * 1.35), int(bh * 1.35), now)
        w.big, w.hits = True, 3
        self.final = w
        self.words = [x for x in self.words if x.unlocked]  # clear the rest out of the way
        self.words.append(w)
        self.events.append(Event("boss_final", w, text=text))

    def stars(self, player: int) -> int:
        from ..rewards import stars_for_round
        p = self.players[player]
        misses = sum(s["missed"] for s in self.word_stats.get(player, {}).values())
        return stars_for_round(max(p.broken, 5 if self.defeated else p.broken), self.defeated, misses, p.best_combo)


# ======================================================================================
SENTENCES = Path(__file__).resolve().parent.parent / "data" / "sentences.toml"


def load_sentences(bank) -> list[tuple[str, int]]:
    """[(sentence, level index needed)] - the level is the hardest school-list word in it."""
    level_of = {}
    for key in bank.order:
        lvl = bank.level(key)
        if lvl.is_letters:
            continue
        for w in lvl.words:
            level_of.setdefault(norm(w), lvl.index)
    out = []
    for s in tomllib.loads(SENTENCES.read_text(encoding="utf-8"))["sentences"]:
        toks = [norm(t) for t in re.findall(r"[A-Za-z']+", s)]
        need = max([level_of.get(t, 0) for t in toks] + [1])
        out.append((s, need))
    return out


class SentenceGame(Game):
    """Words of a sentence float around; read and hit them in order to build it."""
    kind = "sentence"

    def __init__(self, **kw):
        super().__init__(**kw)
        if self.round_end != "time":
            self.round_end = "sentence"
        self.goal = max(2, self.round_words // 5)
        self.done_count = 0
        self.sentence = ""
        self.tokens: list[str] = []
        self.placed = 0
        self.next_at = self.started_at + 1.0
        self.used: set[str] = set()
        # the reader's level decides which sentences fit (letters-only kids can't use this game)
        idx = max(t.level.index for t in self.lanes[0].tracks if not t.level.is_letters) \
            if any(not t.level.is_letters for t in self.lanes[0].tracks) else 1
        self.pool = [s for s, need in load_sentences(self.bank) if need <= idx] or \
            [s for s, _ in load_sentences(self.bank)][:5]

    @property
    def bar_y(self) -> float:
        return self.h * 0.26

    def _depth(self, w, now):
        return None  # words float in place: nothing to pace

    def update(self, dt: float, now: float) -> None:
        if self.over or self._time_up(now):
            return
        if not self.tokens and now >= self.next_at:
            self._new_sentence(now)
        for w in self.words:  # gentle floating
            w.x = w.ax + math.sin(now * 0.7 + w.phase) * 22
            w.y = w.ay + math.sin(now * 1.1 + w.phase * 1.3) * 12
        self._update_rockets(dt, now)

    def _new_sentence(self, now: float) -> None:
        fresh = [s for s in self.pool if s not in self.used] or self.pool
        self.sentence = self.rng.choice(fresh)
        self.used.add(self.sentence)
        self.tokens = re.findall(r"[A-Za-z']+", self.sentence)
        self.placed = 0
        lane = self.lanes[0]
        track = reader_track(lane)
        # spread the words over a grid of spots in reach, shuffled
        cols, rows = 3, 2
        spots = [((c + 0.5) / cols, 0.45 + r * 0.25) for r in range(rows) for c in range(cols)]
        self.rng.shuffle(spots)
        for i, tok in enumerate(self.tokens):
            if len(tok) == 1:
                continue  # "I", "a": too short to hear reliably - filled in for them
            sx, sy = spots[i % len(spots)]
            bw, bh = self.measure(tok, False)
            x = self.w * (0.1 + 0.8 * sx) + self.rng.uniform(-30, 30)
            y = self.h * sy + (i // len(spots)) * bh * 1.2
            w = FallingWord(next(self._ids), tok, False, track.level_key, track.level.points,
                            track, lane, x, y, bw, bh, now)
            w.slot, w.ax, w.ay, w.phase = i, x, y, self.rng.uniform(0, 6.28)
            self.words.append(w)
            self._stat(track.owner, tok, "seen")
        self._fill_short_words()
        self.events.append(Event("sentence_start", text=self.sentence))

    def _fill_short_words(self) -> None:
        """One-letter words fill themselves in, so the next blank is always a real word."""
        while self.placed < len(self.tokens) and len(self.tokens[self.placed]) == 1:
            self.placed += 1

    def _break(self, w, player, now, style="punch", angle=0.0):
        needed = self.tokens[self.placed] if self.placed < len(self.tokens) else None
        if needed is None or norm(w.text) != norm(needed):
            self.players[player].combo = 0
            self.events.append(Event("wrong", w, player=player, x=w.x, y=w.y, text="Not yet!"))
            return
        w.slot = self.placed
        super()._break(w, player, now, style, angle)
        self.placed += 1
        self._fill_short_words()
        self.events.append(Event("place", w, player=player, x=w.x, y=w.y, text=w.text))
        if self.placed == len(self.tokens):
            self.done_count += 1
            for p in self.players:
                p.score += 25 * len(self.tokens)
            self.events.append(Event("sentence_done", text=self.sentence))
            self.tokens = []
            self.words = []
            self.next_at = now + 3.0
            if self.done_count >= self.goal:
                self._finish_lane(self.lanes[0])
                self._check_over()

    def stars(self, player: int) -> int:
        from ..rewards import stars_for_round
        p = self.players[player]
        return stars_for_round(max(p.broken, 5 if self.lanes[0].done else 0), self.lanes[0].done, 0,
                               p.best_combo)
