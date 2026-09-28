"""e-Gov 法令 XML → graph records (v2.0).

See `docs/GRAPH_SCHEMA_V2.md` §2 for the authoritative node model.

v2 emit set:
    Law             — single per XML
    Hierarchy       — Part(編)/Chapter(章)/Section(節)/Subsection(款)/Division(目)
    Article         — 主条文 (no body text; body lives on Paragraphs)
    Paragraph       — 項 (carries text)
    Item            — 号 (carries text)
    SupplArticle    — 附則 article-level
    SupplParagraph  — 附則 項
    Attachment      — Appdx* (別表/様式/別記/附録/目録)

CONTAINS edges form a strict tree rooted at Law (P4 in design doc).

Hierarchy path encoding (single uppercase letter per level):
    Part      → P
    Chapter   → C
    Section   → S
    Subsection→ U
    Division  → D
e.g. `P1C2S1` = 第1編 第2章 第1節
"""
from __future__ import annotations

import csv
import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterator

from .ids.normalize import (
    article_path_from_num_attr,
    make_article_key,
    make_attachment_key,
    make_hierarchy_key,
)
from .numerals import kanji_to_int

# Mapping from XML tag → single-letter hierarchy code.
_HIERARCHY_LEVELS: dict[str, str] = {
    "Part": "P",
    "Chapter": "C",
    "Section": "S",
    "Subsection": "U",
    "Division": "D",
}

_HIERARCHY_TITLE_TAG: dict[str, str] = {
    "Part": "PartTitle",
    "Chapter": "ChapterTitle",
    "Section": "SectionTitle",
    "Subsection": "SubsectionTitle",
    "Division": "DivisionTitle",
}

# Appendix tag prefix — covers AppdxTable, AppdxStyle, AppdxFormat, AppdxNote,
# AppdxFig, AppdxNotice, Appdx (bare).
_APPDX_PREFIX = "Appdx"


@dataclass
class ParsedRecord:
    """One parsed entity. Maps directly to GraphNode at write-time."""
    id: str
    title: str
    type: str  # see module docstring for legal types
    text: str = ""
    law_id: str | None = None
    parent_id: str | None = None
    article_path: str | None = None
    paragraph_num: int | None = None
    item_num: int | None = None
    suppl_tag: str | None = None
    section: str | None = None
    is_active: bool = True
    jurisdiction: str = "JP"
    raw_attributes: dict = field(default_factory=dict)


@dataclass
class ParseStats:
    law: str
    articles: int = 0
    paragraphs: int = 0
    items: int = 0
    suppl_articles: int = 0
    suppl_paragraphs: int = 0
    suppl_items: int = 0
    hierarchy: int = 0
    attachments: int = 0
    skipped: int = 0
    dup_ids: int = 0
    error: str | None = None


# ---------------------------------------------------------------------------
# Type detection / mst extraction (unchanged from v1)
# ---------------------------------------------------------------------------
def detect_law_type(law_id: str) -> str:
    """Map e-Gov law_id to law_type code."""
    if len(law_id) < 5:
        return "other"
    type_code = law_id[3:5]
    if type_code == "AC":
        return "act"
    if type_code == "CO":
        return "cabinet_order"
    if type_code in ("M5", "M0", "M4"):
        return "ministerial_ordinance"
    if type_code.startswith("F"):
        return "ministerial_ordinance"
    if type_code == "DF":
        return "imperial_order"
    if type_code in ("DT", "IO"):
        return "other"
    return "other"


def extract_mst_id(xml_dir_name: str) -> str:
    parts = xml_dir_name.split("_", 1)
    return parts[1] if len(parts) > 1 else ""


# ---------------------------------------------------------------------------
# Text collection helpers (scoped — no descendant leakage)
# ---------------------------------------------------------------------------
def _text(elem: ET.Element | None) -> str:
    """Full text of an element including inline markup (<Ruby>, <Sup>, <Sub>,
    <Line>, <ArithFormula>, <QuoteStruct> …). Ruby readings (<Rt>) are dropped
    so 「激<Ruby>甚<Rt>じん</Rt></Ruby>災害」 reads 激甚災害. `elem.text` alone
    stops at the first child element and silently truncates the sentence."""
    if elem is None:
        return ""
    parts = [elem.text or ""]
    for ch in elem:
        if ch.tag != "Rt":
            parts.append(_text(ch))
        parts.append(ch.tail or "")
    return "".join(parts)


