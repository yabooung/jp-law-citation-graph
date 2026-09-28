"""Tests for jlawcite.resolver."""
import json
import pytest

from jlawcite.resolver import (
    LawNameIndex,
    build_law_contexts,
    load_aliases,
    normalize_promulgation,
    resolve_referential,
)


# ---------- normalize_promulgation ----------
def test_normalize_kanji_arabic():
    assert normalize_promulgation("昭和四十年法律第三十三号") == "昭和40年法律第33号"


def test_normalize_strips_parens():
    assert normalize_promulgation("（昭和22年法律第26号）") == "昭和22年法律第26号"
    assert normalize_promulgation("(平成元年政令第5号)") == "平成1年政令第5号"


def test_normalize_arabic_passthrough():
    assert normalize_promulgation("令和5年法律第10号") == "令和5年法律第10号"


def test_normalize_returns_none_on_garbage():
    assert normalize_promulgation("foo") is None
    assert normalize_promulgation("") is None
    assert normalize_promulgation("第33号") is None


def test_normalize_handles_gengou():
    """元年 → 1."""
    assert normalize_promulgation("令和元年法律第1号") == "令和1年法律第1号"


# ---------- load_aliases ----------
# v3.0 contract: load_aliases returns primary file ∪ sibling jp_abbrev_kit.json
# ∪ hardcoded manual fallbacks. Tests check the *contributions* of the primary
# file rather than asserting strict equality.
def test_load_aliases_skips_metadata(tmp_path):
    p = tmp_path / "aliases.json"
    p.write_text(json.dumps({
        "_format": "metadata",
        "所税": "所得税法",
        "通則法": "国税通則法",
    }), encoding="utf-8")
    a = load_aliases(p)
    assert "_format" not in a
    assert a["所税"] == "所得税法"
    assert a["通則法"] == "国税通則法"


def test_load_aliases_missing_file(tmp_path):
    # No primary file and no sibling kit → only hardcoded manual fallbacks.
    a = load_aliases(tmp_path / "nope.json")
    assert a["農協法"] == "農業協同組合法"
    assert a["健保法"] == "健康保険法"


def test_load_aliases_primary_wins_over_kit(tmp_path):
    # Primary file's mapping must override the sibling kit (setdefault semantics).
    (tmp_path / "jp_abbrev_kit.json").write_text(
        json.dumps({"健保法": "別の法律"}), encoding="utf-8"
    )
    p = tmp_path / "aliases.json"
    p.write_text(json.dumps({"健保法": "健康保険法"}), encoding="utf-8")
    a = load_aliases(p)
    assert a["健保法"] == "健康保険法"


# ---------- LawNameIndex ----------
@pytest.fixture
def index() -> LawNameIndex:
    return LawNameIndex(
        canonical_to_id={
            "所得税法": "340AC0000000033",
            "国税通則法": "337AC0000000066",
        },
        promulgation_to_id={
            "昭和40年法律第33号": "340AC0000000033",
        },
        alias_to_canonical={
            "所税": "所得税法",
            "通則法": "国税通則法",
        },
    )


def test_resolve_canonical(index):
    r = index.resolve("所得税法")
    assert r.law_id == "340AC0000000033"
    assert r.via == "canonical"
    assert r.confidence == 1.0


def test_resolve_alias(index):
    r = index.resolve("所税")
    assert r.law_id == "340AC0000000033"
    assert r.via == "alias"
    assert r.confidence == 0.9


def test_resolve_promulgation_wins(index):
    """Promulgation match takes precedence even when name is wrong."""
    r = index.resolve("間違った名前", promulgation="昭和四十年法律第三十三号")
    assert r.law_id == "340AC0000000033"
    assert r.via == "promulgation"


def test_resolve_promulgation_arabic(index):
    r = index.resolve("", promulgation="（昭和40年法律第33号）")
    assert r.via == "promulgation"


def test_resolve_unknown(index):
    assert index.resolve("存在しない法") is None


# ---------- Phase 7: derived index features ----------
def test_resolve_old_name():
    """旧法令名 from CSV col[4] resolves to current law_id."""
    idx = LawNameIndex(
        canonical_to_id={"産業標準化法": "344AC0000000020"},
        promulgation_to_id={},
        alias_to_canonical={},
        old_to_id={"工業標準化法": "344AC0000000020"},
    )
    r = idx.resolve("工業標準化法")
    assert r.law_id == "344AC0000000020"
    assert r.via == "old_name"
    assert r.confidence == 0.95


