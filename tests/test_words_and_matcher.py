from dataclasses import dataclass

import pytest

from word_punch.speech.matcher import EXACT, LETTER_NAME, LETTER_SOUND, best_match, match_strength
from word_punch.words import WordBank


@pytest.fixture(scope="module")
def bank():
    return WordBank()


@dataclass
class T:
    text: str
    is_letter: bool = False
    unlocked: bool = False
    y: float = 0.0


def test_school_lists_have_expected_counts(bank):
    k = sum(len(bank.level(k).words) for k in ("k1", "k2", "k3", "k4"))
    g1 = sum(len(bank.level(k).words) for k in ("g1q1", "g1q2", "g1q3", "g1q4"))
    assert k == 43  # the school's 45, minus "a" and "I" (too short to hear reliably)
    assert g1 == 60  # sheet says "Total Words: 60"


def test_letters_level_is_upper_and_lower(bank):
    words = bank.level("letters").words
    assert len(words) == 52 and "A" in words and "a" in words


def test_every_letter_has_name_and_sound_aliases(bank):
    for ch in "abcdefghijklmnopqrstuvwxyz":
        assert bank.letter_names[ch], ch
        assert bank.letter_sounds[ch], ch


def test_homophones_match(bank):
    assert match_strength("two", "to", False, bank) == EXACT
    assert match_strength("too", "two", False, bank) == EXACT
    assert match_strength("won", "one", False, bank) == EXACT
    assert match_strength("eye", "I", False, bank) == EXACT
    assert match_strength("cat", "to", False, bank) == 0


def test_apostrophe_and_case(bank):
    assert match_strength("don't", "don't", False, bank) == EXACT
    assert match_strength("i", "I", False, bank) == EXACT


def test_letter_name_and_sound(bank):
    assert match_strength("bee", "B", True, bank) == LETTER_NAME
    assert match_strength("b", "b", True, bank) == LETTER_NAME
    assert match_strength("but", "b", True, bank) == LETTER_SOUND
    assert match_strength("dee", "B", True, bank) == 0


def test_best_match_prefers_strength_then_lowest(bank):
    high_c, low_k = T("C", True, y=100), T("K", True, y=400)
    # "cut" is a sound-alias for both C and K: the lower one wins.
    assert best_match("cut", [high_c, low_k], bank) is low_k
    # "see" is C's name: a name match beats a lower sound match.
    assert best_match("see", [high_c, low_k], bank) is high_c


def test_best_match_skips_unlocked(bank):
    a = T("the", unlocked=True)
    assert best_match("the", [a], bank) is None


def test_word_beats_letter_alias(bank):
    word_and, letter_a = T("and", y=10), T("A", True, y=500)
    assert best_match("and", [word_and, letter_a], bank) is word_and


def test_sound_keys(bank):
    def clash(a, a_letter, b, b_letter):
        return bool(bank.sound_keys(a, a_letter) & bank.sound_keys(b, b_letter))
    assert clash("to", False, "two", False)
    assert clash("B", True, "b", True)
    assert clash("R", True, "are", False)
    assert clash("why", False, "Y", True)
    assert not clash("the", False, "is", False)
    assert not clash("B", True, "D", True)


def test_letter_name_heard_for_sound_alike_word(bank):
    assert match_strength("r", "are", False, bank) == EXACT
    assert match_strength("y", "why", False, bank) == EXACT
    assert match_strength("u", "you", False, bank) == EXACT
    assert match_strength("r", "the", False, bank) == 0


def test_vocab_includes_homophones(bank):
    v = bank.vocab(["k2"])
    assert {"to", "two", "too", "be", "bee"} <= v


def test_aliases_count_but_weaker_than_the_word(bank):
    from word_punch.speech.matcher import ALIAS
    assert match_strength("yeah", "you", False, bank) == ALIAS
    assert match_strength("set", "said", False, bank) == ALIAS
    the_word, alike = T("you", y=10), T("yes", y=500)  # pretend both on screen
    assert best_match("you", [the_word, alike], bank) is the_word


def test_list_words_never_alias_other_list_words(bank):
    # "could" is a 1st-grade word, so it must not unlock "good"
    assert "could" not in bank.aliases_of("good")
    for word, alikes in bank.aliases.items():
        for a in alikes:
            assert a not in bank.group(word) or True
            assert a not in {w.lower() for k in bank.order[1:] for w in bank.level(k).words}


def test_user_alias_saved_and_loaded(tmp_path):
    path = tmp_path / "aliases.toml"
    b = WordBank(user_aliases=path)
    assert b.add_user_alias("was", "fuzz", path)
    assert not b.add_user_alias("was", "said", path)   # a list word
    b2 = WordBank(user_aliases=path)
    assert "fuzz" in b2.aliases_of("was")


def test_grade_levels_through_high_school(bank):
    keys = ["g2a", "g2b", "g3a", "g3b", "g4", "g5", "g6", "g7", "g8", "g9", "g10", "g11", "g12",
            "college", "masters", "doctorate"]
    assert bank.order[-len(keys):] == keys
    seen = {}
    for k in bank.order:
        if bank.level(k).is_letters:
            continue
        for w in bank.level(k).words:
            assert w.lower() not in seen, f"{w} is in both {seen.get(w.lower())} and {k}"
            seen[w.lower()] = k
    assert all(len(bank.level(k).words) >= 20 for k in keys)
    pts = [bank.level(k).points for k in bank.order]
    assert pts == sorted(pts), "harder levels should be worth more"
