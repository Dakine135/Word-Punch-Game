"""Speech test: shows one word at a time; the kid reads it aloud.

Measures how often and how fast the recognizer gets kids' speech right, and logs results
to logs/speech_test_<time>.csv. Shows two things for every attempt:
  - "Game heard": what the game's recognizer picked (it can only choose words in play, or "?")
  - "Transcript": what a free, any-word recognizer thinks was said, with confidence per word
    (green = sure, yellow = unsure, red = guessing) - this is how you see *why* it got it wrong.

    python tools/speech_spike.py --levels k2 k3
    python tools/speech_spike.py --levels letters
Keys:
  type a word + Enter   test any word (it's added to what the game listens for)
  Space                 skip (counts as a miss)
  F5                    after a miss: accept what it heard for that word from now on
                        (saved in aliases.toml - the game uses it too)
  Tab / Shift+Tab       change mic (saved to settings.toml, the game uses it too)
  Esc                   clear typing / quit
"""
from __future__ import annotations

import argparse
import csv
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pygame

from word_punch import config
from word_punch.speech.matcher import match_strength
from word_punch.speech.service import Heard, SpeechService, Transcript, Utterance, Voice, list_input_devices
from word_punch.ui.mic_meter import draw_mic_meter
from word_punch.ui.render import font as game_font
from word_punch.words import WordBank, norm

ROOT = Path(__file__).resolve().parent.parent
W, H = 1280, 780
BG = (25, 30, 50)
DIM = (150, 155, 175)
TEXT = (225, 225, 235)
GOOD = (120, 235, 140)
BAD = (255, 120, 120)
WARN = (245, 205, 90)


def conf_color(c: float):
    return GOOD if c >= 0.85 else WARN if c >= 0.6 else BAD