def test_resolve_strips_leading_noise():
    """の改正規定、 etc. is stripped before lookup."""
    idx = LawNameIndex(
        canonical_to_id={"租税特別措置法": "340AC0000000026"},
        promulgation_to_id={}, alias_to_canonical={}, old_to_id={},
    )
    r = idx.resolve("の改正規定、租税特別措置法")
    assert r is not None
    assert r.law_id == "340AC0000000026"


def test_resolve_strips_prefix_新():
    idx = LawNameIndex(
        canonical_to_id={"租税特別措置法": "340AC0000000026"},
        promulgation_to_id={}, alias_to_canonical={}, old_to_id={},
    )
    r = idx.resolve("新租税特別措置法")
    assert r is not None
    assert r.via == "prefix_stripped"
    assert r.confidence == pytest.approx(0.95)  # 1.0 − 0.05


def test_resolve_strips_prefix_改正前():
    idx = LawNameIndex(
        canonical_to_id={"会社法": "417AC0000000086"},
        promulgation_to_id={}, alias_to_canonical={}, old_to_id={},
    )
    r = idx.resolve("改正前の会社法")
    assert r is not None
    assert r.via == "prefix_stripped"


def test_resolve_suffix_match():
    """When name doesn't match exactly, find longest canonical that's a suffix."""
    idx = LawNameIndex(
        canonical_to_id={"租税特別措置法": "340AC0000000026"},
        promulgation_to_id={}, alias_to_canonical={}, old_to_id={},
    )
    # '準用租税特別措置法' — suffix match works because no prefix rule covers '準用'
    # in _PREFIX_STRIP, so suffix match is the fallback
    r = idx.resolve("準用租税特別措置法")
    assert r is not None
    assert r.law_id == "340AC0000000026"
    # 'prefix_stripped' or 'suffix' both acceptable depending on pipeline order
    assert r.via in ("prefix_stripped", "suffix")


def test_resolve_suffix_picks_longest():
    """Two candidates ending in the input — take the longer (more specific)."""
    idx = LawNameIndex(
        canonical_to_id={
            "法": "X",                          # too short — would match anything
            "租税特別措置法": "340AC0000000026",
            "措置法": "Y",
        },
        promulgation_to_id={}, alias_to_canonical={}, old_to_id={},
    )
    r = idx.resolve("新租税特別措置法")
    assert r.law_id == "340AC0000000026"  # longest match wins


# ---------- Phase 7: 同法/新法 referential ----------
def test_referential_doha_uses_last_external():
    """同法 → last externally-cited law (Law node)."""
    r = resolve_referential(
        "同法", "L", "main", "1", 1, contexts={},
        last_external_law_id="340AC0000000033",
    )
    assert r is not None
    assert r.target_id == "340AC0000000033"
    assert r.fallback_level == "law_only"


def test_referential_doha_no_prior_external():
    """同法 with no prior external citation → unresolved."""
    r = resolve_referential(
        "同法", "L", "main", "1", 1, contexts={},
        last_external_law_id=None,
    )
    assert r is None


def test_referential_shinpou_uses_src_law():
    """新法 (in Suppl context) → current document's law."""
    r = resolve_referential(
        "新法", "L_currentlaw", "suppl", "5", 1, contexts={},
    )
    assert r is not None
    assert r.target_id == "L_currentlaw"
    assert r.fallback_level == "law_only"


def test_referential_honnpou_self_returns_none():
    """本法 / 本令 / 本規則 → self-ref, drop edge."""
    for kind in ("本法", "本令", "本規則"):
        assert resolve_referential(kind, "L", "main", "1", 1, contexts={}) is None


# ---------- ReferentialResolver ----------
@pytest.fixture
def contexts():
    records = [
        {"type": "Article", "id": "L_a1", "law_id": "L", "article_path": "1",
         "section": "main"},
        {"type": "Paragraph", "id": "L_a1_p1", "law_id": "L", "article_path": "1",
         "paragraph_num": 1, "section": "main"},
        {"type": "Paragraph", "id": "L_a1_p2", "law_id": "L", "article_path": "1",
         "paragraph_num": 2, "section": "main"},
        {"type": "Article", "id": "L_a2", "law_id": "L", "article_path": "2",
         "section": "main"},
        {"type": "Paragraph", "id": "L_a2_p1", "law_id": "L", "article_path": "2",
         "paragraph_num": 1, "section": "main"},
        {"type": "Article", "id": "L_a3", "law_id": "L", "article_path": "3",
         "section": "main"},
    ]
    return build_law_contexts(records)


