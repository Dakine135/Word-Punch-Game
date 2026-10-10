import random

from word_punch.vision.pose_backend import Keypoint, Person
from word_punch.vision.smoothing import OneEuro, PoseSmoother


def test_one_euro_reduces_jitter_when_still():
    rng = random.Random(0)
    f = OneEuro(1.5, 6.0)
    raw, out = [], []
    for i in range(60):
        x = 0.5 + rng.gauss(0, 0.01)
        raw.append(x)
        out.append(f(x, i / 20))
    jit = lambda s: sum(abs(a - b) for a, b in zip(s[10:], s[11:])) / len(s[11:])
    assert jit(out) < jit(raw) * 0.4


def test_one_euro_follows_fast_moves():
    f = OneEuro(1.5, 6.0)
    for i in range(10):
        f(0.2, i / 20)
    for i in range(10, 16):  # a fast move to 0.8 over 0.3 s
        last = f(0.2 + 0.6 * (i - 9) / 6, i / 20)
    assert last > 0.65  # caught up most of the way, not lagging far behind


def person(x):
    return Person({"nose": Keypoint(x, 0.3, 0.9)})


def test_blending_between_pose_updates():
    s = PoseSmoother("off")
    s.update(0, person(0.2), 1.0)
    s.update(0, person(0.4), 1.1)
    s.params = (1e9, 0)  # treat as smoothing on for blending, without filtering
    s.history[0] = [(1.0, person(0.2)), (1.1, person(0.4))]
    mid = s.at(0, 1.15).keypoints["nose"].x
    assert 0.29 < mid < 0.31  # halfway from previous to latest
    assert abs(s.at(0, 1.5).keypoints["nose"].x - 0.4) < 1e-6


def test_drop_resets():
    s = PoseSmoother("medium")
    s.update(1, person(0.2), 1.0)
    s.drop(1)
    assert s.at(1, 1.0) is None
