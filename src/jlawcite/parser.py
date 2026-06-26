"""e-Gov 法令 XML → graph records.

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
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
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
def _direct_paragraph_text(para_elem: ET.Element) -> str:
    """Concatenate Paragraph's direct sentences. Excludes nested Item/Subitem."""
    parts: list[str] = []
    for ps in para_elem.findall("ParagraphSentence"):
        for s in ps.findall("Sentence"):
            if s.text:
                parts.append(s.text)
    # Some XMLs put <Sentence> directly under Paragraph
    for s in para_elem.findall("Sentence"):
        if s.text:
            parts.append(s.text)
    return "\n".join(parts).strip()


def _item_text(item_elem: ET.Element) -> str:
    """Concatenate Item text including its Subitem* descendants (flattened)."""
    parts: list[str] = []
    title = item_elem.findtext("ItemTitle") or ""
    if title:
        parts.append(title.strip())
    for ist in item_elem.findall("ItemSentence"):
        for s in ist.iter("Sentence"):
            if s.text:
                parts.append(s.text)
    for s in item_elem.findall("Sentence"):
        if s.text:
            parts.append(s.text)
    # Subitem* are flattened (not emitted as separate nodes)
    for sub in item_elem.iter():
        if sub is item_elem:
            continue
        if sub.tag.startswith("Subitem"):
            sub_title = sub.findtext("Subitem1Title") or sub.findtext("Subitem2Title") \
                        or sub.findtext("Subitem3Title") or sub.findtext("Subitem4Title") or ""
            if sub_title:
                parts.append(sub_title.strip())
            for s in sub.iter("Sentence"):
                if s.text:
                    parts.append(s.text)
    return "\n".join(p for p in parts if p).strip()


def _hierarchy_title(elem: ET.Element, tag: str) -> str:
    title_tag = _HIERARCHY_TITLE_TAG.get(tag, "")
    return (elem.findtext(title_tag) or "").strip()


def _attachment_text(elem: ET.Element) -> str:
    """Best-effort flatten of Appdx* contents into a single text blob."""
    parts: list[str] = []
    for s in elem.iter("Sentence"):
        if s.text:
            parts.append(s.text)
    return "\n".join(parts).strip()


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
    title = (root.findtext(".//LawTitle") or law_name or law_id).strip()
    law_num = (root.findtext(".//LawNum") or "").strip()  # promulgation_no

    # ---- Law node (root) ----
    law_attrs = {"mst_id": mst_id, "law_title": title}
    if law_num:
        law_attrs["promulgation_no"] = law_num
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
        amend_law = sp.get("AmendLawNum", "") or sp.get("Extract", "") or f"sp{spi}"
        amend_tag = re.sub(r"[^A-Za-z0-9]+", "", amend_law)[:16] or f"sp{spi}"
        for art in sp.findall("Article"):
            _emit_article(art, parent_id=law_id, section="suppl",
                          suppl_tag=amend_tag, ctx=ctx)

    # ---- Attachments (Appdx*) ----
    for elem in root.iter():
        if not elem.tag.startswith(_APPDX_PREFIX):
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


