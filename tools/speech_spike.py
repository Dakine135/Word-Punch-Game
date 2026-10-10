"""Speech test: shows one word at a time; the kid reads it aloud.

Measures how often and how fast the recognizer gets kids' speech right, and logs results
to logs/speech_test_<time>.csv.

    python tools/speech_spike.py --levels k2 k3
    python tools/speech_spike.py --levels letters
Keys: Space = skip (counts as a miss), Esc = quit.
"""
from __future__ import annotations

import argparse
import csv
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pygame

from word_punch import config
from word_punch.speech.matcher import match_strength
from word_punch.speech.service import Heard, SpeechService, Voice
from word_punch.words import WordBank

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    bank = WordBank()
    ap = argparse.ArgumentParser()
    ap.add_argument("--levels", nargs="+", default=["k2", "k3"], choices=bank.order)
    ap.add_argument("--device", help="mic name substring (overrides settings)")
    args = ap.parse_args()

    cfg = config.load()
    if args.device:
        cfg["speech"]["device"] = args.device
    words = [(w, bank.level(k).is_letters) for k in args.levels for w in bank.level(k).words]
    speech = SpeechService(cfg["speech"])
    speech.start(bank.vocab(args.levels))

    pygame.init()
    screen = pygame.display.set_mode((1100, 650))
    pygame.display.set_caption("Word Punch - speech test")
    huge = pygame.font.SysFont("comicsansms", 200, bold=True)
    font = pygame.font.SysFont("arial", 26)
    clock = pygame.time.Clock()

    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"speech_test_{time.strftime('%Y%m%d_%H%M%S')}.csv"
    log = open(log_path, "w", newline="")
    writer = csv.writer(log)
    writer.writerow(["target", "result", "seconds", "heard"])

    random.shuffle(words)
    idx, shown_at = 0, time.time()
    heard: list[str] = []
    hits = misses = 0
    times: list[float] = []
    flash_until, flash_color = 0.0, (0, 0, 0)

    def next_word(result: str):
        nonlocal idx, shown_at, heard, hits, misses, flash_until, flash_color
        target = words[idx % len(words)][0]
        dt = time.time() - shown_at
        writer.writerow([target, result, f"{dt:.2f}", " ".join(heard)])
        log.flush()
        if result == "hit":
            hits += 1
            times.append(dt)
            flash_color = (40, 160, 60)
        else:
            misses += 1
            flash_color = (170, 50, 50)
        flash_until = time.time() + 0.5
        idx += 1
        if idx % len(words) == 0:
            random.shuffle(words)
        shown_at, heard = time.time() + 0.5, []

    try:
        running = True
        while running:
            for e in pygame.event.get():
                if e.type == pygame.QUIT or (e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE):
                    running = False
                elif e.type == pygame.KEYDOWN and e.key == pygame.K_SPACE:
                    next_word("skip")

            target, is_letter = words[idx % len(words)]
            for ev in speech.poll():
                if time.time() < shown_at:
                    continue  # still showing the last result
                if isinstance(ev, Heard):
                    heard.append(ev.word + ("" if ev.final else "~"))
                    if match_strength(ev.word, target, is_letter, bank):
                        next_word("hit")
                        break
                elif isinstance(ev, Voice):
                    heard.append("?")

            now = time.time()
            screen.fill(flash_color if now < flash_until else (25, 30, 50))
            if now >= flash_until:
                t, _ = words[idx % len(words)]
                surf = huge.render(t, True, (255, 255, 255))
                screen.blit(surf, surf.get_rect(center=(550, 270)))
            status = "listening" if speech.ready else "starting mic..."
            avg = sum(times) / len(times) if times else 0
            lines = [
                f"{status}   heard: {' '.join(heard[-8:])}   (~ = partial, ? = unknown sound)",
                f"hits {hits}   skips {misses}   avg time {avg:.1f}s   levels: {' '.join(args.levels)}",
                "Space = skip   Esc = quit",
            ]
            for i, line in enumerate(lines):
                screen.blit(font.render(line, True, (220, 220, 220)), (20, 520 + i * 36))
            pygame.display.flip()
            clock.tick(60)
    finally:
        speech.stop()
        log.close()
        pygame.quit()
        print(f"log: {log_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
