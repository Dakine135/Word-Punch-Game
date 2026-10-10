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


def update_from_game(profile: Profile, track, player, finished: bool) -> None:
    """Copy progress back after (or during) a game."""
    if track is not None and track.owner is not None:
        profile.level = track.level_key
        profile.good = dict(track.good)
        profile.misses = dict(track.misses)
    profile.best_score = max(profile.best_score, player.score)
    profile.last_played = time.time()
    if finished:
        profile.sessions += 1
        profile.words_read += player.broken
