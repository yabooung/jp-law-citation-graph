"""Japanese numeral conversion (kanji ↔ int).

Used by xml_parser, citation_extractor, ids.normalize.
Centralized here so all consumers share the same parsing semantics.
"""
from __future__ import annotations

import re

KANJI_DIGITS: dict[str, int] = {
    "〇": 0, "零": 0,
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9,
}

NUMERAL_RE = r"[\d一二三四五六七八九十百千〇零]+"


def kanji_to_int(s: str) -> int | None:
    """Convert kanji numeral to int.

    Supports:
        - Pure arabic digits: '10' → 10
        - Mixed forms: '10の2' → 10 (returns first integer chunk)
        - Kanji place-value: '千二百三十' → 1230
        - Kanji digit-string: '一二' → 12

    Returns None on parse failure.
    """
    if not s:
        return None
    if s.isdigit():
        return int(s)

    # Mixed forms — take leading integer
    m = re.match(r"^(\d+)", s)
    if m:
        return int(m.group(1))

    # Place-value (千百十)
    if "千" in s or "百" in s or "十" in s:
        total, cur = 0, 0
        for ch in s:
            if ch in KANJI_DIGITS:
                cur = KANJI_DIGITS[ch]
            elif ch == "十":
                total += (cur or 1) * 10
                cur = 0
            elif ch == "百":
                total += (cur or 1) * 100
                cur = 0
            elif ch == "千":
                total += (cur or 1) * 1000
                cur = 0
            else:
                return None
        return total + cur

    # Pure digit-string
    if all(ch in KANJI_DIGITS for ch in s):
        n = 0
        for ch in s:
            n = n * 10 + KANJI_DIGITS[ch]
        return n

    return None
