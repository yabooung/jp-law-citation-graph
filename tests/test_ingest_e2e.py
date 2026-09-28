"""End-to-end ingest on a two-law mini corpus (an Act and its 施行令).

Covers the v3.2 structure and resolution rules in one place: Article-less
provisions, branch chapters/items, per-block 附則 scopes, kind-aware
attachment ids, defined abbreviations (以下「法」という。), bare/同法 tokens,
enumeration carryover, 同条 antecedents, 前号, pending versions.
"""
import json
import sys

import pytest

from jlawcite.pipeline import ingest_full

ACT_ID = "999AC0000000010"
ORD_ID = "999CO0000000010"

ACT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Law>
  <LawNum>令和二年法律第十号</LawNum>
  <LawBody>
    <LawTitle>テスト法</LawTitle>
    <MainProvision>
      <Chapter Num="1">
        <ChapterTitle>第一章　総則</ChapterTitle>
        <Article Num="1">
          <ArticleTitle>第一条</ArticleTitle>
          <Paragraph Num="1"><ParagraphSentence><Sentence>この法律は、試験を目的とする。</Sentence></ParagraphSentence></Paragraph>
        </Article>
        <Article Num="2">
          <ArticleTitle>第二条</ArticleTitle>
          <Paragraph Num="1">
            <ParagraphSentence><Sentence>第一条及び第三条の規定は、附則第二条の場合に準用する。</Sentence></ParagraphSentence>
            <Item Num="1"><ItemTitle>一</ItemTitle><ItemSentence><Sentence>甲</Sentence></ItemSentence></Item>
            <Item Num="1_2"><ItemTitle>一の二</ItemTitle><ItemSentence><Sentence>乙</Sentence></ItemSentence></Item>
            <Item Num="2"><ItemTitle>二</ItemTitle><ItemSentence><Sentence>前号に掲げるもの</Sentence></ItemSentence></Item>
          </Paragraph>
        </Article>
      </Chapter>
      <Chapter Num="1_2">
        <ChapterTitle>第一章の二　雑則</ChapterTitle>
        <Article Num="3">
          <ArticleTitle>第三条</ArticleTitle>
          <Paragraph Num="1"><ParagraphSentence><Sentence>本文。</Sentence></ParagraphSentence></Paragraph>
          <Paragraph Num="2"><ParagraphSentence><Sentence>前項の規定は、別表第一及び様式第一に掲げる者に適用する。</Sentence></ParagraphSentence></Paragraph>
        </Article>
      </Chapter>
    </MainProvision>
    <SupplProvision>
      <Article Num="1"><ArticleTitle>第一条</ArticleTitle>
        <Paragraph Num="1"><ParagraphSentence><Sentence>この法律は、公布の日から施行する。</Sentence></ParagraphSentence></Paragraph>
      </Article>
      <Article Num="2"><ArticleTitle>第二条</ArticleTitle>
        <Paragraph Num="1"><ParagraphSentence><Sentence>経過措置。</Sentence></ParagraphSentence></Paragraph>
      </Article>
    </SupplProvision>
    <SupplProvision AmendLawNum="令和三年法律第一号" Extract="true">
      <Paragraph Num="1"><ParagraphSentence><Sentence>この法律は、令和三年四月一日から施行する。</Sentence></ParagraphSentence></Paragraph>
    </SupplProvision>
    <SupplProvision Extract="true">
      <Paragraph Num="1"><ParagraphSentence><Sentence>抄録。</Sentence></ParagraphSentence></Paragraph>
    </SupplProvision>
    <AppdxTable><AppdxTableTitle>別表第一（第三条関係）</AppdxTableTitle><Sentence>表</Sentence></AppdxTable>
    <AppdxStyle><AppdxStyleTitle>様式第１</AppdxStyleTitle><Sentence>様式</Sentence></AppdxStyle>
  </LawBody>
