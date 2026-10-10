"""Pre-generate every voice clip (all words, letters, phrases) into assets/voice/.

The game also does this in the background as needed; running it ahead of time (e.g. on the
Pi after install) means the first game never waits for a clip.
    python tools/gen_voice.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from word_punch import config
from word_punch.app import PHRASES
from word_punch.voice import Voice, spoken
from word_punch.words import WordBank


def main() -> int:
    bank = WordBank()
    v = Voice(config.load()["voice"])
    if not v.enabled:
        print(v.error or "voice disabled")
        return 1
    texts = list(PHRASES)
    for key in bank.order:
        lvl = bank.level(key)
        texts += [spoken(w, lvl.is_letters) for w in lvl.words]
    texts += list(sys.argv[1:])
    t = time.time()
    made = 0
    for text in dict.fromkeys(texts):
        if not v.path(text).exists():
            v._generate(text)
            made += 1
    print(f"{made} new clips ({len(texts)} total) in {time.time() - t:.1f}s -> {v.path('x').parent}"
          + (f"  ERROR {v.error}" if v.error else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
