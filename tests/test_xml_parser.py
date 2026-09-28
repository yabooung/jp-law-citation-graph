"""Tests for jlawcite.parser (v2.0)."""
from jlawcite.parser import detect_law_type, extract_mst_id, parse_law_xml


def _types(records):
    return [r.type for r in records]


def _by_id(records):
    return {r.id: r for r in records}


def test_detect_law_type_act():
    assert detect_law_type("340AC0000000033") == "act"


def test_detect_law_type_cabinet_order():
    assert detect_law_type("340CO0000000096") == "cabinet_order"


def test_detect_law_type_ministerial():
    assert detect_law_type("340M50000040011") == "ministerial_ordinance"
    assert detect_law_type("332M00000040015") == "ministerial_ordinance"


def test_detect_law_type_unknown():
    assert detect_law_type("999XX0000000000") == "other"


def test_extract_mst_id():
    assert extract_mst_id("340AC0000000033_19650401_339AC0000000033") == "19650401_339AC0000000033"
    assert extract_mst_id("340AC0000000033") == ""


def _write_xml(tmp_path, law_id_dir: str, content: str):
    xml_dir = tmp_path / law_id_dir
    xml_dir.mkdir()
    xml_file = xml_dir / f"{xml_dir.name}.xml"
    xml_file.write_text(content, encoding="utf-8")
    return xml_file


# ---------- Minimal: 1 Article + 1 Paragraph ----------
def test_parse_minimal_xml(tmp_path):
    xml = _write_xml(tmp_path, "999AC0000000001_20250101_000", """<?xml version="1.0" encoding="UTF-8"?>
<Law>
  <LawTitle>テスト法</LawTitle>
  <MainProvision>
    <Article Num="1">
      <ArticleTitle>第一条</ArticleTitle>
      <Paragraph Num="1">
        <ParagraphSentence>
          <Sentence>これはテスト本文。</Sentence>
        </ParagraphSentence>
      </Paragraph>
    </Article>
  </MainProvision>
</Law>
""")
    records, edges, stats = parse_law_xml(xml, "テスト法")

    # v2: Law + Article + Paragraph = 3 records
    assert _types(records) == ["Law", "Article", "Paragraph"]
    by_id = _by_id(records)
    assert "999AC0000000001" in by_id
    assert "999AC0000000001_a1" in by_id
    assert "999AC0000000001_a1_p1" in by_id

    article = by_id["999AC0000000001_a1"]
    paragraph = by_id["999AC0000000001_a1_p1"]
    assert article.text == ""  # Article has no body in v2
    assert "テスト本文" in paragraph.text
    assert paragraph.parent_id == article.id
    assert article.parent_id == "999AC0000000001"

    # Edges: Law→Article, Article→Paragraph
    assert ("999AC0000000001", "999AC0000000001_a1", "CONTAINS") in edges
    assert ("999AC0000000001_a1", "999AC0000000001_a1_p1", "CONTAINS") in edges
    assert len(edges) == 2

    assert stats.articles == 1
    assert stats.paragraphs == 1


