"""Tests for jlawcite.ids.normalize (v2.0)."""
import pytest

from jlawcite.ids.normalize import (
    article_path_from_num_attr,
    make_article_key,
    make_attachment_key,
    make_hierarchy_key,
    parse_article_key,
    validate_article_key,
    validate_law_id,
)


# ---------- article_path conversions ----------
def test_article_path_simple():
    assert article_path_from_num_attr("10") == "10"
    assert article_path_from_num_attr("1") == "1"


def test_article_path_eda():
    assert article_path_from_num_attr("10_2") == "10-2"
    assert article_path_from_num_attr("4_3_2") == "4-3-2"


def test_article_path_kanji():
    assert article_path_from_num_attr("二") == "2"


# ---------- make_article_key (v1 forms still work) ----------
def test_make_paragraph_key_simple():
    k = make_article_key("340AC0000000033", "10", paragraph_num=1)
    assert k == "340AC0000000033_a10_p1"


def test_make_paragraph_key_eda():
    k = make_article_key("340AC0000000033", "10-2", paragraph_num=3)
    assert k == "340AC0000000033_a10-2_p3"


def test_make_suppl_paragraph_key():
    k = make_article_key(
        "340AC0000000033", "5", paragraph_num=1,
        section="suppl", suppl_tag="X",
    )
    assert k == "340AC0000000033_asup-X-5_p1"


# ---------- v2.0 — Article-level (no _p) ----------
def test_make_article_level_key_v2():
    k = make_article_key("340AC0000000033", "10", paragraph_num=None)
    assert k == "340AC0000000033_a10"


def test_make_suppl_article_level_key_v2():
    k = make_article_key(
        "340AC0000000033", "5", paragraph_num=None,
        section="suppl", suppl_tag="X",
    )
    assert k == "340AC0000000033_asup-X-5"


# ---------- v2.0 — Item key ----------
def test_make_item_key_v2():
    k = make_article_key("340AC0000000033", "10-2", paragraph_num=3, item_num=1)
    assert k == "340AC0000000033_a10-2_p3_i1"


def test_item_requires_paragraph():
    with pytest.raises(ValueError, match="item_num requires paragraph_num"):
        make_article_key("340AC0000000033", "10", paragraph_num=None, item_num=1)


# ---------- v2.0 — Attachment & Hierarchy ----------
def test_make_attachment_key():
    assert make_attachment_key("340AC0000000033", "1") == "340AC0000000033_at-1"
    assert make_attachment_key("340AC0000000033", "2-3") == "340AC0000000033_at-2-3"


def test_make_attachment_key_sanitizes():
    # Non-safe chars are replaced (defensive)
    assert make_attachment_key("340AC0000000033", "1 a") == "340AC0000000033_at-1-a"


def test_make_attachment_key_rejects_empty():
    with pytest.raises(ValueError):
        make_attachment_key("340AC0000000033", "")


def test_make_hierarchy_key():
    assert make_hierarchy_key("340AC0000000033", "P1C2") == "340AC0000000033_hP1C2"
    assert make_hierarchy_key("340AC0000000033", "P1C2S1") == "340AC0000000033_hP1C2S1"


def test_make_hierarchy_key_requires_uppercase_lead():
    with pytest.raises(ValueError):
        make_hierarchy_key("340AC0000000033", "1abc")


# ---------- validate_article_key ----------
def test_validate_accepts_v1_paragraph():
    validate_article_key("340AC0000000033_a10_p1")
    validate_article_key("340AC0000000033_a10-2_p3")


def test_validate_accepts_v2_article_no_paragraph():
    validate_article_key("340AC0000000033_a10")
    validate_article_key("340AC0000000033_a10-2")


def test_validate_accepts_v2_item():
    validate_article_key("340AC0000000033_a10_p1_i2")
    validate_article_key("340AC0000000033_a10-2_p3_i1")


def test_validate_accepts_v2_attachment():
    validate_article_key("340AC0000000033_at-1")
    validate_article_key("340AC0000000033_at-2-3")


def test_validate_accepts_v2_hierarchy():
    validate_article_key("340AC0000000033_hP1C2")


def test_validate_accepts_suppl():
    validate_article_key("340AC0000000033_asup-X-5")
    validate_article_key("340AC0000000033_asup-X-5_p1")
    validate_article_key("340AC0000000033_asup-X-5_p1_i2")


def test_validate_accepts_legacy_suffixes():
    """v1 backward compat: _add / _attachment / _DOC."""
    validate_article_key("340AC0000000033_a5_p1_add")
    validate_article_key("340AC0000000033_a5_p1_attachment")


def test_validate_rejects_japanese():
    with pytest.raises(ValueError, match="Japanese"):
        validate_article_key("340AC0000000033_a第10条_p1")


def test_validate_rejects_garbage():
    with pytest.raises(ValueError):
        validate_article_key("not_a_key")
    with pytest.raises(ValueError):
        validate_article_key("340AC0000000033_xyz_42")


def test_validate_law_id():
    validate_law_id("340AC0000000033")
    with pytest.raises(ValueError):
        validate_law_id("xx")
    with pytest.raises(ValueError):
        validate_law_id("12_AC_X")


# ---------- parse_article_key round-trips ----------
def test_parse_paragraph_round_trip():
    key = make_article_key("340AC0000000033", "10-2", paragraph_num=3)
    parsed = parse_article_key(key)
    assert parsed == {
        "kind": "paragraph",
        "law_id": "340AC0000000033",
        "art_path": "10-2",
        "paragraph_num": 3,
        "item_num": None,
        "section": "main",
        "suppl_tag": None,
        "suffix": None,
    }


def test_parse_article_v2():
    parsed = parse_article_key("340AC0000000033_a10-2")
    assert parsed["kind"] == "article"
    assert parsed["art_path"] == "10-2"
    assert parsed["paragraph_num"] is None


def test_parse_item_v2():
    parsed = parse_article_key("340AC0000000033_a10_p1_i2")
    assert parsed["kind"] == "item"
    assert parsed["paragraph_num"] == 1
    assert parsed["item_num"] == 2


def test_parse_suppl_paragraph():
    parsed = parse_article_key("340AC0000000033_asup-X-5_p1")
    assert parsed["kind"] == "paragraph"
    assert parsed["section"] == "suppl"
    assert parsed["suppl_tag"] == "X"
    assert parsed["art_path"] == "5"
    assert parsed["paragraph_num"] == 1


def test_parse_suppl_article_v2():
    parsed = parse_article_key("340AC0000000033_asup-X-5")
    assert parsed["kind"] == "article"
    assert parsed["section"] == "suppl"
    assert parsed["suppl_tag"] == "X"


def test_parse_attachment():
    parsed = parse_article_key("340AC0000000033_at-1")
    assert parsed == {
        "kind": "attachment",
        "law_id": "340AC0000000033",
        "annex_id": "1",
        "suffix": None,
    }


def test_parse_hierarchy():
    parsed = parse_article_key("340AC0000000033_hP1C2")
    assert parsed == {
        "kind": "hierarchy",
        "law_id": "340AC0000000033",
        "level_path": "P1C2",
        "suffix": None,
    }


def test_parse_legacy_suffix():
    parsed = parse_article_key("340AC0000000033_a5_p1_add")
    assert parsed["kind"] == "paragraph"
    assert parsed["suffix"] == "add"
