"""Word lists, homophones and letter aliases loaded from data/words.toml."""
from __future__ import annotations

import string
import tomllib
from dataclasses import dataclass
from pathlib import Path

DATA = Path(__file__).parent / "data" / "words.toml"
USER_ALIASES = Path(__file__).parent.parent / "aliases.toml"  # learned/added sound-alikes (git-ignored)

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
    def __init__(self, path: Path = DATA, user_aliases: Path | None = USER_ALIASES):
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

        # Word sound-alikes (built in + user's aliases.toml).
        self.aliases: dict[str, set[str]] = {}
        sources = [data.get("aliases", {})]
        if user_aliases and user_aliases.exists():
            sources.append(tomllib.loads(user_aliases.read_text(encoding="utf-8")).get("aliases", {}))
        list_words = {norm(x) for lvl in self.levels.values() if not lvl.is_letters for x in lvl.words}
        list_words |= {m for x in list(list_words) for m in self.group(x)}
        for src in sources:
            for word, alikes in src.items():
                for a in alikes:
                    a = norm(a)
                    # never let one list word stand in for another (that would skip reading)
                    if a and a not in list_words:
                        self.aliases.setdefault(norm(word), set()).add(a)

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

    def listen_tokens(self, text: str, is_letter: bool) -> set[str]:
        """Every token that would unlock this one target."""
        if is_letter:
            ch = norm(text)
            return set(self.letter_names.get(ch, ())) | set(self.letter_sounds.get(ch, ()))
        return set(self.group(text)) | self.letters_sounding_like(text) | self.aliases_of(text)

    def aliases_of(self, word: str) -> set[str]:
        out: set[str] = set()
        for member in self.group(word):
            out |= self.aliases.get(member, set())
        return out

    def add_user_alias(self, word: str, heard: str, path: Path | None = None) -> bool:
        """Remember that `heard` should count for `word` (saved in aliases.toml)."""
        path = path or USER_ALIASES
        word, heard = norm(word), norm(heard)
        list_words = {norm(x) for lvl in self.levels.values() if not lvl.is_letters for x in lvl.words}
        if not heard or heard in self.group(word) or heard in list_words:
            return False
        data = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        al = data.setdefault("aliases", {})
        al.setdefault(word, [])
        if heard not in al[word]:
            al[word].append(heard)
        lines = ["# Extra sound-alikes that count for a word (added from tools/speech_spike.py F5)", "[aliases]"]
        for k, v in sorted(al.items()):
            key = k if k.replace("_", "").isalnum() else '"' + k.replace('"', '') + '"'
            lines.append(f"{key} = [" + ", ".join('"' + x.replace('"', '') + '"' for x in v) + "]")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.aliases.setdefault(word, set()).add(heard)
        return True

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
                    tokens.update(self.aliases_of(w))
        return tokens

    def all_vocab(self) -> set[str]:
        return self.vocab(self.order)
