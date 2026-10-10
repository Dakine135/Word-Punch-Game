"""Word lists, homophones and letter aliases loaded from data/words.toml."""
from __future__ import annotations

import string
import tomllib
from dataclasses import dataclass
from pathlib import Path

DATA = Path(__file__).parent / "data" / "words.toml"

LETTER_LEVEL = "letters"


def norm(text: str) -> str:
    """Normalize a word for comparison: lowercase, straight apostrophes."""
    return text.strip().lower().replace("’", "'")


@dataclass(frozen=True)
class Level:
    key: str
    name: str
    points: int
    words: tuple[str, ...]  # display text, e.g. "I", "don't", "B"
    index: int  # position in the progression

    @property
    def is_letters(self) -> bool:
        return self.key == LETTER_LEVEL


class WordBank:
    def __init__(self, path: Path = DATA):
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        self.order: list[str] = data["order"]
        self.levels: dict[str, Level] = {}
        for i, key in enumerate(self.order):
            raw = data["levels"][key]
            words = raw["words"]
            if key == LETTER_LEVEL:
                words = list(string.ascii_uppercase) + list(string.ascii_lowercase)
            self.levels[key] = Level(key, raw["name"], raw["points"], tuple(words), i)

        # Homophones: each word maps to the frozenset of its group (itself if none).
        self._groups: dict[str, frozenset[str]] = {}
        for group in data["homophones"]:
            g = frozenset(norm(w) for w in group)
            for w in g:
                self._groups[w] = g

        self.letter_names: dict[str, tuple[str, ...]] = {
            k: tuple(norm(w) for w in v) for k, v in data["letters"]["name"].items()}
        self.letter_sounds: dict[str, tuple[str, ...]] = {
            k: tuple(norm(w) for w in v) for k, v in data["letters"]["sound"].items()}

    def level(self, key: str) -> Level:
        return self.levels[key]

    def next_level(self, key: str) -> str | None:
        i = self.order.index(key)
        return self.order[i + 1] if i + 1 < len(self.order) else None

    def group(self, word: str) -> frozenset[str]:
        w = norm(word)
        return self._groups.get(w, frozenset([w]))

    def letters_sounding_like(self, word: str) -> set[str]:
        """Letters whose spoken name sounds like this word ("are" -> {"r"}, "why" -> {"y"})."""
        group = self.group(word)
        return {ch for ch, names in self.letter_names.items()
                if any(self.group(n) & group for n in names)}

    def sound_keys(self, text: str, is_letter: bool) -> frozenset[str]:
        """Things sharing any key sound alike and must not be on screen together.

        Letters and words can collide too: the letter R and the word "are".
        """
        if is_letter:
            ch = norm(text)
            keys = {"letter:" + ch}  # "B" and "b" share a key
            keys.update("word:" + min(self.group(n)) for n in self.letter_names.get(ch, ()))
            return frozenset(keys)
        keys = {"word:" + min(self.group(text))}
        keys.update("letter:" + ch for ch in self.letters_sounding_like(text))
        return frozenset(keys)

    def vocab(self, level_keys) -> set[str]:
        """Every token the recognizer should listen for when these levels are in play."""
        tokens: set[str] = set()
        for key in level_keys:
            lvl = self.levels[key]
            if lvl.is_letters:
                for names in self.letter_names.values():
                    tokens.update(names)
                for sounds in self.letter_sounds.values():
                    tokens.update(sounds)
            else:
                for w in lvl.words:
                    tokens.update(self.group(w))
        return tokens

    def all_vocab(self) -> set[str]:
        return self.vocab(self.order)
