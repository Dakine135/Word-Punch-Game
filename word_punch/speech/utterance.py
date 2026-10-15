"""GPU speech recognition for kids: detect each utterance, transcribe it with a modern model
(Whisper or Parakeet), and report the words. Runs inside the speech process.

Vosk listened for a fixed list of words, but its adult-trained models filed most of the kids'
speech as "unknown". Whisper/Parakeet transcribe whatever was said (much better with
children); the game then matches the words against what's on screen.

Flow per utterance:
  noise-floor VAD finds speech -> interim transcripts every ~0.4 s while talking (fast unlock)
  -> a final transcript when they stop -> "heard" events for each new word.
"""
from __future__ import annotations

import os
import re
import time
from collections import deque

import numpy as np

NUMBERS = {"1": "one", "2": "two", "3": "three", "4": "four", "5": "five", "6": "six",
           "7": "seven", "8": "eight", "9": "nine", "10": "ten"}
# Things Whisper says on silence/noise; never count them as reading.
HALLUCINATIONS = {"thank you", "thanks for watching", "thank you for watching", "you", "bye", "so",
                  "subtitles by the amara.org community", "i'm sorry"}


def words_of(text: str) -> list[str]:
    out = []
    for t in re.findall(r"[A-Za-z']+|\d+", text):
        out.append(NUMBERS.get(t, t.lower()))
    return out


def _cuda_dlls() -> None:
    """Make the CUDA/cuDNN DLLs that ship with PyTorch visible to CTranslate2/onnxruntime."""
    try:
        import torch  # noqa: F401  (loads its CUDA libraries)
        lib = os.path.join(os.path.dirname(torch.__file__), "lib")
        if os.path.isdir(lib) and hasattr(os, "add_dll_directory"):
            os.add_dll_directory(lib)
    except Exception:
        pass


class WhisperEngine:
    def __init__(self, cfg: dict):
        _cuda_dlls()
        from faster_whisper import WhisperModel
        self.model = WhisperModel(cfg.get("whisper_model", "large-v3-turbo"), device="cuda",
                                  compute_type="float16")
        self.name = f"whisper {cfg.get('whisper_model', 'large-v3-turbo')}"

    def transcribe(self, audio: np.ndarray, hint: list[str], quick: bool) -> str:
        prompt = (", ".join(hint[:30]) + ".") if hint else None
        segs, _ = self.model.transcribe(audio, language="en", beam_size=1 if quick else 5,
                                        initial_prompt=prompt, without_timestamps=True,
                                        condition_on_previous_text=False, vad_filter=False)
        keep = [s.text for s in segs if s.no_speech_prob < 0.6 and s.avg_logprob > -1.2]
        return " ".join(keep).strip()


