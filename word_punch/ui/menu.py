"""Start screens kids can drive with their hands: hold a hand over a button (or punch it).

Mouse clicks and the keyboard work too, for grown-ups.

Flow:  Setup (parent, keyboard) <-> Who's playing? -> How to play? -> countdown -> game
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import pygame

from .. import rewards
from ..game.games import KINDS, TITLES, allowed_modes
from ..profiles import Profile, ProfileStore
from ..words import WordBank
from .render import GOLD, PLAYER_COLORS, WHITE, Renderer

HOLD_S = 1.2  # how long a hand must stay on a button
PANEL = (16, 20, 40, 225)
DIM = (170, 175, 195)


@dataclass(eq=False)
class Button:
    key: str
    rect: pygame.Rect
    label: str
    sub: str = ""
    color: tuple = (90, 100, 160)
    selected: bool = False      # toggles (joined player, gentle on, ...)
    enabled: bool = True
    hover: float = 0.0          # seconds a hand has been on it
    latched: bool = False       # just fired; wait until pointers leave
    data: object = None
    mouse_only: bool = False    # grown-up buttons: a click, never a hand hover or punch
    mouse_over: bool = False    # highlight only; the mouse never "holds" a button


@dataclass
class Pointers:
    """Everything that can point this frame (screen coords)."""
    hands: list = field(default_factory=list)    # (x, y)
    mouse: tuple | None = None
    clicks: list = field(default_factory=list)   # (x, y)
    punches: list = field(default_factory=list)  # (x, y)


def update_buttons(buttons: list[Button], ptr: Pointers, dt: float) -> Button | None:
    """Advance hover timers; return the button that fired this frame, if any."""
    fired = None
    for b in buttons:
        if not b.enabled:
            b.hover = 0
            continue
        b.mouse_over = bool(ptr.mouse and b.rect.collidepoint(ptr.mouse))
        if any(b.rect.collidepoint(p) for p in ptr.clicks):
            fired = b
            continue
        if b.mouse_only:
            continue
        inside = [p for p in ptr.hands if b.rect.collidepoint(p)]
        if any(b.rect.collidepoint(p) for p in ptr.punches):
            fired = b
        if not inside:
            b.latched = False
            b.hover = max(0.0, b.hover - dt * 2)
            continue
        if b.latched:
            continue
        b.hover += dt
        if b.hover >= HOLD_S:
            fired = b
    if fired:
        fired.hover, fired.latched = 0.0, True
    return fired


def draw_button(surface: pygame.Surface, r: Renderer, b: Button, now: float, focused: bool = False) -> None:
    rect = b.rect
    base = b.color if b.enabled else (60, 62, 75)
    if b.selected:
        glow = rect.inflate(16, 16)
        g = pygame.Surface(glow.size, pygame.SRCALPHA)
        pygame.draw.rect(g, (*b.color, 120), g.get_rect(), border_radius=28)
        surface.blit(g, glow)
    body = pygame.Surface(rect.size, pygame.SRCALPHA)
    pygame.draw.rect(body, (*base, 235 if b.selected else 190), body.get_rect(), border_radius=22)
    surface.blit(body, rect)
    # hover progress fills from the bottom
    if b.hover > 0:
        frac = min(1.0, b.hover / HOLD_S)
        fill = pygame.Rect(rect.left, rect.bottom - int(rect.height * frac), rect.width, int(rect.height * frac))
        f = pygame.Surface(fill.size, pygame.SRCALPHA)
        f.fill((255, 255, 255, 70))
        surface.blit(f, fill)
    focused = focused or b.mouse_over
    border = WHITE if (b.selected or focused) else (180, 185, 210)
    pygame.draw.rect(surface, border, rect, 6 if (b.selected or focused) else 3, border_radius=22)
    label = r.hud_font.render(b.label, True, WHITE if b.enabled else DIM)
    if label.get_width() > rect.width - 20:
        label = pygame.transform.smoothscale(label, (rect.width - 20, int(label.get_height() * (rect.width - 20) / label.get_width())))
    if b.sub:
        sub = r.small_font.render(b.sub, True, (230, 230, 240) if b.enabled else DIM)
        gap = 6
        total = label.get_height() + gap + sub.get_height()
        top = rect.centery - total // 2
        surface.blit(label, label.get_rect(midtop=(rect.centerx, top)))
        surface.blit(sub, sub.get_rect(midtop=(rect.centerx, top + label.get_height() + gap)))
    else:
        surface.blit(label, label.get_rect(center=rect.center))


def shade(surface: pygame.Surface, alpha: int = 150) -> None:
    s = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
    s.fill((8, 10, 24, alpha))
    surface.blit(s, (0, 0))


def title(surface, r: Renderer, text: str, y: int) -> None:
    t = r.big_font.render(text, True, GOLD)
    o = r.big_font.render(text, True, (0, 0, 0))
    rect = t.get_rect(center=(surface.get_width() // 2, y))
    for dx, dy in ((-3, 3), (3, 3), (0, 4)):
        surface.blit(o, rect.move(dx, dy))
    surface.blit(t, rect)


def hint(surface, r: Renderer, text: str) -> None:
    t = r.small_font.render(text, True, DIM)
    surface.blit(t, t.get_rect(midbottom=(surface.get_width() // 2, surface.get_height() - 12)))


class Menu:
    """Owns the start screens. step() returns a start request when it's time to play."""

    def __init__(self, renderer: Renderer, size: tuple[int, int], store: ProfileStore, bank: WordBank,
                 gentle: bool = False, max_players: int = 3, style: str = "punch"):
        self.r, (self.w, self.h) = renderer, size
        self.store, self.bank = store, bank
        self.gentle = gentle
        self.style = style
        self.max_players = max_players
        self.joined: list[Profile] = []
        self.mode = "split"
        self.kind = "classic"
        self.screen = "who"
        self.countdown_until = 0.0
        self.setup = SetupScreen(self)
        self.profiles = store.all()
        if not self.profiles:
            self.screen = "setup"

    # ---- screens -------------------------------------------------------------------

    def reset(self) -> None:
        self.profiles = self.store.all()
        names = {p.name for p in self.joined}
        self.joined = [p for p in self.profiles if p.name in names][: self.max_players]
        self.screen = "who" if self.profiles else "setup"

    def _who_buttons(self) -> list[Button]:
        buttons = []
        cols, cw, ch, gap = 3, 330, 150, 36
        shown = self.profiles[:6]
        x0 = (self.w - (cols * cw + (cols - 1) * gap)) // 2
        for i, p in enumerate(shown):
            row, col = divmod(i, cols)
            rect = pygame.Rect(x0 + col * (cw + gap), 170 + row * (ch + 26), cw, ch)
            joined = p in self.joined
            color = PLAYER_COLORS[self.joined.index(p) % 3] if joined else (70, 80, 130)
            sub = self.bank.level(p.level).name + (f"   best {p.best_score}" if p.best_score else "")
            if joined:
                sub = f"Player {self.joined.index(p) + 1}  -  " + sub
            buttons.append(Button("player", rect, p.name, sub, color, joined, data=p))
        n = len(self.joined)
        go = pygame.Rect(self.w // 2 - 200, self.h - 150, 400, 96)
        buttons.append(Button("next", go, "Let's go!" if n else "Pick your name",
                              f"{n} player{'s' if n != 1 else ''}" if n else "hold your hand on it",
                              (60, 160, 90), enabled=n > 0))
        buttons.append(Button("closet", pygame.Rect(self.w // 2 - 480, self.h - 150, 250, 96), "Dress up!",
                              "hats & colours", (170, 80, 160), enabled=n > 0))
        buttons.append(Button("settings", pygame.Rect(self.w - 150, self.h - 70, 136, 52), "Settings", "",
                              (70, 75, 100), mouse_only=True))
        buttons.append(Button("setup", pygame.Rect(14, self.h - 70, 136, 52), "Players", "",
                              (70, 75, 100), mouse_only=True))
        return buttons

    GAME_INFO = {
        "classic": ("Word Punch", "read it, punch it", (220, 130, 40)),
        "catch": ("Catch the Word", "listen and find it", (60, 150, 210)),
        "whack": ("Whack-a-Word", "words pop up!", (120, 170, 60)),
        "boss": ("Boss Battle", "beat the monster", (200, 70, 90)),
        "sentence": ("Sentence Builder", "words in order", (150, 90, 200)),
    }

    def _game_buttons(self) -> list[Button]:
        bw, bh, gap = 360, 150, 30
        readers = any(not self.bank.level(p.level).is_letters for p in self.joined)
        buttons = []
        for i, kind in enumerate(KINDS):
            row, col = divmod(i, 3)
            n_in_row = 3 if row == 0 else len(KINDS) - 3
            x0 = (self.w - (n_in_row * bw + (n_in_row - 1) * gap)) // 2
            title_, sub, color = self.GAME_INFO[kind]
            ok = readers or kind != "sentence"
            buttons.append(Button(f"game:{kind}", pygame.Rect(x0 + col * (bw + gap), 170 + row * (bh + 28), bw, bh),
                                  title_, sub if ok else "for readers", color, enabled=ok))
        buttons.append(Button("back", pygame.Rect(self.w // 2 - 150, self.h - 130, 300, 80), "Back", "", (90, 90, 110)))
        return buttons

    def _mode_buttons(self) -> list[Button]:
        n = len(self.joined)
        bw, bh, gap = 340, 210, 30
        names = [p.name for p in self.joined]
        info = {"split": ("Own sides", "your own words"),
                "coop": ("Team up", "share the sky"),
                "competitive": ("Race", "fastest wins"),
                "tag": ("Tag team", f"{names[0]} reads, {names[1]} hits" if n > 1 else "")}
        modes = [(m, *info[m]) for m in allowed_modes(self.kind, n)]
        if n == 1:
            modes = [(modes[0][0], "Play!", "")]
        if len(modes) == 4:
            bw, gap = 270, 22
        x0 = (self.w - (len(modes) * bw + (len(modes) - 1) * gap)) // 2
        buttons = [Button(f"mode:{m}", pygame.Rect(x0 + i * (bw + gap), 190, bw, bh), label, sub,
                          (200, 120, 40) if m == "competitive" else (60, 120, 200) if m == "coop" else (70, 160, 90))
                   for i, (m, label, sub) in enumerate(modes)]
        bw2, gap2 = 300, 30
        x0 = self.w // 2 - (3 * bw2 + 2 * gap2) // 2
        buttons.append(Button("style", pygame.Rect(x0, 450, bw2, 90),
                              "Slice!" if self.style == "slice" else "Punch!",
                              "swipe through words" if self.style == "slice" else "rocket punches",
                              (200, 70, 90) if self.style == "slice" else (220, 130, 40)))
        buttons.append(Button("gentle", pygame.Rect(x0 + bw2 + gap2, 450, bw2, 90),
                              "No lives" if self.gentle else "Lives",
                              "words come back" if self.gentle else "tap to change",
                              (150, 90, 170), selected=self.gentle))
        buttons.append(Button("back", pygame.Rect(x0 + 2 * (bw2 + gap2), 450, bw2, 90), "Back", "", (90, 90, 110)))
        return buttons

    def _closet_buttons(self) -> list[Button]:
        n = len(self.joined)
        col = self.w / max(1, n)
        buttons = []
        for i, p in enumerate(self.joined):
            cx = int(col * (i + 0.5))
            for row, kind in ((400, "hat"), (500, "color")):
                buttons.append(Button(f"{kind}-", pygame.Rect(cx - 190, row, 80, 80), "<", "", (80, 90, 140), data=i))
                buttons.append(Button(f"{kind}+", pygame.Rect(cx + 110, row, 80, 80), ">", "", (80, 90, 140), data=i))
        buttons.append(Button("done", pygame.Rect(self.w // 2 - 160, self.h - 128, 320, 72), "Done!", "",
                              (60, 160, 90)))
        return buttons

    def _cycle(self, p: Profile, kind: str, step: int) -> None:
        items = rewards.HATS if kind == "hat" else rewards.COLORS
        options = [i for i, _, _ in rewards.unlocked(items, p.stars)]
        cur = p.hat if kind == "hat" else p.color
        idx = options.index(cur) if cur in options else 0
        new = options[(idx + step) % len(options)]
        if kind == "hat":
            p.hat = new
        else:
            p.color = new
        self.store.save(p)

    # ---- per frame -----------------------------------------------------------------

    def step(self, dt: float, now: float, ptr: Pointers, keys: list) -> dict | None:
        if self.screen == "setup":
            if self.setup.handle_keys(keys):
                self.reset()
            return None
        if self.screen == "countdown":
            if now >= self.countdown_until:
                self.screen = "who"
                return {"profiles": list(self.joined), "mode": self.mode, "gentle": self.gentle,
                        "style": self.style, "kind": self.kind}
            return None

        if self.screen == "settings":
            return None  # the App drives the settings screen
        for e in keys:
            if e.key == pygame.K_p and self.screen == "who":
                self.screen = "setup"
                return None
            if e.key == pygame.K_s and self.screen == "who":
                self.screen = "settings"
                return None
            if e.key == pygame.K_BACKSPACE and self.screen in ("mode", "game"):
                self.screen = "game" if self.screen == "mode" else "who"

        if self.screen == "closet":
            buttons = self._closet_buttons()
        elif self.screen == "game":
            buttons = self._game_buttons()
        else:
            buttons = self._who_buttons() if self.screen == "who" else self._mode_buttons()
        self._carry_hover(buttons)
        fired = update_buttons(buttons, ptr, dt)
        self._buttons = buttons
        if not fired:
            return None
        if fired.key == "player":
            p = fired.data
            if p in self.joined:
                self.joined.remove(p)
            elif len(self.joined) < self.max_players:
                self.joined.append(p)
        elif fired.key == "next":
            self.screen = "game"
        elif fired.key.startswith("game:"):
            self.kind = fired.key.split(":", 1)[1]
            self.screen = "mode"
        elif fired.key.startswith("mode:"):
            self.mode = fired.key.split(":", 1)[1]
            self.screen = "countdown"
            self.countdown_until = now + 3.5
        elif fired.key == "gentle":
            self.gentle = not self.gentle
        elif fired.key == "style":
            self.style = "slice" if self.style == "punch" else "punch"
        elif fired.key == "back":
            self.screen = "game" if self.screen == "mode" else "who"
        elif fired.key == "settings":
            self.screen = "settings"
        elif fired.key == "closet":
            self.screen = "closet"
        elif fired.key == "done":
            self.screen = "who"
        elif fired.key[:-1] in ("hat", "color"):
            self._cycle(self.joined[fired.data], fired.key[:-1], 1 if fired.key.endswith("+") else -1)
        elif fired.key == "setup":
            self.screen = "setup"
        return None

    def _carry_hover(self, buttons: list[Button]) -> None:
        """Buttons are rebuilt each frame; keep hover timers by identity."""
        def ident(b):
            return (b.key, b.data if isinstance(b.data, int) else id(b.data) if b.data else b.label)
        old = {ident(b): b for b in getattr(self, "_buttons", [])}
        for b in buttons:
            prev = old.get(ident(b))
            if prev is None and b.key in ("gentle", "style"):
                prev = next((o for o in old.values() if o.key == b.key), None)
            if prev is None and b.key == "next":
                prev = next((o for o in old.values() if o.key == "next"), None)
            if prev:
                b.hover, b.latched = prev.hover, prev.latched

    # ---- drawing -------------------------------------------------------------------

    def draw(self, surface: pygame.Surface, now: float) -> None:
        shade(surface, 120 if self.screen == "countdown" else 160)
        r = self.r
        if self.screen == "setup":
            self.setup.draw(surface, now)
            return
        if self.screen == "countdown":
            self._draw_countdown(surface, now)
            return
        buttons = getattr(self, "_buttons", None) or (
            self._closet_buttons() if self.screen == "closet" else
            self._game_buttons() if self.screen == "game" else
            self._who_buttons() if self.screen == "who" else self._mode_buttons())
        if self.screen == "closet":
            self._draw_closet(surface, now)
            for b in buttons:
                draw_button(surface, r, b, now)
            return
        if self.screen == "game":
            title(surface, r, "Pick a game!", 90)
            hint(surface, r, "Hold your hand on a game")
        elif self.screen == "who":
            title(surface, r, "Who's playing?", 90)
            hint(surface, r, "Hold your hand on your name (or punch it!)      P = players   S = settings")
        else:
            title(surface, r, "How do you want to play?", 100)
            hint(surface, r, "Hold your hand on a button      Backspace = back")
        for b in buttons:
            draw_button(surface, r, b, now)

    def _draw_closet(self, surface, now) -> None:
        r = self.r
        title(surface, r, "Dress up!", 70)
        hint(surface, r, "Hold your hand on the arrows to change. Earn stars to unlock more!")
        n = len(self.joined)
        col = self.w / max(1, n)
        for i, p in enumerate(self.joined):
            cx = int(col * (i + 0.5))
            team = PLAYER_COLORS[i % 3]
            name = r.hud_font.render(p.name, True, team)
            surface.blit(name, name.get_rect(center=(cx, 140)))
            # star count
            s = r.hud_font.render(f"{p.stars}", True, GOLD)
            surface.blit(s, s.get_rect(midleft=(cx + 14, 182)))
            r._star(surface, cx - 8, 182, 16, now)
            # preview head with hat
            head_y = 300
            pygame.draw.circle(surface, (235, 195, 165), (cx, head_y), 48)
            for ex in (-16, 16):
                pygame.draw.circle(surface, (40, 40, 50), (cx + ex, head_y - 6), 6)
            pygame.draw.arc(surface, (40, 40, 50), (cx - 18, head_y + 2, 36, 26), 3.5, 5.9, 4)
            rewards.draw_hat(surface, p.hat, cx, head_y - 42, 100, 0)
            # hat row
            lab = r.small_font.render(rewards.item_name(rewards.HATS, p.hat), True, WHITE)
            surface.blit(lab, lab.get_rect(center=(cx, 440)))
            # colour row: a glove in that colour
            color = rewards.glove_color(p.color, team, now)
            g = r.glove(color, 70)
            surface.blit(g, g.get_rect(center=(cx - 40, 540)))
            lab = r.small_font.render(rewards.item_name(rewards.COLORS, p.color), True, WHITE)
            surface.blit(lab, lab.get_rect(midleft=(cx - 5, 540)))
            # what's next
            nxt = [x for x in (rewards.next_locked(rewards.HATS, p.stars), rewards.next_locked(rewards.COLORS, p.stars)) if x]
            if nxt:
                item = min(nxt, key=lambda x: x[2])
                t = r.small_font.render(f"Next: {item[1]} at {item[2]} stars", True, DIM)
                surface.blit(t, t.get_rect(center=(cx, 600)))

    def _draw_countdown(self, surface, now) -> None:
        r = self.r
        left = max(0.0, self.countdown_until - now)
        n = math.ceil(left - 0.5)
        text = str(n) if n > 0 else "GO!"
        k = 1 + (left - math.floor(left)) * 0.6
        t = pygame.transform.rotozoom(r.big_font.render(text, True, GOLD), 0, 1.8 * k)
        surface.blit(t, t.get_rect(center=(self.w // 2, self.h // 2 - 40)))
        names = self.joined
        if self.mode == "tag" and len(names) > 1:
            label = r.hud_font.render(f"{names[0].name} reads (stand left)   -   "
                                      f"{', '.join(p.name for p in names[1:])} punches (stand right)", True, WHITE)
            surface.blit(label, label.get_rect(center=(self.w // 2, self.h - 100)))
        elif self.mode == "split" and len(names) > 1:
            lane_w = self.w / len(names)
            for i, p in enumerate(names):
                cx = int(lane_w * (i + 0.5))
                label = r.hud_font.render(f"{p.name}  stand here", True, PLAYER_COLORS[i % 3])
                surface.blit(label, label.get_rect(center=(cx, self.h - 110)))
                pygame.draw.polygon(surface, PLAYER_COLORS[i % 3],
                                    [(cx - 22, self.h - 80), (cx + 22, self.h - 80), (cx, self.h - 50)])
            for i in range(1, len(names)):
                x = int(lane_w * i)
                pygame.draw.line(surface, WHITE, (x, self.h - 160), (x, self.h - 20), 3)
        elif len(names) > 1:
            order = "   ".join(p.name for p in names)
            label = r.hud_font.render(f"Stand left to right:   {order}", True, WHITE)
            surface.blit(label, label.get_rect(center=(self.w // 2, self.h - 100)))
        mode_name = TITLES[self.kind] + "  -  " + {"split": "Own sides", "coop": "Team up", "competitive": "Race",
                                                    "tag": "Tag team"}[self.mode]
        style = "slice" if self.style == "slice" else "punch"
        sub = r.hud_font.render(f"{mode_name}  -  {style}  -  {'no lives' if self.gentle else 'lives'}", True, DIM)
        surface.blit(sub, sub.get_rect(center=(self.w // 2, 120)))


class SetupScreen:
    """Parent setup with the keyboard: add kids, set their level, rename, delete."""

    def __init__(self, menu: Menu):
        self.menu = menu
        self.sel = 0
        self.typing: str | None = None   # text being typed
        self.typing_for: str = ""        # "new" | "rename"
        self.confirm_delete = False
        self.msg = ""

    @property
    def profiles(self) -> list[Profile]:
        return self.menu.profiles

    def handle_keys(self, keys) -> bool:
        """Returns True when the parent leaves setup."""
        store, bank = self.menu.store, self.menu.bank
        for e in keys:
            if self.typing is not None:
                if e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    name = self.typing.strip()
                    if not name:
                        self.typing = None
                    elif store.exists(name) and not (self.typing_for == "rename" and self._current() and
                                                      self._current().slug == name.lower()):
                        self.msg = f"There's already a {name}"
                    elif self.typing_for == "new":
                        store.save(Profile(name, level="k1"))
                        self.menu.profiles = store.all()
                        self.sel = next(i for i, p in enumerate(self.profiles) if p.name == name)
                        self.msg = f"Added {name} - use Left/Right to set the level"
                        self.typing = None
                    else:
                        store.rename(self._current(), name)
                        self.menu.profiles = store.all()
                        self.typing = None
                elif e.key == pygame.K_ESCAPE:
                    self.typing = None
                elif e.key == pygame.K_BACKSPACE:
                    self.typing = self.typing[:-1]
                elif e.unicode and (e.unicode.isalnum() or e.unicode in " -'") and len(self.typing) < 16:
                    self.typing += e.unicode
                continue

            cur = self._current()
            if e.key in (pygame.K_ESCAPE, pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_p):
                if self.profiles:
                    self.confirm_delete = False
                    return True
                self.msg = "Add at least one player first (press N)"
            elif e.key == pygame.K_n:
                self.typing, self.typing_for, self.msg = "", "new", ""
            elif e.key == pygame.K_g:
                from ..report import write_report
                path = write_report()
                self.msg = f"Parent report opened in your browser ({path.name})"
            elif e.key == pygame.K_r and cur:
                self.typing, self.typing_for, self.msg = cur.name, "rename", ""
            elif e.key == pygame.K_UP and self.profiles:
                self.sel = (self.sel - 1) % len(self.profiles)
                self.confirm_delete = False
            elif e.key == pygame.K_DOWN and self.profiles:
                self.sel = (self.sel + 1) % len(self.profiles)
                self.confirm_delete = False
            elif e.key in (pygame.K_LEFT, pygame.K_RIGHT) and cur:
                order = bank.order
                i = order.index(cur.level) + (1 if e.key == pygame.K_RIGHT else -1)
                cur.level = order[max(0, min(len(order) - 1, i))]
                cur.good = {}  # mastery progress belongs to a level
                store.save(cur)
            elif e.key == pygame.K_DELETE and cur:
                if self.confirm_delete:
                    store.delete(cur)
                    self.menu.profiles = store.all()
                    self.sel = max(0, min(self.sel, len(self.profiles) - 1))
                    self.msg = f"Deleted {cur.name}"
                    self.confirm_delete = False
                else:
                    self.confirm_delete = True
                    self.msg = f"Press Delete again to remove {cur.name} and their progress"
        return False

    def _current(self) -> Profile | None:
        return self.profiles[self.sel] if self.profiles and self.sel < len(self.profiles) else None

    def draw(self, surface, now) -> None:
        r, w = self.menu.r, self.menu.w
        title(surface, r, "Parent setup", 80)
        panel = pygame.Rect(w // 2 - 430, 150, 860, 400)
        p = pygame.Surface(panel.size, pygame.SRCALPHA)
        p.fill(PANEL)
        surface.blit(p, panel)
        y = panel.top + 20
        if not self.profiles:
            t = r.hud_font.render("No players yet - press N to add one", True, WHITE)
            surface.blit(t, t.get_rect(center=(w // 2, y + 40)))
        for i, prof in enumerate(self.profiles[:9]):
            selected = i == self.sel
            color = GOLD if selected else WHITE
            level = self.menu.bank.level(prof.level).name
            left = f"{'>' if selected else ' '}  {prof.name}"
            right = f"{level}    best {prof.best_score}    words read {prof.words_read}"
            surface.blit(r.hud_font.render(left, True, color), (panel.left + 24, y))
            t = r.small_font.render(right, True, color if selected else DIM)
            surface.blit(t, (panel.left + 330, y + 8))
            y += 42
        help_lines = ["N  new player      R  rename      Up/Down  pick      Left/Right  change level",
                      "G  parent report (opens in your browser)      Delete  remove      Enter  done"]
        for j, line in enumerate(help_lines):
            t = r.small_font.render(line, True, DIM)
            surface.blit(t, t.get_rect(center=(w // 2, panel.bottom + 30 + j * 30)))
        if self.typing is not None:
            box = pygame.Rect(w // 2 - 300, 300, 600, 110)
            pygame.draw.rect(surface, (30, 36, 70), box, border_radius=16)
            pygame.draw.rect(surface, GOLD, box, 4, border_radius=16)
            q = "New player's name:" if self.typing_for == "new" else "Rename to:"
            surface.blit(r.small_font.render(q + "   (Enter = save, Esc = cancel)", True, DIM), (box.left + 20, box.top + 12))
            cursor = "_" if int(now * 2) % 2 == 0 else " "
            surface.blit(r.hud_font.render(self.typing + cursor, True, WHITE), (box.left + 20, box.top + 50))
        if self.msg:
            t = r.small_font.render(self.msg, True, GOLD)
            surface.blit(t, t.get_rect(center=(w // 2, panel.top - 18)))