def test_zenjyou_previous_article(contexts):
    """前条 from 第2条 → 第1条."""
    r = resolve_referential("前条", "L", "main", "2", 1, contexts)
    assert r.target_id == "L_a1"


def test_jijou_next_article(contexts):
    r = resolve_referential("次条", "L", "main", "2", 1, contexts)
    assert r.target_id == "L_a3"


def test_doujou_same_article(contexts):
    r = resolve_referential("同条", "L", "main", "2", 1, contexts)
    assert r.target_id == "L_a2"


def test_zenkou_previous_paragraph(contexts):
    """前項 from 第1条第2項 → 第1条第1項."""
    r = resolve_referential("前項", "L", "main", "1", 2, contexts)
    assert r.target_id == "L_a1_p1"


def test_doukou_same_paragraph(contexts):
    r = resolve_referential("同項", "L", "main", "1", 2, contexts)
    assert r.target_id == "L_a1_p2"


def test_zenjyou_at_first_returns_none(contexts):
    """前条 from 第1条 → 없음."""
    assert resolve_referential("前条", "L", "main", "1", 1, contexts) is None


def test_jijou_at_last_returns_none(contexts):
    assert resolve_referential("次条", "L", "main", "3", 1, contexts) is None


def test_self_ref_returns_none(contexts):
    assert resolve_referential("本条", "L", "main", "1", 1, contexts) is None
    assert resolve_referential("本項", "L", "main", "1", 1, contexts) is None


def test_unknown_kind_returns_none(contexts):
    """同号/前各号 not yet supported."""
    assert resolve_referential("同号", "L", "main", "1", 1, contexts) is None


def test_eda_sort_order():
    """枝番 sort: 第10条の2 between 第10条 and 第11条."""
    records = [
        {"type": "Article", "id": "L_a10", "law_id": "L", "article_path": "10",
         "section": "main"},
        {"type": "Article", "id": "L_a10-2", "law_id": "L", "article_path": "10-2",
         "section": "main"},
        {"type": "Article", "id": "L_a11", "law_id": "L", "article_path": "11",
         "section": "main"},
    ]
    ctx = build_law_contexts(records)
    # 前条 from 11 → 10-2 (not 10)
    r = resolve_referential("前条", "L", "main", "11", None, ctx)
    assert r.target_id == "L_a10-2"
    r = resolve_referential("前条", "L", "main", "10-2", None, ctx)
    assert r.target_id == "L_a10"


# ---------- v3.2: abbreviation definitions / promulgation issuers ----------
def test_extract_abbrev_definitions():
    from jlawcite.resolver import extract_abbrev_definitions
    text = "この省令において使用する用語は、水先法（昭和二十四年法律第百二十一号。以下「法」という。）において"
    assert extract_abbrev_definitions(text) == [("法", "昭和二十四年法律第百二十一号", "水先法")]
    # non-law abbreviations are ignored
    assert extract_abbrev_definitions("独立行政法人（以下「機構」という。）") == []


def test_resolve_abbrev_definition_kinds():
    from jlawcite.resolver import (
        ABBREV_AMENDING, ABBREV_PRE_AMENDMENT, LawNameIndex, resolve_abbrev_definition)
    idx = LawNameIndex(canonical_to_id={"農地法": "327AC0000000229"},
                       promulgation_to_id={}, alias_to_canonical={}, old_to_id={})
    assert resolve_abbrev_definition("法", None, "農地法", idx) == "327AC0000000229"
    assert resolve_abbrev_definition("旧農地法", None, "改正前の農地法", idx) == ABBREV_PRE_AMENDMENT
    assert resolve_abbrev_definition(
        "改正法", "令和三年法律第一号", "農地法の一部を改正する法律", idx) == ABBREV_AMENDING


def test_normalize_promulgation_qualified_issuer():
    assert normalize_promulgation("平成十七年法務省令第十八号") == "平成17年法務省令第18号"
    assert normalize_promulgation("令和元年厚生労働省令第一号") == "令和1年厚生労働省令第1号"


def test_suffix_and_trim_respect_compound_boundary():
    """A compound / repealed name must not collapse onto a shorter current law
    ('失業保険法' → '保険法'), but clause over-grab is still trimmed."""
    idx = LawNameIndex(canonical_to_id={"保険法": "A", "租税特別措置法": "B", "国民年金法": "C"},
                       promulgation_to_id={}, alias_to_canonical={}, old_to_id={})
    assert idx.resolve("失業保険法") is None
    assert idx.resolve("第六十二条中租税特別措置法").law_id == "B"
    assert idx.resolve("旧国民年金法").law_id == "C"
