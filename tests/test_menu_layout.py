import os

import pygame
import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from word_punch.game.games import KINDS
from word_punch.profiles import Profile, ProfileStore
from word_punch.ui.menu import Menu
from word_punch.ui.render import Renderer
from word_punch.words import WordBank

W, H = 1280, 720


@pytest.fixture(scope="module")
def menu(tmp_path_factory):
    pygame.init()
    store = ProfileStore(tmp_path_factory.mktemp("profiles"))
    for name, lvl in (("Ava", "k2"), ("Ben", "letters"), ("Cy", "g5"), ("Di", "g9"), ("Ed", "k1"), ("Flo", "g12")):
        store.save(Profile(name, level=lvl))
    m = Menu(Renderer((W, H)), (W, H), store, WordBank())
    m.joined = m.profiles[:3]
    return m


def hand_buttons(buttons):
    return [b for b in buttons if not b.mouse_only]


def test_every_hand_button_is_in_the_top_half(menu):
    screens = {"who": menu._who_buttons(), "game": menu._game_buttons(), "closet": menu._closet_buttons()}
    for kind in KINDS:
        menu.kind = kind
        screens[f"mode:{kind}"] = menu._mode_buttons()
    for name, buttons in screens.items():
        for b in hand_buttons(buttons):
            assert b.rect.bottom <= H // 2, f"{name}: '{b.label}' reaches down to y={b.rect.bottom}"
            assert b.rect.left >= 0 and b.rect.right <= W, f"{name}: '{b.label}' is off screen"


def test_buttons_dont_overlap(menu):
    for buttons in (menu._who_buttons(), menu._game_buttons(), menu._closet_buttons(), menu._mode_buttons()):
        hb = hand_buttons(buttons)
        for i, a in enumerate(hb):
            for b in hb[i + 1:]:
                assert not a.rect.colliderect(b.rect), (a.label, b.label)


def test_buttons_popping_up_under_a_palm_dont_fire(menu):
    from word_punch.ui.menu import Pointers
    menu.screen = "who"
    menu._built_for = None
    btn = next(b for b in menu._who_buttons() if b.key == "next")
    palm = Pointers(hands=[btn.rect.center], palms=[btn.rect.center], mode="palm", hold_s=0.4)
    t = 100.0
    for _ in range(90):  # 3 s with an open palm parked where "Let's go!" appears
        t += 1 / 30
        assert menu.step(1 / 30, t, palm, []) is None
        assert menu.screen == "who", "the button under the palm fired by itself"
    away = Pointers(hands=[(5, 700)], mode="palm", hold_s=0.4)
    menu.step(1 / 30, t, away, [])                    # hand moves off: unlocked
    for _ in range(20):                               # then a deliberate palm selects it
        t += 1 / 30
        menu.step(1 / 30, t, palm, [])
    assert menu.screen == "game"
