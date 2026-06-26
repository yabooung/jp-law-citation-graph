"""Japanese statutory citation extractor.

Covers:
  - Internal:    第N条 / 第N条の2 / 第N条第M項 / 第N条第M項第K号
  - External:    法令名（promulgation_year法律第Num号）第N条 — also bare 法令名第N条
  - Referential: 前条 / 次条 / 同条 / 同項 / 同号 / 本条 / 本項
  - Range:       第N条から第M条まで
  - Carryover:   NTA kankeihrei (法令名 omission across consecutive items)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .numerals import NUMERAL_RE, kanji_to_int

# ---------- Patterns ----------
_NUM = NUMERAL_RE

INTERNAL_PAT = re.compile(
    rf"第({_NUM})条"
    rf"((?:の{_NUM})*)"
    rf"(?:第({_NUM})項)?"
    rf"(?:第({_NUM})号)?"
)

LAW_NAME_PAT = (
    r"([一-鿿々ヶ぀-ゟ、]{1,40}?"
    r"(?:基本通達|条約|憲法|条例|法律|法|令|規則|通達|告示))"
)

PROM_PAT = (
    r"（"  # full-width left paren (
    r"((?:明治|大正|昭和|平成|令和)[\d一二三四五六七八九十]+年"
    r"(?:法律|政令|省令|府令|規則|条約|勅令)第[\d一二三四五六七八九十百千]+号)"
    r"）"  # full-width right paren )
)

EXTERNAL_FULL_PAT = re.compile(
    rf"{LAW_NAME_PAT}\s*(?:{PROM_PAT})?\s*"
    rf"第({_NUM})条((?:の{_NUM})*)"
    rf"(?:第({_NUM})項)?"
    rf"(?:第({_NUM})号)?"
)

REFERENTIAL_PAT = re.compile(
    r"(前条|次条|同条|同項|同号|本条|本項|前項|次項|前号|前各号|各号"
    r"|同法|同令|同規則|同条例"          # same-law context refs
    r"|新法|旧法|新令|旧令|新規則|旧規則"  # amendment context refs
    r"|本法|本令|本規則)"                  # this-law refs
)

RANGE_PAT = re.compile(
    rf"第({_NUM})条(?:から|乃至)第({_NUM})条まで"
)

ITEM_ONLY_PAT = re.compile(rf"第({_NUM})号")

# ---- 別表 / 様式 (annex/form) reference ----
# Examples: 「別表第1」「別表第二」「別表第1の2」「様式第3号」
ATTACHMENT_REF_PAT = re.compile(
    rf"(別表|様式|別記|附録|目録)第({_NUM})(?:の({_NUM}))?(?:号)?"
)

# ---- delegation (DELEGATES_TO) ----
# Extract delegation expressions to subordinate legislation (政令/省令/府令/規則/命令).
# e.g. 「政令で定める」「主務省令で定める」「内閣府令で定める」.
# Note: the marker alone does not name the delegated law;
# the intent is extracted here; the caller infers the target from the source law family.
DELEGATION_PAT = re.compile(
    r"(政令|内閣府令|主務省令|省令|府令|規則|命令)で定める"
)

# ---- amendment (AMENDS) ----
# Expressions in supplementary provisions that amend the main law's articles.
# 「第N条を次のように改める」「第N条を削る」「第N条の次に次の一条を加える」
AMEND_PAT = re.compile(
    rf"第({_NUM})条((?:の{_NUM})*)"
    rf"(?:第({_NUM})項)?"
    rf"を(?:次のように|削る|加える|改める)"
)


@dataclass
class AttachmentRef:
    """Reference to an Attachment (別表 / 様式)."""
    raw: str
    kind: str         # 別表 / 様式 / 別記 / 附録 / 目録
    annex_num: int    # leading number (e.g. 1 for 別表第1)
    annex_eda: int | None = None  # the '2' in 別表第1の2
    span: tuple[int, int] = (0, 0)

    @property
    def annex_id(self) -> str:
        if self.annex_eda is not None:
            return f"{self.annex_num}-{self.annex_eda}"
        return str(self.annex_num)


@dataclass
class DelegationRef:
    """Delegation marker (caller resolves target law)."""
    raw: str
    target_kind: str  # 政令 / 省令 / 府令 / 規則 / 命令
    span: tuple[int, int] = (0, 0)


@dataclass
class AmendRef:
    """Amendment of a main-law article from a SupplArticle."""
    raw: str
    article_num: int
    eda: list[int] = field(default_factory=list)
    paragraph: int | None = None
    span: tuple[int, int] = (0, 0)


# ---------- Data classes ----------
@dataclass
class IntRef:
    """Internal reference (within current article's law)."""
    raw: str
    article_num: int
    eda: list[int] = field(default_factory=list)
    paragraph: int | None = None
    item: int | None = None
    span: tuple[int, int] = (0, 0)

    @property
    def article_path(self) -> str:
        if self.eda:
            return "-".join([str(self.article_num)] + [str(e) for e in self.eda])
        return str(self.article_num)


@dataclass
class ExtRef:
    """External reference (other law)."""
    raw: str
    law_name_raw: str
    article_num: int
    eda: list[int] = field(default_factory=list)
    paragraph: int | None = None
    item: int | None = None
    promulgation: str | None = None
    span: tuple[int, int] = (0, 0)


@dataclass
class RefRef:
    """Referential (前条 / 次条 / 同条 etc.)."""
    raw: str
    kind: str
    span: tuple[int, int] = (0, 0)


# ---------- Extractors ----------
def parse_eda(eda_str: str) -> list[int]:
    """'の2の3' → [2, 3]. Empty string → []."""
    if not eda_str:
        return []
    parts = re.findall(rf"の({_NUM})", eda_str)
    return [v for p in parts if (v := kanji_to_int(p)) is not None]


# Leading clutter that the law-name regex over-captures. Stripped post-match
# so EXTERNAL_FULL_PAT spans stay accurate (mask spans for internal extraction).
# Prefixes derived from analysis of unresolved-citation samples, where
# fragment over-grab (~16%) + long over-grab (~21%) accounted for ~37% of misses.
# They cover: particle/naked starts (は、/ただし、/が/を/の/に), amendment-clause
# boilerplate (改正規定 etc.), and context adverbs (この場合において/なお/例えば).
_EXT_LAW_NAME_LEADING_NOISE = re.compile(
    r"^(?:"
    # long verb-clause prefixes (top patterns from unresolved samples)
    r"掲げる者が|掲げる者に該当しなくなったとき(?:[、,]|若しくは)?|"
    r"使用者は[、,]?|事業者は[、,]?|発注者は[、,]?|"
    r"既に|現に|これを|これに|これから|"
    r"一項を加える改正規定[、,]?|二項を加える改正規定[、,]?|"
    r"同条の次に一条を加える改正規定[、,]?|"
    r"一条を加える改正規定[、,]?|"
    # supplementary-provision long patterns + clause
    r"この法律の施行の際現に|この法律の施行の際|"
    r"なおその効力を有するものとされる|するものとされた|"
    r"場合には[、,]?|場合に[、,]?|かかわらず[、,]?|"
    r"協会が|"
    # 第N条-anchored prefix + role noun + particle
    r"第[一二三四五六七八九十百千〇0-9]+条第[一二三四五六七八九十0-9]+項において準用する|"
    r"第[一二三四五六七八九十百千〇0-9]+条において準用する|"
    r"第[一二三四五六七八九十百千〇0-9]+条において|"
    r"船舶所有者は[、,]?|厚生労働大臣は[、,]?|"
    r"都道府県知事は[、,]?|市町村長は[、,]?|"
    # more clause prefixes from unresolved analysis
    r"第[一二三四五六七八九十百千〇0-9]+項の規定により[、,]?|"
    r"第[一二三四五六七八九十百千〇0-9]+号の規定により[、,]?|"
    r"に係る[、,]?|係る[、,]?|質問等及び|同条に|改める[、,]?|"
    r"における|に基づく|に対する|"
    r"ついて[、,]?|"
    r"経過措置期間適用月が[一二三四五六七八九十0-9]+月以外の月の場合にあっては[、,]?|"
    # supplementary-provision timing prefix
    r"施行日前にされた|施行日前に|"
    r"平成[一二三四五六七八九十0-9]+年[一二三四五六七八九十0-9]*月?改正前|"
    r"平成[一二三四五六七八九十0-9]+年改正法附則第[一二三四五六七八九十百千〇0-9]+条の規定による改正前の|"
    # 金融サービスの fragment (observed)
    r"金融サービスの|"
    # amendment-clause patterns (longest first for leftmost-match)
    r"の次に一条を加える改正規定[、,]?|の次に[一二三四五六七八九十]+条を加える改正規定[、,]?|"
    r"を加える改正規定[、,]?|これらの規定を|"
    r"改正規定[、,]?|同条を|"
    # context adverbs
    r"この場合において[、,]|なお[、,]?|例えば[、,]?|特に[、,]?|"
    # base patterns
    r"の改正規定[、,]?|において準用する|により準用する|"
    r"とする|とし|の規定により|の規定による|の規定[、,]?|"
    r"準用する|"
    r"又は|及び|並びに|若しくは|と|や|に|から|まで|"
    # particle + naked prefixes
    r"は[、,]|ただし[、,]?|が|を|の|"
    r"による|により|について|に基づき|に従い|に応じて|に係る|"
    r"[、,。\s]+"
    r")+"
)

# Tokens that look like a law-name capture but are actually referential
# (handled by REFERENTIAL_PAT, not as external citation).
_REFERENTIAL_LAWNAME_TOKENS = {
    "同法", "同令", "同規則", "同条例",
    "新法", "旧法", "新令", "旧令", "新規則", "旧規則",
    "本法", "本令", "本規則",
    "前法", "次法",
    # "新+parent-law" forms surfacing as captured law name end with these — handled
    # downstream by prefix stripping in LawNameIndex.
}


def extract_external(text: str) -> tuple[list[ExtRef], list[tuple[int, int]]]:
    """Returns (refs, spans_consumed).

    EXTERNAL_FULL_PAT groups: 1=law_name, 2=prom (inside ()), 3=art, 4=eda, 5=para, 6=item

    Cleans `law_name_raw` by stripping leading clutter (`の改正規定、`,
    `又は`, etc.) post-match. Drops captures whose law_name reduces to a
    pure referential token (`同法`, `新法`, …) — those are handled by
    extract_referential.
    """
    refs: list[ExtRef] = []
    spans: list[tuple[int, int]] = []
    for m in EXTERNAL_FULL_PAT.finditer(text):
        law_name = _EXT_LAW_NAME_LEADING_NOISE.sub("", m.group(1)).strip()
        if not law_name or law_name in _REFERENTIAL_LAWNAME_TOKENS:
            # Don't double-count as external; let referential extractor handle.
            continue
        prom = m.group(2)
        art = m.group(3)
        eda = m.group(4)
        para = m.group(5)
        item = m.group(6)
        art_n = kanji_to_int(art) if art else None
        if art_n is None:
            continue
        refs.append(ExtRef(
            raw=m.group(0),
            law_name_raw=law_name,
            article_num=art_n,
            eda=parse_eda(eda),
            paragraph=kanji_to_int(para) if para else None,
            item=kanji_to_int(item) if item else None,
            promulgation=prom,
            span=(m.start(), m.end()),
        ))
        spans.append((m.start(), m.end()))
    return refs, spans


# Local abbreviation definitions: '<pre>（(以下)?「<label>」という。）' / 'と総称する'.
# Used to resolve law-specific anaphora (新法/旧法/平成N年旧法) and ad-hoc abbreviations
# (e.g. 組織的犯罪処罰法) that only make sense within the defining law.
LOCAL_DEF_PAT = re.compile(
    r"(.{0,50}?)（(?:以下)?[「『]([^」』]{1,20})[」』](?:という|と総称する)"
)
_DEF_LABEL_SUFFIX = ("法律", "法", "令", "規則", "条例", "条約")


def extract_local_definitions(text: str) -> list[tuple[str, str]]:
    """Find local abbreviation definitions in `text`.

    Returns [(label, preceding_text)] for each '（以下「label」という。）' whose
    label looks like a law name (ends in a law-suffix token). The caller
    resolves the antecedent law from `preceding_text` (usually
    '…(この法律による)改正(後|前)の<法令名>') and maps label → law_id, scoped to
    the law the definition appears in.
    """
    out: list[tuple[str, str]] = []
    for m in LOCAL_DEF_PAT.finditer(text):
        label = m.group(2)
        if label.endswith(_DEF_LABEL_SUFFIX):
            out.append((label, m.group(1)))
    return out


def extract_internal(text: str, mask_spans: list[tuple[int, int]] | None = None) -> list[IntRef]:
    """Internal refs, excluding those within external spans."""
    mask_spans = mask_spans or []

    def in_mask(pos: int) -> bool:
        return any(s <= pos < e for s, e in mask_spans)

    refs: list[IntRef] = []
    for m in INTERNAL_PAT.finditer(text):
        if in_mask(m.start()):
            continue
        art = kanji_to_int(m.group(1))
        if art is None:
            continue
        refs.append(IntRef(
            raw=m.group(0),
            article_num=art,
            eda=parse_eda(m.group(2)),
            paragraph=kanji_to_int(m.group(3)) if m.group(3) else None,
            item=kanji_to_int(m.group(4)) if m.group(4) else None,
            span=(m.start(), m.end()),
        ))
    return refs


def extract_referential(text: str, mask_spans: list[tuple[int, int]] | None = None) -> list[RefRef]:
    mask_spans = mask_spans or []

    def in_mask(pos: int) -> bool:
        return any(s <= pos < e for s, e in mask_spans)

    out: list[RefRef] = []
    for m in REFERENTIAL_PAT.finditer(text):
        if in_mask(m.start()):
            continue
        out.append(RefRef(raw=m.group(0), kind=m.group(1), span=(m.start(), m.end())))
    return out


def extract_attachment_refs(
    text: str,
    mask_spans: list[tuple[int, int]] | None = None,
) -> list[AttachmentRef]:
    """別表/様式/別記 references → AttachmentRef list."""
    mask_spans = mask_spans or []

    def in_mask(pos: int) -> bool:
        return any(s <= pos < e for s, e in mask_spans)

    out: list[AttachmentRef] = []
    for m in ATTACHMENT_REF_PAT.finditer(text):
        if in_mask(m.start()):
            continue
        n = kanji_to_int(m.group(2))
        if n is None:
            continue
        eda = kanji_to_int(m.group(3)) if m.group(3) else None
        out.append(AttachmentRef(
            raw=m.group(0),
            kind=m.group(1),
            annex_num=n,
            annex_eda=eda,
            span=(m.start(), m.end()),
        ))
    return out


def extract_delegations(
    text: str,
    mask_spans: list[tuple[int, int]] | None = None,
) -> list[DelegationRef]:
    """Find delegation markers (e.g. '政令で定める'). Caller resolves the target law."""
    mask_spans = mask_spans or []

    def in_mask(pos: int) -> bool:
        return any(s <= pos < e for s, e in mask_spans)

    out: list[DelegationRef] = []
    for m in DELEGATION_PAT.finditer(text):
        if in_mask(m.start()):
            continue
        out.append(DelegationRef(
            raw=m.group(0),
            target_kind=m.group(1),
            span=(m.start(), m.end()),
        ))
    return out


def extract_amendments(text: str) -> list[AmendRef]:
    """Detect amendment refs in SupplArticle text (e.g. '第N条を…改める')."""
    out: list[AmendRef] = []
    for m in AMEND_PAT.finditer(text):
        n = kanji_to_int(m.group(1))
        if n is None:
            continue
        out.append(AmendRef(
            raw=m.group(0),
            article_num=n,
            eda=parse_eda(m.group(2)),
            paragraph=kanji_to_int(m.group(3)) if m.group(3) else None,
            span=(m.start(), m.end()),
        ))
    return out


def extract_all(text: str) -> dict:
    """Convenience: extract all reference types from text."""
    ext, spans = extract_external(text)
    internal = extract_internal(text, mask_spans=spans)
    refer = extract_referential(text, mask_spans=spans)
    return {
        "external": ext,
        "internal": internal,
        "referential": refer,
    }


# ---------- NTA kankeihrei parser (gold extractor) ----------
def parse_kankeihrei(items: list[str]) -> list[dict]:
    """Parse NTA shitsugi kankeihrei items into structured refs.

    Handles carryover: '所得税法施行令第14条' → '第15条' inherits 所得税法施行令.
    Returns list of {law_name, article_num, eda, paragraph, item, raw, carryover, ...}.
    """
    TUTATSU_NUM = re.compile(r"^(\d+)\s*[-‐−]\s*(\d+)(?:\s*[-‐−]\s*(\d+))?")
    PARA_ONLY = re.compile(rf"^第({_NUM})項")
    ITEM_ONLY = re.compile(rf"^第({_NUM})号")
    SUPPL_ART = re.compile(rf"^附則第({_NUM})条")

    out: list[dict] = []
    last_law: str | None = None
    last_article: int | None = None

    for raw in items:
        s = raw.strip()
        if not s:
            continue

        # 通達 sub-section like "2-1"
        m_tu = TUTATSU_NUM.match(s)
        if m_tu and last_law and "通達" in last_law:
            out.append({
                "raw": s, "law_name": last_law, "article_num": None,
                "tutatsu_section": s, "carryover": True,
                "type": "circular_or_misc",
            })
            continue

        # 附則第N条
        m_sp = SUPPL_ART.match(s)
        if m_sp and last_law:
            art_n = kanji_to_int(m_sp.group(1))
            out.append({
                "raw": s, "law_name": last_law, "article_num": art_n,
                "section": "suppl", "carryover": True,
            })
            last_article = art_n
            continue

        # External (law name + 第N条)
        m = EXTERNAL_FULL_PAT.search(s)
        if m and m.start() == 0:
            law_name = m.group(1)
            art = m.group(3)
            eda = m.group(4)
            para = m.group(5)
            item = m.group(6)
            last_law = law_name
            art_n = kanji_to_int(art) if art else None
            last_article = art_n
            out.append({
                "raw": s, "law_name": law_name, "article_num": art_n,
                "eda": parse_eda(eda),
                "paragraph": kanji_to_int(para) if para else None,
                "item": kanji_to_int(item) if item else None,
                "carryover": False,
            })
            continue

        # Carryover: 第N条 (no law name) → inherit last_law
        m2 = INTERNAL_PAT.match(s)
        if m2 and last_law:
            art_n = kanji_to_int(m2.group(1))
            last_article = art_n
            out.append({
                "raw": s, "law_name": last_law, "article_num": art_n,
                "eda": parse_eda(m2.group(2)),
                "paragraph": kanji_to_int(m2.group(3)) if m2.group(3) else None,
                "item": kanji_to_int(m2.group(4)) if m2.group(4) else None,
                "carryover": True,
            })
            continue

        # Paragraph-only: 第N項 → inherit last_law + last_article
        m_pa = PARA_ONLY.match(s)
        if m_pa and last_law and last_article:
            out.append({
                "raw": s, "law_name": last_law, "article_num": last_article,
                "paragraph": kanji_to_int(m_pa.group(1)), "carryover": True,
            })
            continue

        # Item-only: 第N号
        m_it = ITEM_ONLY.match(s)
        if m_it and last_law and last_article:
            out.append({
                "raw": s, "law_name": last_law, "article_num": last_article,
                "item": kanji_to_int(m_it.group(1)), "carryover": True,
            })
            continue

        # 通達 / 基本通達 / その他 — record law only
        m3 = re.match(LAW_NAME_PAT + r"\s*(\S*)", s)
        if m3:
            if "通達" in m3.group(1):
                last_law = m3.group(1)
            out.append({
                "raw": s, "law_name": m3.group(1), "article_num": None,
                "ref_text": m3.group(2), "carryover": False,
                "type": "circular_or_misc",
            })
            continue

        out.append({"raw": s, "parse_error": True})

    return out
