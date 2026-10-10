import copy
import random

import pytest

from word_punch import config
from word_punch.game import scoring
from word_punch.game.core import Game
from word_punch.game.difficulty import Difficulty
from word_punch.game.track import Track
from word_punch.words import WordBank

BASE_CFG = config.load()
SIZE = (1200, 800)


@pytest.fixture(scope="module")
def bank():
    return WordBank()


def measure(text, is_letter):
    return (40 + 25 * len(text), 70)


def make_game(bank, mode="split", levels=("k2", "letters"), **rules):
    cfg = copy.deepcopy(BASE_CFG)
    cfg["rules"].update(rules)
    names = [f"P{i + 1}" for i in range(len(levels))]
    return Game(mode=mode, player_names=names, player_levels=list(levels), bank=bank,
                cfg=cfg, size=SIZE, measure=measure, rng=random.Random(1))


def run(game, seconds, t0=0.0, dt=1 / 60):
    t = t0
    for _ in range(int(seconds / dt)):
        t += dt
        game.update(dt, t)
    return t


def kinds(game):
    return [e.kind for e in game.drain_events()]


def test_split_lanes_spawn_their_own_levels(bank):
    g = make_game(bank)
    run(g, 6)
    assert {w.level_key for w in g.words if w.lane.index == 0} <= {"k1", "k2"}  # k1 = review
    assert {w.level_key for w in g.words if w.lane.index == 1} == {"letters"}
    for w in g.words:
        assert w.lane.x0 <= w.x - w.w / 2 and w.x + w.w / 2 <= w.lane.x1


def test_no_sound_alikes_on_screen(bank):
    g = make_game(bank, mode="coop", levels=("k2", "letters"))
    g.diff_cfg = dict(g.diff_cfg, max_on_screen=8)
    for _ in range(30):
        t = run(g, 3)
        keys = [bank.sound_keys(w.text, w.is_letter) for w in g.words]
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                assert not keys[i] & keys[j], (g.words[i].text, g.words[j].text)
        # clear some so new ones keep coming
        g.words = g.words[2:]


def test_say_then_punch_breaks_and_scores(bank):
    g = make_game(bank)
    t = run(g, 2)
    w = next(x for x in g.words if x.lane.index == 0)
    assert g.heard(w.text.lower(), t) is w and w.unlocked
    g.punch(0, w.x, t)
    t = run(g, 1, t)
    assert w not in g.words
    ev = kinds(g)
    assert "unlock" in ev and "break" in ev
    assert g.players[0].score > 0


def test_punch_locked_word_clangs_and_passes(bank):
    g = make_game(bank)
    t = run(g, 2)
    w = next(x for x in g.words if x.lane.index == 0)
    g.punch(0, w.x, t)
    run(g, 1, t)
    assert w in g.words
    assert "clang" in kinds(g)


def test_split_credit_goes_to_lane_owner(bank):
    g = make_game(bank)
    t = run(g, 2)
    w = next(x for x in g.words if x.lane.index == 1)
    g.heard(bank.letter_names[w.text.lower()][0], t)
    g.punch(0, w.x, t)  # "player 0" punched, but in lane 1
    run(g, 1, t)
    assert g.players[1].score > 0 and g.players[0].score == 0


def test_competitive_first_punch_wins(bank):
    g = make_game(bank, mode="competitive", levels=("k3", "k2"))
    t = run(g, 2)
    w = g.words[0]
    assert w.level_key in ("k2", "k1")  # easiest level among players
    g.heard(w.text, t)
    g.punch(1, w.x, t)
    g.punch(0, w.x, t + 0.05)
    run(g, 1, t)
    assert g.players[1].score > 0 and g.players[0].score == 0


def test_lives_and_game_over(bank):
    g = make_game(bank, mode="coop", levels=("k2",), lives=2)
    run(g, 60)
    assert g.over
    ev = kinds(g)
    assert ev.count("miss") == 2 and "gameover" in ev


def test_split_lane_out_but_game_continues(bank):
    g = make_game(bank, lives=1)
    t = 0.0
    # Keep lane 1 clear so only lane 0 runs out.
    for _ in range(40 * 60):
        t += 1 / 60
        g.words = [w for w in g.words if w.lane.index == 0]
        g.update(1 / 60, t)
    assert not g.lanes[0].alive and g.lanes[1].alive and not g.over
    assert "lane_out" in kinds(g)


