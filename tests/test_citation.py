"""Tests for jlawcite.citation."""
from jlawcite.citation import (
    extract_all,
    extract_attachment_refs,
    extract_delegations,
    extract_external,
    extract_internal,
    parse_eda,
)


def test_parse_eda():
    assert parse_eda("") == []
    assert parse_eda("の2") == [2]
    assert parse_eda("の2の3") == [2, 3]


def test_internal_simple():
    refs = extract_internal("第10条")
    assert len(refs) == 1
    assert refs[0].article_num == 10


def test_internal_with_eda_para():
    refs = extract_internal("第10条の2第3項")
    assert len(refs) == 1
    assert refs[0].article_num == 10
    assert refs[0].eda == [2]
    assert refs[0].paragraph == 3


def test_external_with_promulgation():
    text = "民事執行法（昭和五十四年法律第四号）第百九十五条"
    refs, _ = extract_external(text)
    assert len(refs) == 1
    assert refs[0].article_num == 195
    assert "民事執行法" in refs[0].law_name_raw


def test_external_strips_leading_noise():
    """の改正規定、 prefix is stripped post-match."""
    text = "の改正規定、租税特別措置法第10条"
    refs, _ = extract_external(text)
    assert len(refs) == 1
    assert refs[0].law_name_raw == "租税特別措置法"


def test_external_naked_tokens():
    """同法第N条 / 新法第N条 / bare 法第N条 are emitted as naked external refs
    (resolved by the caller), so their 第N条 is not misread as same-law."""
    text = "同法第10条と新法第5条を引く"
    refs, spans = extract_external(text)
    assert [(r.law_name_raw, r.article_num, r.naked) for r in refs] == [
        ("同法", 10, True), ("新法", 5, True)]
    assert extract_internal(text, mask_spans=spans) == []


def test_external_naked_bare_law():
    refs, _ = extract_external("（法第五十七条の十二第三項に規定する")
    assert refs[0].law_name_raw == "法"
    assert refs[0].article_path == "57-12" and refs[0].paragraph == 3
    # preceded by kanji → part of a longer law name, not a bare token
    refs, _ = extract_external("政令第五条")
    assert [r.naked for r in refs] == [False]


def test_suppl_and_branch_item_refs():
    refs = extract_internal("附則第三条第二項第十二号の二")
    assert refs[0].suppl and refs[0].article_path == "3"
    assert refs[0].item_path == "12-2"
    refs = extract_internal("附則第二項の規定")
    assert refs[0].suppl and refs[0].article_path == "0" and refs[0].paragraph == 2
    refs, _ = extract_external("所得税法附則第十五条")
    assert refs[0].law_name_raw == "所得税法" and refs[0].suppl


def test_extract_all_separates():
    text = "第10条と前条参照"
    out = extract_all(text)
    assert len(out["internal"]) == 1
    assert len(out["referential"]) == 1
    assert out["referential"][0].kind == "前条"


# ---------- Phase 4: attachment refs ----------
def test_attachment_ref_basic():
    refs = extract_attachment_refs("別表第1に掲げる")
    assert len(refs) == 1
    assert refs[0].kind == "別表"
    assert refs[0].annex_num == 1
    assert refs[0].annex_id == "1"


def test_attachment_ref_kanji():
    refs = extract_attachment_refs("別表第二参照")
    assert refs[0].annex_num == 2


def test_attachment_ref_with_eda():
    refs = extract_attachment_refs("別表第1の2")
    assert refs[0].annex_num == 1
    assert refs[0].annex_eda == 2
    assert refs[0].annex_id == "1-2"


def test_attachment_ref_multiple_kinds():
    refs = extract_attachment_refs("別表第1、様式第3号、別記第2")
    kinds = [r.kind for r in refs]
    assert "別表" in kinds and "様式" in kinds and "別記" in kinds


# ---------- Phase 4: delegation refs ----------
def test_delegation_basic():
    refs = extract_delegations("政令で定めるところにより")
    assert len(refs) == 1
    assert refs[0].target_kind == "政令"


def test_delegation_kinds():
    text = "省令で定める場合及び主務省令で定める方法、内閣府令で定める要件"
    refs = extract_delegations(text)
    kinds = {r.target_kind for r in refs}
    # all three should be detected; '主務省令' overlaps with '省令'
    assert "省令" in kinds or "主務省令" in kinds
    assert "内閣府令" in kinds


def test_delegation_no_match():
    refs = extract_delegations("第10条第1項に掲げる")
    assert refs == []


# ---------- Phase 4: amendments ----------
def test_amend_kaishi():
    from jlawcite.citation import extract_amendments
    refs = extract_amendments("第5条を次のように改める。")
    assert len(refs) == 1
    assert refs[0].article_num == 5


def test_amend_kezuru():
    from jlawcite.citation import extract_amendments
    refs = extract_amendments("第10条の2を削る。")
    assert refs[0].article_num == 10
    assert refs[0].eda == [2]


def test_amend_kuwaeru_simple():
    """Simple form: '第3条…を加える' is matched."""
    from jlawcite.citation import extract_amendments
    refs = extract_amendments("第3条第2項を加える。")
    assert len(refs) == 1
    assert refs[0].article_num == 3
    assert refs[0].paragraph == 2


def test_amend_insert_after_not_matched():
    """The compound form '第N条の次に次の一条を加える' is NOT matched —
    out-of-scope for v2.0 (creates a new article, not amends an existing one)."""
    from jlawcite.citation import extract_amendments
    assert extract_amendments("第3条の次に次の一条を加える。") == []


def test_amend_no_match():
    from jlawcite.citation import extract_amendments
    assert extract_amendments("第5条第1項を引用する") == []


def test_attachment_ref_bare_and_fullwidth():
    assert [r.attachment_slug for r in extract_attachment_refs("別表に掲げる")] == ["0"]
    assert [r.attachment_slug for r in extract_attachment_refs("様式第３号による")] == ["style-3"]
    assert extract_attachment_refs("別表中「甲」を") == []


def test_external_span_excludes_overcaptured_clause():
    """The clause before a short token is not part of the ref span, so
    referential tokens inside it (前項 / 同条) are still extracted."""
    from jlawcite.citation import extract_referential
    text = "前項の規定は、法第十条の場合に準用する。"
    refs, spans = extract_external(text)
    assert [(r.law_name_raw, r.raw, r.naked) for r in refs] == [("法", "法第十条", True)]
    assert [r.kind for r in extract_referential(text, spans)] == ["前項"]
    # katakana-ending names stay names
    refs, _ = extract_external("テスト法第三条")
    assert refs[0].law_name_raw == "テスト法" and not refs[0].naked


def test_enum_gap_pattern():
    from jlawcite.citation import ENUM_GAP_PAT
    for gap in ["、", "及び第十項、", "（第二号イを除く。）、", "本文、", "から", "第一項中「"]:
        assert ENUM_GAP_PAT.match(gap), gap
    for gap in ["の規定により", "」とあるのは「", "に規定する者及び"]:
        assert not ENUM_GAP_PAT.match(gap), gap