def _iter_top(elem: ET.Element, tags: frozenset[str] | set[str]):
    """Yield descendants whose tag is in `tags`, without descending into them
    (a <Sentence> inside a <QuoteStruct> inside a <Sentence> is yielded once,
    as part of its outer sentence)."""
    for ch in elem:
        if ch.tag in tags:
            yield ch
        else:
            yield from _iter_top(ch, tags)


_SENTENCE = frozenset({"Sentence"})
_SUBITEM_RE = re.compile(r"Subitem\d+$")


def _direct_paragraph_text(para_elem: ET.Element) -> str:
    """Concatenate Paragraph's direct sentences. Excludes nested Item/Subitem."""
    parts: list[str] = []
    for ps in para_elem.findall("ParagraphSentence"):
        parts += [_text(x) for x in _iter_top(ps, _SENTENCE)]
    # Some XMLs put <Sentence> directly under Paragraph
    parts += [_text(x) for x in para_elem.findall("Sentence")]
    return "\n".join(p for p in parts if p).strip()


def _item_text(item_elem: ET.Element) -> str:
    """Concatenate Item text including its Subitem* descendants (flattened)."""
    parts: list[str] = []
    title = _text(item_elem.find("ItemTitle"))
    if title:
        parts.append(title.strip())
    for ist in item_elem.findall("ItemSentence"):
        parts += [_text(x) for x in _iter_top(ist, _SENTENCE)]
    parts += [_text(x) for x in item_elem.findall("Sentence")]
    # Subitem* are flattened (not emitted as separate nodes in v2.0), in
    # document order; each level contributes only its own title + sentence.
    for sub in item_elem.iter():
        if sub is item_elem or not _SUBITEM_RE.match(sub.tag):
            continue
        sub_title = _text(sub.find(f"{sub.tag}Title"))
        if sub_title:
            parts.append(sub_title.strip())
        sent = sub.find(f"{sub.tag}Sentence")
        if sent is not None:
            parts += [_text(x) for x in _iter_top(sent, _SENTENCE)]
    return "\n".join(p for p in parts if p).strip()


def _hierarchy_title(elem: ET.Element, tag: str) -> str:
    title_tag = _HIERARCHY_TITLE_TAG.get(tag, "")
    return _text(elem.find(title_tag)).strip() if title_tag else ""


# Text-bearing tags found inside Appdx* payloads.
# AppdxTable mostly nests <Sentence>; AppdxStyle/AppdxFormat/AppdxNote use
# StyleStruct/FormatStruct/NoteStruct wrappers whose inner text often lives
# in non-Sentence tags (RelatedArticleNum, *StructTitle, RemarksLabel, etc.).
# <Fig> is excluded — image-only reference, no text content.
_ATTACHMENT_TEXT_TAGS = frozenset({
    "Sentence",
    "RelatedArticleNum",
    "RemarksLabel",
    "ItemTitle",
    "StyleStructTitle",
    "FormatStructTitle",
    "NoteStructTitle",
    "FigStructTitle",
    "TableStructTitle",
    "ArithFormulaNum",
})


def _attachment_text(elem: ET.Element) -> str:
    """Best-effort flatten of Appdx* contents into a single text blob.

    Walks the entire subtree and collects text from a known set of leaf
    text-bearing tags. The Appdx* title element is captured separately by
    `_emit_attachment` and may be re-collected here as the recursive walk
    does not exclude it; that's acceptable for downstream search/citation.
    """
    parts: list[str] = []
    for sub in _iter_top(elem, _ATTACHMENT_TEXT_TAGS):
        t = _text(sub).strip()
        if t:
            parts.append(t)
    return "\n".join(parts).strip()


# Attachment ID prefix per Appdx* kind, so 別表第一 and 様式第一 of the same
# law get distinct IDs (`_at-1` vs `_at-style-1`). 別表 keeps the bare form.
_ATTACHMENT_KIND_PREFIX = {
    "AppdxTable": "",
    "AppdxStyle": "style-",
    "AppdxFormat": "format-",
    "AppdxNote": "note-",
    "AppdxFig": "fig-",
    "AppdxNotice": "notice-",
    "Appdx": "appdx-",
}


