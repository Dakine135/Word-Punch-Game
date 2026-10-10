"""Word Punch main loop: wires camera/pose, mic/speech, keyboard/mouse into the Game."""
from __future__ import annotations

import argparse
import random
import time
from collections import deque

import pygame

from . import config
from .game.core import MODES, Game
from .profiles import Profile, ProfileStore, apply_to_track, update_from_game
from .ui import display
from .ui.camera_view import CameraView
from .ui.effects import Effects
from .ui.menu import Button, Menu, Pointers, draw_button, update_buttons
from .ui.mic_meter import draw_mic_meter
from .ui.render import GOLD, PLAYER_COLORS, Renderer
from .ui.settings import SettingsScreen
from .ui.skeleton import SkeletonLayer
from .ui.sfx import Sfx
from .voice import Voice, spoken
from .words import WordBank

HELP = """With no --player, a start screen lets the kids pick their names (saved profiles).
Players are NAME:LEVEL. Levels: letters k1 k2 k3 k4 g1q1 g1q2 g1q3 g1q4
Examples:
  python -m word_punch                                   (start screen)
  python -m word_punch --player Sam:k3 --player Max:letters
  python -m word_punch --mode coop --gentle --player Sam:k2 --player Max:letters
  python -m word_punch --sim          (no camera/mic: type a word + Enter to say it, click to punch)
Keys: Esc = back to the start screen (quits from there), F11 / Alt+Enter fullscreen,
      F3 debug info, F2 pause, Enter = play again, M = menu after a game.
"""


def parse_args(bank: WordBank, argv=None):
    ap = argparse.ArgumentParser(prog="word_punch", epilog=HELP,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=MODES, default="split")
    ap.add_argument("--player", action="append", metavar="NAME:LEVEL",
                    help="repeat for each player (1-3)")
    ap.add_argument("--gentle", action="store_true", help="no lives; missed words come back")
    ap.add_argument("--lives", type=int)
    ap.add_argument("--letters-easy", action="store_true", help="any sound unlocks a letter")
    ap.add_argument("--sim", action="store_true", help="no camera and no mic")
    ap.add_argument("--no-camera", action="store_true", help="mouse clicks punch")
    ap.add_argument("--no-mic", action="store_true", help="type words + Enter to say them")
    ap.add_argument("--mic", help="mic name substring (overrides settings)")
    ap.add_argument("--fullscreen", action="store_true", help="start fullscreen")
    ap.add_argument("--windowed", action="store_true", help="start in a window (overrides settings)")
    ap.add_argument("--debug", action="store_true", help="show fps / heard words")
    ap.add_argument("--quit-after", type=float, metavar="SECONDS",
                    help="exit after this long and print performance stats (benchmarking)")
    args = ap.parse_args(argv)
    args.use_menu = not args.player
    players = args.player or ["Player 1:k2", "Player 2:letters"]
    args.names, args.levels = [], []
    for spec in players[:3]:
        name, _, level = spec.rpartition(":")
        if level not in bank.levels:
            ap.error(f"unknown level {level!r} in {spec!r}")
        args.names.append(name or f"Player {len(args.names) + 1}")
        args.levels.append(level)
    if args.sim:
        args.no_camera = args.no_mic = True
    return args