def test_gentle_mode_bounces_and_says(bank):
    g = make_game(bank, mode="coop", levels=("k2",), gentle=True)
    run(g, 90)
    assert not g.over
    ev = kinds(g)
    assert "bounce" in ev and "say" in ev and "miss" not in ev


def test_letters_easy_any_voice_unlocks(bank):
    g = make_game(bank, levels=("letters",), letters_easy=True)
    t = run(g, 1)
    assert len(g.words) == 1
    g.voice(t)
    assert g.words[0].unlocked


def test_level_up_after_mastery(bank):
    rules = dict(BASE_CFG["rules"], mastery_hits=1)
    track = Track(bank, "k1", rules)
    for w in ["a", "I", "the"]:
        assert not track.record_hit(w, "k1", 1.0)
    assert track.record_hit("is", "k1", 1.0)
    assert track.level_up() and track.level_key == "k2"


def test_slow_reads_dont_count_toward_mastery(bank):
    rules = dict(BASE_CFG["rules"], mastery_hits=1)
    track = Track(bank, "k1", rules)
    for w in ["a", "I", "the", "is"]:
        track.record_hit(w, "k1", 9.0)
    assert not track.mastered()


def test_letter_mastery_is_case_insensitive(bank):
    rules = dict(BASE_CFG["rules"], mastery_hits=1)
    track = Track(bank, "letters", rules)
    for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        track.record_hit(ch, "letters", 1.0)
    assert track.mastered()


def test_review_words_come_from_earlier_levels(bank):
    rules = dict(BASE_CFG["rules"], review_chance=1.0)
    track = Track(bank, "k3", rules)
    rng = random.Random(0)
    levels = {track.candidates(rng)[0].level_key for _ in range(50)}
    assert levels <= {"k1", "k2"} and levels


def test_missed_words_come_back_more(bank):
    rules = dict(BASE_CFG["rules"], review_chance=0.0)
    track = Track(bank, "k2", rules)
    for _ in range(10):
        track.record_miss("said")
    rng = random.Random(0)
    firsts = [track.candidates(rng)[0].text for _ in range(300)]
    assert firsts.count("said") > 300 / 12 * 3


def test_difficulty_ramps_and_eases():
    d = Difficulty(BASE_CFG["difficulty"])
    start = d.fall
    for _ in range(5):
        d.on_hit(1.0)
    assert d.fall > start
    fast = d.fall
    d.on_miss()
    assert d.fall < fast
    for _ in range(200):
        d.on_hit(0.5)
    assert d.fall == BASE_CFG["difficulty"]["max_fall"]


def test_scoring():
    c = BASE_CFG["scoring"]
    slow = scoring.points(20, 10, 10, 0, c)
    fast = scoring.points(20, 0, 0, 0, c)
    combo = scoring.points(20, 10, 10, 5, c)
    assert slow == 20 and fast == 60 and combo == 30
    assert scoring.points(45, 10, 10, 0, c) > scoring.points(10, 10, 10, 0, c)


def test_screen_vocab_is_only_whats_on_screen(bank):
    g = make_game(bank, mode="split", levels=("k1", "letters"))
    run(g, 3)
    vocab = g.screen_vocab()
    for w in g.words:
        assert bank.listen_tokens(w.text, w.is_letter) <= vocab
    # nothing from words that aren't on screen
    on_screen = {w.text.lower() for w in g.words}
    assert not ({"the", "is"} - on_screen) & vocab or {"the", "is"} & on_screen


def test_listen_tokens(bank):
    assert {"a", "uh"} <= bank.listen_tokens("a", False)
    assert "r" in bank.listen_tokens("are", False)            # heard as the letter name
    assert {"bee", "but"} <= bank.listen_tokens("B", True)     # letter name + sound


def read_and_punch(g, lane, t, player=0):
    """Unlock and break the lowest word in a lane; returns the new time."""
    ws = sorted([w for w in g.words if w.lane is lane], key=lambda w: -w.y)
    if not ws:
        return run(g, 0.5, t)
    w = ws[0]
    g.heard(w.text if not w.is_letter else g.bank.letter_names[w.text.lower()][0], t)
    g.punch(player, w.x, t)
    return run(g, 0.6, t)


def test_split_round_ends_after_words_per_lane(bank):
    g = make_game(bank, levels=("k2", "letters"), round_end="words", round_words=3, gentle=True)
    t = run(g, 2)
    for _ in range(40):
        if g.lanes[0].done:
            break
        t = read_and_punch(g, g.lanes[0], t, 0)
    assert g.lanes[0].done and not g.lanes[0].alive and g.lanes[0].broken == 3
    assert not g.over                     # the other kid is still playing
    assert "lane_done" in kinds(g)
    for _ in range(60):
        if g.over:
            break
        t = read_and_punch(g, g.lanes[1], t, 1)
    assert g.over and g.result == "complete"