def attachment_kind_prefix(tag: str) -> str:
    return _ATTACHMENT_KIND_PREFIX.get(tag, "other-")


def _attachment_subtype(tag: str) -> str:
    if tag.endswith("Table"):
        return "別表"
    if tag.endswith("Style") or tag.endswith("Format"):
        return "様式"
    if tag.endswith("Note"):
        return "別記"
    if tag.endswith("Fig"):
        return "別図"
    if tag.endswith("Notice"):
        return "別記"
    return "other"


def _parse_pnum(elem: ET.Element, fallback: int) -> int:
    raw = elem.get("Num", str(fallback))
    if raw.isdigit():
        return int(raw)
    n = kanji_to_int(raw)
    return n if n is not None else fallback


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------
def parse_law_xml(
    xml_path: Path,
    law_name: str | None = None,
) -> tuple[list[ParsedRecord], list[tuple[str, str, str]], ParseStats]:
    """Parse one e-Gov XML.

    Returns:
        (records, edges, stats) where each edge is (source, target, "CONTAINS").
        CITES edges are produced separately by the citation pass in
        `pipeline/ingest_full.py`.
    """
    xml_dir_name = xml_path.parent.name
    law_id = xml_path.stem.split("_")[0]
    mst_id = extract_mst_id(xml_dir_name)

    records: list[ParsedRecord] = []
    edges: list[tuple[str, str, str]] = []
    stats = ParseStats(law=law_name or law_id)

    try:
        tree = ET.parse(xml_path)
    except ET.ParseError as e:
        stats.error = f"XML parse error: {e}"
        return [], [], stats

    root = tree.getroot()
    law_title_elem = root.find(".//LawTitle")
    title = (_text(law_title_elem) or law_name or law_id).strip()
    law_num = _text(root.find(".//LawNum")).strip()  # promulgation_no

    # ---- Law node (root) ----
    law_attrs = {"mst_id": mst_id, "law_title": title}
    if law_num:
        law_attrs["promulgation_no"] = law_num
    # Official short names, e.g. Abbrev="激甚法,激甚災害法"
    abbrev = (law_title_elem.get("Abbrev") if law_title_elem is not None else "") or ""
    if abbrev:
        law_attrs["abbrevs"] = [a.strip() for a in abbrev.split(",") if a.strip()]
    records.append(ParsedRecord(
        id=law_id,
        title=title,
        type="Law",
        law_id=law_id,
        raw_attributes=law_attrs,
    ))

    seen_ids: set[str] = {law_id}
    ctx = _Context(
        law_id=law_id, mst_id=mst_id, law_title=title,
        records=records, edges=edges, seen=seen_ids, stats=stats,
    )

    # ---- MainProvision (descend recursively — XML wraps it in <LawBody>) ----
    for main_prov in root.iter("MainProvision"):
        _walk_main(main_prov, parent_id=law_id, hpath="", ctx=ctx)

    # ---- SupplProvision ----
    for spi, sp in enumerate(root.iter("SupplProvision"), start=1):
        amend_law_num = sp.get("AmendLawNum", "")
        # AmendLawNum is 和暦 kanji, so this is almost always `sp{i}`. Never
        # fall back to the Extract flag ("true") — that collided across blocks.
        amend_tag = re.sub(r"[^A-Za-z0-9]+", "", amend_law_num)[:16] or f"sp{spi}"
        ctx.suppl_amend_law_num = amend_law_num
        _walk_container(sp, parent_id=law_id, section="suppl",
                        suppl_tag=amend_tag, ctx=ctx)
        ctx.suppl_amend_law_num = None

    # ---- Attachments (Appdx*) ----
    for elem in root.iter():
        # Appdx* containers only — not their AppdxTableTitle-style children
        if not elem.tag.startswith(_APPDX_PREFIX) or elem.tag.endswith("Title"):
            continue
        _emit_attachment(elem, ctx)

    return records, edges, stats


# ---------------------------------------------------------------------------
# Walking implementation
# ---------------------------------------------------------------------------
@dataclass
class _Context:
    """Mutable bag passed through recursive walk."""
    law_id: str
    mst_id: str
    law_title: str
    records: list[ParsedRecord]
    edges: list[tuple[str, str, str]]
    seen: set[str]
    stats: ParseStats
    suppl_amend_law_num: str | None = None  # AmendLawNum of the SupplProvision being walked


