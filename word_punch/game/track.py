"""A level track: which words a kid is working on, and when they've mastered them."""
from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass, field

from ..words import WordBank, norm


@dataclass(frozen=True)
class WordPick:
    text: str
    is_letter: bool
    level_key: str
    points: int


@dataclass
class Track:
    bank: WordBank
    level_key: str
    rules: dict
    owner: int | None = None  # player index, or None for a shared track
    finished: bool = False   # mastered a level during this round ("level" round goal)
    good: Counter = field(default_factory=Counter)    # fast reads at the current level
    misses: Counter = field(default_factory=Counter)  # misses ever (weights spaced repetition)

    @property
    def level(self):
        return self.bank.level(self.level_key)

    def _key(self, text: str) -> str:
        # Letters count case-insensitively for mastery ("B" and "b" are the same letter).
        return norm(text) if self.level.is_letters else text

    def review_levels(self) -> list[str]:
        """The few word levels just before this one (letters never come back as review).

        Only recent levels: a 9th grader shouldn't get kindergarten words as review."""
        idx = self.level.index
        earlier = [k for k in self.bank.order[:idx] if not self.bank.level(k).is_letters]
        return earlier[-self.rules.get("review_depth", 3):] if earlier else []

    def levels_in_play(self) -> list[str]:
        return [self.level_key] + self.review_levels()

    def candidates(self, rng: random.Random) -> list[WordPick]:
        """Words in a weighted-shuffled order; caller takes the first that fits on screen."""
        level_key = self.level_key
        review = self.review_levels()
        if review and rng.random() < self.rules["review_chance"]:
            level_key = rng.choice(review)
        lvl = self.bank.level(level_key)
        words = list(lvl.words)
        if level_key != self.level_key:
            # Review never shows one-letter words ("a", "I"): single letters belong to the
            # Letters level (and to K-Q1 itself, where "a" and "I" are taught).
            words = [w for w in words if len(w) > 1] or words
        # Weighted shuffle: missed words are more likely to come first.
        weights = [1.0 + 2.0 * self.misses[w] for w in words]
        order = sorted(range(len(words)), key=lambda i: rng.random() ** (1.0 / weights[i]), reverse=True)
        return [WordPick(words[i], lvl.is_letters, lvl.key, lvl.points) for i in order]

    def record_hit(self, text: str, level_key: str, read_time: float) -> bool:
        """Returns True if this hit completed the level (caller levels up)."""
        if level_key != self.level_key:
            return False  # a review word
        if read_time <= self.rules["mastery_read_s"]:
            self.good[self._key(text)] += 1
        return self.mastered()

    def record_miss(self, text: str) -> None:
        self.misses[text] += 1

    def mastered(self) -> bool:
        need = self.rules["mastery_hits"]
        keys = {self._key(w) for w in self.level.words}
        return all(self.good[k] >= need for k in keys)

    def progress(self) -> float:
        need = self.rules["mastery_hits"]
        keys = {self._key(w) for w in self.level.words}
        return sum(min(self.good[k], need) for k in keys) / (need * len(keys))

    def level_up(self) -> bool:
        nxt = self.bank.next_level(self.level_key)
        if nxt is None:
            return False
        self.level_key = nxt
        self.good.clear()
        return True