@dataclass
class Attempt:
    target: str
    said: list = field(default_factory=list)      # [(word, conf)] from the free recognizer
    game: list = field(default_factory=list)      # tokens the game's recognizer produced
    hit: bool = False
    seconds: float = 0.0                          # how long the word was up before the hit


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
    vocab = set(bank.vocab(args.levels))
    grammar = cfg["speech"].get("grammar", "screen")

    def listen_for(target):
        """Like the game: the word shown + 3 other words (as if on screen), unless grammar = level."""
        if grammar != "screen":
            return set(vocab)
        others = random.sample([w for w in words if w != target], min(3, len(words) - 1))
        toks = set()
        for text, is_letter in [target] + others:
            toks |= bank.listen_tokens(text, is_letter)
        return toks

    # Mic choices: "" = system default, then each input device by name.
    mics = [("", "System default")] + [(name, name) for _, name in list_input_devices()]
    current = cfg["speech"]["device"]
    mic_idx = next((i for i, (n, _) in enumerate(mics) if n and current and current.lower() in n.lower()), 0)

    def start_speech():
        svc = SpeechService(dict(cfg["speech"], device=mics[mic_idx][0]), transcript=True)
        svc.start(vocab)
        return svc

    speech = start_speech()
    saved_msg = ""
    switch_at = 0.0  # apply a mic change shortly after the last Tab press

    pygame.init()
    screen = pygame.display.set_mode((W, H))
    pygame.display.set_caption("Word Punch - speech test")
    huge = game_font(170)
    mid = pygame.font.SysFont("arial", 28)
    font = pygame.font.SysFont("arial", 22)
    small = pygame.font.SysFont("arial", 19)
    clock = pygame.time.Clock()

    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"speech_test_{time.strftime('%Y%m%d_%H%M%S')}.csv"
    log = open(log_path, "w", newline="", encoding="utf-8")
    writer = csv.writer(log)
    writer.writerow(["target", "result", "seconds", "game_heard", "transcript"])

    def log_row(target, result, seconds, game, said):
        writer.writerow([target, result, f"{seconds:.2f}" if seconds else "", " ".join(game),
                         " ".join(f"{w}({c})" for w, c in said)])
        log.flush()

    random.shuffle(words)
    speech.set_vocab(listen_for(words[0]))
    idx, shown_at = 0, time.time()
    custom: tuple[str, bool] | None = None  # a typed-in test word
    typed = ""
    game_heard: list[str] = []      # game tokens for the current word
    live = ""                       # live partial transcript
    last_said: list = []            # last final transcript [(word, conf)]
    history: list[Attempt] = []
    attempt = None                  # the utterance in progress
    consumed = False                # this utterance already scored; ignore the rest of it
    last_event = 0.0
    hits = misses = 0
    times: list[float] = []
    flash_until, flash_color = 0.0, (0, 0, 0)
    note, note_until = "", 0.0

    def target_now() -> tuple[str, bool]:
        return custom if custom else words[idx % len(words)]

    def next_word(result: str) -> float:
        nonlocal idx, shown_at, game_heard, hits, misses, flash_until, flash_color, custom
        dt = time.time() - shown_at
        if result == "hit":
            hits += 1
            times.append(dt)
            flash_color = (40, 160, 60)
        else:
            misses += 1
            flash_color = (170, 50, 50)
            log_row(target_now()[0], "skip", dt, game_heard, [])
        flash_until = time.time() + 0.5
        if custom:
            custom = None
        else:
            idx += 1
            if idx % len(words) == 0:
                random.shuffle(words)
        shown_at, game_heard = time.time() + 0.5, []
        speech.set_vocab(listen_for(target_now()))
        return dt

    try:
        running = True
        while running:
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    running = False
                elif e.type != pygame.KEYDOWN:
                    continue
                elif e.key == pygame.K_ESCAPE:
                    if typed:
                        typed = ""
                    else:
                        running = False
                elif e.key == pygame.K_SPACE:
                    next_word("skip")
                elif e.key == pygame.K_F5:
                    # Accept the last miss's sound-alike for its word.
                    miss = next((a for a in reversed(history) if not a.hit), None)
                    cand = None
                    if miss:
                        said = [w for w, _ in miss.said if not match_strength(w, miss.target, False, bank)]
                        game = [g.rstrip("~") for g in miss.game if g != "?"]
                        cand = (said or game or [None])[0]
                    if cand and bank.add_user_alias(miss.target, cand):
                        vocab.add(cand)
                        speech.set_vocab(listen_for(target_now()))
                        note = f'Now "{cand}" counts for "{miss.target}"'
                    elif miss:
                        note = f'Nothing to add for "{miss.target}" (heard: {cand or "nothing"})'
                    else:
                        note = "No missed attempt yet"
                    note_until = time.time() + 4
                elif e.key == pygame.K_TAB:
                    step = -1 if e.mod & pygame.KMOD_SHIFT else 1
                    mic_idx = (mic_idx + step) % len(mics)
                    switch_at = time.time() + 0.6
                    saved_msg = ""
                elif e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    if typed:
                        is_letter = len(typed) == 1
                        custom = (typed, is_letter)
                        if not is_letter and norm(typed) not in vocab:
                            vocab.add(norm(typed))
                        speech.set_vocab(listen_for(custom) | {norm(typed)})
                        typed, game_heard, shown_at = "", [], time.time()
                elif e.key == pygame.K_BACKSPACE:
                    typed = typed[:-1]
                elif e.unicode and (e.unicode.isalpha() or e.unicode == "'"):
                    typed += e.unicode

            if switch_at and time.time() >= switch_at:
                switch_at = 0.0
                speech.stop(wait=False)
                speech = start_speech()
                path = config.save_user("speech", "device", mics[mic_idx][0])
                saved_msg = f"saved to {path.name} - the game will use this mic"

            target, is_letter = target_now()
            now = time.time()
            if attempt is not None and now - last_event > 3.0:
                consumed = False  # safety: utterance never got a final transcript
            for ev in speech.poll():
                last_event = now
                if isinstance(ev, Utterance):
                    continue
                if isinstance(ev, Transcript):
                    if not ev.final:
                        live = ev.text
                        if ev.text and attempt is None:
                            attempt = Attempt(target)
                        continue
                    # End of an utterance: record it with what was really said.
                    live = ""
                    last_said = ev.words
                    a = attempt or Attempt(target)
                    a.said = ev.words
                    history.append(a)
                    del history[:-7]
                    log_row(a.target, "hit" if a.hit else "miss", a.seconds, a.game, a.said)
                    attempt, consumed = None, False
                    continue
                if attempt is None:
                    attempt = Attempt(target)
                attempt.game.append("?" if isinstance(ev, Voice) else ev.word + ("" if ev.final else "~"))
                if consumed or now < shown_at:
                    continue  # rest of an utterance that already scored, or still flashing
                if isinstance(ev, Heard):
                    game_heard.append(ev.word + ("" if ev.final else "~"))
                    if match_strength(ev.word, target, is_letter, bank):
                        attempt.hit, consumed = True, True
                        attempt.seconds = next_word("hit")
                        target, is_letter = target_now()
                elif isinstance(ev, Voice):
                    game_heard.append("?")

            # ---- draw ----
            now = time.time()
            screen.fill(flash_color if now < flash_until else BG)
            if now >= flash_until:
                t, _ = target_now()
                surf = huge.render(t, True, WARN if custom else (255, 255, 255))
                screen.blit(surf, surf.get_rect(center=(W // 2, 135)))
                if custom:
                    c = small.render("(your test word)", True, DIM)
                    screen.blit(c, c.get_rect(center=(W // 2, 240)))

            y = 265
            screen.blit(mid.render("Game heard:", True, DIM), (20, y))
            screen.blit(mid.render(" ".join(game_heard[-8:]) or "-", True, TEXT), (180, y))
            y += 40
            screen.blit(mid.render("Transcript:", True, DIM), (20, y))
            if live:
                screen.blit(mid.render(live + " ...", True, DIM), (180, y))
            else:
                x = 180
                for w, c in last_said:
                    s = mid.render(f"{w} ", True, conf_color(c))
                    screen.blit(s, (x, y))
                    x += s.get_width()
                if not last_said:
                    screen.blit(mid.render("-", True, DIM), (x, y))

            # History: word shown / what was said (free transcript) / what the game heard.
            y = 360
            screen.blit(font.render("Recent attempts:   word shown   |   you said (confidence)   |   game heard",
                                    True, WARN), (20, y))
            y += 32
            for a in reversed(history):
                if a.hit:  # check mark
                    pygame.draw.lines(screen, GOOD, False, [(20, y + 11), (25, y + 17), (34, y + 4)], 3)
                else:      # cross
                    pygame.draw.line(screen, BAD, (21, y + 4), (32, y + 16), 3)
                    pygame.draw.line(screen, BAD, (32, y + 4), (21, y + 16), 3)
                screen.blit(small.render(a.target, True, TEXT), (44, y))
                x = 160
                for w, c in a.said:
                    s = small.render(f"{w}({c:.2f}) ", True, conf_color(c))
                    if x + s.get_width() > 560:
                        screen.blit(small.render("...", True, DIM), (x, y))
                        break
                    screen.blit(s, (x, y))
                    x += s.get_width()
                screen.blit(small.render("|  " + (" ".join(a.game) or "-"), True, DIM), (580, y))
                y += 27

            # Mic meter, stats, keys.
            if switch_at:
                status = "switching..."
            elif speech.error:
                status = speech.error
            elif speech.ready:
                status = "listening"
            else:
                status = "starting mic..."
            draw_mic_meter(screen, pygame.Rect(20, 625, 480, 26), speech.level, speech.peak, font,
                           f"Mic level  ({status})")
            avg = sum(times) / len(times) if times else 0
            screen.blit(font.render(
                f"hits {hits}   skips {misses}   avg time {avg:.1f}s   levels: {' '.join(args.levels)}",
                True, TEXT), (20, 665))
            screen.blit(small.render(
                "type a word + Enter = test   Space = skip   F5 = accept last miss   Tab = mic   Esc = quit",
                True, DIM), (20, 700))
            if typed:
                screen.blit(mid.render(f"test word: {typed}_   (Enter)", True, WARN), (20, 735))
            elif now < note_until:
                screen.blit(mid.render(note, True, GOOD), (20, 735))

            # Mic list on the right.
            x, y = 880, 360
            screen.blit(font.render("Microphone (Tab to change):", True, WARN), (x, y))
            for i, (_, label) in enumerate(mics):
                selected = i == mic_idx
                screen.blit(small.render(("> " if selected else "   ") + label, True,
                                         GOOD if selected else DIM), (x, y + 32 + i * 24))
            for j, line in enumerate(saved_msg.split(" - ") if saved_msg else []):
                screen.blit(small.render(line, True, DIM), (x, y + 40 + len(mics) * 24 + j * 22))

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
