"""JP article_key normalization (v2.0).

See `docs/GRAPH_SCHEMA_V2.md` §2.2 for the authoritative ID rules.

Supported forms:
    Law node          : {law_id}                                 — uses LAW_ID_RE
    Article           : {law_id}_a{art_path}
    Paragraph         : {law_id}_a{art_path}_p{pnum}
    Item              : {law_id}_a{art_path}_p{pnum}_i{item_path}   (item_path '3' | '12-2')
    SupplArticle      : {law_id}_asup-{tag}-{art_path}
    SupplParagraph    : {law_id}_asup-{tag}-{art_path}_p{pnum}
    Attachment        : {law_id}_at-{annex_id}
    Hierarchy         : {law_id}_h{level_code}{path}             (e.g. P1C2S1)

Examples:
    340AC0000000033_a10              # 第10条 (Article node)
    340AC0000000033_a10_p1           # 第10条第1項 (Paragraph)
    340AC0000000033_a10-2_p3_i2     # 第10条の2 第3項 第2号 (Item)
    340AC0000000033_asup-X-5         # 附則(改正X) 第5条
    340AC0000000033_asup-X-5_p1      # 附則(改正X) 第5条第1項
    340AC0000000033_at-1             # 別表第1
    340AC0000000033_hP1C2            # 第1編 第2章

Legacy v1 suffixes (`_add`, `_attachment`, `_DOC`) remain accepted for
backward compatibility while consumers migrate.
"""
from __future__ import annotations

import re

from ..numerals import kanji_to_int

# v2 article_key regex (covers Article / Paragraph / Item / Suppl* / Attachment / Hierarchy)
# First char after `_a`/`_at-`/`_h` must be alphanumeric to reject garbage like "not_a_key".
ARTICLE_KEY_RE = re.compile(
    r"^[A-Za-z0-9]+"
    r"(?:"
    r"_a[A-Za-z0-9][A-Za-z0-9_-]*(?:_p\d+(?:_i\d+(?:-\d+)*)?)?"  # Article / Paragraph / Item / Suppl*
    r"|_at-[A-Za-z0-9][A-Za-z0-9_-]*"                    # Attachment
    r"|_h[A-Z][A-Za-z0-9_-]*"                            # Hierarchy
    r")"
    r"(?:_add|_attachment|_DOC)?$"                       # legacy suffixes (v1 compat)
)

# JP law_id regex: {era}{type}{seq}
# era: 3 digits (Meiji 001-099, Taisho 100-110, Showa 111-159, Heisei 160-188, Reiwa 189+)
# type: 2-3 char code (AC, CO, DF, IO, DT for letters-only;
#       M50, M51, M0, M1, F0, F1, ... for letter+digit ministerial codes)
LAW_ID_RE = re.compile(r"^[0-9]{3}[A-Z][A-Z0-9][A-Z0-9]?[0-9A-Z]+$")


def article_path_from_num_attr(num_attr: str) -> str | None:
    """e-Gov XML Article@Num attribute → readable art_path.

    '10'      → '10'
    '10_2'    → '10-2'
    '4_3_2'   → '4-3-2'
    'の二'    → '2'

    Returns None if not a valid number form.
    """
    if not num_attr:
        return None
    parts = num_attr.split("_")
    out: list[str] = []
    for p in parts:
        if p.isdigit():
            out.append(p)
            continue
        n = kanji_to_int(p)
        if n is None:
            return None
        out.append(str(n))
    return "-".join(out)


def _suppl_segment(art_path: str, suppl_tag: str | None) -> str:
    tag = suppl_tag or "sp"
    return f"asup-{tag}-{art_path}"


def make_article_key(
    law_id: str,
    art_path: str,
    paragraph_num: int | None = 1,
    item_num: int | str | None = None,
    suffix: str | None = None,
    section: str = "main",
    suppl_tag: str | None = None,
) -> str:
    """Construct an Article / Paragraph / Item key.

    Args:
        law_id: e-Gov 法令番号 (e.g., '340AC0000000033')
        art_path: '10', '10-2', etc.
        paragraph_num: 1-indexed Paragraph 번호. Pass `None` for an Article-level
            node (no `_p` segment, v2.0 신규).
        item_num: 1-indexed Item(号) 번호, or branch path '12-2' (第十二号の二).
            Requires `paragraph_num`. v2.0 신규.
        suffix: legacy v1 suffix ('_add' / '_attachment') — avoid for new code.
        section: 'main' or 'suppl'.
        suppl_tag: when section='suppl', the AmendLawNum tag (≤16 chars).

    Returns:
        e.g.  '340AC0000000033_a10-2'
              '340AC0000000033_a10-2_p3'
              '340AC0000000033_a10-2_p3_i1'
              '340AC0000000033_asup-X-5_p1'
    """
    if section == "suppl":
        art_segment = _suppl_segment(art_path, suppl_tag)
    else:
        art_segment = f"a{art_path}"
    base = f"{law_id}_{art_segment}"
    if paragraph_num is not None:
        base += f"_p{paragraph_num}"
        if item_num is not None:
            base += f"_i{item_num}"
    elif item_num is not None:
        raise ValueError("item_num requires paragraph_num")
    if suffix:
        if not suffix.startswith("_"):
            suffix = "_" + suffix
        base += suffix
    return base


