"""Offline speech recognition in its own process (mic -> Vosk -> heard words).

The game talks to it through SpeechService:
    svc = SpeechService(cfg["speech"]); svc.start(vocab)
    for event in svc.poll(): ...      # Heard(word) or Voice()
    svc.mute(1.2)                      # ignore the mic while the game itself is talking
    svc.level, svc.device_name, svc.error   # mic meter (0..1) and status, updated by poll()
"""
from __future__ import annotations

import json
import math
import multiprocessing as mp
import queue
import time
from dataclasses import dataclass


@dataclass
class Heard:
    word: str
    t: float
    final: bool


@dataclass
class Voice:
    """Someone said something (possibly not a known word)."""
    t: float


@dataclass
class Transcript:
    """Unrestricted transcription (any English words), for testing/debugging only.

    final=False: a live partial guess that may still change.
    words: [(word, confidence 0..1)] on final results.
    """
    text: str
    final: bool
    words: list


def list_input_devices() -> list[tuple[int, str]]:
    """Input devices on the default host API (MME on Windows), so each mic is listed once."""
    import sounddevice as sd
    api = sd.default.hostapi
    return [(i, d["name"].strip()) for i, d in enumerate(sd.query_devices())
            if d["max_input_channels"] > 0 and d["hostapi"] == api]


def find_input_device(name_part: str):
    """Device index whose name contains name_part (default host API first), or None = default."""
    import sounddevice as sd
    if not name_part:
        return None
    for i, name in list_input_devices():
        if name_part.lower() in name.lower():
            return i
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0 and name_part.lower() in d["name"].lower():
            return i
    raise ValueError(f"no input device matching {name_part!r}")


def level_of(pcm: bytes) -> float:
    """Loudness of an int16 block as 0..1 (-60 dBFS .. 0 dBFS)."""
    import numpy as np
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    if x.size == 0:
        return 0.0
    rms = float(np.sqrt(np.mean(x * x)))
    db = 20 * math.log10(max(rms, 1e-6))
    return min(1.0, max(0.0, (db + 60) / 60))


def _speech_main(cfg: dict, vocab: list[str], cmd_q: mp.Queue, out_q: mp.Queue, stop) -> None:
    import sounddevice as sd
    import vosk

    vosk.SetLogLevel(-1)
    model = vosk.Model(cfg["model"])
    rate = cfg["sample_rate"]

    def make_recognizer(words):
        r = vosk.KaldiRecognizer(model, rate, json.dumps(sorted(words) + ["[unk]"]))
        r.SetWords(True)
        return r

    rec = make_recognizer(vocab)
    # Optional second recognizer with the full vocabulary, so a tester can see what was
    # actually heard when the game's restricted recognizer gets it wrong. Costs extra CPU.
    free = None
    if cfg.get("transcript"):
        free = vosk.KaldiRecognizer(model, rate)
        free.SetWords(True)
    last_partial = ""
    pending_vocab = None        # applied between utterances so a word in progress isn't lost
    pending_since = 0.0
    in_utterance = False
    loudest = 0.0               # loudest block in the current utterance
    current_vocab = list(vocab)
    from collections import deque
    pre_roll: deque = deque(maxlen=8)   # ~0.4 s before speech starts
    utter: list[bytes] = []             # audio of the current utterance (when saving misses)
    audio_q: queue.Queue = queue.Queue()
    muted_until = 0.0
    sent: list[str] = []  # words of the current utterance already sent, by position

    def on_audio(indata, frames, time_info, status):
        audio_q.put(bytes(indata))

    def send(words, now, final):
        # Send each word that is new or changed at its position in the utterance.
        # Grammar-mode partials are fairly stable and kids say single words, so
        # reacting to partials feels much snappier than waiting for silence.
        for i, w in enumerate(words):
            if i < len(sent) and sent[i] == w:
                continue
            if w == "[unk]":
                out_q.put(("voice", now))
            else:
                out_q.put(("heard", (w, now, final)))
            if i < len(sent):
                sent[i] = w
            else:
                sent.append(w)

    try:
        device = find_input_device(cfg["device"])
        stream = sd.RawInputStream(samplerate=rate, blocksize=rate // 20, dtype="int16",
                                   channels=1, device=device, callback=on_audio)
        info = sd.query_devices(device if device is not None else sd.default.device[0])
    except Exception as e:  # bad device name, mic unplugged, unsupported rate...
        out_q.put(("error", f"mic: {e}"))
        return
    out_q.put(("device", info["name"].strip()))
    with stream:
        out_q.put(("ready", None))
        while not stop.is_set():
            # Commands from the game.
            while True:
                try:
                    cmd, arg = cmd_q.get_nowait()
                except queue.Empty:
                    break
                if cmd == "vocab":
                    pending_vocab, pending_since = arg, time.time()
                elif cmd == "mute":
                    muted_until = time.time() + arg

            try:
                data = audio_q.get(timeout=0.1)
            except queue.Empty:
                continue
            level = level_of(data)
            out_q.put(("level", level))
            now = time.time()
            if pending_vocab is not None and (not in_utterance or now - pending_since > 2.0):
                current_vocab = list(pending_vocab)
                rec = make_recognizer(pending_vocab)
                pending_vocab, in_utterance, loudest = None, False, 0.0
                sent.clear()
            if now < muted_until:
                rec.Reset()
                sent.clear()
                continue

            if free is not None:
                if free.AcceptWaveform(data):
                    r = json.loads(free.Result())
                    if r.get("text"):
                        words = [(w["word"], round(w.get("conf", 1.0), 2)) for w in r.get("result", [])]
                        out_q.put(("transcript", (r["text"], True, words)))
                    last_partial = ""
                else:
                    partial = json.loads(free.PartialResult()).get("partial", "")
                    if partial != last_partial:
                        last_partial = partial
                        out_q.put(("transcript", (partial, False, [])))

            loudest = max(loudest, level)
            if cfg.get("save_misses"):
                if in_utterance or level >= cfg.get("voice_level", 0.45):
                    if not utter:
                        utter.extend(pre_roll)
                    utter.append(data)
                else:
                    pre_roll.append(data)
            if rec.AcceptWaveform(data):
                result = json.loads(rec.Result())
                words = [w["word"] if w.get("conf", 1.0) >= cfg["min_confidence"] else "[unk]"
                         for w in result.get("result", [])]
                send(words, now, True)
                if not words and not sent and loudest >= cfg.get("voice_level", 0.45):
                    # A clear sound the recognizer couldn't place (e.g. a very short "a").
                    out_q.put(("voice", now))
                    if cfg.get("save_misses") and utter:
                        _save_miss(b"".join(utter), rate, current_vocab)
                utter = []
                sent.clear()
                in_utterance, loudest = False, 0.0
            else:
                partial = json.loads(rec.PartialResult()).get("partial", "").split()
                in_utterance = in_utterance or bool(partial) or level >= cfg.get("voice_level", 0.45)
                if cfg["use_partials"]:
                    send(partial, now, False)


