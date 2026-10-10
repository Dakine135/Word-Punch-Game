import random

from word_punch import config
from word_punch.game.core import Game
from word_punch.profiles import Profile, ProfileStore, update_from_game
from word_punch.report import build, word_status
from word_punch.words import WordBank


def test_word_status():
    assert word_status(None) == "new"
    assert word_status({"read": 5, "missed": 0, "time": 10}) == "strong"
    assert word_status({"read": 1, "missed": 3, "time": 2}) == "trouble"
    assert word_status({"read": 1, "missed": 0, "time": 2}) == "learning"


def test_round_stats_saved_to_profile_and_report_builds(tmp_path):
    bank = WordBank()
    cfg = config.load()
    cfg["rules"].update(gentle=True, round_end="lives")
    g = Game(mode="split", player_names=["Clyde"], player_levels=["k1"], bank=bank, cfg=cfg,
             size=(1200, 800), measure=lambda t, l: (100, 70), rng=random.Random(0))
    t = 0.0
    for _ in range(60 * 4):
        t += 1 / 60
        g.update(1 / 60, t)
    w = g.words[0]
    g.heard(w.text, t)
    g.punch(0, w.x, t)
    for _ in range(60):
        t += 1 / 60
        g.update(1 / 60, t)
    prof = Profile("Clyde", level="k1")
    update_from_game(prof, g.track_for(0), g.players[0], True, g, {"game": "classic", "result": "complete"})
    assert prof.word_stats[w.text]["read"] == 1 and prof.history[-1]["words"] == 1
    store = ProfileStore(tmp_path)
    store.save(prof)
    loaded = store.all()[0]
    assert loaded.word_stats[w.text]["read"] == 1
    page = build([loaded], bank)
    assert "Clyde" in page and "K - Q1" in page
