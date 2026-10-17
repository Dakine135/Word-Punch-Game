"""Background music: a cheerful chiptune loop synthesized at startup (no audio files).

C - Am - F - G, 8 bars at 116 bpm: square-wave bass, triangle arpeggio, soft kick and hi-hat.
"""
from __future__ import annotations

import numpy as np
import pygame

RATE = 22050
MUSIC_CHANNEL = 0  # reserved in Sfx


def _note(midi: int) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


def _env(n: int, attack=0.005, release=0.12) -> np.ndarray:
    t = np.arange(n) / RATE
    return np.clip(t / attack, 0, 1) * np.exp(-t / release)


def _square(f, n, duty=0.5):
    t = np.arange(n) / RATE
    return np.where((t * f) % 1.0 < duty, 1.0, -1.0)


def _triangle(f, n):
    t = np.arange(n) / RATE
    return 2 * np.abs(2 * ((t * f) % 1.0) - 1) - 1


def build_loop() -> np.ndarray:
    bpm = 116
    beat = int(RATE * 60 / bpm)
    eighth = beat // 2
    chords = [(48, [60, 64, 67, 72]), (45, [57, 60, 64, 69]), (41, [53, 57, 60, 65]), (43, [55, 59, 62, 67])]
    bars = chords * 2
    total = beat * 4 * len(bars)
    out = np.zeros(total)
    rng = np.random.default_rng(7)
    for b, (root, arp) in enumerate(bars):
        start = b * beat * 4
        for i in range(8):  # bass on 8ths: root, root, fifth, root...
            n = eighth
            pitch = root + (7 if i in (2, 6) else 0)
            s = start + i * eighth
            out[s:s + n] += 0.16 * _square(_note(pitch), n, 0.25) * _env(n, release=0.09)
        pattern = [0, 1, 2, 3, 2, 1, 2, 3]
        for i, j in enumerate(pattern):  # arpeggio on 8ths
            n = eighth
            s = start + i * eighth
            out[s:s + n] += 0.13 * _triangle(_note(arp[j] + 12), n) * _env(n, release=0.15)
        for i in range(4):  # drums
            s = start + i * beat
            if i in (0, 2):
                n = beat // 2
                t = np.arange(n) / RATE
                out[s:s + n] += 0.35 * np.sin(2 * np.pi * (110 - 70 * t / t[-1]) * t) * _env(n, release=0.06)
            hs = s + eighth
            n = eighth // 3
            out[hs:hs + n] += 0.05 * rng.uniform(-1, 1, n) * _env(n, release=0.02)
    out /= max(1e-6, np.abs(out).max()) * 1.4
    return out


class Music:
    def __init__(self, volume: int = 35):
        self.ok = False
        self.volume = volume
        try:
            if not pygame.mixer.get_init():
                return
            wave = build_loop()
            freq, _, channels = pygame.mixer.get_init()
            if freq != RATE:
                idx = np.linspace(0, len(wave) - 1, int(len(wave) * freq / RATE)).astype(int)
                wave = wave[idx]
            pcm = (wave * 32767).astype(np.int16)
            if channels > 1:
                pcm = np.repeat(pcm[:, None], channels, axis=1)
            self.sound = pygame.sndarray.make_sound(np.ascontiguousarray(pcm))
            self.channel = pygame.mixer.Channel(MUSIC_CHANNEL)
            self.ok = True
        except (pygame.error, ValueError) as e:
            print(f"music disabled: {e}")

    def play(self) -> None:
        if self.ok and not self.channel.get_busy():
            self.channel.play(self.sound, loops=-1)
        self.set_volume(self.volume)

    def set_volume(self, percent: int, duck: bool = False) -> None:
        self.volume = percent
        if self.ok:
            self.channel.set_volume(percent / 100 * (0.35 if duck else 1.0))


# ---- real tracks (assets/music, downloaded by tools/fetch_models.py) ---------------------

from pathlib import Path  # noqa: E402

MUSIC_DIR = Path(__file__).resolve().parent.parent.parent / "assets" / "music"
PLAYLISTS = {  # mood -> files (a list alternates between rounds)
    "menu": ["menu_happy_clappy.wav"],
    "game": ["game_arplands.ogg", "game_happy_adventure.mp3"],
    "boss": ["boss_fight_bounce.mp3"],
    "calm": ["calm_concentration.mp3"],  # catch the word / sentence builder: listening & thinking
}
MUSIC_CHANNELS = (0, 2)  # reserved in Sfx (1 is the voice); two so tracks can crossfade


class MusicBox:
    """Looping background tracks by mood, crossfading when the mood changes.

    Falls back to the synthesized loop (Music) if the files aren't there."""

    FADE_MS = 900

    def __init__(self, volume: int = 35):
        self.volume = volume
        self.ok = False
        self.mood = None
        self.round = 0
        self.ducked = False
        self._sounds: dict[str, pygame.mixer.Sound] = {}
        self._active = 0
        self.fallback = None
        if not pygame.mixer.get_init():
            return
        if not all((MUSIC_DIR / f).exists() for files in PLAYLISTS.values() for f in files):
            self.fallback = Music(volume)
            return
        self.channels = [pygame.mixer.Channel(i) for i in MUSIC_CHANNELS]
        self.ok = True

    def _sound(self, name: str) -> pygame.mixer.Sound:
        if name not in self._sounds:
            self._sounds[name] = pygame.mixer.Sound(str(MUSIC_DIR / name))
        return self._sounds[name]

    def play(self, mood: str, new_round: bool = False) -> None:
        """Switch to a mood ("menu", "game", "boss", "calm"); no-op if it's already playing."""
        if self.fallback:
            self.fallback.play()
            return
        if not self.ok or (mood == self.mood and not new_round):
            return
        if new_round:
            self.round += 1
        files = PLAYLISTS.get(mood, PLAYLISTS["game"])
        name = files[self.round % len(files)]
        if mood == self.mood and len(files) == 1:
            return
        self.mood = mood
        old = self.channels[self._active]
        self._active = 1 - self._active
        new = self.channels[self._active]
        old.fadeout(self.FADE_MS)
        try:
            new.play(self._sound(name), loops=-1, fade_ms=self.FADE_MS)
        except pygame.error as e:
            print(f"music: {e}")
        self._apply_volume()

    def _apply_volume(self) -> None:
        if self.ok:
            self.channels[self._active].set_volume(self.volume / 100 * (0.35 if self.ducked else 1.0))

    def set_volume(self, percent: int, duck: bool = False) -> None:
        self.volume, self.ducked = percent, duck
        if self.fallback:
            self.fallback.set_volume(percent, duck)
        self._apply_volume()
