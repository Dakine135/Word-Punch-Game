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

import numpy as np
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
class Utterance:
    """One stretch of speech and what each model made of it (for logs/game_*.csv)."""
    info: dict


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


def _gpu_speech_main(cfg: dict, vocab: list[str], cmd_q: mp.Queue, out_q: mp.Queue, stop) -> None:
    """Whisper / Parakeet on the GPU: transcribe each utterance, report its words."""
    import sounddevice as sd

    from .utterance import UtteranceListener, make_engine

    rate = 16000
    try:
        engine = make_engine(cfg)
    except Exception as e:
        out_q.put(("error", f"speech model: {e}"))
        return
    listener = UtteranceListener(engine, cfg, rate)
    listener.hint = sorted(vocab)[:30]
    listener.vocab = sorted(vocab)
    audio_q: queue.Queue = queue.Queue()
    muted_until = 0.0
    has_hint = False

    def on_audio(indata, frames, time_info, status):
        audio_q.put(bytes(indata))

    try:
        device = find_input_device(cfg["device"])
        stream = sd.RawInputStream(samplerate=rate, blocksize=rate // 20, dtype="int16",
                                   channels=1, device=device, callback=on_audio)
        info = sd.query_devices(device if device is not None else sd.default.device[0])
    except Exception as e:
        out_q.put(("error", f"mic: {e}"))
        return
    out_q.put(("device", info["name"].strip()))
    with stream:
        out_q.put(("ready", None))
        while not stop.is_set():
            while True:
                try:
                    cmd, arg = cmd_q.get_nowait()
                except queue.Empty:
                    break
                if cmd == "hint":  # the words on screen (display spelling)
                    listener.hint, has_hint = list(arg)[:30], True
                elif cmd == "vocab":
                    listener.vocab = list(arg)
                    if not has_hint:  # fallback hint (e.g. the speech test tool)
                        listener.hint = list(arg)[:30]
                elif cmd == "mute":
                    muted_until = time.time() + arg
                    listener.reset()
            try:
                data = audio_q.get(timeout=0.1)
            except queue.Empty:
                continue
            level = level_of(data)
            out_q.put(("level", level))
            now = time.time()
            if now < muted_until:
                continue
            for ev in listener.feed(data, level, now):
                if ev[0] == "voice" and cfg.get("save_misses") and listener.last_audio is not None:
                    pcm = (np.clip(listener.last_audio, -1, 1) * 32767).astype(np.int16).tobytes()
                    _save_miss(pcm, rate, listener.hint)
                out_q.put(ev)


