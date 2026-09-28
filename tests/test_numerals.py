"""Tests for jlawcite.numerals."""
from jlawcite.numerals import kanji_to_int


def test_arabic():
    assert kanji_to_int("10") == 10
    assert kanji_to_int("123") == 123


def test_pure_kanji_digits():
    assert kanji_to_int("一") == 1
    assert kanji_to_int("一二") == 12  # digit-string


def test_place_value():
    assert kanji_to_int("十") == 10
    assert kanji_to_int("二十") == 20
    assert kanji_to_int("百") == 100
    assert kanji_to_int("二百三十四") == 234
    assert kanji_to_int("千二百三十四") == 1234


def test_mixed_arabic_kanji():
    # '10の2' takes leading int
    assert kanji_to_int("10の2") == 10


def test_invalid():
    assert kanji_to_int("") is None
    assert kanji_to_int("abc") is None
