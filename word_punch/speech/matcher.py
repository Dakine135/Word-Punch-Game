"""Decide which on-screen target a heard token unlocks."""
from __future__ import annotations

from typing import Iterable, Protocol

from ..words import WordBank, norm

EXACT = 3        # the word itself or a homophone
ALIAS = 2        # a sound-alike the recognizer often hears for the word
LETTER_NAME = 2  # "bee" for B
LETTER_SOUND = 1 # "but" for B ("buh")


class Target(Protocol):
    text: str
    is_letter: bool
    unlocked: bool
    y: float  # larger = closer to the bottom = more urgent


def match_strength(token: str, text: str, is_letter: bool, bank: WordBank) -> int:
    token = norm(token)
    if is_letter:
        key = norm(text)
        if token in bank.letter_names.get(key, ()):
            return LETTER_NAME
        if token in bank.letter_sounds.get(key, ()):
            return LETTER_SOUND
        return 0
    group = bank.group(text)
    if token in group:
        return EXACT
    # A letter name that sounds like the word: the recognizer often hears "are" as "r".
    if len(token) == 1 and any(bank.group(n) & group for n in bank.letter_names.get(token, ())):
        return EXACT
    if token in bank.aliases_of(text):
        return ALIAS
    return 0


def best_match(token: str, targets: Iterable[Target], bank: WordBank) -> Target | None:
    """The locked target this token most likely refers to, or None.

    Ranking: strongest match, then the most urgent (lowest on screen).
    """
    best, best_key = None, None
    for t in targets:
        if t.unlocked:
            continue
        s = match_strength(token, t.text, t.is_letter, bank)
        if s == 0:
            continue
        key = (s, t.y)
        if best_key is None or key > best_key:
            best, best_key = t, key
    return best
