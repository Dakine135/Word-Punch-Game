from word_punch import config
from word_punch.vision.pose_backend import Keypoint, Person
from word_punch.vision.punch import PunchDetector
from word_punch.vision.tracker import Tracker

PUNCH_CFG = config.load()["punch"]


def person(cx=0.5, wrist_y=0.6, shoulder_y=0.4, width=0.12, vis=0.9):
    """A person centered at cx; both wrists at wrist_y."""
    half = width / 2
    return Person({
        "nose": Keypoint(cx, shoulder_y - 0.1, vis),
        "left_shoulder": Keypoint(cx - half, shoulder_y, vis),
        "right_shoulder": Keypoint(cx + half, shoulder_y, vis),
        "left_wrist": Keypoint(cx - half, wrist_y, vis),
        "right_wrist": Keypoint(cx + half, wrist_y, vis),
    })


def run(trajectory, fps=30):
    """Feed (wrist_y per frame) and return punches."""
    det = PunchDetector(PUNCH_CFG)
    punches = []
    for i, y in enumerate(trajectory):
        punches += det.update(person(wrist_y=y), i / fps)
    return punches


def lerp(a, b, n):
    return [a + (b - a) * i / (n - 1) for i in range(n)]


def test_fast_upward_punch_detected():
    # chest (0.55) to above head (0.2) in ~0.2 s
    traj = [0.55] * 10 + lerp(0.55, 0.2, 7) + [0.2] * 5
    punches = run(traj)
    assert len(punches) == 2  # both wrists moved together in this synthetic person


def test_fast_punch_detected_at_low_fps():
    traj = [0.55] * 4 + lerp(0.55, 0.2, 3) + [0.2] * 3
    assert run(traj, fps=8)


def test_slow_reach_ignored():
    # same distance over 2 seconds
    assert not run([0.55] * 10 + lerp(0.55, 0.2, 60))


def test_small_jitter_ignored():
    assert not run([0.55, 0.5] * 30)


def test_punch_below_shoulder_ignored():
    # fast but stays below the shoulder line (0.4)
    assert not run([0.9] * 10 + lerp(0.9, 0.5, 6) + [0.5] * 5)


def test_cooldown_prevents_double_count():
    up_down = [0.55] * 6 + lerp(0.55, 0.2, 6)
    punches = run(up_down + lerp(0.2, 0.55, 2) + lerp(0.55, 0.2, 3))
    assert len(punches) == 2  # one per hand; the immediate re-punch is in cooldown


def test_tracker_keeps_slots_when_people_swap_order_in_list():
    tr = Tracker(max_players=2)
    tr.update([person(0.3), person(0.7)], 0.0)
    slots = tr.update([person(0.72), person(0.31)], 0.033)
    assert abs(slots[0].x - 0.31) < 1e-6 and abs(slots[1].x - 0.72) < 1e-6


def test_tracker_survives_dropout_and_frees_slot_later():
    tr = Tracker(max_players=2, keep_s=1.0)
    tr.update([person(0.3), person(0.7)], 0.0)
    slots = tr.update([person(0.3)], 0.5)
    assert slots[1].active and slots[1].person is None
    slots = tr.update([person(0.3)], 2.0)
    assert not slots[1].active


def test_tracker_new_person_takes_free_slot():
    tr = Tracker(max_players=3)
    tr.update([person(0.5)], 0.0)
    slots = tr.update([person(0.5), person(0.1)], 0.1)
    assert slots[0].x == 0.5 and slots[1].x == 0.1


def with_id(p, tid):
    p.track_id = tid
    return p


def test_tracker_follows_ids_when_kids_cross():
    tr = Tracker(max_players=2)
    tr.update([with_id(person(0.3), 7), with_id(person(0.7), 9)], 0.0)
    slots = tr.update([with_id(person(0.72), 7), with_id(person(0.28), 9)], 0.5)  # swapped sides
    assert slots[0].track_id == 7 and abs(slots[0].x - 0.72) < 1e-6
    assert slots[1].track_id == 9 and abs(slots[1].x - 0.28) < 1e-6


def test_tracker_new_id_reuses_a_free_slot():
    tr = Tracker(max_players=2, keep_s=1.0)
    tr.update([with_id(person(0.3), 1), with_id(person(0.7), 2)], 0.0)
    slots = tr.update([with_id(person(0.3), 1), with_id(person(0.69), 5)], 2.0)  # id 2 lost, 5 appears
    assert slots[1].track_id == 5 and slots[0].track_id == 1