# Article path used for the synthetic Article that holds <Paragraph>s placed
# directly under MainProvision / SupplProvision (no <Article> wrapper). 第0条
# never occurs in real statutes, so it cannot collide.
SYNTHETIC_ART_PATH = "0"


def _walk_container(elem: ET.Element, parent_id: str, section: str,
                    suppl_tag: str | None, ctx: _Context) -> None:
    """Emit Articles found anywhere below a SupplProvision (incl. Chapter
    wrappers) plus a synthetic Article for bare <Paragraph> children."""
    direct_paras = [ch for ch in elem if ch.tag == "Paragraph"]
    if direct_paras:
        _emit_synthetic_article(direct_paras, parent_id, section, suppl_tag, ctx)
    for child in elem:
        if child.tag == "Article":
            _emit_article(child, parent_id=parent_id, section=section,
                          suppl_tag=suppl_tag, ctx=ctx)
        elif child.tag in _HIERARCHY_LEVELS:
            _walk_container(child, parent_id, section, suppl_tag, ctx)


def _emit_synthetic_article(paras: list[ET.Element], parent_id: str, section: str,
                            suppl_tag: str | None, ctx: _Context) -> None:
    art = ET.Element("Article", Num=SYNTHETIC_ART_PATH)
    art.extend(paras)
    title = "附則" if section == "suppl" else ctx.law_title
    _emit_article(art, parent_id=parent_id, section=section,
                  suppl_tag=suppl_tag, ctx=ctx, title=title, synthetic=True)


def _walk_main(elem: ET.Element, parent_id: str, hpath: str, ctx: _Context) -> None:
    """Recursive walk of MainProvision. Emits Hierarchy nodes and routes Articles."""
    direct_paras = [ch for ch in elem if ch.tag == "Paragraph"]
    if direct_paras:
        _emit_synthetic_article(direct_paras, parent_id, "main", None, ctx)
    for child in elem:
        tag = child.tag
        if tag in _HIERARCHY_LEVELS:
            num_attr = child.get("Num", "")
            level_code = _HIERARCHY_LEVELS[tag]
            # '1_2' (第一章の二) → '1-2'; must not collapse onto '1'
            num_str = (article_path_from_num_attr(num_attr) if num_attr else None) \
                or num_attr or "X"
            new_hpath = f"{hpath}{level_code}{num_str}"
            try:
                hid = make_hierarchy_key(ctx.law_id, new_hpath)
            except ValueError:
                ctx.stats.skipped += 1
                continue
            if hid in ctx.seen:
                # Still walk the subtree so its Articles are not lost.
                ctx.stats.dup_ids += 1
                _walk_main(child, parent_id=hid, hpath=new_hpath, ctx=ctx)
                continue
            ctx.seen.add(hid)
            ctx.records.append(ParsedRecord(
                id=hid,
                type="Hierarchy",
                title=_hierarchy_title(child, tag) or f"{tag} {num_str}",
                law_id=ctx.law_id,
                parent_id=parent_id,
                section="main",
                raw_attributes={"mst_id": ctx.mst_id, "law_title": ctx.law_title,
                                "level": tag, "level_path": new_hpath},
            ))
            ctx.edges.append((parent_id, hid, "CONTAINS"))
            ctx.stats.hierarchy += 1
            _walk_main(child, parent_id=hid, hpath=new_hpath, ctx=ctx)
        elif tag == "Article":
            _emit_article(child, parent_id=parent_id, section="main",
                          suppl_tag=None, ctx=ctx)
        # Other tags (LawTitle, EnactStatement, etc.) are ignored at this level.


