"""Kid profiles: level, mastery progress and missed words, saved between sessions.

One JSON file per kid in profiles/ (git-ignored).
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import ROOT

PROFILE_DIR = ROOT / "profiles"


@dataclass
class Profile:
    name: str
    level: str = "k1"
    good: dict = field(default_factory=dict)     # fast reads at the current level (mastery)
    misses: dict = field(default_factory=dict)   # words missed, ever (spaced repetition)
    best_score: int = 0
    words_read: int = 0
    sessions: int = 0
    last_played: float = 0.0
    word_stats: dict = field(default_factory=dict)  # word -> {"seen","read","missed","time"} lifetime
    history: list = field(default_factory=list)     # one entry per finished round
    levels_reached: dict = field(default_factory=dict)  # level key -> first date reached
    stars: int = 0                                  # lifetime stars (unlock hats and colours)
    hat: str = "party"
    color: str = "team"

    @property
    def slug(self) -> str:
        return slugify(self.name)


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "player"


class ProfileStore:
    def __init__(self, directory: Path = PROFILE_DIR):
        self.dir = directory

    def all(self) -> list[Profile]:
        if not self.dir.exists():
            return []
        out = []
        for path in sorted(self.dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                known = {k: v for k, v in data.items() if k in Profile.__dataclass_fields__}
                out.append(Profile(**known))
            except (ValueError, TypeError) as e:
                print(f"skipping bad profile {path.name}: {e}")
        # most recently played first
        return sorted(out, key=lambda p: (-p.last_played, p.name.lower()))

    def save(self, profile: Profile) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.dir / f"{profile.slug}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(profile), indent=2), encoding="utf-8")
        tmp.replace(path)

    def delete(self, profile: Profile) -> None:
        (self.dir / f"{profile.slug}.json").unlink(missing_ok=True)

    def rename(self, profile: Profile, new_name: str) -> None:
        self.delete(profile)
        profile.name = new_name
        self.save(profile)

    def exists(self, name: str) -> bool:
        return (self.dir / f"{slugify(name)}.json").exists()


def apply_to_track(profile: Profile, track) -> None:
    """Load a kid's saved progress into a game Track at the start of a game."""
    if track.level_key == profile.level:
        track.good.update(profile.good)
    track.misses.update(profile.misses)


def update_from_game(profile: Profile, track, player, finished: bool, game=None, info: dict | None = None) -> None:
    """Copy progress back after (or during) a game. `finished` adds the round to the history."""
    if track is not None and track.owner is not None:
        if track.level_key != profile.level:
            profile.levels_reached.setdefault(track.level_key, time.strftime("%Y-%m-%d"))
        profile.level = track.level_key
        profile.good = dict(track.good)
        profile.misses = dict(track.misses)
    profile.levels_reached.setdefault(profile.level, time.strftime("%Y-%m-%d"))
    profile.best_score = max(profile.best_score, player.score)
    profile.last_played = time.time()
    if not finished:
        return
    profile.sessions += 1
    profile.words_read += player.broken
    stats = game.word_stats.get(player.index, {}) if game is not None else {}
    misses = 0
    for word, s in stats.items():
        life = profile.word_stats.setdefault(word, {"seen": 0, "read": 0, "missed": 0, "time": 0.0})
        for k in life:
            life[k] = round(life[k] + s.get(k, 0), 2)
        misses += s.get("missed", 0)
    entry = {"date": time.strftime("%Y-%m-%d %H:%M"), "score": player.score, "words": player.broken,
             "misses": misses, "best_combo": player.best_combo, "level": profile.level}
    entry.update(info or {})
    profile.stars += int(entry.get("stars", 0))
    profile.history.append(entry)
    del profile.history[:-200]
