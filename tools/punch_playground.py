"""Punch playground: the real game with camera + skeletons, words unlock by themselves,
so kids can practice punching and you can tune punch detection live.

    python tools/punch_playground.py                      (2 players: P1 k1, P2 letters)
    python tools/punch_playground.py --player Sam:k3 --player Max:letters --mode coop
    python tools/punch_playground.py --no-camera          (mouse clicks punch - animation test)

Keys:
  Up / Down        min_rise  (how far the fist must travel up, in shoulder-widths)
  Right / Left     min_speed (how fast, shoulder-widths per second)
  ] / [            window    (how long a punch may take)
  A                require fist to end above the shoulder (on/off)
  B                rocket starts at the floor / at the fist
  U                auto-unlock words (on/off; off = say the word, needs --mic)
  K                skeletons on/off
  H                hide/show the tuning panel
  S                save punch settings to settings.toml
  R                restart     Esc  quit
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pygame

from word_punch import config
from word_punch.app import App, parse_args
from word_punch.game.core import Event
from word_punch.ui.render import GOLD, PLAYER_COLORS
from word_punch.words import WordBank

PANEL = (10, 12, 26, 200)
GOOD = (120, 235, 140)
DIM = (170, 175, 195)


class Playground(App):
    def __init__(self, args, cfg, bank):
        cfg["game"]["skeletons"] = False  # the playground draws its own (with the shoulder line)
        super().__init__(args, cfg, bank)
        self.show_typing = False
        self.auto_unlock = True
        self.show_skeleton = True
        self.show_panel = True
        self.msg, self.msg_until = "", 0.0
        self.punches = [0, 0, 0]
        self._last_punch = {}

    # ---- keys --------------------------------------------------------------------

    def flash_msg(self, text: str) -> None:
        self.msg, self.msg_until = text, time.time() + 2.5

    def on_key(self, e, now: float) -> bool:
        pc, rules = self.cfg["punch"], self.cfg["rules"]
        k = e.key
        if k in (pygame.K_UP, pygame.K_DOWN):
            pc["min_rise"] = round(max(0.1, pc["min_rise"] + (0.1 if k == pygame.K_UP else -0.1)), 2)
        elif k in (pygame.K_RIGHT, pygame.K_LEFT):
            pc["min_speed"] = round(max(0.25, pc["min_speed"] + (0.25 if k == pygame.K_RIGHT else -0.25)), 2)
        elif k in (pygame.K_RIGHTBRACKET, pygame.K_LEFTBRACKET):
            pc["window_s"] = round(min(1.0, max(0.1, pc["window_s"] + (0.05 if k == pygame.K_RIGHTBRACKET else -0.05))), 2)
        elif k == pygame.K_a:
            pc["above_shoulder"] = not pc["above_shoulder"]
        elif k == pygame.K_b:
            rules["rocket_from"] = "fist" if rules["rocket_from"] == "bottom" else "bottom"
            self.flash_msg(f"rockets start at the {rules['rocket_from']}")
        elif k == pygame.K_u:
            self.auto_unlock = not self.auto_unlock
            self.flash_msg("auto-unlock " + ("on" if self.auto_unlock else "off - read the words"))
        elif k == pygame.K_k:
            self.show_skeleton = not self.show_skeleton
        elif k == pygame.K_h:
            self.show_panel = not self.show_panel
        elif k == pygame.K_s:
            for key in ("min_rise", "min_speed", "window_s", "above_shoulder"):
                path = config.save_user("punch", key, pc[key])
            config.save_user("rules", "rocket_from", rules["rocket_from"])
            self.flash_msg(f"saved to {path.name}")
        elif k == pygame.K_r:
            self.new_game()
            self.punches = [0, 0, 0]
        else:
            return False
        return True

    # ---- per frame -----------------------------------------------------------------

    def after_update(self, now: float) -> None:
        if self.auto_unlock and not self.game.over:
            for w in self.game.words:
                # unlock once the word has cleared the HUD strip
                if not w.unlocked and w.y > self.renderer.hud_height:
                    w.unlocked, w.unlocked_at, w.read_time = True, now, now - w.spawned_at
                    self.game.events.append(Event("unlock", w, x=w.x, y=w.y))
        if self.vision:
            for i, det in enumerate(self.punchers):
                for h in det.hands:
                    key = (i, h.hand)
                    if h.last_punch != self._last_punch.get(key, h.last_punch):
                        self.punches[i] += 1
                    self._last_punch[key] = h.last_punch

    def draw_overlay(self, surf: pygame.Surface, now: float) -> None:
        r = self.renderer
        if self.vision and self.show_skeleton:
            self.skeletons.begin()
            for s in self.tracker.slots:
                if s.person:
                    self.skeletons.add(self.view, s.person, PLAYER_COLORS[s.index % 3], alpha=220,
                                       shoulder_line=True)
            self.skeletons.end(surf)

        # settings panel (bottom right)
        pc, rules = self.cfg["punch"], self.cfg["rules"]
        lines = [
            ("PUNCH TUNING", GOLD),
            (f"min_rise   {pc['min_rise']:.1f}   (Up/Down)", (255, 255, 255)),
            (f"min_speed  {pc['min_speed']:.2f}  (Left/Right)", (255, 255, 255)),
            (f"window     {pc['window_s']:.2f}s ([ / ])", (255, 255, 255)),
            (f"above shoulder: {'on' if pc['above_shoulder'] else 'off'}  (A)", (255, 255, 255)),
            (f"rocket from: {rules['rocket_from']}  (B)", (255, 255, 255)),
            (f"auto-unlock: {'on' if self.auto_unlock else 'off'}  (U)", (255, 255, 255)),
            ("S save   K skeleton   R restart   H hide", DIM),
        ]
        if not self.show_panel:
            lines = [("H = tuning panel", DIM)]
        f = r.small_font
        lh = f.get_height() + 2
        pw, ph = 370, lh * len(lines) + 16
        px, py = self.size[0] - pw - 12, self.size[1] - ph - 60
        panel = pygame.Surface((pw, ph), pygame.SRCALPHA)
        panel.fill(PANEL)
        surf.blit(panel, (px, py))
        for i, (text, color) in enumerate(lines):
            surf.blit(f.render(text, True, color), (px + 10, py + 8 + i * lh))

        # live punch meters per player (bottom left): bar fills to 2x the threshold,
        # the white tick is the threshold; green = this motion would count.
        if self.vision:
            y = self.size[1] - 70
            for s in self.tracker.slots:
                if not s.active:
                    continue
                color = PLAYER_COLORS[s.index % 3]
                det = self.punchers[s.index]
                label = f.render(f"P{s.index + 1}  punches {self.punches[s.index]}", True, color)
                block_h = 2 * (lh + 4) + label.get_height()
                y -= block_h + 10
                bg = pygame.Surface((420, block_h + 8), pygame.SRCALPHA)
                bg.fill(PANEL)
                surf.blit(bg, (12, y - 4))
                surf.blit(label, (20, y))
                for j, h in enumerate(det.hands):
                    m = h.best
                    yy = y + label.get_height() + 4 + j * (lh + 4)
                    side = "L" if h.hand.startswith("left") else "R"
                    surf.blit(f.render(side, True, DIM), (20, yy))
                    self._bar(surf, 42, yy + 4, 160, lh - 8, m.rise, pc["min_rise"], "rise")
                    self._bar(surf, 222, yy + 4, 160, lh - 8, m.speed, pc["min_speed"], "speed")
                    if pc["above_shoulder"]:
                        dot = GOOD if m.above else (255, 110, 110)
                        pygame.draw.circle(surf, dot, (396, yy + lh // 2), 6)

        if now < self.msg_until:
            t = r.hud_font.render(self.msg, True, GOLD)
            surf.blit(t, t.get_rect(center=(self.size[0] // 2, int(self.size[1] * 0.3))))

    def _bar(self, surf, x, y, w, h, value, threshold, name):
        pygame.draw.rect(surf, (50, 54, 72), (x, y, w, h), border_radius=4)
        frac = min(1.0, value / (2 * threshold)) if threshold > 0 else 0
        ok = value >= threshold
        pygame.draw.rect(surf, GOOD if ok else (230, 180, 70), (x, y, int(w * frac), h), border_radius=4)
        tx = x + w // 2
        pygame.draw.line(surf, (255, 255, 255), (tx, y - 3), (tx, y + h + 3), 2)
        t = self.renderer.small_font.render(f"{name} {value:.1f}", True, (240, 240, 245))
        t = pygame.transform.smoothscale(t, (int(t.get_width() * 0.7), int(t.get_height() * 0.7)))
        surf.blit(t, (x + 4, y + (h - t.get_height()) // 2))


def main() -> int:
    bank = WordBank()
    argv = sys.argv[1:]
    if "--mic" not in argv:
        argv = ["--no-mic"] + argv
    if "--player" not in argv:
        argv += ["--player", "P1:k1", "--player", "P2:letters"]
    args = parse_args(bank, ["--gentle"] + argv)
    return Playground(args, config.load(), bank).run()


if __name__ == "__main__":
    sys.exit(main())
