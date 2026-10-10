"""Points for breaking a word: harder words, faster reading, faster punching and combos pay more."""
from __future__ import annotations


def speed_bonus(elapsed: float, target: float, max_extra: float) -> float:
    """1.0 at/after target, rising linearly to 1 + max_extra at zero time."""
    if target <= 0:
        return 1.0
    return 1.0 + max_extra * max(0.0, (target - elapsed) / target)


def points(base: int, read_time: float, punch_time: float, combo: int, cfg: dict) -> int:
    read = speed_bonus(read_time, cfg["read_target_s"], 1.0)
    punch = speed_bonus(punch_time, cfg["punch_target_s"], 0.5)
    combo_mult = 1.0 + cfg["combo_step"] * min(combo, cfg["combo_max"])
    return int(round(base * read * punch * combo_mult))