def _walk_main(elem: ET.Element, parent_id: str, hpath: str, ctx: _Context) -> None:
    """Recursive walk of MainProvision. Emits Hierarchy nodes and routes Articles."""
    for child in elem:
        tag = child.tag
        if tag in _HIERARCHY_LEVELS:
            num_attr = child.get("Num", "")
            level_code = _HIERARCHY_LEVELS[tag]
            num_int = kanji_to_int(num_attr) if num_attr else None
            num_str = str(num_int) if num_int is not None else (num_attr or "X")
            new_hpath = f"{hpath}{level_code}{num_str}"
            try:
                hid = make_hierarchy_key(ctx.law_id, new_hpath)
            except ValueError:
                ctx.stats.skipped += 1
                continue
            if hid in ctx.seen:
                ctx.stats.dup_ids += 1
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
) -> None:
    """Emit Article + child Paragraphs (+ child Items) under the given parent."""
    art_num_str = art_elem.get("Num", "")
    art_path = article_path_from_num_attr(art_num_str)
    if art_path is None:
        ctx.stats.skipped += 1
        return

    art_title = (art_elem.findtext("ArticleTitle") or f"第{art_path}条").strip()
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
        raw_attributes={"mst_id": ctx.mst_id, "law_title": ctx.law_title},
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
            raw_attributes={"mst_id": ctx.mst_id, "law_title": ctx.law_title},
        ))
        ctx.edges.append((article_id, para_id, "CONTAINS"))
        if section == "main":
            ctx.stats.paragraphs += 1
        else:
            ctx.stats.suppl_paragraphs += 1

        # Items (号)
        for item in para.findall("Item"):
            inum_str = item.get("Num", "")
            try:
                inum = int(inum_str.split("_")[0]) if inum_str else None
            except ValueError:
                inum = None
            if inum is None:
                ctx.stats.skipped += 1
                continue
            item_id = make_article_key(
                law_id=ctx.law_id, art_path=art_path, paragraph_num=pnum,
                item_num=inum, section=section, suppl_tag=suppl_tag,
            )
            if item_id in ctx.seen:
                ctx.stats.dup_ids += 1
                continue
            ctx.seen.add(item_id)
            ctx.records.append(ParsedRecord(
                id=item_id,
                type="Item",
                title=f"{node_title} 第{inum}号",
                text=_item_text(item),
                law_id=ctx.law_id,
                parent_id=para_id,
                article_path=art_path,
                paragraph_num=pnum,
                item_num=inum,
                suppl_tag=suppl_tag,
                section=section,
                raw_attributes={"mst_id": ctx.mst_id, "law_title": ctx.law_title},
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
            t = elem.findtext(tag)
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
        att_id = make_attachment_key(ctx.law_id, annex_slug)
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
        t = elem.findtext(tag)
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


def _slugify_annex_id(raw: str) -> str:
    """Convert annex identifier to a safe slug for IDs.

    Strips kanji/non-alphanumeric, leaving digits/letters/hyphens.
    Falls back to kanji-to-int extraction if no digits.
    """
    s = re.sub(r"[^\w]", "-", raw, flags=re.UNICODE)
    s = re.sub(r"-+", "-", s).strip("-")
    # Pull a leading number if possible
    m = re.search(r"\d+", s)
    if m:
        # Compose: leading number + any following hyphenated digits
        nums = re.findall(r"\d+", s)
        if nums:
            return "-".join(nums)
    # Fallback: kanji number extraction
    n = kanji_to_int(raw.replace("第", "").replace("号", "").replace("表", "").strip())
    if n is not None:
        return str(n)
    # Last resort: ascii-only chars
    ascii_safe = re.sub(r"[^A-Za-z0-9_-]", "", s)
    return ascii_safe


# ---------------------------------------------------------------------------
# CSV-driven XML discovery (unchanged from v1)
# ---------------------------------------------------------------------------
def find_law_xmls(xml_base: Path, csv_fp: Path | None = None) -> Iterator[tuple[str, Path]]:
    """Walk all e-Gov XML directories. Yields (law_name, xml_path) tuples.

    Selects the latest 施行日 per law_id when CSV is provided.
    """
    if csv_fp and csv_fp.exists():
        name_for_id: dict[str, tuple[str, str]] = {}
        with csv_fp.open(encoding="utf-8-sig") as f:
            r = csv.reader(f)
            try:
                next(r)  # header
            except StopIteration:
                pass
            for row in r:
                if len(row) < 13:
                    continue
                name, sehkoubi, law_id = row[2], row[9] or "00000000", row[11]
                if law_id not in name_for_id or sehkoubi > name_for_id[law_id][1]:
                    name_for_id[law_id] = (name, sehkoubi)

        for law_id, (name, _) in name_for_id.items():
            matches = list(xml_base.glob(f"{law_id}_*"))
            for d in matches:
                xml_path = d / f"{d.name}.xml"
                if xml_path.exists():
                    yield (name, xml_path)
                    break
    else:
        # No CSV — pick latest 施行日 per law_id to avoid emitting duplicate
        # nodes across versions. Directory format: {law_id}_{YYYYMMDD}_{amend}.
        latest: dict[str, tuple[str, Path]] = {}
        for d in xml_base.iterdir():
            if not d.is_dir():
                continue
            xml_path = d / f"{d.name}.xml"
            if not xml_path.exists():
                continue
            parts = d.name.split("_")
            law_id = parts[0]
            sehkoubi = parts[1] if len(parts) > 1 else "00000000"
            existing = latest.get(law_id)
            if existing is None or sehkoubi > existing[0]:
                latest[law_id] = (sehkoubi, xml_path)
        for law_id, (_, xml_path) in latest.items():
            yield (law_id, xml_path)