def make_attachment_key(law_id: str, annex_id: str) -> str:
    """別表 / 様式 / 別記 노드 ID. v2.0 신규.

    Args:
        annex_id: e.g. '1', '2-3', or any safe slug. Hyphen/underscore allowed.
    """
    safe = re.sub(r"[^A-Za-z0-9_-]", "-", annex_id)
    if not safe:
        raise ValueError(f"empty annex_id derived from {annex_id!r}")
    return f"{law_id}_at-{safe}"


def make_hierarchy_key(law_id: str, level_path: str) -> str:
    """編/章/節/款 노드 ID. v2.0 신규.

    Args:
        level_path: compact code such as 'P1C2S1' (Part1 Chapter2 Section1).
            Caller is responsible for stable encoding.
    """
    if not level_path or not level_path[0].isupper():
        raise ValueError(f"level_path must start with uppercase code, got {level_path!r}")
    safe = re.sub(r"[^A-Za-z0-9_-]", "", level_path)
    return f"{law_id}_h{safe}"


def parse_article_key(key: str) -> dict:
    """Reverse of make_*_key. Returns dict with kind + parsed components.

    Returned `kind` ∈ {'article', 'paragraph', 'item', 'attachment', 'hierarchy'}.
    For suppl variants `section` == 'suppl' and `suppl_tag` is populated.
    """
    if not ARTICLE_KEY_RE.match(key):
        raise ValueError(f"Invalid JP article_key: {key!r}")

    suffix = None
    for s in ("_add", "_attachment", "_DOC"):
        if key.endswith(s):
            suffix = s.lstrip("_")
            key = key[: -len(s)]
            break

    # Attachment
    m_at = re.match(r"^([A-Za-z0-9]+)_at-(.+)$", key)
    if m_at:
        return {
            "kind": "attachment",
            "law_id": m_at.group(1),
            "annex_id": m_at.group(2),
            "suffix": suffix,
        }

    # Hierarchy
    m_h = re.match(r"^([A-Za-z0-9]+)_h([A-Z][A-Za-z0-9_-]*)$", key)
    if m_h:
        return {
            "kind": "hierarchy",
            "law_id": m_h.group(1),
            "level_path": m_h.group(2),
            "suffix": suffix,
        }

    # Article / Paragraph / Item (incl. Suppl*)
    m = re.match(
        r"^([A-Za-z0-9]+)_a([A-Za-z0-9_-]+?)(?:_p(\d+)(?:_i(\d+))?)?$",
        key,
    )
    if not m:
        raise ValueError(f"Cannot parse JP article_key structure: {key!r}")
    law_id = m.group(1)
    art_seg = m.group(2)
    pnum = int(m.group(3)) if m.group(3) else None
    inum = int(m.group(4)) if m.group(4) else None

    section = "main"
    suppl_tag: str | None = None
    art_path = art_seg
    if art_seg.startswith("sup-"):
        section = "suppl"
        rest = art_seg[len("sup-"):]
        idx = rest.find("-")
        if idx > 0:
            suppl_tag = rest[:idx]
            art_path = rest[idx + 1:]

    if inum is not None:
        kind = "item"
    elif pnum is not None:
        kind = "paragraph"
    else:
        kind = "article"

    return {
        "kind": kind,
        "law_id": law_id,
        "art_path": art_path,
        "paragraph_num": pnum,
        "item_num": inum,
        "section": section,
        "suppl_tag": suppl_tag,
        "suffix": suffix,
    }


def validate_article_key(key: str) -> str:
    """Strict validation. Raises ValueError on failure."""
    if not isinstance(key, str):
        raise ValueError(f"article_key must be str, got {type(key)}")
    # Check Japanese chars first (more informative error)
    if re.search(r"[぀-ゟ゠-ヿ一-鿿]", key):
        raise ValueError(f"article_key must not contain Japanese characters: {key!r}")
    if not ARTICLE_KEY_RE.match(key):
        raise ValueError(f"article_key fails regex: {key!r}")
    return key


def validate_law_id(law_id: str) -> str:
    """Strict validation for Law node IDs."""
    if not isinstance(law_id, str):
        raise ValueError(f"law_id must be str, got {type(law_id)}")
    if not LAW_ID_RE.match(law_id):
        raise ValueError(f"law_id fails regex: {law_id!r}")
    return law_id