def _speech_main(cfg: dict, vocab: list[str], cmd_q: mp.Queue, out_q: mp.Queue, stop) -> None:
    if cfg.get("engine", "vosk") in ("whisper", "parakeet", "choice"):
        return _gpu_speech_main(cfg, vocab, cmd_q, out_q, stop)
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
    # Second opinion: when Vosk hears a voice but can't place the word (the kids' problem),
    # ask Whisper on the GPU "which on-screen word was that?" (whisper_choice.py).
    chooser = None
    if cfg.get("second_opinion", True):
        try:
            from .whisper_choice import WhisperChooser, cuda_dlls
            cuda_dlls()
            chooser = WhisperChooser(cfg.get("choice_model", "openai/whisper-large-v3-turbo"))
        except Exception as e:  # keep listening with Vosk alone
            out_q.put(("error", f"second opinion off: {e}"))
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
    floor = 0.3                 # background noise level (0..1): music, fans, the room
    current_vocab = list(vocab)
    from collections import deque
    pre_roll: deque = deque(maxlen=8)   # ~0.4 s before speech starts
    recent: deque = deque(maxlen=20)    # (word, time) Vosk has sent
    # Whisper's own look at each stretch of speech (found by loudness, not by Vosk):
    seg = {"audio": [], "voiced": 0, "quiet": 0, "loud": 0.0, "start": 0.0}
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
                recent.append((w, now))
            if i < len(sent):
                sent[i] = w
            else:
                sent.append(w)

    def end_segment(now, gate):
        """A stretch of speech just ended: did Whisper hear an on-screen word Vosk missed?"""
        audio, voiced, loud, start = b"".join(seg["audio"]), seg["voiced"], seg["loud"], seg["start"]
        seg.update(audio=[], voiced=0, quiet=0, loud=0.0)
        if voiced < 3:  # under 0.15 s of sound: a clap or a thud
            return
        vosk_words = [w for w, t in recent if t >= start - 1.0]
        diag = {"peak": round(loud, 2), "floor": round(floor, 2), "gate": round(gate, 2),
                "secs": round(len(audio) / 2 / rate, 1), "vosk": " ".join(vosk_words) or "-"}
        picked = None
        if chooser is not None:
            try:
                x = np.frombuffer(audio, np.int16).astype(np.float32) / 32768
                picked, info = chooser.choose(x, current_vocab, cfg.get("choice_floor", -2.0))
                diag["whisper"] = f"{info.get('best')}:{info.get('score', 0):.2f}"
            except Exception as e:
                out_q.put(("error", f"second opinion: {e}"))
        if picked and picked not in vosk_words:
            out_q.put(("heard", (picked, now, True)))
            out_q.put(("transcript", (f"(whisper) {picked}", True, [(picked, 1.0)])))
            diag["used"] = "whisper"
        if not picked and not vosk_words:
            out_q.put(("voice", now))
            if cfg.get("save_misses"):
                _save_miss(audio, rate, current_vocab, diag)
        out_q.put(("utt", diag))

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
            # Someone is speaking when the mic is clearly above the room's background noise
            # (kids across the room are much quieter than a grown-up next to the laptop).
            floor += (level - floor) * (0.2 if level < floor else 0.003)  # drops fast, rises slowly
            gate = min(cfg.get("voice_level", 0.45), floor + cfg.get("voice_margin", 0.1))
            if pending_vocab is not None and (not in_utterance or now - pending_since > 2.0):
                current_vocab = list(pending_vocab)
                rec = make_recognizer(pending_vocab)
                pending_vocab, in_utterance = None, False
                sent.clear()
            if now < muted_until:
                rec.Reset()
                sent.clear()
                seg.update(audio=[], voiced=0, quiet=0, loud=0.0)
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

            # Vosk: fast, reacts while the word is still being said.
            if rec.AcceptWaveform(data):
                result = json.loads(rec.Result())
                words = [w["word"] if w.get("conf", 1.0) >= cfg["min_confidence"] else "[unk]"
                         for w in result.get("result", [])]
                send(words, now, True)
                sent.clear()
                in_utterance = False
            else:
                partial = json.loads(rec.PartialResult()).get("partial", "").split()
                in_utterance = in_utterance or bool(partial)
                if cfg["use_partials"]:
                    send(partial, now, False)

            # Whisper: checks every stretch of speech once it ends (kids' quiet or unclear
            # words that Vosk drops, files as "[unk]" or mistakes for another word).
            if level >= gate:
                if not seg["audio"]:
                    seg["audio"], seg["start"] = list(pre_roll), now
                seg["audio"].append(data)
                seg["voiced"] += 1
                seg["quiet"] = 0
                seg["loud"] = max(seg["loud"], level)
            elif seg["audio"]:
                seg["audio"].append(data)
                seg["quiet"] += 1
            else:
                pre_roll.append(data)
            if seg["audio"] and (seg["quiet"] >= 8 or len(seg["audio"]) >= 160):  # 0.4 s pause, or 8 s
                end_segment(now, gate)


def _save_miss(audio: bytes, rate: int, vocab: list[str], diag: dict | None = None) -> None:
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
    (Path(str(stem) + ".json")).write_text(json.dumps({"listening_for": vocab, **(diag or {})}), encoding="utf-8")


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

    def set_hint(self, words) -> None:
        """Words on screen right now (GPU models use them as a spelling hint)."""
        self._cmd_q.put(("hint", list(words)))

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
            elif kind == "utt":
                events.append(Utterance(arg))
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
