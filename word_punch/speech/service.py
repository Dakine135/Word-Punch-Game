"""Offline speech recognition in its own process (mic -> Vosk -> heard words).

The game talks to it through SpeechService:
    svc = SpeechService(cfg["speech"]); svc.start(vocab)
    for event in svc.poll(): ...      # Heard(word) or Voice()
    svc.mute(1.2)                      # ignore the mic while the game itself is talking
"""
from __future__ import annotations

import json
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


def find_input_device(name_part: str):
    import sounddevice as sd
    if not name_part:
        return None
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0 and name_part.lower() in d["name"].lower():
            return i
    raise ValueError(f"no input device matching {name_part!r}")


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

    device = find_input_device(cfg["device"])
    with sd.RawInputStream(samplerate=rate, blocksize=rate // 10, dtype="int16",
                           channels=1, device=device, callback=on_audio):
        out_q.put(("ready", None))
        while not stop.is_set():
            # Commands from the game.
            while True:
                try:
                    cmd, arg = cmd_q.get_nowait()
                except queue.Empty:
                    break
                if cmd == "vocab":
                    rec = make_recognizer(arg)
                    sent.clear()
                elif cmd == "mute":
                    muted_until = time.time() + arg

            try:
                data = audio_q.get(timeout=0.1)
            except queue.Empty:
                continue
            now = time.time()
            if now < muted_until:
                rec.Reset()
                sent.clear()
                continue

            if rec.AcceptWaveform(data):
                result = json.loads(rec.Result())
                words = [w["word"] if w.get("conf", 1.0) >= cfg["min_confidence"] else "[unk]"
                         for w in result.get("result", [])]
                send(words, now, True)
                sent.clear()
            elif cfg["use_partials"]:
                send(json.loads(rec.PartialResult()).get("partial", "").split(), now, False)


class SpeechService:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        ctx = mp.get_context("spawn")
        self._cmd_q = ctx.Queue()
        self._out_q = ctx.Queue()
        self._stop = ctx.Event()
        self._ctx = ctx
        self._proc = None
        self.ready = False

    def start(self, vocab) -> None:
        self._proc = self._ctx.Process(
            target=_speech_main, daemon=True,
            args=(self.cfg, sorted(vocab), self._cmd_q, self._out_q, self._stop))
        self._proc.start()

    def set_vocab(self, vocab) -> None:
        self._cmd_q.put(("vocab", sorted(vocab)))

    def mute(self, seconds: float) -> None:
        self._cmd_q.put(("mute", seconds))

    def poll(self) -> list[Heard | Voice]:
        events = []
        while True:
            try:
                kind, arg = self._out_q.get_nowait()
            except queue.Empty:
                break
            if kind == "ready":
                self.ready = True
            elif kind == "heard":
                events.append(Heard(*arg))
            elif kind == "voice":
                events.append(Voice(arg))
        return events

    def stop(self) -> None:
        self._stop.set()
        if self._proc:
            self._proc.join(timeout=2)
            if self._proc.is_alive():
                self._proc.terminate()
