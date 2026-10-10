"""Re-run saved 'unheard' clips (logs/audio, from Settings -> Save unheard speech) through
both speech models and a few listening tricks, to see what would have caught them.

    python tools/replay_misses.py
"""
from __future__ import annotations

import json
import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import vosk  # noqa: E402

AUDIO = ROOT / "logs" / "audio"
MODELS = ["vosk-model-small-en-us-0.15", "vosk-model-en-us-0.22-lgraph"]


def decode(model, audio: np.ndarray, vocab: list[str], unk: bool = True) -> str:
    words = sorted(set(vocab) - {"[unk]"}) + (["[unk]"] if unk else [])
    r = vosk.KaldiRecognizer(model, 16000, json.dumps(words))
    data = np.clip(audio, -32768, 32767).astype(np.int16).tobytes()
    out = []
    for i in range(0, len(data), 3200):
        if r.AcceptWaveform(data[i:i + 3200]):
            out.append(json.loads(r.Result()).get("text", ""))
    out.append(json.loads(r.FinalResult()).get("text", ""))
    return " ".join(t for t in out if t).strip() or "-"


def deepen(x: np.ndarray, factor: float = 0.82) -> np.ndarray:
    return np.interp(np.arange(0, len(x) - 1, factor), np.arange(len(x)), x)


def main() -> int:
    clips = sorted(AUDIO.glob("*.wav"))
    if not clips:
        print("No clips yet - turn on Settings -> Save unheard speech and play a round.")
        return 0
    vosk.SetLogLevel(-1)
    models = {m: vosk.Model(str(ROOT / "models" / m)) for m in MODELS if (ROOT / "models" / m).exists()}
    caught = {k: 0 for k in [f"{m}{v}" for m in models for v in ("", " +deeper", " forgiving")]}
    for clip in clips:
        meta = json.loads(clip.with_suffix(".json").read_text(encoding="utf-8"))
        vocab = meta["listening_for"]
        with wave.open(str(clip)) as w:
            audio = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32)
        print(f"\n{clip.name}  ({len(audio) / 16000:.1f}s)  listening for: "
              f"{' '.join(v for v in vocab if v != '[unk]')[:90]}")
        for name, m in models.items():
            short = "small" if "small" in name else "big"
            for label, a, unk in (("", audio, True), (" +deeper", deepen(audio), True), (" forgiving", audio, False)):
                text = decode(m, a, vocab, unk)
                got = any(t in vocab and t != "[unk]" for t in text.split())
                caught[f"{name}{label}"] += got
                print(f"   {short + label:16s} -> {text}")
    print("\ncaught (any listened-for word):")
    for k, v in caught.items():
        print(f"   {k:45s} {v}/{len(clips)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
