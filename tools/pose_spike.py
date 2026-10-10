"""Pose test: mirrored camera, skeletons, player slots, and PUNCH! events.

Use it to check tracking with the kids and to tune [punch] in settings.toml.
    python tools/pose_spike.py            (Esc quits, F toggles fullscreen)
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pygame

from word_punch import config
from word_punch.ui.camera_view import CameraView
from word_punch.vision.punch import PunchDetector
from word_punch.vision.service import VisionService
from word_punch.vision.tracker import Tracker

PLAYER_COLORS = [(255, 80, 80), (80, 170, 255), (120, 230, 90)]
BONES = [("left_shoulder", "right_shoulder"), ("left_shoulder", "left_elbow"),
         ("left_elbow", "left_wrist"), ("right_shoulder", "right_elbow"),
         ("right_elbow", "right_wrist"), ("left_shoulder", "left_hip"),
         ("right_shoulder", "right_hip"), ("left_hip", "right_hip")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, help="quit after this long and print stats")
    args = ap.parse_args()
    cfg = config.load()
    vision = VisionService(cfg)
    vision.start()

    pygame.init()
    size = (cfg["game"]["width"], cfg["game"]["height"])
    screen = pygame.display.set_mode(size)
    pygame.display.set_caption("Word Punch - pose test")
    font = pygame.font.SysFont("arial", 22, bold=True)
    big = pygame.font.SysFont("arial", 64, bold=True)
    view = CameraView(size, (vision.width, vision.height))
    tracker = Tracker(cfg["pose"]["max_people"])
    detectors = [PunchDetector(cfg["punch"]) for _ in range(tracker.max_players)]
    flashes: list[tuple[float, int, int, int]] = []  # (t, x, y, slot)
    punch_counts = [0] * tracker.max_players
    clock = pygame.time.Clock()
    pose_times: list[float] = []
    started = time.time()
    stats = {"pose_frames": 0, "people_max": 0, "detect_ms": []}

    try:
        running = True
        while running:
            for e in pygame.event.get():
                if e.type == pygame.QUIT or (e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE):
                    running = False
                elif e.type == pygame.KEYDOWN and e.key == pygame.K_f:
                    pygame.display.toggle_fullscreen()

            if args.seconds and time.time() - started > args.seconds:
                running = False
            for t, people in vision.poll():
                pose_times.append(t)
                stats["pose_frames"] += 1
                stats["people_max"] = max(stats["people_max"], len(people))
                stats["detect_ms"].append(vision.pose_ms)
                slots = tracker.update(people, t)
                for s in slots:
                    for p in detectors[s.index].update(s.person, t):
                        punch_counts[s.index] += 1
                        flashes.append((time.time(), *view.to_screen(p.x, p.y), s.index))
            if vision.error:
                print(vision.error)
                return 1

            view.draw(screen, vision.latest_frame())
            for s in tracker.slots:
                if not s.person:
                    continue
                color = PLAYER_COLORS[s.index]
                kp = s.person.keypoints
                for a, b in BONES:
                    if kp[a].vis > 0.3 and kp[b].vis > 0.3:
                        pygame.draw.line(screen, color, view.to_screen(kp[a].x, kp[a].y),
                                         view.to_screen(kp[b].x, kp[b].y), 4)
                for hand in ("left_wrist", "right_wrist"):
                    if kp[hand].vis > 0.3:
                        pygame.draw.circle(screen, color, view.to_screen(kp[hand].x, kp[hand].y), 18, 5)
                nose = kp["nose"]
                label = font.render(f"P{s.index + 1}  punches: {punch_counts[s.index]}", True, color)
                x, y = view.to_screen(nose.x, nose.y)
                screen.blit(label, (x - label.get_width() // 2, max(0, y - 80)))

            now = time.time()
            flashes = [f for f in flashes if now - f[0] < 0.6]
            for ft, x, y, slot in flashes:
                age = (now - ft) / 0.6
                pygame.draw.circle(screen, (255, 230, 60), (x, y), int(30 + 90 * age), 6)
                txt = big.render("PUNCH!", True, PLAYER_COLORS[slot])
                screen.blit(txt, (x - txt.get_width() // 2, y - 120 - int(60 * age)))

            pose_times = [pt for pt in pose_times if now - pt < 1.0]
            hud = font.render(
                f"pose fps {len(pose_times)}   detect {vision.pose_ms:.0f} ms   draw fps {clock.get_fps():.0f}"
                + ("" if vision.ready else "   (starting camera...)"), True, (255, 255, 255))
            screen.blit(hud, (10, 10))
            pygame.display.flip()
            clock.tick(60)
    finally:
        vision.stop()
        pygame.quit()
        if args.seconds:
            ms = sorted(stats["detect_ms"]) or [0]
            elapsed = time.time() - started
            print(f"pose frames {stats['pose_frames']} in {elapsed:.1f}s, max people {stats['people_max']}, "
                  f"detect median {ms[len(ms) // 2]:.0f} ms, punches {punch_counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
