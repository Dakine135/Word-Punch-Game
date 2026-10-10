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