class ParakeetEngine:
    def __init__(self, cfg: dict):
        _cuda_dlls()
        import onnx_asr
        self.model = onnx_asr.load_model(cfg.get("parakeet_model", "nemo-parakeet-tdt-0.6b-v2"),
                                         providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
        self.name = "parakeet"

    def transcribe(self, audio: np.ndarray, hint: list[str], quick: bool) -> str:
        return self.model.recognize(audio, sample_rate=16000).strip()


class ChoiceEngine:
    """Whisper answers "which of the words on screen was that?" (see whisper_choice.py)."""

    def __init__(self, cfg: dict):
        _cuda_dlls()
        from .whisper_choice import WhisperChooser
        self.chooser = WhisperChooser(cfg.get("choice_model", "openai/whisper-large-v3-turbo"))
        self.floor = cfg.get("choice_floor", -2.0)
        self.name = f"choice {self.chooser.name}"

    def choose(self, audio: np.ndarray, vocab: list[str]):
        return self.chooser.choose(audio, vocab, self.floor, with_free=True)


def make_engine(cfg: dict):
    engine = cfg.get("engine")
    if engine == "choice":
        return ChoiceEngine(cfg)
    return ParakeetEngine(cfg) if engine == "parakeet" else WhisperEngine(cfg)


class UtteranceListener:
    """Feed 50 ms int16 blocks; get (kind, payload) events back."""

    def __init__(self, engine, cfg: dict, rate: int = 16000):
        self.engine, self.cfg, self.rate = engine, cfg, rate
        self.noise = 0.25            # noise floor (0..1 level scale), adapts to the room
        self.pre = deque(maxlen=6)   # ~0.3 s before speech starts
        self.buf: list[np.ndarray] = []
        self.speaking = False
        self.loud_blocks = 0
        self.quiet_s = 0.0
        self.sent: set[str] = set()
        self.last_interim = 0.0
        self.loudest = 0.0
        self.hint: list[str] = []
        self.vocab: list[str] = []   # tokens to choose from (choice engine)
        self.last_audio = None

    def _start_margin(self) -> float:
        return self.cfg.get("vad_margin", 0.12)

    def feed(self, block: bytes, level: float, now: float) -> list[tuple]:
        events = []
        x = np.frombuffer(block, np.int16).astype(np.float32) / 32768
        if not self.speaking:
            self.pre.append(x)
            if level > self.noise + self._start_margin() and level > self.cfg.get("vad_min", 0.3):
                self.loud_blocks += 1
            else:
                self.loud_blocks = 0
                self.noise += (level - self.noise) * 0.02   # slow drift toward the room level
            if self.loud_blocks >= 2:
                self.speaking, self.buf, self.sent, self.quiet_s = True, list(self.pre), set(), 0.0
                self.last_interim, self.loudest = now, level
            return events

        self.buf.append(x)
        self.loudest = max(self.loudest, level)
        if level < self.noise + self._start_margin() * 0.5:
            self.quiet_s += len(x) / self.rate
        else:
            self.quiet_s = 0.0
        dur = sum(len(b) for b in self.buf) / self.rate
        ended = self.quiet_s >= self.cfg.get("end_silence", 0.4) or dur >= self.cfg.get("max_utterance", 5.0)
        if hasattr(self.engine, "choose"):
            return self._feed_choice(ended, now)
        if not ended and now - self.last_interim >= self.cfg.get("interim_every", 0.4) and dur >= 0.35:
            self.last_interim = now
            events += self._emit(self.engine.transcribe(np.concatenate(self.buf), self.hint, quick=True),
                                 now, final=False)
        if ended:
            self.last_audio = np.concatenate(self.buf)
            text = self.engine.transcribe(self.last_audio, self.hint, quick=False)
            events += self._emit(text, now, final=True)
            if not words_of(text) and not self.sent and self.loudest >= self.cfg.get("voice_level", 0.45):
                events.append(("voice", now))
            events.append(("transcript", (text, True, [(w, 1.0) for w in words_of(text)])))
            self.speaking, self.loud_blocks, self.buf = False, 0, []
        return events

    def _feed_choice(self, ended: bool, now: float) -> list[tuple]:
        if not ended:
            return []
        self.last_audio = np.concatenate(self.buf)
        self.speaking, self.loud_blocks, self.buf = False, 0, []
        word, info = self.engine.choose(self.last_audio, self.vocab)
        events = []
        if word:
            events.append(("heard", (word, now, True)))
        elif self.loudest >= self.cfg.get("voice_level", 0.45):
            events.append(("voice", now))
        shown = f"{info.get('free', '').strip()}  ->  {word or '(none)'}"
        events.append(("transcript", (shown, True, [(word, 1.0)] if word else [])))
        return events

    def _emit(self, text: str, now: float, final: bool) -> list[tuple]:
        if text.strip().lower().strip(".!?") in HALLUCINATIONS and not final:
            return []
        out = []
        if not final:
            out.append(("transcript", (text, False, [])))
        for w in words_of(text):
            if w not in self.sent:
                self.sent.add(w)
                out.append(("heard", (w, now, final)))
        return out

    def reset(self) -> None:
        self.speaking, self.loud_blocks, self.buf, self.sent = False, 0, [], set()