def test_race_first_to_goal_wins(bank):
    g = make_game(bank, mode="competitive", levels=("k2", "k2"), round_end="words", round_words=2, gentle=True)
    t = run(g, 2)
    for _ in range(40):
        if g.over:
            break
        t = read_and_punch(g, g.lanes[0], t, player=1)
    assert g.over and g.result == "complete" and g.winner == 1


def test_coop_goal_is_shared(bank):
    g = make_game(bank, mode="coop", levels=("k2", "letters"), round_end="words", round_words=2, gentle=True)
    assert g.word_goal(g.lanes[0]) == 4


def test_time_round(bank):
    g = make_game(bank, mode="coop", levels=("k2",), round_end="time", round_minutes=0.5, gentle=True)
    t = run(g, 20)
    assert not g.over and 9 < g.time_left(t) < 11
    run(g, 11, t)
    assert g.over and g.result == "complete"


def test_level_round_ends_on_mastery(bank):
    g = make_game(bank, levels=("k1",), round_end="level", mastery_hits=1, gentle=True, review_chance=0.0)
    t = run(g, 2)
    for _ in range(80):
        if g.over:
            break
        t = read_and_punch(g, g.lanes[0], t, 0)
    assert g.over and g.result == "complete"
    assert g.lanes[0].tracks[0].level_key == "k2"  # still levels up


def test_lives_round_reports_out(bank):
    g = make_game(bank, mode="coop", levels=("k2",), lives=1, round_end="lives")
    run(g, 40)
    assert g.over and g.result == "out"


def test_slice_cuts_unlocked_and_clangs_locked(bank):
    g = make_game(bank, mode="coop", levels=("k2",), gentle=True)
    t = run(g, 3)
    w = g.words[0]
    g.slice(0, w.x - 200, w.y, w.x + 200, w.y, t)       # locked: clang only
    assert w in g.words and "clang" in kinds(g)
    g.heard(w.text, t)
    cut = g.slice(0, w.x - 200, w.y + 5, w.x + 200, w.y - 5, t + 1)
    assert cut == [w] and w not in g.words
    ev = [e for e in g.drain_events() if e.kind == "break"]
    assert ev and ev[0].style == "slice"


def test_slice_misses_when_swipe_is_elsewhere(bank):
    g = make_game(bank, mode="coop", levels=("k2",), gentle=True)
    t = run(g, 3)
    w = g.words[0]
    g.heard(w.text, t)
    assert g.slice(0, w.x - 200, w.y + 300, w.x + 200, w.y + 300, t) == []


def force_power(g, power):
    t = run(g, 3)
    w = g.words[0]
    w.power = power
    g.heard(w.text, t)
    g.punch(0, w.x, t)
    return w, run(g, 0.5, t)


def test_gold_word_doubles_points(bank):
    a = make_game(bank, mode="coop", levels=("k2",), gentle=True, powerups=False)
    b = make_game(bank, mode="coop", levels=("k2",), gentle=True, powerups=False)
    force_power(a, "")
    force_power(b, "gold")
    assert b.players[0].score == 2 * a.players[0].score
    assert any(e.kind == "power" and e.text == "gold" for e in b.drain_events())


def test_freeze_stops_falling(bank):
    g = make_game(bank, mode="coop", levels=("k2",), gentle=True, powerups=False)
    w, t = force_power(g, "freeze")
    run(g, 1.0, t)
    ys = [x.y for x in g.words]
    run(g, 2.0, t + 1.0)
    assert [x.y for x in g.words][: len(ys)] == ys  # nothing moved while frozen


def test_giant_gloves_make_big_rockets(bank):
    g = make_game(bank, mode="coop", levels=("k2",), gentle=True, powerups=False)
    w, t = force_power(g, "giant")
    r = g.punch(0, 100, t)
    assert r.radius > g.h * 0.045 * 2


def test_stars(bank):
    from word_punch.rewards import stars_for_round
    assert stars_for_round(2, False, 0, 0) == 0
    assert stars_for_round(6, False, 5, 2) == 1
    assert stars_for_round(15, True, 3, 4) == 2
    assert stars_for_round(15, True, 1, 6) == 3
