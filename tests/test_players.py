"""Who's playing: rounds hold each kid's slot, extras (a grown-up walking through) stay grey."""
import numpy as np

from word_punch.vision.appearance import BINS, Look, add_looks, head_ratio
from word_punch.vision.pose_backend import Keypoint, Person
from word_punch.vision.tracker import Tracker

RED, BLUE, GREEN, GREY = 0, 8, 4, 13


def hist(b):
    h = [0.02] * BINS
    h[b] = 1.0
    s = sum(h)
    return [v / s for v in h]


def dressed(cx, colour, tid=None, head=0.62, width=0.12):
    """A person at cx wearing `colour`, with a kid's (0.62) or grown-up's (0.42) head."""
    half = width / 2
    kp = {
        "nose": Keypoint(cx, 0.3, 0.9),
        "left_ear": Keypoint(cx - head * half, 0.29, 0.9),
        "right_ear": Keypoint(cx + head * half, 0.29, 0.9),
        "left_shoulder": Keypoint(cx - half, 0.4, 0.9),
        "right_shoulder": Keypoint(cx + half, 0.4, 0.9),
        "left_wrist": Keypoint(cx - half, 0.6, 0.9),
        "right_wrist": Keypoint(cx + half, 0.6, 0.9),
    }
    return Person(kp, track_id=tid, look={"top": hist(colour), "bottom": hist(colour), "clean": True})


def frames(tr, make, t0, n=20, dt=0.033):
    t = t0
    for _ in range(n):
        slots = tr.update(make(), t)
        t += dt
    return slots, t


def two_kids_locked():
    tr = Tracker(3)
    _, t = frames(tr, lambda: [dressed(0.3, RED, 1), dressed(0.7, BLUE, 2)], 0.0)
    tr.lock(2)
    return tr, t


def test_head_ratio_tells_kids_from_grownups():
    assert abs(head_ratio(dressed(0.5, RED)) - 0.62) < 0.01
    assert abs(head_ratio(dressed(0.5, RED, head=0.42)) - 0.42) < 0.01


def test_a_grownup_walking_in_is_grey_and_cant_take_a_slot():
    tr, t = two_kids_locked()
    # Red kid ducks out of view; a grown-up in green stands right where they were.
    slots, t = frames(tr, lambda: [dressed(0.32, GREEN, 5, head=0.42), dressed(0.7, BLUE, 2)], t, n=200)
    assert slots[0].active and slots[0].person is None      # held for the red kid
    assert slots[1].person.track_id == 2
    assert not slots[2].active                               # no third player in a 2-kid round
    assert [p.track_id for p in tr.extras] == [5]


def test_a_lost_kid_wins_their_slot_back_by_clothes():
    tr, t = two_kids_locked()
    slots, t = frames(tr, lambda: [], t, n=100)  # both out of view for 3 s
    # Back with new IDs, on swapped sides.
    slots, t = frames(tr, lambda: [dressed(0.25, BLUE, 7), dressed(0.75, RED, 8)], t)
    assert slots[0].person.track_id == 8 and slots[1].person.track_id == 7


def test_swapped_tracker_ids_are_fixed_by_clothes():
    tr, t = two_kids_locked()
    # The pose tracker mixes the two kids' IDs up while they stand still.
    slots, t = frames(tr, lambda: [dressed(0.3, RED, 2), dressed(0.7, BLUE, 1)], t, n=15)
    assert abs(slots[0].x - 0.3) < 1e-6 and abs(slots[1].x - 0.7) < 1e-6


def test_lock_prefers_kids_over_a_grownup_who_arrived_first():
    tr = Tracker(3)
    frames(tr, lambda: [dressed(0.5, GREEN, 9, head=0.42)], 0.0, n=10)       # grown-up first
    _, t = frames(tr, lambda: [dressed(0.5, GREEN, 9, head=0.42), dressed(0.2, RED, 1),
                               dressed(0.8, BLUE, 2)], 1.0)
    tr.lock(2)
    slots = tr.update([dressed(0.5, GREEN, 9, head=0.42), dressed(0.2, RED, 1), dressed(0.8, BLUE, 2)], t)
    assert {slots[0].person.track_id, slots[1].person.track_id} == {1, 2}
    assert [p.track_id for p in tr.extras] == [9]


def test_a_kid_missing_at_the_start_gets_the_empty_slot():
    tr = Tracker(3)
    _, t = frames(tr, lambda: [dressed(0.3, RED, 1)], 0.0)
    tr.lock(2)
    slots, t = frames(tr, lambda: [dressed(0.3, RED, 1), dressed(0.7, BLUE, 4)], t)
    assert slots[0].person.track_id == 1 and slots[1].person.track_id == 4


def test_ignore_grownups_in_menus():
    tr = Tracker(3, ignore_grownups=True)
    slots, _ = frames(tr, lambda: [dressed(0.2, GREEN, 9, head=0.42), dressed(0.6, RED, 1)], 0.0)
    assert [s.person.track_id for s in slots if s.person] == [1]
    assert [p.track_id for p in tr.extras] == [9]


def test_unlock_lets_slots_expire_again():
    tr, t = two_kids_locked()
    frames(tr, lambda: [dressed(0.3, RED, 1)], t, n=100)
    assert tr.slots[1].active  # held during the round
    tr.unlock()
    slots, _ = frames(tr, lambda: [dressed(0.3, RED, 1)], t + 4, n=40)
    assert not slots[1].active


def test_clothes_colours_from_a_frame():
    frame = np.zeros((200, 400, 3), np.uint8)
    frame[:, :200] = (220, 30, 30)   # red shirt on the left
    frame[:, 200:] = (30, 30, 220)   # blue shirt on the right

    def body(cx):
        return Person({"left_shoulder": Keypoint(cx - 0.1, 0.2, 0.9), "right_shoulder": Keypoint(cx + 0.1, 0.2, 0.9),
                       "left_hip": Keypoint(cx - 0.08, 0.7, 0.9), "right_hip": Keypoint(cx + 0.08, 0.7, 0.9)})

    people = [body(0.25), body(0.75), body(0.26)]
    add_looks(frame, people)
    looks = []
    for p in people:
        lk = Look()
        lk.learn(p.look, None, dirty_ok=True)
        looks.append(lk)
    assert looks[0].distance(looks[2]) < 0.1 < 0.6 < looks[0].distance(looks[1])
    assert people[1].look["clean"] and not people[0].look["clean"]  # 0 and 2 overlap


def test_lights_dimming_doesnt_drop_the_players():
    tr, t = two_kids_locked()
    # Everyone's colours wash out to grey at once: tracker IDs still hold them.
    slots, t = frames(tr, lambda: [dressed(0.3, GREY, 1), dressed(0.7, GREY, 2)], t, n=60)
    assert slots[0].person.track_id == 1 and slots[1].person.track_id == 2
    assert tr.extras == []
