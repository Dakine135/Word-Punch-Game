"""Speech test: shows one word at a time; the kid reads it aloud.

Measures how often and how fast the recognizer gets kids' speech right, and logs results
to logs/speech_test_<time>.csv.

    python tools/speech_spike.py --levels k2 k3
    python tools/speech_spike.py --levels letters
Keys: Space = skip (counts as a miss), Tab / Shift+Tab = change mic (saved to settings.toml),
Esc = quit. The bar at the bottom shows the mic level - it should jump when someone talks.
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
from word_punch.speech.service import Heard, SpeechService, Voice, list_input_devices
from word_punch.ui.mic_meter import draw_mic_meter
from word_punch.ui.render import font as game_font
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
    vocab = bank.vocab(args.levels)

    # Mic choices: "" = system default, then each input device by name.
    mics = [("", "System default")] + [(name, name) for _, name in list_input_devices()]
    current = cfg["speech"]["device"]
    mic_idx = next((i for i, (n, _) in enumerate(mics) if n and current and current.lower() in n.lower()), 0)

    def start_speech():
        svc = SpeechService(dict(cfg["speech"], device=mics[mic_idx][0]))
        svc.start(vocab)
        return svc

    speech = start_speech()
    saved_msg = ""
    switch_at = 0.0  # apply a mic change shortly after the last Tab press

    pygame.init()
    screen = pygame.display.set_mode((1100, 700))
    pygame.display.set_caption("Word Punch - speech test")
    huge = game_font(200)
    font = pygame.font.SysFont("arial", 24)
    small = pygame.font.SysFont("arial", 20)
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
                elif e.type == pygame.KEYDOWN and e.key == pygame.K_TAB:
                    step = -1 if e.mod & pygame.KMOD_SHIFT else 1
                    mic_idx = (mic_idx + step) % len(mics)
                    switch_at = time.time() + 0.6
                    saved_msg = ""

            if switch_at and time.time() >= switch_at:
                switch_at = 0.0
                speech.stop(wait=False)
                speech = start_speech()
                path = config.save_user("speech", "device", mics[mic_idx][0])
                saved_msg = f"saved to {path.name} - the game will use this mic"

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
                screen.blit(surf, surf.get_rect(center=(550, 210)))

            # Mic meter + status
            if switch_at:
                status = "switching..."
            elif speech.error:
                status = speech.error
            elif speech.ready:
                status = "listening"
            else:
                status = "starting mic..."
            draw_mic_meter(screen, pygame.Rect(20, 430, 500, 30), speech.level, speech.peak, font,
                           f"Mic level  ({status})")
            avg = sum(times) / len(times) if times else 0
            lines = [
                f"heard: {' '.join(heard[-8:])}",
                "(~ = partial guess, ? = a sound that wasn't one of the words)",
                f"hits {hits}   skips {misses}   avg time {avg:.1f}s   levels: {' '.join(args.levels)}",
                "Space = skip   Tab / Shift+Tab = change mic   Esc = quit",
            ]
            for i, line in enumerate(lines):
                screen.blit(font.render(line, True, (220, 220, 220)), (20, 480 + i * 34))

            # Mic list on the right
            x, y = 560, 395
            screen.blit(font.render("Microphone (Tab to change):", True, (255, 220, 120)), (x, y))
            for i, (_, label) in enumerate(mics):
                selected = i == mic_idx
                color = (120, 255, 140) if selected else (170, 170, 190)
                screen.blit(small.render(("> " if selected else "   ") + label, True, color), (x, y + 32 + i * 24))
            if saved_msg:
                screen.blit(small.render(saved_msg, True, (150, 150, 170)), (x, y + 36 + len(mics) * 24))
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