def _emit_article(
    art_elem: ET.Element,
    parent_id: str,
    section: str,
    suppl_tag: str | None,
    ctx: _Context,
    title: str | None = None,
    synthetic: bool = False,
) -> None:
    """Emit Article + child Paragraphs (+ child Items) under the given parent."""
    art_num_str = art_elem.get("Num", "")
    art_path = article_path_from_num_attr(art_num_str)
    if art_path is None:
        ctx.stats.skipped += 1
        return

    art_title = (title or _text(art_elem.find("ArticleTitle")) or f"第{art_path}条").strip()
    base_attrs = {"mst_id": ctx.mst_id, "law_title": ctx.law_title}
    if section == "suppl" and ctx.suppl_amend_law_num:
        base_attrs["suppl_amend_law_num"] = ctx.suppl_amend_law_num
    article_id = make_article_key(
        law_id=ctx.law_id, art_path=art_path, paragraph_num=None,
        section=section, suppl_tag=suppl_tag,
    )
    if article_id in ctx.seen:
        ctx.stats.dup_ids += 1
        return
    ctx.seen.add(article_id)

    art_type = "Article" if section == "main" else "SupplArticle"
    ctx.records.append(ParsedRecord(
        id=article_id,
        type=art_type,
        title=art_title,
        text="",  # Article-level has no body text in v2 (body lives on paragraphs)
        law_id=ctx.law_id,
        parent_id=parent_id,
        article_path=art_path,
        suppl_tag=suppl_tag,
        section=section,
        raw_attributes={**base_attrs, **({"synthetic": True} if synthetic else {})},
    ))
    ctx.edges.append((parent_id, article_id, "CONTAINS"))
    if section == "main":
        ctx.stats.articles += 1
    else:
        ctx.stats.suppl_articles += 1

    paragraphs = art_elem.findall("Paragraph")
    if not paragraphs:
        # Synthesize a single Paragraph for body-bearing Articles with no <Paragraph>
        synthetic_text = _direct_paragraph_text(art_elem)
        if synthetic_text:
            _emit_paragraph_synthetic(article_id, art_path, synthetic_text,
                                      section, suppl_tag, ctx)
        return

    for idx, para in enumerate(paragraphs, start=1):
        pnum = _parse_pnum(para, idx)
        para_id = make_article_key(
            law_id=ctx.law_id, art_path=art_path, paragraph_num=pnum,
            section=section, suppl_tag=suppl_tag,
        )
        if para_id in ctx.seen:
            ctx.stats.dup_ids += 1
            continue
        ctx.seen.add(para_id)

        para_type = "Paragraph" if section == "main" else "SupplParagraph"
        text = _direct_paragraph_text(para)
        node_title = art_title if pnum == 1 else f"{art_title} 第{pnum}項"
        ctx.records.append(ParsedRecord(
            id=para_id,
            type=para_type,
            title=node_title,
            text=text,
            law_id=ctx.law_id,
            parent_id=article_id,
            article_path=art_path,
            paragraph_num=pnum,
            suppl_tag=suppl_tag,
            section=section,
            raw_attributes=dict(base_attrs),
        ))
        ctx.edges.append((article_id, para_id, "CONTAINS"))
        if section == "main":
            ctx.stats.paragraphs += 1
        else:
            ctx.stats.suppl_paragraphs += 1

        # Items (号)
        for item in para.findall("Item"):
            inum_str = item.get("Num", "")
            # '12_2' (第十二号の二) → item_path '12-2', item_num 12
            item_path = article_path_from_num_attr(inum_str) if inum_str else None
            if item_path is None:
                ctx.stats.skipped += 1
                continue
            inum = int(item_path.split("-")[0])
            item_id = make_article_key(
                law_id=ctx.law_id, art_path=art_path, paragraph_num=pnum,
                item_num=item_path, section=section, suppl_tag=suppl_tag,
            )
            if item_id in ctx.seen:
                ctx.stats.dup_ids += 1
                continue
            ctx.seen.add(item_id)
            ctx.records.append(ParsedRecord(
                id=item_id,
                type="Item",
                title=f"{node_title} 第{item_path.replace('-', 'の')}号",
                text=_item_text(item),
                law_id=ctx.law_id,
                parent_id=para_id,
                article_path=art_path,
                paragraph_num=pnum,
                item_num=inum,
                suppl_tag=suppl_tag,
                section=section,
                raw_attributes={**base_attrs, "item_path": item_path},
            ))
            ctx.edges.append((para_id, item_id, "CONTAINS"))
            if section == "main":
                ctx.stats.items += 1
            else:
                ctx.stats.suppl_items += 1