</Law>
"""

ORD_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Law>
  <LawNum>令和二年政令第二十号</LawNum>
  <LawBody>
    <LawTitle>テスト法施行令</LawTitle>
    <MainProvision>
      <Article Num="1">
        <ArticleTitle>第一条</ArticleTitle>
        <Paragraph Num="1"><ParagraphSentence><Sentence>テスト法（令和二年法律第十号。以下「法」という。）第二条第一項の政令で定める者は、法第三条第二項及び第一条に規定する者とする。</Sentence></ParagraphSentence></Paragraph>
      </Article>
      <Article Num="2">
        <ArticleTitle>第二条</ArticleTitle>
        <Paragraph Num="1"><ParagraphSentence><Sentence>テスト法第三条の規定は、同条第二項に規定する者及び同法第一条の者に適用する。</Sentence></ParagraphSentence></Paragraph>
        <Paragraph Num="2"><ParagraphSentence><Sentence>第一条の規定は、前項の場合について準用する。この場合において、同条中「者」とあるのは「法人」と読み替えるものとする。</Sentence></ParagraphSentence></Paragraph>
      </Article>
    </MainProvision>
  </LawBody>
</Law>
"""


def _write(base, dirname, xml):
    d = base / dirname
    d.mkdir(parents=True)
    (d / f"{dirname}.xml").write_text(xml, encoding="utf-8")


@pytest.fixture(scope="module")
def out(tmp_path_factory):
    base = tmp_path_factory.mktemp("raw")
    _write(base, f"{ACT_ID}_20200401_000000000000000", ACT_XML)
    _write(base, f"{ACT_ID}_20990101_508AC0000000001", ACT_XML)   # pending version
    _write(base, f"{ORD_ID}_20200401_000000000000000", ORD_XML)
    out_dir = tmp_path_factory.mktemp("parsed")
    argv = sys.argv
    sys.argv = ["ingest_full", "--input", str(base), "--output", str(out_dir),
                "--as-of", "20260101", "--aliases", str(base / "none.json")]
    try:
        ingest_full.main()
    finally:
        sys.argv = argv
    nodes = {n["id"]: n for n in map(json.loads, (out_dir / "jp_nodes.jsonl").open(encoding="utf-8"))}
    cites = [json.loads(l) for l in (out_dir / "jp_cites_edges.jsonl").open(encoding="utf-8")]
    attaches = [json.loads(l) for l in (out_dir / "jp_attaches_edges.jsonl").open(encoding="utf-8")]
    pending = [json.loads(l) for l in (out_dir / "jp_pending_versions.jsonl").open(encoding="utf-8")]
    return nodes, {(e["source"], e["target"]): e for e in cites}, attaches, pending


def test_structures_are_not_dropped(out):
    nodes, *_ = out
    # Article under 第一章の二 (was lost when Chapter '1_2' collided with '1')
    assert f"{ACT_ID}_hC1-2" in nodes
    assert nodes[f"{ACT_ID}_a3"]["parent_id"] == f"{ACT_ID}_hC1-2"
    # Branch item 第一号の二
    assert nodes[f"{ACT_ID}_a2_p1_i1-2"]["item_path"] == "1-2"
    # Article-less 附則 blocks → synthetic article '0', unique tag per block
    assert f"{ACT_ID}_asup-sp2-0_p1" in nodes
    assert f"{ACT_ID}_asup-sp3-0_p1" in nodes
    assert nodes[f"{ACT_ID}_asup-sp2-0_p1"]["suppl_amend_law_num"] == "令和三年法律第一号"
    # Kind-aware attachment ids, full-width digits normalized
    assert f"{ACT_ID}_at-1" in nodes and f"{ACT_ID}_at-style-1" in nodes


def test_version_selection_and_pending(out):
    nodes, _, _, pending = out
    law = nodes[ACT_ID]
    assert law["enforcement_date"] == "20200401"
    assert law["is_active"] is True
    assert law["next_enforcement_date"] == "20990101"
    assert [p["enforcement_date"] for p in pending] == ["20990101"]


