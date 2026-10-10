import copy
import random

import pytest

from word_punch import config
from word_punch.game.games import (KINDS, BossGame, CatchGame, SentenceGame, WhackGame, allowed_modes,
                                   load_sentences, make_game)
from word_punch.words import WordBank

BASE = config.load()


@pytest.fixture(scope="module")
def bank():
    return WordBank()


def new(bank, kind, mode="coop", levels=("k2",), **rules):
    cfg = copy.deepcopy(BASE)
    cfg["rules"].update(dict(gentle=True, powerups=False), **rules)
    return make_game(kind, mode=mode, player_names=[f"P{i}" for i in range(len(levels))],
                     player_levels=list(levels), bank=bank, cfg=cfg, size=(1200, 800),
                     measure=lambda t, l: (40 + 22 * len(t), 70), rng=random.Random(2))


def run(g, secs, t=0.0, dt=1 / 60):
    for _ in range(int(secs / dt)):
        t += dt
        g.update(dt, t)
    return t


def kinds(g):
    return [e.kind for e in g.drain_events()]


def test_every_kind_has_modes(bank):
    for k in KINDS:
        assert allowed_modes(k, 1) and allowed_modes(k, 2)
        g = new(bank, k, mode=allowed_modes(k, 2)[0], levels=("k2", "k1"))
        run(g, 5)


def test_catch_says_a_target_and_only_it_counts(bank):
    g = new(bank, "catch", round_end="words", round_words=2)
    t = run(g, 4)
    ev = g.drain_events()
    assert any(e.kind == "target" for e in ev) and g.target is not None
    assert all(w.unlocked and w.neutral for w in g.words)
    wrong = next((w for w in g.words if w is not g.target), None)
    if wrong:
        g._break(wrong, 0, t)
        assert wrong in g.words and "wrong" in kinds(g)
    target = g.target
    g._break(target, 0, t)
    assert target not in g.words and g.players[0].broken == 1


def test_whack_words_pop_up_and_duck(bank):
    g = new(bank, "whack")
    t = run(g, 2)
    assert g.words and all(w.hole >= 0 for w in g.words)
    w = g.words[0]
    assert g.touch(0, w.x, w.y, t) is None          # locked: no whack
    g.heard(w.text, t)
    assert g.touch(0, w.x, w.y, t) is w and w not in g.words
    t = run(g, 20, t)
    assert "duck" in kinds(g)                         # others went back down


def test_boss_battle_final_word_then_defeat(bank):
    g = new(bank, "boss", round_words=5)
    t = run(g, 1)
    for _ in range(300):
        if g.final is not None:
            break
        ws = sorted(g.words, key=lambda w: -w.y)
        if ws:
            w = ws[0]
            g.heard(w.text, t)
            g._break(w, 0, t)
        t = run(g, 0.5, t)
    assert g.boss_hp == 0 and g.final is not None and g.final.big
    g.heard(g.final.text, t)
    for _ in range(3):
        g._break(g.final, 0, t)
    assert g.defeated and g.over and g.result == "complete"


def test_sentence_builder_in_order(bank):
    g = new(bank, "sentence", levels=("k4",), round_words=10)
    t = run(g, 1.5)
    assert g.tokens and len(g.words) == len(g.tokens)
    first, second = g.tokens[0], g.tokens[1]
    w2 = next(w for w in g.words if w.text.lower() == second.lower() and w.text.lower() != first.lower())
    g.heard(w2.text, t)
    g._break(w2, 0, t)
    assert w2 in g.words and "wrong" in kinds(g)    # out of order
    for i, tok in enumerate(list(g.tokens)):
        w = next(x for x in g.words if x.text.lower() == tok.lower())
        g.heard(w.text, t)
        g._break(w, 0, t)
    assert g.done_count == 1 and "sentence_done" in kinds(g)


def test_sentences_have_levels(bank):
    s = load_sentences(bank)
    assert len(s) > 30
    easy = [x for x, need in s if need <= bank.level("k2").index]
    assert easy, "some sentences must work for early readers"


def test_tag_team_reader_cannot_punch(bank):
    g = new(bank, "classic", mode="tag", levels=("k2", "letters"))
    t = run(g, 3)
    w = g.words[0]
    g.heard(w.text, t)
    assert g.players[0].score == 5                    # reader scores for reading
    assert g.punch(0, w.x, t) is None and "tag_wrong" in [e.kind for e in g.drain_events()]
    assert g.punch(1, w.x, t) is not None
