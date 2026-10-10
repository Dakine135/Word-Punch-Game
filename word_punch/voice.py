"""The game's speaking voice (Piper TTS), offline.

Clips are generated once, cached as WAV files in assets/voice/, and played through pygame.
Generation runs on a background thread so the game never stalls; a clip that isn't ready yet
is generated first and then played.

    voice = Voice(cfg["voice"])
    voice.prepare(["the", "said", ...])      # warm the cache in the background
    seconds = voice.say("Find", "the")        # queue clips back to back; returns total length
"""
from __future__ import annotations

import hashlib
import queue
import re
import threading
import wave
from pathlib import Path

import pygame

from .config import ROOT

CACHE = ROOT / "assets" / "voice"


def clip_name(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40] or "x"
    digest = hashlib.md5(text.encode("utf-8")).hexdigest()[:6]  # "B" and "b" differ
    return f"{slug}_{digest}.wav"


class Voice:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.enabled = cfg.get("enabled", True)
        self.model = Path(cfg["model"])
        CACHE.mkdir(parents=True, exist_ok=True)
        self._piper = None
        self._lock = threading.Lock()
        self._jobs: queue.Queue = queue.Queue()
        self._sounds: dict[str, pygame.mixer.Sound] = {}
        self._pending_say: list[tuple[str, ...]] = []
        self.channel = None
        self.error: str | None = None
        if self.enabled and not self.model.exists():
            self.error = f"voice model missing ({self.model.name}) - run tools/fetch_models.py"
            self.enabled = False
        if self.enabled:
            threading.Thread(target=self._worker, daemon=True).start()

    # ---- generation ------------------------------------------------------------------

    def _load(self):
        if self._piper is None:
            from piper import PiperVoice, SynthesisConfig
            self._piper = PiperVoice.load(str(self.model))
            self._syn = SynthesisConfig(length_scale=self.cfg.get("slowness", 1.15),
                                        volume=self.cfg.get("loudness", 1.0))
        return self._piper

    def path(self, text: str) -> Path:
        return CACHE / clip_name(text)

    def _generate(self, text: str) -> None:
        p = self.path(text)
        if p.exists():
            return
        try:
            with self._lock:
                voice = self._load()
                tmp = p.with_suffix(".tmp")
                with wave.open(str(tmp), "wb") as w:
                    voice.synthesize_wav(text, w, syn_config=self._syn)
                tmp.replace(p)
        except Exception as e:  # never let speech crash the game
            self.error = f"voice: {e}"

    def _worker(self) -> None:
        while True:
            text = self._jobs.get()
            self._generate(text)

    def prepare(self, texts) -> None:
        """Generate any missing clips in the background."""
        if not self.enabled:
            return
        for t in texts:
            if not self.path(t).exists():
                self._jobs.put(t)

    # ---- playback --------------------------------------------------------------------

    def _sound(self, text: str) -> pygame.mixer.Sound | None:
        if text in self._sounds:
            return self._sounds[text]
        p = self.path(text)
        if not p.exists():
            return None
        try:
            s = pygame.mixer.Sound(str(p))
            s.set_volume(self.cfg.get("volume", 100) / 100)
        except pygame.error:
            return None
        self._sounds[text] = s
        return s

    def ready(self, *texts: str) -> bool:
        return all(self.path(t).exists() for t in texts)

    def say(self, *texts: str) -> float:
        """Speak these clips back to back (replacing whatever is being said). Returns seconds."""
        if not self.enabled or not pygame.mixer.get_init():
            return 0.0
        if not self.ready(*texts):
            self.prepare(texts)
            self._pending_say = [texts]  # play when generated (see update)
            return 1.0
        self._pending_say = []
        if self.channel is None:
            self.channel = pygame.mixer.Channel(pygame.mixer.get_num_channels() - 1)
        sounds = [s for s in (self._sound(t) for t in texts) if s]
        if not sounds:
            return 0.0
        self.channel.stop()
        self.channel.play(sounds[0])
        for s in sounds[1:]:
            self.channel.queue(s)  # pygame queues only one; chain the rest in update()
        self._chain = sounds[2:]
        return sum(s.get_length() for s in sounds) + 0.1

    def update(self) -> None:
        """Call every frame: plays clips that just finished generating, continues chains."""
        if self._pending_say and self.ready(*self._pending_say[0]):
            self.say(*self._pending_say.pop())
        chain = getattr(self, "_chain", None)
        if chain and self.channel and self.channel.get_queue() is None:
            self.channel.queue(chain.pop(0))

    def speaking(self) -> bool:
        return bool(self.channel and self.channel.get_busy())

    def set_volume(self, percent: int) -> None:
        self.cfg["volume"] = percent
        for s in self._sounds.values():
            s.set_volume(percent / 100)


def spoken(text: str, is_letter: bool) -> str:
    """How to say a target: letters as 'the letter B' (a lone letter is too short to hear well)."""
    return f"the letter {text.upper()}" if is_letter else text
