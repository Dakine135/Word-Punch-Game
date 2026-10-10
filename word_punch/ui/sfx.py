"""Sound effects synthesized with numpy at startup (no audio files to ship)."""
from __future__ import annotations

import numpy as np
import pygame

RATE = 22050


def _env(n: int, attack: float = 0.005, release: float = 0.3) -> np.ndarray:
    t = np.arange(n) / RATE
    a = np.clip(t / attack, 0, 1)
    r = np.exp(-t / release)
    return a * r


def _tone(freqs, dur, release=0.25, shape="sine"):
    n = int(RATE * dur)
    t = np.arange(n) / RATE
    out = np.zeros(n)
    for f in freqs:
        f = np.asarray(f(t) if callable(f) else f)
        phase = 2 * np.pi * np.cumsum(np.broadcast_to(f, t.shape)) / RATE
        out += np.sin(phase) if shape == "sine" else np.sign(np.sin(phase)) * 0.5
    return out / max(1, len(freqs)) * _env(n, release=release)


def _noise(dur, release=0.15, lowpass=0.0):
    n = int(RATE * dur)
    x = np.random.default_rng(0).uniform(-1, 1, n)
    if lowpass:
        # simple one-pole low-pass for a "thump"
        y = np.empty_like(x)
        acc = 0.0
        for i, v in enumerate(x):
            acc += lowpass * (v - acc)
            y[i] = acc
        x = y / max(1e-6, np.abs(y).max())
    return x * _env(n, release=release)


def _sound(wave: np.ndarray, volume: float = 0.5) -> pygame.mixer.Sound:
    data = np.clip(wave * volume, -1, 1)
    pcm = (data * 32767).astype(np.int16)
    freq, _, channels = pygame.mixer.get_init()
    if freq != RATE:
        idx = np.linspace(0, len(pcm) - 1, int(len(pcm) * freq / RATE)).astype(int)
        pcm = pcm[idx]
    if channels > 1:
        pcm = np.repeat(pcm[:, None], channels, axis=1)
    return pygame.sndarray.make_sound(np.ascontiguousarray(pcm))


class Sfx:
    def __init__(self):
        self.ok = False
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(RATE, -16, 2, 512)
            self.sounds = {
                # bright two-note chime: you read it!
                "unlock": _sound(np.concatenate([_tone([880, 1320], 0.09, 0.08),
                                                 _tone([1175, 1760], 0.25, 0.15)]), 0.35),
                "launch": _sound(_tone([lambda t: 300 + 1500 * t], 0.18, 0.1), 0.25),
                "break": _sound(_noise(0.45, 0.12, lowpass=0.25) * 0.8
                                + _tone([lambda t: 160 - 100 * t], 0.45, 0.2), 0.7),
                "clang": _sound(_tone([520, 1240, 1870], 0.35, 0.12), 0.3),
                "miss": _sound(_tone([lambda t: 330 - 200 * t], 0.5, 0.3, "square"), 0.25),
                "bounce": _sound(_tone([lambda t: 200 + 400 * t], 0.25, 0.15), 0.3),
                "levelup": _sound(np.concatenate([_tone([f], 0.12, 0.1) for f in (523, 659, 784, 1047)]
                                                 + [_tone([1047, 1568], 0.5, 0.3)]), 0.4),
                "gameover": _sound(np.concatenate([_tone([f], 0.22, 0.2, "square") for f in (392, 330, 262)]), 0.25),
            }
            self.ok = True
        except pygame.error as e:
            print(f"sound disabled: {e}")

    def set_volume(self, percent: int) -> None:
        if self.ok:
            for snd in self.sounds.values():
                snd.set_volume(max(0, min(100, percent)) / 100)

    def play(self, name: str) -> None:
        if self.ok and name in self.sounds:
            self.sounds[name].play()