# ---------- Multi-paragraph + Suppl + 枝番 ----------
def test_parse_xml_with_eda_and_suppl(tmp_path):
    xml = _write_xml(tmp_path, "999AC0000000002_20250101_000", """<?xml version="1.0" encoding="UTF-8"?>
<Law>
  <LawTitle>テスト法2</LawTitle>
  <MainProvision>
    <Article Num="10_2">
      <ArticleTitle>第十条の二</ArticleTitle>
      <Paragraph Num="1">
        <ParagraphSentence><Sentence>本文1。</Sentence></ParagraphSentence>
      </Paragraph>
      <Paragraph Num="2">
        <ParagraphSentence><Sentence>本文2。</Sentence></ParagraphSentence>
      </Paragraph>
    </Article>
  </MainProvision>
  <SupplProvision AmendLawNum="令和五年法律第十号">
    <Article Num="1">
      <ArticleTitle>附則第一条</ArticleTitle>
      <Paragraph Num="1">
        <ParagraphSentence><Sentence>附則本文。</Sentence></ParagraphSentence>
      </Paragraph>
    </Article>
  </SupplProvision>
</Law>
""")
    records, edges, stats = parse_law_xml(xml)
    by_id = _by_id(records)

    # Main: Article 10-2 + 2 Paragraphs
    assert "999AC0000000002_a10-2" in by_id
    assert "999AC0000000002_a10-2_p1" in by_id
    assert "999AC0000000002_a10-2_p2" in by_id

    # Suppl: SupplArticle + SupplParagraph
    suppl_article_ids = [k for k in by_id if k.startswith("999AC0000000002_asup-")
                         and "_p" not in k]
    suppl_para_ids = [k for k in by_id if k.startswith("999AC0000000002_asup-")
                      and "_p1" in k]
    assert len(suppl_article_ids) == 1
    assert len(suppl_para_ids) == 1
    assert by_id[suppl_article_ids[0]].type == "SupplArticle"
    assert by_id[suppl_para_ids[0]].type == "SupplParagraph"

    # Stats
    assert stats.articles == 1
    assert stats.paragraphs == 2
    assert stats.suppl_articles == 1
    assert stats.suppl_paragraphs == 1


# ---------- Items (号) ----------
def test_parse_xml_with_items(tmp_path):
    xml = _write_xml(tmp_path, "999AC0000000003_20250101_000", """<?xml version="1.0" encoding="UTF-8"?>
<Law>
  <LawTitle>テスト法3</LawTitle>
  <MainProvision>
    <Article Num="2">
      <ArticleTitle>第二条</ArticleTitle>
      <Paragraph Num="1">
        <ParagraphSentence><Sentence>各号に掲げる。</Sentence></ParagraphSentence>
        <Item Num="1">
          <ItemTitle>一</ItemTitle>
          <ItemSentence><Sentence>第一号本文</Sentence></ItemSentence>
        </Item>
        <Item Num="2">
          <ItemTitle>二</ItemTitle>
          <ItemSentence><Sentence>第二号本文</Sentence></ItemSentence>
        </Item>
      </Paragraph>
    </Article>
  </MainProvision>
</Law>
""")
    records, edges, stats = parse_law_xml(xml)
    by_id = _by_id(records)

    assert "999AC0000000003_a2_p1_i1" in by_id
    assert "999AC0000000003_a2_p1_i2" in by_id
    item1 = by_id["999AC0000000003_a2_p1_i1"]
    assert item1.type == "Item"
    assert item1.parent_id == "999AC0000000003_a2_p1"
    assert "第一号本文" in item1.text
    assert stats.items == 2

    # Paragraph text excludes item bodies (scoped collection)
    para = by_id["999AC0000000003_a2_p1"]
    assert "各号に掲げる" in para.text
    assert "第一号本文" not in para.text


# ---------- Hierarchy (Part/Chapter/Section) ----------
def test_parse_xml_with_hierarchy(tmp_path):
    xml = _write_xml(tmp_path, "999AC0000000004_20250101_000", """<?xml version="1.0" encoding="UTF-8"?>
<Law>
  <LawTitle>テスト法4</LawTitle>
  <MainProvision>
    <Part Num="1">
      <PartTitle>第一編 総則</PartTitle>
      <Chapter Num="1">
        <ChapterTitle>第一章 通則</ChapterTitle>
        <Article Num="1">
          <ArticleTitle>第一条</ArticleTitle>
          <Paragraph Num="1">
            <ParagraphSentence><Sentence>本文。</Sentence></ParagraphSentence>
          </Paragraph>
        </Article>
      </Chapter>
    </Part>
  </MainProvision>
</Law>
""")
    records, edges, stats = parse_law_xml(xml)
    by_id = _by_id(records)

    assert "999AC0000000004_hP1" in by_id
    assert "999AC0000000004_hP1C1" in by_id
    part = by_id["999AC0000000004_hP1"]
    chap = by_id["999AC0000000004_hP1C1"]
    article = by_id["999AC0000000004_a1"]

    assert part.type == "Hierarchy"
    assert part.parent_id == "999AC0000000004"
    assert chap.parent_id == part.id
    assert article.parent_id == chap.id

    assert stats.hierarchy == 2

    # Each non-Law node has exactly one parent edge
    children = [t for s, t, _ in edges]
    assert len(children) == len(set(children))