def _emit_paragraph_synthetic(
    article_id: str,
    art_path: str,
    text: str,
    section: str,
    suppl_tag: str | None,
    ctx: _Context,
) -> None:
    """Emit a synthetic Paragraph 1 when the Article has body text but no <Paragraph>."""
    para_id = make_article_key(
        law_id=ctx.law_id, art_path=art_path, paragraph_num=1,
        section=section, suppl_tag=suppl_tag,
    )
    if para_id in ctx.seen:
        ctx.stats.dup_ids += 1
        return
    ctx.seen.add(para_id)
    para_type = "Paragraph" if section == "main" else "SupplParagraph"
    ctx.records.append(ParsedRecord(
        id=para_id,
        type=para_type,
        title=f"第{art_path}条",
        text=text,
        law_id=ctx.law_id,
        parent_id=article_id,
        article_path=art_path,
        paragraph_num=1,
        suppl_tag=suppl_tag,
        section=section,
        raw_attributes={"mst_id": ctx.mst_id, "law_title": ctx.law_title,
                        "synthetic": True},
    ))
    ctx.edges.append((article_id, para_id, "CONTAINS"))
    if section == "main":
        ctx.stats.paragraphs += 1
    else:
        ctx.stats.suppl_paragraphs += 1


def _emit_attachment(elem: ET.Element, ctx: _Context) -> None:
    """Emit an Attachment node for an Appdx* element."""
    # Stable annex_id: use Num attr if present, else position-based.
    raw_num = elem.get("Num") or elem.get("AppdxTableTitle") or ""
    if not raw_num:
        # Look for explicit title element
        for tag in ("AppdxTableTitle", "AppdxStyleTitle",
                    "AppdxFormatTitle", "AppdxNoteTitle", "AppdxFigTitle",
                    "AppdxNoticeTitle", "AppdxTitle"):
            t = _text(elem.find(tag))
            if t:
                raw_num = t
                break
    if not raw_num:
        ctx.stats.skipped += 1
        return
    annex_slug = _slugify_annex_id(raw_num)
    if not annex_slug:
        ctx.stats.skipped += 1
        return
    try:
        att_id = make_attachment_key(ctx.law_id, attachment_kind_prefix(elem.tag) + annex_slug)
    except ValueError:
        ctx.stats.skipped += 1
        return
    if att_id in ctx.seen:
        ctx.stats.dup_ids += 1
        return
    ctx.seen.add(att_id)

    title_text = ""
    for tag in ("AppdxTableTitle", "AppdxStyleTitle", "AppdxFormatTitle",
                "AppdxNoteTitle", "AppdxFigTitle", "AppdxNoticeTitle",
                "AppdxTitle"):
        t = _text(elem.find(tag))
        if t:
            title_text = t.strip()
            break
    if not title_text:
        title_text = raw_num.strip()

    ctx.records.append(ParsedRecord(
        id=att_id,
        type="Attachment",
        title=title_text or annex_slug,
        text=_attachment_text(elem),
        law_id=ctx.law_id,
        parent_id=ctx.law_id,
        section="main",
        raw_attributes={"mst_id": ctx.mst_id, "law_title": ctx.law_title,
                        "appdx_tag": elem.tag,
                        "attachment_subtype": _attachment_subtype(elem.tag)},
    ))
    ctx.edges.append((ctx.law_id, att_id, "CONTAINS"))
    ctx.stats.attachments += 1


_ANNEX_KANJI_NUM = re.compile(r"[〇一二三四五六七八九十百千]+")


def _slugify_annex_id(raw: str) -> str:
    """Convert annex identifier to a safe slug for IDs.

    Matches the `AttachmentRef.annex_id` convention ('1', '1-2') so that
    別表第一 / 第一号様式の二 resolve from 「別表第一」-style references.
    Parenthetical notes like （第五条関係） are ignored. An annex without any
    number (a law's sole 別表 / 別記様式) gets '0'.
    """
    raw = unicodedata.normalize("NFKC", raw)  # 様式第２ → 様式第2
    raw = re.sub(r"[（(][^）)]*[）)]", "", raw)
    s = re.sub(r"[^\w]", "-", raw, flags=re.UNICODE)
    s = re.sub(r"-+", "-", s).strip("-")
    nums = re.findall(r"[0-9]+", s)
    if nums:
        return "-".join(nums)
    # Kanji numerals: first number (+ optional の-branch)
    m = _ANNEX_KANJI_NUM.search(raw)
    if m:
        n = kanji_to_int(m.group(0))
        # の-branch may follow directly (様式第一の二) or after 号様式 (第一号様式の二)
        e = re.search(r"の([〇一二三四五六七八九十百千]+)", raw[m.end():])
        eda = kanji_to_int(e.group(1)) if e else None
        if n is not None:
            return f"{n}-{eda}" if eda is not None else str(n)
    # Last resort: ascii-only chars; no number at all → sole annex '0'
    ascii_safe = re.sub(r"[^A-Za-z0-9_-]", "", s).strip("-_")
    return ascii_safe or "0"