def _save_miss(audio: bytes, rate: int, vocab: list[str]) -> None:
    """logs/audio/<time>.wav + .json (what it was listening for) - for tuning to kids' voices."""
    import wave
    from pathlib import Path
    d = Path(__file__).resolve().parent.parent.parent / "logs" / "audio"
    d.mkdir(parents=True, exist_ok=True)
    stem = d / time.strftime("%Y%m%d_%H%M%S")
    with wave.open(str(stem) + ".wav", "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(audio)
    (Path(str(stem) + ".json")).write_text(json.dumps({"listening_for": vocab}), encoding="utf-8")


class SpeechService:
    def __init__(self, cfg: dict, transcript: bool = False):
        self.cfg = dict(cfg, transcript=transcript)
        ctx = mp.get_context("spawn")
        self._cmd_q = ctx.Queue()
        self._out_q = ctx.Queue()
        self._stop = ctx.Event()
        self._ctx = ctx
        self._proc = None
        self.ready = False
        self.level = 0.0    # latest mic loudness 0..1
        self.peak = 0.0     # slowly falling peak, for the meter
        self.device_name = ""
        self.error: str | None = None

    def start(self, vocab) -> None:
        self._proc = self._ctx.Process(
            target=_speech_main, daemon=True,
            args=(self.cfg, sorted(vocab), self._cmd_q, self._out_q, self._stop))
        self._proc.start()

    def set_vocab(self, vocab) -> None:
        self._cmd_q.put(("vocab", sorted(vocab)))

    def mute(self, seconds: float) -> None:
        self._cmd_q.put(("mute", seconds))

    def poll(self) -> list[Heard | Voice | Transcript]:
        events = []
        while True:
            try:
                kind, arg = self._out_q.get_nowait()
            except queue.Empty:
                break
            if kind == "level":
                self.level = arg
                self.peak = max(arg, self.peak - 0.02)
            elif kind == "ready":
                self.ready = True
            elif kind == "device":
                self.device_name = arg
            elif kind == "error":
                self.error = arg
            elif kind == "heard":
                events.append(Heard(*arg))
            elif kind == "voice":
                events.append(Voice(arg))
            elif kind == "transcript":
                events.append(Transcript(*arg))
        return events

    def stop(self, wait: bool = True) -> None:
        """Stop the recognizer. wait=False returns immediately (used when switching mics)."""
        self._stop.set()
        proc = self._proc
        if not proc:
            return

        def finish():
            proc.join(timeout=2)
            if proc.is_alive():
                proc.terminate()

        if wait:
            finish()
        else:
            import threading
            threading.Thread(target=finish, daemon=True).start()