# ---------- Synthetic Paragraph for Article without Paragraph child ----------
def test_synthetic_paragraph(tmp_path):
    xml = _write_xml(tmp_path, "999AC0000000005_20250101_000", """<?xml version="1.0" encoding="UTF-8"?>
<Law>
  <LawTitle>テスト法5</LawTitle>
  <MainProvision>
    <Article Num="1">
      <ArticleTitle>第一条</ArticleTitle>
      <Sentence>段落タグなし本文。</Sentence>
    </Article>
  </MainProvision>
</Law>
""")
    records, edges, stats = parse_law_xml(xml)
    by_id = _by_id(records)

    # Article + synthetic Paragraph
    assert "999AC0000000005_a1" in by_id
    assert "999AC0000000005_a1_p1" in by_id
    para = by_id["999AC0000000005_a1_p1"]
    assert "段落タグなし本文" in para.text


# ---------- Attachment (Appdx*) ----------
def test_parse_xml_with_attachment(tmp_path):
    xml = _write_xml(tmp_path, "999AC0000000006_20250101_000", """<?xml version="1.0" encoding="UTF-8"?>
<Law>
  <LawTitle>テスト法6</LawTitle>
  <MainProvision>
    <Article Num="1">
      <ArticleTitle>第一条</ArticleTitle>
      <Paragraph Num="1">
        <ParagraphSentence><Sentence>本文。</Sentence></ParagraphSentence>
      </Paragraph>
    </Article>
  </MainProvision>
  <AppdxTable Num="1">
    <AppdxTableTitle>別表第1（第10条関係）</AppdxTableTitle>
    <Sentence>表の中身</Sentence>
  </AppdxTable>
</Law>
""")
    records, edges, stats = parse_law_xml(xml)
    by_id = _by_id(records)

    assert "999AC0000000006_at-1" in by_id
    att = by_id["999AC0000000006_at-1"]
    assert att.type == "Attachment"
    assert att.parent_id == "999AC0000000006"
    assert "別表第1" in att.title
    assert stats.attachments == 1


# ---------- AppdxStyle 様式: text spread across non-Sentence tags ----------
def test_attachment_style_collects_non_sentence_tags(tmp_path):
    xml = _write_xml(tmp_path, "999AC0000000007_20250101_000", """<?xml version="1.0" encoding="UTF-8"?>
<Law>
  <LawTitle>テスト法7</LawTitle>
  <MainProvision>
    <Article Num="1">
      <ArticleTitle>第一条</ArticleTitle>
      <Paragraph Num="1">
        <ParagraphSentence><Sentence>本文。</Sentence></ParagraphSentence>
      </Paragraph>
    </Article>
  </MainProvision>
  <AppdxStyle Num="1">
    <AppdxStyleTitle>(別記)第一号様式</AppdxStyleTitle>
    <RelatedArticleNum>(第三条関係)</RelatedArticleNum>
    <StyleStruct>
      <StyleStructTitle>記載要領</StyleStructTitle>
      <Style>
        <Fig src="./pict/001.jpg" />
      </Style>
      <Remarks>
        <RemarksLabel>備考</RemarksLabel>
        <Sentence>用紙はA4とする。</Sentence>
      </Remarks>
    </StyleStruct>
  </AppdxStyle>
</Law>
""")
    records, _, _ = parse_law_xml(xml)
    by_id = _by_id(records)
    att = by_id["999AC0000000007_at-style-1"]
    assert att.type == "Attachment"
    # All non-Sentence text-bearing tags collected
    assert "(第三条関係)" in att.text
    assert "記載要領" in att.text
    assert "備考" in att.text
    assert "用紙はA4とする" in att.text