# ---------------------------------------------------------------------------
# Version discovery (current vs pending)
# ---------------------------------------------------------------------------
# The e-Gov bulk dump ships every *known* version of a law: the one currently
# in force plus any 未施行 versions already promulgated. Directory names are
# `{law_id}_{YYYYMMDD 施行日}_{amend_law_id}`; the CSV 施行日 column is in
# 和暦 (e.g. 令和九年六月二十三日) so we take dates from the directory name and
# join CSV rows via the 本文URL tail (`.../{law_id}/{YYYYMMDD}_{amend_law_id}`).
@dataclass
class LawVersion:
    law_id: str
    mst_id: str              # "{YYYYMMDD}_{amend_law_id}"
    enforcement_date: str    # YYYYMMDD
    xml_path: Path
    law_name: str = ""
    amend_law_name: str = ""
    amend_law_num: str = ""
    amend_promulgation_date: str = ""   # 和暦, as given by e-Gov
    enforcement_note: str = ""          # 施行日備考 (e.g. 政令で定める日)
    url: str = ""


def list_law_versions(xml_base: Path, csv_fp: Path | None = None) -> dict[str, list[LawVersion]]:
    """All versions per law_id, sorted oldest → newest by (施行日, amend id)."""
    meta: dict[str, list[str]] = {}
    if csv_fp and csv_fp.exists():
        with csv_fp.open(encoding="utf-8-sig") as f:
            r = csv.reader(f)
            next(r, None)  # header
            for row in r:
                if len(row) < 13:
                    continue
                meta[f"{row[11]}_{row[12].rstrip('/').rsplit('/', 1)[-1]}"] = row

    by_law: dict[str, list[LawVersion]] = {}
    for d in xml_base.iterdir():
        xml_path = d / f"{d.name}.xml"
        if not d.is_dir() or not xml_path.exists():
            continue
        law_id, _, mst_id = d.name.partition("_")
        v = LawVersion(law_id=law_id, mst_id=mst_id,
                       enforcement_date=mst_id.split("_")[0] or "00000000",
                       xml_path=xml_path)
        row = meta.get(d.name)
        if row:
            v.law_name, v.amend_law_name, v.amend_law_num = row[2], row[6], row[7]
            v.amend_promulgation_date, v.enforcement_note, v.url = row[8], row[10], row[12]
        by_law.setdefault(law_id, []).append(v)

    for versions in by_law.values():
        versions.sort(key=lambda v: v.mst_id)
    return by_law


def split_current_pending(
    versions: list[LawVersion], as_of: str,
) -> tuple[LawVersion, list[LawVersion], bool]:
    """(current, pending, in_force) for one law as of YYYYMMDD `as_of`.

    current = latest version with 施行日 <= as_of. A law with no version in
    force yet falls back to its earliest version with in_force=False, so it
    still appears in the corpus.
    """
    past = [v for v in versions if v.enforcement_date <= as_of]
    pending = [v for v in versions if v.enforcement_date > as_of]
    if past:
        return past[-1], pending, True
    return pending[0], pending[1:], False


def find_law_xmls(
    xml_base: Path, csv_fp: Path | None = None, as_of: str | None = None,
) -> Iterator[tuple[str, Path]]:
    """Yield (law_name, xml_path) for the version of each law in force at
    `as_of` (YYYYMMDD, default today)."""
    as_of = as_of or date.today().strftime("%Y%m%d")
    for law_id, versions in list_law_versions(xml_base, csv_fp).items():
        current, _, _ = split_current_pending(versions, as_of)
        yield (current.law_name or law_id, current.xml_path)