def test_internal_and_suppl_refs(out):
    _, cites, _, _ = out
    src = f"{ACT_ID}_a2_p1"
    assert (src, f"{ACT_ID}_a1") in cites
    assert (src, f"{ACT_ID}_a3") in cites
    # 附則第二条 → the original 附則 block, not 本則 第二条
    assert (src, f"{ACT_ID}_asup-sp1-2") in cites
    assert (src, f"{ACT_ID}_a2") not in cites


def test_referential_item_and_paragraph(out):
    _, cites, attaches, _ = out
    assert (f"{ACT_ID}_a2_p1_i2", f"{ACT_ID}_a2_p1_i1-2") in cites      # 前号
    assert (f"{ACT_ID}_a3_p2", f"{ACT_ID}_a3_p1") in cites              # 前項
    assert {(e["source"], e["target"]) for e in attaches} == {
        (f"{ACT_ID}_a3_p2", f"{ACT_ID}_at-1"),
        (f"{ACT_ID}_a3_p2", f"{ACT_ID}_at-style-1"),
    }


def test_cross_law_resolution(out):
    _, cites, _, _ = out
    s1 = f"{ORD_ID}_a1_p1"
    # テスト法（令和二年法律第十号。以下「法」という。）第二条第一項
    assert (s1, f"{ACT_ID}_a2_p1") in cites
    # 法第三条第二項 — defined abbreviation, not the 施行令's own 第三条
    assert cites[(s1, f"{ACT_ID}_a3_p2")]["extracted_from"].endswith("defined_abbrev")
    # 及び第一条 — enumeration carryover keeps テスト法
    assert cites[(s1, f"{ACT_ID}_a1")]["extracted_from"] == "INTERNAL_PAT/enum_carryover"
    assert (s1, f"{ORD_ID}_a1") not in cites

    s2 = f"{ORD_ID}_a2_p1"
    # 同条第二項 → antecedent テスト法第三条, paragraph 2
    assert cites[(s2, f"{ACT_ID}_a3_p2")]["extracted_from"] == "REFERENTIAL/同条"
    # 同法第一条 → last external law
    assert (s2, f"{ACT_ID}_a1") in cites


def test_same_article_skips_paragraph_antecedents(out):
    """「第一条の規定は、前項の場合について準用する。…同条中」: 同条 is 第一条,
    not the article of 前項 (the source's own 第二条)."""
    _, cites, _, _ = out
    src = f"{ORD_ID}_a2_p2"
    assert cites[(src, f"{ORD_ID}_a1")]["extracted_from"] in ("INTERNAL_PAT", "REFERENTIAL/同条")
    assert (src, f"{ORD_ID}_a2") not in cites


def test_adjacent_articles():
    from jlawcite.pipeline.ingest_full import _adjacent_articles
    assert _adjacent_articles("10", "11") and _adjacent_articles("10", "10-2")
    assert _adjacent_articles("10-2", "11") and _adjacent_articles("10-2", "10-3")
    assert not _adjacent_articles("1", "14")          # 抄 附則: 前条 of 14 is not 1
    assert not _adjacent_articles("0", "1")


def test_same_law_token_matches_kind():
    from types import SimpleNamespace
    from jlawcite.pipeline.ingest_full import _resolve_naked
    hist = [ACT_ID, ORD_ID]                      # テスト法 …, then テスト法施行令 …
    tok = lambda n: SimpleNamespace(law_name_raw=n)
    assert _resolve_naked(tok("同法"), "X", hist, {}, {})[0].law_id == ACT_ID
    assert _resolve_naked(tok("同令"), "X", hist, {}, {})[0].law_id == ORD_ID
    assert _resolve_naked(tok("同規則"), "X", hist, {}, {})[0] is None


def test_pre_amendment_prefix_detection():
    from jlawcite.pipeline.ingest_full import _names_pre_amendment
    assert _names_pre_amendment("その効力を有するとされる旧不動産登記法", "不動産登記法")
    assert _names_pre_amendment("改正前の消防法", "消防法")
    assert not _names_pre_amendment("改正後の消防法", "消防法")
    assert not _names_pre_amendment("旧令による共済組合等からの年金受給者のための特別措置法",
                                    "旧令による共済組合等からの年金受給者のための特別措置法")