# ---------- AppdxFormat 書式: predominantly Fig-only is OK to remain empty ----------
def test_attachment_format_with_fig_and_title(tmp_path):
    xml = _write_xml(tmp_path, "999AC0000000008_20250101_000", """<?xml version="1.0" encoding="UTF-8"?>
<Law>
  <LawTitle>テスト法8</LawTitle>
  <MainProvision>
    <Article Num="1">
      <ArticleTitle>第一条</ArticleTitle>
      <Paragraph Num="1">
        <ParagraphSentence><Sentence>本文。</Sentence></ParagraphSentence>
      </Paragraph>
    </Article>
  </MainProvision>
  <AppdxFormat Num="1">
    <AppdxFormatTitle>第１号書式</AppdxFormatTitle>
    <RelatedArticleNum>(第五条関係)</RelatedArticleNum>
    <FormatStruct>
      <FormatStructTitle>申請書</FormatStructTitle>
      <Format>
        <Fig src="./pict/002.jpg" />
      </Format>
    </FormatStruct>
  </AppdxFormat>
</Law>
""")
    records, _, _ = parse_law_xml(xml)
    by_id = _by_id(records)
    att = by_id["999AC0000000008_at-format-1"]
    assert "(第五条関係)" in att.text
    assert "申請書" in att.text


def test_slugify_annex_id_kanji_titles():
    from jlawcite.parser import _slugify_annex_id
    assert _slugify_annex_id("第一号様式") == "1"
    assert _slugify_annex_id("別表第十二") == "12"
    assert _slugify_annex_id("様式第一の二") == "1-2"
    assert _slugify_annex_id("第一号様式の二") == "1-2"
    assert _slugify_annex_id("別表第三（第五条関係）") == "3"
    assert _slugify_annex_id("別表第1の2") == "1-2"


def test_inline_markup_text_is_kept(tmp_path):
    """<Ruby>/<Sup>/<QuoteStruct> inside a Sentence must not truncate it; Ruby
    readings (<Rt>) are dropped; nested Subitems are not duplicated."""
    xml = _write_xml(tmp_path, "999AC0000000009_20250101_000", """<?xml version="1.0" encoding="UTF-8"?>
<Law>
  <LawBody>
  <LawTitle Abbrev="激甚法,激甚災害法">激<Ruby>甚<Rt>じん</Rt></Ruby>災害法</LawTitle>
  <MainProvision>
    <Article Num="1">
      <ArticleTitle>第一条</ArticleTitle>
      <Paragraph Num="1">
        <ParagraphSentence><Sentence>失<Ruby>踪<Rt>そう</Rt></Ruby>の宣告は、十<Sup>2</Sup>日以内とする。</Sentence></ParagraphSentence>
        <Item Num="1">
          <ItemTitle>一</ItemTitle>
          <ItemSentence><Sentence>次に掲げるもの</Sentence></ItemSentence>
          <Subitem1 Num="1">
            <Subitem1Title>イ</Subitem1Title>
            <Subitem1Sentence><Sentence>甲</Sentence></Subitem1Sentence>
            <Subitem2 Num="1">
              <Subitem2Title>（１）</Subitem2Title>
              <Subitem2Sentence><Sentence>乙</Sentence></Subitem2Sentence>
            </Subitem2>
          </Subitem1>
        </Item>
      </Paragraph>
    </Article>
  </MainProvision>
  </LawBody>
</Law>
""")
    records, _, _ = parse_law_xml(xml)
    by_id = _by_id(records)
    law = by_id["999AC0000000009"]
    assert law.title == "激甚災害法"
    assert law.raw_attributes["abbrevs"] == ["激甚法", "激甚災害法"]
    assert by_id["999AC0000000009_a1_p1"].text == "失踪の宣告は、十2日以内とする。"
    assert by_id["999AC0000000009_a1_p1_i1"].text.split("\n") == [
        "一", "次に掲げるもの", "イ", "甲", "（１）", "乙"]