class App:
    def __init__(self, args, cfg: dict, bank: WordBank):
        self.args, self.cfg, self.bank = args, cfg, bank
        if args.gentle:
            cfg["rules"]["gentle"] = True
        if args.lives:
            cfg["rules"]["lives"] = args.lives
        if args.letters_easy:
            cfg["rules"]["letters_easy"] = True
        if args.mic:
            cfg["speech"]["device"] = args.mic

        pygame.init()
        fullscreen = (args.fullscreen or cfg["game"]["fullscreen"]) and not args.windowed
        self.size = (cfg["game"]["width"], cfg["game"]["height"])
        self.screen = display.open_window(self.size, fullscreen, "Word Punch")
        self.renderer = Renderer(self.size)
        self.effects = Effects()
        self.sfx = Sfx()
        self.sfx.set_volume(cfg["game"].get("volume", 100))
        self.voice = Voice(cfg["voice"])
        self.debug = args.debug or cfg["game"].get("debug", False)
        self.pending_restart: dict[str, float] = {}
        self.skeletons = SkeletonLayer(self.size)
        self.blades: dict = {}        # (who, hand) -> deque[(t, x, y, player)] trail points
        self._last_hand: dict = {}    # (slot, hand) -> (t, x, y, scale) normalized, for swipe speed
        self._last_mouse = None       # (t, x, y) while a button is held
        self.mouse_moved_at = 0.0
        self._cursor_visible = None
        self.settings_screen: SettingsScreen | None = None
        self.show_typing = True  # the "say:" box when there's no mic
        self.paused = False
        self.typed = ""
        self.heard_log: deque = deque(maxlen=8)
        self.hands: list[tuple[int, int, int]] = []

        self.vision = self.speech = None
        self.view = CameraView(self.size, (cfg["camera"]["width"], cfg["camera"]["height"]), dim=0.35)
        self.pose_times: deque = deque(maxlen=60)
        if not args.no_camera:
            self.start_vision()
        self.store = ProfileStore()
        self.player_profiles: list[Profile | None] = [None] * len(args.names)
        self.frame_punches: list[tuple[int, int]] = []
        self.frame_clicks: list[tuple[int, int]] = []
        self.frame_keys: list = []
        self.over_buttons: list[Button] = []
        self.menu = Menu(self.renderer, self.size, self.store, bank, gentle=cfg["rules"]["gentle"],
                         style=cfg["rules"].get("style", "punch"))
        self.state = "menu" if args.use_menu else "playing"
        self.new_game()
        self._update_cursor()
        if not args.no_mic:
            self.start_speech()

    # ---- devices (restartable from the settings screen) ------------------------------

    def start_vision(self) -> None:
        from .vision.punch import PunchDetector
        from .vision.service import VisionService
        from .vision.tracker import Tracker
        cam = self.cfg["camera"]
        self.vision = VisionService(self.cfg)
        self.vision.start()
        self.view = CameraView(self.size, (cam["width"], cam["height"]), dim=0.35)
        self.tracker = Tracker(3)
        self.punchers = [PunchDetector(self.cfg["punch"]) for _ in range(3)]
        self.pose_times.clear()

    def start_speech(self) -> None:
        from .speech.service import SpeechService
        self.speech = SpeechService(self.cfg["speech"])
        self._vocab = self.game.vocab()
        self.speech.start(self._vocab)

    def pose_fps(self) -> float:
        now = time.time()
        return sum(1 for t in self.pose_times if now - t < 1)

    def on_setting_changed(self, section: str, key: str, restart: str) -> None:
        """Called by the settings screen after it changed (and saved) a value."""
        if restart:
            self.pending_restart[restart] = time.time() + 0.8  # wait for the parent to stop clicking
        if section == "voice" and key == "volume":
            self.voice.set_volume(self.cfg["voice"]["volume"])
            self.speak("Great job!")
        elif section == "game" and key == "volume":
            self.sfx.set_volume(self.cfg["game"]["volume"])
            self.sfx.play("unlock")
        elif section == "game" and key == "debug":
            self.debug = self.cfg["game"]["debug"]

    def apply_restarts(self, now: float) -> None:
        for what, at in list(self.pending_restart.items()):
            if now < at:
                continue
            del self.pending_restart[what]
            if what == "camera" and not self.args.no_camera:
                if self.vision:
                    self.vision.stop()
                self.start_vision()
            elif what == "mic" and not self.args.no_mic:
                if self.speech:
                    self.speech.stop(wait=False)
                self.start_speech()

    def new_game(self):
        self.game = Game(mode=self.args.mode, player_names=self.args.names,
                         player_levels=self.args.levels, bank=self.bank, cfg=self.cfg,
                         size=self.size, measure=self.renderer.measure, now=time.time())
        for i, prof in enumerate(self.player_profiles):
            track = self.game.track_for(i)
            if prof and track:
                apply_to_track(prof, track)
        self.game_started = time.time()
        self.over_at = None
        self.saved_final = False
        self.prepare_voice()
        self.over_buttons = []
        if self.speech:
            self._sync_vocab()

    def prepare_voice(self) -> None:
        """Make sure every word that can appear this game has a voice clip (background)."""
        texts = []
        for key in self.game.levels_in_play():
            lvl = self.bank.level(key)
            texts += [spoken(w, lvl.is_letters) for w in lvl.words]
        self.voice.prepare(texts + PHRASES)

    def speak(self, *texts: str) -> None:
        """Say something and keep the mic from hearing it."""
        seconds = self.voice.say(*texts)
        if seconds and self.speech:
            self.speech.mute(seconds + 0.3)

    def start_from_menu(self, req: dict) -> None:
        profiles = req["profiles"]
        self.args.mode = req["mode"]
        self.args.names = [p.name for p in profiles]
        self.args.levels = [p.level for p in profiles]
        self.cfg["rules"]["gentle"] = req["gentle"]
        self.cfg["rules"]["style"] = req.get("style", self.style)
        self.player_profiles = list(profiles)
        self.effects = Effects()
        self.new_game()
        self.state = "playing"

    def to_menu(self) -> None:
        self.save_progress(finished=True)
        self.menu.reset()
        self.state = "menu"

    def save_progress(self, finished: bool) -> None:
        """Write each kid's progress to their profile (once per game when finished)."""
        if finished and self.saved_final:
            return
        for i, prof in enumerate(self.player_profiles):
            if prof is None or i >= len(self.game.players):
                continue
            info = {"mode": self.game.mode, "style": self.cfg["rules"].get("style", "punch"),
                    "game": getattr(self.game, "kind", "classic"),
                    "minutes": round((time.time() - self.game_started) / 60, 1),
                    "result": self.game.result or "quit",
                    "stars": self.stars_for(i) if hasattr(self, "stars_for") else 0}
            update_from_game(prof, self.game.track_for(i), self.game.players[i], finished, self.game, info)
            self.store.save(prof)
        if finished:
            self.saved_final = True

    def _sync_vocab(self):
        if self.cfg["speech"].get("grammar", "screen") == "screen":
            vocab = self.game.screen_vocab()
            if not vocab:
                return  # nothing to read right now; keep listening for the last words
        else:
            vocab = self.game.vocab()
        if vocab != getattr(self, "_vocab", None):
            self._vocab = vocab
            self.speech.set_vocab(vocab)

    # ---- input ---------------------------------------------------------------------

    def handle_events(self, now: float) -> bool:
        self.frame_clicks, self.frame_keys = [], []
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                return False
            if e.type == pygame.MOUSEMOTION:
                self.mouse_moved_at = now
                if (self.state == "playing" and self.style == "slice" and not self.game.over
                        and any(e.buttons)):
                    self._mouse_slice(e, now)
            if e.type == pygame.KEYDOWN and display.is_toggle_key(e):
                display.toggle_fullscreen()
                self._update_cursor()
                continue
            if e.type == pygame.KEYDOWN and e.key == pygame.K_F3:
                self.debug = not self.debug
                continue
            if self.state == "menu" and self.menu.screen == "settings":
                if self.settings_screen is None:
                    self.settings_screen = SettingsScreen(self)
                done = False
                if e.type == pygame.KEYDOWN:
                    done = self.settings_screen.handle_key(e)
                elif e.type == pygame.MOUSEBUTTONDOWN and e.button in (1, 3):
                    done = self.settings_screen.handle_click(e.pos, e.button)
                elif e.type == pygame.MOUSEWHEEL:
                    self.settings_screen.handle_wheel(e.y)
                if done:
                    self.menu.screen = "who"
                    self.settings_screen = None
                continue
            if self.state == "menu":
                if e.type == pygame.KEYDOWN:
                    if e.key == pygame.K_ESCAPE and self.menu.screen != "setup":
                        if self.menu.screen == "who":
                            return False
                        self.menu.screen = "who"
                    else:
                        self.frame_keys.append(e)
                elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                    self.frame_clicks.append(e.pos)
                continue
            if e.type == pygame.KEYDOWN:
                if self.on_key(e, now):
                    continue
                if e.key == pygame.K_ESCAPE:
                    if self.args.use_menu:
                        self.to_menu()
                        continue
                    return False
                if e.key == pygame.K_m and self.game.over and self.args.use_menu:
                    self.to_menu()
                elif e.key == pygame.K_F3:
                    self.debug = not self.debug
                elif e.key == pygame.K_F2:
                    self.paused = not self.paused
                elif e.key == pygame.K_RETURN:
                    if self.game.over:
                        self.new_game()
                    elif self.typed:
                        self.say(self.typed, now)
                        self.typed = ""
                elif e.key == pygame.K_BACKSPACE:
                    self.typed = self.typed[:-1]
                elif e.unicode and (e.unicode.isalpha() or e.unicode == "'"):
                    self.typed += e.unicode
            if e.type == pygame.MOUSEBUTTONDOWN and e.button in (1, 3, 2):
                if self.game.over:
                    self.frame_clicks.append(e.pos)
                    continue
                if self.style == "slice":
                    self._last_mouse = (now, *e.pos)
                    continue
                player = {1: 0, 3: 1, 2: 2}[e.button]
                self.game.punch(player, e.pos[0], now, e.pos[1])
        return True

    def _mouse_slice(self, e, now: float) -> None:
        """Drag with a mouse button held to slice (left = player 1, right = 2, middle = 3)."""
        player = 0 if e.buttons[0] else 1 if e.buttons[2] else 2
        if self._last_mouse is None:
            self._last_mouse = (now, *e.pos)
            return
        t0, x0, y0 = self._last_mouse
        x1, y1 = e.pos
        self._last_mouse = (now, x1, y1)
        dt = max(now - t0, 1e-3)
        speed = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5 / dt
        if speed > 600:
            self._blade(("mouse", player), now, x1, y1, player)
        if speed > 1200:
            self.game.slice(player, x0, y0, x1, y1, now)

    def _update_cursor(self):
        """Mouse pointer: always in menus; during play (fullscreen + camera) only after it moves."""
        playing = self.state == "playing" and not self.game.over and not self.paused
        hide = playing and self.vision and display.is_fullscreen() and time.time() - self.mouse_moved_at > 2.5
        if self._cursor_visible != (not hide):
            self._cursor_visible = not hide
            pygame.mouse.set_visible(not hide)

    @property
    def style(self) -> str:
        return self.cfg["rules"].get("style", "punch")

    def _blade(self, key, t, x, y, player) -> None:
        trail = self.blades.setdefault(key, deque(maxlen=12))
        trail.append((t, x, y, player))

    def _hand_point(self, person, hand: str):
        """Roughly where the fist is: a bit past the wrist, along the forearm."""
        wrist = person.get(hand, 0.4)
        if wrist is None:
            return None
        elbow = person.get(hand.replace("wrist", "elbow"), 0.3)
        if elbow is None:
            return wrist.x, wrist.y
        return wrist.x + (wrist.x - elbow.x) * 0.3, wrist.y + (wrist.y - elbow.y) * 0.3

    def _slice_from_pose(self, slot, t: float, now: float) -> None:
        """Turn a fast hand movement into a slice (slice style only)."""
        person = slot.person
        for hand in ("left_wrist", "right_wrist"):
            key = (slot.index, hand)
            pt = self._hand_point(person, hand) if person else None
            prev = self._last_hand.get(key)
            if pt is None:
                self._last_hand.pop(key, None)
                continue
            self._last_hand[key] = (t, pt[0], pt[1], person.scale)
            if prev is None or not (0 < t - prev[0] < 0.3):
                continue
            speed = ((pt[0] - prev[1]) ** 2 + (pt[1] - prev[2]) ** 2) ** 0.5 / person.scale / (t - prev[0])
            x0, y0 = self.view.to_screen(prev[1], prev[2])
            x1, y1 = self.view.to_screen(*pt)
            player = self.game.lane_at((x0 + x1) / 2).players[0] if self.game.mode == "split" else slot.index
            threshold = self.cfg["punch"].get("slice_speed", 5.0)
            if speed >= threshold * 0.6:
                if not self.blades.get(key) or now - self.blades[key][-1][0] > 0.3:
                    self._blade(key, now, x0, y0, player)
                self._blade(key, now, x1, y1, player)
            if speed >= threshold:
                self.game.slice(slot.index, x0, y0, x1, y1, now)

    def draw_skeletons(self, surf: pygame.Surface) -> None:
        if not (self.vision and self.cfg["game"].get("skeletons", True)):
            return
        self.skeletons.begin()
        for s in self.tracker.slots:
            if not s.person:
                continue
            idx = s.index
            if self.state == "playing" and self.game.mode == "split":
                x, _ = self.view.to_screen(s.person.center_x, 0.5)
                idx = self.game.lane_at(x).players[0]
            self.skeletons.add(self.view, s.person, PLAYER_COLORS[idx % 3])
        self.skeletons.end(surf)

    # ---- hooks for tools that extend the game (e.g. tools/punch_playground.py) -------

    def on_key(self, e, now: float) -> bool:
        """Return True if the key was handled."""
        return False

    def after_update(self, now: float) -> None:
        pass

    def draw_overlay(self, surf: pygame.Surface, now: float) -> None:
        pass

    def say(self, word: str, now: float):
        self.heard_log.append(word)
        target = self.game.heard(word, now)
        self.log_speech("heard", word, target)

    def log_speech(self, kind: str, token: str, target) -> None:
        """logs/game_<time>.csv: what was heard, what it unlocked, what was on screen."""
        if getattr(self, "_speech_log", None) is None:
            import csv
            from .config import ROOT
            (ROOT / "logs").mkdir(exist_ok=True)
            path = ROOT / "logs" / f"game_{time.strftime('%Y%m%d_%H%M%S')}.csv"
            self._speech_log_file = open(path, "w", newline="", encoding="utf-8")
            self._speech_log = csv.writer(self._speech_log_file)
            self._speech_log.writerow(["time", "event", "heard", "unlocked", "locked_on_screen", "players"])
        on_screen = " ".join(w.text for w in self.game.words if not w.unlocked)
        players = " ".join(f"{p.name}:{lvl}" for p, lvl in zip(self.game.players, self.args.levels))
        self._speech_log.writerow([time.strftime("%H:%M:%S"), kind, token,
                                   target.text if target else "", on_screen, players])
        self._speech_log_file.flush()

    def poll_speech(self, now: float):
        if not self.speech:
            return
        from .speech.service import Heard, Voice
        for ev in self.speech.poll():
            if isinstance(ev, Heard):
                self.say(ev.word, now)
            elif isinstance(ev, Voice):
                self.heard_log.append("?")
                self.game.voice(now)
                if self.state == "playing":
                    self.log_speech("sound", "?", None)

    def poll_vision(self, now: float):
        if not self.vision:
            return
        self.hands = []
        self.frame_punches = []
        playing = self.state == "playing" and not self.game.over
        for t, people in self.vision.poll():
            self.pose_times.append(t)
            slots = self.tracker.update(people, t)
            for s in slots:
                if playing and self.style == "slice":
                    self._slice_from_pose(s, t, now)
                for p in self.punchers[s.index].update(s.person, t):
                    x, y = self.view.to_screen(p.x, p.y)
                    self.frame_punches.append((x, y))
                    if not playing or self.style == "slice":
                        continue
                    player = self.game.lane_at(x).players[0] if self.game.mode == "split" else s.index
                    color = PLAYER_COLORS[player % 3]
                    self.effects.ring(x, y, color, r0=20, r1=110, life=0.3, width=10)
                    self.effects.sparkle(x, y, color, 16)
                    self.game.punch(s.index, x, now, y)
        for s in self.tracker.slots:
            if not s.person:
                continue
            for hand in ("left_wrist", "right_wrist"):
                kp = s.person.get(hand, 0.4)
                if kp:
                    x, y = self.view.to_screen(kp.x, kp.y)
                    player = s.index
                    if self.state == "playing" and self.game.mode == "split":
                        player = self.game.lane_at(x).players[0]
                    self.hands.append((player, x, y))

    # ---- events -> effects -----------------------------------------------------------

    def react(self, now: float):
        r, fx = self.renderer, self.effects
        for ev in self.game.drain_events():
            k = ev.kind
            if k == "unlock":
                self.sfx.play("unlock")
                fx.sparkle(ev.x, ev.y, GOLD, 20)
            elif k == "launch":
                self.sfx.play("launch")
                color = PLAYER_COLORS[ev.player % 3]
                fx.ring(ev.x, ev.y, color, r0=10, r1=90, life=0.35, width=8)
                fx.burst(ev.x, ev.y, [(200, 200, 210), color], n=14, speed=260, size=7, life=0.4)
            elif k == "break" and ev.style == "slice":
                self.sfx.play("slash")
                color = PLAYER_COLORS[ev.player % 3]
                w = ev.word
                fx.split(r.block_image(w), ev.x, ev.y, ev.angle)
                import math as _m
                dx, dy = _m.cos(ev.angle) * w.w * 0.7, _m.sin(ev.angle) * w.w * 0.7
                fx.streak(ev.x - dx, ev.y - dy, ev.x + dx, ev.y + dy, color)
                fx.burst(ev.x, ev.y, [color, GOLD, (255, 255, 255)], n=40, speed=450)
                ty = max(ev.y, r.hud_height + w.h * 0.6)
                fx.float_text(random.choice(("SLICE!", "CHOP!", "SWISH!", "NINJA!", "SLASH!")),
                              ev.x, ty, color, r.big_font, life=0.9, rise=30, pop=True)
                fx.float_text(f"+{ev.points}", ev.x, ty + r.big_font.get_height() * 0.8, GOLD,
                              r.pop_font, life=1.2, pop=True)
                fx.shake = 6
            elif k == "break":
                self.sfx.play("break")
                color = PLAYER_COLORS[ev.player % 3]
                w = ev.word
                fx.ring(ev.x, ev.y, (255, 255, 255), r0=w.h * 0.4, r1=w.w * 0.85, life=0.3, width=10)
                fx.ring(ev.x, ev.y, GOLD, r0=w.h * 0.2, r1=w.w * 0.8, life=0.5, width=8)
                fx.debris(ev.x, ev.y, w.w, w.h, [GOLD, (255, 230, 120), (200, 150, 30)])
                fx.burst(ev.x, ev.y, [color, GOLD, (255, 255, 255)], n=50)
                # keep the text below the HUD strip so it's never hidden
                ty = max(ev.y, r.hud_height + w.h * 0.6)
                fx.float_text(random.choice(("POW!", "BAM!", "WHAM!", "BOOM!", "KAPOW!")),
                              ev.x, ty, color, r.big_font, life=0.9, rise=30, pop=True)
                fx.float_text(f"+{ev.points}", ev.x, ty + r.big_font.get_height() * 0.8, GOLD,
                              r.pop_font, life=1.2, pop=True)
                fx.shake = 10
            elif k == "clang":
                self.sfx.play("clang")
                fx.ring(ev.x, ev.y, (190, 200, 230), r0=8, r1=60, life=0.25, width=5)
                fx.sparkle(ev.x, ev.y, (180, 190, 220))
                fx.float_text("Read it first!", ev.x, ev.y + 40, (220, 230, 255), r.small_font, life=1.0)
            elif k == "miss":
                self.sfx.play("miss")
                fx.flash((255, 40, 40))
                if self.cfg["voice"].get("read_missed", True) and ev.word:
                    self.speak(spoken(ev.word.text, ev.word.is_letter))
            elif k == "bounce":
                self.sfx.play("bounce")
            elif k == "say":
                fx.float_text(ev.text, ev.word.x, ev.word.y + 60, (255, 255, 255), r.pop_font, life=1.5)
                if self.cfg["voice"].get("read_missed", True):
                    self.speak("This word says", spoken(ev.word.text, ev.word.is_letter))
            elif k == "levelup":
                self.sfx.play("levelup")
                self.save_progress(finished=False)
                lane = ev.lane
                cx = (lane.x0 + lane.x1) / 2
                fx.float_text("LEVEL UP!", cx, self.size[1] * 0.4, GOLD, r.big_font, life=2.0, rise=20, pop=True)
                fx.float_text(ev.text, cx, self.size[1] * 0.52, (255, 255, 255), r.pop_font, life=2.0, rise=20)
                fx.burst(cx, self.size[1] * 0.4, [GOLD, (255, 255, 255), (255, 120, 200)], n=120, speed=700)
            elif k == "vanish":
                fx.sparkle(ev.x, ev.y, GOLD, 14)
            elif k == "lane_done":
                self.sfx.play("win")
                lane = ev.lane
                cx = (lane.x0 + lane.x1) / 2
                for i in range(4):
                    fx.burst(cx + (i - 1.5) * 90, self.size[1] * 0.35,
                             [GOLD, (255, 255, 255), (255, 120, 200), (120, 220, 255)], n=50, speed=650)
            elif k == "gameover":
                self.sfx.play("win" if ev.text == "complete" else "gameover")
                self.over_at = now
                self.save_progress(finished=True)
        if self.speech:
            self._sync_vocab()

    # ---- main loop -----------------------------------------------------------------

    def draw(self, now: float):
        surf = self.screen
        frame = self.vision.latest_frame() if self.vision else None
        if frame is None:
            surf.fill((18, 22, 44))
        else:
            self.view.draw(surf, frame)
        r = self.renderer
        if self.state == "menu" and self.menu.screen == "settings":
            if self.settings_screen is None:
                self.settings_screen = SettingsScreen(self)
            self.draw_skeletons(surf)
            self.settings_screen.draw(surf, now)
            r.draw_hands(surf, self.hands, now)
            pygame.display.flip()
            return
        if self.state == "menu":
            self.draw_skeletons(surf)
            self.menu.draw(surf, now)
            r.draw_hands(surf, self.hands, now)
            self.effects.draw(surf)
            if self.debug:
                self._draw_debug(surf)
            pygame.display.flip()
            return
        self.draw_skeletons(surf)
        r.draw_background(surf, self.game)
        r.draw_words(surf, self.game, now)
        self.effects.draw(surf)
        r.draw_rockets(surf, self.game, now)
        r.draw_blades(surf, self.blades, now)
        r.draw_hands(surf, self.hands, now)
        r.draw_lane_out(surf, self.game, now)
        r.draw_hud(surf, self.game, now)
        self.effects.draw_texts(surf)
        if now - self.game_started < 12 and not self.game.over:
            r.draw_say_hint(surf, "Read the word out loud, then " +
                            ("SLICE it with a fast swipe!" if self.style == "slice" else "punch up under it!"))
        if self.args.no_mic and self.show_typing:
            t = r.hud_font.render(f"say: {self.typed}_", True, (255, 255, 255))
            surf.blit(t, (14, self.size[1] - t.get_height() - 30))
        self.draw_overlay(surf, now)
        if self.debug:
            self._draw_debug(surf)
        elif self.speech and self.speech.error:
            t = r.small_font.render(self.speech.error + "  (try --mic, or pick one in tools/speech_spike.py)",
                                    True, (255, 120, 120))
            surf.blit(t, (14, self.size[1] - t.get_height() - 70))
        if self.paused:
            t = r.big_font.render("Paused", True, GOLD)
            surf.blit(t, t.get_rect(center=(self.size[0] // 2, self.size[1] // 2)))
        if self.game.over:
            r.draw_game_over(surf, self.game, "")
            for b in self.over_buttons:
                draw_button(surf, r, b, now)
            r.draw_say_hint(surf, "Hold your hand on a button   (Enter = play again" +
                            (", M = menu)" if self.args.use_menu else ")"))
            r.draw_hands(surf, self.hands, now)

        if self.effects.shake > 0:
            import random
            dx, dy = random.randint(-4, 4), random.randint(-4, 4)
            surf.scroll(dx, dy)
        pygame.display.flip()

    def _pointers(self) -> Pointers:
        mouse = pygame.mouse.get_pos() if pygame.mouse.get_focused() else None
        return Pointers(hands=[(x, y) for _, x, y in self.hands], mouse=mouse,
                        clicks=self.frame_clicks, punches=self.frame_punches)

    def step_menu(self, dt: float, now: float) -> None:
        req = self.menu.step(dt, now, self._pointers(), self.frame_keys)
        if req:
            self.start_from_menu(req)

    def step_game_over(self, dt: float, now: float) -> None:
        if not self.over_buttons:
            w, h = self.size
            again_x = w // 2 - 380 if self.args.use_menu else w // 2 - 180
            self.over_buttons = [Button("again", pygame.Rect(again_x, int(h * 0.7), 360, 100),
                                        "Play again", "", (60, 160, 90))]
            if self.args.use_menu:
                self.over_buttons.append(Button("menu", pygame.Rect(w // 2 + 20, int(h * 0.7), 360, 100),
                                                "Menu", "", (90, 100, 160)))
        if now - (self.over_at or now) < 1.5:
            return  # let the results sink in before buttons react
        fired = update_buttons(self.over_buttons, self._pointers(), dt)
        if fired and fired.key == "again":
            self.save_progress(finished=True)
            self.new_game()
        elif fired and fired.key == "menu":
            self.to_menu()

    def _draw_debug(self, surf):
        lines = [f"fps {self.clock.get_fps():.0f}"]
        if self.vision:
            pf = self.pose_fps()
            lines.append(f"camera: {self.vision.camera_name}")
            lines.append(f"pose {pf} fps, {self.vision.pose_ms:.0f} ms" +
                         (f"  ERROR {self.vision.error}" if self.vision.error else ""))
        if self.speech:
            sp = self.speech
            state = sp.error or ("ready" if sp.ready else "starting...")
            lines.append(f"mic: {sp.device_name or cfg_device(self.cfg)} ({state})")
            draw_mic_meter(surf, pygame.Rect(self.size[0] - 320, self.size[1] - 70, 300, 22),
                           sp.level, sp.peak, self.renderer.small_font, "mic level")
        lines.append("heard: " + " ".join(self.heard_log))
        for lane in self.game.lanes:
            d = lane.difficulty
            lines.append(f"lane {lane.index}: fall {d.fall:.3f} interval {d.interval:.1f}s")
        y = self.size[1] - 24 * len(lines) - 70
        for line in lines:
            surf.blit(self.renderer.small_font.render(line, True, (180, 255, 180)), (14, y))
            y += 24

    def run(self) -> int:
        self.clock = pygame.time.Clock()
        last = start = time.time()
        frames = 0
        try:
            while True:
                now = time.time()
                frames += 1
                if self.args.quit_after and now - start > self.args.quit_after:
                    break
                dt = min(now - last, 0.1)
                last = now
                if not self.handle_events(now):
                    break
                self.apply_restarts(now)
                self.voice.update()
                self._update_cursor()
                self.poll_speech(now)
                self.poll_vision(now)
                if self.state == "menu":
                    self.step_menu(dt, now)
                    self.effects.update(dt)
                    self.draw(now)
                    self.clock.tick(self.cfg["game"]["fps"])
                    continue
                if self.game.over:
                    self.step_game_over(dt, now)
                if not self.paused:
                    self.game.update(dt, now)
                    for r in self.game.rockets:
                        self.effects.trail(r.x, r.y + r.radius * 1.2, PLAYER_COLORS[r.player % 3],
                                           size=r.radius * 0.5)
                    self.effects.update(dt)
                self.after_update(now)
                self.react(now)
                self.draw(now)
                self.clock.tick(self.cfg["game"]["fps"])
        finally:
            if self.state == "playing":
                self.save_progress(finished=True)
            if self.args.quit_after:
                elapsed = time.time() - start
                stats = [f"draw {frames / elapsed:.0f} fps"]
                if self.vision:
                    stats.append(f"pose {len(self.pose_times) and sum(1 for t in self.pose_times if time.time() - t < 2) / 2:.0f} fps"
                                 f" ({self.vision.pose_ms:.0f} ms){' ERROR ' + self.vision.error if self.vision.error else ''}")
                if self.speech:
                    stats.append("mic ready" if self.speech.ready else "mic NOT ready")
                print("stats:", ", ".join(stats))
            if self.vision:
                self.vision.stop()
            if self.speech:
                self.speech.stop()
            pygame.quit()
        return 0


PHRASES = ["This word says", "Find", "Great job!", "You did it!", "Round complete!", "Try again!",
           "Oops! That says", "Level up!", "Read the words, then punch!", "Read the words, then slice!"]


def cfg_device(cfg: dict) -> str:
    return cfg["speech"]["device"] or "system default"


def main(argv=None) -> int:
    bank = WordBank()
    args = parse_args(bank, argv)
    return App(args, config.load(), bank).run()
