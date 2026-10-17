"""Settings screen (for grown-ups): keyboard or mouse.

Up/Down pick a row, Left/Right change it, Esc/Enter go back. Mouse: click a row, click the
left/right side of its value (or use the wheel) to change it. Every change is saved to
settings.toml right away; camera and mic changes restart those devices after a short pause.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import pygame

from .. import config
from .menu import PANEL, shade, title
from .mic_meter import draw_mic_meter
from .render import GOLD, WHITE, Renderer

DIM = (170, 175, 195)
SECTION = (120, 200, 255)


@dataclass
class Item:
    label: str
    section: str               # settings.toml section to save into ("" = header row)
    key: str
    options: list              # [(value, display text)]
    restart: str = ""          # "camera" | "mic" | ""
    note: str = ""

    def index_of(self, value: Any) -> int:
        for i, (v, _) in enumerate(self.options):
            if v == value or (isinstance(v, float) and isinstance(value, (int, float)) and abs(v - value) < 1e-6):
                return i
        return -1


def header(text: str) -> Item:
    return Item(text, "", "", [])


def steps(lo: float, hi: float, step: float, fmt: str = "{:.1f}") -> list:
    out, v = [], lo
    while v <= hi + 1e-9:
        out.append((round(v, 3), fmt.format(v)))
        v += step
    return out


ON_OFF = [(True, "on"), (False, "off")]


def _models():
    return config.ROOT / "models"


class SettingsScreen:
    def __init__(self, app):
        self.app = app
        self.r: Renderer = app.renderer
        self.w, self.h = app.size
        self.sel = 1
        self.scroll = 0
        self.items = self._build()
        self.rows: list[tuple[pygame.Rect, int]] = []  # clickable rows on screen

    # ---- what can be changed -----------------------------------------------------

    def _build(self) -> list[Item]:
        from ..speech.service import list_input_devices
        cameras = [("", "Auto (prefer USB webcam)")]
        try:
            import cv2

            from ..vision.camera_select import list_cameras, rank
            api = cv2.CAP_DSHOW if __import__("sys").platform == "win32" else cv2.CAP_V4L2
            cameras += [(c.name, c.name) for c in list_cameras(api) if rank(c) is not None]
        except Exception as e:  # camera listing is best effort
            print("camera list failed:", e)
        try:
            mics = [("", "System default")] + [(n, n) for _, n in list_input_devices()]
        except Exception as e:
            print("mic list failed:", e)
            mics = [("", "System default")]
        return [
            header("CAMERA"),
            Item("Camera", "camera", "name", cameras, "camera",
                 "the laptop camera sees wider than the C270"),
            Item("Picture size", "camera", "size",
                 [((640, 360), "640 x 360 (fast)"), ((960, 540), "960 x 540"), ((1280, 720), "1280 x 720 (sharp, slower)")],
                 "camera"),
            Item("Exposure", "camera", "exposure",
                 [("auto", "auto")] + [(v, f"{v}  ({'brighter, slower' if v > -5 else 'darker, faster'})")
                                       for v in (-3, -4, -5, -6, -7)], "camera",
                 "auto can drop to ~15 fps in a dim room"),
            Item("Pose model", "pose", "yolo_model",
                 [(str(_models() / f"yolo11{m}-pose.pt"), label) for m, label in
                  (("x", "YOLO extra large (best)"), ("l", "YOLO large"), ("m", "YOLO medium"),
                   ("s", "YOLO small"), ("n", "YOLO nano (fastest)"))],
                 "camera", note="all run on the GPU; x was steadiest and still ~16 ms per frame"),
            Item("Smoothing", "pose", "smoothing",
                 [("off", "off"), ("low", "low"), ("medium", "medium"), ("high", "high (steadiest)")],
                 note="steadier skeletons, hats and hand rings (punches still use the raw pose)"),
            Item("Lock players for the round", "pose", "lock_players", ON_OFF,
                 note="only the kids there at the start play; anyone walking through is grey"),
            Item("Ignore grown-ups", "pose", "ignore_grownups", ON_OFF,
                 note="grown-ups (smaller head next to their shoulders) never get a player colour"),
            Item("Grown-up cutoff", "pose", "grownup_ratio",
                 [(0.48, "0.48 (only clear grown-ups)"), (0.5, "0.50"), (0.53, "0.53"), (0.56, "0.56 (older kids too)")],
                 note="head width / shoulder width; F3 in a game shows each person's number"),
            Item("Person tracker", "pose", "tracker",
                 [("botsort", "BoT-SORT (remembers looks)"), ("bytetrack", "ByteTrack (older)")], "camera"),
            header("MICROPHONE"),
            Item("Microphone", "speech", "device", mics, "mic"),
            Item("Speech model", "speech", "model",
                 [(str(_models() / "vosk-model-en-us-0.22-lgraph"), "accurate (best for kids)"),
                  (str(_models() / "vosk-model-small-en-us-0.15"), "fast (for Raspberry Pi)")], "mic",
                 note="the accurate model hears kids' voices much better"),
            Item("Whisper second opinion", "speech", "second_opinion", ON_OFF, "mic",
                 note="when the fast listener can't place a word, Whisper (GPU) tries - helps kids' voices"),
            Item("Whisper strictness", "speech", "choice_floor",
                 [(-1.6, "strict (fewer mistakes)"), (-2.0, "balanced"), (-2.5, "forgiving (catches more)")], "mic"),
            Item("Save unheard speech", "speech", "save_misses", ON_OFF, "mic",
                 note="saves clips it couldn't understand to logs/audio (for tuning) - kids' voices!"),
            Item("Listen for", "speech", "grammar",
                 [("screen", "only the words on screen (best)"), ("level", "every word in their levels")],
                 note="on-screen only is much more accurate for kids"),
            Item("React to partial words", "speech", "use_partials", ON_OFF, "mic",
                 "on = faster, off = waits until the word is finished"),
            header("GAME"),
            Item("Round ends", "rules", "round_end",
                 [("time", "after a few minutes"), ("words", "after a number of words"),
                  ("level", "when the level is mastered"), ("lives", "only when lives run out")],
                 note="a round can be won! (race mode: first to the goal wins)"),
            Item("Words per round", "rules", "round_words", [(n, str(n)) for n in (5, 10, 15, 20, 25, 30, 40, 50)],
                 note="per kid; team up adds them together"),
            Item("Minutes per round", "rules", "round_minutes", [(n, f"{n} min") for n in (1, 2, 3, 4, 5, 7, 10)]),
            Item("Lives", "rules", "lives", [(n, str(n)) for n in range(1, 10)]),
            Item("Default attack", "rules", "style", [("punch", "punch (rockets)"), ("slice", "slice (swipe)")],
                 note="the kids can also switch it on the mode screen"),
            Item("Starting speed", "difficulty", "start_fall",
                 [(0.035, "slow"), (0.055, "normal"), (0.08, "fast"), (0.11, "very fast")],
                 note="speeds up by itself when they read fast"),
            Item("Words on screen (per lane)", "difficulty", "max_on_screen", [(n, str(n)) for n in range(1, 6)]),
            Item("Times through to level up", "rules", "mastery_hits", [(n, str(n)) for n in range(1, 5)],
                 note="read every word on the level this many times in one session, without losing a life"),
            Item("Letters: any sound counts", "rules", "letters_easy", ON_OFF),
            Item("Glove launches from", "rules", "rocket_from", [("bottom", "the floor"), ("fist", "the fist")]),
            Item("Power-ups", "rules", "powerups", ON_OFF, note="golden x2, freeze, and giant gloves words"),
            header("PUNCH"),
            Item("How far to punch up", "punch", "min_rise", steps(0.3, 2.0, 0.1),
                 note="in shoulder-widths; lower = easier"),
            Item("How fast to punch", "punch", "min_speed", steps(1.0, 8.0, 0.25, "{:.2f}"),
                 note="lower = easier"),
            Item("Fist must end above shoulder", "punch", "above_shoulder", ON_OFF),
            Item("Slice: swipe speed", "punch", "slice_speed", steps(2.0, 10.0, 0.5),
                 note="slice mode; lower = easier (shoulder-widths per second)"),
            header("MENUS"),
            Item("Pick buttons by", "menu", "select",
                 [("palm", "open palm (raise hand, open it)"), ("hover", "holding a hand still")],
                 note="open palm: hands resting near buttons won't press them by accident"),
            Item("Open palm hold time", "menu", "palm_hold_s", [(0.2, "0.2 s"), (0.4, "0.4 s"), (0.7, "0.7 s"),
                                                               (1.0, "1 s")]),
            header("DISPLAY & SOUND"),
            Item("Show skeletons", "game", "skeletons", ON_OFF, note="each kid's body drawn in their color"),
            Item("Sound volume", "game", "volume", [(v, f"{v}%") for v in range(0, 101, 10)]),
            Item("Voice volume", "voice", "volume", [(v, f"{v}%") for v in range(0, 101, 10)]),
            Item("Music volume", "game", "music", [(v, f"{v}%") for v in range(0, 101, 10)]),
            Item("Read missed words aloud", "voice", "read_missed", ON_OFF),
            Item("Start fullscreen", "game", "fullscreen", ON_OFF),
            Item("Show debug info", "game", "debug", ON_OFF),
        ]

    def _get(self, item: Item):
        cfg = self.app.cfg
        if item.section == "camera" and item.key == "size":
            return (cfg["camera"]["width"], cfg["camera"]["height"])
        return cfg[item.section].get(item.key)

    def _set(self, item: Item, value) -> None:
        cfg = self.app.cfg
        if item.section == "camera" and item.key == "size":
            cfg["camera"]["width"], cfg["camera"]["height"] = value
            config.save_user("camera", "width", value[0])
            config.save_user("camera", "height", value[1])
        else:
            cfg[item.section][item.key] = value
            config.save_user(item.section, item.key, value)
        self.app.on_setting_changed(item.section, item.key, item.restart)

    # ---- input ---------------------------------------------------------------------

    def _move(self, d: int) -> None:
        i = self.sel
        while True:
            i = (i + d) % len(self.items)
            if self.items[i].section:
                self.sel = i
                return

    def _change(self, d: int) -> None:
        item = self.items[self.sel]
        if not item.options:
            return
        i = item.index_of(self._get(item))
        i = (0 if d > 0 else len(item.options) - 1) if i < 0 else max(0, min(len(item.options) - 1, i + d))
        value = item.options[i][0]
        if value != self._get(item):
            self._set(item, value)

    def handle_key(self, e) -> bool:
        """Returns True when leaving the screen."""
        if e.key in (pygame.K_ESCAPE, pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_s):
            return True
        if e.key == pygame.K_UP:
            self._move(-1)
        elif e.key == pygame.K_DOWN:
            self._move(1)
        elif e.key in (pygame.K_LEFT, pygame.K_RIGHT):
            self._change(1 if e.key == pygame.K_RIGHT else -1)
        return False

    def handle_click(self, pos, button: int = 1) -> bool:
        if self.back_rect.collidepoint(pos):
            return True
        for rect, i in self.rows:
            if rect.collidepoint(pos):
                self.sel = i
                if button in (4, 5):  # wheel
                    self._change(1 if button == 4 else -1)
                elif pos[0] > rect.left + rect.width * 0.55:
                    self._change(1 if pos[0] > rect.left + rect.width * 0.8 else -1)
        return False

    def handle_wheel(self, dy: int) -> None:
        self._move(-1 if dy > 0 else 1)

    # ---- drawing -------------------------------------------------------------------

    def draw(self, surface: pygame.Surface, now: float) -> None:
        r, app = self.r, self.app
        shade(surface, 150)
        title(surface, r, "Settings", 52)
        status = []
        if app.vision:
            status.append(f"camera: {app.vision.camera_name or 'starting...'}   pose {app.pose_fps():.0f} fps")
        if app.pending_restart:
            status.append("applying...")
        t = r.small_font.render("   ".join(status), True, GOLD)
        surface.blit(t, t.get_rect(center=(self.w // 2, 104)))

        panel = pygame.Rect(60, 125, self.w - 120, self.h - 200)
        p = pygame.Surface(panel.size, pygame.SRCALPHA)
        p.fill(PANEL)
        surface.blit(p, panel)
        row_h = 34
        visible = (panel.height - 16) // row_h
        if self.sel < self.scroll + 1:
            self.scroll = max(0, self.sel - 1)
        elif self.sel >= self.scroll + visible:
            self.scroll = self.sel - visible + 1
        self.rows = []
        y = panel.top + 8
        for i in range(self.scroll, min(len(self.items), self.scroll + visible)):
            item = self.items[i]
            rect = pygame.Rect(panel.left + 10, y, panel.width - 20, row_h - 2)
            if not item.section:
                surface.blit(r.small_font.render(item.label, True, SECTION), (rect.left + 6, y + 5))
            else:
                selected = i == self.sel
                if selected:
                    pygame.draw.rect(surface, (60, 70, 120), rect, border_radius=8)
                surface.blit(r.small_font.render(item.label, True, WHITE if selected else DIM),
                             (rect.left + 22, y + 5))
                cur = self._get(item)
                idx = item.index_of(cur)
                text = item.options[idx][1] if idx >= 0 else str(cur)
                vx = rect.left + int(rect.width * 0.48)
                val = r.small_font.render(f"<  {text}  >" if selected else text, True, GOLD if selected else WHITE)
                if val.get_width() > rect.right - vx - 10:
                    val = pygame.transform.smoothscale(val, (rect.right - vx - 10, val.get_height()))
                surface.blit(val, (vx, y + 5))
                if item.key == "device" and app.speech:
                    draw_mic_meter(surface, pygame.Rect(rect.right - 170, y + 9, 150, 14),
                                   app.speech.level, app.speech.peak)
                self.rows.append((rect, i))
            y += row_h

        note = self.items[self.sel].note
        lines = [note] if note else []
        lines.append("Up/Down pick   Left/Right change   Esc done   (saved automatically)")
        for j, line in enumerate(lines):
            t = r.small_font.render(line, True, GOLD if (note and j == 0) else DIM)
            surface.blit(t, t.get_rect(center=(self.w // 2, panel.bottom + 18 + j * 26)))
        self.back_rect = pygame.Rect(self.w - 150, 30, 110, 46)
        pygame.draw.rect(surface, (90, 100, 160), self.back_rect, border_radius=12)
        b = r.small_font.render("Done", True, WHITE)
        surface.blit(b, b.get_rect(center=self.back_rect.center))
